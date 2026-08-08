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

## Non-submission rule

This is a local evaluation repository. **Never prepare, publish, upload, or
submit its results or trajectories to a τ-bench leaderboard or any third party
without fresh, explicit human authorization naming the target and scope.** A
request to run or compare tasks is not submission authorization. The durable
execution and publication rules are in [BENCHMARK_POLICY.md](BENCHMARK_POLICY.md).

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

## Frozen local train/test split

Because τ-bench does not provide an official split for `banking_knowledge`,
this repository freezes a seed-42 local split of the 97 public tasks: 48 train
and 49 test. The exact IDs and the scientific-use rules are declared in
[AGENTS.md](AGENTS.md) and hard-coded in
[`src/codex_tau/task_split.py`](src/codex_tau/task_split.py). Runtime code never
reshuffles them.

The split is formed by shuffling the sorted IDs with Python `random.Random(42)`,
assigning the first `ceil(97 * 0.5)` IDs to test, assigning the remainder to
train, and sorting each stored partition. The prior smoke/optimization tasks,
`task_001` and `task_004`, are both in train. Prompt iteration and human
labeling must use train only; the test partition is aggregate evaluation only.

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
the two fixed smoke tasks or the frozen 49-task test partition, and refuses
trial counts other than one.

## Frozen test run

The candidate prompt can be evaluated once on the frozen test partition with
the same `alltools`, model, reasoning, simulator, and authentication boundaries
as the smoke harness:

```bash
uv run codex-tau preflight experiments/test-candidate.toml
uv run codex-tau run experiments/test-candidate.toml
```

The experiment contains all 49 test IDs explicitly. Its manifest records the
split algorithm, seed, counts, digest, exact task IDs, tool-schema digest, and
Pass@1. Per-task console summaries are disabled for held-out runs. Test
trajectories must not be used for subsequent prompt optimization.

## ExpertTrace prompt provenance

The ExpertTrace workflow used for the existing candidate optimized a root
`AGENTS.md`, not an arbitrary prompt path. This repository preserves the
historical prompt provenance while using the current root `AGENTS.md` for
repository evaluation rules:

- the pinned ExpertTrace workspace commit stores the baseline bytes in
  `AGENTS.md`;
- the pinned optimization commit stores the candidate bytes in `AGENTS.md`;
- `prompts/banking_knowledge/*.md` contains those exact bytes for the harness;
- each experiment pins the source branch, commit, path, project, workspace, and
  optimization identifiers;
- the runner verifies `git show <source-commit>:AGENTS.md` byte-for-byte before
  starting Codex.

The current repository `AGENTS.md` is not an evaluated prompt. The app-server
runs outside the repository and the harness loads the prompt file only after
verifying it against its historical source commit, so repository instructions
are not exposed to the evaluated model.

## Artifacts and leaderboard scope

Local output is written below `runs/<arm>-<timestamp>/` and includes τ-bench's
`results.json`, per-task adapter audits, and `manifest.json`. Everything below
`runs/` except `.gitkeep` is ignored. The 410 MiB reference result, auth state,
raw databases, embedding caches, and credentials are never copied or committed.

Smoke results prove integration and prompt replacement only. The frozen
test-partition result is a local, single-trial held-out estimate, not an official
full-domain leaderboard score. Neither is leaderboard-valid, and neither may be
submitted. The standing non-submission rule in
[BENCHMARK_POLICY.md](BENCHMARK_POLICY.md) applies to every run. This repository
intentionally contains no submission path.
