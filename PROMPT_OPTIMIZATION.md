# One-shot train-trace prompt optimization

## Frozen evidence and method

The only optimization evidence was the fresh train run
`vanilla-train-alltools-20260808T212330Z`. It contains the repository's 48
frozen train tasks and scored **23/48** in aggregate. The analysis read those
train trajectories once, split into two fixed halves for qualitative review,
then synthesized one general replacement for τ-bench's `AGENT_INSTRUCTION`.

No test task definition, test trajectory, test reward, or test result was
viewed. Earlier pilots and other runs were not optimization evidence. Codex
subagents performed the train-trace qualitative review and one-shot synthesis.
During prompt authoring there was no additional benchmark evaluated-agent or
user-simulator inference, benchmark preflight, candidate or validation
evaluation, test run, or leaderboard submission.

This method is inspired only at a high level by reflection-based prompt
optimization research, including GEPA. It is **not GEPA**: there was no
optimizer, iterative loop, candidate population, search, mutation/selection
cycle, or validation-feedback step. One train-only review produced one prompt,
which was then frozen before any optimized test evaluation.

## Evidence taxonomy

The 48 trajectories comprised 23 passes and 25 failures. Reviewers assigned
one primary process failure to each failed trajectory:

| Primary process failure | Count |
| --- | ---: |
| Incomplete dependency or state-transition planning before writes | 6 |
| Premature, overbroad, or ambiguously staged transfer | 4 |
| Incomplete recommendation coverage or unverified decisive eligibility | 5 |
| Incorrect component, period, exclusion, or reconciliation arithmetic | 8 |
| Cross-resource fact leakage instead of per-resource isolation | 1 |
| Non-minimal or incomplete tool arguments | 1 |
| **Total** | **25** |

Secondary evidence overlapped those primary labels. Schema-minimal argument
construction contributed to four trajectories, three as mixed or recoverable
issues. Resource isolation contributed to one additional mixed failure.
Repeated searches often increased length without closing the exact policy
dependency, so the change emphasizes dependency completion rather than
exhaustive retrieval.

Successful trajectories established important counterexamples that the prompt
preserves: resistance to adversarial requests that conflict with policy or
tool state; constraint-aware and net-value product comparison; complete net
reconciliation; multi-cause diagnosis; per-card isolation; reuse of one valid
verification event; correct staged-transfer counting; and authoritative reads
after writes.

## Accepted changes

- Plan required dependencies, current state, transition order, intended end
  state, and verification before advice, mutation, or transfer.
- Retrieve the most specific policy and its referenced eligibility,
  exceptions, dates, limits, and schemas; stop once decision-critical
  dependencies are closed.
- Ask only for unknown facts that can change a recommendation or action, and
  verify time-sensitive eligibility instead of inferring it.
- Compare all plausible candidates across every hard constraint and net value,
  including disqualifiers.
- Compute policy-derived components and periods separately, reconcile totals,
  and audit both under- and over-applied values.
- Isolate identifiers, facts, status, and rules by resource.
- Use exact schema-minimal arguments and repeat a complete canonical payload
  for every user-owned discovered-tool call.
- Inventory multi-item work and shared limits before consuming scarce benefits
  or beginning dependent writes.
- Delay irreversible actions until prescribed retention and confirmation steps
  are complete; inspect every result and verify final authoritative state.
- Track staged transfer protocols exactly and avoid language that implies a
  nonfinal transfer has completed.

## Rejected changes

- Task IDs, customer or account values, hidden expected actions, gold answers,
  copied dialogue, or other trace-specific exemplars.
- Hard-coded products, rates, formulas, periods, dates, limits, or tool names.
- Blanket authentication or transfer rules that could override an explicit
  policy exception or staged protocol.
- Trusting a user's asserted state change over authoritative tool state.
- Exhaustive retrieval churn after all decision-critical dependencies are
  resolved.
- GEPA execution, iterative refinement, candidate search, test-driven prompt
  selection, or validation feedback.

## Prompt delta and rationale

The canonical instruction contained only the customer-service role,
one-action-per-turn constraint, policy-following requirement, and valid-JSON
requirement. The replacement preserves all four. It adds a compact process
contract covering:

1. dependency-closed planning;
2. decisive-fact elicitation and verification reuse;
3. exhaustive, net-value recommendations;
4. component/period arithmetic and symmetric reconciliation;
5. per-resource fact isolation;
6. schema-minimal, self-contained tool calls;
7. pre-write multi-item planning and post-write reads;
8. irreversible-action and transfer staging; and
9. explicit recovery rather than unsupported success claims.

These are general trigger-to-action-to-verification rules. They encode no
benchmark answer and do not change the unmodified `alltools` policy, toolkit,
system-prompt template, model, authentication, or developer-instruction
boundaries.

## Frozen artifact and experiment

- Baseline instruction: `prompts/banking_knowledge/baseline.md`
- Baseline normalized SHA-256:
  `e00faa515230c8648931f73ed25c9528418cccc522fe8936917f4c2a047bc5d2`
- Optimized instruction: `prompts/banking_knowledge/optimized.md`
- Optimized file SHA-256:
  `dddd25c976a631e2559c6afefc90582328ae0ca9bc78be07e565ea53e47717c9`
- Experiment: `experiments/optimized-test-alltools.toml`
- Matrix: 49 frozen test tasks, one trial, seed 300, concurrency 16,
  `alltools`, GPT-5.4/high evaluated agent, GPT-5.2/low user simulator, and 200
  maximum steps.

The experiment remains local-only and aggregate-only. Test outcomes must not be
used to revise this prompt. Results and trajectories must never be submitted to
a τ-bench leaderboard; any other publication requires fresh explicit
authorization.

## Execution status

The fresh vanilla train run
`vanilla-train-alltools-20260808T212330Z` completed at harness commit
`e289cf9`. It scored **23/48 (47.9167%)** in **14m03.159s**. All 48
trajectories ended with `user_stop`, there were no infrastructure errors, and
all 1,322 accepted dynamic-tool calls had their 1,322 results returned.

The vanilla held-out run `vanilla-test-alltools-20260808T215353Z` completed at
harness commit `57e184f`. It scored **15/49 (30.6122%)** in **17m18.564s**.
All 49 trajectories ended with `user_stop`, there were no infrastructure
errors, and all 1,726 accepted dynamic-tool calls had their 1,726 results
returned. Only aggregate output and infrastructure integrity were inspected;
no held-out task definition, task identity, trajectory, per-task reward, or
individual adapter audit was opened.

The optimized held-out attempt
`optimized-test-alltools-20260808T221206Z` ran at harness commit `57e184f` for
approximately **17m16s** and orchestrated all 49 configured trajectories.
Exactly one trajectory ended in a Codex turn-output timeout after the hard
600-second limit, with a 120-second idle limit, following an `item/started`
event. The fail-closed harness therefore produced no manifest, valid optimized
score, or valid vanilla-to-optimized delta. No held-out task identity,
definition, trajectory, per-task reward, or individual adapter audit was
opened, and the frozen prompt was not revised.

That original attempt remains invalid and unscored. Its exact, separately
authorized missing-only recovery is
`optimized-test-alltools-20260808T221206Z--recovery-c716dea3506a`. Recovery took
**7m23.253s** wall time; the one retried trajectory took **7m09.358s**. The
recovery skipped and preserved all 48 completed rows and audits, retried exactly
the sole missing row with its original simulation seed, and left the source run
immutable.

The recovered optimized run scored **23/49 (46.9388%)**, compared with the
vanilla held-out run's **15/49 (30.6122%)**: **8 additional passes** and an
observed increase of **16.3265 percentage points**. All 49 final trajectories
ended with `user_stop`; none ended in an infrastructure or unexpected error.
All 1,897 accepted dynamic-tool calls had their 1,897 results returned, and all
49 adapter audits passed.

The recovery used hash-pinned authorization `c716dea…`, the unchanged prompt
SHA-256 `dddd25c976a631e2559c6afefc90582328ae0ca9bc78be07e565ea53e47717c9`,
source harness commit `57e184f`, recovery harness commit `2ae5eb1`, and pinned
τ-bench commit `fc0055dc4e0a316c3f83133267fbd6faaa770992`. The exact
authorization is consumed; it permits no additional retry. No held-out task
identity, definition, trajectory, per-task reward, or individual adapter audit
was opened for human inspection during recovery or aggregate reporting.

This is an observed improvement on one local, single-trial held-out split. It
is not proof that the prompt caused the difference or that the result
generalizes. In addition, `task_002` and `task_008` had previously been exposed
during infrastructure diagnosis, so any held-out interpretation retains that
contamination caveat. These local results are not leaderboard results and do
not authorize publication, upload, or submission.
