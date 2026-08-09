# Reference parity audit

The external `results.json` artifact was generated on 2026-03-25. This harness
is pinned to τ-bench v1.0.1 at
`fc0055dc4e0a316c3f83133267fbd6faaa770992` (2026-07-16). The artifact's
recorded Git commit, `d82e292428a5e43e271fce4b042f7c2dabf5fd65`, is not
available in the public τ-bench or example-project repositories, so its full
source configuration cannot be reconstructed.

## Controllable trajectory settings

| Setting | External artifact | Reference profile |
| --- | --- | --- |
| Agent model | GPT-5.4 | GPT-5.4 |
| Reasoning | high | high |
| User simulator | GPT-5.2/low | GPT-5.2/low |
| Seed | 300 | 300 |
| Trial-0 derived simulation seed | 626729 | 626729 |
| Retrieval | terminal_use | terminal_use |
| Maximum steps | 200 | 200 |
| Maximum consecutive errors | 10 | 10 |
| Agent prompt | Standard τ-bench `LLMAgent` | Exact same canonical constructor and bytes |
| Extra Codex instructions | Not applicable | Explicitly disabled |
| Codex-native tools | Not applicable | Omitted; only τ-bench dynamic tools |

## Remaining differences

- The external artifact uses standard `llm_agent`; this harness must use Codex
  app-server with personal ChatGPT authentication. App-server owns the internal
  reasoning/tool continuation loop, whereas `llm_agent` makes one Platform API
  generation after each user or tool message. This is an irreducible
  architecture and billing-boundary difference.
- The external artifact contains 97 tasks times four trials. The bounded local
  test contains the frozen 49-task subset times one trial. It matches trial 0,
  but not the reference's sample size.
- The artifact predates v1.0.1. On the same 49 task IDs, 42/49
  `evaluation_criteria` values are byte-identical, 48/49 descriptions are
  identical, and 48/49 user-tool definitions are identical. All 49 user
  scenarios and initial states are identical. The banking policy also differs
  by a heading and one blank line. Later τ-bench commits changed banking data,
  tool behavior, and grading fixes, so scores are not version-identical.
- The artifact does not record complete tool schemas, Codex/app-server version,
  service tier, retry policy, concurrency, output-token limits, or provider
  request defaults. Those cannot be proven equal from the artifact.
- ChatGPT app-server inference and Platform API inference may apply different
  provider-side defaults even when model, reasoning effort, prompt bytes, and
  tool schemas match.

The reference profile is therefore a controlled current-v1.0.1 comparison, not
an exact reproduction of the March artifact. Any score comparison must retain
that qualification.

## Alltools prompt-study arms

The `vanilla-train-alltools` and `vanilla-test-alltools` experiments use the
canonical τ-bench alltools prompt and toolkit. Their complete model-visible
prompt is exposed byte-for-byte in `prompts/banking_knowledge/baseline.md` and
parity-tested against the pinned τ-bench constructor and runtime policy. They
are internal baselines for the prompt study, not extensions of the terminal-use
reference profile and not reference-comparable.

The current optimized artifact is a path-and-hash-pinned replacement for the
complete textual alltools system prompt, including both `<instructions>` and
`<policy>`. GPT-5.6-Sol synthesized it once from a leakage-safe packet of the
48 retained train traces and all 17 authoritative tool contracts. The
structured alltools schemas, evaluated model, reasoning, simulator, task
matrix, step limit, authentication boundary, and empty developer instructions
remain fixed.

The final current-Sol adaptive retest scored 19/49 (38.7755%), versus 15/49
(30.6122%) for the canonical alltools baseline. One original no-reward
infrastructure row was replaced by a separately authorized, single
missing-only retry; the final manifest proves the other 48 rows remained
unchanged and that no independent full-matrix rerun occurred. This is
reused-holdout evidence rather than a pristine held-out result because the
partition was used by the retained vanilla arm and retired demos. It is not
comparable with the external terminal-use artifact. The previously disclosed
exposure of `task_002` and `task_008` remains an additional contamination
caveat.
