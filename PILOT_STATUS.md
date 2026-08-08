# Five-task alltools concurrency status

The transport blocker and the four-trial concurrency ramp were verified locally
on 2026-08-08. Both five-task/four-trial runs scored **65.0% Pass@1**: 13 of
20 trajectories passed at concurrency eight and at concurrency 16.

The bounded ramp is:

1. `task_002` and `task_008`, four trials each, concurrency two;
2. if every trajectory passes infrastructure validation, the five explicit
   pilot tasks, four trials each, concurrency eight; and
3. if concurrency eight remains clean, rerun that exact 20-trajectory matrix
   at concurrency 16.

The concurrency-two validation completed all eight trajectories in 8m59s and
scored 75.0% (6/8). The concurrency-eight pilot completed all 20 trajectories
in 5m15s and scored 65.0% (13/20). The concurrency-16 scaling trial completed
the same matrix in 3m16s and scored 65.0% (13/20). Relative to concurrency
eight, concurrency 16 reduced wall time by 38.0% and increased trajectory
throughput by 61.2%. All 48 trajectories ended with `user_stop`; none ended in
an infrastructure or unexpected error.

Each trajectory has a distinct task-and-seed audit path, and `results.json` is
checkpointed after every completed simulation. Model-free checks pass (42
tests). Every run audit verified personal ChatGPT authentication, GPT-5.4/high,
empty instruction-source discovery, no model reroute, no denied Codex-native
capability, and clean shutdown. The five-task pilot completed 324 authoritative
τ-bench dynamic-tool calls at concurrency eight and 321 at concurrency 16.

## Root cause and fix

Codex app-server lifecycle events echo complete dynamic-tool results. Python's
`asyncio.create_subprocess_exec` defaults each subprocess stream reader to a
64 KiB line limit. A real `task_002` shell result was 123,322 bytes, so the
app-server's corresponding `item/completed` JSON line exceeded that default.
The harness's stdout reader task failed silently while app-server remained
alive, which looked like a post-tool continuation stall.

The harness now:

- sets an explicit 64 MiB per-line reader ceiling for app-server stdout and
  stderr;
- reports background reader failures and unexpected stdout closure
  immediately;
- records the reader ceiling in preflight, per-task audits, and manifests; and
- has model-free regression coverage for a 128 KiB JSON-RPC line.

The ceiling is more than 500 times the observed failing result and more than
eight times the current banking-domain data tree. It is a bounded maximum
buffer size, not an eager per-process allocation.

## Verification evidence

- 42 model-free tests passed, including the large-line transport regression and
  multi-trial audit/result matrix coverage.
- Synthetic 123,322-byte repeated and exact captured payloads both completed
  after raising the reader limit.
- One post-fix `task_002` trial completed normally in 89.15 seconds with 28
  messages, 10 dynamic-tool results, `user_stop`, and reward `1.0`.
- ChatGPT authentication, GPT-5.4/high, GPT-5.2/low, the canonical prompt,
  unmodified `alltools`, tool-only capability isolation, and seed 300 were
  preserved.

The earlier infrastructure-error records remain under ignored local `runs/`
directories. They are not zero rewards and are not included in either score.
The verified concurrency-two, concurrency-eight, and concurrency-16 manifests
are also local, ignored artifacts and are not committed.

The adapter-level diagnosis exposed `task_002` and `task_008` identities and
retrieval sequences; `task_002` was rerun after the transport fix. Any future
held-out claim including these tasks must disclose that contamination. No
prompt was optimized from this evidence, and no result may be submitted under
the repository's standing non-submission rule.
