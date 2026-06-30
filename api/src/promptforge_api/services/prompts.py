"""Prompt business logic.

The service speaks plain arguments and ORM entities — never Pydantic — so the
domain stays independent of the HTTP boundary (ADR 0003 / CLAUDE.md). For now the
ORM model doubles as the domain entity (the agreed two-layer choice); when a
method here grows real domain logic worth isolating from persistence (e.g. the
promotion rules in a later sprint), that's the trigger to introduce a dataclass
domain layer.

This module owns the registry's *rules*: versions are immutable and appended in a
linear chain (ADR 0005); a version's declared variables must match its template
exactly (ADR 0004); rendering fails loudly on any variable mismatch.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import structlog
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from promptforge_api.cache import Cache, CacheStats, CacheStatsSnapshot, NullCache
from promptforge_api.composition.builder import BlockRef, PinnedComposition, pin_composition
from promptforge_api.composition.resolver import resolve
from promptforge_api.db.models import Label, Prompt, PromptVersion
from promptforge_api.exceptions import PromptNotFoundError, VersionNotFoundError
from promptforge_api.repositories.composition import CompositionRepository
from promptforge_api.repositories.prompts import PromptRepository, PromptSummary
from promptforge_api.services.promotion import (
    GateAllowed,
    PromotionGate,
    PromotionPromoted,
    PromotionResult,
)
from promptforge_api.services.scans import ScanService
from promptforge_api.templating import check_variable_contract, render_template

# Re-exported from the neutral exceptions module so existing imports
# (`from promptforge_api.services.prompts import PromptNotFoundError`) keep working while the
# eval/promotion services can raise the same errors without an import cycle (see exceptions.py).
__all__ = ["PromptNotFoundError", "VersionNotFoundError"]

# Cache outcomes are logged here (not in the cache adapter) so the line carries the
# request's correlation id (threaded via contextvars) and the prompt/label context —
# making the server-side cache hit rate observable by grepping/aggregating these events.
_logger = structlog.get_logger(__name__)


class PromptAlreadyExistsError(Exception):
    """Raised when creating a prompt whose name is already taken."""

    def __init__(self, name: str) -> None:
        super().__init__(f"prompt '{name}' already exists")
        self.name = name


class LabelNotFoundError(Exception):
    """Raised when a prompt has no label with the requested name."""

    def __init__(self, name: str, label: str) -> None:
        super().__init__(f"prompt '{name}' has no label '{label}'")
        self.name = name
        self.label = label


class InvalidOutputSchemaError(Exception):
    """Raised when a supplied output_schema is not a valid JSON Schema."""

    def __init__(self, message: str) -> None:
        super().__init__(f"output_schema is not a valid JSON Schema: {message}")


class RenderVariableError(Exception):
    """Raised when render is given the wrong set of variables (missing/unexpected)."""

    def __init__(self, missing: set[str], unexpected: set[str]) -> None:
        parts: list[str] = []
        if missing:
            parts.append(f"missing variables: {sorted(missing)}")
        if unexpected:
            parts.append(f"unexpected variables: {sorted(unexpected)}")
        super().__init__("; ".join(parts))
        self.missing = missing
        self.unexpected = unexpected


@dataclass(frozen=True)
class RenderedPrompt:
    """The result of rendering a version: finished text + the version's metadata.

    Carries the *identity* of the version it came from (``prompt_id`` /
    ``prompt_version_id`` / ``version_number``) so a caller that runs this prompt can
    attribute the resulting trace back to the exact version — the linkage the Phase 7
    observability story (cost/latency/quality per version) is built on.
    """

    prompt: str
    model_settings: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    prompt_id: uuid.UUID
    prompt_version_id: uuid.UUID
    version_number: int


class PromptService:
    """Use-cases for prompts: create, version, read history, label, and render."""

    def __init__(
        self,
        repository: PromptRepository,
        cache: Cache | None = None,
        *,
        composition: CompositionRepository | None = None,
        gate: PromotionGate | None = None,
        scans: ScanService | None = None,
        cache_ttl_seconds: int = 30,
        cache_stats: CacheStats | None = None,
    ) -> None:
        self._repository = repository
        # Default to a no-op cache so a service built without one (or in a unit test)
        # behaves exactly as before — straight to the repository.
        self._cache: Cache = cache if cache is not None else NullCache()
        # Render-cache hit/miss recorder (Sprint 29 T4). Defaults to a private, throwaway instance
        # so a service built without one still records harmlessly; the router injects the shared
        # process-wide recorder so the read endpoint sees the same counts.
        self._cache_stats: CacheStats = cache_stats if cache_stats is not None else CacheStats()
        # Composition is optional: a service built without it serves plain prompts and
        # rejects any request that carries block references (a misconfiguration).
        self._composition = composition
        # The promotion gate is optional too: without it, label moves are unguarded and new
        # versions aren't auto-evaluated (the pre-Sprint-11 behaviour every existing test relies
        # on). With it, the gated label is quality-gated and version-create triggers an eval.
        self._gate = gate
        # Scanning is optional in the same way: with it, every version-create triggers a security
        # scan (Sprint 12). Unconditional — unlike the eval gate, scanning needs no golden set.
        self._scans = scans
        self._cache_ttl_seconds = cache_ttl_seconds

    # ----------------------------------------------------------------- create
    def create_prompt(
        self,
        *,
        name: str,
        description: str | None,
        content: str,
        input_variables: list[str],
        model_settings: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        blocks: list[BlockRef] | None = None,
    ) -> Prompt:
        """Create a prompt and its immutable version 1 in one transaction."""
        if self._repository.get_by_name(name) is not None:
            raise PromptAlreadyExistsError(name)

        pinned = self._pin(blocks)
        self._validate_version(content, input_variables, output_schema, pinned)

        prompt = Prompt(name=name, description=description)
        # version_number starts at 1; parent is None — this is the root of the
        # lineage. The cascade on Prompt.versions inserts this with the prompt.
        version = PromptVersion(
            version_number=1,
            content=content,
            input_variables=input_variables,
            model_settings=model_settings,
            output_schema=output_schema,
        )
        prompt.versions.append(version)
        self._repository.add(prompt)
        self._repository.flush()
        # The version now has an id; pin its composition edges (a no-op if uncomposed).
        self._persist_prompt_blocks(version.id, pinned)
        # A brand-new prompt has no golden set yet, so this is a no-op today; kept for symmetry
        # with add_version (and in case create ever accepts a golden-set reference).
        if self._gate is not None:
            self._gate.trigger_on_create(prompt, version)
        # Scan-on-save: unconditional (no golden-set precondition), so even a first version is
        # checked for injection/secrets/PII/jailbreaks before it can ever be promoted.
        if self._scans is not None:
            self._scans.trigger_on_create(prompt, version)
        return self._require_prompt(name)

    def add_version(
        self,
        *,
        name: str,
        content: str,
        input_variables: list[str],
        model_settings: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        blocks: list[BlockRef] | None = None,
    ) -> PromptVersion:
        """Append the next immutable version to an existing prompt (ADR 0005)."""
        prompt = self._require_prompt(name)
        pinned = self._pin(blocks)
        self._validate_version(content, input_variables, output_schema, pinned)

        # versions are loaded ordered by version_number, so the last is the latest.
        latest = prompt.versions[-1]
        version = PromptVersion(
            version_number=latest.version_number + 1,
            parent_version_id=latest.id,
            content=content,
            input_variables=input_variables,
            model_settings=model_settings,
            output_schema=output_schema,
        )
        # Append through the relationship (not a raw prompt_id) so the in-memory
        # aggregate stays consistent and the cascade inserts the row; flush
        # populates server defaults (created_at) via RETURNING.
        prompt.versions.append(version)
        self._repository.flush()
        self._persist_prompt_blocks(version.id, pinned)
        # Eager eval: if the prompt has a golden set, kick off this version's gating eval now so
        # its verdict usually exists by the time anyone tries to promote it (no-op otherwise).
        if self._gate is not None:
            self._gate.trigger_on_create(prompt, version)
        # Eager scan: kick off this version's security scan now (always — no golden set needed).
        if self._scans is not None:
            self._scans.trigger_on_create(prompt, version)
        return version

    # ------------------------------------------------------------------- read
    def list_prompts(self) -> list[PromptSummary]:
        """Return all prompts as lightweight summaries (name-ordered) for the list view."""
        return self._repository.list_summaries()

    def get_prompt(self, name: str) -> Prompt | None:
        """Return a prompt with its versions, or ``None`` if it doesn't exist."""
        return self._repository.get_by_name(name)

    def version_block_refs(
        self, version_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[tuple[str, int]]]:
        """Pinned (block name, version) refs per version id, so reads can expose composition.

        Empty when no composition repo is wired (a service serving plain prompts).
        """
        if self._composition is None:
            return {}
        return self._composition.block_refs_for_prompt_versions(version_ids)

    def list_versions(self, name: str) -> list[PromptVersion]:
        """Return a prompt's version history, oldest first."""
        return list(self._require_prompt(name).versions)

    def get_version(self, name: str, version_number: int) -> PromptVersion:
        """Fetch one version of a prompt by its number."""
        return self._require_version(name, version_number)

    # ----------------------------------------------------------------- labels
    def set_label(
        self, *, name: str, label: str, version_number: int, actor: str = "system"
    ) -> PromotionResult:
        """Point a label at a version (creating or moving it). Moving = deploy.

        For the gate's protected label the move is **quality-gated** (Sprint 11): the candidate
        must have a completed eval that clears the floor and doesn't regress against the current
        production version, or the move is refused with the failing scores. Every other label
        moves freely, as before. Returns a :class:`PromotionResult` the router maps to 200
        (promoted) or 409 (blocked / eval pending).
        """
        prompt = self._require_prompt(name)
        candidate = self._find_version(prompt, version_number)
        if candidate is None:
            raise VersionNotFoundError(name, version_number)

        existing = self._repository.get_label(prompt.id, label)
        # Captured before the move: the version production points at *now* is both the audit's
        # "from" and the baseline the candidate is compared against.
        current_version = existing.version if existing is not None else None

        detail: dict[str, Any] | None = None
        gated = self._gate is not None and label == self._gate.gated_label
        if gated:
            assert self._gate is not None
            outcome = self._gate.evaluate(
                prompt=prompt,
                candidate=candidate,
                current_version=current_version,
                label=label,
                actor=actor,
            )
            if not isinstance(outcome, GateAllowed):
                # Blocked or pending: the gate already recorded the audit + fired the webhook.
                # Return (don't raise) so those writes commit and the router can send a 409.
                return outcome
            detail = outcome.detail

        moved = self._apply_label(prompt, existing, label, candidate)
        if gated:
            assert self._gate is not None
            self._gate.record_promotion(
                prompt=prompt,
                candidate=candidate,
                previous=current_version,
                label=label,
                actor=actor,
                detail=detail,
            )
        return PromotionPromoted(label=moved, detail=detail)

    def _apply_label(
        self, prompt: Prompt, existing: Label | None, label: str, version: PromptVersion
    ) -> Label:
        """Create the label or re-point it at *version* — the deploy primitive."""
        if existing is not None:
            # Assign through the relationship so the FK *and* the in-memory
            # .version both move — re-pointing a label is the deploy primitive.
            existing.version = version
            self._repository.flush()
            return existing

        new_label = Label(prompt_id=prompt.id, name=label, version=version)
        self._repository.add_label(new_label)
        self._repository.flush()
        return new_label

    def resolve_label(self, name: str, label: str) -> PromptVersion:
        """Return the version a label currently points at."""
        prompt = self._require_prompt(name)
        found = self._repository.get_label(prompt.id, label)
        if found is None:
            raise LabelNotFoundError(name, label)
        return found.version

    # ----------------------------------------------------------------- render
    def render(
        self, *, name: str, version_number: int, variables: dict[str, str]
    ) -> RenderedPrompt:
        """Fill a version's template with *variables*, failing loudly on mismatch."""
        return self._render(self._require_version(name, version_number), variables)

    def render_by_label(
        self, *, name: str, label: str, variables: dict[str, str]
    ) -> RenderedPrompt:
        """Resolve a label to its version, then render it — the SDK's single call.

        Floating fetch (see the pinned-vs-floating ADR): callers ask for a label
        ('production') and always get whatever version it currently points at, so a
        deploy (re-pointing the label) is picked up without the caller changing.

        Read-through cached: a hot ``(name, label, variables)`` is served from the cache
        within the TTL, skipping the DB. A hit only ever returns a value that previously
        rendered successfully, so the variable contract is still effectively enforced —
        a never-seen, invalid variable set misses and fails loudly in ``_render``.
        """
        key = _render_cache_key(name, label, variables)
        cached = self._cache.get(key)
        if cached is not None:
            _logger.info("render_cache", outcome="hit", prompt=name, label=label)
            self._cache_stats.record(name, hit=True)
            return _rendered_from_json(cached)

        _logger.info("render_cache", outcome="miss", prompt=name, label=label)
        # Resolve + render *before* counting the miss: only tally one once we know this was a real,
        # served prompt. Recording earlier would count misses for unknown prompts (growing the
        # per-prompt dict on a request-controlled name) and for renders that fail variable
        # validation (depressing the hit-rate this signal reports). The hit path above is safe to
        # count eagerly — a cache hit only ever holds a value that previously rendered successfully.
        rendered = self._render(self.resolve_label(name, label), variables)
        self._cache_stats.record(name, hit=False)
        self._cache.set(key, _rendered_to_json(rendered), ttl_seconds=self._cache_ttl_seconds)
        return rendered

    def render_cache_stats(self, name: str) -> CacheStatsSnapshot:
        """Cumulative render-cache hit/miss counts for *name* (404 if the prompt doesn't exist)."""
        self._require_prompt(name)
        return self._cache_stats.snapshot(name)

    def _render(self, version: PromptVersion, variables: dict[str, str]) -> RenderedPrompt:
        """Fill one version's template, enforcing the render-variable contract.

        For a composed version, ``input_variables`` is the full union (own + inherited
        block variables), so the same provided-equals-declared check enforces that the
        caller supplies everything the composition needs.
        """
        declared = set(version.input_variables)
        provided = set(variables)
        missing = declared - provided
        unexpected = provided - declared
        if missing or unexpected:
            raise RenderVariableError(missing, unexpected)

        return RenderedPrompt(
            prompt=self._compose(version, variables),
            model_settings=version.model_settings,
            output_schema=version.output_schema,
            prompt_id=version.prompt_id,
            prompt_version_id=version.id,
            version_number=version.version_number,
        )

    def _compose(self, version: PromptVersion, variables: dict[str, str]) -> str:
        """Resolve a version's composition into finished text (plain render if uncomposed)."""
        if self._composition is None:
            return render_template(version.content, variables)
        top_blocks = self._composition.get_prompt_top_block_ids(version.id)
        if not top_blocks:
            return render_template(version.content, variables)
        subgraph = self._composition.load_block_subgraph(top_blocks)
        return resolve(version.content, top_blocks, subgraph, variables)

    # ----------------------------------------------------------------- shared
    def _pin(self, blocks: list[BlockRef] | None) -> PinnedComposition | None:
        """Resolve block references to a pinned composition, or ``None`` if uncomposed."""
        if not blocks:
            return None
        if self._composition is None:
            raise RuntimeError("composition repository not configured")
        return pin_composition(self._composition, blocks)

    def _persist_prompt_blocks(
        self, prompt_version_id: uuid.UUID, pinned: PinnedComposition | None
    ) -> None:
        """Write the prompt→block edges in position order (no-op when uncomposed)."""
        if pinned is None:
            return
        assert self._composition is not None  # guaranteed when pinned is not None
        for position, block_version_id in enumerate(pinned.block_version_ids):
            self._composition.add_prompt_block(prompt_version_id, block_version_id, position)
        self._repository.flush()

    def _validate_version(
        self,
        content: str,
        input_variables: list[str],
        output_schema: dict[str, Any] | None,
        pinned: PinnedComposition | None = None,
    ) -> None:
        """Enforce the variable contract (ADR 0004) and JSON-Schema validity.

        When composed, the contract widens: the declared variables must equal the union of
        the prompt's own placeholders and the variables inherited from its blocks.
        """
        inherited = pinned.inherited_variables if pinned is not None else ()
        check_variable_contract(content, input_variables, extra_required=inherited)

        if output_schema is not None:
            try:
                Draft202012Validator.check_schema(output_schema)
            except SchemaError as exc:
                raise InvalidOutputSchemaError(exc.message) from exc

    def _require_prompt(self, name: str) -> Prompt:
        prompt = self._repository.get_by_name(name)
        if prompt is None:
            raise PromptNotFoundError(name)
        return prompt

    def _require_version(self, name: str, version_number: int) -> PromptVersion:
        version = self._find_version(self._require_prompt(name), version_number)
        if version is None:
            raise VersionNotFoundError(name, version_number)
        return version

    @staticmethod
    def _find_version(prompt: Prompt, version_number: int) -> PromptVersion | None:
        return next((v for v in prompt.versions if v.version_number == version_number), None)


def _render_cache_key(name: str, label: str, variables: dict[str, str]) -> str:
    """Build a stable cache key for one render-by-label request.

    Variables are canonicalised (sorted keys) and hashed so the key has a bounded length
    and is independent of dict ordering. The ``v1`` segment lets the cached value's shape
    change later without colliding with stale entries. ``name`` and ``label`` are
    URL-quoted so a label containing the ``:`` separator can't make two different
    (name, label) pairs map to the same key string.
    """
    canonical = json.dumps(variables, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"render:v1:{quote(name, safe='')}:{quote(label, safe='')}:{digest}"


def _rendered_to_json(rendered: RenderedPrompt) -> str:
    """Serialise a rendered prompt for the cache (the same shape the API returns).

    The version identity is stored too (UUIDs as strings), so a cache *hit* returns a
    fully-linked ``RenderedPrompt`` — a cached render must not lose the version it came
    from, or traces from cached fetches couldn't be attributed.
    """
    return json.dumps(
        {
            "prompt": rendered.prompt,
            "model_settings": rendered.model_settings,
            "output_schema": rendered.output_schema,
            "prompt_id": str(rendered.prompt_id),
            "prompt_version_id": str(rendered.prompt_version_id),
            "version_number": rendered.version_number,
        }
    )


def _rendered_from_json(payload: str) -> RenderedPrompt:
    """Rebuild a rendered prompt from its cached JSON."""
    data = json.loads(payload)
    return RenderedPrompt(
        prompt=data["prompt"],
        model_settings=data["model_settings"],
        output_schema=data["output_schema"],
        prompt_id=uuid.UUID(data["prompt_id"]),
        prompt_version_id=uuid.UUID(data["prompt_version_id"]),
        version_number=data["version_number"],
    )
