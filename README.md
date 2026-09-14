# Agent Swarm

Local FastAPI MVP for goal-driven, cooperating agents.

This repo is being evolved toward the Autonomous Organization OS described in [NORTH_STAR.md](NORTH_STAR.md). That document is the product vision, not a description of what already runs. Honest current capability vs that vision is in [ImplementationStatus.md](ImplementationStatus.md).

## Run

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. The mission controller talks to models through the provider-independent contract in `app/providers.py`. Controller and workers request capabilities (reasoning, coding, tools, context, cost, privacy); `ModelRouter` selects from registered providers. There is no demo substitute: if no provider is configured or every configured provider fails, the mission fails closed.

## Model providers

Set keys in the environment only. Never commit them, log them, or return them over HTTP.

| Variable | Role |
| --- | --- |
| `OPENAI_API_KEY` | Primary provider. Existing OpenAI Responses path when this is the only key set. |
| `SWARM_MODEL` | OpenAI model id (default `gpt-6-astra`). |
| `SWARM_REASONING_EFFORT` | Reasoning effort for both adapters (default `high`). |
| `OPENROUTER_API_KEY` | Secondary OpenAI-compatible gateway (OpenRouter). Used when the primary is unconfigured/unavailable or raises `PROVIDER_OUTAGE`. |
| `OPENROUTER_MODEL` | OpenRouter model id (default `openai/gpt-4o`). |
| `OPENROUTER_BASE_URL` | Optional Chat Completions base URL (default `https://openrouter.ai/api/v1`). |
| `OPENROUTER_SITE_URL` / `OPENROUTER_TITLE` | Optional OpenRouter attribution headers. |
| `XAI_API_KEY` | Optional xAI Grok Chat Completions adapter. Opt-in only; ignored when unset. |
| `XAI_MODEL` | xAI model id (default `grok-3`). Does not opt in by itself. |
| `XAI_BASE_URL` | Optional Chat Completions base URL (default `https://api.x.ai/v1`). |
| `ANTHROPIC_API_KEY` | Optional Anthropic Messages adapter. Opt-in only; ignored when unset. |
| `ANTHROPIC_MODEL` | Anthropic model id (default `claude-sonnet-4-5`). Does not opt in by itself. |
| `ANTHROPIC_BASE_URL` | Optional Messages base URL (default `https://api.anthropic.com/v1`). |
| `MISTRAL_API_KEY` | Optional Mistral OpenAI-compatible Chat Completions adapter. Opt-in only; ignored when unset. |
| `MISTRAL_MODEL` | Mistral model id (default `mistral-small-latest`). Does not opt in by itself. |
| `MISTRAL_BASE_URL` | Optional Chat Completions base URL (default `https://api.mistral.ai/v1`). |
| `OLLAMA_BASE_URL` | Opt-in local OpenAI-compatible Ollama server (default `http://127.0.0.1:11434/v1` when opted in). |
| `OLLAMA_MODEL` | Optional Ollama model id. Setting this (or `OLLAMA_BASE_URL`) registers the local adapter in the router catalog. |
| `VLLM_BASE_URL` | Opt-in local OpenAI-compatible vLLM server (default `http://127.0.0.1:8000/v1` when opted in). Set this if Mission Control and vLLM would otherwise share port 8000. |
| `VLLM_MODEL` | Optional vLLM model id. Setting this (or `VLLM_BASE_URL`) registers the local adapter in the router catalog. |
| `LLAMACPP_BASE_URL` | Opt-in local OpenAI-compatible llama.cpp server (default `http://127.0.0.1:8080/v1` when opted in). |
| `LLAMACPP_MODEL` | Optional llama.cpp model id. Setting this (or `LLAMACPP_BASE_URL`) registers the local adapter in the router catalog. |
| `SWARM_LOCAL_TOOLS` | Optional comma-separated allowlist of in-process tools (`echo`, `clock.utc`, `hash.sha256`). Empty means no local tools. |
| `MCP_SERVER_URL` | Optional JSON-RPC MCP endpoint. Unset stays out of the catalog; unreachable calls fail closed. |
| `MCP_API_KEY` | Optional bearer token for `MCP_SERVER_URL`. Never logged, never returned over HTTP, never placed in model context. |

With only `OPENAI_API_KEY`, behavior matches the previous OpenAI-only wiring: the router has a one-model catalog. `RATE_LIMIT` and `TIMEOUT` still retry on the same adapter; they do not fail over. Auth, policy, and invalid-output errors also stay on the provider that raised them. If both OpenAI and OpenRouter are down, a configured xAI, Anthropic, or Mistral key or a configured Ollama, vLLM, or llama.cpp daemon may serve as the next fallback. If every configured provider is down or none is configured, the result is `{error, failure_class}` — never `FallbackController`. A down Ollama, vLLM, or llama.cpp daemon is reported `unavailable` and never invents a completion. An unset `XAI_API_KEY`, `ANTHROPIC_API_KEY`, or `MISTRAL_API_KEY` is reported `unconfigured`; a set key is reported as configured without probing the live API.

## Safety defaults

The runtime enforces mission-wide depth, agent, task, tool-call, runtime, and payment limits through an explicit `PolicyGate` before spawn, finish, and tool use. Dangerous actions (shell, browser, network, live payment, deploy) are denied by default. Optional mission `privacy=local_only` forbids cloud/network tools and is forwarded to `ModelRouter` capability requests. Payments go through `PaymentProvider` behind `WalletAdapter` and are simulated by default. Live settlement intentionally fails closed until an isolated wallet is configured; private keys must remain outside the agent process. This slice does not enable live spending. Transient `RATE_LIMIT` and `TIMEOUT` provider errors are retried with bounded exponential backoff (3 retries, 0.5s / 1s / 2s) against the same adapter. Classified `PROVIDER_OUTAGE` (or an unconfigured primary) may use the next model in the router fallback chain (OpenRouter when `OPENROUTER_API_KEY` is set; xAI when `XAI_API_KEY` is set; Anthropic when `ANTHROPIC_API_KEY` is set; Mistral when `MISTRAL_API_KEY` is set; Ollama when `OLLAMA_MODEL` or `OLLAMA_BASE_URL` is set; vLLM when `VLLM_MODEL` or `VLLM_BASE_URL` is set; llama.cpp when `LLAMACPP_MODEL` or `LLAMACPP_BASE_URL` is set). Exhausted retries or a failed failover still fail closed with `{error, failure_class}`.

Mission, agent, task, event, worker-lease, and idempotency state is durable in SQLite. Schema is applied by versioned migrations (`app/migrations.py`); existing create_all-era databases are upgraded in place and rows are not dropped. A graceful server shutdown suspends active execution without converting it into a user stop; the next configured runtime resumes it against the original mission deadline. An interrupted text-only task is retained as a stopped attempt and retried under a new task ID. Mission and task worker leases heartbeat and expire so a restarted process can reclaim unfinished work; a live lease blocks a second worker. Payments and tool invokes go through an idempotency key path and replay the first stored outcome instead of running twice. Tools run only through `ToolProvider`: allowlisted local tools and/or an MCP JSON-RPC stub. Unconfigured or unknown tools fail `TOOL_MISSING` without charging `max_tool_calls`. A real invoke emits `tool.started` then `tool.completed` or `tool.failed` — never a fabricated success.

## Next integration seams

- Add concrete research, code, messaging, browser, and HTTP tool adapters behind `ToolProvider`.
- Implement an isolated EVM wallet service behind `PaymentProvider` / `WalletAdapter` with recipient/asset/amount policy checks. Do not enable live spend from the agent process.

See [ImplementationStatus.md](ImplementationStatus.md) for the recommended next slice.
