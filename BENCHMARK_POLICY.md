# Benchmark execution and submission policy

This repository is a local evaluation harness. Its standing rule is:

> Never prepare, publish, upload, or submit results or trajectories to any
> τ-bench leaderboard or third party without fresh, explicit human
> authorization that names the submission target and scope.

In particular:

- A request to run, inspect, compare, or summarize tasks is **not** permission
  to submit results.
- Do not create a leaderboard submission file, invoke a submission-preparation
  command, open a submission pull request, or upload trajectories without that
  separate authorization.
- Do not merge a harness pull request on the user's behalf unless separately
  authorized.
- Do not run a complete domain or expand the configured task/trial set without
  fresh authorization for the exact local evaluation scope and expected cost.
- Keep all local run artifacts ignored unless publication is separately and
  explicitly authorized after a credential and size review.

The repository intentionally provides `preflight` and bounded local `run`
commands only. It provides no leaderboard submission command. The exact legacy
allowlist remains the two-task smoke set, the two-task/four-trial alltools
validation, the five-task/four-trial alltools pilots at concurrency eight and
16, and the frozen 49-task terminal-use reference test.

Fresh authorization adds three exact, local-only `alltools` matrices:

1. `vanilla-train-alltools`: the frozen 48 train IDs, one trial, concurrency 16;
2. `vanilla-test-alltools`: the frozen 49 test IDs, one trial, concurrency 16;
3. `optimized-test-alltools`: those same 49 test IDs, one trial, concurrency 16,
   only after its one-shot prompt has been authored exclusively from the fresh
   vanilla train traces and frozen by repo-relative path and SHA-256.

The third experiment and its prompt artifact were authored only after the first
matrix produced the authorized train traces. Their train-only derivation,
fixed path, and SHA-256 are recorded in `PROMPT_OPTIMIZATION.md`. Test
output remains aggregate-only. In all cases, test trajectories must not feed prompt optimization.
The authorization does not cover extra trials, other task IDs,
concurrency above 16, one combined 97-task run, or any submission. Any future
expansion must preserve the personal-ChatGPT/Platform billing boundary and
remain local by default.
