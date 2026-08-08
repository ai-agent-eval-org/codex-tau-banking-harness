# Security

## Credential separation

The parent τ-bench process may receive `OPENAI_API_KEY` for the GPT-5.2 user
simulator and `alltools` embeddings. Before spawning Codex, the harness removes
OpenAI/Codex API-key and access-token variables, creates an isolated temporary
`CODEX_HOME`, and requires app-server `account/read` to report a managed
ChatGPT account. An API-key account, missing account, model fallback, or absent
GPT-5.4/xhigh entitlement aborts the run.

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

## Artifact redaction

Manifests contain hashes, non-secret plan/rate-limit metadata, version and Git
provenance, task IDs, and artifact paths. They reject secret-looking key names
or values. Do not attach raw environment dumps, Codex auth caches, cookies,
OAuth tokens, or Platform keys to an issue or pull request.

If a credential is ever written to a run artifact, stop the run, revoke and
rotate the credential at its provider, remove the artifact from disk and any
Git history or remote storage, and only then resume with a clean output
directory. Treat a committed credential as compromised even if the commit was
later reverted.
