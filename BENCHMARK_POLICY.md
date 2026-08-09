# Benchmark execution and submission policy

This repository is a local evaluation harness. Its standing rule is:

> Never prepare, publish, upload, or submit results or trajectories to a
> τ-bench leaderboard. Publication or disclosure to any other third party
> requires fresh, explicit human authorization naming the target and scope.

In particular:

- A request to run, inspect, compare, or summarize tasks is **not** publication
  permission.
- Do not create a leaderboard submission file, invoke a submission-preparation
  command, open a submission pull request, or upload trajectories to a
  leaderboard. There is no exception to this repository rule.
- Do not merge a harness pull request on the user's behalf unless separately
  authorized.
- Do not run a complete domain or expand the configured task/trial set without
  fresh authorization for the exact local evaluation scope and expected cost.
- Keep local run artifacts ignored unless publication is separately and
  explicitly authorized after a credential and size review. The exact Option
  A `results.json` already tracked on this branch is a narrow exception for
  internal metric calculation, not leaderboard preparation or submission.

The repository intentionally provides `preflight` and bounded local `run`
commands only. It provides no leaderboard submission command. Its exact
configuration allowlist includes the two-task smoke set, the
two-task/four-trial alltools validation, the five-task/four-trial alltools
pilots at concurrency eight and 16, and the frozen 49-task terminal-use
reference test. Allowlisting validates configuration; it is not execution
authorization.

A consumed authorization covered two retained local-only `alltools` baseline
matrices:

1. `vanilla-train-alltools`: the frozen 48 train IDs, one trial, concurrency 16;
2. `vanilla-test-alltools`: the frozen 49 test IDs, one trial, concurrency 16.

The current `optimized-test-alltools` config pins a complete replacement system
prompt authored only after the retained train run. Its train-only derivation,
fixed path, and SHA-256 are recorded in `PROMPT_OPTIMIZATION.md`. The current
optimized prompt has not been evaluated. A fresh authorization in the active
task covers exactly its frozen 49-task, one-trial run at concurrency 16; it does
not cover any other matrix or retry. Because the test partition was used by
the retained vanilla arm and earlier retired demos, the run is an adaptive
retest, not a pristine held-out run. In every case, test trajectories must not feed prompt optimization.

Prior execution authority is consumed and does not cover a rerun, extra trial,
other task ID, concurrency above 16, or one combined 97-task run. Any future
local execution requires fresh authorization for its exact scope and cost,
must preserve the personal-ChatGPT/Platform billing boundary, and can never
authorize leaderboard submission.

## Interrupted-run recovery is one-shot

The harness includes a fail-closed `resume-interrupted` implementation so an
already authorized matrix can be recovered without rerunning completed rows.
This is implementation, not authorization. The command cannot do model work
unless a fresh human authorization for one exact source run and exactly one
retry has first been encoded in the hash-pinned record described in
`authorizations/README.md`, committed, and left clean with the recovery code.

No active recovery authorization record is present. The command must not infer
authorization from a failed checkpoint, a request to inspect or summarize it,
or prior authorization for an original matrix. Recovery is local only and does
not relax the standing submission prohibition.
