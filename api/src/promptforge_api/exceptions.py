"""Shared domain exceptions, in one neutral module that imports no service code.

Several services raise the same registry/eval errors, and the layering would otherwise
cycle — the eval and promotion services raise ``PromptNotFoundError`` while the prompt
service depends on the promotion gate. Housing the cross-cut exceptions here lets every
service import them without an import cycle. The HTTP status mapping for all of them
lives in :mod:`promptforge_api.errors`. ``services.prompts`` re-exports the registry
ones so existing imports keep working.
"""

from __future__ import annotations

import uuid


class PromptNotFoundError(Exception):
    """Raised when a named prompt does not exist."""

    def __init__(self, name: str) -> None:
        super().__init__(f"prompt '{name}' not found")
        self.name = name


class VersionNotFoundError(Exception):
    """Raised when a prompt has no version with the requested number."""

    def __init__(self, name: str, version_number: int) -> None:
        super().__init__(f"prompt '{name}' has no version {version_number}")
        self.name = name
        self.version_number = version_number


class TraceNotFoundError(Exception):
    """Raised when a trace with the requested id does not exist."""

    def __init__(self, trace_id: uuid.UUID) -> None:
        super().__init__(f"trace '{trace_id}' not found")
        self.trace_id = trace_id


class DatasetAlreadyExistsError(Exception):
    """Raised when creating a dataset whose name is already taken."""

    def __init__(self, name: str) -> None:
        super().__init__(f"dataset '{name}' already exists")
        self.name = name


class DatasetNotFoundError(Exception):
    """Raised when a named dataset does not exist."""

    def __init__(self, name: str) -> None:
        super().__init__(f"dataset '{name}' not found")
        self.name = name


class DatasetInUseError(Exception):
    """Raised when deleting a dataset that one or more prompts still use as their golden set.

    We refuse the delete rather than silently null out the references (ADR 0024): dropping a
    prompt's golden set out from under it would quietly remove its promotion gate. The caller
    must detach the set from each prompt first; the offending prompt names are carried so the
    UI can tell the user exactly what to fix.
    """

    def __init__(self, name: str, prompt_names: list[str]) -> None:
        joined = ", ".join(prompt_names)
        super().__init__(
            f"dataset '{name}' is in use as a golden set by: {joined}; "
            "detach it from those prompts before deleting"
        )
        self.name = name
        self.prompt_names = prompt_names


class EmptyGoldenSetError(Exception):
    """Raised when attaching a dataset with no items as a prompt's golden set.

    A golden set with nothing to grade can't gate anything, so we refuse the attach
    rather than let a prompt look gated while every eval against it would be empty.
    """

    def __init__(self, name: str) -> None:
        super().__init__(f"dataset '{name}' has no items; cannot use it as a golden set")
        self.name = name


class GoldenSetMissingError(Exception):
    """Raised when promoting to the gated label but the prompt has no golden set.

    The "CI for prompts" rule: you can't ship to production without a quality bar to
    clear (Sprint 11). Attach a golden set first.
    """

    def __init__(self, name: str) -> None:
        super().__init__(
            f"prompt '{name}' has no golden set; attach one before promoting to the gated label"
        )
        self.name = name
