# Implementation status

Audit of this repository against [NORTH_STAR.md](NORTH_STAR.md). Written from the code as it exists, not from the vision document.

This is an early FastAPI Mission Control MVP. Most of the north star is not built. The app is runnable; tests cover the current runtime and OpenAI adapter.

---

## How to read this

- **DONE** means it works in this codebase today.
- **PARTIAL** means a real seed exists but is far from the north-star behavior.
- **MISSING** means not present in a form that can be extended without new work.
- **BROKEN** means present but incorrect, unused, or actively misleading.
- Classification records *what* failed. `RATE_LIMIT` and `TIMEOUT` are retried with bounded backoff against the same provider. `PROVIDER_OUTAGE` (or an unconfigured/unavailable primary) may use the next catalog candidate (OpenRouter when `OPENROUTER_API_KEY` is set; local Ollama when `OLLAMA_MODEL` or `OLLAMA_BASE_URL` is set). Exhausted retries or a failed failover still fail closed.

---

## DONE

- FastAPI process with lifespan, static Mission Control UI, REST + WebSocket (`app/main.py`).
- SQLite persistence for missions, durable agent/task rows, and append-only mission events (`app/store.py`). Legacy or partially missing graph rows are backfilled from events without destroying existing data.
- In-process `SwarmRuntime`: spawn agents, assign one pending task per new specialist, call the controller, run those tasks when the controller `wait`s with in-flight work, stop a mission or all missions, simulate payments (`app/runtime.py`). `MissionStatus.WAITING` is persisted and emitted as `mission.waiting` while that work runs, then `mission.running` before the next decide. `wait` with no pending/running tasks still raises `PolicyError` (`INVALID_OUTPUT`).
- Mission safety limits: depth, agents, tasks, tool calls, runtime seconds, payment cap (`MissionLimits`). Spawn/task/tool-call/runtime/payment caps are enforced. `max_tool_calls` is a real budget: `SwarmRuntime.invoke_tool` / `consume_tool_call` raise classified `PolicyError` (`RESOURCE_EXHAUSTED`) when exceeded. With no ToolProvider connected (`external_tools: []`), an invoke fails closed as `TOOL_MISSING` and does not charge the budget or emit `tool.started`.
- Fail-closed live payments: `WalletAdapter` simulates unless `live_payments` is set, then raises; no private keys in the agent process (`app/credentials.py`, `WalletAdapter`).
- Credential isolation: OpenAI key from `OPENAI_API_KEY` or Windows Credential Manager; never returned over HTTP.
- OpenAI Responses adapter (`OpenAIResponsesModelProvider` / `OpenAIProvider`) with structured JSON schema, usage metadata, no response-body leakage on errors.
- OpenRouter / OpenAI-compatible Chat Completions adapter (`OpenRouterModelProvider`) behind the same `ModelProvider` contract. Key from `OPENROUTER_API_KEY` only.
- Local Ollama Chat Completions adapter (`OllamaModelProvider`) behind the same contract. Opt-in via `OLLAMA_MODEL` and/or `OLLAMA_BASE_URL` (default `http://127.0.0.1:11434/v1`). No cloud credential. `health()` reports `unconfigured` when not opted in and `unavailable` when the daemon is down; `complete()` fails closed with `PROVIDER_OUTAGE` — no fake completions.
- Capability-based `ModelRouter` (`app/router.py`): controller/workers request reasoning/coding/tools/context/cost/privacy instead of a model id. A scored policy ranks registered `ModelProvider` catalogs (OpenAI + OpenRouter + optional Ollama) and walks a fallback chain. `PROVIDER_OUTAGE` (or unconfigured/unavailable) uses the next candidate and still emits `llm.failover`. Auth, policy, invalid output, `RATE_LIMIT`, and `TIMEOUT` stay on the provider that raised them.
- Minimal outage routing (`FailoverModelProvider`): on `PROVIDER_OUTAGE` or unconfigured/unavailable primary, try the configured secondary once. Emits `llm.failover`. Does **not** fail over on auth, policy, invalid output, `RATE_LIMIT`, or `TIMEOUT`. OpenAI-only when only `OPENAI_API_KEY` is set. `build_controller()` unwraps this into `ModelRouter` so selection is capability-based; the Failover adapter remains for direct/outage tests.
- Explicit `ProviderError` / `PolicyError` paths. Provider failure does **not** swap in `FallbackController` or mark the mission completed.
- Structured **failure classification** on the main provider/runtime failure paths:
  - `FailureClass` enum in `app/models.py` (north-star names: `RATE_LIMIT`, `PROVIDER_OUTAGE`, `TIMEOUT`, `CONTEXT_LIMIT`, `POLICY_REFUSAL`, `INVALID_OUTPUT`, `AUTHORIZATION_REQUIRED`, `CAPABILITY_MISMATCH`, `RESOURCE_EXHAUSTED`, `MODEL_FAILURE`, `UNKNOWN_FAILURE`, plus unused-for-now classes).
  - `ProviderError.failure_class` set at each OpenAI raise site (HTTP map, timeout, connect failure, incomplete, refusal, invalid JSON, missing key).
  - `PolicyError.failure_class` set on spawn/task/tool-budget/budget/invalid-model-output/invalid-wait paths.
  - Mission `result` includes `{error, failure_class}`. The same payload is on `mission.failed`. Provider errors also emit `llm.failed`.
  - Runtime deadline → `TIMEOUT`. Unexpected exceptions → `UNKNOWN_FAILURE`. Stop/cancel stays `stopped` (not a fake success).
- Bounded **retry/backoff** on the runtime `model_call` path for `RATE_LIMIT` and `TIMEOUT` only:
  - Same OpenAI adapter (no FallbackController, no other provider).
  - **3 retries** (4 attempts total); exponential delays **0.5s, 1s, 2s** (cap 8s).
  - Retry is skipped if remaining mission runtime would not cover the next backoff, so a rate-limit near the deadline stays `RATE_LIMIT` instead of becoming a deadline `TIMEOUT`.
  - Each retry emits `llm.retry` (`attempt`, `max_attempts`, `delay_seconds`, `failure_class`, `error`). Final failure still emits `llm.failed` and `mission.failed` with `failure_class`. `mission.result` stays `{error, failure_class}`.
- Health endpoint reports OpenAI, OpenRouter, and Ollama configured/model status, `fallback: false`. Ollama also reports daemon `status` (`unconfigured` / `unavailable` / `healthy`). Does not expose keys.
- Human stop: per-mission stop and global STOP ALL; in-flight and unscheduled durable unfinished missions are cancelled/stopped.
- Unfinished missions resume when a configured runtime restarts. Graceful shutdown emits `mission.suspended` without fabricating STOP; interrupted text-only attempts remain `stopped` and retry under a new task ID; the original runtime deadline remains in force.
- Vanilla JS control room: live event stream, agent tree, inspector, activity, result panel, explicit **preview** mode labeled as non-running, **objective HUD** (`#objectiveHud`) with truthful mode/status chips, and a critical **alert stack** (`#alerts`) for real terminal events (`mission.failed` including `failure_class`, `mission.completed`, blocked, stop/stop-all) plus additive `verification.failed`. Optional Notification API only after a launch gesture, and only when the tab is hidden.
- High-stakes controller `decide` can run independent multi-planner proposals plus judge/synthesis (`app/planning.py`) through `ModelRouter` when two or more providers exist. Default N is 3 (`SWARM_PLANNER_COUNT`, clamped 2–4). OpenAI-only catalogs, trivial goals, mid-flight decides, and `SWARM_MULTI_PLANNER=0` stay single-planner. Emits real `planner.proposal` / `judge.decision` events. All-planner or judge failure stays fail-closed; no `FallbackController`. Durable recovery APIs unchanged.
- Finish is gated on a real verifier (`app/verifier.py`). Controller `finish` emits `verification.started`, then `OpenAIProvider.verify` runs a fail-closed local evidence precheck and a ModelRouter structured verdict (`pass` / `fail` / `inconclusive`). Only `pass` completes the mission. Fail or inconclusive emits `verification.failed` and fails the mission as `VERIFICATION_FAILURE`. Invalid/missing verifier JSON is inconclusive, not a pass. OpenAI-only still calls the model — never auto-passes. When two or more providers exist, verification prefers an independent catalog entry. `FallbackController` stays tests-only and uses the local evidence check only.
- Tests: runtime completion/replay, spawn limits, simulated payments, provider failure stays failed with class, stop-all, runtime deadline/`TIMEOUT`, OpenAI usage + classified HTTP/timeout/outage errors, retry-then-success and retry-exhausted for `RATE_LIMIT`/`TIMEOUT`, non-retryable classes fail immediately, OpenRouter adapter contract + classified errors, Ollama adapter contract + daemon-down health/outage, outage failover to secondary, both-down fail closed, OpenAI-only factory path, durable graph migration/partial backfill, crash/graceful restart, attempt history, original deadline, ModelRouter capability ranking + fallback chain with fakes, local_only routing to Ollama, multi-planner + judge with fakes (OpenAI-only single path, trivial skip, fail-closed), `max_tool_calls` exhausted/`TOOL_MISSING` when no provider, controller `wait` with in-flight work (`WAITING`) vs invalid wait (`PolicyError`), verifier seed (missing verifier / fail / inconclusive stay failed, OpenAI-only no auto-pass, independent provider when a second catalog entry exists).

---

## PARTIAL

| North-star idea | What exists | Gap |
| --- | --- | --- |
| Objective engine | `Mission` + `SwarmRuntime.run` loop; high-stakes `decide` may run N independent planners + one judge (`app/planning.py`) | Seed only: start-plan and finish-verification decides. No OrganizationDesigner, no multi-judge, no planner-bot spawn. Mid-flight and trivial goals stay single-planner. |
| AgentSpec | Pydantic `AgentSpec` (id, parent, role, purpose, capabilities, depth, status) | No model selection, budgets, TTL, tools, workspace, permissions, fallback models, success criteria. |
| Agent factory | `SwarmRuntime.spawn` | Controller may spawn specialists; no runtime factory API, no replace/clone/merge/kill-as-reorg. |
| Model provider | `ModelProvider` contract + OpenAI Responses + OpenRouter Chat Completions + local Ollama + `ModelRouter` scored selection + outage failover | Not full north-star routing (no historical success, latency SLOs, or cached-context affinity). Streaming still explicit `CAPABILITY_MISMATCH`. vLLM / llama.cpp adapters are not in the catalog. |
| Events | Typed-ish string events + WebSocket replay of history; additive `planner.proposal` / `judge.decision` when multi-planner actually runs; additive `mission.waiting` / `mission.running`, `task.pending`, `tool.started` / `tool.failed`; additive `verification.started` / `verification.passed` / `verification.failed` | Missing most remaining north-star event types (replan, org change, self-mod, budget warning). HUD/activity understand the new verification events; no fake success animation. |
| Observability | Events, token usage on `llm.completed`, `llm.retry` on transient provider errors, activity feed, verification started/passed/failed | No cost, “why this agent”, burn rate, or external evidence runners (tests/build/HTTP). |
| Persistence | Missions, agents, tasks, and events survive restart; unfinished text-only attempts are explicitly stopped/retried and graceful shutdown is resumable | Execution is still in-process `asyncio`; no durable queue/worker lease or idempotency keys for future external side effects. |
| Policy | Limits + capability allowlist + fail-closed wallet | Not an external Policy Engine. LLM can still choose actions inside the allowlist; no human-approval gate for irreversible acts beyond payments. |
| Credentials | Key stays in env/cred manager | No capability broker. Agents do not request capabilities through a broker; the process holds the OpenAI key and calls the API. |
| UI | Agent tree + inspector + objective HUD (mode/status) + critical in-app alerts | Not a game world. Preview is synthetic (explicitly labeled). No cost HUD, replay scrubber, command bar, org graph view, or Pixi/React. Alerts are terminal mission events plus real `verification.failed` — no fake work animations. |
| Human control | Stop / stop-all | No pause/resume, approve/deny, inject info that the runtime consumes, kill individual agent, change budget. `/answers/{question_id}` stores an event only. |
| Memory | Mission JSON + event log | No scoped memory, retrieval, or learned strategy store. Each model call gets a dump of current agents/tasks. |
| Cost | `budget` / `spent` on payments only | No token-cost accounting, estimates, or ResourceScheduler. Token counts are usage telemetry, not money. |
| Verification | Mandatory verify-before-complete seed: ModelRouter structured verdict + local fabricated-claim precheck; events; `VERIFICATION_FAILURE` fail-closed | No external evidence runners (tests, HTTP, files, deployments). No dedicated verifier agent/bot. Same-model verify when the catalog is OpenAI-only (honest call, not a skip). |
| Tools | Capability strings `reason`/`write`/`review`; `max_tool_calls` enforced at `invoke_tool` / `consume_tool_call` | No ToolProvider, MCP, browser, shell, filesystem, HTTP. Production `external_tools: []` — invoke fails `TOOL_MISSING` (no fake tool success). |
| Failure recovery | Classified failures; bounded `RATE_LIMIT`/`TIMEOUT` retry; capability-based routing; `PROVIDER_OUTAGE` may fail over along the router chain including local Ollama; durable restart recovery | Exhausted retries or every configured provider down still kill the mission. No replan. |

---

## MISSING

North-star systems with no implementation to extend yet:

- Additional provider adapters (Anthropic, Gemini, xAI, Mistral, DeepSeek, Cohere, vLLM, llama.cpp) beyond OpenAI + OpenRouter + Ollama.
- Historical / cost-aware ModelRouter features (success memory, latency, cached context).
- OrganizationDesigner, authority/delegation graph, dynamic reorg (replace/clone/merge).
- Independent verifier agents and external evidence runners (tests/build/HTTP/files) beyond the finish-gate seed.
- ResourceScheduler, cost estimation UX, conservative dollar defaults as enforced policy.
- ToolProvider, MCP, self-generated tools, tool registry.
- WorkspaceProvider / sandboxes / Docker.
- Browser (Playwright etc.).
- PaymentProvider (Stripe/x402/wallets) beyond simulated `WalletAdapter`.
- Policy Engine as a separate control plane; protected-core rules; kill switch beyond stop-all.
- Self-modification workflow, self-dev agents, rollback, staging/canary.
- Long-term memory layers.
- Game-world UI (Pixi/React/Phaser), bot states as real animation, world areas, replay timeline, command bar, semantic zoom.
- Historical replay distinct from live.
- Durable queues / background workers (execution is in-process `asyncio.Task`).
- DB migrations (SQLAlchemy `create_all` only).
- Lint/typecheck/CI pipelines (pytest only, via `.[dev]`).

---

## BROKEN

Not “crashes on boot”, but incorrect or misleading relative to claims or unused surface:

- **README previously said** the UI falls back to an offline controller without a key, and that the default model is `gpt-5`. Code: launch returns **503** if the key is missing; default model is **`gpt-6-astra`**. README is corrected in this slice. Do not reintroduce a silent demo fallback.
- **`POST /api/missions/{id}/answers/{question_id}`** accepts answers; nothing in the runtime asks questions or consumes them.
- **External evidence is still missing:** the verifier judges claimed text against mission artifacts via ModelRouter. It does not run tests, hit endpoints, or hash files.
- **`FallbackController`** would request capabilities `project_work`/`report` which the live OpenAI path would reject; it is tests-only and must stay that way.

Nothing in the current test suite is known red. UI preview is synthetic by design; it must remain labeled preview.

---

## TECH DEBT

- `SwarmRuntime.run` is the orchestrator, factory, task engine, and failure handler in one module. Verification is extracted to `app/verifier.py` + `OpenAIProvider.verify`; do not grow the runtime loop further.
- Agents/tasks have durable snapshots plus append-only events and an in-memory working set. Recovery reconciles missing rows, but snapshot/event writes are not yet one atomic transaction.
- Event types are free-form strings (`agent.spawned`, `llm.failed`, …). Fine for now; a typed enum should come with the next event-schema expansion.
- `LLMProvider` remains the controller+worker behavior interface layered over the lower-level `ModelProvider`. `ModelRouter` is the selection seam; do not add provider conditionals to the runtime.
- SQLite uses additive `create_all`, not a versioned migration framework. Existing data is preserved, but future column changes need real migrations.
- Windows-only credential save path; Linux/cloud must use `OPENAI_API_KEY`.
- UI is vanilla JS modules (`control.js`, `state.mjs`, `control.css`). North star allows preserving this stack. Do not replace with React/Pixi in an early slice.
- Default model id `gpt-6-astra` is environment-specific; keep it overridable via `SWARM_MODEL`.
- No packaging beyond `pyproject.toml`; no Dockerfile, no CI.

---

## What must stay untouched (this and nearby slices)

- Vanilla JS Mission Control **plus** the truthful status HUD / critical alert stack. Do not replace with React/Pixi in this phase. Do not add fake progress or decorative workers.
- Fail-closed behavior: no fake success, no silent `FallbackController` in production, no demo substitute after provider errors.
- Credential handling: keys never in model context or HTTP responses.
- Simulated payments by default; live wallet remains unconfigured/fail-closed.
- Existing event names and mission JSON that the UI already understands (`agent.spawned`, `mission.failed`, `result.error`, etc.). Additive fields (`failure_class`) and additive events (`llm.retry`, `verification.started` / `passed` / `failed`) are OK.
- Keep the app startable as documented in README (`uvicorn app.main:app`).

## What already fits and should be extended

- `ModelProvider` + `OpenAIProvider` → `ModelRouter` now picks from registered providers; extend scoring rather than hardcoding model ids. Keep controller semantics.
- `AgentSpec` → add fields incrementally (model, budget, tools) rather than a new agent type.
- `Store` event log + durable agent/task rows → later add atomic checkpoints, worker leases, and idempotency records.
- `FailureClass` + `ProviderError`/`PolicyError` → `ModelRouter` reuses these for outage fallback. Do not invent a second error framework.
- `WalletAdapter` → real PaymentProvider behind the same fail-closed seam.
- WebSocket event sink → richer typed events; UI already applies unknown events safely.

## What should wait / be refactored only when needed

- Do not extract more micro-interfaces until OrganizationDesigner or external evidence runners exist. `ModelRouter` remains the selection seam.
- Do not replace SQLite.
- Do not replace the control-loop with LangGraph/Agents SDK wrappers.
- Self-modification, payments, browser, and game UI are later slices.

---

## NEXT PRIORITY

**This slice:** verifier seed so `finish` is a claim, not success. `SwarmRuntime` runs `verification.started` → ModelRouter verifier → `verification.passed` or fail-closed `verification.failed` (`VERIFICATION_FAILURE`). OpenAI-only still verifies; missing/invalid/inconclusive verdicts never complete the mission. Planning modules are only called through existing APIs. No OrganizationDesigner. No React/Pixi rewrite.

**Recommended next backend slice:** OrganizationDesigner (mutable org topology from the judged plan) **or** external evidence runners so verification can check tests/endpoints/files. Still fail closed. Still no game-world UI rewrite.

**Explicitly not next:** game-world UI, self-modification, PaymentProvider, Playwright.

---

## Audit notes (repo facts)

- Tree: `app/` (runtime, llm, providers, router, planning, verifier, store, models, main, health, credentials, static UI), `tests/`, `scripts/check_openai.py`, `NORTH_STAR.md`, this file. No CI, no Docker, no `.env.example`.
- Dependencies: FastAPI, uvicorn, SQLAlchemy, pydantic, httpx; pytest in `dev`; `pywin32` on Windows only.
- Production providers: `OpenAIResponsesModelProvider` → `https://api.openai.com/v1/responses`; `OpenRouterModelProvider` → `{OPENROUTER_BASE_URL}/chat/completions`; `OllamaModelProvider` → `{OLLAMA_BASE_URL}/chat/completions` (default `http://127.0.0.1:11434/v1`). `build_model_provider()` wraps OpenAI+OpenRouter in `FailoverModelProvider` when both keys are set; a single cloud provider plus opted-in Ollama uses Failover(cloud, ollama). `build_router()` always appends configured Ollama as a third catalog entry when both cloud keys are present. `build_controller()` unwraps that into `ModelRouter` for capability-based selection. `FallbackController` is a test fixture (`mode = "demo"`). Retry/backoff for `RATE_LIMIT`/`TIMEOUT` lives in `SwarmRuntime.model_call`; outage failover lives in `ModelRouter` (and `FailoverModelProvider` when used directly).
- Tests are extended in this slice rather than replaced.
- No TODOs in application code.
- Hypotheses checked: OpenAI + optional OpenRouter + optional local Ollama behind `ModelProvider`; `ModelRouter` scores capabilities and falls back on `PROVIDER_OUTAGE` including to Ollama; high-stakes `decide` can run independent planners + judge when multiple providers exist; finish requires a ModelRouter verifier (OpenAI-only still calls the model; missing/invalid/inconclusive never completes); classified `RATE_LIMIT`/`TIMEOUT` retry then fail closed; SQLite mission/agent/task snapshots plus events; resumable in-process execution with truthful interrupted-attempt history; UI vanilla JS with objective HUD + critical alerts wired to existing events plus verification.failed.
