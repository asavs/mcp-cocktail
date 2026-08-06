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
| Live scene-graph inspection | **A**, **B**, or **C** | — | High | Re-verified 2026-08-06: `unity command get_scene_hierarchy` returned the live hierarchy from a shell, exit 0. The former "A — impossible / structural" was **wrong, not stale** |
| Reading Editor console / compile errors | **B** | — | Medium | T-000; `get_console_logs` returned structured data immediately |
| Invoking Editor menu items | **B** | — | Medium | T-000; `menu` executed and listed all 873 items |
| Editor lifecycle (quit, play mode) | **B** | — | Low | T-000; `File/Exit` worked but errored on response as the server died |
| Scripted / repeatable setup | **A** | — | Medium | T-000; every CLI step was reproducible, GUI steps were not |
| GameObject authoring | **C**, then **B** | — | Medium-High | T-005, the first run with all three arms actually executing: **failed calls C 0, B 1, A 3**. C accepts the public `size`; A and B require the serialized `m_Size`. C echoes state on 2 of 4 mutating calls, B 1 of 5, A 0 of 6. Prefer **B** where tools must be allowlisted read-only (44/140 vs 9/47) or where loud, specific errors matter more than call count. A authors correctly *with* a verify-every-write discipline (T-003) |
| Setting a **computed** property (non-trivial setter) | **C** | A, B — they write the backing field, not the property | Medium-High | T-006, 2026-08-06. C resolves the literal name by reflection on the public C# API first, so the **real setter runs**. Decisive case: `Transform.position` on a child of a parent at `(10,5,3)` → world `(50,60,70)`, local `(40,55,67)` = `world − parent`, exactly right. A rejected it outright |
| Setting **private serialized** state (no public setter) | **A** or **B** | C — its fallback supports only some `SerializedPropertyType`s | Medium | T-006. C's tier-2 fallback matches literal serialized names but failed `m_Size` with `Unsupported SerializedPropertyType: Vector3`; A wrote it fine. The serialized layer reaches state the public API does not expose |
| Prefab authoring | ? | — | None | **Untested** |
| Script creation + attach + recompile | ? | — | None | **Untested** |
| Builds and test runs | ? | — | None | **Untested** — A and B both offer it |
| Asset import / settings changes | ? | — | None | **Untested** |
| Multi-client environments | **C** | — | Medium | 22 configurators vs an uncounted B. Re-verified 2026-08-06: still 22 on `v10.1.2`, still no Grok. **Not structural** — a file count is a version fact |
| Physics / geometry queries (raycasts, bounds) | **B** or **C**, via `eval` / `execute_code` | every introspection tool — the capability does not exist | Low | T3, 2026-07-28; serialized fields cannot answer what a cast returns — [Instruments](../UNITY-TOOLING-NOTES.md#read-only-c-probes-returning-a-table) |
| Carrying on when the other MCP is down | **the other MCP** | A — shares B's failure domain | Low | One real instance: 2026-07-28, Pipeline died mid-session and C carried. T-000's "B→C" was B *configuring* C at setup, not failover — the two are not symmetric |

**Coverage: 14 of 18 rows filled.** **Three** are **structural** — true by architecture, not
worth a trial — so eleven rest on evidence, and the four `?`s are the interesting ones.
`[count corrected 2026-08-05: prose said six structural against five in the table. Corrected
again 2026-08-06: the re-audit below demoted two of those five. Two rows added 2026-08-06 from
T-006.]`

**The two new rows are the first split the matrix has made on capability rather than friction.**
Every previous verdict came down to call count, error quality or allowlistability — differences
of ergonomics between arms that could all, eventually, do the job. Property mutation is not like
that: **the arms operate on different layers.** C resolves a name by reflection against the live
component's public API and runs the real setter; A and B expose only `SerializedProperty` and
write the backing field. Each reaches state the other cannot. A computed property written
through the serialized layer is left inconsistent with what it derives from; private serialized
state has no public setter to reflect on at all. Coverage rose here by finding a question the
table had never asked, which is the same way it rose in Phase 2.

**One row was wrong, not stale.** "Live scene-graph inspection — A impossible, CLI has no
scene access" was carried at **High confidence, structural** — the strongest label in the
table — and is false. `unity list` enumerates 141 Pipeline tools from a shell and
`unity command get_scene_hierarchy` returns the live hierarchy. The contradiction was sitting
eight lines above the row it refutes: the A=B note already said `unity command` uses the same
`com.unity.pipeline` HTTP API that B exposes. Nobody ran the command.

Two consequences worth keeping. First, **the premise excluded arm A from T-001** (see that
trial's own arm table), so a three-way comparison was run as two-way and its verdict covers
less than it appears to. Second, **the A=B correction never swept backwards**: rows written
before it (all of 1–9 and multi-client) were never re-checked against it, and the one row that
gets it right was written the same evening it landed. A correction that only applies going
forward is a correction that has not been applied.

**Arm A is two mechanisms under one letter**, which is what let the error hide. `unity build`
/ `unity test` / `unity install` spawn a fresh batch-mode Editor or talk to the Hub, touching
no Pipeline at all — that is why "headless / CI" survives the A=B correction honestly.
`unity list` / `unity command` are a front-end over the *same* Pipeline server as B. The
matrix writes both as "A". Rows justified on one face do not transfer to the other, and until
this table distinguishes them, the same class of error can recur.

**Staleness, re-audited 2026-08-06.** **Four** filled rows — not three — rest partly on arm C
at `v10.0.0`, three releases behind `v10.1.2`: GameObject authoring, physics/geometry queries,
carrying on when the other MCP is down, and **multi-client environments**. The last was
omitted from the previous count because its "structural" label exempted it; a count of files
shipped in one release is a version fact and expires like any other.

**`[T-004, 2026-08-06: all four are still stale, and the installed package is still v10.0.0.]`**
T-004 was run to refresh them and could not: C's plugin is not attached to its server, so no
Editor-bound call executed. Note the version claim is now confirmed rather than assumed — the
Python server self-reports `10.0.0` and `Packages/manifest.json` pins `#v10.0.0`, while the
package's own update check records `10.1.2` as current. **Anything in this file attributed to
arm C describes v10.0.0 behaviour observed on 2026-07-28 and has not been re-measured since.**

**`[T-005, 2026-08-06: one of the four is now refreshed; three are not.]`** Arm C executed for
the first time in five attempts and *GameObject authoring* now rests on measured `10.0.0`
behaviour rather than T-001's. **Physics/geometry queries, carrying on when the other MCP is
down, and multi-client environments are still unrefreshed** — nothing in T-005 exercised them.
The installed package is still `10.0.0`. Note also that **no live arm-C call reports a package
or server version**: three resources were checked and the number had to be read from the
project lockfile. Any future staleness audit of arm C has to go outside the arm to do it.

The earlier observation that "no filled row cites evidence newer than the installed versions"
is tautological — evidence is produced by running what is installed — and must not be read as
reassurance about the remaining rows.

### Standing observations

Short version, with the detail living elsewhere — this file is for verdicts,
[UNITY-TOOLING-NOTES.md](../UNITY-TOOLING-NOTES.md) is for observations.

- **A fails quietly — but not always, and the blanket phrasing was overstated.**
  `[re-verified 2026-08-06]` `unity list` returns exit **6** with a three-item diagnostic
  when no Pipeline is reachable, and `unity editors running --json` correctly reported
  `count: 0` with three `unity.exe mcp` bridge subprocesses alive — it was right to not
  count them as Editors. The failure mode is real but narrower than "A fails quietly"
  suggests; treat it as a hazard to check for, not a property to assume.
  [Detail](unity-cli.md#scripting-the-cli).
  **`[widened by T-004]` That re-audit covered *connection* failure, which is loud. *Argument*
  failure is silent, and the softening does not reach it.** `set_transform --position 1,2,3`
  and `--position 1 --position 2 --position 3` both return exit 0 and `"success": true` and
  change nothing; only `--position '[1,2,3]'` lands. The payloads of the two no-ops and the
  successful write are the same shape, so neither the exit code nor `success` distinguishes
  them. So: A fails loudly when it cannot reach Pipeline, and quietly when Pipeline cannot
  parse an argument. Verify every write.
- **`[corrected by T-003]` B's mutating calls mostly echo *identity*, not state.**
  The earlier form of this said B echoes the resulting state and C does not, so confirmation
  was free on B. T-003 measured it directly and it is not so: `create_gameobject`,
  `set_transform` and `add_component` return `globalId` / `hierarchyPath` / `instanceId` only
  — `set_transform`'s response contains no `position` field at all. `set_component_properties`
  is the one exception and does echo the resulting property map. So read state back on **both**
  arms; B is better than C here by one tool, not by policy.
  **`[reconfirmed by T-004, and extended to A]`** T-004 reproduced B's split exactly — 3 of 4
  identity-only, `set_component_properties` the lone echo. It also measured **A for the first
  time: 0 of 8 mutating calls echo state.** `create_gameobject`, `set_transform`,
  `add_component` and `set_serialized_field` all return the same identity block. So B beats A
  here by exactly one tool, the same margin by which it beats C.
  **`[corrected by T-005 — the "B beats C" half is wrong]`** All three arms were finally
  measured in one run, and the ranking is **C 2 of 4, B 1 of 5, A 0 of 6**. C's
  `manage_gameobject create` returns the object's full serialized state (transform, tag, layer,
  `componentNames`, `parentInstanceID`) on both create calls; B has exactly one echoing mutator
  and A has none. **C is the best arm on this axis, not the worst.** What remains true of C is
  the narrower original claim: `manage_components set_property` echoes only `{"instanceID": …}`,
  so a property write specifically still vanishes without a read-back. Read state back on all
  three arms regardless — no arm echoes on every mutator.
- **`[feedback]` The `instanceId` collision is an engine-level `EntityId` issue, not a
  Pipeline one — and the field is misnamed.** Source-confirmed in
  `com.unity.pipeline@f49636739437`: on Editor 6000.4+ `PipelineUtils.GetObjectId` returns
  `Object.GetEntityId()`, Unity's new ulong-backed `EntityId` that replaces the classic
  instance id. The JSON field name `instanceId` is a holdover from the pre-`EntityId` design,
  so the name promises something the value is not. The package's own code is clean —
  `ObjectResolver.Describe` builds a fresh POCO per call and reads the id off the object in
  scope, with no pooling or shared buffer, and the batch create path is structurally identical
  to N sequential single creates. **The collision is nondeterministic and sits below the
  package.** Decisive evidence is in T-003's own data: arm A received one identical id for
  three separate sequential calls and then two correct distinct ids immediately afterwards, in
  the same session with the same tool and calling convention — which rules out arm,
  batch-vs-single, and GameObject-vs-component as discriminators. **Use `globalId` or
  `hierarchyPath`; never key anything on `instanceId`.**
- **`[superseded 2026-08-06 — this entry's "not reproduced" verdict was wrong]`** T-001
  recorded that B repeats one `instanceId` across distinct objects. A re-test returned four
  distinct ids for four distinct GameObjects and this was marked not reproduced. That re-test
  also saw three *components on one GameObject* share an id while their `globalId`s differed,
  and called it "a different and plausibly correct behaviour" — **the source does not support
  that.** `Describe()` calls `GetObjectId()` independently per component with no aliasing
  logic, so three components sharing an id is the same defect at component granularity, not a
  clean negative. A nondeterministic bug that failed to appear once was read as evidence of
  absence, and the reassuring interpretation was reached for rather than checked. Kept as
  written; see the entry above for the resolved mechanism.
  **`[T-004 settles this empirically]`** The supersession above rested on source-reading; it no
  longer has to. In T-004 arm B, **all four** objects — root GameObject, child GameObject, its
  Transform, its BoxCollider — returned the identical `568105589213729200` against four
  distinct `globalId`s. Arm A saw three of four share one id. The collision is real, reproduces
  at both GameObject and component granularity, and discriminates nothing. **Also new: the
  value exceeds 2^53**, so any client round-tripping it through a double corrupts it — the
  differing trailing digits across arms (`…729300` / `…729200`) are rounding artifacts, not
  data.
  **`[T-005 identifies the mechanism — the collision *is* the rounding, not a defect beneath
  it]`** T-004 spotted that the trailing digits are artifacts but still read the collision
  itself as engine-level. Arm C ran for the first time and settles it. C serialises the same
  `EntityId` values as **quoted strings** and they come back distinct: `"568105589213729364"`
  (a GameObject) and `"568105589213729346"` (its material) — **18 apart**. That magnitude sits
  in `[2^58, 2^59)`, where IEEE-754 double spacing is 2⁶ = **64**, so two ids 18 apart *cannot*
  round-trip through a double as distinct values. A and B emit the field as a **bare unquoted
  JSON number** and duly return one value (`…729400`, `…729500`) for objects the engine
  distinguishes. C's own small session-local `instanceID`s (`-28066`, `-28076`, `-28090`,
  `-28094`) were likewise all distinct. **The engine is not colliding; Pipeline's serializer is
  destroying the distinction**, and quoting the value would fix it. The operational rule is
  unchanged — use `globalId` or `hierarchyPath`, never `instanceId` — but "nondeterministic"
  was the wrong word: the loss is deterministic in the value's magnitude, which is why it
  looked intermittent whenever two ids happened to straddle a 64-boundary.
- **B has the better safety model** (`confirm=true`, `dry_run`, path
  confinement) — and ships `eval`/`eval_file`, which bypass all of it.
  [Detail](unity-mcp.md#security-notes).
- **B's errors are unusually good** — `unity list` names all three
  prerequisites when the Pipeline isn't reachable. Use it as the benchmark.
- **`[not reproduced on v10.0.0 — this claim is wrong]` C is not GUI-gated.** The entry used to
  say setup could not be fully scripted, making C the most expensive arm to stand up. Source
  and a live test say otherwise. Unity-side, C is an HTTP *client*; the listener on
  `127.0.0.1:8080` is a separate `python.exe` spawned via `uvx`. Starting it needs one
  EditorPrefs flag and one public call, both reachable through `eval`:
  `EditorPrefs.SetBool("MCPForUnity.UseHttpTransport", true)` then
  `MCPForUnity.Editor.Services.MCPServiceLocator.Server.StartLocalHttpServer(true)`. The `true`
  is `quiet`, which **deliberately skips the only confirmation dialog in the path**
  (`ServerManagementService.cs:299-312`) — the same flag the auto-start path uses internally.
  Setting `AutoStartOnLoad` plus `UseHttpTransport` starts it on every Editor load with no
  interaction at all (`HttpAutoStartHandler.cs:18-107`). Verified by a bound port owned by a
  `python.exe` distinct from the Editor, then stopped and the pref reset.
- **The real gate on C is the client, not the arm** — and it is
  [P1, reads-once-at-startup](../UNITY-TOOLING-NOTES.md#p1--reads-once-at-startup). An MCP
  server must be registered before a Claude Code session starts, so C cannot be added to a
  session already running, however cheaply its server starts. This is why C has never appeared
  in a trial run from an existing session, and it is scriptable — register, then start a fresh
  session — rather than needing a human.
  **`[incomplete — T-004 cleared this gate and hit a second one]`** T-004 ran from a fresh
  session with C registered; the tools loaded and the server answered. C still could not
  execute a single Editor-bound call. **The Unity-side plugin does not attach to its own
  server**, silently: `active_instance: null`, `all_keys_in_store: []`, `instance_count: 0`,
  last successful `Plugin registered:` dated 2026-07-29. The Editor *starts* the server and
  then never dials in, and with `MCPForUnity.DebugLogs = 0` (the default) it logs nothing
  about the connection it failed to make. So there are **two** gates, and only the first is
  scriptable — this one needs Editor-side action. **A server that answers is not an arm that
  works;** check `mcpforunity://instances` for a non-zero `instance_count` before assuming
  otherwise. `debug_request_context` is the only call that reveals it.
- **B can be allowlisted read-only, C mostly can't** — 44 of 140 vs 9 of 47,
  because a permission rule can only be as precise as the tool it names.
  [Detail](#tool-surfaces-at-a-glance).
- **C binds loopback, B binds every interface.** CoplayDev listens on
  `127.0.0.1:8080`; Unity's Pipeline listens on `0.0.0.0:7800` while reporting
  its own URL as `127.0.0.1`. On this one dimension C is the better-behaved
  server. [Detail](unity-mcp.md#security-notes).
- **Running both has now paid in both directions, which is the case for the
  setup cost.** T-000 recorded B being used to configure C. On 2026-07-28 the
  reverse happened unplanned: Pipeline stopped serving mid-session and C
  carried the rest of the work, including opening the scene B was needed for.
  Neither server can repair the other — the recovery is still an Editor
  restart — but neither outage was session-ending.
  [Detail](../UNITY-TOOLING-NOTES.md#pipeline-can-drop-out-of-a-live-editor-session).
  `[T3]`
- **C's refusals are safe but have no escape hatch.** `manage_scene` declining
  to load over unsaved changes is correct behaviour; having no `discard`
  action means the only route past it is `execute_code`. See the
  [anti-capabilities](#anti-capabilities).

### Anti-capabilities

Things an arm **cannot** do. As load-bearing for selection as what it can, and easier to
forget because nothing errors — you just find out mid-task.

| Arm | Cannot |
|---|---|
| **B** | `get_scene_hierarchy` has no depth/limit/pagination — 290,642 chars on one real scene, over the client token limit. `find_gameobjects` likewise. |
| **B** | `get_component_properties` returns `<unsupported:Quaternion>` (rotation) and `<unsupported:LayerMask>`. |
| **B** | No terrain introspection — `TerrainData` size/bounds have no read-only route, pushing a read-only question toward `eval`. |
| **C** | `set_property` echoes no state, so a write can vanish silently. `[reconfirmed T-005 — `manage_components set_property` returns a bare `{"instanceID": …}`. Note this is now C's *only* non-echoing class: `manage_gameobject create` echoes the full object.]` |
| **C** | Cannot report its own version. No tool or resource among 47/18 carries a package or server version — `custom-tools`, `ListMcpResourcesTool` and `telemetry_status` were all checked. The only route is reading `packages-lock.json` from outside the arm. `[T-005]` |
| **A/B** | Cannot return a usable object handle. `instanceId` is a 59-bit `EntityId` emitted as a bare JSON number, so distinct objects less than 64 apart collapse onto one value in transit. C quotes the same field and it stays distinct. `[T-005]` |
| ~~**C**~~ | ~~Setup cannot be fully scripted (GUI-gated).~~ **Struck 2026-08-06.** `three-way-setup.sh` registers the Editor with arm C's server unattended and T-005 then ran the arm end-to-end, so this is not an anti-capability. The residual truth is narrower and belongs to the standing observations: recovering a plugin that has *dropped* its attachment is Editor-side. |
| **C** | `manage_scene` cannot **discard** an unsaved scene — its actions are `save` / `load` / `create` / `get_*`. `load` refuses over unsaved changes (correct), so a dirty scratch scene blocks all navigation and the only way through is `execute_code`, i.e. the always-ask tier, for what should be routine. `[feedback]` `[T3]` |
| **B** | Nothing outside the Editor can restart Pipeline once its editor assembly has dropped out — its menu items go with it, so `execute_menu_item` has nothing to call. Recovery is an Editor restart, by hand. [Detail](../UNITY-TOOLING-NOTES.md#pipeline-can-drop-out-of-a-live-editor-session). |
| **B/C** | Neither exposes any **physics or geometry query** — no raycast, no collider bounds, no mesh extents. Introspection reads serialized fields, which cannot answer what a cast returns. Pushes a read-only question into `eval` / `execute_code`. |
| **A** | Cannot report whether a write landed. **0 of 8** mutating calls echo state (T-004), and a malformed array argument is **dropped silently** — exit 0, `"success": true`, nothing changed. The success payload is indistinguishable from a real write. Every mutation needs its own read-back. |
| **A** | No per-tool help. `unity command <tool> --help` prints generic usage; the only schema source is the ~115 KB `parameters` array in `unity list --json`, and it does not say which JSON encoding a vector parameter wants — `set_transform --position` needs `[1,2,3]`, `set_serialized_field --value` needs `{"x":..}`. |
| **C** | Cannot tell you it is disconnected. Server-only tools (`debug_request_context`, `manage_tools`) answer normally while every Editor-bound call fails, so the server looks healthy from the client. Each failure blocks ~20s and returns `retry_after_ms: 250` with `hint: "retry"` — backpressure phrasing for a permanent condition. `[T-004]` |
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

### T-005 — the same authoring task, and the first one that was actually three-way

**Date** 2026-08-06 · **Category** authoring · **Mutating** yes ·
**Versions** CLI `1.0.0-beta.3` (`unity --version`), Editor `6000.5.5f1`, Pipeline
`0.4.0-exp.1`, MCP for Unity package `10.0.0`

Fourth run of the T-001 task — root empty, child empty at local `(1, 2, 3)`, `BoxCollider`
with size `(2, 2, 2)` — named `T005-Root-<arm>` / `T005-Child-<arm>`. Blind and serial, one
subagent per arm, each writing its own account before any comparison:
[arm-a.md](trials/T-005/arm-a.md) · [arm-b.md](trials/T-005/arm-b.md) ·
[arm-c.md](trials/T-005/arm-c.md). Objects deleted afterwards and confirmed gone by read-back
on all six names; scene never saved.

| Arm | Outcome | Steps | Friction | Verifiable? |
|---|---|---|---|---|
| A CLI | completed | 18 invocations (14 against the Editor, of which 3 were failed mutations) | 2 rejected encodings for `m_Size`, 1 silent no-op on `--position 1,2,3`, 1 mangled multi-flag | Only by separate read — **0 of 6** successful mutating calls echoed state |
| B MCP official | completed | 11 Editor calls (1 failed) | one loud 400 on `size` | Mostly by separate read — **1 of 5** mutating calls echoed state |
| C MCP CoplayDev | completed | 14 Editor calls, of which **7 were the task** and 7 were spent hunting version numbers | **none — every call succeeded first try** | **2 of 4** mutating calls echoed state |

**Arm C executed.** Four consecutive prior attempts did not, so every arm-C claim in this file
had been carrying `v10.0.0` evidence from 2026-07-28 with no re-measurement. The three open
questions T-004 could not ask are answered below, and two of them contradict the record.

**The gate held only because it was tested twice.** `three-way-setup.sh` now registers arm C
and asserts `instance_count=1`, and it reported all five lines green. That is the check T-004's
follow-up asked for, and it is necessary but **not sufficient** — it proves a plugin registered
with the server, not that a message survives the round trip. A single real `read_console` call
was made before any arm was spawned and returned live Editor console text. **Run the message,
not the status field.** Every wrong diagnosis in this trial series has come from trusting a
signal instead of a payload.

**C accepts the public API name `size`. A and B require the serialized `m_Size`.** This is the
headline, and it reverses three trials' worth of "`m_Size` over `size` reconfirmed."

- **C**: `manage_components action=set_property property="size" value=[2,2,2]` succeeded on the
  first attempt, read-back confirming `size: {x:2.0, y:2.0, z:2.0}`. `m_Size` was never needed.
- **B**: `set_component_properties {"size":[2,2,2]}` → 400,
  `Component 'BoxCollider' has no serialized property 'size'.` `m_Size` worked immediately after.
- **A**: `set_serialized_field --field size` → exit 6,
  `Field 'size' was not found on 'BoxCollider'. Use a SerializedProperty path (e.g. 'speed', 'settings.speed', 'items.Array.data[0]').`

A and B fail identically because they are one stack. C almost certainly translates the public
property name to the serialized one before reaching Unity's `SerializedProperty` API, where
Pipeline passes it through raw. **This is a real ergonomic difference, not noise:** it is the
difference between the name in every Unity doc page working and costing a round trip.

**C also wants fewer encodings.** A needed three shapes to get a `Vector3` in — `[1,2,3]` for
`set_transform --position`, `{"x":2,"y":2,"z":2}` for `set_serialized_field --value` (the array
form is rejected: `Expected a JSON object with named components (e.g. { "x": 0 }) but received
a 'Array'`), and a bare comma string silently accepted as a no-op. C took `[1,2,3]` for both
`position` and `size` with no discrimination between them.

**State echo, all three arms measured in one run: C 2 of 4, B 1 of 5, A 0 of 6.** C's two
`manage_gameobject create` calls returned the full serialized object — transform, tag, layer,
`componentNames`, `parentInstanceID`. Its two `manage_components` calls (`add`, `set_property`)
returned identity only. B's split is exactly as T-003 and T-004 recorded: `set_component_properties`
alone echoes, the other three do not. **C is now the best arm on this axis and A is still the
worst**, which inverts the T-001-era claim that confirmation was free on B and absent on C.
The practical rule is unchanged for every arm: read the state back. C's `set_property` in
particular still returns a bare `{"instanceID": -28076}` with no value in it.

**The `instanceId` collision is a transport artifact, and C's data proves it.** This supersedes
the standing entry, which treats the collision as an engine-level defect that "reproduces at
both GameObject and component granularity."

- **A** returned `568105589213729500` for *both* `T005-Root-A` and `T005-Child-A`, and
  `568105589213729400` for the child's `BoxCollider`.
- **B** returned `568105589213729400` for all five objects it touched — two GameObjects and a
  component — emitted as a **bare unquoted JSON number**.
- **C** returned small session-local `instanceID`s that were all distinct — root `-28066`,
  child `-28076`, BoxCollider `-28090`, its material `-28094` — *and*, separately, the large
  `EntityId` values as **quoted strings**: gameObject `"568105589213729364"`, material
  `"568105589213729346"`.

Those two C values are **18 apart**. At magnitude ~5.68 × 10¹⁷ the value sits in `[2^58, 2^59)`,
where the IEEE-754 double spacing is 2⁶ = **64**. Two distinct `EntityId`s 18 apart therefore
*cannot* survive a round trip through a double — they collapse onto one. That is precisely what
A and B emit: values rounded to a multiple of the ULP (`…729400`, `…729500`), identical across
objects that the engine distinguishes. **The engine's ids are distinct; Pipeline's JSON destroys
the distinction by serializing a 59-bit integer as a number instead of a string.** C avoids it
by quoting. The operational advice is unchanged — never key on `instanceId` from A or B — but
the diagnosis moves from "nondeterministic engine bug" to "deterministic precision loss in
Pipeline's serializer," which is a fixable defect with a known owner.

**Arm C reports three different version numbers, and none of the live tools carry the one that
matters.** Recorded separately rather than reconciled:

| Number | What it actually is | Where it comes from |
|---|---|---|
| `10.0.0` | the installed Unity package | `Packages/manifest.json` pins `#v10.0.0`; `Packages/packages-lock.json` agrees; `Library/PackageCache/com.coplaydev.unity-mcp@7b7db7b31f4e/package.json` says `"version": "10.0.0"` |
| `10.1.0` | the Python server `uvx` resolved | recorded by T-001's correction note; **not re-observed in this run** |
| `mcp-for-unity-server 3.4.6` | `serverInfo.version` in the MCP `initialize` response | client-side handshake only; **not re-observed in this run**, and not reachable from inside an arm |
| `unity-mcp/editor_state@2` | a response-schema version for one resource | `mcpforunity://editor/state`, `schema_version` field |

The package and the Python server version-stamp independently because the package pulls the
server via `uvx`, so `10.0.0` and `10.1.0` are not in conflict — they describe different
artifacts. `3.4.6` is a third artifact again, and the earlier `3.4.5` in T-001 was FastMCP's
version, not the server's. **Separately: not one of arm C's 47 tools or 18 resources reports a
package or server version.** Three were checked (`mcpforunity://custom-tools`,
`ListMcpResourcesTool`, `manage_editor telemetry_status`) and none carry one; the only route to
`10.0.0` was reading the project's own lockfile from outside the arm. An arm that cannot tell
you which version of itself you are talking to is why four rows in this file went stale unnoticed.

**Step counts do not separate these arms, and should not be read as if they do.** C's task path
was 7 calls, B's 11, A's 14 against the Editor — but C's 7 buys less verification than B's 11,
because C's two read-backs were resource reads that returned everything at once while B spent
separate calls per property. The honest separator is **failed calls: A 3, B 1, C 0.**

**Arm A's silent argument-drop reproduced, plus a new variant.** `--position 1,2,3` returned
exit 0 and `"success": true` and changed nothing, as T-004 found. New this run:
`--position 1 2 3` does not merely lose the value, it **mis-binds the trailing tokens to other
parameters**, producing `Could not resolve 'target': No loaded object with instanceId 2.` — an
error that names a parameter the caller never set. `unity command <tool> --help` was probed
directly and confirmed to print generic usage only.

**Verdict** — **C for this task**, on friction, and for the first time on something other than
step count. C is the only arm in four runs of this task to complete it with **zero failed
calls**, the only one that accepts the property name Unity's own documentation gives, and the
only one whose object handles survive its own JSON. B remains the better-instrumented arm
(loud, specific errors; 44 of 140 tools allowlistable read-only against C's 9 of 47) and is the
right default for unattended work where a permission rule has to be written. A completes the
task but pays for it, and two of its five failures announced nothing.

This is a friction verdict, not a capability verdict — all three arms produced identical correct
scenes, as they have every time.

**Matrix changes** — *GameObject authoring* re-rated to **C, then B**, confidence raised to
Medium-High (first run with all three arms actually executing). Standing observations updated on
the `instanceId` collision (mechanism corrected to serializer precision loss) and on state echo
(C now measured best, not worst). Arm-C staleness cleared for this row only.

**Follow-ups**
- **Three rows still rest on unrefreshed `v10.0.0` arm-C evidence**: physics/geometry queries,
  carrying on when the other MCP is down, and multi-client environments. T-005 refreshed
  GameObject authoring and nothing else.
- **File the `instanceId` serialization defect against Pipeline**, with the 64-ULP arithmetic
  above. It is a one-character fix (quote the value) and it currently makes every object handle
  A and B return non-discriminating.
- Does C's public-name translation extend beyond `BoxCollider.size` — does it accept `center`,
  `isTrigger`, or arbitrary public properties on other component types? Cheap to test and it
  decides whether the ergonomic win generalises or is one lucky alias.
- Arm C still cannot report its own version from any live call. Check whether a newer package
  exposes one before trusting any future staleness audit.
- Prefab authoring and script-create-attach-recompile, still untested after five trials.

### T-004 — the same authoring task, first attempt at a genuine three-way

**Date** 2026-08-06 · **Category** authoring · **Mutating** yes ·
**Versions** CLI `1.0.0-beta.3`, Editor `6000.5.5f1`, Pipeline `0.4.0-exp.1`,
MCP for Unity `v10.0.0` (server self-reported; `LatestKnownVersion` = `10.1.2`)

Third run of the T-001 task — root empty, child empty at local `(1, 2, 3)`, `BoxCollider`
with size `(2, 2, 2)` — named `T004-Root-<arm>` / `T004-Child-<arm>` per arm. Blind and
serial, one subagent per arm, each writing its own account before any comparison:
[arm-a.md](trials/T-004/arm-a.md) · [arm-b.md](trials/T-004/arm-b.md) ·
[arm-c.md](trials/T-004/arm-c.md). Objects deleted afterwards and confirmed gone by
read-back; scene never saved.

| Arm | Outcome | Steps | Friction | Verifiable? |
|---|---|---|---|---|
| A CLI | completed | 23 (17 `unity command`, of which 6 were pure read-back) | 3 encodings for `position`, 2 for `m_Size`; two **silent** no-ops | Only by separate read — **0 of 8** mutating calls echoed state |
| B MCP official | completed | 11 editor calls + 2 schema loads | none — zero errors, zero retries | Mostly by separate read — 1 of 4 mutating calls echoed state |
| C MCP CoplayDev | **blocked** | 12 calls, 2 succeeded | every Editor-bound call returned `no_unity_session` after a 20s block | N/A — nothing was created |

**This is still not a three-way trial.** Arm C failed for the *fourth* consecutive attempt,
and this time **not for the reason the record predicts.**

**A new gate on C, distinct from the known one.** The standing observation says C's real
obstacle is the client — [P1, reads-once-at-startup](../UNITY-TOOLING-NOTES.md#p1--reads-once-at-startup)
— an MCP server must be registered before the session begins. That gate was **cleared** here:
the session started with C registered, `mcp__UnityMCP__*` loaded, and the server answered.
A different gate bit. The **Unity-side plugin is not attached to its own server**:

```json
{"success":false,"error":"Unity session not available; please retry",
 "data":{"reason":"no_unity_session","retry_after_ms":250},"hint":"retry"}
```

`debug_request_context` shows `plugin_hub_configured: true`, `active_instance: null`,
`all_keys_in_store: []`; `mcpforunity://instances` reports `instance_count: 0`. The last
successful `Plugin registered:` line in the server log is dated **2026-07-29** — the plugin
has not connected across three later server sessions. The Editor started the server itself
(`MCP-FOR-UNITY: Starting local HTTP server…` in its own log) and then never dialled into
`127.0.0.1:8080`; confirmed by socket inspection and a 150s poll. `DebugLogs = 0` is why this
is silent in the Unity console. Recovery is Editor-side only (MCP window reconnect, domain
reload, or restart), so the arm ends blocked rather than failed.

Verified independently by the coordinator after the arm reported: `debug_request_context`
returned the same empty instance store, and a read-only `find_gameobjects` returned the same
error verbatim. **This is a property of the setup, not an agent error.**

**`three-way-setup.sh --check` gives a false pass on arm C.** It reported *"ok — server
already answering at `http://127.0.0.1:8080/mcp` (HTTP 406)"* and *"All three arms are up."*
An answering HTTP server is not an attached plugin. The check must additionally require
`instance_count > 0` from `mcpforunity://instances`, or every future trial will spend an arm's
budget rediscovering this. **`[open — the script is unchanged]`**

**The three open questions about C are unanswered, and that is absence of evidence, not
evidence.** No mutating call reached Unity, so nothing was learned about (1) whether C needs
`m_Size` or accepts the public `size` — the public-name form *was* issued and died at the
transport layer; (2) whether C echoes state or identity; (3) whether C hits the `instanceId`
collision. **All arm-C claims in this file still rest on `v10.0.0` evidence from T-001, now
three releases stale, and T-004 did not refresh any of them.**

**First real step-count separation between A and B — with a caveat that matters.** 23 versus
11. But A's excess is almost entirely *first-time argument-encoding discovery*: three attempts
at `position`, two at `m_Size`, and six read-backs that existed only because nothing echoes.
A second A run knowing the encodings would land near 12. So this separates the arms on
**cost of the first correct call**, not on inherent verbosity — which is the cost an agent
without this file actually pays.

**Arm A fails silently on well-formed-looking arguments, which widens a standing observation
rather than confirming it.** The known trap was that only `--flag value` binds. T-004 found
worse: a **correctly named flag with the wrong value encoding is also dropped silently.**

```
unity command set_transform --target /T004-Root-A/T004-Child-A --position 1,2,3 --json
```
→ exit 0, `"success": true`, echo `"position": "1,2,3"`, and `m_LocalPosition` still
`{x:0,y:0,z:0}`. Repeating the flag (`--position 1 --position 2 --position 3`) also returns
success, with the echo showing `"position": 3` — last flag wins, as a scalar. Only
`--position '[1,2,3]'` landed. **The success payload is byte-identical in shape across the two
no-ops and the write that worked**, so exit code and `success: true` carry no information about
whether the value arrived. This partially rolls back the 2026-08-06 softening of "A fails
quietly": that re-audit was about *connection* failures, which are indeed loud (exit 6). This
is *argument* failure, which is silent. Both are true; they are different failure classes.

**Two neighbouring tools want two different `Vector3` encodings, and the schema says neither.**
`set_transform --position` takes `[1,2,3]` and rejects the object form; `set_serialized_field
--value` for a Vector3 takes `{"x":2,"y":2,"z":2}` and rejects the array with the trial's one
loud error, exit 6: `Pipeline server returned 400 Bad Request: Parameter Validation Failed.
Expected a JSON object with named components (e.g. { "x": 0 }) but received a 'Array'.` The
`parameters` array in `unity list --json` distinguishes them only by prose description.

**`m_Size` over `size` reconfirmed on both A and B** — third trial running. Not news; recorded
so the pattern is not re-derived a fourth time.

**The `instanceId` collision is reproduced, and it is total.** On B, all four objects — root
GameObject, child GameObject, its Transform, its BoxCollider — returned the **identical**
`568105589213729200` against four distinct `globalId`s. On A, three of four shared
`568105589213729300`. This is direct empirical confirmation of the entry that was previously
marked *"not reproduced"* and then superseded on source-reading alone; it no longer rests on
source-reading alone. **New on top of that: the value exceeds 2^53**, so the trailing digits
(`…729300` vs `…729200`) are IEEE-754 double-rounding artifacts, not real values — the field is
lossy in transit as well as misnamed and non-discriminating.

**B's verification asymmetry reconfirmed exactly as T-003 corrected it.** 3 of B's 4 mutating
calls returned identity only; `set_component_properties` alone echoed the post-write property
map. **A is strictly worse on this axis than B**, which is new: A has *no* echoing mutator at
all, so B beats A here by exactly one tool. Budget one read per write on both.

**Verdict** — **B for this task, on friction rather than capability.** B completed with zero
errors and zero retries; A completed but paid five failed or ineffective calls, two of which
announced nothing. Both produce identical correct scenes, so this is not a capability verdict.
C remains unmeasured since T-001.

**Matrix changes** — *GameObject authoring* re-rated: **B** preferred, A workable with a
verify-every-write discipline, C's inclusion demoted to unverified-since-T-001. Confidence
held at Medium, not raised, because the arm that would have made this a three-way did not run.

**Follow-ups**
- **Fix `three-way-setup.sh --check` to require `instance_count > 0`.** It currently passes an
  arm that cannot execute a single Editor-bound call.
- Recover C's plugin attachment — Editor-side, needs a human or an Editor restart. Until then
  a three-way trial is not runnable and the four `v10.0.0`-dependent rows stay stale.
- Turn on `MCPForUnity.DebugLogs` before the next attempt; the failure is silent without it.
- Does A's silent argument-drop affect other array-typed (`single[]`, `jobject`, `jtoken`)
  parameters, or only `set_transform`? A survey would be cheap and is worth more than another
  authoring run.
- Prefab authoring and script-create-attach-recompile, still untested after four trials.

### T-003 — T-001 re-run, this time including arm A

**Date** 2026-08-06 · **Category** authoring · **Mutating** yes ·
**Versions** CLI `1.0.0-beta.3`, Editor `6000.5.5f1`, Pipeline `0.4.0-exp.1`

Same task as T-001 — root empty, child empty at local `(1, 2, 3)`, `BoxCollider` with `size`
`(2, 2, 2)` — run because T-001 excluded arm A on the premise that the CLI has no scene
access, which is false. Blind and **serial**, one subagent per arm, each writing its own
account before any comparison: [arm-a.md](trials/T-003/arm-a.md) · [arm-b.md](trials/T-003/arm-b.md).

Serial rather than parallel because one Editor serves both arms. Concurrent runs would have
been two agents mutating one scene, which is not two trials.

**Arm C did not run**, but `[corrected the same day]` **not for the reason first recorded.**
This entry originally said C was unavailable because starting it is GUI-gated, and marked the
"most expensive arm to stand up" claim `[still current]` on the strength of nothing listening
on `127.0.0.1:8080`. That was absence-of-evidence, concluded without reading source that was
sitting in `PackageCache`. The server **starts headlessly** — see the standing observation
below. The real obstacle is different and is a property of the *client*, not the arm: an MCP
server must be registered before a Claude Code session starts, so C cannot be added to a
session already in progress. A three-way trial needs a **fresh session with C registered**,
which is scriptable, rather than a human at the Editor, which is not.

**Both arms completed the task and verified it by read-back.** A took 10 core steps, B took 10
excluding hygiene checks. There is no meaningful step-count winner, which is also what T-001
found between B and C.

**Arm A authors, not just inspects.** T-001's exclusion was wrong in both directions: the CLI
creates GameObjects, reparents, sets local transforms, adds components and sets serialized
properties, all verified by independent read-back.

**The first demonstrated A-vs-B difference, and it is not in the tools.** Both arms call the
same Pipeline tool for scene inspection. Through B, `get_scene_hierarchy` on this scene
returned 291k characters / 7,905 lines and **exceeded the tool-result limit** — it has no
filter, depth or pagination parameter, so on any real scene it is unusable and you must
substitute `find_gameobjects`. Through A the identical call is fine, because the payload lands
in a shell that can filter it before any of it reaches a context window. **Same stack, same
tool, different failure mode by delivery channel.** For inspection of large scenes, prefer A.

**Both arms failed identically on `size` vs `m_Size`** — `set_component_properties` and its CLI
equivalent both require Unity's serialized field name, not the public C# API name in the
Scripting Reference. One failed call plus a discovery round-trip, on both arms. This is the
first *empirical* confirmation of the A=B correction: one stack, one bug, surfacing the same
way through both front-ends.

### T-001 — build the same GameObject hierarchy through each arm

**Date** 2026-07-28 · **Category** authoring · **Mutating** yes ·
**Versions** CLI `1.0.0-beta.3`, Editor `6000.5.5f1`, Pipeline `0.4.0-exp.1`,
MCP for Unity `v10.0.0` `[corrected 2026-08-06: this line read "server 3.4.5". 3.4.5 is
FastMCP's version, not the server's — the Unity package pulls the Python server via uvx, so
the two version-stamp independently. The resolved server here was 10.1.0.]`

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
