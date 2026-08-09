# One-shot full-prompt optimization

## Method and evidence boundary

The optimization evidence is the retained local run
`vanilla-train-alltools-20260808T212330Z`. This is Step A of the study: the
canonical alltools baseline was run once on the frozen 48-task train partition,
producing 48 model-visible production trajectories. The run scored **23/48**;
all trajectories ended with `user_stop`, no infrastructure error occurred, and
all 1,322 accepted dynamic-tool calls received their results.

The prompt pass used only those completed train trajectories, the canonical
baseline prompt, all 17 authoritative model-visible tool contracts, and fixed
runtime metadata. It did not use task definitions, evaluation criteria, grader
checks, gold actions, provider payloads, test or validation material, pilot
material, prior optimized prompts, prior optimization reports, or prior
optimized results.

This was a one-shot synthesis inspired by prompt-reflection research, not GEPA.
There was no candidate population, mutation or selection loop, candidate
evaluation, validation feedback, test feedback, or iterative revision.

## Canonical optimizer instruction

[`prompts/banking_knowledge/optimizer.md`](prompts/banking_knowledge/optimizer.md)
is the exact optimizer instruction used for this pass. Its SHA-256 is:

`9241b834b4c6a3b58301a95054284d1b070884364e5c764b32c07858f8eef917`

The instruction makes tool descriptions and schemas first-class evidence. It
requires complete trace and tool coverage, causal failure analysis, successful
traces as regression controls, one synthesis, and a complete replacement for
the baseline `<instructions>` plus `<policy>` prompt. It prohibits
trace-specific values, hidden evaluator material, test feedback, prior
candidates, and performance claims in the resulting banking prompt.

## Leakage-safe evidence export

[`src/codex_tau/optimizer_packet.py`](src/codex_tau/optimizer_packet.py)
fail-closes unless the source is the exact retained 48-task, trial-zero,
alltools train run. It removes hidden task and grader fields and exports:

- every model-visible message, tool call, and tool result from all 48 traces;
- only the scalar binary outcome and `user_stop` termination state per trace;
- the canonical baseline prompt;
- the canonical optimizer instruction;
- all 17 authoritative tool descriptions, input schemas, output schemas,
  documented errors, and examples; and
- a hash-pinned evidence manifest and fixed-runtime contract.

The packet can be reconstructed locally with:

```bash
uv run python -m codex_tau.optimizer_packet \
  runs/vanilla-train-alltools-20260808T212330Z \
  /tmp/codex-tau-optimizer-packet
```

The source `results.json` SHA-256 was
`49e136b4385989cdcbdd322ccf804f753da050b3f57d3edb1bbc4187ee020ff2`.
The exported evidence manifest verified 48/48 traces, 23 successes, 25
failures, 17/17 tools, the frozen split digest
`48224cbcbfcbad9f149842a64bc26b920ade3335d4e9d8f735b9d135f5394a08`,
and tool-schema digest
`3e895cf7dec550977f7b75242e3c34d961ebe61c33ec34159803874117789801`.

## Synthesis

A clean GPT-5.6-Sol subagent received only the leakage-safe packet and a
completed coverage ledger. It inspected all 48 traces and all 17 tool
contracts, then produced exactly one optimization report and one prompt. Its
complete output SHA-256 was
`a9d02ce6f81524da0d7f9883f919aab173d86b08567387d892c5f0c1a7728c10`.

An earlier GPT-5.4 synthesis finished during cancellation, but its output was
quarantined. It was not shown to the Sol optimizer, compared with the Sol
candidate, copied into the prompt, or evaluated. The Sol output is the sole
eligible candidate.

The final report accounted for every failed train trace in six mutually
exclusive primary clusters:

| Prompt-controllable process cluster | Count |
| --- | ---: |
| Decision and action gating | 6 |
| Multi-part completion and result handling | 8 |
| Security-safe sequencing and recoverable-path use | 4 |
| Calculation, scope, and allocation grounding | 4 |
| Transfer selection and result truthfulness | 2 |
| Discoverable-tool schema discipline | 1 |
| **Total** | **25** |

All 23 successful traces were used as regression controls. The accepted rules
remain general: inventory complete requests, distinguish advice from mutation,
retrieve only decision-critical policy, select tools by their exact contracts,
keep resources isolated, consume authoritative results, sequence security
actions safely, ground calculations and shared allocation, and claim only
verified terminal states.

The pass rejected blanket confirmation, mandatory use of every retrieval
method, blanket transfer, repeated authentication, invented post-write reads,
and hard-coded products, formulas, thresholds, task sequences, or examples.

## Frozen optimization unit

The optimization unit is the complete textual system prompt:

```text
<instructions>...</instructions>
<policy>...</policy>
```

[`prompts/banking_knowledge/baseline.md`](prompts/banking_knowledge/baseline.md)
is byte-parity tested against τ-bench's pinned `SYSTEM_PROMPT`, canonical
`AGENT_INSTRUCTION`, and runtime alltools policy. The harness reads it as the
complete baseline prompt and appends nothing at runtime.

[`prompts/banking_knowledge/optimized.md`](prompts/banking_knowledge/optimized.md)
is the one complete Sol replacement at the same abstraction level. The
structured τ-bench tool schemas remain separate, authoritative, and
unmodified. The experiment config and the runtime execution allowlist both pin
the exact path and hash, so editing the prompt and merely updating the TOML is
not sufficient to authorize another prompt.

- Baseline file SHA-256:
  `c51896d46edd67711f8288735462b104202d4b250609ced2e5c16ded52ba90c3`
- Baseline model-visible SHA-256:
  `40e0c2afebb858e37b99b3dffcaba2cf1f2d48ad26908612fd4b5756d4899780`
- Optimized file SHA-256:
  `4022d30ae66d704fdc1954202aafd94ef0140f3dea65a53b0f154b702ec47e4c`
- Optimized model-visible SHA-256:
  `189d7da5df37f03d78049d6d3e889559ef802a22471e27ac18e707da4fe3043a`
- Bounded config:
  `experiments/optimized-test-alltools.toml`

## Integrity status

The frozen prompt exactly matches the `<optimized_prompt>` section of the Sol
output. Automated inspection found no task or trace IDs, private identifiers,
email addresses, phone numbers, UUIDs, copied dialogue, specific monetary
values or dates, hidden evaluator terms, grader terms, reward terms, benchmark
language, or test/validation language in the prompt.

Model-free tests and preflight verify that the optimized arm remains the exact
49-task test partition, one trial, seed 300, concurrency 16, GPT-5.4/high via
personal ChatGPT authentication, GPT-5.2/low for the official simulator,
unmodified alltools policy and tool schemas, empty developer instructions, no
Codex-native capabilities, reroute detection, complete dynamic-tool delivery
audits, incremental checkpointing, final manifests, and a 64 MiB app-server
stream-reader limit.

The authorized adaptive retest started from clean commit
`a829bd3f4bb79af2a6ae5129b970493434d3f38e` as
`optimized-test-alltools-20260809T033050Z`. Forty-eight trajectories ended
with `user_stop` and have binary rewards. One trajectory ended with
`infrastructure_error` and no reward after the evaluated agent returned an
empty `AssistantMessage` containing neither content nor a tool call. The
harness therefore refused to create a manifest or certify a 49-task score.

All 49 adapter audits still verified personal ChatGPT authentication,
GPT-5.4/high, the frozen prompt hashes, no model reroute, no instruction-source
injection, explicit empty developer instructions, no Codex-native capability
event, the 64 MiB reader, and complete delivery of all 1,497 accepted
dynamic-tool calls with zero pending results. The checkpoint SHA-256 is
`0a8d8280b2d28866f85913bb6422d5dccee7a7922adecec69fa638c88797dee7`.

No partial score is reported, and no test outcome was used to revise the
prompt. Completing the matrix requires a separately authorized, single
missing-only infrastructure retry of this exact immutable source run. Until
that succeeds and the final manifest passes, the current Sol prompt has no
certified eval-set score.

Any completed result is an **adaptive retest**, not a pristine held-out
evaluation, because the 49-task partition was previously used by the retained
vanilla evaluation and retired demo runs. The earlier infrastructure exposure
of `task_002` and `task_008` remains an additional contamination caveat. Test
outcomes may be reported only in aggregate and must never be used to revise
this frozen prompt.

Nothing in this repository authorizes publication, upload, or leaderboard
submission.
