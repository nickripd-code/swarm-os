# Agent Swarm

Local FastAPI MVP for goal-driven, cooperating agents.

## Run

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
\.venv\Scripts\python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. The mission controller uses the OpenAI Responses API when `OPENAI_API_KEY` is configured and falls back to an offline controller when it is not. The default model is `gpt-5`; override it with `SWARM_MODEL` when needed.

## Safety defaults

The runtime enforces mission-wide depth, agent, task, tool-call, runtime, and payment limits. Payments are simulated by default. Live mainnet settlement intentionally fails closed until a real wallet adapter is configured; private keys must remain outside the agent process.

## Next integration seams

- Add richer LLM decision schemas and provider routing for different agent roles.
- Add concrete research, code, messaging, and HTTP tool adapters.
- Implement an isolated EVM wallet service behind `WalletAdapter` with recipient/asset/amount policy checks.
