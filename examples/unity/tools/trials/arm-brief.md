# Trial brief — one arm, one agent, written blind

Hand this to a subagent, one per arm, **serially**. Substitute `<ARM>` and the arm-specific
block. Run `tools/trials/three-way-setup.sh` first, in the session that spawns them; arm C's
tools are absent from any session that started while its server was down.

## Why serial

One Editor serves all three arms. Two agents running concurrently are two agents mutating one
scene, not two trials. This is a property of the subject and bounds trial parallelism no matter
how many agents are available.

## The task

Identical to T-001 and T-003, so results compare directly. In the currently open scene:

1. A root empty GameObject named exactly `T00N-Root-<ARM>`
2. Containing a child empty named exactly `T00N-Child-<ARM>`, at **local** position `(1, 2, 3)`
3. The child carrying a `BoxCollider` whose `size` is `(2, 2, 2)`

Then **verify by reading the state back.** A write that does not echo the resulting state has
not been verified — and on every arm measured so far, most mutating calls echo only identity.

## Constraints for every arm

- Do **not** open, close, or restart the Editor, and do **not** save the scene. A human may be
  at the keyboard and other agents share this Editor.
- Do **not** read another arm's report. Blind means blind.
- Touch nothing you did not create.
- Report failures in full, with literal error text. The failed attempts are the most valuable
  part of the report; do not tidy them away.

## Arm-specific

**Arm A — the `unity` CLI only.** No `mcp__*` tool.
`export PATH="$PATH:/c/Users/asas/AppData/Local/Unity/bin"; export MSYS_NO_PATHCONV=1`
Then `unity command <tool> --flag value --json`.
- **Only `--flag value` binds.** `name=X` and JSON-blob arguments are silently ignored and
  still return `"success": true` — on a read that returns wrong data, on a write it executes
  with defaults and creates stray objects.
- `unity command <tool> --help` does **not** give per-tool help; it prints generic usage. The
  real schema is the `parameters` array in `unity list --json`.
- `MSYS_NO_PATHCONV=1` matters: Git Bash rewrites any argument starting with `/`, and every
  Unity hierarchy path does.
- Capture exit codes as `out=$(cmd 2>&1); code=$?`. Piping into `head` first reports `head`'s
  status, not the command's.

**Arm B — the official MCP only**, `mcp__unity-editor-mcp__*`, loaded via `ToolSearch`.
- `get_scene_hierarchy` has no filter, depth or pagination parameter and will exceed the
  tool-result limit on a real scene. Use `find_gameobjects` with a filter.

**Arm C — CoplayDev only**, `mcp__UnityMCP__*`, loaded via `ToolSearch`. Coarse dispatchers
(`manage_gameobject` with an `action` argument) rather than fine-grained tools.
- The record's arm-C claims all rest on package `v10.0.0`, three releases behind. Anything you
  observe supersedes them; say so explicitly where you differ.

## Known, do not re-derive

- Both A and B require Unity's **serialized** field name `m_Size`, not the public API `size`.
  Whether C does too is an open question worth answering.
- `instanceId` collides nondeterministically across distinct objects — it is
  `Object.GetEntityId()` under a legacy name. Use `globalId` or `hierarchyPath`.

## The report

Write to `docs/trials/T00N/arm-<arm>.md`, in your own words, before any comparison. Include:
versions actually observed; every call in order with literal arguments; step count; what
worked first try and what did not; friction; surprises; whether each mutating call echoed
state or needed a separate read; and the quoted read-back proving the final state.

Plain prose for a stranger debugging their own setup. No session narration, no references to
this brief, no comparison to other arms.
