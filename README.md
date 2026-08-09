# Codex τ-bench banking harness

This repository is a minimal, fail-closed adapter between the official
`banking_knowledge` domain in τ-bench and the Codex app-server. It is pinned to
τ-bench `v1.0.1` (`fc0055dc4e0a316c3f83133267fbd6faaa770992`) and Codex CLI
`0.147.0`.

The evaluated agent uses a personal ChatGPT/Codex login. The parent τ-bench
process may use `OPENAI_API_KEY` only for the official GPT-5.2 user simulator
and, in an `alltools` experiment, OpenAI embeddings. The `terminal_use`
reference profile does not use embeddings. The child Codex process is launched
with a sanitized environment and must report a ChatGPT account before a
simulation can start.

## Non-submission rule

This is a local evaluation repository. **Never prepare, publish, upload, or
submit its results or trajectories to a τ-bench leaderboard.** Publication or
disclosure to any other third party requires fresh, explicit human
authorization naming the target and scope.

A request to run or compare tasks is not submission authorization and grants
no publication authority. The durable execution and publication rules are in
[BENCHMARK_POLICY.md](BENCHMARK_POLICY.md).

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

The reference and vanilla arms read
[`prompts/banking_knowledge/baseline.md`](prompts/banking_knowledge/baseline.md)
as their `AGENT_INSTRUCTION`. That file visibly mirrors τ-bench's canonical
instruction; the loader removes its conventional final Markdown newline, then
verifies fixed raw and normalized hashes. Parity tests prove the normalized
bytes equal the pinned τ-bench constant. The loader renders that instruction
through τ-bench's unmodified `SYSTEM_PROMPT` template and supplies an explicit
empty developer-instruction string. There is no config-selectable baseline
override. The reference profile uses τ-bench's `terminal_use` policy. The
separately labeled alltools arms use τ-bench's unmodified `alltools` policy and
toolkit, including its official BM25, dense-search, and shell tools.

The optimized-test arm is fail-closed around one substitution only. It reads
[`prompts/banking_knowledge/optimized.md`](prompts/banking_knowledge/optimized.md)
instead of `baseline.md` for `AGENT_INSTRUCTION`, and its experiment pins that
artifact's SHA-256. The harness still renders τ-bench's unmodified
`SYSTEM_PROMPT` with the authoritative runtime `alltools` domain policy. Custom
policy text, alternate prompt paths, extra fields, and developer instructions
are rejected. The train-only derivation and fixed hash are documented in
[PROMPT_OPTIMIZATION.md](PROMPT_OPTIMIZATION.md).

Compare the only model-visible instruction change directly:

```bash
diff -u prompts/banking_knowledge/baseline.md \
  prompts/banking_knowledge/optimized.md
```

Codex runs from an empty temporary directory and a temporary `CODEX_HOME` that
contains only the benchmark configuration and a link to the user's existing
`auth.json`. Strict configuration disables Codex shell/exec, web/browser, MCP
discovery, bundled skills, apps, plugins, hooks, goals, user-input, image, and
subagent features exposed by this pinned version. It also disables permissions,
environment, collaboration, app, skill, and personality instruction injection.
The pinned Codex prompt debugger must render only the supplied user message.
The adapter independently aborts if any denied filesystem, plan, or other
native-capability event is observed. Repository `AGENTS.md` files are not
discovered by the evaluated process.

App-server stdout and stderr use an explicit 64 MiB per-line reader limit. This
is more than 500 times the 123,322-byte result that exposed Python's 64 KiB
default and more than eight times the current banking domain data tree. The
limit is a bounded ceiling rather than an eager allocation. Reader failures and
unexpected stdout closure terminate the trajectory immediately instead of
degrading into an idle timeout.

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
`high` reasoning and rejects model rerouting or provider fallback.

Place a Platform API key in the parent environment for the two official
τ-bench components that cannot use a Codex subscription:

```bash
export OPENAI_API_KEY='...'
```

The GPT-5.2 user simulator can consume Platform credits. Evaluated GPT-5.4 agent inference uses the personal
ChatGPT/Codex allowance. Never put a key in an experiment TOML file or run
manifest.

## No-credit checks

```bash
uv run pytest
uv run ruff check src tests
```

The tests do not call a model. They cover child-environment sanitization,
ChatGPT auth enforcement, version pinning, strict Codex configuration,
authoritative terminal-use and alltools schema parity, malformed/unknown tool
rejection, single and multi-tool callback ordering, native-tool denial, prompt
path/hash/UTF-8 provenance, post-run audit enforcement, and τ-bench
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

The commands below are exact reproducibility recipes, not standing permission
for model inference. `preflight` is model-free. Every new `run` or
`resume-interrupted` invocation requires fresh human authorization for its exact
local scope and expected cost; completed one-shot authorizations are consumed.

## Historical two-task smoke configuration

The fixed tasks were selected before scoring: `task_001` is a product
retrieval/recommendation task; `task_004` exercises the distinct account
ownership and human-transfer path. The reference smoke uses one trial, seed
300, `terminal_use`, GPT-5.4/high, 200 maximum steps, and GPT-5.2/low for the
official user simulator.

Load the configured Platform key into the parent process, then run exactly one
arm at a time:

```bash
uv run codex-tau preflight experiments/smoke-reference.toml
uv run codex-tau run experiments/smoke-reference.toml
```

`preflight` performs no model inference. `run` accepts only an exact named
experiment matrix in the code allowlist; name, filename, profile, partition,
task ordering, trials, concurrency, and prompt fields must all match.

## Historical two-task alltools concurrency validation

The completed validation used `task_002` and `task_008`, four trials each, and
two workers. Audits used the per-trial simulation seed in their filenames so
same-task trials could not overwrite one another:

```bash
uv run codex-tau preflight experiments/pilot2-alltools-concurrency2.toml
uv run codex-tau run experiments/pilot2-alltools-concurrency2.toml
```

## Historical five-task alltools pilot

The completed pilot used the first five IDs of the already-frozen test ordering:
`task_002`, `task_008`, `task_010`, `task_012`, and `task_014`. It ran four
trials per task with up to eight concurrent workers while preserving the model,
reasoning, simulator, seed, and step limit. It deliberately used τ-bench's
`alltools` profile:

```bash
uv run codex-tau preflight experiments/pilot5-alltools.toml
uv run codex-tau run experiments/pilot5-alltools.toml
```

It ran only after the two-task concurrency validation completed without an
infrastructure error. This pilot is not comparable to the external
`terminal_use` result. See [PILOT_STATUS.md](PILOT_STATUS.md) for its execution
evidence.

## Historical concurrency-16 scaling trial

The scaling trial reused the exact five-task, four-trial pilot matrix and
changed only the maximum worker count from eight to 16. It was a transport and
throughput validation, not a new benchmark partition:

```bash
uv run codex-tau preflight experiments/pilot5-alltools-concurrency16.toml
uv run codex-tau run experiments/pilot5-alltools-concurrency16.toml
```

The runtime allowlist accepts only this exact concurrency-16 combination; it
does not authorize arbitrary task expansion or leaderboard submission.

## Completed alltools vanilla runs

The completed baseline consists of two separately saved, single-trial
experiments. Both used the canonical τ-bench agent instruction byte-for-byte,
the authoritative unmodified `alltools` policy and toolkit, GPT-5.4/high through
personal ChatGPT authentication, GPT-5.2/low for the simulator, 200 steps, seed
300, and concurrency 16:

```bash
uv run codex-tau preflight experiments/vanilla-train-alltools.toml
uv run codex-tau run experiments/vanilla-train-alltools.toml

uv run codex-tau preflight experiments/vanilla-test-alltools.toml
uv run codex-tau run experiments/vanilla-test-alltools.toml
```

The train arm contains the frozen 48 train IDs. The test arm contains the
frozen 49 test IDs and suppresses per-task console feedback. Their distinct
experiment names guarantee distinct `runs/` locations. These are fresh
alltools baselines; neither is reference-comparable or leaderboard-valid.

## One-shot train-trace prompt pass

Only after `vanilla-train-alltools` finished were its 48 saved trajectories
read for prompt work. The method was a single generalizing reflection pass,
inspired by research such as GEPA but not an execution of GEPA: there was no
iterative search, candidate loop, or validation-guided selection. The train
traces were inspected once, one task-level `AGENT_INSTRUCTION` revision was
written, its SHA-256 was pinned in the separately named
`optimized-test-alltools` config, and both artifacts were frozen before the
49-task test ran once.

Do not inspect the vanilla or optimized test trajectories for prompt feedback.
The frozen artifact, its derivation report, and the bounded config are
present. The harness rejects the optimized experiment if its fixed path or hash
changes. The retained reproducibility commands are:

```bash
uv run codex-tau preflight experiments/optimized-test-alltools.toml
uv run codex-tau run experiments/optimized-test-alltools.toml
```

The aggregate-only outcomes are recorded in
[PROMPT_OPTIMIZATION.md](PROMPT_OPTIMIZATION.md). The completed optimized arm
scored 23/49 (46.9388%) versus the vanilla held-out arm's 15/49 (30.6122%), an
observed single-trial difference of 8 passes and 16.3265 percentage points.
This is not proof of causality or general performance, and the standing
contamination and non-publication caveats apply.

### Consumed interrupted-run recovery

`codex-tau resume-interrupted EXPERIMENT SOURCE_RUN_DIR` is a fail-closed
missing-only recovery mechanism, not standing permission to retry. It requires
fresh human authorization for one exact interrupted source and one retry,
encoded in a committed, clean, hash-pinned record. Recovery preserves the
source, validates the frozen matrix and provenance, skips completed rows, and
uses an exclusive attempt claim and receipt to prevent a second attempt. See
[authorizations/README.md](authorizations/README.md) for the full contract.

The Trial B record is consumed and terminal. Its completed retry authorizes no
additional model work; neither the implementation nor a failed local run can
create retry authority.

## Frozen test run

The standard τ-bench prompt can be evaluated once on the frozen test partition
with the same `terminal_use`, model, reasoning, simulator, step limit, and
authentication boundaries as the smoke harness:

```bash
uv run codex-tau preflight experiments/test-reference.toml
uv run codex-tau run experiments/test-reference.toml
```

The experiment contains all 49 test IDs explicitly. Its manifest records the
split algorithm, seed, counts, digest, exact task IDs, tool-schema digest, and
Pass@1. Per-task console summaries are disabled for held-out runs. Test
trajectories must not be used for subsequent prompt optimization.

## Reference comparability

The controllable trajectory settings match the external reference's
GPT-5.4/high, GPT-5.2/low, seed 300, `terminal_use`, 200-step configuration and
standard τ-bench prompt. See [REFERENCE_PARITY.md](REFERENCE_PARITY.md) for the
remaining known and unknown differences. In particular, app-server/ChatGPT
inference is not the same transport or orchestration as τ-bench's standard
Platform-backed `llm_agent`, and the external result predates this repository's
pinned τ-bench v1.0.1 data.

## Artifacts and leaderboard scope

Local output is written below `runs/<experiment>-<timestamp>/` and includes
τ-bench's incrementally checkpointed `results.json`, one per-trajectory adapter
audit keyed by task and simulation seed, and `manifest.json`. Everything below
`runs/` except `.gitkeep` is ignored. The 410 MiB reference result, auth state,
raw databases, embedding caches, and credentials are never copied or committed.

Smoke results prove integration and setting parity only. The frozen
test-partition result is a local, single-trial held-out estimate, not an official
full-domain leaderboard score. Neither is leaderboard-valid, and neither may be
submitted. The standing non-submission rule in
[BENCHMARK_POLICY.md](BENCHMARK_POLICY.md) applies to every run. This repository
intentionally contains no submission path.

Every completed trajectory audit must independently match the effective prompt
hash and instruction hash, personal ChatGPT account, GPT-5.4/high catalog and
thread model, no reroute, no instruction sources, explicit empty developer
instructions, no Codex-native capability event, and exact accepted-versus-
returned dynamic-tool counts with zero pending results. Manifest generation
fails if any trajectory misses one of these checks.
