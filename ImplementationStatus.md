# Implementation status

Audit of this repository against [NORTH_STAR.md](NORTH_STAR.md). Written from the code as it exists, not from the vision document.

This is an early FastAPI Mission Control MVP. Most of the north star is not built. The app is runnable; tests cover the current runtime and OpenAI adapter.

---

## How to read this

- **DONE** means it works in this codebase today.
- **PARTIAL** means a real seed exists but is far from the north-star behavior.
- **MISSING** means not present in a form that can be extended without new work.
- **BROKEN** means present but incorrect, unused, or actively misleading.
- Classification records *what* failed. `RATE_LIMIT` and `TIMEOUT` are retried with bounded backoff against the same provider. `PROVIDER_OUTAGE` (or an unconfigured/unavailable primary) may use the next catalog candidate (OpenRouter when `OPENROUTER_API_KEY` is set; xAI when `XAI_API_KEY` is set; Anthropic when `ANTHROPIC_API_KEY` is set; Mistral when `MISTRAL_API_KEY` is set; Gemini when `GEMINI_API_KEY` is set; Cohere when `COHERE_API_KEY` is set; local Ollama when `OLLAMA_MODEL` or `OLLAMA_BASE_URL` is set; local vLLM when `VLLM_MODEL` or `VLLM_BASE_URL` is set; local llama.cpp when `LLAMACPP_MODEL` or `LLAMACPP_BASE_URL` is set). Exhausted retries or a failed failover still fail closed.

---

## DONE

- FastAPI process with lifespan, static Mission Control UI, REST + WebSocket (`app/main.py`).
- SQLite persistence for missions, durable agent/task rows, append-only mission events, worker leases, and idempotency keys (`app/store.py`). Schema is applied by versioned migrations (`app/migrations.py`, v2 = lease/idempotency tables). Legacy create_all-era files upgrade in place; rows are not dropped. Legacy or partially missing graph rows are backfilled from events without destroying existing data.
- In-process `SwarmRuntime`: spawn agents, assign one pending task per new specialist, call the controller, run those tasks when the controller `wait`s with in-flight work, stop a mission or all missions, simulate payments (`app/runtime.py`). `MissionStatus.WAITING` is persisted and emitted as `mission.waiting` while that work runs, then `mission.running` before the next decide. `wait` with no pending/running tasks still raises `PolicyError` (`INVALID_OUTPUT`).
- Mission safety limits: depth, agents, tasks, tool calls, runtime seconds, payment cap (`MissionLimits`). Spawn/task/tool-call/runtime/payment caps are enforced. An explicit `PolicyGate` (`app/policy.py`) authorizes spawn, finish, and tool use before the runtime acts. It reuses `PolicyError` (fail closed). Dangerous tool names (shell, browser, network, payment, deploy, secrets) are denied by default as `POLICY_REFUSAL` even if a ToolProvider lists them. Optional mission `privacy` (`cloud_allowed` default, or `local_only`) is persisted and forwarded into `CapabilityRequest`; `local_only` also refuses cloud/network tools. `max_tool_calls` remains a real budget: `SwarmRuntime.invoke_tool` / `consume_tool_call` raise classified `PolicyError` (`RESOURCE_EXHAUSTED`) when exceeded. With no ToolProvider connected, a non-dangerous invoke fails closed as `TOOL_MISSING` and does not charge the budget or emit `tool.started`. OpenAI-only + default `cloud_allowed` is unchanged.
- `ToolProvider` seam (`app/tools.py`): allowlisted in-process tools (`echo`, `clock.utc`, `hash.sha256` via `SWARM_LOCAL_TOOLS`) and an MCP JSON-RPC client stub (`MCP_SERVER_URL`). `invoke_tool` runs `PolicyGate` first, then executes a real provider, emits `tool.started` / `tool.completed` / `tool.failed`, and never invents success. Unconfigured MCP or an unknown name is `TOOL_MISSING`. Execution errors are `TOOL_FAILURE` (or `PROVIDER_OUTAGE` / `TIMEOUT` for MCP transport). Controller `use_tool` is a real action. Credential-shaped keys are stripped from tool payloads. `/api/health` reports `tools` without secrets.
- Fail-closed live payments: `PaymentProvider` behind `WalletAdapter` (`app/payments.py`). Default is `SimulatedPaymentProvider`. `live_payments=True` resolves to `UnconfiguredLivePaymentProvider` and raises `AUTHORIZATION_REQUIRED`. Production factory never enables live spend; no payment secrets are read, logged, or returned.
- Credential isolation: OpenAI key from `OPENAI_API_KEY` or Windows Credential Manager; never returned over HTTP.
- OpenAI Responses adapter (`OpenAIResponsesModelProvider` / `OpenAIProvider`) with structured JSON schema, usage metadata, no response-body leakage on errors.
- OpenRouter / OpenAI-compatible Chat Completions adapter (`OpenRouterModelProvider`) behind the same `ModelProvider` contract. Key from `OPENROUTER_API_KEY` only.
- xAI / OpenAI-compatible Chat Completions adapter (`XAIModelProvider`) behind the same contract. Opt-in via `XAI_API_KEY` only (`XAI_MODEL` default `grok-3`, `XAI_BASE_URL` default `https://api.x.ai/v1`). `health()` reports `unconfigured` without a key and `healthy` when a credential is present; it does not probe the live API. `complete()` fails closed with `AUTHORIZATION_REQUIRED` when unconfigured — no fake completions, no key leakage.
- Anthropic Messages adapter (`AnthropicModelProvider`) behind the same contract. Opt-in via `ANTHROPIC_API_KEY` only (`ANTHROPIC_MODEL` default `claude-sonnet-4-5`, `ANTHROPIC_BASE_URL` default `https://api.anthropic.com/v1`). Native `/v1/messages` (not Chat Completions). Structured output uses a forced Messages tool when `response_format` is json_schema; text JSON is accepted as a fallback. `health()` reports `unconfigured` without a key and `healthy` when a credential is present; it does not probe the live API. `complete()` fails closed with `AUTHORIZATION_REQUIRED` when unconfigured — no fake completions, no key leakage.
- Mistral / OpenAI-compatible Chat Completions adapter (`MistralModelProvider`) behind the same contract. Opt-in via `MISTRAL_API_KEY` only (`MISTRAL_MODEL` default `mistral-small-latest`, `MISTRAL_BASE_URL` default `https://api.mistral.ai/v1`). `MISTRAL_MODEL` does not opt in by itself. `health()` reports `unconfigured` without a key and `healthy` when a credential is present; it does not probe the live API. `complete()` fails closed with `AUTHORIZATION_REQUIRED` when unconfigured — no fake completions, no key leakage.
- Gemini / OpenAI-compatible Chat Completions adapter (`GeminiModelProvider`) behind the same contract. Opt-in via `GEMINI_API_KEY` only (`GEMINI_MODEL` default `gemini-2.0-flash`, `GEMINI_BASE_URL` default `https://generativelanguage.googleapis.com/v1beta/openai`). `health()` reports `unconfigured` without a key and `healthy` when a credential is present; it does not probe the live API. `complete()` fails closed with `AUTHORIZATION_REQUIRED` when unconfigured — no fake completions, no key leakage.
- Cohere / OpenAI-compatible Chat Completions adapter (`CohereModelProvider`) behind the same contract. Opt-in via `COHERE_API_KEY` only (`COHERE_MODEL` default `command-a-03-2025`, `COHERE_BASE_URL` default `https://api.cohere.ai/compatibility/v1`). `COHERE_MODEL` does not opt in by itself. `health()` reports `unconfigured` without a key and `healthy` when a credential is present; it does not probe the live API. `complete()` fails closed with `AUTHORIZATION_REQUIRED` when unconfigured — no fake completions, no key leakage.
- Local Ollama Chat Completions adapter (`OllamaModelProvider`) behind the same contract. Opt-in via `OLLAMA_MODEL` and/or `OLLAMA_BASE_URL` (default `http://127.0.0.1:11434/v1`). No cloud credential. `health()` reports `unconfigured` when not opted in and `unavailable` when the daemon is down; `complete()` fails closed with `PROVIDER_OUTAGE` — no fake completions.
- Local vLLM Chat Completions adapter (`VllmModelProvider`) behind the same contract. Opt-in via `VLLM_MODEL` and/or `VLLM_BASE_URL` (default `http://127.0.0.1:8000/v1`). No cloud credential. `health()` reports `unconfigured` when not opted in and `unavailable` when the daemon is down; `complete()` fails closed (`AUTHORIZATION_REQUIRED` when unconfigured, `PROVIDER_OUTAGE` when unreachable) — no fake completions.
- Local llama.cpp Chat Completions adapter (`LlamaCppModelProvider`) behind the same contract. Opt-in via `LLAMACPP_MODEL` and/or `LLAMACPP_BASE_URL` (default `http://127.0.0.1:8080/v1`). No cloud credential. `health()` reports `unconfigured` when not opted in and `unavailable` when the daemon is down; `complete()` fails closed (`AUTHORIZATION_REQUIRED` when unconfigured, `PROVIDER_OUTAGE` when unreachable) — no fake completions.
- Capability-based `ModelRouter` (`app/router.py`): controller/workers request reasoning/coding/tools/context/cost/privacy instead of a model id. A scored policy ranks registered `ModelProvider` catalogs (OpenAI + OpenRouter + optional xAI + optional Anthropic + optional Mistral + optional Gemini + optional Cohere + optional Ollama + optional vLLM + optional llama.cpp) and walks a fallback chain. Recent in-memory success/failure per provider adjusts score (empty history is unknown, not success). Eligible models of the same known cost kind get a relative cost penalty so cheaper ones rank higher; unknown cost is never treated as cheapest. Selection `rationale` (reasons + score) is on `RouteDecision` and `_meta.route`. `PROVIDER_OUTAGE` (or unconfigured/unavailable) uses the next candidate and still emits `llm.failover`. History does not change failover classes, invent a secondary, or hard-reject the only remaining provider. Auth, policy, invalid output, `RATE_LIMIT`, and `TIMEOUT` stay on the provider that raised them.
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
- Health endpoint reports OpenAI, OpenRouter, xAI, Anthropic, Mistral, Gemini, Cohere, Ollama, vLLM, and llama.cpp configured/model status, `fallback: false`, plus a `tools` block. Ollama, vLLM, and llama.cpp also report daemon `status` (`unconfigured` / `unavailable` / `healthy`). Does not expose keys.
- Human stop: per-mission stop and global STOP ALL; in-flight and unscheduled durable unfinished missions are cancelled/stopped.
- Human question/answer: controller `ask` persists `pending_question`, emits `mission.question`, and parks in `WAITING`. `POST /api/missions/{id}/answers/{question_id}` consumes only the matching open question (`user.answered`) and the decide loop continues with `state.answers`. Unknown mission is 404; mismatch / empty / terminal / no-open-question fail closed (409 / `PolicyError`) and do not emit `user.answered`. Runtime-generated `question_id` — model-supplied ids are ignored.
- Unfinished missions resume when a configured runtime restarts. Graceful shutdown emits `mission.suspended` without fabricating STOP; interrupted text-only attempts remain `stopped` and retry under a new task ID; the original runtime deadline remains in force.
- Typed **event catalog** (`EventType` in `app/events.py`): every currently emitted name (`agent.spawned`, `mission.failed`, `llm.retry`, `llm.failover`, `verification.*`, `mission.question`, `user.answered`, `tool.completed`, …) is an enum value whose string equals the historical UI name. `emit` / `Store.append` reject unknown types and `controller.fallback`. `Store.events` still loads unknown historical rows. No event-name rename; no UI rewrite.
- Vanilla JS control room: live event stream, agent tree, inspector, activity, result panel, explicit **preview** mode labeled as non-running, **objective HUD** (`#objectiveHud`) with truthful mode/status chips, and a critical **alert stack** (`#alerts`) for real terminal events (`mission.failed` including `failure_class`, `mission.completed`, blocked, stop/stop-all) plus additive `verification.failed`. Optional Notification API only after a launch gesture, and only when the tab is hidden.
- High-stakes controller `decide` can run independent multi-planner proposals plus judge/synthesis (`app/planning.py`) through `ModelRouter` when two or more providers exist. Default N is 3 (`SWARM_PLANNER_COUNT`, clamped 2–4). OpenAI-only catalogs, trivial goals, mid-flight decides, and `SWARM_MULTI_PLANNER=0` stay single-planner. Emits real `planner.proposal` / `judge.decision` events. All-planner or judge failure stays fail-closed; no `FallbackController`. Durable recovery APIs unchanged.
- Finish is gated on a real verifier (`app/verifier.py`). Controller `finish` emits `verification.started`, then `OpenAIProvider.verify` runs a fail-closed local evidence precheck and a ModelRouter structured verdict (`pass` / `fail` / `inconclusive`). Only `pass` completes the mission. Fail or inconclusive emits `verification.failed` and fails the mission as `VERIFICATION_FAILURE`. Invalid/missing verifier JSON is inconclusive, not a pass. OpenAI-only still calls the model — never auto-passes. When two or more providers exist, verification prefers an independent catalog entry. `FallbackController` stays tests-only and uses the local evidence check only.
- Tests: runtime completion/replay, spawn limits, simulated payments, PaymentProvider seam (simulated default, live unconfigured fail-closed, factory never enables spend, injected live stub is not selected), provider failure stays failed with class, stop-all, runtime deadline/`TIMEOUT`, OpenAI usage + classified HTTP/timeout/outage errors, retry-then-success and retry-exhausted for `RATE_LIMIT`/`TIMEOUT`, non-retryable classes fail immediately, OpenRouter adapter contract + classified errors, xAI adapter contract + classified errors + unconfigured fail-closed + router registration, Anthropic Messages adapter contract + classified errors + unconfigured fail-closed + router registration, Mistral adapter contract + classified errors + unconfigured fail-closed + `MISTRAL_MODEL` does not opt in + router registration, Gemini adapter contract + classified errors + unconfigured fail-closed + router registration, Cohere adapter contract + classified errors + unconfigured fail-closed + `COHERE_MODEL` does not opt in + router registration, Ollama adapter contract + daemon-down health/outage, vLLM adapter contract + daemon-down/unconfigured health/outage, llama.cpp adapter contract + daemon-down health/outage + router registration, outage failover to secondary, both-down fail closed, OpenAI-only factory path, durable graph migration/partial backfill, versioned SQLite migrations (fresh DB, create_all-era upgrade, v1→v2 lease tables, column-add upgrade, failed upgrade does not stamp / retry is idempotent, newer-than-code fail-closed), crash/graceful restart, attempt history, original deadline, ModelRouter capability ranking + fallback chain with fakes, recent success/failure rerank + relative cost ranking + selection rationale, local_only routing to Ollama, vLLM, or llama.cpp (xAI, Anthropic, Mistral, Gemini, and Cohere stay cloud), multi-planner + judge with fakes (OpenAI-only single path, trivial skip, fail-closed), `max_tool_calls` exhausted/`TOOL_MISSING` when no provider, real local/MCP tool invoke + fail-closed MCP outage/error, controller `use_tool` then finish, controller `wait` with in-flight work (`WAITING`) vs invalid wait (`PolicyError`), verifier seed (missing verifier / fail / inconclusive stay failed, OpenAI-only no auto-pass, independent provider when a second catalog entry exists), controller `ask` parks in `WAITING` and only a matching `/answers/{question_id}` continues (mismatch / empty / terminal / unasked fail closed; resume does not fabricate an answer), typed `EventType` catalog fail-closed writes plus unknown-history replay, worker-lease claim/renew/expire/reclaim/conflict plus payment/tool idempotency replay, PolicyGate (limits, capability deny, dangerous tools, local_only, OpenAI-only/demo finish still completes).

---

## PARTIAL

| North-star idea | What exists | Gap |
| --- | --- | --- |
| Objective engine | `Mission` + `SwarmRuntime.run` loop; high-stakes `decide` may run N independent planners + one judge (`app/planning.py`) | Seed only: start-plan and finish-verification decides. No OrganizationDesigner, no multi-judge, no planner-bot spawn. Mid-flight and trivial goals stay single-planner. |
| AgentSpec | Pydantic `AgentSpec` (id, parent, role, purpose, capabilities, depth, status) | No model selection, budgets, TTL, tools, workspace, permissions, fallback models, success criteria. |
| Agent factory | `SwarmRuntime.spawn` | Controller may spawn specialists; no runtime factory API, no replace/clone/merge/kill-as-reorg. |
| Model provider | `ModelProvider` contract + OpenAI Responses + OpenRouter Chat Completions + xAI Chat Completions + Anthropic Messages + Mistral Chat Completions + Gemini Chat Completions + Cohere Chat Completions + local Ollama + local vLLM + local llama.cpp + `ModelRouter` scored selection + outage failover + in-process recent success/failure scoring + relative cost ranking | Not full north-star routing (no latency SLOs, cached-context affinity, or durable cross-process success memory). Streaming still explicit `CAPABILITY_MISMATCH`. |
| Events | Typed `EventType` catalog (`app/events.py`) for every event the runtime already emits, including `#19` `mission.question` / consumed `user.answered`, `#21` `tool.completed`, and additive `lease.claimed` / `lease.expired` / `lease.released`; writes fail closed (`UnknownEventType`); SQLite/WebSocket still persist the historical dotted strings the vanilla JS HUD already reads; unknown historical rows still replay | Missing most remaining north-star event types (replan, org change, self-mod, budget warning). Per-event payload models are not enforced yet. HUD/activity still key off the same names; no fake success animation. |
| Observability | Events, token usage on `llm.completed`, `llm.retry` on transient provider errors, activity feed, verification started/passed/failed; `llm.completed` `_meta.route` includes score, reasons, and selection `rationale` | No “why this agent”, burn rate, or external evidence runners (tests/build/HTTP). Token counts are still not money. |
| Persistence | Missions, agents, tasks, events, worker leases, and idempotency keys survive restart; unfinished text-only attempts are explicitly stopped/retried and graceful shutdown is resumable; runtime claims mission/task leases (`app/leases.py`) with heartbeat/expiry; SQLite schema is versioned (`schema_migrations`, v2) | Execution is still in-process `asyncio`. No durable job queue or out-of-process worker pool. Expired leases are reclaimable; a live lease blocks a second worker. Side-effecting payment/tool steps require an idempotency key and replay the first stored outcome. Destructive rebuilds (rename/drop column) are not in the framework yet. |
| Policy | Explicit `PolicyGate` on spawn / finish / tool use: mission limits, capability allowlist, deny-by-default dangerous tools, optional `local_only`, fail-closed `PaymentProvider` | Not a full Policy Engine. No human-approval queue, no protected-core merge rules, no authority graph. LLM can still choose among allowed text actions. Live spend stays behind `PaymentProvider`. |
| Credentials | Key stays in env/cred manager | No capability broker. Agents do not request capabilities through a broker; the process holds the OpenAI key and calls the API. |
| UI | Agent tree + inspector + objective HUD (mode/status) + critical in-app alerts | Not a game world. Preview is synthetic (explicitly labeled). No cost HUD, replay scrubber, command bar, org graph view, or Pixi/React. Alerts are terminal mission events plus real `verification.failed` — no fake work animations. |
| Human control | Stop / stop-all; controller `ask` parks the mission in `WAITING` until `POST /answers/{question_id}` consumes the matching answer | No pause/resume, approve/deny beyond this question/answer path, kill individual agent, change budget. |
| Memory | Mission JSON + event log | No scoped memory, retrieval, or learned strategy store. Each model call gets a dump of current agents/tasks. |
| Cost | `budget` / `spent` on simulated payments only; `PaymentProvider` is the spend seam | No token-cost accounting, estimates, or ResourceScheduler. Token counts are usage telemetry, not money. Live settlement adapters are not enabled. |
| Verification | Mandatory verify-before-complete seed: ModelRouter structured verdict + local fabricated-claim precheck; events; `VERIFICATION_FAILURE` fail-closed | No external evidence runners (tests, HTTP, files, deployments). No dedicated verifier agent/bot. Same-model verify when the catalog is OpenAI-only (honest call, not a skip). |
| Tools | `ToolProvider` + `LocalToolProvider` allowlist + MCP JSON-RPC stub; `max_tool_calls` charged on real `tool.started`; controller `use_tool`; health `tools` block | No browser, shell, filesystem, or self-generated registry. Default catalog is empty unless `SWARM_LOCAL_TOOLS` / `MCP_SERVER_URL` is set. Workers still cannot request tools from `WORK_FORMAT`. MCP is HTTP JSON-RPC only (no SSE transport). |
| Failure recovery | Classified failures; bounded `RATE_LIMIT`/`TIMEOUT` retry; capability-based routing; `PROVIDER_OUTAGE` may fail over along the router chain including xAI, Anthropic, Mistral, Gemini, Cohere, local Ollama, vLLM, or llama.cpp; durable restart recovery | Exhausted retries or every configured provider down still kill the mission. No replan. |

---

## MISSING

North-star systems with no implementation to extend yet:

- Additional provider adapters (DeepSeek) beyond OpenAI + OpenRouter + xAI + Anthropic + Mistral + Gemini + Cohere + Ollama + vLLM + llama.cpp.
- Durable / cross-process ModelRouter success memory, latency SLOs, and cached-context affinity. In-process recent success/failure + relative cost ranking exist.
- OrganizationDesigner, authority/delegation graph, dynamic reorg (replace/clone/merge).
- Independent verifier agents and external evidence runners (tests/build/HTTP/files) beyond the finish-gate seed.
- ResourceScheduler, cost estimation UX, conservative dollar defaults as enforced policy.
- Self-generated tools, dynamic tool registry, browser/shell/filesystem adapters beyond the allowlisted local + MCP stub.
- WorkspaceProvider / sandboxes / Docker.
- Browser (Playwright etc.).
- Live PaymentProvider adapters (Stripe/x402/isolated wallet). The fail-closed seam exists; no live spending.
- Full Policy Engine / human-approval queue / protected-core merge rules beyond the spawn/finish/tool `PolicyGate` seed; kill switch beyond stop-all.
- Self-modification workflow, self-dev agents, rollback, staging/canary.
- Long-term memory layers.
- Game-world UI (Pixi/React/Phaser), bot states as real animation, world areas, replay timeline, command bar, semantic zoom.
- Historical replay distinct from live.
- Durable job queue / out-of-process worker pool (execution is still in-process `asyncio.Task`; SQLite worker leases + idempotency keys are a seed only).
- Lint/typecheck/CI pipelines (pytest only, via `.[dev]`).

---

## BROKEN

Not “crashes on boot”, but incorrect or misleading relative to claims or unused surface:

- **README previously said** the UI falls back to an offline controller without a key, and that the default model is `gpt-5`. Code: launch returns **503** if the key is missing; default model is **`gpt-6-astra`**. README is corrected in this slice. Do not reintroduce a silent demo fallback.
- **External evidence is still missing:** the verifier judges claimed text against mission artifacts via ModelRouter. It does not run tests, hit endpoints, or hash files.
- **`FallbackController`** would request capabilities `project_work`/`report` which the live OpenAI path would reject; it is tests-only and must stay that way.

Nothing in the current test suite is known red. UI preview is synthetic by design; it must remain labeled preview.

---

## TECH DEBT

- `SwarmRuntime.run` is the orchestrator, factory, task engine, and failure handler in one module. Verification is extracted to `app/verifier.py` + `OpenAIProvider.verify`; do not grow the runtime loop further.
- Agents/tasks have durable snapshots plus append-only events and an in-memory working set. Recovery reconciles missing rows, but snapshot/event writes are not yet one atomic transaction.
- Event *payloads* are still free-form dicts. `EventType` now catalogs names; typed payload models can come with the next observability expansion.
- `LLMProvider` remains the controller+worker behavior interface layered over the lower-level `ModelProvider`. `ModelRouter` is the selection seam; do not add provider conditionals to the runtime.
- SQLite schema is versioned (`app/migrations.py`). Future column adds belong in `Migration(version=N+1)` using `add_column_if_missing`. SQLite may keep an ADD COLUMN from a failed attempt; do not stamp `schema_migrations` unless the upgrade finished. Destructive rename/drop still needs an explicit rebuild migration.
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
- Existing event names and mission JSON that the UI already understands (`agent.spawned`, `mission.failed`, `result.error`, etc.). Additive fields (`failure_class`) and additive events (`llm.retry`, `verification.started` / `passed` / `failed`, `lease.claimed` / `lease.expired` / `lease.released`) are OK.
- Keep the app startable as documented in README (`uvicorn app.main:app`).

## What already fits and should be extended

- `ModelProvider` + `OpenAIProvider` → `ModelRouter` now picks from registered providers; scoring includes recent success/failure and relative cost. Keep controller semantics.
- `AgentSpec` → add fields incrementally (model, budget, tools) rather than a new agent type.
- `Store` event log + durable agent/task rows + versioned migrations + `worker_leases` / `idempotency_keys` → later add atomic checkpoints and a real durable queue. New columns go through `app/migrations.py`, not `create_all`.
- `FailureClass` + `ProviderError`/`PolicyError` → `PolicyGate` and `ModelRouter` reuse these. Do not invent a second error framework.
- `WalletAdapter` → `PaymentProvider` (`app/payments.py`). Next: an isolated wallet service behind the same fail-closed factory — do not enable live spend from the agent process.
- `ToolProvider` → add browser/shell/HTTP adapters behind the same invoke + budget + event path. Do not bypass `max_tool_calls`.
- WebSocket event sink → `EventType` is the write catalog; UI already applies unknown events safely. Add payload schemas later without renaming existing `event_type` strings.

## What should wait / be refactored only when needed

- Do not extract more micro-interfaces until OrganizationDesigner or external evidence runners exist. `ModelRouter` remains the selection seam.
- Do not replace SQLite.
- Do not replace the control-loop with LangGraph/Agents SDK wrappers.
- Self-modification, live payment adapters, browser, and game UI are later slices.

---

## NEXT PRIORITY

**This slice:** Cohere OpenAI-compatible Chat Completions adapter (`CohereModelProvider`). Opt-in via `COHERE_API_KEY`; `COHERE_MODEL` does not opt in by itself. Registered in `ModelRouter` after Gemini when configured; OpenAI-only catalogs stay one-entry. Fail-closed unconfigured complete (`AUTHORIZATION_REQUIRED`); classified HTTP/timeout/outage/422 errors; no fake completions; keys never in responses or error strings. Health reports configured/model/`fallback: false` without probing the live API. `POST {COHERE_BASE_URL}/chat/completions` with Bearer auth (default `https://api.cohere.ai/compatibility/v1`). Rebased onto latest `origin/main` after Gemini (`#28`) and Mistral (`#29`). Did not rewrite EventType, ToolProvider/MCP, OrganizationDesigner, worker leases, PolicyGate, SQLite migrations, ModelRouter ranking, Gemini, DeepSeek (`#30`), React/Pixi, or LangGraph. Tests: `python3 -m pytest tests/ -q` → **380 passed**.

**Landed on main (keep):** Gemini (`#28`); Mistral (`#29`); ModelRouter historical success + cost-aware ranking (`#26`); Anthropic Messages (`#27`); PolicyGate (`#23`); durable worker leases / idempotency (`#22`); versioned SQLite migrations (`#24`); xAI (`#25`); typed `EventType` catalog (`#20`); ToolProvider / MCP seam (`#21`); mission answers path (`#19`); `PaymentProvider` behind `WalletAdapter` (`#18`); llama.cpp (`#17`); vLLM (`#16`); verifier seed (`#15`).

**Recommended next backend slice:** OrganizationDesigner remains reserved. Remaining cloud adapter (DeepSeek) or worker-side tool requests (`WORK_FORMAT`). Isolated live wallet is later — do not enable spending. Still fail closed. Still no game-world UI rewrite.

**Explicitly not next:** game-world UI, self-modification, Playwright, live payment settlement, OrganizationDesigner.

---

## Audit notes (repo facts)

- Tree: `app/` (runtime, policy, llm, providers, router, planning, verifier, events, tools, payments, leases, store, migrations, models, main, health, credentials, static UI), `tests/`, `scripts/check_openai.py`, `NORTH_STAR.md`, this file. No CI, no Docker, no `.env.example`.
- Dependencies: FastAPI, uvicorn, SQLAlchemy, pydantic, httpx; pytest in `dev`; `pywin32` on Windows only.
- Production providers: `OpenAIResponsesModelProvider` → `https://api.openai.com/v1/responses`; `OpenRouterModelProvider` → `{OPENROUTER_BASE_URL}/chat/completions`; `XAIModelProvider` → `{XAI_BASE_URL}/chat/completions` (default `https://api.x.ai/v1`); `AnthropicModelProvider` → `{ANTHROPIC_BASE_URL}/messages` (default `https://api.anthropic.com/v1`); `MistralModelProvider` → `{MISTRAL_BASE_URL}/chat/completions` (default `https://api.mistral.ai/v1`); `GeminiModelProvider` → `{GEMINI_BASE_URL}/chat/completions` (default `https://generativelanguage.googleapis.com/v1beta/openai`); `CohereModelProvider` → `{COHERE_BASE_URL}/chat/completions` (default `https://api.cohere.ai/compatibility/v1`); `OllamaModelProvider` → `{OLLAMA_BASE_URL}/chat/completions` (default `http://127.0.0.1:11434/v1`); `VllmModelProvider` → `{VLLM_BASE_URL}/chat/completions` (default `http://127.0.0.1:8000/v1`); `LlamaCppModelProvider` → `{LLAMACPP_BASE_URL}/chat/completions` (default `http://127.0.0.1:8080/v1`). `build_model_provider()` wraps the first two configured clouds in `FailoverModelProvider` (OpenAI, then OpenRouter, then xAI, then Anthropic, then Mistral, then Gemini, then Cohere). A single cloud provider plus the first opted-in local (Ollama, then vLLM, then llama.cpp) uses Failover(cloud, local). `build_router()` appends remaining configured adapters so xAI, Anthropic, Mistral, Gemini, Cohere, Ollama, vLLM, and llama.cpp can sit in the catalog. `build_controller()` unwraps that into `ModelRouter` for capability-based selection. `FallbackController` is a test fixture (`mode = "demo"`). Retry/backoff for `RATE_LIMIT`/`TIMEOUT` lives in `SwarmRuntime.model_call`; outage failover lives in `ModelRouter` (and `FailoverModelProvider` when used directly).
- Tests are extended in this slice rather than replaced.
- No TODOs in application code.
- Hypotheses checked: OpenAI + optional OpenRouter + optional xAI + optional Anthropic + optional Mistral + optional Gemini + optional Cohere + optional local Ollama + optional local vLLM + optional local llama.cpp behind `ModelProvider`; `ModelRouter` scores capabilities plus in-process recent success/failure and relative cost, and falls back on `PROVIDER_OUTAGE` including to xAI, Anthropic, Mistral, Gemini, Cohere, Ollama, vLLM, or llama.cpp; high-stakes `decide` can run independent planners + judge when multiple providers exist; finish requires a ModelRouter verifier (OpenAI-only still calls the model; missing/invalid/inconclusive never completes); classified `RATE_LIMIT`/`TIMEOUT` retry then fail closed; SQLite mission/agent/task snapshots plus events with versioned schema migrations (v2 adds worker leases / idempotency keys) instead of `create_all`; resumable in-process execution with truthful interrupted-attempt history; UI vanilla JS with objective HUD + critical alerts wired to existing events plus verification.failed.
