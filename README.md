# PromptForge

**Treat prompts like production code: versioned, tested, observable.**

PromptForge is a self-hosted, open-source platform for managing LLM prompts as first-class
production assets — immutable versions, label-based deployments, automatic evaluation, and full
cost/latency/quality observability. It sits behind a provider-agnostic gateway so you're never
locked to one model vendor, and ships a resilient client SDK so your app keeps working even when the
platform is down.

> **Status: headless platform runs today (pre-v0.1).**
> Phases 0–7 are built and tested — registry, templating, gateway, SDK, async backbone, evaluation,
> and observability. The differentiators (composition, eval-on-change, security scanning), auth
> hardening, and the React UI are next; see [Roadmap](#roadmap). Built sprint by sprint against an
> [18-sprint plan](sprint/00-overview.md); decisions recorded as [ADRs](docs/adr/).

---

## The problem

Most teams manage prompts as string literals scattered through application code: no version history,
no way to test a change before it ships, no visibility into what a prompt costs or whether quality
just regressed, and a hard dependency on one model provider. PromptForge makes a prompt a versioned,
tested, observable artifact — the way we already treat the rest of production.

## Quickstart

```bash
git clone https://github.com/Albin-Jo/PromptForge.git && cd PromptForge
docker compose up -d          # postgres + redis, a one-shot migration, then api + worker + flower
curl http://localhost:8001/healthz          # -> {"status":"ok"}
```

No configuration needed — compose ships working defaults, and the core flow needs **no model
provider key**.

> **Upgrading from an earlier checkout?** Sprint 28 changed the default Postgres password and the
> published host ports (api `8001`, ui `3002`, postgres `5435`, redis `6381`). Postgres only applies
> `POSTGRES_PASSWORD` when it *first* initialises its data dir, so an existing `pgdata` volume keeps
> the old password and the api will fail to authenticate. Reset the local stack with
> `docker compose down -v` (this drops local data) before `up`, or set `POSTGRES_PASSWORD` to the
> old value in a `.env` file.

Then run the end-to-end demo (create → deploy → render → trace → metrics → alert):

```bash
uv run python demo/demo.py
```

Interactive API docs: **http://localhost:8001/docs** · Celery dashboard (Flower):
**http://localhost:5555**. The demo and its narration live in [`demo/`](demo/README.md).

## What works today

| Capability | What it gives you |
|---|---|
| **Registry + versioning** | Every edit is a new **immutable version**; `production`/`staging` labels point at a version, and moving the pointer *is* a deployment. |
| **Server-side templating** | `{{variable}}` rendering with a declared-variable contract enforced at save time, so a malformed template fails loudly, not in production. |
| **Provider-agnostic gateway** | One internal interface in front of every model vendor (via LiteLLM), with timeouts, classified errors, and bounded retry — swap providers by config. |
| **Resilient client SDK** | Fetch + render prompts with an in-process cache and **last-known-good fallback**, so your app survives the platform blinking. |
| **Async backbone** | A Celery worker runs off-request-path work (evals, trace ingestion) with idempotent, at-least-once tasks; correlation IDs thread from the API into jobs. |
| **Evaluation engine** | A from-scratch LLM judge plus **RAGAS / DeepEval** adapters behind one `Scorer` interface; a run grades with several scorers at once and stores per-item + aggregate scores. |
| **Observability** | A trace per execution → query **p50/p95/p99 latency, spend, error rate, and per-version quality**, attributed per version and per feature, with threshold **drift alerts**. |

### The core flow

```
edit prompt → save immutable version → point a label at it (a deploy)
   → app calls sdk.get_prompt(name, label="production")  (cache + fallback)
   → app calls the model via the gateway
   → app reports a trace → ingested async → cost/latency/quality per version
```

### A taste of the API

```
POST   /prompts                          create a prompt + version 1
POST   /prompts/{name}/versions          append a new immutable version
PUT    /prompts/{name}/labels/{label}    point a label at a version (deploy)
POST   /prompts/{name}/render            render the version a label points at (the SDK's call)
POST   /complete                         stream a completion through the gateway
POST   /traces                           report one execution (ingested async)
GET    /prompts/{name}/metrics           latency/cost/error/quality over a window
GET    /prompts/{name}/alerts            drift/regression alerts currently firing
```

Full, browsable schema at `/docs`.

## Architecture

Seven moving parts: a **FastAPI** API service, **Postgres** (system of record), **Redis** (prompt
cache + Celery broker/result backend), **Celery** workers (evals, trace ingestion), a **LiteLLM**
gateway, a **Python client SDK**, and (later) a **React** UI. The API is strictly layered
`router → service → repository`, with Pydantic only at the edge and plain
dataclasses/entities inside. See the [build plan](docs/prompt_platform_build_plan%20-%20Copy.md) for
the full data model, and [docs/adr/](docs/adr/) for the decisions behind it.

```
api/      FastAPI service (routers → services → repositories) + Alembic migrations
worker/   Celery workers (evals, trace ingestion)
sdk/      Python client SDK (caching + last-known-good fallback)
ui/       React UI (planned — Sprints 14–16)
demo/     runnable end-to-end demo
docs/     build plan, ADRs
sprint/   the 18-sprint delivery plan
```

## Engineering standards

This is a learning-driven portfolio build, held to production standards: **strict typing**
(`mypy --strict`) and linting (`ruff`) enforced via pre-commit, **migrations only** (never
`create_all`), **integration tests against a real throwaway Postgres** (not mocks) plus SDK↔API
contract tests, **twelve-factor config**, **structured JSON logging** with a correlation ID threaded
through every layer and into Celery, and an **ADR for every non-obvious decision**. ~210 tests cover
the spine. _(A CI pipeline that runs these on every push lands in Sprint 17.)_

## Roadmap

Built in 18 two-week sprints (foundations → serving → async spine → differentiators → auth/UI/CI →
polish). Full breakdown in [sprint/00-overview.md](sprint/00-overview.md).

**Built (Phases 0–7):** tooling · registry + versioning · templating · gateway · SDK · async
backbone · evaluation engine · observability.

**Next, not yet built:**

- **Composable prompts** — build prompts from reusable, typed, versioned blocks with a tracked
  dependency graph (Sprint 10).
- **Eval-on-change ("CI for prompts")** — saving/promoting auto-runs a golden set and **gates
  promotion on regression** (Sprint 11). _(Observability already detects regressions; this turns
  detection into a gate.)_
- **Security scanning** — flag prompt-injection / PII / secrets on save (Sprint 12).
- **Auth & hardening** — today only static API keys gate the SDK + trace endpoints; full
  user/role auth lands in Sprint 13.
- **React UI** — editor, version diff, dashboards, playground (Sprints 14–16).
- **Containerization & CI hardening, then v0.1** (Sprints 17–18).

**Post-v0.1 backlog:** Kubernetes + Helm, a hosted demo, governance/RBAC + approval workflows,
multi-tenancy, semantic search over prompts (pgvector), and semantic caching.

## What this deliberately does _not_ include

Scoped out on purpose to keep v0.1 shippable — not missed:

- **Kubernetes/Helm** — DevOps scope is Docker + CI; K8s is a documented future extension.
- **Prompt branching / non-linear versioning** — linear versioning + labels covers the real
  workflow; the schema leaves room for branching without building it.
- **Full RBAC / governance workflows** — basic authz only for v0.1.
- **Multi-tenancy** — single-tenant for v0.1.

## License

[MIT](LICENSE) — chosen so the project can be reused freely, including commercially. Reasoning in
[docs/adr/0001-use-mit-license.md](docs/adr/0001-use-mit-license.md).
