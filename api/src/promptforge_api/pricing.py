"""Config-driven model pricing: turn token counts into a cost (Phase 7).

A :class:`Trace` records how many tokens an execution used; this turns that into money:
``cost = input_tokens × input_price + output_tokens × output_price``. Prices change often and
differ per provider, so the table is **config, not code** — a JSON file mapping a (gateway-style)
model id to its per-million-token input/output rates, shipped with sensible defaults and
overridable at runtime via ``PROMPTFORGE_PRICING_FILE`` (so ops update prices without a rebuild).

Money is :class:`~decimal.Decimal`, never float — fractions of a cent must round exactly, and a
binary float can't represent ``0.15`` precisely. An unknown model or missing token count yields
``None`` (cost honestly *absent*), never a silently-wrong ``0`` — and an unpriced model is logged
so the gap is visible.

The bundled ``pricing.json`` rates are public list prices at authoring time and *will* drift;
treat them as a starting default to update, not a source of truth.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

import structlog

from promptforge_api.config import get_settings

_logger = structlog.get_logger(__name__)

# Prices are quoted per *million* tokens (the current vendor convention); divide by this to get
# the cost for an actual token count. Costs are rounded to micro-dollars to match traces.cost_usd
# (Numeric(12, 6)) — six decimals is well below a cent, enough to not lose per-call precision.
_PER = Decimal(1_000_000)
_CENT_PRECISION = Decimal("0.000001")


@lru_cache
def _pricing_table() -> dict[str, dict[str, Decimal]]:
    """Load the pricing table once: the override file if set, else the bundled default.

    Cached for the process; a test that swaps the file must call ``_pricing_table.cache_clear()``.
    Rates are parsed via ``str`` into :class:`Decimal` so a JSON float never taints the money math.
    """
    pricing_file = get_settings().pricing_file
    if pricing_file:
        raw_text = Path(pricing_file).read_text(encoding="utf-8")
    else:
        raw_text = files("promptforge_api").joinpath("pricing.json").read_text(encoding="utf-8")

    raw: dict[str, dict[str, float | str]] = json.loads(raw_text)
    return {
        model: {
            "input_per_1m": Decimal(str(rates["input_per_1m"])),
            "output_per_1m": Decimal(str(rates["output_per_1m"])),
        }
        for model, rates in raw.items()
    }


def compute_cost(rates: Mapping[str, Decimal], input_tokens: int, output_tokens: int) -> Decimal:
    """Pure cost from explicit per-million rates and token counts (no I/O — easy to test)."""
    cost = (
        Decimal(input_tokens) * rates["input_per_1m"]
        + Decimal(output_tokens) * rates["output_per_1m"]
    ) / _PER
    return cost.quantize(_CENT_PRECISION)


def cost_for(model: str, input_tokens: int | None, output_tokens: int | None) -> Decimal | None:
    """Cost in USD for *model* given token counts, or ``None`` if it can't be known.

    ``None`` when either token count is missing (the provider didn't report usage) or the model
    isn't in the pricing table (logged, so an unpriced model surfaces rather than costing 0).
    """
    if input_tokens is None or output_tokens is None:
        return None
    rates = _pricing_table().get(model)
    if rates is None:
        _logger.warning("pricing_model_not_found", model=model)
        return None
    return compute_cost(rates, input_tokens, output_tokens)
