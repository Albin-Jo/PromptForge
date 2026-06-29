"""Unit tests for ScanService — no database, fake repositories.

The scan-on-save trigger has just enough logic to be worth pinning without a container: it must
create a *pending* scan tied to the version, with an empty scanner set (the worker decides what
runs), and hand the new id to the enqueue side. The full async path (worker actually scanning) is
covered by the worker integration test; here we isolate the service's behaviour.
"""

from __future__ import annotations

import uuid

from promptforge_api.db.models import Prompt, PromptVersion
from promptforge_api.db.scan_models import SecurityScan
from promptforge_api.services.scans import ScanService


class _FakeScanRepo:
    """Records added scans and assigns an id on flush, the way the DB default would."""

    def __init__(self) -> None:
        self.added: list[SecurityScan] = []

    def add(self, scan: SecurityScan) -> None:
        self.added.append(scan)

    def flush(self) -> None:
        for scan in self.added:
            if scan.id is None:
                scan.id = uuid.uuid4()

    def latest_for_version(self, prompt_version_id: uuid.UUID) -> SecurityScan | None:
        matches = [s for s in self.added if s.prompt_version_id == prompt_version_id]
        return matches[-1] if matches else None

    def latest_completed_for_version(self, prompt_version_id: uuid.UUID) -> SecurityScan | None:
        completed = [
            s
            for s in self.added
            if s.prompt_version_id == prompt_version_id and s.status == "completed"
        ]
        return completed[-1] if completed else None


def _service() -> tuple[ScanService, _FakeScanRepo, list[uuid.UUID]]:
    repo = _FakeScanRepo()
    enqueued: list[uuid.UUID] = []
    service = ScanService(repo, prompt_repo=None, submit_scan=enqueued.append)  # type: ignore[arg-type]
    return service, repo, enqueued


def _version() -> tuple[Prompt, PromptVersion]:
    prompt = Prompt(name="greeter")
    version = PromptVersion(version_number=1, content="Hello {{name}}")
    version.id = uuid.uuid4()
    prompt.versions.append(version)
    return prompt, version


def test_trigger_on_create_enqueues_a_pending_scan_for_the_version() -> None:
    service, repo, enqueued = _service()
    prompt, version = _version()

    scan = service.trigger_on_create(prompt, version)

    assert scan.status == "pending"
    assert scan.prompt_version_id == version.id
    assert scan.scanners == []  # the worker decides which scanners run
    assert repo.added == [scan]


def test_trigger_on_create_hands_the_new_scan_id_to_the_enqueue_side() -> None:
    service, _repo, enqueued = _service()
    prompt, version = _version()

    scan = service.trigger_on_create(prompt, version)

    # The id is populated by flush *before* enqueue, so the worker can find the row.
    assert scan.id is not None
    assert enqueued == [scan.id]


def test_trigger_on_create_is_unconditional() -> None:
    # Unlike the eval gate, scanning has no golden-set precondition — a brand-new prompt with no
    # quality bar still gets scanned.
    service, _repo, enqueued = _service()
    prompt, version = _version()
    assert prompt.golden_set_id is None

    service.trigger_on_create(prompt, version)

    assert len(enqueued) == 1
