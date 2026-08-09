# Security

## Credential separation

The parent τ-bench process may receive `OPENAI_API_KEY` only for the GPT-5.2
user simulator and the official embeddings used by the fixed `alltools`
retrieval profile. Before spawning Codex, the harness removes
OpenAI/Codex API-key and access-token variables, creates an isolated temporary
`CODEX_HOME`, and requires app-server `account/read` to report a managed
ChatGPT account. An API-key account, missing account, model fallback, or absent
required entitlement aborts the run. Evaluated banking agents remain fixed to
GPT-5.4/high; the separate one-shot optimizer requires GPT-5.6-Sol/max through
the same personal ChatGPT boundary.

The temporary Codex home links to the existing auth file; it never copies,
prints, serializes, or commits its contents. The repository ignores `.env*`,
`auth.json`, run artifacts, τ-bench databases, and embedding caches.

## Capability isolation

The pinned strict Codex config disables its configurable native shell/exec,
web/browser, MCP, apps, plugins, hooks, goals, user-input, workspace dependency,
and subagent features. Codex runs from an empty directory. The adapter aborts
on any filesystem, plan, or other app-server request/item that indicates a
denied native capability. Only runtime dynamic tools derived from τ-bench
`Tool` objects are accepted.

The standalone optimizer uses the same sanitized child environment, empty
temporary working directory, empty developer instructions, instruction-source
rejection, reroute detection, and field-by-field verification of app-server's
effective turn-settings notification. Its dynamic catalog contains only seven
packet-specific tools for bounded evidence reads, external analysis-ledger
writes/reads, and one final submission. Context compaction is the sole added
app-server item type and is counted only as a lifecycle event; it grants no
filesystem, network, memory, or other native capability. The evaluated-agent
allowlist does not accept context compaction.

## Artifact redaction

Manifests contain hashes, non-secret plan/rate-limit metadata, version and Git
provenance, task IDs, and artifact paths. They reject secret-looking key names
or values. Optimizer reports and candidates remain under the ignored local
`optimizer-runs/` directory. Do not attach raw environment dumps, Codex auth
caches, cookies, OAuth tokens, Platform keys, train traces, or optimizer
artifacts to an issue or pull request.

If a credential is ever written to a run artifact, stop the run, revoke and
rotate the credential at its provider, remove the artifact from disk and any
Git history or remote storage, and only then resume with a clean output
directory. Treat a committed credential as compromised even if the commit was
later reverted.
