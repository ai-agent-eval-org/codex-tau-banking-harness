# One-shot full-prompt optimization

## Evidence and method

The only optimization evidence was the retained local train run
`vanilla-train-alltools-20260808T212330Z`. It contains the frozen 48 train
tasks and scored **23/48**. All 48 trajectories ended with `user_stop`; there
were no infrastructure errors, and all 1,322 accepted dynamic-tool calls had
their results returned.

The 48 train trajectories were reviewed once and one replacement prompt was
written. This was a qualitative, generalizing reflection pass inspired at a
high level by prompt-optimization research. It was **not GEPA**: there was no
optimizer, candidate population, mutation or selection loop, iterative
evaluation, validation feedback, or test-guided revision.

No test task definition, test trajectory, per-task test reward, or test audit
was used. Earlier pilots and the retained vanilla test run were excluded from
the review. The previous instruction-only optimized prompt and its two ignored
local result directories were retired as demo artifacts before this pass.

## Optimization unit

The optimization unit is now the complete textual system prompt:

```text
<instructions>...</instructions>
<policy>...</policy>
```

[`prompts/banking_knowledge/baseline.md`](prompts/banking_knowledge/baseline.md)
contains the exact canonical τ-bench alltools rendering. It is byte-parity
tested against the pinned τ-bench `SYSTEM_PROMPT`, canonical
`AGENT_INSTRUCTION`, and runtime alltools policy. The harness reads the file as
the complete prompt; it does not append a hidden policy at runtime.

[`prompts/banking_knowledge/optimized.md`](prompts/banking_knowledge/optimized.md)
is one complete replacement at the same abstraction level. Its experiment
pins both the exact repository path and raw file SHA-256. The structured
τ-bench tool schemas are separate from the textual prompt and remain
authoritative and unmodified.

## Train evidence taxonomy

The baseline train run contained 23 passes and 25 failures. One primary process
failure was assigned to each failed trajectory:

| Primary process failure | Count |
| --- | ---: |
| Incomplete dependency or state-transition planning before writes | 6 |
| Premature, overbroad, or ambiguously staged transfer | 4 |
| Incomplete recommendation coverage or unverified decisive eligibility | 5 |
| Incorrect component, period, exclusion, or reconciliation arithmetic | 8 |
| Cross-resource fact leakage instead of per-resource isolation | 1 |
| Non-minimal or incomplete tool arguments | 1 |
| **Total** | **25** |

Passing trajectories supplied positive controls: resistance to adversarial
claims, net-value comparison, symmetric reconciliation, multi-cause diagnosis,
resource isolation, verification reuse, and exact staged-transfer counting.

## General changes accepted

- Inventory all requested outcomes, resources, hard constraints, shared limits,
  dependencies, transition order, confirmation points, and intended final state
  before advice, mutation, or transfer.
- Retrieve the most specific applicable policy and every decision-critical
  dependency, then stop retrieval when those dependencies are closed.
- Treat exact policy exceptions and authoritative tool state as controlling;
  do not trust an asserted state change without an authoritative result.
- Compare the complete plausible candidate set against eligibility, dates,
  constraints, interactions, and net value before making one recommendation.
- Compute resource-specific components and periods separately; reconcile both
  under- and over-applied values across the complete relevant record set.
- Isolate identifiers, rates, statuses, and rules by account, card,
  transaction, dispute, or other resource.
- Allocate scarce benefits or quotas across all competing items before the
  first write.
- Use schema-minimal agent-tool arguments and complete, self-contained payloads
  for every user-owned discovered-tool call.
- Inspect every write result, complete all actionable items, verify terminal
  state, and never describe a failed write or nonfinal transfer as complete.

## Changes rejected as leakage or overfitting

- Task IDs, customer or account values, gold actions, copied dialogue, hidden
  answers, or trace-specific examples.
- Hard-coded products, rates, dates, periods, limits, formulas, or dynamic tool
  names learned from an individual trace.
- Blanket authentication or transfer rules that override an exact
  knowledge-base exception or staged procedure.
- Test results, test trajectories, pilot diagnostics, candidate evaluations,
  or iterative prompt selection.

## Frozen artifacts

- Baseline file SHA-256:
  `c51896d46edd67711f8288735462b104202d4b250609ced2e5c16ded52ba90c3`
- Baseline model-visible SHA-256:
  `40e0c2afebb858e37b99b3dffcaba2cf1f2d48ad26908612fd4b5756d4899780`
- Optimized file SHA-256:
  `e113c6ef7a8e0ee829089bd57c08d65bc9bc9c2fe76ad96e7f8c7c993d0c559e`
- Optimized model-visible SHA-256:
  `3707b1aa9ca6490132f05cb8e3716e53ec39cb0dac6768a940d115ec411cb554`
- Bounded config:
  `experiments/optimized-test-alltools.toml`

## Evaluation status and integrity boundary

The current full optimized prompt has **not** been evaluated. No model-bearing
run was launched during this reoptimization.

The retained vanilla test run was already evaluated once, and an earlier demo
prompt was also evaluated on that same partition before its local results were
retired. Therefore, another optimized run on the 49 test tasks would be an
adaptive reuse of the partition, not a pristine held-out evaluation. It would
require fresh, explicit authorization for the exact matrix and cost and must be
labeled accordingly. Test trajectories must still never be opened for prompt
feedback.

The earlier infrastructure exposure of `task_002` and `task_008` remains a
contamination caveat for any test-set interpretation. Nothing in this
repository authorizes publication, upload, or leaderboard submission.
