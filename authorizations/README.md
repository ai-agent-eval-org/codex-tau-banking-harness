# Exact interrupted-run retry authorization

This directory documents a dormant, local-only recovery gate. It intentionally
contains no active `resume-interrupted.json` record.

The `resume-interrupted` command is implementation, not authorization. Before
any model work, a human must freshly and explicitly authorize exactly one retry
of one named interrupted source run. Only then may
`authorizations/resume-interrupted.json` be created and committed. The harness,
authorization record, experiment config, and pinned τ-bench submodule must all
be clean when the command starts.

The record is one JSON object with exactly these fields and no others. The
command verifies that its bytes are an ordinary file blob in the current HEAD;
"tracked and clean" alone is not accepted, so symlinks and Git index flags
cannot substitute different authorization bytes. The same byte-and-mode check
covers every tracked harness and vendored τ-bench file, so execution code hidden
by `assume-unchanged` or `skip-worktree` is rejected too.

| Field | Required value |
| --- | --- |
| `format_version` | `1` |
| `authorization_type` | `single_interrupted_retry` |
| `experiment` | `optimized-test-alltools` |
| `source_run_basename` | Exact direct child name under `runs/` |
| `source_harness_commit` | Original 40-character harness commit |
| `source_results_sha256` | SHA-256 of the immutable source `results.json` |
| `source_audit_set_sha256` | Canonical digest of every active source audit filename and file SHA-256 |
| `source_info_sha256` | Canonical SHA-256 of the persisted τ-bench `Info` object |
| `experiment_config_sha256` | SHA-256 of the exact experiment TOML |
| `agent_instruction_sha256` | Frozen optimized instruction SHA-256 |
| `effective_system_prompt_sha256` | Frozen rendered system-prompt SHA-256 |
| `tool_schema_sha256` | Frozen ordered runtime tool-schema SHA-256 |
| `expected_matrix_sha256` | Canonical digest of every expected task/trial/original-seed key |
| `permitted_retry_count` | `1` |

All digests are 64 lowercase hexadecimal characters. This schema contains no
credentials and no trajectory content. It pins authorization to a source
artifact without placing the failed task identity in public command output.

The command additionally requires all of the following before recovery:

- the record is tracked in the current commit and the harness is clean;
- the vendored τ-bench checkout is clean and exactly at the repository pin;
- the source is a direct child of `runs/`, has the authorized basename, and has
  no manifest;
- its exact frozen matrix contains 48 reward-bearing non-infrastructure rows
  and one no-reward infrastructure-failure row, with no duplicates or other
  errors;
- its task payloads, configuration, prompt, policy, tools, results digest, and
  exact adapter-audit set all match the record.

Recovery stages a new ignored directory and never modifies the source. The
failed audit is preserved outside the active audit glob, the failed checkpoint
row is atomically omitted, and pinned τ-bench auto-resume receives the full
frozen configuration. Before inference, the harness independently reconstructs
and exactly compares τ-bench's `Info` and task payloads; τ-bench's permissive
configuration-drift behavior is not trusted. Its deterministic seed logic skips
all completed keys and runs only the one original-seed missing key.

An exclusive, fsynced attempt-claim file permits one attempt even if two
commands race or a process crashes. A receipt separately records source,
staging, task, `Info`, completed-row, and completed-audit digests; those values
are recomputed from the authorized source rather than trusted from the receipt.
The 48 completed rows and audits must remain canonically/byte identical through
finalization. An ambiguous, started, or failed attempt cannot be repeated. A
completed checkpoint may only be finalized, and an existing final manifest is
terminal. Source hashes, clean HEAD inputs, and the pinned clean τ-bench checkout
are checked again immediately before inference and before the manifest.

The final result is classified as a **single missing-only infrastructure
retry**, not an independent full-matrix rerun. The manifest records that the
retry was selected from a no-reward infrastructure failure rather than a task
reward.

Neither creating nor using a recovery record authorizes publication, upload,
submission, additional trials, or a leaderboard action.
