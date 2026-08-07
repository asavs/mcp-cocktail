# mcp-cocktail

A record of how the Unity agent tooling — the `unity` CLI and the two Unity MCP servers —
actually behaves, plus the machinery that puts it in front of you *before* you pay for a
trap rather than after.

Point it at any Unity project. Nothing here is about a particular game.

## Why this is its own repo

The record started inside a game repo, which is where the evidence was. It stopped being
the right home once the content stopped being about that game: "which way of driving Unity
works for which job" is not a fact about anyone's project, and keeping it in one meant it
could only ever be applied to one. Collaborators pulling that repo for gameplay work got
trial reports and upstream bug drafts they had no use for.

History was preserved through the split, so `git log` on any file still reaches back to
where the finding was first written down.

## Layout

| Path | What it is |
|---|---|
| `UNITY-TOOLING-NOTES.md` | **The record.** Observations, traps, version-specific behaviour. Starts with `Patterns` — five recurring shapes — which is the part worth reading first |
| `docs/unity-cli.md`, `docs/unity-mcp.md` | Setup, and how to verify each layer really came up |
| `docs/tooling-scorecard.md` | Comparative verdicts: which arm to use for which job |
| `docs/findings-inbox.md` | Raw, unverified, append-only. A to-check list, not the record |
| `docs/trials/` | Per-arm trial reports, written blind by the agent that ran each arm |
| `docs/tooling-experiment.md` | The method, and the evidence tiers findings are graded against |
| `tools/agent/` | The hook, the transcript miner, the one-line capture tool |
| `tools/git/` | Portable UnityYAMLMerge setup |

## Wiring it into a Unity project

The record is not checked out inside your project. Point your project's
`.claude/settings.json` at this repo by absolute path:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|PowerShell|mcp__unity-editor-mcp__.*|mcp__UnityMCP__.*|mcp__unityMCP__.*",
        "hooks": [
          {
            "type": "command",
            "command": "python \"C:/Users/you/Projects/mcp-cocktail/tools/agent/unity-trap-check.py\"",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

The hook fires on the tool call that would spring a known trap and injects that one finding,
with an absolute link back into the record. It fails silent: a hook that errors must never
break the call it was annotating. `--selftest` covers every rule and every misfire that has
been observed in production.

Set `MCP_COCKTAIL_DIR` if you keep this repo somewhere the scripts can't infer from their
own location.

## Contributing a finding

Mid-task, one line, no context switch:

```bash
python /path/to/mcp-cocktail/tools/agent/note.py "eval rejects top-level using directives, CS1001"
```

That lands in `docs/findings-inbox.md`. Promoting it into `UNITY-TOOLING-NOTES.md` is a
separate, deliberate act — version-stamp it, say what was observed versus inferred, and give
it one home. An inbox that auto-promotes is just a second record that drifts from the first.

The capture tool resolves the inbox from its own location, so it writes here no matter which
project you are standing in when you run it.

## Mining sessions

```bash
python tools/agent/session-mine.py sweep            # rank sessions by Unity tooling used
python tools/agent/session-mine.py stats <uuid>     # turns, tools, arm mix
python tools/agent/session-mine.py grep <pat> <uuid>
```

`sweep` ranks mechanically and flags two classes it will not let you mistake for evidence:
`SETUP` (standing the tooling up — a phase each machine passes through once) and `self-ref`
(the session is about this record, so any retrieval measurement taken there is circular).

Sample long, multi-goal, drifting sessions. Humans remember the interesting ones, which is
the opposite of where the failure mode lives.

## The thing this is trying to fix

The measured failure is not that the record is wrong. It is that it gets read after the cost
is paid. A session-start pointer does not fix it — that is the thing that already works on
short scoped tasks and fails on long ones. So the trigger has to be the tool call itself.

Whether that works is measured, not assumed, and the system is required to be able to report
itself failing. See `docs/trials/M-001-RESULT.md` for the first measured session, which
scored the hook as inert.
