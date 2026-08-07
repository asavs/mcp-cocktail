# T-005 Arm C

Tools used: `mcp__UnityMCP__*` (the CoplayDev MCPForUnity server), plus its resources reached
via `ReadMcpResourceTool` / `ListMcpResourcesTool`. No other Unity tooling was touched.

## Task

In the currently open scene (`Assets/Game/Worlds/OldForest/Scenes/OldForest MultiplayerSession.unity`):
create a root empty GameObject named `T005-Root-C`, a child empty named `T005-Child-C` under
it at local position `(1, 2, 3)`, and give the child a `BoxCollider` with size `(2, 2, 2)`.
This fully succeeded and was verified by reading the state back after every mutation.

## Calls, in order, with literal arguments and literal results

**1. `manage_gameobject`**, `action="create"`, `name="T005-Root-C"`.
Result: `success: true`, and the response body was the object's full serialized state, not
just a name/id:

```
{"name":"T005-Root-C","instanceID":-28066,"tag":"Untagged","layer":0,"activeSelf":true,
"activeInHierarchy":true,"isStatic":false,
"scenePath":"Assets/Game/Worlds/OldForest/Scenes/OldForest MultiplayerSession.unity",
"transform":{"position":{"x":0,"y":0,"z":0},"localPosition":{"x":0,"y":0,"z":0},
"rotation":{...},"localRotation":{...},"scale":{"x":1,"y":1,"z":1},...},
"parentInstanceID":0,"componentNames":["UnityEngine.Transform"]}
```

Worked first try. `instanceID` was `-28066`.

**2. `manage_gameobject`**, `action="create"`, `name="T005-Child-C"`, `parent="T005-Root-C"`,
`position=[1, 2, 3]`.
Result: `success: true`, again with the full transform echoed:

```
"transform":{"position":{"x":1,"y":2,"z":3},"localPosition":{"x":1,"y":2,"z":3},...},
"parentInstanceID":-28066,"componentNames":["UnityEngine.Transform"]
```

Worked first try, and since the parent sits at world origin, this one call doesn't by itself
prove `position` was interpreted as local rather than world — that's confirmed later in the
read-back (step 6). `instanceID` was `-28076`. Note the `parentInstanceID` on the child
(`-28066`) matches the root's own `instanceID` from step 1 exactly, character for character —
no collision between these two IDs.

**3. `manage_components`**, `action="add"`, `target="T005-Child-C"`, `search_method="by_name"`,
`component_type="BoxCollider"`.
Result: `success: true`:

```
{"instanceID":-28076,"componentType":"UnityEngine.BoxCollider","componentInstanceID":-28090}
```

Worked first try. This response is identity-only — the GameObject's instance ID, the
component type name, and the new component's own instance ID (`-28090`). It does not say what
`size` or `center` the new collider actually has (Unity defaults a fresh BoxCollider to size
`(1,1,1)`, but the tool doesn't tell you that — you'd have to already know or go read it).

**4. `manage_components`**, `action="set_property"`, `target="T005-Child-C"`,
`search_method="by_name"`, `component_type="BoxCollider"`, `property="size"`,
`value=[2, 2, 2]`.
Result: `success: true`:

```
{"instanceID":-28076}
```

**This is the important result: `size` — the public C# API name, not the serialized
`m_Size` — worked on the first try, with no fallback needed.** The response itself is
identity-only (just the GameObject's instance ID again), so this call alone doesn't prove the
value stuck; that's confirmed in step 5.

**5. `ReadMcpResourceTool`**, server `UnityMCP`, uri
`mcpforunity://scene/gameobject/-28076/component/BoxCollider`.
Result:

```
{"success":true,"data":{"gameObjectID":-28076,"gameObjectName":"T005-Child-C",
"component":{"typeName":"UnityEngine.BoxCollider","instanceID":-28090,
"properties":{"center":{"x":0.0,"y":0.0,"z":0.0},"size":{"x":2.0,"y":2.0,"z":2.0},
"enabled":true,...,"bounds":{"center":{"x":1.0,"y":2.0,"z":3.0},
"size":{"x":2.0,"y":2.0,"z":2.0}},...,
"material":{"name":"","instanceID":-28094,"entityID":"568105589213729346"},
"gameObject":{"name":"T005-Child-C","instanceID":-28076,
"entityID":"568105589213729364"},...}}}
```

This is the proof: `size` is genuinely `(2, 2, 2)` on the live component, set via the plain
`size` property name. Note this response carries two different ID systems for the same
GameObject at once: `instanceID: -28076` (small, session-local, matches everything else so
far) and a `gameObject.entityID: "568105589213729364"` (an 18-digit string — this is the
`GetEntityId()` value the brief warns rounds under naive JSON number parsing; recorded here
verbatim as a string, not compared numerically). Its sibling `material.entityID` is
`"568105589213729346"` — an 18-digit string only two digits different from the gameObject's,
but not the same value; no collision observed between the two.

**6. `ReadMcpResourceTool`**, uri `mcpforunity://scene/gameobject/-28076` (the child, by
instance ID).
Result:

```
{"success":true,"data":{"instanceID":-28076,"name":"T005-Child-C","tag":"Untagged",
"layer":0,"layerName":"Default","active":true,"activeInHierarchy":true,"isStatic":false,
"transform":{"position":{"x":1.0,"y":2.0,"z":3.0},"localPosition":{"x":1.0,"y":2.0,"z":3.0},
"rotation":{...},"localRotation":{...},"scale":{"x":1.0,"y":1.0,"z":1.0},
"lossyScale":{"x":1.0,"y":1.0,"z":1.0}},"parent":-28066,"children":[],
"componentTypes":["Transform","BoxCollider"],"path":"T005-Root-C/T005-Child-C"}}
```

This is the read-back that actually settles local vs. world position: `localPosition` is
`(1, 2, 3)` and `position` (world) is also `(1, 2, 3)` only because the parent is at the
origin — but the field is explicitly present and correct either way, and the hierarchy path
`T005-Root-C/T005-Child-C` confirms parentage independent of any ID.

**7. `ReadMcpResourceTool`**, uri `mcpforunity://scene/gameobject/-28066` (the root, by
instance ID), run in parallel with step 6.
Result:

```
{"success":true,"data":{"instanceID":-28066,"name":"T005-Root-C","tag":"Untagged",
"layer":0,"layerName":"Default","active":true,"activeInHierarchy":true,"isStatic":false,
"transform":{"position":{"x":0.0,"y":0.0,"z":0.0},"localPosition":{"x":0.0,"y":0.0,"z":0.0},
...},"parent":null,"children":[-28076],
"componentTypes":["Transform"],"path":"T005-Root-C"}}
```

Root confirmed at the scene origin with the child listed as its only child by instance ID.
This is the final, complete proof of the required state: `T005-Root-C` exists with a
`Transform` only; `T005-Child-C` is its child at local `(1, 2, 3)` with a `BoxCollider` of
size `(2, 2, 2)`.

The remaining calls were not part of building the objects — they were spent chasing the
version-number and instance-ID questions below.

**8. `ReadMcpResourceTool`**, uri `mcpforunity://instances`.
Result:

```
{"success": true, "transport": "http", "instance_count": 1,
"instances": [{"id": "third-person-multiplayer-gabe@533741449a7ee5ed",
"name": "third-person-multiplayer-gabe", "hash": "533741449a7ee5ed",
"unity_version": "6000.5.5f1", "connected_at": "2026-08-06T21:37:17.096160+00:00",
"session_id": "ebd876fe-92dd-4c25-90c9-cf496f520cbe"}]}
```

Only one Unity instance connected, so no instance-targeting was needed for anything above.

**9. `manage_editor`**, `action="telemetry_status"`, run in parallel with step 8.
Result: `{"success":true,"telemetry_enabled":true}`. No version information in this one.

**10. `ReadMcpResourceTool`**, uri `mcpforunity://custom-tools`.
Result: a list of 34 tool names available for this project (`project_id":"533741449a7ee5ed"`,
matching the hash in step 8), each entry just a name/description/polling-metadata stub — no
version field anywhere in it.

**11. `ListMcpResourcesTool`**, server `UnityMCP` (no other arguments).
Result: the full list of 18 named resources this server exposes (`editor_state`,
`project_info`, `unity_instances`, `custom_tools`, `gameobject_api`, etc.), each with a
`mcpforunity://...` URI and description. No version field on this listing either.

**12. `ReadMcpResourceTool`**, uri `mcpforunity://project/info`, run in parallel with step 13.
Result:

```
{"success":true,"data":{"projectRoot":"C:/Users/asas/UnityProjects/third-person-multiplayer-gabe",
"projectName":"third-person-multiplayer-gabe","unityVersion":"6000.5.5f1",
"platform":"StandaloneWindows64",
"assetsPath":"C:/Users/asas/UnityProjects/third-person-multiplayer-gabe/Assets"}}
```

**13. `ReadMcpResourceTool`**, uri `mcpforunity://editor/state`.
Result (trimmed):

```
{"success":true,"data":{"schema_version":"unity-mcp/editor_state@2",
"observed_at_unix_ms":1786052291290,"sequence":7,
"unity":{"instance_id":"third-person-multiplayer-gabe@533741449a7ee5ed",
"unity_version":"6000.5.5f1","project_id":null,"platform":"WindowsEditor",
"is_batch_mode":false},"editor":{...,"active_scene":{
"path":"Assets/Game/Worlds/OldForest/Scenes/OldForest MultiplayerSession.unity",...}},
...,"advice":{"ready_for_tools":true,"blocking_reasons":[],...},...}}
```

This surfaces a version string of its own — `"unity-mcp/editor_state@2"` — which is a schema
version for this one resource's response shape, distinct from both the Unity Editor version
and the package version.

**14. `read_console`**, `action="get"`, `count="20"`, `types=["error","warning"]`.
Result: 8 entries. None of them were caused by this arm's own calls — the tool names named in
them (`set_transform`, `set_serialized_field`, `set_component_properties`) belong to a
different MCP server's vocabulary, not `mcp__UnityMCP__*`'s (this server's equivalents are
`manage_gameobject` and `manage_components`, which is what was actually called above). The
Unity console is shared editor-wide, so these are residue from other tooling that touched this
same Editor session, not anything produced here. Recorded verbatim since they were genuinely
present in the console at read time:

```
Editor is not in automated mode. Modal Pop up might break continuous command workflow.
  Start the editor with -automated
Failed to convert parameter 'position' to Single[]: Error converting value "1,2,3" to type
  'System.Single[]'. Path 'position'.
Failed to convert parameter 'position' to Single[]: Error converting value 1 to type
  'System.Single[]'. Path 'position'.
Command 'set_transform' failed: Could not resolve 'target': No loaded object with
  instanceId 2.
Command 'set_serialized_field' failed: Field 'size' was not found on 'BoxCollider'. Use a
  SerializedProperty path (e.g. 'speed', 'settings.speed', 'items.Array.data[0]').
Command 'set_serialized_field' failed: Expected a JSON object with named components
  (e.g. { "x": 0 }) but received a 'Array'.
Command 'set_component_properties' failed: Component 'BoxCollider' has no serialized
  property 'size'.
MCP-FOR-UNITY: [GameObjectSerializer] Unexpected error serializing value of type
  UnityEngine.TransformHandle: System.NullReferenceException: The TransformHandle object is
  null. ...
```

No errors or warnings attributable to any call made here.

Two local filesystem checks (not Editor calls, not counted in the step total) were also done
to chase the package-version question, since none of the 14 Editor-facing calls above surfaced
one:

- `Packages/packages-lock.json` pins `com.coplaydev.unity-mcp` to
  `"https://github.com/CoplayDev/unity-mcp.git?path=/MCPForUnity#v10.0.0"`.
- The resolved package cache directory is
  `Library/PackageCache/com.coplaydev.unity-mcp@7b7db7b31f4e`, and its own `package.json`
  reports `"version": "10.0.0"` — consistent with the lockfile, not contradicting it.

## Step count

14 tool invocations against the Editor (4 `manage_gameobject`/`manage_components` mutations, 8
`ReadMcpResourceTool` reads, 1 `ListMcpResourcesTool`, 1 `manage_editor`, 1 `read_console`).
Two additional local file reads (lockfile and cached package.json) are not counted since they
never reached the Editor.

## Answers to the specific open questions

**Does BoxCollider size need `m_Size`, or does `size` work?** `size` — the plain public API
name — worked on the very first try via `manage_components` `set_property`
(`property="size"`, `value=[2,2,2]`), and the read-back in step 5 confirmed the live component
actually has `size: {x:2, y:2, z:2}`. `m_Size` was never tried because it was never needed.
This differs from what's on record for the other two arms, which reportedly require the
serialized name.

**State-echo tally.** 4 mutating calls total. 2 of 4 echoed the resulting state in full (both
`manage_gameobject create` calls returned the complete transform, tags, layer, component list,
etc.). The other 2 (`manage_components add`, `manage_components set_property`) echoed only
identity — an instance ID and, for `add`, the component type name — never the property values
actually applied. So: **echoed state on 2 of 4 mutating calls.**

**instanceId values, verbatim as strings, and collisions.** Small session-local instance IDs
seen: root GameObject `"-28066"`, child GameObject `"-28076"`, BoxCollider component
`"-28090"`, its default Material `"-28094"`. All four are distinct; no collisions among them.
Separately, the component read-back also carried large `entityID` strings for the same two
objects: GameObject `"568105589213729364"` and Material `"568105589213729346"` — also
distinct from each other, no collision observed. These `entityID` values are the ones large
enough (>2^53) that naive numeric JSON parsing could round them; they were compared here as
strings, not numbers, and found not to collide in this run.

**Version numbers, each with its source.**
- `6000.5.5f1` — Unity Editor version. Reported identically by three independent sources:
  `mcpforunity://instances` (`instances[0].unity_version`), `mcpforunity://project/info`
  (`unityVersion`), and `mcpforunity://editor/state` (`unity.unity_version`).
- `10.0.0` — the CoplayDev MCPForUnity package version. Reported by two sources that agree:
  `Packages/packages-lock.json` (pinned git tag `v10.0.0`) and the resolved
  `Library/PackageCache/com.coplaydev.unity-mcp@7b7db7b31f4e/package.json`
  (`"version": "10.0.0"`). No tool call surfaced this number directly — it required reading
  local project files, since neither `mcpforunity://custom-tools` (34 tools, no version field)
  nor `ListMcpResourcesTool` (18 resources, no version field) nor `manage_editor
  telemetry_status` exposed it.
- `unity-mcp/editor_state@2` — a schema version specific to the `mcpforunity://editor/state`
  resource's response shape (`schema_version` field), unrelated to either number above.

No fourth version number was found. Nothing here contradicts the on-record claim that the
installed package is `v10.0.0` — both places that state a package version agree it's 10.0.0.

## Friction and surprises

- The biggest surprise was that `size` worked at all, given the explicit prior finding that
  Unity's serialized name is required elsewhere. It's possible this server does its own
  property-name translation (public API name to serialized property) internally before
  handing off to Unity's `SerializedProperty` API, where the other tooling apparently does
  not.
- Getting any version number out of the running tools themselves was surprisingly hard: three
  separate resources (`custom-tools`, `tool_groups`/`ListMcpResourcesTool`, and
  `telemetry_status`) were checked and none carry a package or server version, only the Unity
  Editor version and, incidentally, a resource schema version. The only way to get the package
  version was to step outside the MCP tools entirely and read the project's own package
  manifest and lockfile.
- Component-adding and property-setting calls returning identity-only responses means a script
  that trusts the "success" result without a follow-up read has no way to know if `size` had
  silently been ignored, clamped, or misspelled — the read-back resource calls were the only
  thing that actually proved the value took.
- The stale console entries from a different tool vocabulary (`set_transform`,
  `set_serialized_field`) were a reminder that `read_console` is scoped to the whole Editor
  session, not to the calls made by whichever client is currently reading it — worth knowing
  before treating anything in that log as self-diagnostic.
