"""Worker-side eval scorers that wrap external frameworks behind the API's Protocol.

These live in the *worker* package, not ``promptforge_api.evals``, on purpose: they import
``ragas`` and ``deepeval``, which are worker-only dependencies (the API image never installs
them — ADR 0011). They nonetheless satisfy ``promptforge_api.evals.scorer.Scorer`` *structurally*
— a class is a ``Scorer`` if it has ``name`` + ``async score(...)``, with no inheritance or
import of the API's base. That the framework adapters can implement the contract without the
API ever importing them is the whole payoff of choosing a ``Protocol`` over an ABC (ADR 0010).

The from-scratch ``LLMJudgeScorer`` stays in the API (it needs only the gateway, which the API
already owns); the registry here composes it alongside these adapters.
"""
