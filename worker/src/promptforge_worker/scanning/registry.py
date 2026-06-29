"""The scanner registry — turns "run a scan" into a concrete list of scanners.

A scan runs *every registered scanner* (v0.1 has no per-prompt scanner selection — that's a
backlog item), so this module is the single source of truth for "which detectors exist". The
counterpart to the eval engine's ``build_scorers``: the runner asks here for live scanners and
never hard-codes the set.

Each concrete scanner registers itself by appending a factory via :func:`register`. A factory
takes the shared :class:`LLMGateway` (the injection scanner's LLM-judge pass needs it; the
regex/entropy scanners ignore it) and returns a ready scanner. Scanner modules must be imported
for that registration side effect — they're imported at the bottom of this module as each lands.

Right now the registry is intentionally empty: the async spine (task 4) is complete and a scan
runs end-to-end producing a clean result; the first real scanner (task 6) plugs in here.
"""

from __future__ import annotations

from collections.abc import Callable

from promptforge_api.gateway import LLMGateway
from promptforge_api.scanning import Scanner

# A factory builds one scanner from the shared gateway. Registered by each scanner module.
ScannerFactory = Callable[[LLMGateway], Scanner]

_REGISTRY: list[ScannerFactory] = []


def register(factory: ScannerFactory) -> ScannerFactory:
    """Add a scanner factory to the registry (usable as a decorator). Returns it unchanged."""
    _REGISTRY.append(factory)
    return factory


def build_scanners(gateway: LLMGateway) -> list[Scanner]:
    """Instantiate every registered scanner, sharing one gateway. Empty until scanners register."""
    return [factory(gateway) for factory in _REGISTRY]


# Concrete scanners register on import (their modules call register() at import time). Imported
# here at the bottom — after register/build_scanners are defined — so importing the registry pulls
# them in. Add each scanner's import as its task lands.
import promptforge_worker.scanning.injection_scanner  # noqa: E402, F401  (task 12)
import promptforge_worker.scanning.jailbreak_scanner  # noqa: E402, F401  (task 10)
import promptforge_worker.scanning.pii_scanner  # noqa: E402, F401  (task 8)
import promptforge_worker.scanning.secret_scanner  # noqa: E402, F401  (task 6)
