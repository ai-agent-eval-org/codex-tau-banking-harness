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

## Effective optimization instruction

The human instruction, normalized after the follow-up clarifications, was:

> Review the 48 fresh vanilla train trajectories once, using subagents for the
> qualitative review and synthesis. Treat those train traces as the only
> optimization evidence. Produce one general replacement for the complete
> shared `<instructions>` plus `<policy>` system prompt. Make changes that
> address recurring process failures and generalize across the banking domain;
> do not encode task-specific answers. GEPA is inspiration only: do not run
> GEPA, search candidates, iterate against evaluations, or use validation/test
> feedback. Exclude pilots and every test task, trajectory, reward, and audit.
> Preserve the unmodified structured alltools schemas and all runtime, model,
> authentication, and developer-instruction boundaries. Freeze the single
> resulting prompt before testing it.

There was no separate hidden optimizer-prompt artifact. This instruction was
provided through the working conversation and was not added to the evaluated
agent's prompt.

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

After the prompt was frozen, the explicitly authorized adaptive retest
`optimized-test-alltools-20260809T021853Z` ran the 49 frozen test tasks once at
seed 300 and concurrency 16. It used harness commit
`a7a86e65774158caf9df60c19a8cf3807893640e`, the frozen optimized file SHA-256
`e113c6ef7a8e0ee829089bd57c08d65bc9bc9c2fe76ad96e7f8c7c993d0c559e`,
GPT-5.4/high through personal ChatGPT authentication, and GPT-5.2/low for the
official simulator.

The adaptive retest scored **23/49 (46.9388%)**, compared with the retained
vanilla test run's **15/49 (30.6122%)**: **eight additional passes** and an
observed increase of **16.3265 percentage points**. It completed in
**20m22.119s**. All 49 trajectories ended with `user_stop`; none ended in an
infrastructure or unexpected error. All 1,970 accepted dynamic-tool calls had
their 1,970 results returned. All 49 adapter audits verified the frozen prompt,
ChatGPT authentication, GPT-5.4/high, no reroute, no instruction sources,
explicit empty developer instructions, no Codex-native capability event, and
complete tool-result delivery.

Only aggregate score, completion, and integrity fields were inspected. No test
trajectory, per-task reward, or individual audit content was opened for prompt
feedback. The matching 23/49 aggregate from the retired instruction-only demo
is a separate historical run and must not be conflated with this full-prompt
adaptive retest.

Because the retained vanilla test and retired demo had already used this
partition, the result is reused-holdout evidence, not a pristine held-out
evaluation. The execution authority is consumed. Any future run requires fresh
explicit authorization and remains another adaptive retest; test feedback must
never be used for prompt development.

The earlier infrastructure exposure of `task_002` and `task_008` remains a
contamination caveat for any test-set interpretation. Nothing in this
repository authorizes publication, upload, or leaderboard submission.
