# Exact interrupted-run retry authorization

This directory documents a local-only, one-shot recovery gate. No active
`resume-interrupted.json` record is present. The command is implementation, not
authorization.

Before any recovery inference, a human must freshly and explicitly authorize
exactly one retry of one named interrupted source run. Only then may
`authorizations/resume-interrupted.json` be created and committed. The harness,
authorization record, experiment config, full prompt artifact, and pinned
τ-bench checkout must all be clean when the command starts.

The record is one JSON object with exactly these fields and no others:

| Field | Required value |
| --- | --- |
| `format_version` | `1` |
| `authorization_type` | `single_interrupted_retry` |
| `experiment` | `optimized-test-alltools` |
| `source_run_basename` | Exact direct child name under `runs/` |
| `source_harness_commit` | Original 40-character harness commit |
| `source_results_sha256` | SHA-256 of immutable source `results.json` |
| `source_audit_set_sha256` | Canonical digest of every source audit filename and SHA-256 |
| `source_info_sha256` | Canonical SHA-256 of the persisted τ-bench `Info` object |
| `experiment_config_sha256` | SHA-256 of the exact experiment TOML |
| `system_prompt_file_sha256` | SHA-256 of the exact full prompt file, including terminal LF |
| `system_prompt_sha256` | SHA-256 of the exact model-visible full prompt |
| `tool_schema_sha256` | Frozen ordered runtime tool-schema SHA-256 |
| `expected_matrix_sha256` | Canonical digest of every expected task/trial/original-seed key |
| `permitted_retry_count` | `1` |

All digests are 64 lowercase hexadecimal characters. The schema contains no
credentials and no trajectory content. It pins authorization to a source
artifact without placing the failed task identity in public command output.

The command additionally requires all of the following:

- the authorization is a regular file committed in the current clean HEAD;
- every tracked harness byte and the vendored τ-bench checkout match their
  committed state, including protection against `assume-unchanged` and
  `skip-worktree` substitutions;
- the source is a direct child of `runs/`, has the authorized basename, and has
  no manifest;
- its exact optimized test matrix contains 48 reward-bearing non-
  infrastructure rows and one no-reward infrastructure-failure row, with no
  duplicates or other errors;
- its task payloads, configuration, full prompt, policy, tools, results digest,
  and exact adapter-audit set match the record.

Recovery stages a new ignored directory and never modifies the source. The
failed audit is preserved outside the active audit glob, the failed checkpoint
row is atomically omitted, and pinned τ-bench auto-resume receives the full
frozen configuration. The deterministic seed logic skips all completed keys and
runs only the one original-seed missing key.

An exclusive, fsynced attempt-claim file permits one attempt even if two
commands race or a process crashes. A receipt separately records source,
staging, task, `Info`, completed-row, and completed-audit digests. The 48
completed rows and audits must remain byte/canonically identical through
finalization. An ambiguous, started, or failed attempt cannot be repeated. A
completed checkpoint may only be finalized, and an existing final manifest is
terminal.

The final result is classified as a **single missing-only infrastructure
retry**, not an independent full-matrix rerun. Neither creating nor using a
record authorizes publication, upload, submission, additional trials, or a
leaderboard action.
