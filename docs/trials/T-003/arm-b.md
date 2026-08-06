# T-003, arm B: Unity official MCP (`unity-editor-mcp`)

**Task**: In the currently open scene, create empty GameObject `T003-Root-B`,
with child empty GameObject `T003-Child-B` at local position (1, 2, 3),
carrying a `BoxCollider` with `size` (2, 2, 2). Verify by reading state back,
not by trusting create/set call return values. Do not save the scene.

**Versions** (from `mcp__unity-editor-mcp__editor_status`, called at the start
of this trial): editor `6000.5.5f1`, project path
`C:\Users\asas\UnityProjects\third-person-multiplayer-gabe`. No CLI, `eval`,
or `eval_file` was used anywhere in this trial (both prohibited/out of scope
for this arm), so no separate CLI or MCP-package version number was queried.
Editor was `status: ready`, not compiling, play mode `stopped` at the start.

Tool namespace used exclusively: `mcp__unity-editor-mcp__*`.

## Outcome

**Completed.** All three acceptance criteria met and confirmed by read-only
calls made after the mutating calls, none of which reused a mutating call's
own echoed response as the sole evidence.

## Calls made, in order

1. `mcp__unity-editor-mcp__editor_status` — args: none. Returned
   `{"status":"ready","compiling":false,"domainReloadInProgress":false,
   "playMode":"stopped","unityVersion":"6000.5.5f1",
   "projectPath":"C:\\Users\\asas\\UnityProjects\\third-person-multiplayer-gabe", ...}`.
   Used for the version stamp and to confirm the editor was idle and reachable.

2. `mcp__unity-editor-mcp__get_scene_hierarchy` — args: none (active scene).
   **Failed, not with a tool error but a harness-side limit**: the scene is
   large (a working multiplayer project scene, not an empty scratch scene) and
   the response was 291,166 characters across 7,905 lines — over the maximum
   tokens my tool-result channel accepts. The call itself presumably succeeded
   inside Unity; I never saw the payload. I did not retry it with pagination
   because the tool takes no depth/filter/pagination argument (only an
   optional scene `path`), so there was no way to shrink the response by
   asking differently. I abandoned whole-hierarchy dumps for this trial and
   used `find_gameobjects` (which returns only matching nodes) for every
   baseline and verification check instead. This is the single most expensive
   piece of friction in the trial.

3. `mcp__unity-editor-mcp__find_gameobjects` — args: `{"name": "T003-Root-B"}`.
   Returned `{"count": 0, "gameObjects": []}`. Baseline check confirming the
   name wasn't already taken by something else in this shared scene.

4. `mcp__unity-editor-mcp__find_gameobjects` — args: `{"name": "T003-Child-B"}`.
   Returned `{"count": 0, "gameObjects": []}`. Same baseline check for the
   child name.

5. `mcp__unity-editor-mcp__create_gameobject` — args:
   `{"name": "T003-Root-B"}`. Returned:
   ```
   {"globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1603892851-0",
    "assetPath": null, "guid": null, "fileId": null,
    "instanceId": 568105589213729500,
    "hierarchyPath": "/T003-Root-B", "type": "GameObject"}
   ```
   Succeeded first try. Note this response is an *identity echo* (handle,
   path, type) — it does not echo any state such as transform values or
   component list.

6. `mcp__unity-editor-mcp__create_gameobject` — args:
   `{"name": "T003-Child-B", "parent": "/T003-Root-B"}`. Returned:
   ```
   {"globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-532255893-0",
    "assetPath": null, "guid": null, "fileId": null,
    "instanceId": 568105589213729500,
    "hierarchyPath": "/T003-Root-B/T003-Child-B", "type": "GameObject"}
   ```
   Succeeded first try, parent supplied directly at creation (no separate
   `set_parent` call needed). Note the `instanceId` here
   (`568105589213729500`) is identical to the previous call's `instanceId`
   for the *different* GameObject `T003-Root-B`, even though `globalId` and
   `hierarchyPath` correctly differ. Same discrepancy recurred later (see
   Surprises).

7. `mcp__unity-editor-mcp__set_transform` — args:
   `{"target": "/T003-Root-B/T003-Child-B", "position": [1, 2, 3]}`.
   Returned:
   ```
   {"globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-532255893-0",
    "assetPath": null, "guid": null, "fileId": null,
    "instanceId": 568105589213729500,
    "hierarchyPath": "/T003-Root-B/T003-Child-B", "type": "GameObject"}
   ```
   Succeeded first try. Again, identity echo only — no `position` field in
   the response body, so this call's own return value gives zero evidence the
   position actually took effect.

8. `mcp__unity-editor-mcp__add_component` — args:
   `{"target": "/T003-Root-B/T003-Child-B", "type": "BoxCollider"}`.
   Returned:
   ```
   {"globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-532255895-0",
    "assetPath": null, "guid": null, "fileId": null,
    "instanceId": 568105589213729400,
    "hierarchyPath": "/T003-Root-B/T003-Child-B", "type": "BoxCollider"}
   ```
   Succeeded first try. Again identity-only: confirms a `BoxCollider` handle
   now exists on that GameObject, but not its property values (e.g. default
   `size`).

9. `mcp__unity-editor-mcp__set_component_properties` — args:
   `{"target": "/T003-Root-B/T003-Child-B", "type": "BoxCollider",
   "properties": {"size": [2, 2, 2]}}`.
   **Failed**: `Error: Pipeline server returned 400 Bad Request: Parameter
   Validation Failed. Component 'BoxCollider' has no serialized property
   'size'.` `size` is `BoxCollider`'s public C# property name (the one in the
   Unity Scripting API and the one anyone would type first); the tool wants
   Unity's internal serialized field name instead.

10. `mcp__unity-editor-mcp__get_component_properties` — args:
    `{"target": "/T003-Root-B/T003-Child-B", "type": "BoxCollider"}`, called
    to recover from step 9 by discovering the real property name. Returned
    the full serialized map:
    ```
    {"m_Material": null, "m_IncludeLayers": "<unsupported:LayerMask>",
     "m_ExcludeLayers": "<unsupported:LayerMask>",
     "m_LayerOverridePriority": 0, "m_IsTrigger": false,
     "m_ProvidesContacts": false, "m_Size": [1, 1, 1],
     "m_Center": [0, 0, 0]}
    ```
    Confirms the default size is still `[1,1,1]` (step 9's failure did not
    partially apply) and that the real field is `m_Size`.

11. `mcp__unity-editor-mcp__set_component_properties` — args:
    `{"target": "/T003-Root-B/T003-Child-B", "type": "BoxCollider",
    "properties": {"m_Size": [2, 2, 2]}}`. Returned:
    ```
    {"component": {..., "type": "BoxCollider"},
     "properties": {"m_Material": null,
       "m_IncludeLayers": "<unsupported:LayerMask>",
       "m_ExcludeLayers": "<unsupported:LayerMask>",
       "m_LayerOverridePriority": 0, "m_IsTrigger": false,
       "m_ProvidesContacts": false, "m_Size": [2, 2, 2],
       "m_Center": [0, 0, 0]}}
    ```
    Succeeded. Unlike every other mutating call in this trial, this one's
    response body includes the **full resulting property map**, not just an
    identity handle — genuine state echo, not just identity echo.

12. `mcp__unity-editor-mcp__get_component_properties` — args:
    `{"target": "/T003-Root-B/T003-Child-B", "type": "Transform"}`. Read-only,
    independent of the `set_transform` call in step 7. Returned:
    ```
    {"m_LocalRotation": "<unsupported:Quaternion>",
     "m_LocalPosition": [1, 2, 3], "m_LocalScale": [1, 1, 1],
     "m_ConstrainProportionsScale": false}
    ```
    `instanceId` on this component handle: `568105589213729500` — same
    number as steps 5-7's GameObject handles, despite this being a
    *different object* (a Transform *component*, not a GameObject). See
    Surprises.

13. `mcp__unity-editor-mcp__find_gameobjects` — args: `{"name": "T003-Root-B"}`.
    Read-only, independent of step 5. Returned exactly one match:
    `hierarchyPath: "/T003-Root-B"`.

14. `mcp__unity-editor-mcp__find_gameobjects` — args: `{"name": "T003-Child-B"}`.
    Read-only, independent of step 6. Returned exactly one match:
    `hierarchyPath: "/T003-Root-B/T003-Child-B"`. The path itself is proof of
    the parent/child relationship (Unity only produces this path string if
    `T003-Child-B` is actually parented under `T003-Root-B`), so this and the
    previous call jointly stand in for the `get_scene_hierarchy` dump that
    step 2 couldn't deliver.

15. `mcp__unity-editor-mcp__get_component_properties` — args:
    `{"target": "/T003-Root-B/T003-Child-B", "type": "BoxCollider"}`. Called a
    second time, purely as a read-only re-check after step 11's mutation, for
    symmetry with the Transform check in step 12 (i.e., not relying on step
    11's own echo as the only evidence). Returned:
    ```
    {"m_Material": null, "m_IncludeLayers": "<unsupported:LayerMask>",
     "m_ExcludeLayers": "<unsupported:LayerMask>",
     "m_LayerOverridePriority": 0, "m_IsTrigger": false,
     "m_ProvidesContacts": false, "m_Size": [2, 2, 2],
     "m_Center": [0, 0, 0]}
    ```
    Confirms `m_Size: [2, 2, 2]` from a call independent of the mutation.

15 calls total; 1 mutating call failed on its first attempt (step 9), 1
read-only call failed for harness reasons unrelated to the tool's own
correctness (step 2).

## Step count

15 tool calls to reach a fully independently-verified end state:
2 baseline checks (3-4), 1 failed hierarchy dump (2) + 1 status check (1),
4 mutating calls that succeeded (5, 6, 7, 8), 1 mutating call that failed
(9) + 1 recovery read (10) + 1 corrected mutating call (11), and 4 read-only
verification calls after all mutations (12, 13, 14, 15).
Discounting the harness-limited hierarchy dump and the two pre-emptive
baseline lookups as "trial hygiene" rather than task-necessary, the minimum
path to a *verified* correct end state was 10 calls: create root, create
child (parented), set transform, add component, set-properties attempt #1
(wrong key), get-properties (discover key), set-properties attempt #2
(right key), then 3 independent reads to confirm position / hierarchy /
size.

## What worked first try, and what didn't

**Worked first try:**
- `editor_status`
- Both baseline `find_gameobjects` calls
- `create_gameobject` (root)
- `create_gameobject` (child, with `parent` set directly — no separate
  `set_parent` call needed)
- `set_transform` with a plain `position: [1,2,3]` array
- `add_component` with `type: "BoxCollider"`
- Both post-mutation `find_gameobjects` calls
- Both post-mutation `get_component_properties` calls

**Did not work first try:**
- `get_scene_hierarchy` with no arguments — technically may have succeeded
  server-side, but the response exceeded my tool-result size limit and was
  unusable. Root cause: the scene is large and the tool has no way to scope,
  filter, or paginate the dump (only an optional scene-file `path`, not a
  root-node or depth argument).
- `set_component_properties` with `properties: {"size": [2,2,2]}` — exact
  error: `Error: Pipeline server returned 400 Bad Request: Parameter
  Validation Failed. Component 'BoxCollider' has no serialized property
  'size'.` Fixed by discovering and using `m_Size` instead.

## Friction

- **`size` vs `m_Size`**: the tool operates on Unity's internal serialized
  field names, not the public C# API names shown in the Scripting Reference.
  `BoxCollider.size` (public, and what anyone reading Unity docs would type)
  is `m_Size` underneath. Cost one failed call plus one extra
  `get_component_properties` round trip to discover the right key. This
  looks like a durable property of the tool rather than a one-off: nothing
  in the tool description for `set_component_properties` mentions serialized
  vs. public naming, so there's no way to know in advance which spelling a
  given component wants without either already knowing Unity's internals or
  eating a failed call.
- **`get_scene_hierarchy` doesn't scale to real scenes**: it dumps the
  *entire* scene tree with no filter/depth/pagination parameter, and this
  scene (a working project scene with substantial existing content, not an
  empty scratch scene) produced a payload too large for my tool-result
  channel to return at all. For a task explicitly set in an already-populated
  scene, this made the tool's own headline verification method (get the
  whole hierarchy and look at it) unusable, and `find_gameobjects` (which
  does accept a `name` filter) had to substitute for it throughout. Anyone
  relying on the documented "get_scene_hierarchy to see what's there" pattern
  in a non-trivial scene will hit this immediately.
- No friction locating or guessing tool names — `mcp__unity-editor-mcp__*`
  names map closely to their function (`create_gameobject`, `set_transform`,
  `add_component`, `set_component_properties`, `get_component_properties`,
  `find_gameobjects`), and `ToolSearch` surfaced the exact set needed for
  this task on the first query.

## Surprises

- **Shared/reused `instanceId` across distinct objects.** Every
  `create_gameobject` / `set_transform` / `add_component` GameObject-handle
  response in this trial echoed the identical `instanceId` value
  `568105589213729500` — for `T003-Root-B` (step 5), for `T003-Child-B`
  (steps 6-7), and again for the `Transform` *component* handle in step 12
  (which is a different underlying object from either GameObject). The
  `BoxCollider` component handle used a different shared value,
  `568105589213729400`, for both its `add_component` (step 8) and
  `get_component_properties` (steps 10, 11, 15) responses. Meanwhile
  `globalId` and `hierarchyPath` were correct and distinct for every object
  throughout. I did not investigate the mechanism (no `eval` allowed to
  poke Unity's `GetInstanceID()` directly to compare); I only observed that
  `instanceId` is not a trustworthy per-object identifier in this tool's
  responses within a single session, while `hierarchyPath`/`globalId`
  are, and used `hierarchyPath` as the handle for every subsequent call. In
  the affirmative direction: despite this, every call resolved to the
  correct, distinct object — the confusion is cosmetic in the response
  payload, not a mistargeting bug in what the tool actually operated on.
- `create_gameobject`'s `parent` argument accepting a `hierarchyPath` string
  directly (e.g. `"/T003-Root-B"`) worked without needing the object to be
  created and then separately reparented via `set_parent` — one call fewer
  than I expected going in.
- `get_component_properties` on `BoxCollider` surfaces `m_IncludeLayers` and
  `m_ExcludeLayers` as the literal string `"<unsupported:LayerMask>"` rather
  than omitting them or giving a numeric mask. Harmless for this task but
  worth knowing if a future task needs to read or set layer masks through
  this tool — it may not support that property type for either direction.

## Does each mutating call echo the resulting state, or must it be read back separately?

**Mixed, and inconsistent within this one trial.** Evidence:

- `create_gameobject` (steps 5, 6): echoes only `globalId`, `hierarchyPath`,
  `instanceId`, `type` — an *identity* echo, not a *state* echo. No
  transform values, no component list.
- `set_transform` (step 7): echoes the same identity-only shape. The
  `position` value just set does not appear anywhere in the response. This
  call gives **zero** state evidence of its own effect — verification
  requires a separate `get_component_properties` (or hierarchy) read, which
  is exactly what step 12 did.
- `add_component` (step 8): identity-only echo (confirms a component of that
  `type` now exists at that handle) but does not include the new
  component's property values (e.g., default `size`).
- `set_component_properties` (step 11): the one exception — its response
  includes the **entire resulting property map** for the component,
  `m_Size: [2,2,2]` included. This call is genuinely self-verifying.

So the rule in this tool, based on what I saw: property-level mutations
(`set_component_properties`) echo full resulting state; object-level
mutations (`create_gameobject`, `set_transform`, `add_component`) echo only
identity, never state, and must be read back separately to confirm effect.
I did not treat any object-level mutation's return value as evidence of its
effect anywhere in this trial.

## Whether the final state actually verified

**Yes**, confirmed by three read-only calls made after all mutations, none
of which reused a mutating call's own response as evidence:

- Hierarchy/parenting — `find_gameobjects({"name": "T003-Root-B"})` →
  `{"count": 1, "gameObjects": [{"hierarchyPath": "/T003-Root-B", ...}]}`
  and `find_gameobjects({"name": "T003-Child-B"})` →
  `{"count": 1, "gameObjects": [{"hierarchyPath": "/T003-Root-B/T003-Child-B",
  ...}]}` (steps 13-14). Exactly one of each, at the expected nested path —
  no duplicates, no orphaned copy at scene root.

- Local position — `get_component_properties` on the child's `Transform`
  (step 12) → `"m_LocalPosition": [1, 2, 3]`.

- BoxCollider size — `get_component_properties` on the child's
  `BoxCollider`, called fresh after the fix (step 15) →
  `"m_Size": [2, 2, 2]`.

All three acceptance criteria — root name, child name/position, BoxCollider
size — are independently confirmed by read-only calls distinct from the
calls that made the changes. Scene was left dirty; no save call was made at
any point in this trial.
