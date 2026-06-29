"""Unit tests for config-driven pricing (Phase 7) — no DB, pure cost math + table loading."""

from decimal import Decimal

import pytest

from promptforge_api import pricing


def test_compute_cost_is_exact_decimal() -> None:
    rates = {"input_per_1m": Decimal("0.15"), "output_per_1m": Decimal("0.60")}
    # 1M input @ 0.15 + 1M output @ 0.60 = 0.75 exactly (no float drift).
    assert pricing.compute_cost(rates, 1_000_000, 1_000_000) == Decimal("0.750000")
    # A small, fractional-cent call still rounds cleanly to micro-dollars.
    assert pricing.compute_cost(rates, 1000, 500) == Decimal("0.000450")


def test_cost_for_known_model_from_bundled_table() -> None:
    # Validates both the math and that the bundled pricing.json parses + has this model.
    assert pricing.cost_for("openai/gpt-4o-mini", 1_000_000, 1_000_000) == Decimal("0.750000")


def test_cost_for_unpriced_model_is_none() -> None:
    assert pricing.cost_for("made-up/model-x", 1000, 1000) is None


def test_cost_for_missing_tokens_is_none() -> None:
    # No usage reported → cost is honestly absent, not 0.
    assert pricing.cost_for("openai/gpt-4o-mini", None, 100) is None
    assert pricing.cost_for("openai/gpt-4o-mini", 100, None) is None


def test_pricing_file_override(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = tmp_path / "prices.json"
    custom.write_text('{"my/model": {"input_per_1m": 1.0, "output_per_1m": 2.0}}', encoding="utf-8")
    monkeypatch.setenv("PROMPTFORGE_PRICING_FILE", str(custom))

    from promptforge_api.config import get_settings

    # Both the settings singleton and the pricing table are cached; clear so the override loads.
    get_settings.cache_clear()
    pricing._pricing_table.cache_clear()
    try:
        assert pricing.cost_for("my/model", 1_000_000, 0) == Decimal("1.000000")
        # The bundled models are no longer in scope under the override.
        assert pricing.cost_for("openai/gpt-4o-mini", 1000, 1000) is None
    finally:
        # Restore the defaults for every other test in the session.
        get_settings.cache_clear()
        pricing._pricing_table.cache_clear()
