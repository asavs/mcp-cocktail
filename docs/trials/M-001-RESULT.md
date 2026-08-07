# M-001 — result

Answers the questions fixed in [M-001-PREREGISTERED.md](M-001-PREREGISTERED.md). Every
question below is the one asked before the session ran. Where a question turned out to be
the wrong question it is left standing and marked, per the pre-registration's own rule.

**Sample:** session `48264c88-d10b-49d2-8741-0f9a1f8c8843`, cwd
`C:\Users\asas\UnityProjects\third-person-multiplayer-gabe`, 2026-08-06T23:09:19Z to
2026-08-07T01:27Z, resumed briefly at 2026-08-07T17:19Z and killed without further work.
11 user turns, 267 tool calls, 73 Unity calls. Unflagged by the sweep.

**Task:** build a melee combat system. Ordinary development work. The session was not told
it was being measured, and never learned. Outcome: abandoned by the user — the melee did
not look good and instructions were not followed. Branch `feat/melee-cancel-windows`.

## Conditions

| Condition | Held? |
|---|---|
| PR#30 merged, corrected record present | Yes — merged 23:14:55Z, present in checkout |
| New session started after the merge | **No** — session started 23:09:19Z, 5m40s *before* the merge |
| No mention of the record, the loop, or measurement in the prompt | Yes |

The second condition did not hold, and the sample is valid anyway. The pre-registration
required a post-merge session because it believed hooks could not arm mid-session. That
belief is false — see Q1 — so the condition it justified was unnecessary. A sample is not
void for failing a condition that was protecting against something that does not happen.

## Q1 — did the hook fire at all?

**Eight injections.** The mechanism is live, not wired-and-inert.

| # | Time (Z) | Tool | Rule fired |
|---|---|---|---|
| 1 | 23:24:09 | Bash | P1 — manifest change while Unity runs |
| 2 | 23:24:27 | Bash | P1 — manifest change while Unity runs |
| 3 | 23:29:59 | `mcp__UnityMCP__refresh_unity` | generic — read the Patterns section |
| 4 | 23:31:05 | Bash | `unity` CLI general — do not gate on exit codes |
| 5 | 23:47:41 | Bash | P1 — manifest change while Unity runs |
| 6 | 23:54:21 | `mcp__unity-editor-mcp__eval` | `eval` bypasses every `confirm=true` |
| 7 | 00:37:23 | Bash | `unity` CLI general — do not gate on exit codes |
| 8 | 01:01:46 | `mcp__unity-editor-mcp__eval` | `eval` bypasses every `confirm=true` |

**The hook armed mid-session.** The session began at 23:09:19Z. Its own
`git fetch origin main:main` ran at 23:23:26Z, and `.claude/settings.json` in that checkout
was written at 23:11Z — after session start either way. The first injection landed at
23:24:09Z, 43 seconds after the fetch and roughly fifteen minutes into a session that
predates the arming.

This contradicts P1 instance 6, which was carried as
`[source-confirmed, behaviour untested]`. The untested half is now tested and it is wrong.
The merge commit for PR#30 states in its own message that the hook "arms on the next
session, not this one." It armed on that one. Corrected at the source; see
[P1](../../UNITY-TOOLING-NOTES.md#p1--reads-once-at-startup).

Residual uncertainty: `.claude/settings.json`'s contents at 23:09:19Z cannot be
reconstructed from mtime alone. What is certain is that the file changed after session
start and the hook fired afterwards in the same session. This is the second independent
observation of the contradiction — the first is in the findings inbox, dated 2026-08-06 17:33.

## Q2 — did any injection change what happened next?

**Once, decisively. Seven times, no.**

Injection 3 at 23:29:59Z carried the generic pointer at the Patterns section. At 23:30:07Z
— eight seconds later — the session ran `sed -n '1,90p' UNITY-TOOLING-NOTES.md`. That is
the only record consult in 267 tool calls, and the hook caused it. RETRIEVE fired and was
obeyed.

The other seven did not change the following call. Five of them could not have, because
they did not describe the call they fired on:

- Injections 1, 2 and 5 fired the manifest rule on `git diff Packages/manifest.json`,
  `git ls-tree`, and a `grep` of the manifest. All three are reads. The rule is about
  *changing* the manifest while Unity runs.
- Injection 4 fired the `unity` CLI rule on `grep -n "unity open\|..." docs/unity-cli.md` —
  grepping documentation *about* the CLI, not invoking it.
- Injection 7 fired the same rule on a real CLI call, which was already wrapped in
  `timeout 60` and piped to `grep`. The mitigation was applied before the advice arrived.

The hook matches on command text, not on command effect. One injection in eight described
what its call was actually doing.

## Q3 — documented traps hit anyway

**Two.**

1. **Pipeline drop-out.** `editor_status` timed out at 60000ms; `recompile` returned
   `No Pipeline instance found for project`; `mcpforunity://instances` returned
   `Unable to connect`. Documented under
   [Pipeline can drop out mid-session](../../UNITY-TOOLING-NOTES.md#pipeline-can-drop-out-of-a-live-editor-session).
2. **P4 — a green light proves only its own layer.** `unity cmd run_tests` reported
   **47 passed, 0 failed**, three separate times, the last at 01:27:06Z. The delivered
   feature threw *"parameter doesn't exist"* on pressing 4 in play mode. EditMode tests
   proved the code compiled and its own assertions held; they proved nothing about whether
   the Animator parameter existed.

Trap 2 is the finding of this session. It was hit **after** the session read the Patterns
section, which is where P4 is written.

## Q4 — novel traps paid for

**Five.** None are in the record.

1. `eval` rejects a `timeout` outside 1–30000ms with `Bad Request` / *"Timeout must be
   between 1ms and 30000ms"*. The bound is undocumented.
2. `eval` rejects top-level `using` directives — `CS1001: Identifier expected` at line 1,
   column 24. Fully-qualified names work.
3. The official `UnityMCP` server returned `Unable to connect` for `import_model`,
   `generate_model` and `instances` across three attempts while `unity-editor-mcp` was
   healthy in the same minutes. Two servers, one Editor, independent liveness.
4. `Object.GetInstanceID()` is obsolete on this version — `CS0619`, use `GetEntityId`.
5. A pre-existing `CS0104` ambiguous-reference error in the Claudesona package
   (`UnityEditor.PackageManager.PackageInfo` vs `UnityEditor.PackageInfo`) sat in
   `Editor.log` for the whole session and surfaced in every log grep, unrelated to melee.
   Cost: repeated re-reads of an error that was never the one being looked for.

## Q5 — which arms did the work use?

`A-cli=8  B-mcp=60  C-mcp=5`. Arm B by 7.5 to 1 over arm A.

The record is CLI-heavy. This is the **second** independent sample saying it is aimed at
the wrong surface; the pre-registration noted the 19-hour session had already said so and
that nothing had acted on it. Still nothing has.

## Q6 — turns-to-first-consult

**Turn 1**, at 23:30:07Z — roughly nine minutes after the first user message (23:21:34Z),
at tool call ~178 of 267. Caused by injection 3, not self-initiated.

## Primary measurement

**cost-paid-before-consult: 0.** Reported with its required companion:
**novel traps paid for: 5.**

Zero is not a success here. The consult happened nine minutes in, before most of the
session's Unity work, so there was little opportunity to pay documented cost first. The
pair of numbers says what the pre-registration predicted it would: the record is not being
hit early and missed — it is being hit early and is *narrow*. Five novel against two
documented.

## Against the pre-registered thresholds

- **Hook succeeded** — fired on a documented trap and the trap was avoided: **no**.
- **Hook is inert** — fired and the trap was hit anyway: **yes, for P4.** The session read
  the Patterns section at 23:30 and shipped the P4 failure ninety minutes later.
- **Hook failed** — did not fire on a call the rules cover: not observed.
- **Record is too narrow** — novel exceeds documented: **yes, 5 > 2.** As expected.

The thresholds have no category for what actually dominated: **fired on a call the rule
does not describe**, five times of eight. The question was not wrong, but it was
incomplete, and it is left standing with the category added rather than rewritten. See the
amendment in the pre-registration.

## What changed because of this

Measurement that does not act is just a nicer-looking null. Three changes, all traceable to
a number above:

1. **P1 instance 6 withdrawn** in [UNITY-TOOLING-NOTES.md](../../UNITY-TOOLING-NOTES.md#p1--reads-once-at-startup),
   with a note that `[source-confirmed]` is not a verification tier and an unobserved
   instance must not count toward the three that earn a pattern. From Q1.
2. **The misfire class is largely fixed** in `tools/agent/unity-trap-check.py`. Two causes,
   both measured: the matcher was reading `new_string`/`content`, so writing *about* a trap
   fired it; and there was no read/write distinction, so `git diff Packages/manifest.json`
   counted as changing the manifest. Written content is no longer matched, and a shell
   command whose every segment is an inspection fires nothing. All ten misfires observed
   during M-001 and during this writeup are now regression cases in `--selftest`. From Q2.
3. **A fifth threshold** — *misfired* — added to the pre-registration for future sessions,
   so this class cannot vanish into the gap between "succeeded" and "inert". From Q2.

The fix is partial and should not be reported as complete. A Bash command that carries a
path as *data* — an `echo` of JSON, a heredoc, a `python -c` — is not read-only and still
fires. Matching command text remains a proxy for matching command effect. What has been
removed is the large, mechanical part of the class, not the principle behind it.

Also changed, and worth flagging as the kind of thing that caused the original problem: the
selftest used to re-implement the matching loop instead of calling it. 703bf53 had already
fixed a rule that was dead in production while that duplicated loop reported it passing.
It now calls `matching_rules()`, the same function the hook uses.

Not acted on: **Q5**. Two independent samples now say the record is aimed at arm A while
the work happens on arm B, 7.5 to 1. That is a question about what the record is *for*, not
a bug to patch, and it should not be resolved by an agent tidying up after a trial.

## What this does not establish

One session. The loop requires the primary metric to fall across two before adoption is
claimed. Nothing here is a trend.

The session's headline failure was not a tooling failure. The user's instructions —
put melee on slot 4, you are already authenticated — were given and not followed, twice
each. No rule in this record addresses that, and none should; it is not a fact about Unity.
Attributing the abandoned outcome to the tooling record would be the error this trial was
designed to avoid.
