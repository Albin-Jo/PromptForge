"""Unit tests for the SDK client surface (happy path + error mapping).

These use an ``httpx.MockTransport`` so the suite never touches the network: each test
hands the client a fake handler that inspects the outgoing request and returns a canned
response. The SDK↔API *contract* tests (driving the real app) land in a later slice.
"""

from __future__ import annotations

import httpx
import pytest

from promptforge import (
    PromptForgeAPIError,
    PromptForgeClient,
    PromptForgeConnectionError,
    PromptNotFoundError,
    RenderedPrompt,
)


def _client(handler) -> PromptForgeClient:
    """Build a client whose every request is served by *handler* (no network)."""
    return PromptForgeClient("http://test", transport=httpx.MockTransport(handler))


def _ok(prompt: str = "x") -> httpx.Response:
    """A minimal successful render response."""
    return httpx.Response(
        200, json={"prompt": prompt, "model_settings": None, "output_schema": None}
    )


def test_get_prompt_calls_render_by_label_and_parses_response() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        return httpx.Response(
            200,
            json={
                "prompt": "Hello Ada",
                "model_settings": {"model": "claude-opus-4-8"},
                "output_schema": None,
            },
        )

    with _client(handler) as client:
        result = client.get_prompt("greet", label="production", variables={"name": "Ada"})

    assert isinstance(result, RenderedPrompt)
    assert result.prompt == "Hello Ada"
    assert result.model_settings == {"model": "claude-opus-4-8"}
    assert result.output_schema is None
    assert captured["method"] == "POST"
    assert captured["url"] == "http://test/prompts/greet/render"


def test_get_prompt_sends_label_and_variables_in_body() -> None:
    import json

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return _ok()

    with _client(handler) as client:
        client.get_prompt("p", label="staging", variables={"a": "1"})

    assert seen == {"label": "staging", "variables": {"a": "1"}}


def test_label_defaults_to_production_and_variables_to_empty() -> None:
    import json

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return _ok()

    with _client(handler) as client:
        client.get_prompt("p")

    assert seen == {"label": "production", "variables": {}}


def test_api_key_is_sent_as_header() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("x-api-key")
        return _ok()

    client = PromptForgeClient(
        "http://test", api_key="secret", transport=httpx.MockTransport(handler)
    )
    with client:
        client.get_prompt("p")

    assert seen["key"] == "secret"


def test_404_maps_to_prompt_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "prompt 'missing' not found"})

    with _client(handler) as client, pytest.raises(PromptNotFoundError) as info:
        client.get_prompt("missing", label="production")

    assert info.value.name == "missing"
    assert info.value.label == "production"


def test_other_error_status_maps_to_api_error_with_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "missing variables: ['a']"})

    with _client(handler) as client, pytest.raises(PromptForgeAPIError) as info:
        client.get_prompt("p")

    assert info.value.status_code == 422
    assert info.value.detail == "missing variables: ['a']"


def test_network_failure_maps_to_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with _client(handler) as client, pytest.raises(PromptForgeConnectionError):
        client.get_prompt("p")
