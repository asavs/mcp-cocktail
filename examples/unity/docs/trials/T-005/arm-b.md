# T-005 arm B — official Unity MCP (`mcp__unity-editor-mcp__*`)

Task: build `T005-Root-B` with a child `T005-Child-B` at local position `(1, 2, 3)`, carrying a
`BoxCollider` sized `(2, 2, 2)`, using only the `mcp__unity-editor-mcp__*` tool family, then
verify by reading the state back.

Result: fully succeeded. 11 tool calls total (10 that touched the Editor plus one that failed
validation and mutated nothing).

## Environment

`editor_status` was the only call that surfaced version information:

```json
{
  "status": "ready",
  "compiling": false,
  "domainReloadInProgress": false,
  "playMode": "stopped",
  "lastHeartbeat": "2026-08-06T21:34:08.7855132Z",
  "projectPath": "C:\\Users\\asas\\UnityProjects\\third-person-multiplayer-gabe",
  "unityVersion": "6000.5.5f1"
}
```

Unity Editor: `6000.5.5f1`. No field anywhere in the tool set I used exposed a version or build
number for the MCP server/package itself — none of the calls I made returned one, and I did not
find a dedicated "server version" tool among the ones loaded.

## Calls, in order, with literal arguments

1. `editor_status()` → the block above.

2. `find_gameobjects(name="T005-Root-B")` — sanity check before creating anything.
   → `{"count": 0, "gameObjects": []}`. No collision, safe to proceed.

3. `create_gameobject(name="T005-Root-B")`
   → 
   ```json
   {
     "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1800002085-0",
     "assetPath": null, "guid": null, "fileId": null,
     "instanceId": 568105589213729400,
     "hierarchyPath": "/T005-Root-B",
     "type": "GameObject"
   }
   ```
   Worked first try. Echoed identity (globalId, hierarchyPath, type, instanceId) only — no
   transform or other state, but there wasn't any non-default state to echo yet.

4. `create_gameobject(name="T005-Child-B", parent="/T005-Root-B")`
   →
   ```json
   {
     "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1795898401-0",
     "assetPath": null, "guid": null, "fileId": null,
     "instanceId": 568105589213729400,
     "hierarchyPath": "/T005-Root-B/T005-Child-B",
     "type": "GameObject"
   }
   ```
   Worked first try, correctly parented by passing the parent's hierarchy path directly to
   `parent`. Note the `instanceId` — see the instanceId section below.

5. `set_transform(target="/T005-Root-B/T005-Child-B", position="[1,2,3]")`
   →
   ```json
   {
     "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1795898401-0",
     "assetPath": null, "guid": null, "fileId": null,
     "instanceId": 568105589213729400,
     "hierarchyPath": "/T005-Root-B/T005-Child-B",
     "type": "GameObject"
   }
   ```
   Worked first try. Response is identical in shape to a plain identity lookup — no position
   values anywhere in it. This is a write that does not echo the resulting state; I had to read
   it back separately later (step 9) to confirm the position actually landed.

6. `add_component(target="/T005-Root-B/T005-Child-B", type="BoxCollider")`
   →
   ```json
   {
     "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1795898403-0",
     "assetPath": null, "guid": null, "fileId": null,
     "instanceId": 568105589213729400,
     "hierarchyPath": "/T005-Root-B/T005-Child-B",
     "type": "BoxCollider"
   }
   ```
   Worked first try (default `BoxCollider`, default size `(1,1,1)`, not yet what's wanted).
   Again only identity — no `m_Size`/`size` fields in the response at all.

7. `set_component_properties(target="/T005-Root-B/T005-Child-B", type="BoxCollider", properties={"size": [2,2,2]})`
   → **Failed.** Literal error text:
   ```
   Error: Pipeline server returned 400 Bad Request: Parameter Validation Failed. Component 'BoxCollider' has no serialized property 'size'.
   ```
   This confirms directly: the public API name `size` does **not** work through this tool. It
   has to be the serialized field name.

8. `set_component_properties(target="/T005-Root-B/T005-Child-B", type="BoxCollider", properties={"m_Size": [2,2,2]})`
   → Succeeded, and this one **did** echo the full resulting state, not just identity:
   ```json
   {
     "component": {
       "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1795898403-0",
       "assetPath": null, "guid": null, "fileId": null,
       "instanceId": 568105589213729400,
       "hierarchyPath": "/T005-Root-B/T005-Child-B",
       "type": "BoxCollider"
     },
     "properties": {
       "m_Material": null,
       "m_IncludeLayers": "<unsupported:LayerMask>",
       "m_ExcludeLayers": "<unsupported:LayerMask>",
       "m_LayerOverridePriority": 0,
       "m_IsTrigger": false,
       "m_ProvidesContacts": false,
       "m_Size": [2, 2, 2],
       "m_Center": [0, 0, 0]
     }
   }
   ```
   `m_Size` reads back as `[2, 2, 2]` right there in the write response. This is the one call
   out of the whole session where the write echoed the actual resulting values rather than just
   an identity block.

9. `get_serialized_fields(target="/T005-Root-B/T005-Child-B", component="Transform")` — read-back
   for the position set in step 5.
   →
   ```json
   {
     "type": "Transform",
     "fields": [
       {"name": "m_LocalRotation", "value": {"x": 0, "y": 0, "z": 0, "w": 1}},
       {"name": "m_LocalPosition", "value": {"x": 1, "y": 2, "z": 3}},
       {"name": "m_LocalScale", "value": {"x": 1, "y": 1, "z": 1}},
       {"name": "m_ConstrainProportionsScale", "value": false}
     ]
   }
   ```
   Confirms local position `(1, 2, 3)`.

10. `get_serialized_fields(target="/T005-Root-B/T005-Child-B", component="BoxCollider")` — read-back
    for the collider size.
    →
    ```json
    {
      "type": "BoxCollider",
      "fields": [
        {"name": "m_Material", "value": null},
        {"name": "m_IncludeLayers", "value": {"unsupported": "LayerMask"}},
        {"name": "m_ExcludeLayers", "value": {"unsupported": "LayerMask"}},
        {"name": "m_LayerOverridePriority", "value": 0},
        {"name": "m_IsTrigger", "value": false},
        {"name": "m_ProvidesContacts", "value": false},
        {"name": "m_Size", "value": {"x": 2, "y": 2, "z": 2}},
        {"name": "m_Center", "value": {"x": 0, "y": 0, "z": 0}}
      ]
    }
    ```
    Confirms `m_Size = (2, 2, 2)`.

11. `find_gameobjects(hierarchy_path="/T005-Root-B/T005-Child-B")` — final identity/hierarchy
    check.
    →
    ```json
    {
      "count": 1,
      "gameObjects": [{
        "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1795898401-0",
        "assetPath": null, "guid": null, "fileId": null,
        "instanceId": 568105589213729400,
        "hierarchyPath": "/T005-Root-B/T005-Child-B",
        "type": "GameObject"
      }]
    }
    ```
    Confirms the child exists at the expected path, still parented correctly, one object found.

## The `size` vs `m_Size` question

Tried `size` first as instructed. It fails outright and does not silently apply a default or do
nothing quietly — the tool rejects the call with a clear 400 and names the offending property:
`Component 'BoxCollider' has no serialized property 'size'.` No stray object or partial state
was created by the failed attempt; nothing changed until the follow-up call with `m_Size`
succeeded. So: no, `size` does not work here, only `m_Size` does, and the failure mode is
loud and specific rather than silent.

## State-echo tally

Six mutating calls were attempted; one failed validation and changed nothing, leaving five
calls that actually mutated the scene:

1. `create_gameobject` (root) — identity only.
2. `create_gameobject` (child) — identity only.
3. `set_transform` — identity only, no position values.
4. `add_component` — identity only, no default-property values.
5. `set_component_properties` with `m_Size` — **echoed the resulting state** (all eight
   serialized properties, including the new `m_Size`).

Echoed state on 1 of 5 successful mutating calls. (A sixth attempt, `set_component_properties`
with `size`, failed outright and echoed nothing but an error message.)

## instanceId

Every single object and component touched in this session — the root GameObject, the child
GameObject, the BoxCollider component, and the child GameObject again when re-queried at the
end — reported the exact same `instanceId`, verbatim as it appeared in the JSON response body:

```
568105589213729400
```

That one string appeared five separate times across four distinct real objects: the root GO
(step 3), the child GO (steps 4 and 11 — consistent with each other since it's the same object,
which is expected), the child GO's own identity block embedded in the `set_transform` response
(step 5), and the BoxCollider component (steps 6 and 8). The BoxCollider is a genuinely
different object from either GameObject and still produced the identical `instanceId` string.
This is not a case of two objects merely landing close together — it's every object in the
session collapsing onto the same displayed value.

Notably, the tool's JSON response emits `instanceId` as a bare numeric literal (`568105589213729400`,
unquoted), not a string. That value is roughly `5.68 × 10^17`, far beyond `2^53` (~`9.007 × 10^15`)
where IEEE-754 double precision stops representing integers exactly. Because the value is already
a bare JSON number by the time it reaches this report, whatever precision loss occurs from
rounding to the nearest representable double has already happened upstream of anything I could
control — I cannot tell from here whether the underlying engine-side instanceIds actually differed
and were rounded onto the same double, or whether something else is going on. Either way, the
practical result matches the concern precisely: `instanceId` should not be used to distinguish
these objects. `globalId` and `hierarchyPath` stayed distinct and reliable throughout — e.g. the
root's globalId ends in `-1800002085-0`, the child's in `-1795898401-0`, and the BoxCollider's in
`-1795898403-0`.

## Friction and surprises

- Parenting worked cleanly by passing a hierarchy path string (`/T005-Root-B`) directly as the
  `parent` argument to `create_gameobject` — no separate lookup needed to get a handle first.
- `find_gameobjects` with `hierarchy_path` was a convenient exact-match verification tool and
  avoided ever needing the unfiltered, depth-unlimited hierarchy dump.
- The split between "mutate" tools (`create_gameobject`, `set_transform`, `add_component`,
  `set_component_properties`) and "read" tools (`get_serialized_fields`,
  `get_component_properties`) is consistent and predictable, but as shown above, only one of the
  five successful mutating calls actually returned the values it had just set — every read had
  to be double-checked with a dedicated follow-up call to be sure the write landed, which is what
  steps 9–11 were for.
- The single biggest surprise was the instanceId collision reproducing exactly as described,
  and doing so across every object touched in the session rather than intermittently — it wasn't
  a rare edge case, it happened on the very first two objects created and stayed constant for
  the rest of the run.
- No compile errors, no domain reload, no scene save was triggered by any of this — `editor_status`
  before and the absence of any reload/compile fields changing throughout confirms the whole
  sequence stayed inside a single stable Editor state.

## Final verified state

- `T005-Root-B` exists at hierarchy path `/T005-Root-B`.
- `T005-Child-B` exists at `/T005-Root-B/T005-Child-B`, local position `(1, 2, 3)` per the
  `Transform.m_LocalPosition` read-back in step 9.
- `T005-Child-B` carries a `BoxCollider` with `m_Size = (2, 2, 2)` per the read-back in step 10.

Task fully succeeded; the object graph was left in place and neither the scene nor the Editor
was touched beyond what's described above.
