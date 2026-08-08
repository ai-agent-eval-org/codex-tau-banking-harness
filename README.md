# Codex τ-bench banking harness

This repository is a minimal, fail-closed adapter between the official
`banking_knowledge` domain in τ-bench and the Codex app-server. It is pinned to
τ-bench `v1.0.1` (`fc0055dc4e0a316c3f83133267fbd6faaa770992`) and Codex CLI
`0.147.0`.

The evaluated agent uses a personal ChatGPT/Codex login. The parent τ-bench
process may use `OPENAI_API_KEY` only for the official GPT-5.2 user simulator
and `alltools` OpenAI embeddings. The child Codex process is launched with a
sanitized environment and must report a ChatGPT account before a simulation can
start.

## Architecture

τ-bench remains authoritative for policy, state, tool schemas, and execution:

```text
τ-bench Tool objects -> canonical Codex dynamic tools -> Codex tool request
       -> τ-bench AssistantMessage -> τ-bench environment execution
       -> τ-bench ToolMessage -> pending Codex dynamic-tool response
```

No per-tool Python wrappers or MCP server are generated. Every runtime `Tool`
schema is converted automatically, hashed, validated before each call, and
returned to the official τ-bench orchestrator for execution. The tool named
`shell` is therefore τ-bench's read-only `sandbox-runtime` tool, never Codex's
native shell.

The common app-server instructions prefer BM25/dense retrieval and require any
use of τ-bench's dynamic `shell` to target known evidence and bound its output.
This leaves the authoritative tool schema, execution, and result untouched while
avoiding broad listings that can exceed Codex app-server's reliable dynamic-tool
continuation size. The exact common-instruction hash is recorded by preflight and
in every run manifest, separately from the baseline/candidate prompt hash.

Codex runs from an empty temporary directory and a temporary `CODEX_HOME` that
contains only the benchmark configuration and a link to the user's existing
`auth.json`. Strict configuration disables Codex shell/exec, web/browser, MCP
discovery, apps, plugins, hooks, goals, user-input, and subagent features
exposed by this pinned version. The adapter independently aborts if any denied
filesystem, plan, or other native-capability event is observed. Repository
`AGENTS.md` files are not discovered by the evaluated process.

## Exact installation

Prerequisites: Python 3.12 or 3.13, `uv`, Node.js 18+, npm, `rg`, and
`@anthropic-ai/sandbox-runtime`'s `srt`. On macOS, install the shell sandbox with:

```bash
npm install -g @anthropic-ai/sandbox-runtime@0.0.23
```

Clone with the pinned τ-bench code-and-data submodule, then install the locked
Python and Node dependencies:

```bash
git clone --recurse-submodules https://github.com/ai-agent-eval-org/codex-tau-banking-harness.git
cd codex-tau-banking-harness
uv sync --frozen
npm ci
```

For an existing checkout, run `git submodule update --init --recursive` first.
The submodule is detached at the declared τ-bench commit because its built wheel
does not include the official benchmark data tree. The lockfiles contain the
complete dependency resolution. The harness refuses to launch a Codex
executable whose reported version is not `0.147.0`.

## Authentication and cost boundary

Log into the project-local Codex CLI with a personal ChatGPT account:

```bash
./node_modules/.bin/codex login
```

By default the harness reads `${CODEX_HOME:-$HOME/.codex}/auth.json`. It starts
app-server with `forced_login_method = "chatgpt"`, calls `account/read`, and
requires `account.type == "chatgpt"`. It also verifies that GPT-5.4 advertises
`xhigh` reasoning and rejects model rerouting or provider fallback.

Place a Platform API key in the parent environment for the two official
τ-bench components that cannot use a Codex subscription:

```bash
export OPENAI_API_KEY='...'
```

The GPT-5.2 user simulator and `text-embedding-3-large` retrieval calls can
consume Platform credits. Evaluated GPT-5.4 agent inference uses the personal
ChatGPT/Codex allowance. Never put a key in an experiment TOML file or run
manifest.

## No-credit checks

```bash
uv run pytest
uv run ruff check src tests
```

The tests do not call a model. They cover child-environment sanitization,
ChatGPT auth enforcement, version pinning, strict Codex configuration,
authoritative schema parity, malformed/unknown tool rejection, single and
multi-tool callback ordering, native-tool denial, prompt provenance, and τ-bench
message/result serialization.

## Two-task smoke runs

The fixed tasks were selected before scoring: `task_001` is a product
retrieval/recommendation task; `task_004` exercises the distinct account
ownership and human-transfer path. Each arm uses one trial, seed 300,
`alltools`, GPT-5.4/xhigh for Codex, and GPT-5.2/low for the official user
simulator.

Load the configured Platform key into the parent process, then run exactly one
arm at a time:

```bash
uv run codex-tau preflight experiments/smoke-baseline.toml
uv run codex-tau run experiments/smoke-baseline.toml

uv run codex-tau preflight experiments/smoke-candidate.toml
uv run codex-tau run experiments/smoke-candidate.toml
```

`preflight` performs no model inference. `run` refuses any task list other than
the two fixed smoke tasks and refuses trial counts other than one.

## ExpertTrace prompt provenance

The current ExpertTrace workflow optimizes a root `AGENTS.md`, not an arbitrary
prompt path. This repository uses the explicit mapping allowed by that
constraint:

- the ExpertTrace workspace branch stores the baseline bytes in `AGENTS.md`;
- the optimization branch stores the candidate bytes in `AGENTS.md`;
- `prompts/banking_knowledge/*.md` contains those exact bytes for the harness;
- each experiment pins the source branch, commit, path, project, workspace, and
  optimization identifiers;
- the runner verifies `git show <source-commit>:AGENTS.md` byte-for-byte before
  starting Codex.

The evaluated app-server still runs outside the repository, so this mapping
does not expose ExpertTrace or `AGENTS.md` discovery to the model.

## Artifacts and leaderboard scope

Local output is written below `runs/<arm>-<timestamp>/` and includes τ-bench's
`results.json`, per-task adapter audits, and `manifest.json`. Everything below
`runs/` except `.gitkeep` is ignored. The 410 MiB reference result, auth state,
raw databases, embedding caches, and credentials are never copied or committed.

These two-task results prove integration and prompt replacement only. They are
not leaderboard-valid and must not be submitted. A later custom-system
submission would require running the official complete task set under the
declared prompt/orchestration, publishing the implementation and prompt
modifications, preparing the required submission metadata/trajectories, and
following τ-bench's leaderboard review process. This repository intentionally
does none of those steps.
