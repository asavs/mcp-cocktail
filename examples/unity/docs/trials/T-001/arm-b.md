# T-001, arm B: Unity official MCP (`unity-editor-mcp`)

**Task**: In the active scratch scene, create empty GameObject `T001-Root`, with
child empty GameObject `T001-Child` at local position (1, 2, 3), carrying a
`BoxCollider` with `size` (2, 2, 2).

**Versions** (from `editor_status` and `docs/unity-mcp.md` header, both read at
the start of this trial): editor `6000.5.5f1`, CLI `1.0.0-beta.3`, Pipeline
`0.4.0-exp.1`, MCP for Unity `v10.0.0` (per the doc; not independently queried
for this arm — see note below), date 2026-07-28.

Tool namespace used exclusively: `mcp__unity-editor-mcp__*`. No `eval`/
`eval_file`, no CLI, no shell authoring.

## Outcome

**Completed.** All acceptance criteria met and confirmed by reading state back
after the tool calls reported success (see "Verification" below).

## Calls made, in order

1. `mcp__unity-editor-mcp__editor_status` — args: none.
   Returned `{"status":"ready","compiling":false,"domainReloadInProgress":false,
   "playMode":"stopped","unityVersion":"6000.5.5f1", ...}`. Used only for the
   version stamp above; also confirms editor was idle and reachable before
   touching anything.

2. `mcp__unity-editor-mcp__get_scene_hierarchy` — args: none (defaults to
   active scene). Returned the two expected roots, `Main Camera` and
   `Directional Light`, `sceneName`/`scenePath` both empty strings (consistent
   with an untitled, unsaved scene), `isDirty: true`. Baseline check before
   authoring — confirms I was looking at the described scratch scene and
   nothing named `T001-*` already existed.

   Oddity noticed here, unrelated to my task: both root nodes reported the
   *same* `instanceId` (`568105589213755970`). Different objects, identical
   instanceId. Flagged as a possible tool quirk (see Friction).

3. `mcp__unity-editor-mcp__create_gameobject` — args:
   `{"name": "T001-Root"}`. Returned success:
   `{"hierarchyPath": "/T001-Root", "instanceId": 568105589213755140, ...}`.
   Tool-reported success only at this point; not yet verified independently.

4. `mcp__unity-editor-mcp__create_gameobject` — args:
   `{"name": "T001-Child", "parent": "/T001-Root"}`. Returned success:
   `{"hierarchyPath": "/T001-Root/T001-Child", "instanceId": 568105589213755140, ...}`.

   Same instanceId as the previous call's *different* GameObject
   (`T001-Root`). This is the same pattern as step 2 — every object handle
   returned in this session so far after the first two carries instanceId
   `568105589213755140` regardless of which object it names. I treated
   `hierarchyPath` as the reliable handle for all subsequent calls instead of
   `instanceId`, and that worked throughout. I did not determine whether this
   is a real bug in the tool's response serialization or an intentional
   "instanceId not meaningful outside Unity's own session" behavior — flagging
   as uncertain rather than guessing.

5. `mcp__unity-editor-mcp__set_transform` — args:
   `{"target": "/T001-Root/T001-Child", "position": [1, 2, 3]}`. Returned
   success (same handle echoed back). Tool-reported success only; not yet
   independently verified at this point in the sequence.

6. `mcp__unity-editor-mcp__add_component` — args:
   `{"target": "/T001-Root/T001-Child", "type": "BoxCollider"}`. Returned
   success, `"type": "BoxCollider"` in the echoed handle.

7. `mcp__unity-editor-mcp__set_component_properties` — args:
   `{"target": "/T001-Root/T001-Child", "type": "BoxCollider",
   "properties": {"size": [2, 2, 2]}}`.
   **Failed**: `Error: Pipeline server returned 400 Bad Request: Parameter
   Validation Failed. Component 'BoxCollider' has no serialized property
   'size'.`

   This is the one real friction point in the trial. `size` is
   `BoxCollider.size`'s public C# property name and is what the Unity docs and
   most humans would type first. The tool operates on Unity's *serialized*
   field names, not the public API names, and did not accept the public name
   nor auto-map it.

8. `mcp__unity-editor-mcp__get_component_properties` — args:
   `{"target": "/T001-Root/T001-Child", "type": "BoxCollider"}`, called to
   recover from step 7's failure by discovering the actual property name.
   Returned the full serialized property map, including
   `"m_Size": [1, 1, 1]` (still default, confirming step 7 did not partially
   apply) and `"m_Center": [0, 0, 0]`.

9. `mcp__unity-editor-mcp__set_component_properties` — args:
   `{"target": "/T001-Root/T001-Child", "type": "BoxCollider",
   "properties": {"m_Size": [2, 2, 2]}}`. Returned success, with the updated
   properties echoed back in the response: `"m_Size": [2, 2, 2]`.

   At this point I had two signals: the tool's own success response echoing
   the new value, plus the fact that step 7 had just shown me the pre-change
   state to diff against. I still did not treat this as final confirmation —
   see step 10.

10. `mcp__unity-editor-mcp__get_scene_hierarchy` — args: none. This is the
    real, independent verification. Returned all four objects: `Main Camera`,
    `Directional Light`, `T001-Root` (components: `Transform`; child
    `T001-Child`), and `T001-Child` under it with components `Transform`,
    `BoxCollider`. Confirms parent/child relationship and component presence
    from a source separate from the calls that made the changes.

11. `mcp__unity-editor-mcp__get_component_properties` — args:
    `{"target": "/T001-Root/T001-Child", "type": "Transform"}`, called fresh
    (not reusing the create/set-transform response) specifically to
    independently confirm local position. Returned
    `"m_LocalPosition": [1, 2, 3]`, `"m_LocalScale": [1, 1, 1]`.

12. `mcp__unity-editor-mcp__find_gameobjects` — args: `{"name": "T001-Child"}`.
    Returned exactly one match, at `hierarchyPath: "/T001-Root/T001-Child"`,
    confirming there is no naming collision or duplicate created by mistake.

I did not re-call `get_component_properties` for `BoxCollider` a second time
after step 9 (step 9's own response already echoed `m_Size: [2,2,2]`, and step
8 already showed me the schema/pre-state) — in hindsight, for strict symmetry
with the Transform check in step 11, I should have. This is a real gap: my
confirmation of the collider size rests on the *mutating* call's own response
(step 9) plus the *scene hierarchy* confirming the component exists (step 10),
not on a separate read-only property fetch after the fact the way position was
confirmed. I'm noting this explicitly rather than overstating my verification.

## What I verified, and how (recap)

- **GameObject existence and parenting**: confirmed via `get_scene_hierarchy`
  (step 10), a call independent of the creation calls (steps 3-4).
- **Local position (1,2,3)**: confirmed via a fresh `get_component_properties`
  read (step 11), independent of the `set_transform` call that set it (step
  5).
- **BoxCollider presence**: confirmed via `get_scene_hierarchy` (step 10).
- **BoxCollider size (2,2,2)**: confirmed only via the echoed response of the
  `set_component_properties` mutating call itself (step 9), corroborated by
  the pre-state read in step 8. Not confirmed by an independent read-only
  fetch after the mutation. Weaker than the position check, and I want that
  asymmetry on record rather than silently presenting both as equally solid.

## Friction

- **`size` vs `m_Size`**: the tool takes Unity's serialized field names, not
  the public C# API names. `BoxCollider.size` (public) is exposed as
  `m_Size` (serialized). Cost one failed call and one extra
  `get_component_properties` round trip to discover the correct key. Given
  `size` is the name in every Unity Scripting API page and most people's
  muscle memory, this is a plausible general source of first-try failures for
  any component property whose serialized name differs from its public
  property name (also saw `m_LocalPosition` vs `localPosition`,
  `m_LocalScale` vs `localScale` for Transform — I got those right by luck of
  passing position via `set_transform`'s own `position` argument rather than
  through `set_component_properties`).
- **Duplicate/shared `instanceId` values**: every `create_gameobject` /
  `set_transform` / `add_component` response after the very first
  `get_scene_hierarchy` call echoed `instanceId: 568105589213755140`,
  regardless of which distinct GameObject the call concerned (`T001-Root` and
  `T001-Child` both got this number from their respective creation calls).
  The initial `get_scene_hierarchy` before any authoring also showed `Main
  Camera` and `Directional Light` sharing one instanceId
  (`568105589213755970`), different from the number above. I do not know if
  this is a serialization bug (e.g., a field not being refreshed between
  calls in the same batch/frame) or something else in how instanceId is
  computed/reported by this tool. `hierarchyPath` was unambiguous and reliable
  throughout, so I used that as the handle for every call after the two
  `create_gameobject` calls, and it worked without issue. I'm flagging this
  as "possible tool problem, unconfirmed" rather than asserting it's a bug.
- The `docs/unity-mcp.md` reference doc's version table did not need
  correction for this trial; no other doc friction encountered.

## Expressiveness gaps

None encountered for this task. Creating GameObjects, parenting, setting
local transform, adding a component, and setting component properties were
all directly and separately expressible with dedicated tools
(`create_gameobject`, `set_parent` — not needed since `parent` was passable
directly at creation time, `set_transform`, `add_component`,
`set_component_properties`). No need to fall back to `eval`/`eval_file` at
any point, which is consistent with the task's prohibition on using them.

## Confidence / unsure items

- Whether the shared-`instanceId` behavior above is a genuine defect in
  `unity-editor-mcp`'s response building, or an artifact of how I'm reading
  the field (e.g., possibly a "last created object" cache that isn't
  per-object) — unsure, did not investigate further since it didn't block the
  task and `hierarchyPath` was a reliable substitute handle throughout.
  Recording rather than guessing.
- Whether `set_component_properties` would have accepted the public property
  name `size` via some alias I didn't try (e.g., case variations) — I did not
  retry with alternate spellings once `m_Size` worked, so I can't rule out
  that `size` might work under different casing or that the error message is
  simply accurate and exhaustive. Treating the error message at face value.
- The MCP-for-Unity (`v10.0.0`) version noted at the top came from the
  reference doc, not from a direct query in this arm (this trial did not use
  any CoplayDev tool, per the task's restriction), so it is provenance, not an
  independently confirmed observation in this session.
