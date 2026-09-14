# SWARM OS / AUTONOMOUS ORGANIZATION OS
## MASTER BUILD PROMPT FOR CODEX

You are continuing development of an EXISTING project.

DO NOT create a new repository.
DO NOT restart from scratch.
DO NOT replace working systems merely because another architecture appears cleaner.
DO NOT build a disconnected prototype.
DO NOT build a fake animated demo.
DO NOT stop at architecture documents if implementation can continue.
DO NOT silently delete or rewrite working functionality.

This project is already under active development.

Your first responsibility is to inspect the complete current repository, understand what is already implemented, identify partially implemented systems, existing architectural decisions, technical debt, tests, runtime behavior, current frontend/backend integration, and then progressively transform the CURRENT codebase into the system described below.

The goal is not to produce a toy multi-agent demo.

The goal is to build a real persistent, provider-agnostic, multi-LLM Autonomous Organization OS with a game-like real-time interface that truthfully represents what the swarm is actually doing.

---

# 1. PRODUCT DEFINITION

We are building:

AUTONOMOUS ORGANIZATION OS
/
MULTI-LLM SWARM OS
/
DYNAMIC AGENT OPERATING SYSTEM

The user provides an OBJECTIVE.

The system dynamically determines:

- what work is required;
- how to decompose the objective;
- whether one agent or many agents are required;
- which temporary roles should exist;
- which LLM should power each role;
- which tools/capabilities each agent needs;
- how agents communicate;
- which tasks should run sequentially or concurrently;
- which tasks need independent parallel attempts;
- how much token/API/compute budget each branch deserves;
- which agents should be replaced, cloned, merged, killed, or reorganized;
- whether a new capability needs to be built;
- whether its own codebase needs improvement;
- whether the objective has actually been achieved.

The organization itself is mutable runtime state.

The product is NOT primarily:

- a chatbot;
- a fixed agent team;
- a static workflow;
- a wrapper around one LLM;
- a coding assistant;
- a dashboard;
- a generic agent framework.

The product thesis is:

> Give the system an objective.
> Watch it build the organization required to achieve it.

---

# 2. CORE OPERATING PRINCIPLE

THE OBJECTIVE IS MORE IMPORTANT THAN ANY INDIVIDUAL AGENT OR LLM.

No individual model is authoritative.

No individual model failure should terminate an objective.

No individual agent failure should terminate an objective.

No provider outage should terminate an objective.

No single low-confidence answer should be treated as final truth.

If a particular agent/model/provider cannot complete a legitimate task, the system should explore alternative valid execution paths such as:

- another model;
- another provider;
- a local model;
- another specialized agent;
- legitimate task decomposition;
- alternative planning;
- alternative tools;
- parallel independent attempts;
- stronger reasoning;
- a specialist model;
- an independent judge;
- multiple judges;
- a different organization topology;
- a different workspace;
- a newly built internal tool.

The objective should remain alive until one of the following is true:

1. success is externally VERIFIED;
2. the objective is technically infeasible;
3. allowed resource/budget limits are exhausted;
4. required authorization is unavailable;
5. the independent policy layer blocks the real-world action.

The intended hierarchy is:

POLICY
>
OBJECTIVE
>
INDIVIDUAL MODEL / AGENT

Within the permitted execution space:

OBJECTIVE > INDIVIDUAL MODEL.

IMPORTANT:

Do NOT implement an automated system whose purpose is defeating another provider's safety controls through jailbreaks, deceptive obfuscation, or reformulation/decomposition specifically intended to bypass safeguards.

A refusal must be classified.

Legitimate capability failures may trigger alternative execution.

Provider-policy refusals should route through the independent policy/human-review path.

---

# 3. FIRST PHASE: AUDIT THE EXISTING PROJECT

Before major architectural changes:

1. Inspect the COMPLETE repository tree.
2. Read README and architecture docs.
3. Inspect package manifests and dependencies.
4. Inspect environment/configuration files without exposing secrets.
5. Identify all current model integrations.
6. Identify agent abstractions.
7. Identify orchestrator/planner logic.
8. Identify worker/executor logic.
9. Identify memory/state implementation.
10. Identify task/objective schemas.
11. Identify tool execution architecture.
12. Identify browser/computer-use capabilities.
13. Identify shell/code execution.
14. Identify persistence/checkpointing.
15. Identify database schema and migrations.
16. Identify queues/background workers.
17. Inspect current API.
18. Inspect frontend.
19. Inspect current real-time event support.
20. Inspect current tests.
21. Inspect lint/typecheck/build pipelines.
22. Inspect TODOs and unfinished features.
23. Inspect git status.
24. Inspect recent commits/direction where available.
25. Run the project and tests where practical.

Do NOT ask the user to explain functionality that can be discovered from the repository.

Create or update:

ImplementationStatus.md

Maintain clear sections:

DONE
PARTIAL
MISSING
BROKEN
TECH DEBT
NEXT PRIORITY

Also document:

- existing working systems that should remain untouched;
- existing abstractions that already fit the target architecture;
- systems that should be extended;
- systems that should be refactored;
- concrete missing primitives;
- immediate next implementation step.

Then CONTINUE IMPLEMENTING.

Do not stop with a report unless actual execution is blocked.

---

# 4. HIGH-LEVEL TARGET ARCHITECTURE

Conceptually:

OBJECTIVE
    ↓
META ORCHESTRATOR
    ↓
MULTIPLE INDEPENDENT PLANNERS
    ↓
JUDGE / SYNTHESIS
    ↓
ORGANIZATION DESIGNER
    ↓
AGENT FACTORY
    ↓
DYNAMIC ORGANIZATION
    ↓
TASK GRAPH
    ↓
TOOLS / APIS / BROWSERS / WORKSPACES
    ↓
VERIFIERS
    ↓
SUCCESS?
  ┌───────────────┐
 YES             NO
  ↓               ↓
MEMORY        REPLAN
              REORGANIZE
              CHANGE MODEL
              CHANGE TOOL
              SPAWN AGENT
              KILL AGENT
              RETRY
              BUILD CAPABILITY
              SELF-IMPROVE
                  │
                  └───────↺

Cross-cutting layers:

RESOURCE SCHEDULER
POLICY ENGINE
STATE STORE
MEMORY STORE
EVENT BUS
OBSERVABILITY
CREDENTIAL BROKER
MODEL ROUTER
CAPABILITY BROKER

---

# 5. CORE INTERNAL INTERFACES

Prefer small replaceable abstractions such as:

ModelProvider
ModelRouter
AgentRuntime
AgentFactory
OrganizationDesigner
ObjectiveEngine
TaskEngine
WorkspaceProvider
ToolProvider
CredentialBroker
CapabilityBroker
StateStore
MemoryStore
PaymentProvider
PolicyEngine
Verifier
ResourceScheduler
EventBus
ReplayStore
CostEstimator

Avoid giant god classes.

External providers/frameworks must remain implementation details behind OUR interfaces.

---

# 6. MODEL PROVIDER ARCHITECTURE

The swarm must be provider-agnostic.

Support major commercial LLM ecosystems through adapters where practical:

- OpenAI
- Anthropic
- Google Gemini
- xAI
- Mistral
- DeepSeek
- Cohere
- OpenAI-compatible providers
- model gateways / aggregators

Support local/self-hosted inference:

- Ollama
- vLLM
- llama.cpp
- OpenAI-compatible local servers
- custom inference endpoints

There must be NO core architecture like:

if model == "gpt":
    ...

Create a unified provider contract.

Conceptual interface:

ModelProvider

- listModels()
- complete()
- stream()
- capabilities()
- health()
- estimateCost()
- getUsage()
- contextLimits()

Model metadata should include where known:

- provider
- model
- local/cloud
- context window
- reasoning ability
- coding ability
- vision
- tool use
- structured outputs
- latency
- price
- historical reliability
- current availability
- privacy characteristics
- rate limits
- cached-input behavior

---

# 7. MINIMIZE EXTERNAL API KEYS

A core architectural rule:

MINIMIZE EXTERNAL CREDENTIALS.

Do NOT require one direct provider account for every model unless there is a concrete benefit.

Prefer:

- model gateways;
- OAuth tool brokers;
- MCP;
- local inference;
- standardized adapters;
- provider abstraction.

Initial practical configuration should be capable of operating with approximately:

OPENROUTER_API_KEY
OPENAI_API_KEY

plus optional integrations later.

A gateway such as OpenRouter can provide access to many model families through one credential.

Direct OpenAI access may remain useful for specialized OpenAI/Codex-specific capabilities.

Local models should work without external provider credentials.

Initial minimal strategy:

OPENROUTER_API_KEY
OPENAI_API_KEY

Local:
Ollama / vLLM
NO EXTERNAL API KEY

Browser:
Playwright
NO EXTERNAL API KEY

Optional later:
COMPOSIO_API_KEY
Browserbase credentials
cloud credentials
payment credentials
specialized providers

Do not make optional integrations mandatory for core execution.

---

# 8. CREDENTIAL ARCHITECTURE

Never architect:

Agent → raw API key

Instead:

Agent
    ↓
Capability Request
    ↓
Trusted Capability Broker
    ↓
Credential Broker
    ↓
Provider

LLMs should not receive raw credentials whenever technically avoidable.

Secrets remain in trusted backend infrastructure.

Agents request operations.

Trusted executors perform them after validating permissions.

Never expose:

- API secrets;
- private keys;
- card details;
- production credentials;

inside model context unless absolutely unavoidable and explicitly authorized.

---

# 9. MODEL ROUTER

Create an intelligent ModelRouter.

Agents request capabilities rather than hardcoded model names.

Example request:

reasoning: HIGH
coding: HIGH
vision: FALSE
tool_use: REQUIRED
context: >100k
max_latency: 30s
max_cost: $0.40
privacy: CLOUD_ALLOWED

Router should consider:

- capability;
- task type;
- expected quality;
- expected cost;
- latency;
- availability;
- rate limits;
- context requirements;
- tool support;
- privacy;
- provider health;
- historical success on similar tasks;
- cached context opportunities.

Support fallback chains:

primary
↓
alternative model
↓
alternative provider
↓
local model

Provider outage must not terminate the objective.

---

# 10. MULTI-LLM REASONING

Important decisions should optionally use model diversity.

Example:

Planner A → OpenAI
Planner B → Claude
Planner C → Gemini
Planner D → local model

Independent planners should initially produce plans without seeing each other's conclusions.

Then a Judge/Synthesis stage evaluates:

- assumptions;
- contradictions;
- missing information;
- risk;
- cost;
- predicted success;
- evidence;
- implementation feasibility.

The judge should synthesize the strongest plan rather than simple majority voting.

For high-value/high-risk decisions, multiple judges may be justified.

For trivial work, do NOT burn multiple expensive models.

---

# 11. AGENT SPECIFICATION

Create a provider-independent AgentSpec owned by OUR architecture.

Conceptual fields:

id
parent_id
role
objective
instructions
selected_model
preferred_model_capabilities
fallback_models
tools
permissions
budget
token_budget
compute_budget
priority
ttl
success_criteria
termination_conditions
memory_scope
workspace
network_policy
spawn_permissions
status
created_at
metadata

Provider-specific agent objects are runtime implementations only.

Our AgentSpec must remain portable.

---

# 12. AGENT FACTORY

Agents must be dynamically creatable at runtime.

The system should be capable of deciding:

"I need a researcher."

"I need three independent researchers."

"I need a coder."

"I need a browser operator."

"I need a verifier."

"I need a financial analyst."

"I need a domain specialist."

"I need another judge."

"I no longer need these agents."

Agents are disposable organizational/computational units.

Knowledge/results must survive agent destruction.

---

# 13. DYNAMIC ORGANIZATION DESIGNER

Build an OrganizationDesigner.

Its role is to determine the temporary organization required for the current objective.

Example:

Commander
 ├─ Research Lead
 │   ├─ Researcher A
 │   └─ Researcher B
 ├─ Engineering Lead
 │   ├─ Backend Developer
 │   └─ Test Worker
 └─ Independent Verifier

But the structure must NOT be fixed.

The organization may reorganize at runtime.

Examples:

worker repeatedly fails
→ replace

worker overloaded
→ clone role

two agents duplicate effort
→ merge responsibilities

new expertise required
→ spawn specialist

branch no longer useful
→ terminate

planner assumptions invalid
→ rebuild organization

Organization topology is mutable runtime state.

---

# 14. AUTHORITY / DELEGATION GRAPH

Communication and authority should not be globally unrestricted.

Represent:

- who can delegate to whom;
- who can spawn whom;
- which capabilities can be delegated;
- maximum sub-budget;
- who may communicate directly;
- which workspaces may be created;
- which external systems may be touched.

Example:

Commander:
can_spawn Planner
can_spawn Research Lead
global subbudget <= X

Planner:
can_spawn Researcher
can_spawn Analyst
subbudget <= Y

Researcher:
web.search
read files
NO production shell
NO unrestricted credentials
NO payments

A child agent cannot automatically receive more authority than allowed by parent/global policy.

---

# 15. FAILURE / REFUSAL CLASSIFICATION

Implement explicit failure types.

Examples:

MODEL_FAILURE
PROVIDER_OUTAGE
RATE_LIMIT
TIMEOUT
CONTEXT_LIMIT
CAPABILITY_MISMATCH
TOOL_MISSING
TOOL_FAILURE
INVALID_OUTPUT
LOW_CONFIDENCE
VERIFICATION_FAILURE
RESOURCE_EXHAUSTED
AUTHORIZATION_REQUIRED
POLICY_REFUSAL
UNKNOWN_FAILURE

Do not treat all failures identically.

Examples:

RATE_LIMIT
→ retry/backoff/other provider

CAPABILITY_MISMATCH
→ different model

TOOL_MISSING
→ discover/build tool

LOW_CONFIDENCE
→ independent second attempt/judge

VERIFICATION_FAILURE
→ replan/re-execute

PROVIDER_OUTAGE
→ alternative provider/local model

AUTHORIZATION_REQUIRED
→ human approval

POLICY_REFUSAL
→ policy/human review

---

# 16. VERIFICATION IS MANDATORY

An LLM saying:

"Done."

is NOT success.

Each task should have explicit success criteria.

Prefer external evidence.

Examples:

CODE:
- tests pass;
- build passes;
- required behavior works.

DEPLOYMENT:
- endpoint exists;
- health check succeeds;
- expected behavior confirmed.

RESEARCH:
- claims traceable to sources;
- independent corroboration where appropriate.

FILES:
- expected file exists;
- content/hash/structure is correct.

API:
- API confirms resulting state.

BUSINESS OBJECTIVE:
- requested measurable outcome exists.

For important work:

Executor != Verifier

Use independent verifier agents.

---

# 17. PERSISTENT EXECUTION

The swarm must survive:

- process crashes;
- server restarts;
- provider outages;
- agent crashes;
- long-running objectives;
- background job interruptions.

Persist at least:

- objectives;
- plans;
- task graph;
- organization graph;
- agent specs;
- agent statuses;
- important messages;
- tool calls;
- tool results;
- artifacts;
- pending approvals;
- budget;
- spend;
- provider usage;
- verification state;
- errors;
- retries;
- organization changes;
- checkpoints.

A 12-hour objective must not restart from zero after restart.

Avoid repeating expensive or irreversible operations after recovery.

Use checkpoints and event-based persistence where appropriate.

---

# 18. MEMORY

Separate memory scopes:

- working memory;
- agent memory;
- task memory;
- organizational memory;
- long-term learned knowledge.

Do not dump entire chat history into every model call.

Support:

- retrieval;
- summarization;
- structured facts;
- artifact references;
- verified outcomes.

Useful long-term memory can include:

- successful strategies;
- failed strategies;
- provider reliability;
- tool reliability;
- cost/performance history;
- verified facts;
- previous organization designs;
- model performance by task type;
- self-improvement experiments.

---

# 19. RESOURCE ECONOMICS

Create a ResourceScheduler.

Every meaningful model/tool/agent execution has a cost.

Evaluate possible actions using:

- expected value;
- predicted probability of success;
- cost;
- latency;
- risk;
- redundancy;
- required capabilities.

Examples:

"Another strong judge costs $0.18 and may materially reduce uncertainty."
→ APPROVE

"Thirty more researchers would mostly duplicate existing work."
→ DENY

Track:

- cost by objective;
- cost by task;
- cost by agent;
- cost by provider;
- cost by model;
- cost by tool;
- compute cost;
- browser cost;
- payment cost.

Over time, learn which models/tools/topologies perform best for different task classes.

---

# 20. INITIAL COST CONTROL DEFAULTS

All monetary limits should be configurable.

Use conservative defaults for early development.

Suggested starting defaults:

DEFAULT_OBJECTIVE_BUDGET = $3
NORMAL_OBJECTIVE_HARD_CAP = $10
SELF_IMPROVEMENT_BUDGET = $10
MAX_NORMAL_WORKER_BUDGET = $0.30
MAX_EXPENSIVE_SPECIALIST_BUDGET = $1.00
MAX_JUDGE_BUDGET = $1.00
DAILY_GLOBAL_CAP = $20-$30

These are development defaults, NOT permanent product limits.

Provide configuration through environment/config/UI.

Before expensive actions, estimate whether cheaper models/local models can do the work.

Conceptual decision:

remaining budget: $1.74
strong model expected cost: $0.22
cheap model expected cost: $0.009
cheap model estimated success probability: 82%

→ try cheap model first

Escalate only when justified.

---

# 21. COST ESTIMATION UX

Before launching an objective, provide an estimated cost range where enough information exists.

Example:

Estimated cost: $1.40 – $4.80

During execution show:

- total cost;
- burn rate;
- remaining budget;
- expensive agent calls;
- model/tool breakdown.

Cost estimates must clearly be estimates.

Do not pretend precise cost predictability when task complexity is unknown.

---

# 22. TOKEN / CONTEXT COST OPTIMIZATION

Aggressively optimize context.

Use:

- prompt caching where supported;
- structured summaries;
- retrieval instead of giant transcripts;
- task-local context;
- artifact references;
- compact tool outputs;
- model-specific context limits;
- local models for cheap repetitive work.

Avoid repeatedly resending entire organizational history to every agent.

Use stronger/expensive models primarily for:

- hard planning;
- hard coding;
- architecture;
- conflict resolution;
- difficult verification;
- failed cheaper attempts;
- high-value judgments.

Use cheaper/local models for:

- classification;
- routing;
- summarization;
- monitoring;
- extraction;
- simple workers;
- repetitive checks.

---

# 23. TOOL PROVIDER LAYER

Create ToolProvider abstraction.

Support:

- MCP;
- native tools;
- HTTP APIs;
- browser tools;
- filesystem;
- shell;
- code execution;
- external integration brokers.

Do not hardcode hundreds of integrations into core logic.

Tools should expose machine-readable metadata such as:

- capability name;
- permissions required;
- risk class;
- cost;
- latency;
- input/output schema;
- environment requirements.

---

# 24. SELF-GENERATED TOOLS

If an objective requires a capability that does not exist, the swarm may create it.

Example loop:

OBJECTIVE
↓
MISSING CAPABILITY
↓
spawn integration developer
↓
inspect API/docs
↓
write adapter/tool
↓
write tests
↓
run in sandbox/test environment
↓
independent review
↓
register capability
↓
continue original objective

New tools should enter a Tool Registry dynamically after verification.

---

# 25. WORKSPACES / EXECUTION

Do NOT give every agent direct shell access to the main machine.

Agents requiring code execution should preferably receive isolated environments.

Create:

WorkspaceProvider

Potential backends:

- Docker;
- remote worker;
- OpenHands-like runtime;
- Kubernetes;
- local sandbox.

Each workspace may define:

- CPU;
- RAM;
- disk;
- network policy;
- TTL;
- allowed commands/capabilities;
- filesystem scope.

Example:

Coder Agent #142

workspace:
2 CPU
4 GB RAM
network restricted
TTL 45 min

Agent finishes.
Artifacts persisted.
Workspace destroyed.

---

# 26. BROWSER CAPABILITY

Browser capability must be provider-independent.

Possible implementations:

- Playwright;
- Browserbase;
- Stagehand;
- remote browsers;
- computer-use systems.

For MVP prefer Playwright when sufficient.

This reduces credential count and external cost.

Browser actions should produce structured evidence where possible.

---

# 27. PAYMENT PROVIDER

Payments are optional but planned.

Create:

PaymentProvider

Potential adapters:

- Stripe;
- x402;
- crypto wallets;
- virtual cards;
- provider billing APIs.

Do not expose private keys/card credentials directly to LLM context.

Support:

- per-agent spending limits;
- per-task limits;
- objective budget;
- daily global limits;
- merchant/domain restrictions;
- approval thresholds;
- transaction logging.

Every payment must be attributable to:

objective
task
agent
reason
amount
timestamp
result

---

# 28. POLICY ENGINE

Policy enforcement must be external to the LLM.

No agent may grant itself privileges.

No spawned agent may silently obtain greater authority.

Policies can include:

- tool allow/deny;
- network allow/deny;
- domain restrictions;
- credential scope;
- filesystem scope;
- spending limits;
- compute limits;
- payment limits;
- human approval requirements;
- irreversible-action approval.

Core principle:

THINK FREELY.
ACT THROUGH CAPABILITIES.

LLM safety is not the security boundary.

The real security boundary is:

Policy Engine
+
Capability Broker
+
Credential Broker
+
Sandbox
+
Spending Limits
+
Audit
+
Kill Switch

---

# 29. HUMAN CONTROL

Support:

PAUSE OBJECTIVE
RESUME
STOP
APPROVE
DENY
MODIFY OBJECTIVE
CHANGE BUDGET
KILL AGENT
CHANGE PRIORITY
INJECT INFORMATION

Provide a global kill mechanism.

Stopping orchestration must stop creation of new execution tasks.

---

# 30. SELF-REORGANIZATION

This is a core differentiator.

The swarm should repeatedly evaluate whether the current organization still makes sense.

Possible actions:

KEEP
RETRY
CHANGE_MODEL
REPLACE_AGENT
ADD_AGENT
REMOVE_AGENT
PARALLELIZE
MERGE_TASKS
CHANGE_TOOL
CHANGE_TOPOLOGY
REPLAN
REBUILD_ORGANIZATION
BUILD_CAPABILITY

LLMs may propose changes.

Runtime policy/resource constraints decide whether changes are allowed.

---

# 31. SELF-MODIFICATION / SELF-IMPROVEMENT

The system should be capable of modifying, extending and improving ITS OWN CODEBASE.

This is a core capability.

It may detect limitations such as:

- missing capability;
- weak model routing;
- inefficient orchestration;
- repeated failures;
- missing integration;
- weak verifier;
- performance bottleneck;
- expensive execution path;
- missing UI capability;
- bugs;
- inadequate observability;
- poor memory retrieval.

When justified, the swarm may propose and implement changes to its own source code.

Preferred loop:

observe limitation
↓
form hypothesis
↓
design change
↓
create isolated branch/worktree
↓
modify code
↓
run tests
↓
run typecheck/lint/build
↓
run targeted evaluation
↓
compare before vs after
↓
independent reviewer/verifier
↓
merge or rollback
↓
record learned result

SELF-MODIFICATION MUST BE EVIDENCE-DRIVEN.

"This is better" is not proof.

---

# 32. SELF-DEVELOPMENT AGENTS

Support specialized internal roles such as:

ARCHITECT AGENT
CODE AGENT
TEST AGENT
REVIEW AGENT
BENCHMARK AGENT
SECURITY REVIEW AGENT
RELEASE AGENT

For important self-modification:

Author != Reviewer != Verifier

---

# 33. CODEBASE AWARENESS

Maintain a structured understanding of the codebase.

Track:

- modules;
- interfaces;
- dependencies;
- tests;
- ownership/responsibility;
- runtime dependencies;
- known problems;
- performance hotspots;
- recent changes;
- architectural decisions;
- technical debt.

Agents should inspect existing implementation before editing.

Avoid duplicate implementations.

Avoid unnecessary rewrites.

---

# 34. SAFE SELF-EDITING WORKFLOW

Never directly rewrite production code without a controlled workflow.

Preferred:

stable/current
↓
temporary branch/worktree
↓
agent edits
↓
tests
↓
evaluation
↓
review
↓
policy/approval
↓
merge
↓
deployment

Every self-modification should be traceable to:

- objective;
- reason;
- agent;
- branch;
- commit;
- files changed;
- tests executed;
- benchmark/evaluation;
- review result;
- rollback point.

---

# 35. ROLLBACK

Every self-modification requires rollback.

Before major change:

record current commit SHA
create checkpoint

After deployment:

monitor behavior

If regression occurs:

rollback automatically where policy permits
or request human approval.

Never permanently lose the last known-good version.

---

# 36. PROTECTED CORE

Not all code is equally self-modifiable.

Protected categories include:

- Policy Engine;
- Credential Broker;
- Secret Storage;
- Global Kill Switch;
- Audit Logging;
- Authorization;
- Spending Limit Enforcement;
- Production Deployment Policy;
- Self-Modification Policy itself.

Agents may inspect and propose changes.

But modification/merge of protected core requires stronger authorization and, by default, human approval.

The swarm must not silently remove its own control mechanisms.

---

# 37. SELF-MODIFICATION PERMISSIONS

Define permissions such as:

READ_OWN_CODE
CREATE_BRANCH
EDIT_NON_CRITICAL_CODE
RUN_TESTS
RUN_BENCHMARKS
CREATE_PULL_REQUEST
MERGE_NON_CRITICAL_CHANGE
DEPLOY_STAGING
DEPLOY_PRODUCTION
MODIFY_PROTECTED_CORE

No agent gets unrestricted self-modification by default.

---

# 38. SELF-IMPROVEMENT TRIGGERS

Self-improvement may be triggered by:

- repeated failure pattern;
- poor benchmark;
- high cost;
- slow latency;
- tool reliability issue;
- missing capability;
- human request;
- new model/provider availability;
- new integration requirement;
- UI limitation;
- production incident;
- weak verification.

Do not constantly rewrite code for no reason.

A change should have measurable expected benefit.

---

# 39. BEFORE / AFTER EVALUATION

Compare meaningful self-improvements using metrics such as:

- task success rate;
- cost;
- latency;
- token usage;
- retries;
- verification pass rate;
- agent count;
- provider failures;
- test coverage;
- runtime stability;
- resource consumption.

Retain changes only when evidence supports improvement.

---

# 40. SELF-GENERATED AGENT TYPES

Agent roles should not all be predefined.

Organization Designer may create specialized AgentSpecs dynamically.

Examples:

"PostgreSQL Performance Specialist"
"Brazilian Legal Researcher"
"React Rendering Optimization Reviewer"
"Stripe Webhook Debugger"

Generate:

- role;
- instructions;
- required model capabilities;
- tools;
- budget;
- success criteria.

Then instantiate dynamically.

---

# 41. STAGING BEFORE PRODUCTION

Where practical:

SELF-MODIFIED VERSION
↓
STAGING
↓
TEST OBJECTIVES
↓
EVALUATION
↓
CANARY
↓
PRODUCTION

The swarm should be able to test a modified version of itself against controlled objectives before replacing stable runtime.

---

# 42. SELF-MODIFICATION PRINCIPLE

THE SYSTEM MAY IMPROVE ITSELF.

BUT:

SELF-MODIFICATION DOES NOT IMPLY SELF-AUTHORIZATION.

Code-generation authority
and
permission authority

are separate.

The swarm may write code requesting more capabilities.

The Policy Engine decides whether those capabilities are granted.

The swarm must never gain additional real-world authority simply because it modified its own code.

---

# 43. OBSERVABILITY

Every objective must be inspectable.

Provide structured traces showing:

- current objective;
- plan;
- active agents;
- models;
- tasks;
- agent hierarchy;
- tool calls;
- cost;
- token usage;
- errors;
- retries;
- verification attempts;
- replanning;
- organization changes;
- self-modifications;
- final evidence.

The user should be able to answer:

"What is the swarm doing right now?"
"Why did it create this agent?"
"Why did it switch models?"
"Why did it spend this money?"
"What failed?"
"Why did it replan?"
"Why is the objective not complete?"
"Why did it modify its own code?"

---

# 44. UI: PRODUCT VISION

THE UI SHOULD FEEL LIKE A STRATEGY / MANAGEMENT GAME.

But:

THE GAME REPRESENTS REALITY.

Every visible bot represents a real running agent.

Every status reflects real backend state.

Every meaningful animation corresponds to a real event.

This is NOT:

- a normal SaaS dashboard;
- a generic admin panel;
- a fake animated demo;
- a crypto-looking interface;
- a childish cartoon;
- a static node graph.

The user should feel like they are watching a living digital organization operate.

---

# 45. MAIN WORLD

Create a living:

AI HEADQUARTERS
/
DIGITAL CITY
/
AUTONOMOUS OPERATIONS CENTER

Prefer polished:

2D
or
2.5D / isometric

Avoid unnecessary full 3D.

Visual inspiration may come from the FEEL of:

RimWorld
Oxygen Not Included
Factorio
The Sims
Prison Architect
management/strategy games

Do NOT copy assets or exact visual styles.

Create an original premium futuristic identity.

---

# 46. SEMANTIC WORLD AREAS

Possible areas:

COMMAND CENTER
- Meta Orchestrator
- global objective

PLANNING ROOM
- planners
- judges
- synthesis

RESEARCH LAB
- research agents

ENGINEERING LAB
- coding/test agents

BROWSER ROOM
- browser/computer-use agents

TOOL HUB
- APIs
- MCP
- external integrations

SERVER ROOM
- compute
- containers
- workspaces
- deployments

VERIFICATION LAB
- verifier agents

FINANCE AREA
- budget
- spend
- payments
- resources

MEMORY ARCHIVE
- long-term organizational memory

CORE / SELF-IMPROVEMENT LAB
- self-modification work
- architecture changes
- internal upgrades

Agents should move to areas that correspond to what they are ACTUALLY doing.

No fake movement.

---

# 47. AGENTS AS BOTS

Every active agent is represented as a bot/avatar.

Bots should be:

- visually distinct;
- charming;
- expressive;
- readable;
- professional;
- not childish.

Each bot communicates:

ROLE
STATUS
MODEL
CURRENT TASK
HEALTH
BUDGET/SPEND when relevant

Possible role accessories:

Researcher → magnifying glass / documents
Coder → terminal / tablet
Planner → holographic plan board
Judge → comparison/scales motif
Browser Agent → browser/window motif
Finance Agent → wallet/resource motif
Verifier → scanner/checkmark
Orchestrator → command/control motif
Architect → blueprint motif
Reviewer → inspection motif

Role identity is PRIMARY.
Model/provider identity is SECONDARY.

---

# 48. BOT STATES / EMOTIONS

Bots should visibly react to REAL state.

IDLE
- relaxed

THINKING
- thoughtful
- only during a real model call

WORKING
- focused
- interacting with tool/workstation

SUCCESS
- happy
- small celebration
- only after verified success

FAILED
- confused/disappointed

BLOCKED
- waiting

WAITING_FOR_HUMAN
- raises hand

LOW_CONFIDENCE
- uncertain expression

RETRYING
- determined

RATE_LIMITED
- clock/waiting state

SPAWNING
- arrival/materialization

TERMINATED
- graceful exit/fade

SELF_UPDATING
- engineering/core-lab activity

Animations communicate state.

Do not overanimate.

---

# 49. HEAD ICONS

Display contextual icons above agents where useful.

Examples:

reasoning
browser
code
shell
research
model call
tool call
money
waiting
warning
question
human approval
verified
retry
high priority
permission denied
self-update
test
deployment

Do not rely only on emoji.

Use polished icons.

Important icons should be clickable.

Examples:

warning
→ exact error

cost
→ cost breakdown

browser
→ current browser operation/session

approval
→ pending approval

tool
→ tool call detail

self-update
→ code-change inspector

---

# 50. AGENT SPAWNING

Agent creation should be visually significant.

Backend:

AGENT_CREATED

UI:

spawn portal / elevator / terminal activates
↓
bot materializes
↓
short label appears

Example:

RESEARCHER #17
Claude
Task #31
Budget $0.80
Parent: Research Lead

↓
bot moves toward actual work area

If many spawn at once, batch intelligently.

---

# 51. AGENT TERMINATION

Successful completion:

bot finishes
hands off result/artifact
shows completion
leaves gracefully

Failure replacement:

FAILED
REPLACED BY AGENT #42

Historical agents remain inspectable.

---

# 52. AGENT INSPECTOR

Click any bot to open Agent Inspector.

Show:

- Agent Name
- Agent ID
- Role
- Current Model
- Provider
- Current Task
- Status
- Parent Agent
- Child Agents
- high-level reasoning/status summary
- recent actions
- tool calls
- artifacts
- task messages
- cost
- token usage
- lifetime
- allocated budget
- permissions
- workspace
- network access
- errors
- retries
- success criteria
- confidence where available

Do NOT expose hidden chain-of-thought.

Possible actions:

PAUSE AGENT
KILL AGENT
CHANGE PRIORITY
OPEN TASK
OPEN WORKSPACE
VIEW OUTPUT
INJECT INFORMATION

Do not expose secrets.

---

# 53. THOUGHT BUBBLES

Bots may display short structured summaries.

Examples:

"Comparing three providers"
"Waiting for tests"
"Researching competitor pricing"
"Need another specialist"
"Verification failed — retrying"
"Conflicting evidence found"
"Waiting for approval"
"Building missing integration"
"Testing self-update"

These must come from structured status/events.

Never reveal raw hidden chain-of-thought.

---

# 54. COMMUNICATION VISUALIZATION

Visualize agent communications subtly.

Possible:

- message packet;
- brief connection beam;
- light pulse;
- small bubble.

Do not create permanent spaghetti.

When an agent is selected, highlight its relevant communication paths.

Aggregate heavy traffic.

---

# 55. WORLD VIEW + ORGANIZATION GRAPH

Support at least:

WORLD VIEW

and

ORGANIZATION GRAPH

WORLD VIEW:
game-like headquarters

ORGANIZATION GRAPH:
real hierarchy/delegation structure

Graph shows:

- parent/child;
- delegations;
- teams;
- task ownership;
- dependencies;
- communication topology.

Organization changes should animate.

New agent → node appears.
Terminated agent → node fades.
Reassignment → edge changes.
New team → cluster forms.

---

# 56. OBJECTIVE HUD

Current objective must remain visible.

Example:

OBJECTIVE
"Build and launch a landing page and obtain 10 verified qualified leads."

Use milestone-based progress.

DO NOT invent fake percentages.

Example:

✓ Market research
✓ Product positioning
● Landing page implementation
○ Deployment
○ Outreach
○ 10 verified leads

Show:

Elapsed Time
Total Spend
Budget
Burn Rate
Active Agents
Total Agents Spawned
Completed Tasks
Failed Attempts
Replans

---

# 57. REAL-TIME EVENT SYSTEM

Backend is canonical source of truth.

Use WebSocket/SSE or existing real-time infrastructure.

Useful typed events:

OBJECTIVE_CREATED
OBJECTIVE_UPDATED
OBJECTIVE_COMPLETED

PLAN_CREATED

TASK_CREATED
TASK_STARTED
TASK_COMPLETED
TASK_FAILED

AGENT_CREATED
AGENT_STARTED
AGENT_STATUS_CHANGED
AGENT_REPLACED
AGENT_TERMINATED

MODEL_CALL_STARTED
MODEL_CALL_COMPLETED
MODEL_CALL_FAILED

TOOL_CALL_STARTED
TOOL_CALL_COMPLETED
TOOL_CALL_FAILED

BROWSER_ACTION

WORKSPACE_CREATED
WORKSPACE_DESTROYED

PAYMENT_REQUESTED
PAYMENT_COMPLETED

APPROVAL_REQUIRED

VERIFICATION_STARTED
VERIFICATION_PASSED
VERIFICATION_FAILED

REPLAN_STARTED

ORGANIZATION_CHANGED

SELF_MODIFICATION_PROPOSED
SELF_MODIFICATION_STARTED
SELF_MODIFICATION_TESTING
SELF_MODIFICATION_REVIEWED
SELF_MODIFICATION_DEPLOYED
SELF_MODIFICATION_ROLLED_BACK

BUDGET_WARNING
PROVIDER_OFFLINE

UI reacts to actual events.

---

# 58. ABSOLUTE RULE: NO FAKE WORK

If the agent is NOT calling a model:

do not show THINKING.

If browser is not active:

do not show browser use.

If no agent exists:

do not render decorative workers.

If verification has not passed:

do not show success.

If payment failed:

do not show successful spending.

If task failed:

show actual failure.

If self-update has not passed tests:

do not show successful upgrade.

THE GAME IS AN ANIMATED REPRESENTATION OF REAL EXECUTION.

---

# 59. MODEL BADGES

Each bot has a subtle model badge.

Examples:

GPT
Claude
Gemini
Grok
Qwen
Mistral
DeepSeek
Local

Role > Model.

When ModelRouter changes model:

Claude
↓
GPT

show subtle transition.

---

# 60. COST UI

Cost must be highly visible.

Top HUD:

TOTAL COST
CURRENT BURN RATE
OBJECTIVE BUDGET
REMAINING BUDGET

Finance area should break down cost by:

- agent;
- task;
- provider;
- model;
- tool;
- compute;
- browser;
- payment;
- self-improvement.

Show successful-output / cost metrics where meaningful.

---

# 61. ALERTS

Create game-like alerts for real events.

Examples:

NEW AGENT SPAWNED
VERIFICATION FAILED
ORGANIZATION RESTRUCTURED
BUDGET 80% USED
HUMAN APPROVAL REQUIRED
PROVIDER OFFLINE
AGENT REPLACED
SELF-UPDATE PROPOSED
SELF-UPDATE ROLLED BACK
OBJECTIVE COMPLETE

Click alert
→ jump to relevant entity/task.

---

# 62. MISSION START EXPERIENCE

Starting an objective should feel like launching a mission.

User enters:

- Objective
- Optional Budget
- Optional Deadline
- Allowed Resources
- Autonomy Level

Then:

OBJECTIVE ACCEPTED

Command Center activates.

Planner bots spawn.

Different model badges appear.

Plans are generated.

Judge compares them.

Organization graph forms.

Specialists begin spawning.

Tasks appear.

Bots move toward work.

This should be a signature UX moment.

---

# 63. SIGNATURE SCENE

Desired experience:

User creates objective.

Three planner bots spawn:

GPT Planner
Claude Planner
Gemini Planner

Each starts a REAL model call.

Status → THINKING.

They finish.

Judge receives plans.

Judge synthesizes.

Organization Designer decides:

2 researchers
2 coders
1 browser agent
1 verifier

Six bots spawn.

They move to relevant rooms.

Research bots use search/browser.

Coders receive isolated workspaces.

One coding agent fails.

Red warning appears.

System replaces it.

Replacement bot spawns.

Failed agent's useful artifacts/state are handed off.

Replacement continues.

Verifier rejects first result.

Swarm reorganizes.

New specialist spawns.

Eventually verifier passes.

Bots celebrate briefly.

OBJECTIVE COMPLETE.

Everything shown corresponds to actual backend state.

---

# 64. GLOBAL COMMAND BAR

Add natural-language command/control.

Examples:

"Prioritize deployment."
"Increase budget to $50."
"Pause everything."
"Stop all outreach agents."
"Why was Agent #27 created?"
"Give research team more budget."
"Show only failed agents."
"Explain the latest self-update."

Commands must map to actual runtime actions.

---

# 65. FILTERS

Allow filtering by:

Team
Role
Model
Provider
Status
Task
Cost
Failure
Active/Completed
Self-modification involvement

---

# 66. SEMANTIC ZOOM

Support:

FAR:
teams / departments

MEDIUM:
individual agents

CLOSE:
animations
workstations
status icons
details

Use level-of-detail.

Do not render unnecessary detail when zoomed out.

---

# 67. LARGE SWARMS

UI must remain usable with:

1 agent
10 agents
50 agents
100+ agents

For large swarms:

- group by team;
- aggregate repeated activity;
- semantic zoom;
- LOD;
- reduce particle effects;
- avoid excessive DOM nodes;
- virtualize lists/panels.

Every real agent must still be inspectable.

---

# 68. HISTORICAL REPLAY

Persisted events should support replay.

Example timeline:

00:00 Objective Created
00:05 3 Planners Spawned
00:24 Organization Created
02:14 Browser Agent Failed
02:15 Replacement Spawned
03:02 Replan
04:37 Deployment Failed
05:10 Verification Passed

Provide:

PLAY
PAUSE
SCRUB TIMELINE
LIVE NOW

Replay must be visually distinct from LIVE mode.

---

# 69. SELF-MODIFICATION UI

When the system improves itself:

Core/Engineering Lab activates.

Example:

SYSTEM IMPROVEMENT PROPOSED
↓
Architect bot creates design
↓
Coder bots spawn
↓
Test bots validate
↓
Reviewer inspects
↓
UI displays:

SELF-UPDATE
Branch: swarm/improve-router-184
Files changed: 7
Tests: 143/143
Expected saving: 18%
Status: REVIEW

If accepted:

DEPLOYING UPDATE

If rejected:

UPDATE REJECTED
ROLLED BACK

User can inspect:

- reason for modification;
- diff summary;
- tests;
- benchmark;
- risk;
- reviewer verdict;
- deployment state;
- rollback option.

Never expose secrets in diffs/UI.

---

# 70. FRONTEND TECHNOLOGY

Preserve existing frontend stack when practical.

If React already exists:

strongly consider:

React
+
PixiJS

for game/world rendering.

Alternative:

Phaser

Evaluate based on:

- current codebase;
- performance;
- mobile support;
- 100+ animated agents;
- camera/zoom;
- interaction model;
- developer speed.

Avoid hundreds of constantly animated DOM elements if performance suffers.

Avoid unnecessary 3D.

2D/2.5D is preferred.

---

# 71. UI STATE ARCHITECTURE

Separate:

BACKEND CANONICAL STATE

from

UI PRESENTATION STATE.

Backend owns:

- agents;
- tasks;
- objective;
- organization;
- status;
- events;
- cost;
- model calls;
- tool calls;
- verification;
- self-updates.

Frontend owns:

- camera;
- zoom;
- selection;
- transitions;
- visual layout;
- filters;
- open panels;
- replay position.

Frontend must never invent backend truth.

---

# 72. SUGGESTED FRONTEND MODULES

Prefer modular components:

WorldRenderer
AgentEntity
AgentAnimator
WorldLayout
WorldCamera
ObjectiveHUD
CostHUD
AlertSystem
AgentInspector
OrganizationGraph
TaskInspector
EventStreamClient
ReplayController
CommandBar
FilterPanel
ModelBadge
StatusIcon
AgentTooltip
SelfUpdateInspector

Do not create one giant World.tsx.

---

# 73. VISUAL STYLE

Desired:

premium
clean
futuristic
friendly
subtle sci-fi
excellent typography
beautiful small characters
smooth transitions
strong hierarchy
polished interactions

Avoid:

generic SaaS
cards everywhere
Bootstrap-like dashboard
excessive neon
hacker cliché
matrix rain
crypto-casino aesthetic
cheap pixel art
overly childish cartoon style

The user should WANT to leave the swarm open just to watch it operate.

---

# 74. MOBILE

Desktop is primary initially.

Mobile/tablet should still support:

- objective status;
- overview;
- alerts;
- active agents;
- agent inspector;
- approvals;
- pause/stop;
- basic world viewing.

---

# 75. OPEN-SOURCE / FRAMEWORK STRATEGY

Do NOT reinvent everything.

Study and borrow concepts from:

OpenAI Agents SDK
Microsoft Agent Framework
Swarms
OpenHands
Agency Swarm
LangGraph
MCP
LiteLLM
Ollama
vLLM
Playwright
Browserbase / Stagehand
Composio

But do NOT make the product a thin wrapper around one framework.

Useful patterns:

OpenAI Agents SDK:
- agent runtime
- tools
- handoffs
- tracing

Microsoft Agent Framework:
- durable workflows
- checkpoints
- recovery

Swarms:
- hierarchical/dynamic swarm patterns
- councils
- auto swarm building

OpenHands:
- isolated workspaces
- agent execution

Agency Swarm:
- communication/authority topology

Fugu-like concepts:
- meta-coordinator selecting models/agents/topologies dynamically

Our proprietary/product layer remains:

Objective Engine
Organization Designer
Failure Recovery
Resource Economics
Verification
Persistent Execution
Self-Reorganization
Cross-provider Model Routing
Self-Improvement

---

# 76. ENGINEERING QUALITY

Use:

- typed schemas;
- small composable modules;
- clean boundaries;
- migrations;
- tests;
- structured logging;
- explicit error propagation;
- observability;
- idempotency where needed;
- rollback paths.

Avoid:

- fake integrations;
- hardcoded demo responses;
- silent failures;
- unnecessary rewrites;
- giant classes;
- tight provider coupling;
- exposing secrets;
- claiming untested features work.

---

# 77. IMPLEMENTATION PRIORITY

ADAPT THIS ORDER BASED ON WHAT ALREADY EXISTS.

Suggested dependency order:

AUDIT EXISTING PROJECT
↓
STABILIZE BUILD
↓
ImplementationStatus.md
↓
provider-independent interfaces
↓
ModelGateway
↓
OpenRouter/OpenAI/local support
↓
ModelRouter
↓
Objective + durable task state
↓
event architecture
↓
AgentSpec
↓
AgentFactory
↓
multi-planner + judge
↓
OrganizationDesigner
↓
Verifier
↓
failure classification
↓
replanning
↓
self-reorganization
↓
ResourceScheduler
↓
Capability/Policy Broker
↓
workspace/tool adapters
↓
self-generated tool support
↓
self-modification workflow
↓
real-time game-world UI
↓
bot state synchronization
↓
Agent Inspector
↓
spawn/terminate animations
↓
organization graph
↓
cost/resource HUD
↓
self-update UI
↓
replay
↓
optional payment/integration adapters

Do NOT blindly follow this if existing code already implements parts.

---

# 78. DEVELOPMENT WORKFLOW

Do NOT rebuild everything in one giant commit.

Inspect first.

Then make incremental changes.

Keep the application runnable.

After meaningful phases:

- run tests;
- run build;
- run typecheck;
- run lint where configured;
- verify backend events;
- verify actual behavior;
- update ImplementationStatus.md.

Do not destroy working pieces.

---

# 79. NORTH STAR BEHAVIOR

The user gives the system a goal.

The screen comes alive.

Several planner bots spawn.

Different LLMs independently investigate the objective.

They disagree.

A judge synthesizes.

Organization Designer decides what workforce is required.

Specialized bots visibly spawn.

Some research.

Some code.

Some browse.

Some verify.

They communicate.

Some fail.

The system notices.

A replacement spawns.

The organization changes shape.

Models may switch dynamically.

Workspaces appear and disappear.

Costs accumulate visibly.

Verifier rejects incomplete work.

Swarm replans.

Useful knowledge survives individual agents.

If capability is missing, the swarm may build that capability.

If its own implementation is the bottleneck, the swarm may propose a self-update.

Self-update is developed in isolation, tested, reviewed, and deployed or rolled back.

Eventually the objective is externally verified.

Bots celebrate.

OBJECTIVE COMPLETE.

And everything the user saw corresponded to what the system ACTUALLY DID.

---

# 80. FINAL PRODUCT PHILOSOPHY

The product should progressively become capable of:

"I keep failing this class of tasks because I lack capability X."

↓
"I should build capability X."

↓
create development team

↓
modify own code

↓
test itself

↓
independent agents evaluate new version

↓
deploy safely

↓
continue the original objective

At the same time:

- no agent can silently grant itself more authority;
- credentials remain outside LLM context where possible;
- policy remains external;
- budgets remain enforceable;
- rollback remains available;
- user control remains absolute.

The system is autonomous in problem solving.

It is NOT autonomous in rewriting its own permissions.

---

# 81. START NOW

You are working inside the EXISTING project.

DO NOT create a new repository.

Start by inspecting everything currently present.

Determine:

1. what is already implemented;
2. what already fits this architecture;
3. what should remain unchanged;
4. what is partially implemented;
5. what is broken;
6. what is missing;
7. which dependencies are useful;
8. which new dependencies are actually justified;
9. what the highest-leverage next implementation is.

Update ImplementationStatus.md.

Then continue implementation immediately.

Do not return only with a plan unless execution is genuinely blocked.

The target is a real persistent, provider-agnostic, multi-LLM Autonomous Organization OS with:

- dynamic agent creation;
- multi-model reasoning;
- model routing;
- durable execution;
- verification;
- dynamic organization;
- cost-aware scheduling;
- external capability control;
- local LLM support;
- self-generated tools;
- safe self-modification;
- and a game-like real-time UI that truthfully visualizes the living swarm.
