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
commands only. It provides no leaderboard submission command. The current
experiment files remain restricted to `task_001` and `task_004`, one trial per
task. Any future bounded expansion should use explicit task IDs and trial
counts, preserve the personal-ChatGPT/Platform billing boundary, and remain
local by default.
