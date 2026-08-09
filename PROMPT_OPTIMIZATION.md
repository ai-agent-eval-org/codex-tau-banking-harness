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

## Optimizer instruction provenance

[`prompts/banking_knowledge/optimizer.md`](prompts/banking_knowledge/optimizer.md)
is now the instruction used by the standalone `codex-tau optimize` command.
Its SHA-256 is:

`73e30696eef8ade7fc2079c85c40374c1e6f18321aa3442ecb9a6c18116a4992`

The instruction makes tool descriptions and schemas first-class evidence. It
requires complete trace and tool coverage, causal failure analysis, successful
traces as regression controls, one synthesis, and a complete replacement for
the baseline `<instructions>` plus `<policy>` prompt. It prohibits
trace-specific values, hidden evaluator material, test feedback, prior
candidates, and performance claims in the resulting banking prompt.

The active [`prompts/banking_knowledge/optimized.md`](prompts/banking_knowledge/optimized.md)
was generated with this exact instruction by the standalone Luna run described
below. The previously active Sol prompt used a historical instruction preserved
at commit `a829bd3f4bb79af2a6ae5129b970493434d3f38e`; that historical instruction's
SHA-256 is
`9241b834b4c6a3b58301a95054284d1b070884364e5c764b32c07858f8eef917`.

## Standalone execution

```bash
uv run codex-tau optimize --preflight-only
uv run codex-tau optimize
```

The inference command prepares the packet internally, creates one fresh
ephemeral app-server thread using personal ChatGPT authentication and
GPT-5.6-Luna/max. Only that subprocess enables app-server's local Code Mode host,
which can orchestrate the seven audited packet tools but has no shell,
filesystem, web, network, memory, MCP, app, plugin, or subagent capability. It
requires all 48 traces and all 17 tool contracts to be fully read and analyzed,
then requires the complete external ledger to be reread before accepting one
report and one replacement prompt. Trace contents are untrusted evidence, not
instructions. A malformed non-submission packet call is returned to the same
turn for correction and recorded by hashed tool name, error, and arguments in
the final manifest. Once structural coverage is complete, the harness retains
the sole submitted report and prompt exactly as supplied: it performs no
keyword, content, format, length, PII, or semantic rejection. Leakage safety
comes from the hash-pinned train-only packet boundary, not output heuristics.
App-server context compaction is counted as a lifecycle event.

The command has no candidate search, automatic retry, or evaluation step. Its
ignored `optimizer-runs/one-shot-<timestamp>/` bundle is a candidate only; the
command does not overwrite the active prompt or authorize promotion, testing,
publication, or submission.

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

## Current Luna synthesis

The authorized standalone run
`optimizer-runs/one-shot-20260809T152843Z` used one fresh personal-ChatGPT
app-server thread at GPT-5.6-Luna/max. It received only the fixed train packet,
completed all required structural coverage, and made one submission in one
turn with no retry. The audit records 48 complete trace analyses, 17 complete
tool analyses, a complete reread ledger, 631 dynamic packet-tool calls and 631
returned results, zero pending results, zero recoverable tool errors, no model
reroute, empty developer instructions, and no instruction sources or native
capabilities.

The ignored local bundle contains the exact submitted report and prompt. Their
SHA-256 values are:

- Optimization report:
  `70ee37665e64dbd9884ebc7d5d03a87c33c6d6102e89cf760eed8136bbd416fe`
- Optimized prompt:
  `91fe41860cca2655f664ba4f8a1a8251aa43d567ecee08bfd67f5ab03a0d8550`

The prompt was promoted without editing and is byte-identical to the submitted
candidate. No output heuristic, lexical scan, PII scan, format check, or
semantic veto selected or rewrote it. Its evidence boundary is enforced by the
fixed train-only packet and complete-coverage audit.

For history only, the previously active GPT-5.6-Sol prompt was evaluated in the
adaptive retest described below. An earlier GPT-5.4 synthesis was quarantined
and never compared, promoted, or evaluated. Neither historical candidate was
included in the Luna packet.

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
is the one complete Luna replacement at the same abstraction level. The
structured τ-bench tool schemas remain separate, authoritative, and
unmodified. The experiment config and the runtime execution allowlist both pin
the exact path and hash, so editing the prompt and merely updating the TOML is
not sufficient to authorize another prompt.

- Baseline file SHA-256:
  `c51896d46edd67711f8288735462b104202d4b250609ced2e5c16ded52ba90c3`
- Baseline model-visible SHA-256:
  `40e0c2afebb858e37b99b3dffcaba2cf1f2d48ad26908612fd4b5756d4899780`
- Optimized file SHA-256:
  `91fe41860cca2655f664ba4f8a1a8251aa43d567ecee08bfd67f5ab03a0d8550`
- Optimized model-visible SHA-256:
  `91fe41860cca2655f664ba4f8a1a8251aa43d567ecee08bfd67f5ab03a0d8550`
- Bounded config:
  `experiments/optimized-test-alltools.toml`

## Integrity status

The frozen prompt is an exact byte match for the sole Luna submission. Its
model-visible SHA-256 equals its raw file SHA-256 because the submitted text has
no terminal newline. Integrity is established structurally: the source packet
was the hash-pinned 48-trace train export; the optimizer had no test, web,
filesystem, memory, app, plugin, MCP, subagent, or native Codex tool access; all
required trace and tool analyses completed; and the harness accepted exactly
one submission without content-based rejection or rewriting.

Model-free tests and preflight verify that the optimized arm remains the exact
49-task test partition, one trial, seed 300, concurrency 16, GPT-5.4/high via
personal ChatGPT authentication, GPT-5.2/low for the official simulator,
unmodified alltools toolkit and structured tool schemas, empty developer
instructions, no Codex-native capabilities, reroute detection, complete
dynamic-tool delivery audits, incremental checkpointing, final manifests, and
a 64 MiB app-server stream-reader limit. The current Luna prompt has no test
score yet.

For historical comparison only, the previously active Sol prompt's adaptive
retest finalized as
`optimized-test-alltools-20260809T033050Z--recovery-bb161af26fd2`. It scored
**19/49 (38.7755%)**, versus the canonical alltools baseline's **15/49
(30.6122%)**. A separately authorized missing-only recovery replaced one
original no-reward infrastructure row and cryptographically preserved the
other 48. Its results SHA-256 is
`ad72c1e994dc916320506823b948e8fde5766f146f028fb14283900fa0ddb332`,
and its manifest SHA-256 is
`af20e5b9001cff6ae1dad53392767e13de6b2b53c1989f97d87aa4ed42913f1c`.
That result does not score the Luna prompt, and its execution and retry
authorizations are consumed.

Any future result is an **adaptive retest**, not a pristine held-out
evaluation, because the 49-task partition was previously used by the retained
vanilla evaluation and retired demo runs. The earlier infrastructure exposure
of `task_002` and `task_008` remains an additional contamination caveat. Test
outcomes may be reported only in aggregate and must never be used to revise the
frozen prompt.

Nothing in this repository authorizes publication, upload, or leaderboard
submission.
