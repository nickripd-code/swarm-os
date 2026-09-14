# Agent Swarm

Local FastAPI MVP for goal-driven, cooperating agents.

This repo is being evolved toward the Autonomous Organization OS described in [NORTH_STAR.md](NORTH_STAR.md). That document is the product vision, not a description of what already runs. Honest current capability vs that vision is in [ImplementationStatus.md](ImplementationStatus.md).

## Run

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. The mission controller uses the OpenAI Responses API through the provider-independent contract in `app/providers.py` when `OPENAI_API_KEY` is configured and fails closed when it is not (no demo substitute). The default model is `gpt-6-astra`; override it with `SWARM_MODEL` when needed.

## Safety defaults

The runtime enforces mission-wide depth, agent, task, tool-call, runtime, and payment limits. Payments are simulated by default. Live mainnet settlement intentionally fails closed until a real wallet adapter is configured; private keys must remain outside the agent process. Transient `RATE_LIMIT` and `TIMEOUT` provider errors are retried with bounded exponential backoff (3 retries, 0.5s / 1s / 2s) against the same OpenAI adapter. If retries exhaust, the mission fails closed with `{error, failure_class}` — no demo fallback.

Unfinished text-only missions are rehydrated from SQLite and the event log after a process/server restart. An interrupted model task is recorded as stopped and retried as a new attempt; the original mission runtime deadline is preserved. This recovery path does not yet cover external tool side effects, because real tool providers are not connected.

## Next integration seams

- Add a provider registry/router and a real second provider adapter behind the existing model contract.
- Add concrete research, code, messaging, and HTTP tool adapters.
- Implement an isolated EVM wallet service behind `WalletAdapter` with recipient/asset/amount policy checks.

See [ImplementationStatus.md](ImplementationStatus.md) for the recommended next slice.
