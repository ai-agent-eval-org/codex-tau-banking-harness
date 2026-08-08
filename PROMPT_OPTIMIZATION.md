# One-shot train-trace prompt optimization

## Frozen evidence and method

The only optimization evidence was the fresh train run
`vanilla-train-alltools-20260808T212330Z`. It contains the repository's 48
frozen train tasks and scored **23/48** in aggregate. The analysis read those
train trajectories once, split into two fixed halves for qualitative review,
then synthesized one general replacement for τ-bench's `AGENT_INSTRUCTION`.

No test task definition, test trajectory, test reward, or test result was
viewed. Earlier pilots and other runs were not optimization evidence. No model
inference, preflight, validation run, candidate evaluation, or leaderboard
submission was performed while authoring the prompt.

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

- Prompt: `prompts/banking_knowledge/optimized.md`
- SHA-256: `dddd25c976a631e2559c6afefc90582328ae0ca9bc78be07e565ea53e47717c9`
- Experiment: `experiments/optimized-test-alltools.toml`
- Matrix: 49 frozen test tasks, one trial, seed 300, concurrency 16,
  `alltools`, GPT-5.4/high evaluated agent, GPT-5.2/low user simulator, and 200
  maximum steps.

The experiment remains local-only and aggregate-only. Test outcomes must not be
used to revise this prompt, and neither results nor trajectories may be
submitted or published without fresh explicit authorization.
