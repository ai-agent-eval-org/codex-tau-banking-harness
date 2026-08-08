# Five-task alltools pilot status

The transport blocker was fixed and verified locally on 2026-08-08. The full
five-task pilot has not been rerun, so there is still no five-task Pass@1 to
report.

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

- 37 model-free tests passed, including the large-line transport regression.
- Synthetic 123,322-byte repeated and exact captured payloads both completed
  after raising the reader limit.
- One post-fix `task_002` trial completed normally in 89.15 seconds with 28
  messages, 10 dynamic-tool results, `user_stop`, and reward `1.0`.
- ChatGPT authentication, GPT-5.4/high, GPT-5.2/low, the canonical prompt,
  unmodified `alltools`, tool-only capability isolation, and seed 300 were
  preserved.

The earlier infrastructure-error records remain under ignored local `runs/`
directories. They are not zero rewards and must not be included in benchmark
scores. The post-fix verification is one task, not a five-task estimate.

The adapter-level diagnosis exposed `task_002` and `task_008` identities and
retrieval sequences; `task_002` was rerun after the transport fix. Any future
held-out claim including these tasks must disclose that contamination. No
prompt was optimized from this evidence, and no result may be submitted under
the repository's standing non-submission rule.
