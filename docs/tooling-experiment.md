# The three-way tooling experiment

We have three ways to make Unity do things, and no principled basis yet for
choosing between them. This is how we build one.

| Arm | What it is | Doc |
|---|---|---|
| **A — CLI** | `unity` shell commands | [unity-cli.md](unity-cli.md) |
| **B — MCP official** | `mcp__unity-editor-mcp__*` (Unity Pipeline) | [unity-mcp.md](unity-mcp.md#unity-official) |
| **C — MCP CoplayDev** | `mcp__unityMCP__*` (MCP for Unity) | [unity-mcp.md](unity-mcp.md#coplaydev-mcp-for-unity) |

**The method:** when you take on a substantial task, run it three times in
parallel — one subagent per arm, each blind to the others — then compare. The
comparison is the point; the task getting done is a by-product.

Results go in [tooling-scorecard.md](tooling-scorecard.md). Qualitative
surprises go in [../UNITY-TOOLING-NOTES.md](../UNITY-TOOLING-NOTES.md).

---

## Before you run a trial

### 1. Is it worth it?

Three arms cost roughly three times the tokens and, for mutating tasks, three
times the wall-clock. Run a trial when:

- the task is **substantial enough to differentiate** the arms (a one-line edit
  tells you nothing), and
- its category is **thin or contested** in the scorecard matrix, and
- nobody is **waiting on the result**.

Otherwise just use the current best-known arm from the matrix and get on with
it. A protocol nobody follows because it's too heavy is worse than no protocol.

### 2. Is it mutating?

**This determines whether you can parallelise, and it is the most important
call you make.**

All three arms drive the **same running Editor** and the **same working tree**.
Three agents changing the scene at once will interleave, stomp each other's
state, and produce a comparison that measures nothing.

| Task type | Examples | How to run |
|---|---|---|
| **Read-only** | inspect hierarchy, read settings, list assets, read console, find references | **Parallel.** 3 subagents at once. Safe — nothing to race. |
| **Mutating** | create/modify GameObjects, edit scripts, change settings, add packages, builds | **Serial.** One arm at a time, reset between. |

If you're unsure, treat it as mutating.

### 3. Can all three arms even do it?

Some tasks are impossible for one arm. **That is a result, not a problem** —
record it as `N/A — cannot express` with a one-line reason and run the other
two. Do not contort a task to make it three-way, and do not silently drop an
arm.

Known asymmetries: installing editors and headless/CI work are CLI-only (the
MCPs need a live Editor); live scene-graph inspection is MCP-only.

---

## Running a trial

### Define acceptance criteria first

Write down what "done" means **before** any arm runs. Post-hoc judging is how
you accidentally reward whichever arm you already preferred. Something like:

> A `Cube` named `SpawnMarker` exists at `(0, 2, 0)` in `[BB] Core.unity`,
> tagged `Respawn`, and the scene compiles with no new console errors.

### Blind the arms

Each subagent gets: the task, its acceptance criteria, **its own arm only**,
and a pointer to that arm's doc. It must **not** be told what the other arms
are doing or that a comparison is happening — that invites convergence and
performance for the grader.

Prompt skeleton:

```
Task: <task>
Done when: <acceptance criteria>

Use ONLY <arm>. Do not use <the other two>.
Reference: docs/<arm doc>

Report back:
- outcome: completed | partial | blocked
- the sequence of calls/commands you actually used
- anything that cost you time, surprised you, or that the docs got wrong
- anything you could not express with this approach
```

### Read-only tasks — parallel

Spawn all three at once. Nothing to coordinate.

### Mutating tasks — serial, with a reset

Between arms, restore the baseline. **Both** halves matter — git state *and*
Editor state:

```bash
git status --porcelain          # confirm clean before starting
# ... run arm ...
git stash -u && git stash drop  # discard the arm's work
```

Then in the Editor: reopen the target scene **without saving**, exit play mode
if an arm left it running, and confirm `recompile_status` is idle before the
next arm starts. An arm that inherits the previous arm's half-applied state
produces a meaningless reading.

If you want the *work* kept rather than discarded, run the winning arm's
approach again afterwards on a branch — don't try to preserve one arm's output
while resetting for the next.

### Synthesise

The parent agent — not the subagents — compares results and writes the
scorecard entry. Subagents report; they don't grade themselves.

---

## What to actually measure

Wall-clock is nearly useless here (CLI latency alone is 60s+ and swamps
everything). Measure what predicts future pain:

- **Outcome** — completed / partial / blocked, against the stated criteria.
- **Steps** — how many calls or commands it took. Fewer is usually better, but
  see the next point.
- **Recoverable vs terminal friction** — did the arm fail in a way that told
  you how to fix it, or did it just produce a wrong answer? This is the single
  most valuable column. This CLI has repeatedly returned *confident wrong
  answers* rather than errors ([detail](unity-cli.md#scripting-the-cli)); an
  arm that fails loudly beats one that fails quietly, even if it fails more
  often.
- **Verifiability** — could the arm confirm its own work, or did you need
  another arm to check it?
- **Expressiveness gaps** — what the arm simply couldn't say.

Don't report a winner on step count alone. An arm that took twice as many calls
but told you exactly what went wrong is the better tool.

---

## Contributing results

1. Append a trial entry to [tooling-scorecard.md](tooling-scorecard.md) using
   the template there. Don't rewrite earlier entries.
2. Update the **capability matrix** at the top of that file if your trial
   changes the picture — and cite the trial ID.
3. Put quirks, traps and version-specific behaviour in
   [../UNITY-TOOLING-NOTES.md](../UNITY-TOOLING-NOTES.md) instead. The scorecard
   is for comparisons; the notes are for observations.
4. **Record inconclusive and failed trials.** A trial where all three arms did
   fine is real evidence that the category doesn't discriminate — which saves
   the next person from running it. Deleting boring results is how you end up
   with a file that only contains dramatic ones.

Stamp every entry with the versions you ran against. These tools are moving
fast; an unversioned result rots into a lie.
