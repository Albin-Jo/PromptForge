"""Unit tests for the mustache-style renderer — pure functions, no DB (ADR 0004)."""

import pytest

from promptforge_api.templating import extract_variables, render_template


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("Hello {{name}}", {"name"}),
        ("{{a}} and {{ b }} and {{a}}", {"a", "b"}),  # dedup + whitespace tolerance
        ("no variables here", set()),
        ("{{ first_name }}", {"first_name"}),  # identifiers with underscores
        ("{{1bad}} {{ok}}", {"ok"}),  # a name can't start with a digit → not a placeholder
    ],
)
def test_extract_variables(template: str, expected: set[str]) -> None:
    assert extract_variables(template) == expected


def test_render_substitutes_all_placeholders() -> None:
    out = render_template("Hi {{name}}, you are {{role}}", {"name": "Ada", "role": "admin"})
    assert out == "Hi Ada, you are admin"


def test_render_handles_repeated_and_spaced_placeholders() -> None:
    out = render_template("{{x}}-{{ x }}-{{x}}", {"x": "z"})
    assert out == "z-z-z"


def test_render_inserts_values_literally_no_reinterpretation() -> None:
    """A value containing {{...}} is inserted verbatim, never re-scanned (no SSTI)."""
    out = render_template("payload: {{a}}", {"a": "{{b}} \\1 {{a}}"})
    assert out == "payload: {{b}} \\1 {{a}}"


def test_render_missing_value_is_a_keyerror() -> None:
    """The service guarantees presence; a gap here is a programming error."""
    with pytest.raises(KeyError):
        render_template("{{missing}}", {})
