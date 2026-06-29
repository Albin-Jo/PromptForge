"""Mustache-style prompt rendering — pure functions, no template logic (ADR 0004).

The whole security stance lives here: a template only ever has its ``{{ name }}``
placeholders replaced with the literal string of a supplied value. There are no
conditionals, loops, attribute access, or method calls, and a substituted value is
**never re-scanned as template source** — so a value that itself contains ``{{x}}``
is inserted verbatim, not interpreted. That makes server-side template injection
impossible by construction rather than by configuration.

These functions are deliberately free of database, HTTP, and Pydantic concerns so
they can be unit-tested in isolation; the service layer owns validation policy
(which variables are required) and turns failures into HTTP errors.
"""

import re
from collections.abc import Iterable, Mapping

# A placeholder is {{ name }} with optional surrounding whitespace; a name is a
# plain identifier. Anything fancier (dots, calls, filters) is intentionally not a
# placeholder — it's just literal text — because we render data, never code.
_PLACEHOLDER = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


class VariableContractError(Exception):
    """Raised when declared variables don't match a template's required variables.

    Lives here (not in a service) because it's a pure template/variable concern shared by
    prompt *and* block version creation, and by composition — keeping it neutral avoids a
    service-to-service import. Mapped to HTTP 422 in :mod:`promptforge_api.errors`.
    """


def extract_variables(template: str) -> set[str]:
    """Return the set of variable names referenced by ``{{ ... }}`` in *template*."""
    return set(_PLACEHOLDER.findall(template))


def render_template(template: str, variables: Mapping[str, str]) -> str:
    """Substitute every ``{{ name }}`` with ``variables[name]``.

    Uses a replacement *function* (not a replacement string) so the inserted value
    is treated as a literal — backreferences and any ``{{...}}`` inside a value are
    not interpreted. Assumes every referenced name is present in *variables*; the
    service validates that up front, so a missing key here is a programming error
    and surfaces as :class:`KeyError`.
    """

    def _replace(match: re.Match[str]) -> str:
        return variables[match.group(1)]

    return _PLACEHOLDER.sub(_replace, template)


def check_variable_contract(
    content: str, input_variables: list[str], *, extra_required: Iterable[str] = ()
) -> None:
    """Enforce ADR 0004: declared variables must match the template's required set exactly.

    Pure (no DB/HTTP) and shared by prompt *and* block version creation — both render
    through the same mustache engine, so both owe the same contract: no duplicate names,
    every required variable declared, and no declared name left unused.

    The *required* set is the template's own ``{{placeholders}}`` plus ``extra_required`` —
    the variables a composition inherits from the blocks it includes (their union). With
    no extra (the non-composed case) this is exactly the original placeholders-equal-declared
    check. Raises :class:`VariableContractError` (mapped to 422) on any mismatch.
    """
    if len(set(input_variables)) != len(input_variables):
        raise VariableContractError("input_variables contains duplicate names")

    required = extract_variables(content) | set(extra_required)
    declared = set(input_variables)
    undeclared = required - declared
    unused = declared - required
    if undeclared or unused:
        problems: list[str] = []
        if undeclared:
            problems.append(f"undeclared required variables: {sorted(undeclared)}")
        if unused:
            problems.append(f"declared variables not required: {sorted(unused)}")
        raise VariableContractError("; ".join(problems))
