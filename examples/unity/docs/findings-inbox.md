# Findings inbox

Raw, unstructured, append-only. Written mid-task by whoever hit the thing.

This is **not** the record. Promoting an entry into
[UNITY-TOOLING-NOTES.md](../UNITY-TOOLING-NOTES.md) is a separate deliberate act:
version-stamp it, say what was observed versus inferred, and put it in one home.
An inbox that auto-promotes is just a second record that drifts from the first.

Nothing here has been verified. Read it as a to-check list.

---

- **2026-08-06 17:33** — PreToolUse hook fired in a session that predates it - contradicts the recorded claim that hooks are snapshotted at session start and need a new session

- **2026-08-06 17:33 · 30min** — project 'ask' beats personal 'allow', so 'don't ask again' on an ask-listed tool writes an entry that can never win and prompts forever

- **2026-08-06 17:33** — AGENTS.md already required contributing findings and it was not happening - the instruction was fine, the mid-task cost was too high

- **2026-08-07 · from M-001** — mcp eval rejects a timeout outside 1-30000ms with Bad Request 'Timeout must be between 1ms and 30000ms' - the bound is undocumented and the error only appears after the call

- **2026-08-07 · from M-001** — mcp eval rejects top-level 'using' directives, CS1001 Identifier expected at line 1 col 24 - fully-qualified names work, so the snippet has to be written without usings

- **2026-08-07 · from M-001** — official UnityMCP returned 'Unable to connect' for import_model/generate_model/instances while unity-editor-mcp was healthy against the same Editor in the same minutes - two servers, one Editor, independent liveness

- **2026-08-07 · from M-001** — Object.GetInstanceID() is obsolete on this version, CS0619, use GetEntityId

- **2026-08-07 · from M-001** — a pre-existing CS0104 in the Claudesona package sat in Editor.log all session and surfaced in every log grep unrelated to the work - grepping Editor.log for 'error CS' returns other people's errors and there is no way to scope it to the current compile

- **2026-08-07 · from M-001** — the trap-check hook matches on command text not command effect: it fired the manifest rule on 'git diff Packages/manifest.json' and the CLI rule on a grep of docs/unity-cli.md. 5 of 8 fires did not describe the call. Fired again on a Write to a .md file while writing this up

- **2026-08-07 12:25 · 15min** — a project-scoped PreToolUse hook pointing at a script inside that same project makes the script undeletable mid-session: removing it makes every matched tool (Bash, Edit, Write) fail closed, and fixing settings.json needs exactly those tools. Point hooks outside the tree they guard, and make them exit 0 when the target is missing

- **2026-08-07 12:25 · 5min** — note.py crashed on its own success message after a rename -- INBOX was written, then NameError. The write happens before the confirmation, so the entry landed and the tool looked like it failed
