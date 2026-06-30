"""Trace read use-cases exposed to the API: page a prompt's executions, fetch one in full.

The read counterpart to the ingest path. The UI's debugging surface (Sprint 24) needs to browse
recent executions and drill into a single one; this service turns the request's *names* (prompt
name, version number) into the ids the :class:`TraceRepository` filters on, and raises the same
``PromptNotFoundError`` / ``VersionNotFoundError`` the rest of the registry uses (mapped to 404).

Speaks plain arguments and ORM entities, never Pydantic (ADR 0003) — the router maps to DTOs.
"""

from __future__ import annotations

import uuid

from promptforge_api.db.models import Prompt, PromptVersion
from promptforge_api.db.trace_models import Trace
from promptforge_api.exceptions import (
    PromptNotFoundError,
    TraceNotFoundError,
    VersionNotFoundError,
)
from promptforge_api.repositories.prompts import PromptRepository
from promptforge_api.repositories.traces import TraceRepository

# Traces are the fastest-growing table, so the list always pages. A sane default page size and a
# hard cap keep a caller from pulling the whole table in one request.
DEFAULT_TRACE_PAGE_SIZE = 50
MAX_TRACE_PAGE_SIZE = 200


class TraceService:
    """Read access to traces: a paged, optionally-scoped list and a single full trace."""

    def __init__(self, trace_repo: TraceRepository, prompt_repo: PromptRepository) -> None:
        self._traces = trace_repo
        self._prompts = prompt_repo

    def list_traces(
        self,
        *,
        prompt_name: str | None = None,
        version_number: int | None = None,
        limit: int = DEFAULT_TRACE_PAGE_SIZE,
        offset: int = 0,
    ) -> list[Trace]:
        """A page of traces, newest first, optionally scoped to a prompt and/or one of its versions.

        ``prompt_name`` resolves to the ``prompt_id`` filter; ``version_number`` (only meaningful
        with a prompt) further scopes to that version. Unknown prompt/version → 404 (so a stale link
        fails loudly rather than silently listing everything).
        """
        prompt_id: uuid.UUID | None = None
        prompt_version_id: uuid.UUID | None = None
        if prompt_name is not None:
            prompt = self._require_prompt(prompt_name)
            prompt_id = prompt.id
            if version_number is not None:
                prompt_version_id = self._require_version(prompt, prompt_name, version_number).id

        return self._traces.list_traces(
            prompt_id=prompt_id,
            prompt_version_id=prompt_version_id,
            limit=limit,
            offset=offset,
        )

    def get_trace(self, trace_id: uuid.UUID) -> Trace:
        """Fetch one trace in full (rendered input + output), or fail with a 404-mapped error."""
        trace = self._traces.get(trace_id)
        if trace is None:
            raise TraceNotFoundError(trace_id)
        return trace

    def _require_prompt(self, name: str) -> Prompt:
        prompt = self._prompts.get_by_name(name)
        if prompt is None:
            raise PromptNotFoundError(name)
        return prompt

    @staticmethod
    def _require_version(prompt: Prompt, name: str, version_number: int) -> PromptVersion:
        version = next((v for v in prompt.versions if v.version_number == version_number), None)
        if version is None:
            raise VersionNotFoundError(name, version_number)
        return version
