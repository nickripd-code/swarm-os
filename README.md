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
| `GEMINI_API_KEY` | Optional Gemini OpenAI-compatible Chat Completions adapter. Opt-in only; ignored when unset. |
| `GEMINI_MODEL` | Gemini model id (default `gemini-2.0-flash`). Does not opt in by itself. |
| `GEMINI_BASE_URL` | Optional Chat Completions base URL (default `https://generativelanguage.googleapis.com/v1beta/openai`). |
| `COHERE_API_KEY` | Optional Cohere OpenAI-compatible Chat Completions adapter. Opt-in only; ignored when unset. |
| `COHERE_MODEL` | Cohere model id (default `command-a-03-2025`). Does not opt in by itself. |
| `COHERE_BASE_URL` | Optional Chat Completions base URL (default `https://api.cohere.ai/compatibility/v1`). |
| `DEEPSEEK_API_KEY` | Optional DeepSeek OpenAI-compatible Chat Completions adapter. Opt-in only; ignored when unset. |
| `DEEPSEEK_MODEL` | DeepSeek model id (default `deepseek-chat`). Does not opt in by itself. |
| `DEEPSEEK_BASE_URL` | Optional Chat Completions base URL (default `https://api.deepseek.com/v1`). |
| `TOGETHER_API_KEY` | Optional Together AI OpenAI-compatible Chat Completions adapter. Opt-in only; ignored when unset. |
| `TOGETHER_MODEL` | Together model id (default `meta-llama/Llama-3.3-70B-Instruct-Turbo`). Does not opt in by itself. |
| `TOGETHER_BASE_URL` | Optional Chat Completions base URL (default `https://api.together.ai/v1`). |
| `GROQ_API_KEY` | Optional Groq OpenAI-compatible Chat Completions adapter. Opt-in only; ignored when unset. |
| `GROQ_MODEL` | Groq model id (default `openai/gpt-oss-120b`). Does not opt in by itself. |
| `GROQ_BASE_URL` | Optional Chat Completions base URL (default `https://api.groq.com/openai/v1`). |
| `FIREWORKS_API_KEY` | Optional Fireworks AI OpenAI-compatible Chat Completions adapter. Opt-in only; ignored when unset. |
| `FIREWORKS_MODEL` | Fireworks model id (default `accounts/fireworks/models/llama-v3p1-8b-instruct`). Does not opt in by itself. |
| `FIREWORKS_BASE_URL` | Optional Chat Completions base URL (default `https://api.fireworks.ai/inference/v1`). |
| `AZURE_OPENAI_API_KEY` | Optional Azure OpenAI Chat Completions adapter. Opt-in only together with endpoint and deployment. |
| `AZURE_OPENAI_ENDPOINT` | Azure resource root (example `https://{resource}.openai.azure.com`). Required to opt in; does not opt in by itself. |
| `AZURE_OPENAI_DEPLOYMENT` | Azure deployment name used as the catalog model id. Required to opt in; does not opt in by itself. |
| `AZURE_OPENAI_API_VERSION` | Optional Azure API version query (default `2024-10-21`). Does not opt in by itself. |
| `PERPLEXITY_API_KEY` | Optional Perplexity OpenAI-compatible Chat Completions adapter. Opt-in only; ignored when unset. |
| `PERPLEXITY_MODEL` | Perplexity model id (default `sonar`). Does not opt in by itself. |
| `PERPLEXITY_BASE_URL` | Optional Chat Completions base URL (default `https://api.perplexity.ai`). |
| `BEDROCK_API_KEY` | Optional AWS Bedrock Converse adapter. Opt-in only; ignored when unset. `AWS_BEARER_TOKEN_BEDROCK` is accepted as the AWS alias. |
| `BEDROCK_MODEL` | Bedrock model id (default `amazon.nova-lite-v1:0`). Does not opt in by itself. |
| `BEDROCK_REGION` | Bedrock runtime region (default `us-east-1`). Does not opt in by itself. |
| `BEDROCK_BASE_URL` | Optional Converse base URL (default `https://bedrock-runtime.{region}.amazonaws.com`). Does not opt in by itself. |
| `HUGGINGFACE_API_KEY` | Optional Hugging Face Inference OpenAI-compatible Chat Completions adapter. Opt-in only; ignored when unset. |
| `HUGGINGFACE_MODEL` | Hugging Face model id (default `meta-llama/Llama-3.1-8B-Instruct`). Does not opt in by itself. |
| `HUGGINGFACE_BASE_URL` | Optional Chat Completions base URL (default `https://router.huggingface.co/v1`). |
| `CEREBRAS_API_KEY` | Optional Cerebras OpenAI-compatible Chat Completions adapter. Opt-in only; ignored when unset. |
| `CEREBRAS_MODEL` | Cerebras model id (default `llama-3.3-70b`). Does not opt in by itself. |
| `CEREBRAS_BASE_URL` | Optional Chat Completions base URL (default `https://api.cerebras.ai/v1`). |
| `SAMBANOVA_API_KEY` | Optional SambaNova Cloud OpenAI-compatible Chat Completions adapter. Opt-in only; ignored when unset. |
| `SAMBANOVA_MODEL` | SambaNova model id (default `Meta-Llama-3.3-70B-Instruct`). Does not opt in by itself. |
| `SAMBANOVA_BASE_URL` | Optional Chat Completions base URL (default `https://api.sambanova.ai/v1`). |
| `VERTEX_API_KEY` | Optional Google Cloud Vertex AI Gemini `generateContent` adapter. Opt-in only together with a project. Distinct from consumer `GEMINI_API_KEY`. |
| `VERTEX_PROJECT` | Google Cloud project id. Required to opt in; does not opt in by itself. `GOOGLE_CLOUD_PROJECT` is accepted as the GCP alias. |
| `VERTEX_LOCATION` | Vertex region (default `us-central1`). Does not opt in by itself. |
| `VERTEX_MODEL` | Vertex Gemini model id (default `gemini-2.0-flash`). Does not opt in by itself. |
| `VERTEX_BASE_URL` | Optional Vertex host (default `https://{location}-aiplatform.googleapis.com`). Does not opt in by itself. |
| `OLLAMA_BASE_URL` | Opt-in local OpenAI-compatible Ollama server (default `http://127.0.0.1:11434/v1` when opted in). |
| `OLLAMA_MODEL` | Optional Ollama model id. Setting this (or `OLLAMA_BASE_URL`) registers the local adapter in the router catalog. |
| `VLLM_BASE_URL` | Opt-in local OpenAI-compatible vLLM server (default `http://127.0.0.1:8000/v1` when opted in). Set this if Mission Control and vLLM would otherwise share port 8000. |
| `VLLM_MODEL` | Optional vLLM model id. Setting this (or `VLLM_BASE_URL`) registers the local adapter in the router catalog. |
| `LLAMACPP_BASE_URL` | Opt-in local OpenAI-compatible llama.cpp server (default `http://127.0.0.1:8080/v1` when opted in). |
| `LLAMACPP_MODEL` | Optional llama.cpp model id. Setting this (or `LLAMACPP_BASE_URL`) registers the local adapter in the router catalog. |
| `SWARM_LOCAL_TOOLS` | Optional comma-separated allowlist of in-process tools (`echo`, `clock.utc`, `hash.sha256`). Empty means no local tools. |
| `MCP_SERVER_URL` | Optional JSON-RPC MCP endpoint. Unset stays out of the catalog; unreachable calls fail closed. |
| `MCP_API_KEY` | Optional bearer token for `MCP_SERVER_URL`. Never logged, never returned over HTTP, never placed in model context. |
| `SWARM_BROWSER` | Optional Playwright browser tools (`browser.navigate`, `browser.snapshot`, `browser.click`). Unset stays disabled and PolicyGate still denies browser tools. Set to `1`/`true`/`yes`/`on` to opt in. Requires `pip install -e ".[browser]"` and `playwright install chromium` for a live driver; CI uses fakes and does not browse. |
| `SWARM_SELFMOD` | Optional self-modification sandbox (`selfmod.propose`, `selfmod.diff`). Unset stays disabled and PolicyGate still denies `selfmod.*`. Set to `1`/`true`/`yes`/`on` to opt in. Default is dry-run/diff only — proposals are not applied. |
| `SWARM_SELFMOD_WRITE` | Second flag required for `selfmod.apply`. Writes go to an isolated sandbox directory, not the production tree. Unset keeps apply denied even if `SWARM_SELFMOD` is set. |
| `SWARM_SELFMOD_PRODUCTION_WRITE` | Third flag required before apply may write into the production source tree. Protected core files (`app/policy.py`, credentials, payments, selfmod policy, leases) are still refused. Unset never writes production files. |
| `SWARM_SELFMOD_SANDBOX` | Optional sandbox directory for apply. Defaults to a temp directory. If this path is inside the production tree, apply still requires `SWARM_SELFMOD_PRODUCTION_WRITE`. |
| `SWARM_DEFAULT_TOKEN_BUDGET` | Conservative mission token-cost budget in USD (default `3`). Separate from simulated payment `budget`. |
| `SWARM_TOKEN_BUDGET_HARD_CAP` | Hard cap applied to `max_token_cost` / the default budget (default `10`). |
| `SWARM_TOKEN_PRICE_INPUT_PER_MILLION` | Conservative USD per million input tokens when the catalog omits listed prices (default `15`). Empty disables the default. |
| `SWARM_TOKEN_PRICE_OUTPUT_PER_MILLION` | Conservative USD per million output/reasoning tokens when the catalog omits listed prices (default `60`). Empty disables the default. |
| `SWARM_TOKEN_COST_MARKUP` | Multiplier applied to token estimates (default `1.25`). |
| `SWARM_TOKEN_BUDGET_WARNING_FRACTION` | Emit `budget.warning` when estimated token spend crosses this fraction of the budget (default `0.8`). |
| `SWARM_TOKEN_UNKNOWN_PRICE` | `fail` (default) refuses a billed call when prices cannot be estimated; `skip` records `known: false` and does not invent a dollar amount. |

With only `OPENAI_API_KEY`, behavior matches the previous OpenAI-only wiring: the router has a one-model catalog. `RATE_LIMIT` and `TIMEOUT` still retry on the same adapter; they do not fail over. Auth, policy, and invalid-output errors also stay on the provider that raised them. If both OpenAI and OpenRouter are down, a configured xAI, Anthropic, Mistral, Gemini, Cohere, DeepSeek, Together, Groq, Fireworks, Azure OpenAI, Perplexity, Bedrock, Hugging Face, Cerebras, SambaNova, or Vertex AI key or a configured Ollama, vLLM, or llama.cpp daemon may serve as the next fallback. If every configured provider is down or none is configured, the result is `{error, failure_class}` — never `FallbackController`. A down Ollama, vLLM, or llama.cpp daemon is reported `unavailable` and never invents a completion. An unset `XAI_API_KEY`, `ANTHROPIC_API_KEY`, `MISTRAL_API_KEY`, `GEMINI_API_KEY`, `COHERE_API_KEY`, `DEEPSEEK_API_KEY`, `TOGETHER_API_KEY`, `GROQ_API_KEY`, `FIREWORKS_API_KEY`, `PERPLEXITY_API_KEY`, `BEDROCK_API_KEY`, `HUGGINGFACE_API_KEY`, `CEREBRAS_API_KEY`, or `SAMBANOVA_API_KEY` is reported `unconfigured`; a set key is reported as configured without probing the live API. Azure OpenAI reports `unconfigured` unless `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, and `AZURE_OPENAI_DEPLOYMENT` are all set; a full opt-in is reported as configured without probing the live API. Bedrock also accepts `AWS_BEARER_TOKEN_BEDROCK` as an alias; ambient IAM keys do not opt in. Vertex AI reports `unconfigured` unless `VERTEX_API_KEY` and `VERTEX_PROJECT` (or `GOOGLE_CLOUD_PROJECT`) are set; `GEMINI_API_KEY`, `VERTEX_MODEL`, `VERTEX_LOCATION`, `VERTEX_BASE_URL`, and ambient ADC do not opt in. A full Vertex opt-in is reported as configured without probing the live API.

## Safety defaults

The runtime enforces mission-wide depth, agent, task, tool-call, runtime, payment, and estimated token-cost limits through an explicit `PolicyGate` before spawn, finish, and tool use, plus `ResourceScheduler` on the model-call path. Dangerous actions (shell, browser, network, live payment, deploy, self-modification) are denied by default. `SWARM_BROWSER` opts in the Playwright `browser.navigate` / `browser.snapshot` / `browser.click` tools only; other dangerous names stay refused, and `local_only` still forbids them. `SWARM_SELFMOD` opts in `selfmod.propose` / `selfmod.diff` (dry-run only). `selfmod.apply` additionally requires `SWARM_SELFMOD_WRITE` and still writes a sandbox unless `SWARM_SELFMOD_PRODUCTION_WRITE` is set; protected core files cannot be applied. Optional mission `privacy=local_only` forbids cloud/network tools and is forwarded to `ModelRouter` capability requests. Payments go through `PaymentProvider` behind `WalletAdapter` and are simulated by default. Token USD estimates are separate from wallet `spent` and fail closed as `RESOURCE_EXHAUSTED` when the remaining token budget cannot cover a known estimate (or when price metadata is missing and `SWARM_TOKEN_UNKNOWN_PRICE=fail`). Live settlement intentionally fails closed until an isolated wallet is configured; private keys must remain outside the agent process. This slice does not enable live spending. Transient `RATE_LIMIT` and `TIMEOUT` provider errors are retried with bounded exponential backoff (3 retries, 0.5s / 1s / 2s) against the same adapter. Classified `PROVIDER_OUTAGE` (or an unconfigured primary) may use the next model in the router fallback chain (OpenRouter when `OPENROUTER_API_KEY` is set; xAI when `XAI_API_KEY` is set; Anthropic when `ANTHROPIC_API_KEY` is set; Mistral when `MISTRAL_API_KEY` is set; Gemini when `GEMINI_API_KEY` is set; Cohere when `COHERE_API_KEY` is set; DeepSeek when `DEEPSEEK_API_KEY` is set; Together when `TOGETHER_API_KEY` is set; Groq when `GROQ_API_KEY` is set; Fireworks when `FIREWORKS_API_KEY` is set; Azure OpenAI when `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, and `AZURE_OPENAI_DEPLOYMENT` are set; Perplexity when `PERPLEXITY_API_KEY` is set; Bedrock when `BEDROCK_API_KEY` or `AWS_BEARER_TOKEN_BEDROCK` is set; Hugging Face when `HUGGINGFACE_API_KEY` is set; Cerebras when `CEREBRAS_API_KEY` is set; SambaNova when `SAMBANOVA_API_KEY` is set; Vertex AI when `VERTEX_API_KEY` and `VERTEX_PROJECT` (or `GOOGLE_CLOUD_PROJECT`) are set; Ollama when `OLLAMA_MODEL` or `OLLAMA_BASE_URL` is set; vLLM when `VLLM_MODEL` or `VLLM_BASE_URL` is set; llama.cpp when `LLAMACPP_MODEL` or `LLAMACPP_BASE_URL` is set). Exhausted retries or a failed failover still fail closed with `{error, failure_class}`.

Mission, agent, task, event, worker-lease, and idempotency state is durable in SQLite. Schema is applied by versioned migrations (`app/migrations.py`); existing create_all-era databases are upgraded in place and rows are not dropped. A graceful server shutdown suspends active execution without converting it into a user stop; the next configured runtime resumes it against the original mission deadline. An interrupted text-only task is retained as a stopped attempt and retried under a new task ID. Mission and task worker leases heartbeat and expire so a restarted process can reclaim unfinished work; a live lease blocks a second worker. Payments and tool invokes go through an idempotency key path and replay the first stored outcome instead of running twice. Tools run only through `ToolProvider`: allowlisted local tools, an MCP JSON-RPC stub, an optional Playwright browser provider (`SWARM_BROWSER`), and an optional self-modification sandbox (`SWARM_SELFMOD`). Controller `use_tool` and worker `WORK_FORMAT` status `use_tool` both go through `PolicyGate` then `invoke_tool`. Unconfigured or unknown tools fail `TOOL_MISSING` without charging `max_tool_calls`. A real invoke emits `tool.started` then `tool.completed` or `tool.failed` — never a fabricated success. Browser health is `unconfigured` until opted in, `unavailable` if Playwright is missing, and never reports a successful browse without a driver result. Self-mod health is `unconfigured` until opted in and never reports an applied production write unless the write flags are set and apply actually ran.

## Next integration seams

- Add concrete research, code, messaging, HTTP, and fuller computer-use adapters behind `ToolProvider`. The Playwright browser seed exists and stays disabled by default.
- Extend the self-modification sandbox (`app/selfmod.py`) with isolated worktrees, tests/review, and rollback. Propose/diff is the default; do not enable production writes from the agent process.
- Implement an isolated EVM wallet service behind `PaymentProvider` / `WalletAdapter` with recipient/asset/amount policy checks. Do not enable live spend from the agent process.

See [ImplementationStatus.md](ImplementationStatus.md) for the recommended next slice.
