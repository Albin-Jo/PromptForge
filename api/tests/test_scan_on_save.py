"""Integration test: saving a version triggers a security scan (the scan-on-save wiring).

The unit tests cover ``ScanService.trigger_on_create`` in isolation; this pins the wiring through
the real HTTP → PromptService path — that create/add_version actually enqueue a scan. The
``captured_enqueues`` autouse fixture (conftest) stands in for the broker and records the ids.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient


def _create(client: TestClient, name: str = "greeter") -> None:
    resp = client.post(
        "/prompts",
        json={"name": name, "content": "Hello {{who}}", "input_variables": ["who"]},
    )
    assert resp.status_code == 201, resp.text


def test_creating_a_prompt_enqueues_one_scan(
    client: TestClient, captured_enqueues: SimpleNamespace
) -> None:
    _create(client)
    assert len(captured_enqueues.scans) == 1  # the first version is scanned on save


def test_adding_a_version_enqueues_another_scan(
    client: TestClient, captured_enqueues: SimpleNamespace
) -> None:
    _create(client)
    resp = client.post(
        "/prompts/greeter/versions",
        json={"content": "Hi {{who}}", "input_variables": ["who"]},
    )
    assert resp.status_code == 201, resp.text
    assert len(captured_enqueues.scans) == 2  # one per saved version, no golden set required
