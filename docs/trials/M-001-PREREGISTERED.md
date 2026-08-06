# M-001 — first measured development session (pre-registered)

**Written before the session runs.** Every question and threshold below is fixed in advance,
because the failure mode this record keeps hitting is an account assembled around evidence
already in hand. Deciding what counts as success *after* seeing the transcript is how a null
result gets narrated into a win.

If a question below turns out to be the wrong question, say so in the writeup and leave it
standing. Do not quietly replace it with one the data answers better.

## The session

Ordinary development work: the melee combat system. Not a trial, not an experiment, and **the
session must not be told it is being measured.** A session that knows it is under observation
consults the record and scores well while telling us nothing — the exact artifact the Metrics
section of the loop prompt warns about.

Conditions that must hold, or the sample is void and should be discarded rather than salvaged:

- PR#30 merged, so the corrected record is present in the working checkout.
- A **new** session, started after the merge — the `PreToolUse` hook is snapshotted at session
  start and does not arm retroactively.
- No mention of the tooling record, this file, the loop, or any measurement in the prompt.

## Primary measurement

**cost-paid-before-consult** — how many *documented* traps were hit before the record was
opened. Prior reading, from the only genuine dev sample in the corpus: **0, with 13 novel
traps paid for.** That zero is the floor-at-zero failure, not a success.

**Report it alongside novel traps paid for, always.** A low primary with a high novel count
means the record is narrow, not that retrieval is healthy, and it is the only pair of numbers
that separates those.

## Questions, fixed in advance

1. **Did the hook fire at all?** Count of injections. Zero is a real and important outcome — it
   would mean the mechanism is wired and inert, which is worse than unwired because it looks
   armed.
2. **Did any injection change what happened next?** For each fire: did the following tool call
   differ from what the session was about to do? An injection that fires and is ignored is a
   different failure from one that never fires.
3. **How many documented traps were hit anyway?** Cross-reference against the trap list. These
   are retrieval failures.
4. **How many novel traps were paid for?** Anything that cost time and is not in the record.
   This is the coverage number and is expected to be the larger one.
5. **Which arms did the work use?** `session-mine.py stats`. The record is CLI-heavy; if a real
   authoring session uses arm B almost exclusively, the record is aimed at the wrong surface —
   which is what the 19-hour session already suggested and nothing has acted on.
6. **Turns-to-first-consult.** If the record was never opened, record `never` rather than a
   large number.

## Thresholds, fixed in advance

- The hook **succeeded** if it fired on a documented trap and the session avoided that trap.
- The hook **is inert** if it fired and the trap was hit anyway.
- The hook **failed** if it did not fire on a call the rules cover.
- The **record is too narrow** — regardless of the hook — if novel traps exceed documented
  traps hit. Expected, on prior evidence.

## What must not happen in the writeup

- Do not reclassify a novel trap as documented because something similar is in the record.
  Similar is not documented; the test is whether a reader could have found it before paying.
- Do not report the primary metric without the novel-trap companion.
- Do not treat one session as a trend. The loop requires the primary metric to fall across
  **two** sessions before adoption is claimed, and explicitly requires the system to be able
  to report itself failing.
- If the hook fired zero times, that is the headline. Do not lead with anything else.

## Analysis procedure

```
PYTHONIOENCODING=utf-8 python tools/agent/session-mine.py sweep
PYTHONIOENCODING=utf-8 python tools/agent/session-mine.py stats <uuid>
PYTHONIOENCODING=utf-8 python tools/agent/session-mine.py grep "unity-trap-check|TRAP|<trap terms>" <uuid>
```

Confirm the session is unflagged by the sweep before analysing it. A `SETUP` or `self-ref`
flag means it is not the sample this measures, and no amount of care in the analysis fixes a
contaminated sample.
