# Agent Swarm

Local FastAPI MVP for goal-driven, cooperating agents.

This repo is being evolved toward the Autonomous Organization OS described in [NORTH_STAR.md](NORTH_STAR.md). That document is the product vision, not a description of what already runs. Honest current capability vs that vision is in [ImplementationStatus.md](ImplementationStatus.md).

## Run

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. The mission controller talks to models through the provider-independent contract in `app/providers.py`. There is no demo substitute: if no provider is configured or every configured provider fails, the mission fails closed.

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

With only `OPENAI_API_KEY`, behavior matches the previous OpenAI-only wiring. `RATE_LIMIT` and `TIMEOUT` still retry on the same adapter; they do not fail over. Auth, policy, and invalid-output errors also stay on the provider that raised them. If both providers are down or neither is configured, the result is `{error, failure_class}` — never `FallbackController`.

## Safety defaults

The runtime enforces mission-wide depth, agent, task, tool-call, runtime, and payment limits. Payments are simulated by default. Live mainnet settlement intentionally fails closed until a real wallet adapter is configured; private keys must remain outside the agent process. Transient `RATE_LIMIT` and `TIMEOUT` provider errors are retried with bounded exponential backoff (3 retries, 0.5s / 1s / 2s) against the same adapter. Classified `PROVIDER_OUTAGE` (or an unconfigured primary) may use OpenRouter when `OPENROUTER_API_KEY` is set. Exhausted retries or a failed failover still fail closed with `{error, failure_class}`.

Mission, agent, task, and event state is durable in SQLite. A graceful server shutdown suspends active execution without converting it into a user stop; the next configured runtime resumes it against the original mission deadline. An interrupted text-only task is retained as a stopped attempt and retried under a new task ID. External tools are not connected yet, so side-effect idempotency is not claimed.

## Next integration seams

- Wire the provider-neutral registry/router in `app/routing.py` into `AgentSpec` and the runtime agent factory. It already produces ranked primary/fallback plans with hard capability, budget, latency, context and privacy filters; live mission execution still uses the fixed OpenAI/OpenRouter outage path.
- Add concrete research, code, messaging, and HTTP tool adapters.
- Implement an isolated EVM wallet service behind `WalletAdapter` with recipient/asset/amount policy checks.

See [ImplementationStatus.md](ImplementationStatus.md) for the recommended next slice.
