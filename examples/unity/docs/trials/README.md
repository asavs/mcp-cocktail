# Trial reports

One directory per trial, one report per arm, each **written by the agent that
ran that arm** — in its own words, before anyone compares anything.

```
docs/trials/T-001/arm-b.md      the agent that used the official MCP
docs/trials/T-001/arm-c.md      the agent that used CoplayDev
```

The verdict does not live here. It goes in
[tooling-scorecard.md](../tooling-scorecard.md), written by the synthesising
agent, and links back to these. Verdicts are for deciding which arm to use;
these are the evidence the verdict was drawn from.

## Why keep them

The scorecard entry is a conclusion written after the fact by whoever ran the
comparison. That is the right format for a verdict and the wrong one for
evidence — a step count nobody can recount, a "friction" column that is one
person's summary of their own experience, and no way to tell a tool that
misbehaved from an agent that misused it.

These reports fix that by being written **during** the work by an agent that
does not know a comparison is happening. Over time they accumulate into
something the scorecard cannot be: a record of what these tools are actually
like to use, including the parts that did not make the verdict.

Keep the ones that found nothing. A trial where the arm behaved perfectly is
evidence about the arm.

## What a report contains

The agent running an arm is asked for:

- **Outcome** — completed / partial / blocked, against criteria it was given
  before starting.
- **Every call it made**, in order, with arguments, and what came back.
- **What it verified, and how** — separating *the tool reported success* from
  *the resulting state was read back and confirmed*. These are not the same
  claim and the difference is usually the finding.
- **Friction** — anything that cost time, surprised it, or that the docs got
  wrong.
- **Expressiveness gaps** — what it could not say with this arm at all.
- **Confidence** — where it is unsure whether a thing is a tool problem or its
  own mistake. This is more useful than a confident guess.

## Reading them later

Written blind, so a report may confidently describe something the other arm
did better, or misattribute a fumble. That is the point — it is a record of the
experience, not an adjudication. Cross-check against the sibling report and the
scorecard entry before treating any single claim as settled.

Every report is stamped with the tool versions it ran against. An unversioned
result rots into a lie.
