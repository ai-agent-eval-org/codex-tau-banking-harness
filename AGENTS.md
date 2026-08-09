# Repository evaluation rules

This repository is a local-only Codex/τ-bench evaluation harness. Never
prepare, publish, upload, or submit results or trajectories to a τ-bench
leaderboard. Publication or disclosure to any other third party requires fresh,
explicit human authorization naming the target and scope. Running or comparing
tasks is not publication authorization.

## Frozen banking train/test split

The public `banking_knowledge` task set has 97 tasks and no official train/test
split. This repository uses one immutable local 50/50 split generated as
follows:

1. Sort all task IDs lexicographically.
2. Shuffle once with Python `random.Random(42).shuffle`.
3. Put the first `ceil(97 * 0.5) = 49` shuffled IDs in test and the remaining
   48 in train.
4. Sort each partition lexicographically for storage and execution.

Never reshuffle, move tasks between partitions, or silently change the seed or
algorithm. Production execution must import the hard-coded tuples from
`src/codex_tau/task_split.py`; it must not generate a split at runtime.

Train (48 tasks):

```text
task_001 task_003 task_004 task_005 task_006 task_007 task_015 task_017
task_018 task_020 task_021 task_023 task_024 task_025 task_026 task_028
task_029 task_032 task_033 task_034 task_036 task_040 task_044 task_049
task_052 task_054 task_059 task_060 task_063 task_064 task_067 task_070
task_072 task_075 task_077 task_079 task_081 task_083 task_087 task_088
task_090 task_092 task_093 task_094 task_095 task_097 task_099 task_100
```

Test (49 tasks):

```text
task_002 task_008 task_010 task_012 task_014 task_016 task_019 task_022
task_027 task_031 task_035 task_037 task_038 task_039 task_041 task_043
task_045 task_046 task_047 task_048 task_050 task_051 task_053 task_055
task_056 task_057 task_058 task_061 task_062 task_065 task_066 task_068
task_069 task_071 task_073 task_074 task_076 task_078 task_080 task_082
task_084 task_085 task_086 task_089 task_091 task_096 task_098 task_101
task_102
```

## Experimental hygiene

- Prompt optimization, human labeling, failure analysis, and trajectory review
  may use train tasks only. For the current one-shot full-prompt pass, the only
  optimization evidence was the fresh `vanilla-train-alltools` run produced by
  this harness. The earlier pilots and all test trajectories were excluded.
- The one-shot pass was methodologically inspired by prompt-reflection
  research, including GEPA, but it was not GEPA: there was no iterative
  optimizer, candidate search, selection loop, or evaluation-feedback cycle.
  The complete fresh train traces were read once and one general full-system-
  prompt revision was frozen. The retired instruction-only demo prompt and its
  ignored local results are not evidence for the current prompt.
- Freeze the prompt and harness before a test run. Test outcomes may be used
  only for an aggregate evaluation report, never as feedback for the next
  prompt. If test feedback influences development, disclose that the test set
  is contaminated and define a new benchmark before making held-out claims.
- Test runs must disable per-task console summaries. Inspect only aggregate
  completion, infrastructure integrity, and final score; do not open test
  trajectories or task-level rewards during prompt development.
- Keep the reference configuration fixed at `terminal_use`, the exact standard
  τ-bench `LLMAgent` system-prompt constructor, the official runtime tool
  schemas, GPT-5.4/high through personal ChatGPT authentication, 200 maximum
  steps, and GPT-5.2/low for the official user simulator. The Platform API key
  may be used only by the simulator and official `alltools` embeddings, never
  for evaluated Codex inference.
- A custom or optimized prompt is a separately named experiment and must never
  be represented as reference-comparable. The reference and vanilla profiles
  have no configurable prompt override or additional developer instructions.
  All alltools vanilla runs load the complete
  `prompts/banking_knowledge/baseline.md` artifact; its raw and model-visible
  hashes are fixed and parity-tested against the pinned τ-bench
  `SYSTEM_PROMPT`, canonical `AGENT_INSTRUCTION`, and runtime alltools policy.
  The optimized form loads the complete system prompt from the fixed,
  repo-relative UTF-8 path `prompts/banking_knowledge/optimized.md`, pinned by
  raw file SHA-256. No hidden policy is appended. Structured τ-bench tool
  schemas remain separate and unmodified. Additional developer instructions
  are forbidden.
- An experiment config or runtime allowlist entry is a reproducibility control,
  not execution authority. Every model-bearing run requires fresh, explicit
  human authorization for its exact task IDs, trials, concurrency, and expected
  cost. Prior pilot, vanilla, optimized, and recovery execution authority is
  consumed. Concurrency 16 is the validated maximum; do not increase it without
  a separately authorized, bounded fixed-matrix scaling validation. Never run
  one combined 97-task matrix or submit to a leaderboard.
- An optimized prompt artifact and experiment config may be authored only
  after the fresh vanilla train run has completed. The prompt must be derived
  only from those train traces, then its repo-relative path and SHA-256 must be
  frozen before an evaluation. The current full prompt was evaluated once on
  the 49-task test partition as the disclosed adaptive retest
  `optimized-test-alltools-20260809T021853Z`; that execution authority is
  consumed. Any future run on the already-used test partition is another
  adaptive retest, not a pristine held-out evaluation, and requires fresh
  authorization and disclosure.
- Do not commit raw runs, credentials, embedding caches, or large artifacts.
- The presence of `resume-interrupted` implementation is not authorization to
  execute it. An interrupted trajectory may be retried only after fresh,
  explicit human authorization for that exact source run and one retry, encoded
  in the exact hash-pinned record documented under `authorizations/`, committed
  with a clean harness. No active recovery record is present. Never infer,
  generate, or activate retry authority from the implementation or the
  existence of a failed local run.
- Preserve the held-out contamination disclosure recorded in
  `REFERENCE_PARITY.md` and `PROMPT_OPTIMIZATION.md` in every future claim.
  Never use pilot or test diagnostics for prompt optimization.
