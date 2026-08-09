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
  A and Option B `results.json` files already tracked on this branch are narrow
  exceptions for internal metric calculation, not leaderboard preparation or
  submission.

The repository provides `preflight`, bounded local `run`, one-shot
`resume-interrupted`, and one-shot train-only `optimize` commands. It provides
no leaderboard submission command. Its exact evaluation allowlist contains
only the three alltools prompt-study matrices: train baseline, test baseline,
and optimized test. Historical smoke, pilot, scaling, and terminal-use
reference configs have been removed. Allowlisting validates configuration; it
is not execution authorization.

A consumed authorization covered two retained local-only `alltools` baseline
matrices:

1. `vanilla-train-alltools`: the frozen 48 train IDs, one trial, concurrency 16;
2. `vanilla-test-alltools`: the frozen 49 test IDs, one trial, concurrency 16.

The current `optimized-test-alltools` config pins a complete replacement system
prompt authored only after the retained train run. Its train-only derivation,
fixed path, and SHA-256 are recorded in `PROMPT_OPTIMIZATION.md`. The current
Luna prompt's authorized adaptive retest completed 46 graded rows (18 pass, 28
fail), but three rows have no reward after empty-assistant-message
infrastructure failures. It has no authoritative 49-task score, and the
original run authorization is consumed. No retry is authorized. For history
only, the previously active Sol prompt's optimized adaptive retest finalized as
`optimized-test-alltools-20260809T033050Z--recovery-bb161af26fd2` after one
separately authorized missing-only infrastructure retry. It scored 19/49. The
manifest preserves the retry provenance and proves the other 48 rows were not
rerun. That score does not apply to the Luna prompt. Both historical execution
and retry authorizations are consumed.
Because the test partition was used by the retained vanilla arm and earlier
retired demos, the result is an adaptive retest, not a pristine held-out run.
In every case, test trajectories must not feed prompt optimization.

## Prompt optimization is one-shot

`codex-tau optimize` is not an evaluation or submission path. One execution
uses a fresh personal-ChatGPT app-server thread at GPT-5.6-Luna/max to inspect
only the fixed 48-trace train packet and submit exactly one local candidate.
It has no test access, candidate evaluation, selection loop, or automatic
retry. It leaves the active prompt unchanged and writes only to the ignored
`optimizer-runs/` directory.

The command cannot do model work without fresh explicit authorization for one
exact source and one attempt. Its implementation, a successful preflight, a
failed attempt, or a retained candidate cannot create permission to retry,
evaluate, promote, publish, or submit anything.

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
