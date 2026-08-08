# Repository evaluation rules

This repository is a local-only Codex/τ-bench evaluation harness. Never
prepare, publish, upload, or submit results or trajectories to a leaderboard or
third party without fresh, explicit human authorization naming the target and
scope. Running or comparing tasks is not submission authorization.

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
  may use train tasks only.
- Freeze the prompt and harness before a test run. Test outcomes may be used
  only for an aggregate evaluation report, never as feedback for the next
  prompt. If test feedback influences development, disclose that the test set
  is contaminated and define a new benchmark before making held-out claims.
- Keep the evaluation configuration fixed at `alltools`, the official τ-bench
  dynamic-tool schemas, GPT-5.4/xhigh through personal ChatGPT authentication,
  and GPT-5.2/low for the official user simulator. The Platform API key may be
  used only by the simulator and `alltools` embeddings, never by Codex.
- Keep task IDs and trial counts explicit. Do not run all 97 tasks or add trials
  without fresh authorization for that exact local cost scope.
- Do not commit raw runs, credentials, embedding caches, or large artifacts.
