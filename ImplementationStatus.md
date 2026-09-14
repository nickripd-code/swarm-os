# Implementation status

Audit of this repository against [NORTH_STAR.md](NORTH_STAR.md). Written from the code as it exists, not from the vision document.

This is an early FastAPI Mission Control MVP. Most of the north star is not built. The app is runnable; tests cover the current runtime and OpenAI adapter.

---

## How to read this

- **DONE** means it works in this codebase today.
- **PARTIAL** means a real seed exists but is far from the north-star behavior.
- **MISSING** means not present in a form that can be extended without new work.
- **BROKEN** means present but incorrect, unused, or actively misleading.
- Classification in this slice records *what* failed. It does **not** yet retry, switch providers, or keep the objective alive.

---

## DONE

- FastAPI process with lifespan, static Mission Control UI, REST + WebSocket (`app/main.py`).
- SQLite persistence for missions (JSON blob) and append-only mission events (`app/store.py`). Agents and tasks are reconstructed by projecting events.
- In-process `SwarmRuntime`: spawn agents, assign one task per new specialist, call the controller, stop a mission or all missions, simulate payments (`app/runtime.py`).
- Mission safety limits: depth, agents, tasks, runtime seconds, payment cap (`MissionLimits`). Spawn/task/runtime/payment caps are enforced.
- Fail-closed live payments: `WalletAdapter` simulates unless `live_payments` is set, then raises; no private keys in the agent process (`app/credentials.py`, `WalletAdapter`).
- Credential isolation: OpenAI key from `OPENAI_API_KEY` or Windows Credential Manager; never returned over HTTP.
- Single OpenAI Responses adapter (`OpenAIProvider`) with structured JSON schema, usage metadata, no response-body leakage on errors.
- Explicit `ProviderError` / `PolicyError` paths. Provider failure does **not** swap in `FallbackController` or mark the mission completed.
- Structured **failure classification** on the main provider/runtime failure paths:
  - `FailureClass` enum in `app/models.py` (north-star names: `RATE_LIMIT`, `PROVIDER_OUTAGE`, `TIMEOUT`, `CONTEXT_LIMIT`, `POLICY_REFUSAL`, `INVALID_OUTPUT`, `AUTHORIZATION_REQUIRED`, `CAPABILITY_MISMATCH`, `RESOURCE_EXHAUSTED`, `MODEL_FAILURE`, `UNKNOWN_FAILURE`, plus unused-for-now classes).
  - `ProviderError.failure_class` set at each OpenAI raise site (HTTP map, timeout, connect failure, incomplete, refusal, invalid JSON, missing key).
  - `PolicyError.failure_class` set on spawn/task/budget/invalid-model-output paths.
  - Mission `result` includes `{error, failure_class}`. The same payload is on `mission.failed`. Provider errors also emit `llm.failed`.
  - Runtime deadline → `TIMEOUT`. Unexpected exceptions → `UNKNOWN_FAILURE`. Stop/cancel stays `stopped` (not a fake success).
- Health endpoint reports OpenAI configured/model/reasoning, `fallback: false`.
- Human stop: per-mission stop and global STOP ALL; in-flight workers are cancelled.
- Server restart marks leftover pending/running/waiting missions `stopped` (does not resume).
- Vanilla JS control room: live event stream, agent tree, inspector, activity, result panel, explicit **preview** mode labeled as non-running.
- Tests: runtime completion/replay, spawn limits, simulated payments, provider failure stays failed with class, stop-all, runtime deadline/`TIMEOUT`, OpenAI usage + classified HTTP/timeout/outage errors.

---

## PARTIAL

| North-star idea | What exists | Gap |
| --- | --- | --- |
| Objective engine | `Mission` + `SwarmRuntime.run` loop | One controller LLM decides spawn/finish/blocked/wait. No independent planners, judge, or organization designer. |
| AgentSpec | Pydantic `AgentSpec` (id, parent, role, purpose, capabilities, depth, status) | No model selection, budgets, TTL, tools, workspace, permissions, fallback models, success criteria. |
| Agent factory | `SwarmRuntime.spawn` | Controller may spawn specialists; no runtime factory API, no replace/clone/merge/kill-as-reorg. |
| Model provider | `LLMProvider` with `decide`/`work` | Not the north-star `ModelProvider` (list/stream/health/cost/capabilities). OpenAI-only. |
| Events | Typed-ish string events + WebSocket replay of history | Missing most north-star event types (verification, replan, org change, self-mod, budget warning). |
| Observability | Events, token usage on `llm.completed`, activity feed | No cost, retries, verification traces, “why this agent”, burn rate. |
| Persistence | Missions + events survive process restart | Agents/tasks are in-memory during a run; restart **stops** work instead of resuming. No checkpoints, no org graph table. |
| Policy | Limits + capability allowlist + fail-closed wallet | Not an external Policy Engine. LLM can still choose actions inside the allowlist; no human-approval gate for irreversible acts beyond payments. |
| Credentials | Key stays in env/cred manager | No capability broker. Agents do not request capabilities through a broker; the process holds the OpenAI key and calls the API. |
| UI | Agent tree + inspector + HUD-ish stats | Not a game world. Preview mode is synthetic (explicitly labeled). No cost HUD, replay scrubber, command bar, org graph view. |
| Human control | Stop / stop-all | No pause/resume, approve/deny, inject info that the runtime consumes, kill individual agent, change budget. `/answers/{question_id}` stores an event only. |
| Memory | Mission JSON + event log | No scoped memory, retrieval, or learned strategy store. Each model call gets a dump of current agents/tasks. |
| Cost | `budget` / `spent` on payments only | No token-cost accounting, estimates, or ResourceScheduler. Token counts are usage telemetry, not money. |
| Verification | Controller prompt says not to claim undone work; workers can `blocked` | No independent verifier, no external success criteria, finish = model `summary`. |
| Tools | Capability strings `reason`/`write`/`review` | No ToolProvider, MCP, browser, shell, filesystem, HTTP. `external_tools: []`. |
| Failure recovery | Failures are **classified** | Class is recorded, then the mission still dies. No retry/backoff, no other provider, no replan. |

---

## MISSING

North-star systems with no implementation to extend yet:

- Multi-provider adapters (Anthropic, Gemini, xAI, Mistral, DeepSeek, Cohere, OpenRouter, Ollama, vLLM, llama.cpp).
- ModelRouter / capability-based routing / fallback chains.
- Multi-planner + judge/synthesis.
- OrganizationDesigner, authority/delegation graph, dynamic reorg (replace/clone/merge).
- Verifier agents and mandatory external evidence.
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
- **`MissionLimits.max_tool_calls` is never enforced** (no tool calls exist).
- **`MissionStatus.WAITING` is unused.** Controller `wait` with no in-flight work raises `PolicyError`.
- **`POST /api/missions/{id}/answers/{question_id}`** accepts answers; nothing in the runtime asks questions or consumes them.
- **Restart is not durable execution:** running missions are force-stopped. That is intentional fail-closed today, but it contradicts north-star “12-hour objective must not restart from zero.”
- **Finish is not verification:** `action == "finish"` plus a summary completes the mission. An LLM saying done is treated as done.
- **`FallbackController`** would request capabilities `project_work`/`report` which the live OpenAI path would reject; it is tests-only and must stay that way.

Nothing in the current test suite is known red. UI preview is synthetic by design; it must remain labeled preview.

---

## TECH DEBT

- `SwarmRuntime.run` is the orchestrator, factory, task engine, and failure handler in one module. Fine for this MVP; do not grow it into a god class—extract when adding routing/verification.
- Agents/tasks live in `defaultdict` on the runtime; store projection is a second copy of truth. Dual state will bite once resume exists.
- Event types are free-form strings (`agent.spawned`, `llm.failed`, …). Fine for now; a typed enum should come with the next event-schema expansion.
- `LLMProvider` is a controller+worker interface, not a model gateway. Keep OpenAI behind it; do not sprinkle `if model == "gpt"` elsewhere.
- SQLite JSON blobs, no migrations. Acceptable while the schema is tiny.
- Windows-only credential save path; Linux/cloud must use `OPENAI_API_KEY`.
- UI is vanilla JS modules (`control.js`, `state.mjs`, `control.css`). North star allows preserving this stack. Do not replace with React/Pixi in an early slice.
- Default model id `gpt-6-astra` is environment-specific; keep it overridable via `SWARM_MODEL`.
- No packaging beyond `pyproject.toml`; no Dockerfile, no CI.

---

## What must stay untouched (this and nearby slices)

- Vanilla JS Mission Control unless a **tiny** status surface is required. Do not rewrite the UI; do not add React/Pixi until a dedicated UI slice.
- Fail-closed behavior: no fake success, no silent `FallbackController` in production, no demo substitute after provider errors.
- Credential handling: keys never in model context or HTTP responses.
- Simulated payments by default; live wallet remains unconfigured/fail-closed.
- Existing event names and mission JSON that the UI already understands (`agent.spawned`, `mission.failed`, `result.error`, etc.). Additive fields (`failure_class`) are OK.
- Keep the app startable as documented in README (`uvicorn app.main:app`).

## What already fits and should be extended

- `LLMProvider` → evolve toward `ModelProvider` + keep `OpenAIProvider` as the first adapter.
- `AgentSpec` → add fields incrementally (model, budget, tools) rather than a new agent type.
- `Store` event log → durable task/org/agent rows and replay.
- `FailureClass` + `ProviderError`/`PolicyError` → retry/backoff and later routing (do not invent a second error framework).
- `WalletAdapter` → real PaymentProvider behind the same fail-closed seam.
- WebSocket event sink → richer typed events; UI already applies unknown events safely.

## What should wait / be refactored only when needed

- Do not extract micro-interfaces until a second provider or verifier exists.
- Do not replace SQLite.
- Do not replace the control-loop with LangGraph/Agents SDK wrappers.
- Self-modification, payments, browser, and game UI are later slices.

---

## NEXT PRIORITY

**Recommended next slice (slice 2):** bounded retry/backoff for `RATE_LIMIT` and `TIMEOUT` (and optionally `PROVIDER_OUTAGE`) **without** treating retries as success and **without** a fake second provider.

Why this, not a UI rewrite or ModelRouter:

1. This slice made failure *legible*. The north star still says a provider outage must not kill the objective—today it still does.
2. Retry on classified classes is the smallest use of the new taxonomy.
3. A full ModelGateway/OpenRouter adapter is the right *following* slice so `PROVIDER_OUTAGE` can change provider; doing routing first without retries still dies on 429s.

**Smallest steps for slice 2 (keep the app runnable):**

1. On `RATE_LIMIT` / `TIMEOUT` from `model_call`, retry the same provider with backoff, capped by mission runtime and a small retry limit; emit `llm.failed` (or a retry event) each time; if exhausted, fail the mission with the same `failure_class`.
2. Tests: 429 then success → mission can complete; repeated 429 → still `failed` + `RATE_LIMIT`, never `mission.completed` via fallback.
3. Do not add OpenRouter, React, or verification in that slice unless they fall out of the retry work.

**Slice 3 (after retries):** provider-independent `ModelProvider` contract (health, model id, complete) + OpenRouter adapter behind the same `LLMProvider.decide/work` used today, so classified `PROVIDER_OUTAGE` has a real alternative. Still no UI rewrite.

**Explicitly not next:** game-world UI, self-modification, PaymentProvider, Playwright, OrganizationDesigner.

---

## Audit notes (repo facts)

- Tree: `app/` (runtime, llm, store, models, main, health, credentials, static UI), `tests/`, `scripts/check_openai.py`, `NORTH_STAR.md`, this file. No CI, no Docker, no `.env.example`.
- Dependencies: FastAPI, uvicorn, SQLAlchemy, pydantic, httpx; pytest in `dev`; `pywin32` on Windows only.
- Single production provider: `OpenAIProvider` → `https://api.openai.com/v1/responses`. `FallbackController` is a test fixture (`mode = "demo"`).
- 11 tests existed before this slice; this slice extends them rather than replacing coverage.
- No TODOs in application code.
- Hypotheses checked: OpenAI-only in `app/llm.py`; runtime killed missions on `ProviderError` with a string `error` (now classified); SQLite missions+events; agents/tasks in-memory / event-projected; UI vanilla JS and left unchanged this slice.
