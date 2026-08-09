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
| Agent prompt | Standard τ-bench `LLMAgent` | Exact same constructor and bytes |
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

## Fresh alltools and optimized arms

The `vanilla-train-alltools` and `vanilla-test-alltools` experiments preserve
the canonical τ-bench agent instruction and `SYSTEM_PROMPT` rendering, but use
the `alltools` retrieval policy and toolkit. They are internal baselines for the
prompt study, not extensions of the terminal-use reference profile and not
reference-comparable.

The completed `optimized-test-alltools` arm differed again by replacing only
the `AGENT_INSTRUCTION` substitution with one path-and-hash-pinned artifact
derived in a single pass from fresh vanilla train traces. τ-bench's
`SYSTEM_PROMPT`, authoritative alltools domain policy, tools, model, reasoning,
simulator, task IDs, trial count, step limit, and concurrency remained fixed,
with no additional developer instructions. One original no-reward
infrastructure failure was recovered through an exact, original-seed,
missing-only retry; 48 completed rows and audits were preserved and skipped.

The recovered optimized arm scored 23/49 (46.9388%), while the fresh alltools
vanilla test arm scored 15/49 (30.6122%). That observed single-trial difference
is comparable only within this local alltools methodology. It is not proof of
causality or general performance and is not comparable with the external
terminal-use artifact. The previously disclosed exposure of `task_002` and
`task_008` remains a contamination caveat for held-out interpretation.
