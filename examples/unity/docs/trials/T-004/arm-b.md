# T-004, arm B: creating a parented object with a sized collider through the Unity Editor MCP

Tooling: the `unity-editor-mcp` MCP server only. No CLI, no other MCP server.

## Versions actually observed

Reported by `editor_status` at the start of the run:

```json
{
  "status": "ready",
  "compiling": false,
  "domainReloadInProgress": false,
  "playMode": "stopped",
  "lastHeartbeat": "2026-08-06T19:13:15.4782434Z",
  "projectPath": "C:\\Users\\asas\\UnityProjects\\third-person-multiplayer-gabe",
  "unityVersion": "6000.5.5f1"
}
```

Unity 6000.5.5f1. The MCP server does not report its own version through any tool I called; `editor_status` returns editor state only, so the server build is unknown from inside the session.

The open scene, from `list_open_scenes`: `OldForest MultiplayerSession` at
`Assets/Game/Worlds/OldForest/Scenes/OldForest MultiplayerSession.unity`, 14 root objects, already dirty before I touched anything.

## Every call, in order

Two of these are schema loads rather than editor calls: the tools in this server are exposed lazily, so their parameter schemas have to be fetched before any of them can be invoked. That is a real cost of the first call but not of subsequent ones.

0a. Schema load: `create_gameobject`, `find_gameobjects`, `add_component`, `set_component_properties`, `get_component_properties`
0b. Schema load: `editor_status`, `list_open_scenes`, `set_transform`, `set_parent`, `get_serialized_fields`

1. `editor_status` — no arguments. Output quoted above.

2. `list_open_scenes` — no arguments. Output summarized above.

3. `create_gameobject` with `name: "T004-Root-B"` (no `parent`, no `primitive`):

```json
{
  "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-17752553-0",
  "assetPath": null, "guid": null, "fileId": null,
  "instanceId": 568105589213729200,
  "hierarchyPath": "/T004-Root-B",
  "type": "GameObject"
}
```

4. `create_gameobject` with `name: "T004-Child-B"`, `parent: "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-17752553-0"`:

```json
{
  "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-780622362-0",
  "assetPath": null, "guid": null, "fileId": null,
  "instanceId": 568105589213729200,
  "hierarchyPath": "/T004-Root-B/T004-Child-B",
  "type": "GameObject"
}
```

5. `set_transform` with `target: "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-780622362-0"`, `position: "[1, 2, 3]"`. Response was the same identity block as step 4 — no transform values in it.

6. `add_component` with `target: "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-780622362-0"`, `type: "BoxCollider"`:

```json
{
  "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-780622364-0",
  "assetPath": null, "guid": null, "fileId": null,
  "instanceId": 568105589213729200,
  "hierarchyPath": "/T004-Root-B/T004-Child-B",
  "type": "BoxCollider"
}
```

7. `set_component_properties` with `target: "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-780622364-0"`, `properties: "{\"m_Size\": [2, 2, 2]}"`. This one returned the full post-write property map (quoted in the read-back section).

8. `find_gameobjects` with `name: "T004-Root-B"` — `count: 1`.

9. `find_gameobjects` with `hierarchy_path: "/T004-Root-B/T004-Child-B"` — `count: 1`.

10. `get_component_properties` with `target: <child globalId>`, `type: "Transform"`.

11. `get_component_properties` with `target: <child globalId>`, `type: "BoxCollider"`.

**Step count: 11 editor calls, plus 2 schema-load calls before the first one. Zero failed calls, zero retries.**

## What worked first try

All of it. There were no errors, so there is no literal error text to reproduce — nothing was tidied away, there was simply nothing to tidy.

Three things in particular went right on the first attempt and are worth calling out because they are the usual places to lose time:

- **Parenting at creation.** `create_gameobject` takes a `parent` handle, so the child never existed at the scene root and never needed reparenting. This sidesteps `set_parent` entirely, and with it the `world_position_stays` question. `set_parent` defaults `world_position_stays` to `true`, which means reparenting *after* setting a local position would have silently rewritten that local position to preserve the world position. Creating the child already-parented and setting the transform afterwards avoids the ordering hazard rather than solving it.
- **`m_Size`, not `size`.** The serialized name is what the property setter wants. This was known going in and did not have to be discovered.
- **Local, not world.** `set_transform` documents `position` as local position, and the read-back confirms it: the value landed in `m_LocalPosition` unchanged. There is no separate world-position parameter on this tool.

## Friction

**Vectors and property maps are declared as `string` in the schemas.** `set_transform.position` has `"type": "string"` with the description "Local position as `[x,y,z]`", and `set_component_properties.properties` is likewise a `string` holding a JSON object. So you pass JSON-encoded *text*, not a JSON array or object: `"[1, 2, 3]"` and `"{\"m_Size\": [2, 2, 2]}"`. Both were accepted as written. Reading the schema literally, rather than assuming the natural JSON type, is what made these work first try; guessing a bare array would have hit a client-side validation error before the call ever reached Unity.

**Reading the hierarchy.** `get_scene_hierarchy` takes no arguments — no filter, no depth limit, no pagination. On a scene with 14 roots and real content it returns more than the tool-result limit allows, so it is unusable for verification here. `find_gameobjects` is the working substitute: it filters by `name`, `tag`, `type`, and `hierarchy_path`, and combines those filters. Filtering by `hierarchy_path` is the useful move for this task, because a hit on the exact path `/T004-Root-B/T004-Child-B` proves the parent relationship in the same call that proves existence.

**Two overlapping readers.** `get_component_properties` and `get_serialized_fields` both read component state. I used the former throughout; the latter additionally reports each field's declared type and can read a single `SerializedProperty` path via its `field` argument. Nothing signals which one to reach for; either would have answered this question.

**`<unsupported:...>` placeholders.** Some field types come back as strings like `"<unsupported:Quaternion>"` and `"<unsupported:LayerMask>"` instead of values. This did not block this task, since position and size are plain vectors, but it means the property map is not a complete picture of a component. If you need to verify a rotation, this reader will not give it to you.

## Surprises

**The `instanceId` collision is real and total.** Every single object in this run — the root GameObject, the child GameObject, the child's Transform, and the child's BoxCollider — reported the *identical* `instanceId`:

```
568105589213729200
```

Four distinct objects, four distinct `globalId`s, one shared `instanceId`. This value is not an identifier in any useful sense; it is `Object.GetEntityId()` surfaced under a legacy name, and it does not discriminate between objects at all here. If you address anything by `instanceId` you are addressing an arbitrary object. Use `globalId` for a stable handle, or `hierarchyPath` when you want something human-readable. Note also that the value exceeds 2^53, so any client that round-trips it through a IEEE-754 double will corrupt it on top of everything else.

The `globalId`s, by contrast, behaved exactly as identifiers should. Note their internal structure: the child GameObject is `...-780622362-0`, its Transform is `...-780622363-0`, and its BoxCollider is `...-780622364-0` — consecutive. Do not rely on that arithmetic; read the handle you are given back from the call that created the thing.

**Mutating calls almost never echo state.** Of the four mutating calls, three returned nothing but the object's identity block — the same `globalId`/`hierarchyPath`/`type` shape you would get from a bare lookup, with no indication of what changed. `set_transform` is the sharpest case: it returned an identity block containing no position at all. A successful-looking response from it is evidence that a call was dispatched, not that a value landed.

The single exception was `set_component_properties`, which returned the component's full post-write property map. That is the behavior every mutating tool in this server ought to have, and it is the one call in this run that self-verified.

| Call | Echoed resulting state? |
| --- | --- |
| `create_gameobject` (root) | No — identity only |
| `create_gameobject` (child) | Partly — `hierarchyPath` does prove the parenting, but no transform |
| `set_transform` | **No** — identity only, no position |
| `add_component` | No — identity only, though the returned handle is the new component |
| `set_component_properties` | **Yes** — full property map after the write |

So three of the four mutations required a separate read to confirm. The one useful accident is that the identity block includes `hierarchyPath`, which encodes the parent chain; that makes the child's creation response weak evidence of correct parenting for free. Nothing else about the desired state is observable from a write response.

## Read-back proving the final state

Existence and parentage, `find_gameobjects` with `name: "T004-Root-B"`:

```json
{
  "count": 1,
  "gameObjects": [
    {
      "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-17752553-0",
      "assetPath": null, "guid": null, "fileId": null,
      "instanceId": 568105589213729200,
      "hierarchyPath": "/T004-Root-B",
      "type": "GameObject"
    }
  ]
}
```

`count: 1` and a `hierarchyPath` of `/T004-Root-B` with no further segments: the root exists exactly once and is genuinely at the scene root.

`find_gameobjects` with `hierarchy_path: "/T004-Root-B/T004-Child-B"`:

```json
{
  "count": 1,
  "gameObjects": [
    {
      "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-780622362-0",
      "assetPath": null, "guid": null, "fileId": null,
      "instanceId": 568105589213729200,
      "hierarchyPath": "/T004-Root-B/T004-Child-B",
      "type": "GameObject"
    }
  ]
}
```

The child is found *by* that exact path, so the parent relationship is confirmed by the query itself.

Local position, `get_component_properties` on the child with `type: "Transform"`:

```json
{
  "component": {
    "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-780622363-0",
    "hierarchyPath": "/T004-Root-B/T004-Child-B",
    "type": "Transform"
  },
  "properties": {
    "m_LocalRotation": "<unsupported:Quaternion>",
    "m_LocalPosition": [1, 2, 3],
    "m_LocalScale": [1, 1, 1],
    "m_ConstrainProportionsScale": false
  }
}
```

`m_LocalPosition` is `[1, 2, 3]` — the serialized *local* field, which is the thing that was asked for, not a world position that happens to coincide.

Collider size, `get_component_properties` on the child with `type: "BoxCollider"`:

```json
{
  "component": {
    "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-780622364-0",
    "hierarchyPath": "/T004-Root-B/T004-Child-B",
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

The component is present on the child (its `hierarchyPath` is the child's) and `m_Size` is `[2, 2, 2]`.

All four requirements are confirmed by reads issued after the writes, not by the writes' own return values.

## Scene state

The scene was not saved and the editor was not opened, closed, restarted, or put into play mode. The scene was already dirty when the run began, so the dirty flag is not a signal that these objects are the only unsaved change in it. The created objects live only in the in-memory scene until someone saves.
