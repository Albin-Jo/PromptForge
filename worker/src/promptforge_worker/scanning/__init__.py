"""Worker-side security scanning: the runner and the scanner registry.

The scanner *interface* and domain types (:class:`~promptforge_api.scanning.Scanner`,
``Finding``, ``Severity``) live in the API package — the runner imports them — exactly as the
eval engine splits its ``Scorer`` protocol (API) from its runner/adapters (worker). The concrete
scanners (secret, PII, jailbreak, injection) land in later Sprint-12 tasks and register
themselves here; until then the registry is empty and a scan completes clean.
"""
