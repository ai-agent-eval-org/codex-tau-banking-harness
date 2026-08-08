# Five-task alltools pilot status

No valid score was produced on 2026-08-08.

The pilot was predeclared as one trial each over `task_002`, `task_008`,
`task_010`, `task_012`, and `task_014`, using GPT-5.4/high through personal
ChatGPT authentication, GPT-5.2/low for the user simulator, seed 300,
`max_steps = 200`, and τ-bench's unmodified `alltools` retrieval profile.

Two independent real tasks, `task_002` and `task_008`, followed the same
sequence:

1. `KB_search_bm25` completed and its result was returned to app-server.
2. `KB_search_dense` completed and its result was returned to app-server.
3. `shell` completed and its result was returned to app-server.
4. Codex app-server emitted no subsequent event and hit the 120-second
   no-event watchdog at `item/tool/call:responded`.

The remaining three tasks were cancelled because the completed records were
infrastructure errors and could not form a Pass@1 estimate. Partial files stay
under the ignored local `runs/` directory and must not be published.

Isolation checks established:

- a fresh app-server completes one dynamic shell call and continuation;
- a fresh app-server completes BM25, dense, and shell sequentially when their
  returned payloads are tiny synthetic strings;
- τ-bench retrieval, cached embeddings, sandbox execution, ChatGPT auth, and
  GPT-5.4 model selection all initialized successfully;
- the failure therefore occurs when app-server continues after the real
  τ-bench shell result, not while the retrieval tool executes;
- every trajectory already creates a fresh local app-server and thread, so
  restarting the harness process does not clear the failure.

This is an infrastructure failure, not a zero reward. Do not report or compare
it as a benchmark score, and do not submit it to any leaderboard.

The adapter-level failure diagnosis exposed task identities and retrieval
sequences for `task_002` and `task_008`; `task_002`'s public scenario was also
inspected locally. Any future held-out claim including those tasks must disclose
that contamination. No prompt was optimized from this evidence.
