# Tooling scorecard

Which arm to reach for, and the trials that justify it.

Protocol: [tooling-experiment.md](tooling-experiment.md).
Recurring failure shapes that cut across all arms:
[Patterns](../UNITY-TOOLING-NOTES.md#patterns).

> This file said "the three arms" until 2026-08-05. There are at least twelve, and two of
> the three were not independent. The table below is the current option set; the
> [watch-list](#watch-list) is the rest.

| Arm | What it is | Status |
|---|---|---|
| **A** | `unity` CLI | in use |
| **B** | MCP official — `com.unity.pipeline`, `mcp__unity-editor-mcp__*` | in use |
| **B2** | `com.unity.ai.assistant`'s own relay MCP — a *different* first-party server | ⚠️ do not install on 6.5 |
| **C** | MCP CoplayDev — `com.coplaydev.unity-mcp`, `mcp__unityMCP__*` (but see below) | in use |
| **D** | [IvanMurzak/Unity-MCP](https://github.com/IvanMurzak/Unity-MCP) — C#/.NET, npm CLI, Apache-2.0 | untested, credible |
| — | eight further credible entrants | untested, see [watch-list](#watch-list) |

**⚠️ A and B are one stack, not two.** `unity mcp` is an MCP front-end over the same
`com.unity.pipeline` local HTTP API (`:7800`) that `unity list` and `unity command` use —
confirmed from the CLI's own help text. Treating them as independent arms overstates
redundancy: **if Pipeline breaks, A and B fail together.** Rows below justified as
"structural" on the assumption they are separate need re-auditing.

**⚠️ B2 exists and is a landmine on Unity 6.5.** `com.unity.ai.assistant` ships a relay MCP
(named pipes) distinct from Pipeline, and Unity documents a Claude Code config for it. On 6.5
it livelocks the AssetDatabase so the Editor never loads and *every* bridge appears broken —
see [UNITY-TOOLING-NOTES.md](../UNITY-TOOLING-NOTES.md#log) and
[CoplayDev#1219](https://github.com/CoplayDev/unity-mcp/issues/1219).

**Arm C's governance has changed twice.** `justinpbarnett/unity-mcp` → transferred to
`CoplayDev` (2025-08) → **Ramen acquired Coplay (2026-03, GDC)**, the deal explicitly
including this repo; it is now marketed alongside Aura. Licence has been MIT throughout (the
`LICENSE` file has exactly two commits in its history) and no fork ever diverged meaningfully
— 1,392 forks enumerated, 374 of the 428 pushed within three months are pure upstream syncs,
and the whole network's star maximum is 17. So arm C is simply arm C; the note here is that
its steward now sells a competing product, which is a tracking concern, not a code one.

**Naming trap:** the `unity-editor-mcp` registration is arm B (Unity's CLI-hosted server). It
is unrelated to the dead GitHub repo `akiojin/unity-editor-mcp`.

The tool prefix is derived from **the client's own config key**, so C's
namespace differs per client and neither spelling is canonical: Codex's
`config.toml` declares `[mcp_servers.unityMCP]` and Codex sees
`mcp__unityMCP__*`; `~/.claude.json` declares `"UnityMCP"` and Claude Code sees
`mcp__UnityMCP__*`. Searching for the other client's casing returns nothing,
which reads as "the tools aren't loaded". Check your own config before
concluding that.

---

## Capability matrix

The working answer to "which arm should I use". Update it when a trial changes
the picture, and cite the trial.

| Use case | Best | Avoid | Confidence | Evidence |
|---|---|---|---|---|
| Install / uninstall editors and modules | **A** | B, C — impossible | High | Structural: MCPs need a live Editor |
| Open / close projects, license, auth | **A** | B, C — impossible | High | Structural |
| Headless / CI / no Editor running | **A** | B, C — impossible | High | Structural |
| Live scene-graph inspection | **B** or **C** | A — impossible | High | Structural: CLI has no scene access |
| Reading Editor console / compile errors | **B** | — | Medium | T-000; `get_console_logs` returned structured data immediately |
| Invoking Editor menu items | **B** | — | Medium | T-000; `menu` executed and listed all 873 items |
| Editor lifecycle (quit, play mode) | **B** | — | Low | T-000; `File/Exit` worked but errored on response as the server died |
| Scripted / repeatable setup | **A** | — | Medium | T-000; every CLI step was reproducible, GUI steps were not |
| GameObject authoring | **B** or **C** | — | Medium | T-001; both correct, no winner — see the failure modes |
| Prefab authoring | ? | — | None | **Untested** |
| Script creation + attach + recompile | ? | — | None | **Untested** |
| Builds and test runs | ? | — | None | **Untested** — A and B both offer it |
| Asset import / settings changes | ? | — | None | **Untested** |
| Multi-client environments | **C** | — | Medium | 22 configurators vs ~16; structural |

Most rows are empty on purpose. Six of the filled ones are **structural** —
true by architecture, not worth a trial. The interesting rows are the `?`s.

### Standing observations

Short version, with the detail living elsewhere — this file is for verdicts,
[UNITY-TOOLING-NOTES.md](../UNITY-TOOLING-NOTES.md) is for observations.

- **A fails quietly** — returns confident wrong answers rather than errors.
  [Detail](unity-cli.md#scripting-the-cli).
- **B's mutating calls echo the resulting state; C's don't.** Confirmation is
  free on B and a deliberate extra read on C, whose `set_property` returns only
  an instance id. Read state back on C. T-001.
- **`[not reproduced on Pipeline 0.4.0-exp.1]`** T-001 recorded that B repeats one
  `instanceId` across distinct objects. A re-test returned four distinct ids for four
  distinct GameObjects. Three *components on one GameObject* did share an id while their
  `globalId`s differed, which is a different and plausibly correct behaviour. Superseded,
  not deleted — the T-001 entry below is left as written. `hierarchyPath` remains the
  handle that is unambiguous by construction, so prefer it regardless.
- **B has the better safety model** (`confirm=true`, `dry_run`, path
  confinement) — and ships `eval`/`eval_file`, which bypass all of it.
  [Detail](unity-mcp.md#security-notes).
- **B's errors are unusually good** — `unity list` names all three
  prerequisites when the Pipeline isn't reachable. Use it as the benchmark.
- **C is GUI-gated** — setup can't be fully scripted, making it the most
  expensive arm to stand up on a fresh machine.
  [Detail](unity-mcp.md#coplaydev-mcp-for-unity).
- **B can be allowlisted read-only, C mostly can't** — 44 of 140 vs 9 of 47,
  because a permission rule can only be as precise as the tool it names.
  [Detail](#tool-surfaces-at-a-glance).
- **C binds loopback, B binds every interface.** CoplayDev listens on
  `127.0.0.1:8080`; Unity's Pipeline listens on `0.0.0.0:7800` while reporting
  its own URL as `127.0.0.1`. On this one dimension C is the better-behaved
  server. [Detail](unity-mcp.md#security-notes).

### Anti-capabilities

Things an arm **cannot** do. As load-bearing for selection as what it can, and easier to
forget because nothing errors — you just find out mid-task.

| Arm | Cannot |
|---|---|
| **B** | `get_scene_hierarchy` has no depth/limit/pagination — 290,642 chars on one real scene, over the client token limit. `find_gameobjects` likewise. |
| **B** | `get_component_properties` returns `<unsupported:Quaternion>` (rotation) and `<unsupported:LayerMask>`. |
| **B** | No terrain introspection — `TerrainData` size/bounds have no read-only route, pushing a read-only question toward `eval`. |
| **C** | `set_property` echoes no state, so a write can vanish silently. |
| **C** | Setup cannot be fully scripted (GUI-gated). Note: `ClientConfigurationService.ConfigureAllDetectedClients()` *is* a public method already called non-interactively, so the capability exists — what is missing is a shipped headless entrypoint. "Impossible" overstates it. |
| **A/B** | Nothing scene-level without a running Editor — and they share one failure domain. |

### Watch-list

Credible, untested. Listed so the option set is honest rather than tidy; a row here is a
complete answer until someone runs a trial. **Unity 6.5 support is unproven for every arm we
use** — only `isuzu-shiranui` cites the 6.5 `EntityId` migration explicitly.

| Project | ★ | Licence | Why it earns a row |
|---|---|---|---|
| [isuzu-shiranui/UnityMCP](https://github.com/isuzu-shiranui/UnityMCP) | 141 | MIT | Only project citing verified Unity **6.5** support incl. the `EntityId` migration |
| [CoderGamester/mcp-unity](https://github.com/CoderGamester/mcp-unity) | 1855 | MIT | Largest independent Unity MCP; 16 months continuous; names Claude Code and Codex |
| [hatayama/unity-cli-loop](https://github.com/hatayama/unity-cli-loop) | 491 | MIT | Most actively developed; CLI-first and deprecating its own MCP; OpenUPM + npm |
| [r1n7aro/Locus](https://github.com/r1n7aro/Locus) | 696 | **GPL-3.0** | Only serious non-MCP, non-CLI architecture — fails independently of everything else |
| [liyingsong99/AIBridge](https://github.com/liyingsong99/AIBridge) | 199 | MIT | Broadest declared range (`2019.4 ~ 6000.x`); adds Player-process debugging |
| [FunplayAI/funplay-unity-mcp](https://github.com/FunplayAI/funplay-unity-mcp) | 209 | MIT | Cheapest standup — `openupm add`, one-click Codex/Claude config |
| [youngwoocho02/unity-cli](https://github.com/youngwoocho02/unity-cli) | 310 | MIT | Single Go binary, no Python/MCP — **but releases stopped 2026-06-11** |
| [cziberpv/unity-bridge](https://github.com/cziberpv/unity-bridge) | 74 | MIT | JSON-file protocol — works for any agent that can write files, no MCP needed |

**Rejected, with reasons** (so this is not re-derived):

- **Asset Store listings generally** — installs are UI-only through Package Manager → My
  Assets; no CLI, REST, or webhook, and `PackageManager.Client` covers only the UPM registry.
  Any Asset-Store-distributed arm structurally fails the headless-setup axis. The one good
  listing (realvirtual MCP Server) is free on GitHub anyway.
- **Aura, Bezi, Ludus AI, Unity Muse** — no headless surface, an MCP *client* rather than a
  server, Unreal-only, and deprecated, respectively.
- **`nuskey8/UnityAgentClient`** (273★) — Agent Client Protocol, inverts control direction.
  Dormant since 2025-11. The *protocol shape* is worth knowing; the repo is not.
- **`AnkleBreaker-Studio/unity-mcp-server`** (362★) — active and broad, but **`NOASSERTION`
  licence** on both repos. Resolve before touching.
- **High-star corpses:** `jackwrichards/UnityMCP` (521★, untouched since 2025-03, no licence),
  `notargs/UnityNaturalMCP` and `nurture-tech/unity-mcp-server` (both **archived**),
  `akiojin/unity-mcp-server` (README opens `[DEPRECATED]`).
- **Roll-your-own** — `-executeMethod` harnesses are superseded by `unity run --command`;
  Roslyn REPLs are redundant since `unity eval` already is one;
  `Unity-Technologies/com.unity.rpc` abandoned 2021.

---

## Tool surfaces at a glance

Captured 2026-07-28. B via `unity list`; C by speaking MCP directly to
`http://127.0.0.1:8080/mcp` (see [unity-mcp.md](unity-mcp.md#verify-and-recover)).

| | B — Unity official | C — CoplayDev |
|---|---|---|
| Server | Pipeline `0.4.0-exp.1` | `mcpforunityserver 10.0.0` |
| Tools | **140** | **47** |
| Granularity | fine-grained — `create_gameobject`, `set_parent`, `set_active` | coarse dispatchers — `manage_gameobject`, `manage_scene` + an `action` argument |
| Arbitrary code | `eval` / `eval_file` | `execute_code` |

Granularity is the real difference, and it cuts both ways. B's 140 tools are
self-documenting: the schema tells you what the call does, and a wrong call
fails at validation. C's 47 are compact — far less context to load — but each
one hides a sub-API you have to learn from its description, and a wrong
`action` fails at runtime.

**Granularity also decides what can be pre-approved.** A permission rule names
a tool, so it can only be as precise as the tool is. B's read/write split falls
on tool boundaries — `get_scene_hierarchy` cannot write, `set_transform` cannot
not-write — so 44 of its 140 are allowlistable as read-only with no judgement
call. C's dispatchers put both sides of that line inside one name:
`manage_scene` covers `get_hierarchy` and `delete`, `manage_asset` covers
reading and deleting. Only 9 of C's 47 could be allowlisted, and one of those,
`read_console`, is a compromise — its `clear` action mutates console state,
which is ephemeral UI rather than project data. The rest are unreachable
without prompting on every call, however harmless the `action`. See
[`.claude/settings.json`](../.claude/settings.json).

This is the first non-structural difference found without running a trial, and
it favours B for unattended agent work specifically.

**Only in C:**

- `unity_reflect` / `unity_docs` — verify Unity APIs against the actual
  assemblies. The server's own instructions say *"LLM training data frequently
  contains incorrect, outdated, or hallucinated Unity APIs"* and tell agents to
  reflect before answering. Nothing in B addresses hallucinated APIs, and for
  agent work this may be C's strongest argument.
- `generate_image` / `generate_model` — AI asset generation.
- `manage_probuilder`, `manage_vfx`, `manage_profiler`, `manage_ui` — B has no
  equivalents.
- `set_active_instance` — explicit routing when several Editors are connected.
  B has no multi-instance concept.
- `batch_execute` — several operations per call, which partly offsets the
  latency of coarse dispatchers.

**Only in B:** `set_authoring_root` path confinement, and `confirm=true` /
`dry_run` guards on destructive tools. C's guards, if any, are inside each
dispatcher and not visible from the tool list. `[unverified]`

C's tools have since been invoked through a normal client (`read_console`
returned structured console data), so the raw-HTTP procedure above is a
diagnostic for when a client won't load them, not the working path.

**Not yet compared:** actual behaviour. Everything above is read off the tool
lists, not from running the same task through both. That's what a T-001
authoring trial is for.

## Trials

Newest first. Template at the bottom.

### T-001 — build the same GameObject hierarchy through each arm

**Date** 2026-07-28 · **Category** authoring · **Mutating** yes ·
**Versions** CLI `1.0.0-beta.3`, Editor `6000.5.5f1`, Pipeline `0.4.0-exp.1`,
MCP for Unity `v10.0.0` (server `3.4.5`)

Run blind and serial, one subagent per arm on the same model, each writing its
own account before any comparison: [arm-b.md](trials/T-001/arm-b.md) ·
[arm-c.md](trials/T-001/arm-c.md).

**Task** Create a root empty `T001-Root`, containing a child empty at local
position `(1, 2, 3)` carrying a `BoxCollider` with `size` `(2, 2, 2)`.
**Done when** The state is read back and confirmed, not assumed. Untitled
scratch scene; deleted afterwards, never saved.

| Arm | Outcome | Steps | Friction | Verifiable? |
|---|---|---|---|---|
| A CLI | N/A | — | No live-scene access — structural | — |
| B MCP official | completed | 12 | `size` rejected; needed a read to discover `m_Size` | Yes — and mutating calls echo the resulting state |
| C MCP CoplayDev | completed | 9 | None on the path taken | Yes, via `mcpforunity://` resources — but `set_property` echoes nothing |

**Both arms produced correct scenes.** Verified independently after each run:
`m_Size [2,2,2]`, `m_LocalPosition [1,2,3]`, correct parenting. This category
does not separate them on outcome, and the step counts are too close — and too
dependent on which path an agent picks — to carry a verdict.

What the trial did separate is **how each one fails**, and they fail in
opposite directions.

**B fails loudly.** Its one stumble was rejecting `size` with
`Component 'BoxCollider' has no serialized property 'size'` — a 400 naming the
exact problem. `size` is the public C# property every Unity doc page shows;
the tool wants the serialized `m_Size`. That cost a failed call and a
discovery read, and it is the good kind of friction: the arm said what was
wrong and the fix was immediate.

**C did not stumble at all here** — but has a path that fails silently, and
it's worse than it first looked. Probed separately, `manage_gameobject
action=create` with `component_properties` returns `"success": true`, adds
the component, and leaves the property at its default. Reproduced twice, then
confirmed against the package source at installed commit `7b7db7b31f4e`:
`ManageGameObject.cs:55-68` accepts and coerces `componentProperties` for
every action, but only `GameObjectModify.cs:227` ever reads it back — the
create path never consults it. `GameObjectCreate.cs:239-258` does implement
per-component properties, but reads them from `{typeName, properties}`
objects nested inside `componentsToAdd`; the Python layer types
`components_to_add` as `list[str] | str | None`, so Pydantic rejects that
shape before it reaches Unity — there's no JSON-string workaround, since the
:55-68 coercion covers `componentProperties` only. Net result: **there is no
reachable way to set a component property at creation time** — one argument
is accepted then silently ignored, the other is implemented but unreachable
from the client. Confirmed working on `action=modify`. The arm-C agent never
hit it because it used `manage_components`, which the dispatcher's own
description tells you to do (*"NOT for component management"*) — that path
happens to sidestep the bug rather than avoid a warned-against shortcut.
Filed upstream: [CoplayDev/unity-mcp#1297](https://github.com/CoplayDev/unity-mcp/issues/1297).
`[reproduced, source-confirmed, reported upstream]`

**Each arm has a handle trap, and they are mirror images.** B returned the
*same* `instanceId` for genuinely different objects — `Main Camera` and
`Directional Light` share one, and both created objects shared another.
`hierarchyPath` is unambiguous and worked throughout, so B's own numeric
handles are the unreliable part of its response. C's `instanceID` values were
distinct and usable as handles for every subsequent call.
`[B's duplicate instanceId: confirmed independently, cause unknown]`

**Verification asymmetry, which is the practically useful finding.** B's
mutating calls echo the resulting state, so confirmation is free. C's
`set_property` returns only `{"instanceID": ...}` — no value — so a C agent
that doesn't deliberately re-read has no signal at all that a write landed.
Both arms *can* self-verify; only one makes it the default.

**Also settled** — `position` on C's `create` is **local** when a `parent` is
given. The arm-C report correctly declined to conclude this, since its root
sat at the origin where local and world coincide. Re-run with the root at
`(10,0,0)`: child at local `(1,2,3)`, world `(11,2,3)`.

**Verdict** — **no winner for authoring.** Both express the task cleanly and
both got it right. Prefer B when you want failures that announce themselves;
prefer C for a slightly leaner call sequence. Either way, read the state back:
B because a wrong property name is a live risk, C because a write can vanish
without complaint.

**Matrix changes** — *GameObject authoring* filled as "B or C", Medium,
citing this trial. Added the verification-asymmetry and instanceId
observations.

**Follow-ups**
- ~~Report C's `component_properties` drop upstream~~ — done, source-confirmed:
  [CoplayDev/unity-mcp#1297](https://github.com/CoplayDev/unity-mcp/issues/1297).
- Does the drop affect other C dispatchers that take properties inline
  (`manage_material`, `manage_scriptable_object`)?
- What causes B's duplicate `instanceId`? Harmless here only because
  `hierarchyPath` exists.
- Prefab authoring and script-create-attach-recompile, still untested.

### T-000 — initial setup of CLI, both MCP servers, and the git merge driver

**Date** 2026-07-28 · **Category** setup · **Mutating** yes ·
**Versions** CLI `1.0.0-beta.3`, Editor `6000.5.5f1`, Pipeline `0.4.0-exp.1`,
MCP for Unity `v10.0.0`

Not a controlled trial — this was the bootstrap, done before the protocol
existed. Recorded because it's the only evidence behind several matrix rows and
because "how hard was each arm to stand up" is itself a finding.

| Arm | Outcome | Friction |
|---|---|---|
| **A** CLI | Completed | Docs give a Windows install command that cannot work; only the beta channel is published; several commands return non-zero on success; commands are cwd-sensitive and invent plausible wrong answers; some `--help` subcommands hang |
| **B** MCP official | Completed | Reports `✓ Connected` while exposing **zero** tools without `com.unity.pipeline`; needs an Editor restart to resolve the package; server binds late. Once up: 140 tools, worked first time |
| **C** MCP CoplayDev | Completed | `uv` must be on the Editor's PATH **at launch** — installing it while Unity runs is unrecoverable without a restart; bundled README describes a UI that no longer exists; setup is GUI-only |

**Notable:** B was used to set up C — `menu` opened CoplayDev's own
configuration window. Cross-arm bootstrapping works.

**Verdict** — A is the only arm that can install anything, so it's not
optional. B was the least painful to reach a working state *given* the CLI
already existed. C cost the most human intervention, entirely because of the
GUI dependency.

**Follow-ups**
- Compare B and C on the same authoring task — the first real trial.
- `unity build` (A) vs `build` (B) on the same target.
- Does C offer anything B doesn't, beyond client breadth?

---

## Trial template

```markdown
### T-NNN — <one-line task>

**Date** YYYY-MM-DD · **Category** <setup|inspection|authoring|build-test|debug>
· **Mutating** yes/no · **Versions** CLI x, Pipeline y, MCP-for-Unity z, Editor w

**Task** <what was asked>
**Done when** <acceptance criteria, written before running>

| Arm | Outcome | Steps | Friction | Verifiable? |
|---|---|---|---|---|
| A CLI | completed/partial/blocked/N-A | | | |
| B MCP official | | | | |
| C MCP CoplayDev | | | | |

**Verdict** <which arm, and why — not step count alone>
**Matrix changes** <rows updated, or "none">
**Follow-ups** <what this raises>
```
