"""Unit tests for the API-key dependency (no database needed)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from promptforge_api.config import get_settings
from promptforge_api.security import require_api_key


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> object:
    """Reset the cached Settings around each test so env changes take effect."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_open_when_no_keys_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROMPTFORGE_API_KEYS", raising=False)
    # No key configured and none supplied — auth is disabled, so this passes.
    assert require_api_key(x_api_key=None) is None
    assert require_api_key(x_api_key="anything") is None


def test_valid_key_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMPTFORGE_API_KEYS", "secret,rotated")
    assert require_api_key(x_api_key="secret") is None
    assert require_api_key(x_api_key="rotated") is None  # rotation: multiple keys valid


def test_missing_key_is_rejected_when_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMPTFORGE_API_KEYS", "secret")
    with pytest.raises(HTTPException) as info:
        require_api_key(x_api_key=None)
    assert info.value.status_code == 401


def test_wrong_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMPTFORGE_API_KEYS", "secret")
    with pytest.raises(HTTPException) as info:
        require_api_key(x_api_key="nope")
    assert info.value.status_code == 401


def test_comma_separated_keys_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMPTFORGE_API_KEYS", " k1 , k2 ,")
    assert get_settings().api_keys == ["k1", "k2"]
