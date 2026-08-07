# T-004, arm A — building a small hierarchy with the `unity` CLI

## What was built

In the already-open scene `Assets/Game/Worlds/OldForest/Scenes/OldForest MultiplayerSession.unity`:

- `/T004-Root-A` — empty GameObject at scene root
- `/T004-Root-A/T004-Child-A` — empty child, local position `(1, 2, 3)`
- a `BoxCollider` on the child with size `(2, 2, 2)`

Nothing was saved, and the Editor was not opened, closed, or restarted.

## Versions observed

| Thing | Value |
|---|---|
| `unity --version` | `1.0.0-beta.3` |
| Editor (from `unity status --json`) | `6000.5.5f1` |
| Editor PID / port | `19092` / `7800` |
| Tools advertised by `unity list --json` | 140 |

## Environment

Run from Git Bash with:

```
export PATH="$PATH:/c/Users/asas/AppData/Local/Unity/bin"
export MSYS_NO_PATHCONV=1
```

`MSYS_NO_PATHCONV=1` is not optional. Every hierarchy path this API takes begins with `/`, and
MSYS will otherwise rewrite `/T004-Root-A` into a Windows path such as
`C:/Program Files/Git/T004-Root-A` before the CLI ever sees it. With the variable set, the
argument arrives intact — you can confirm this yourself because every response echoes the
parameters it received.

Exit codes were captured as `out=$(cmd 2>&1); code=$?` so that a failing command's status was
not masked by a pipeline.

## Total: 23 CLI invocations

Six of orientation (`--version`, `--help`, `status`, `list`, `command --help`,
`list_open_scenes`), then 17 `unity command` calls. Eight of those 17 were mutating attempts;
five of the eight actually changed anything.

## Every call, in order

### Orientation

```
unity --version
unity --help
unity status --json
unity list --json
unity command --help
unity command list_open_scenes --json
```

`unity command --help` prints generic usage for the `command` subcommand — arguments, timeout,
global flags — and says nothing about any individual tool. The only real schema source is the
`parameters` array inside `unity list --json`. That output is ~115 KB, so it is worth dumping it
to a file and filtering rather than reading it inline. The fields that matter per parameter are
`name`, `type`, and `required`. The `type` values you will meet here are `string`, `bool`,
`objectref`, `single[]`, `jobject`, and `jtoken` — and, as shown below, the last three do not all
accept the same encoding on the command line.

### Pre-check and creation

```
unity command find_gameobjects --name T004-Root-A --json
```
→ `"count": 0`. Nothing pre-existing to collide with.

```
unity command create_gameobject --name T004-Root-A --json
```
→ succeeded first try. Result:

```json
"result": {
  "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1617077174-0",
  "assetPath": null, "guid": null, "fileId": null,
  "instanceId": 568105589213729300,
  "hierarchyPath": "/T004-Root-A",
  "type": "GameObject"
}
```

```
unity command create_gameobject --name T004-Child-A --parent /T004-Root-A --json
```
→ succeeded first try; `"hierarchyPath": "/T004-Root-A/T004-Child-A"`. Passing a hierarchy path
string where the schema says `objectref` works fine; there is no need to construct a handle
object.

### Setting the local position — three attempts

The schema says `position` is `single[]`, "Local position as [x,y,z]". Getting an array across
the command line took three tries.

**Attempt 1 — comma-separated:**

```
unity command set_transform --target /T004-Root-A/T004-Child-A --position 1,2,3 --json
```

Exit code 0, `"success": true`, and the echoed parameters show `"position": "1,2,3"` — a string,
not an array. The result block was identity only. A read-back:

```
unity command get_serialized_fields --target /T004-Root-A/T004-Child-A --component Transform --field m_LocalPosition --json
```
→ `"value": { "x": 0, "y": 0, "z": 0 }`

So the write reported success and did nothing.

**Attempt 2 — repeated flag:**

```
unity command set_transform --target /T004-Root-A/T004-Child-A --position 1 --position 2 --position 3 --json
```

Again exit 0 and `"success": true`. The echo shows `"position": 3` — repeating the flag does not
build an array, it just lets the last occurrence win, and the value arrives as a bare number.
Read-back again returned `{ "x": 0, "y": 0, "z": 0 }`. Second silent no-op.

**Attempt 3 — JSON array as a single quoted argument:**

```
unity command set_transform --target /T004-Root-A/T004-Child-A --position '[1,2,3]' --json
```

Echo shows `"position": "[1,2,3]"` — still a JSON *string* in the echo — but this time the
server parsed it. Read-back:

```json
"fields": [
  {
    "name": "m_LocalPosition",
    "path": "m_LocalPosition",
    "propertyType": "Vector3",
    "value": { "x": 1, "y": 2, "z": 3 }
  }
]
```

The lesson: array-typed parameters want a JSON literal in one shell argument. The parameter echo
is not a reliable signal of whether it parsed, because the echo shows the raw string in both the
working and the non-working case.

### The BoxCollider

```
unity command add_component --target /T004-Root-A/T004-Child-A --type BoxCollider --json
```
→ succeeded first try; result identity `"type": "BoxCollider"`,
`"globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1532777301-0"`.

**Setting the size — first attempt, by analogy with the position that had just worked:**

```
unity command set_serialized_field --target /T004-Root-A/T004-Child-A --component BoxCollider --field m_Size --value '[2,2,2]' --json
```

This one failed loudly, which was a relief after the silent no-ops. Exit code **6**:

```json
{
  "success": false,
  "command": "unity command set_serialized_field",
  "data": null,
  "errors": [
    {
      "code": "COMMAND_FAILED",
      "message": "Pipeline server returned 400 Bad Request: Parameter Validation Failed. Expected a JSON object with named components (e.g. { \"x\": 0 }) but received a 'Array'."
    }
  ],
  "warnings": []
}
```

A read-back confirmed `m_Size` was still `{ "x": 1, "y": 1, "z": 1 }`, i.e. the failure was clean
and partial state was not written.

**Second attempt, object form:**

```
unity command set_serialized_field --target /T004-Root-A/T004-Child-A --component BoxCollider --field m_Size --value '{"x":2,"y":2,"z":2}' --json
```
→ exit 0, `"success": true`, identity-only result.

So two vector-valued parameters on two neighbouring tools want two different JSON encodings:
`set_transform --position` takes `[1,2,3]` and rejects nothing visibly; `set_serialized_field
--value` for a `Vector3` takes `{"x":2,"y":2,"z":2}` and rejects the array with a 400. Neither
tool's `parameters` entry in `unity list --json` says which. `set_transform` says "Local position
as [x,y,z]", which is the array hint; `set_serialized_field` says only "JSON value to assign".

Note also that the serialized field name is `m_Size`. The public C# property is `size`; that name
does not resolve here.

## Did mutating calls echo state?

No. Not one of them.

`create_gameobject`, `set_transform`, `add_component`, and `set_serialized_field` all return the
same shape: a `result` object containing `globalId`, `assetPath`, `guid`, `fileId`, `instanceId`,
`hierarchyPath`, `type`. That is an identity handle and nothing else. There is no position in the
`set_transform` response and no size in the `set_serialized_field` response. `"success": true`
means "the request was accepted", not "the value you intended is now in the scene" — the two
silent position no-ops above returned exactly the same success-shaped payload as the write that
worked.

Every value in this report therefore came from a **separate read call**. Budget one read per
write. Of the 17 `unity command` calls, 6 existed purely to find out what the previous call had
actually done.

`find_gameobjects` and `get_serialized_fields` are the useful readers.
`get_component_properties` gives a fuller picture of one component in a single call and is the
better choice for a final check.

## Surprises and friction

**Silent success on a malformed argument is the main hazard.** Two consecutive `set_transform`
calls returned exit 0 and `"success": true` while changing nothing. Had I trusted the exit code,
I would have reported a finished hierarchy with the child sitting at the origin. The CLI does not
type-check `single[]` parameters before shipping them, and the server appears to drop what it
cannot coerce rather than reject it. The same tolerance means a mistyped flag name is likely to
vanish without complaint too — assume `--flag value` is the only binding form, and verify.

**`--json` is forwarded to the tool as a parameter.** Every response echoes
`"parameters": { ..., "json": true }`. The tools ignore it, but it is a reminder that the CLI
does not filter its own flags out of the parameter map, so a tool that happened to define a
`json` parameter would behave oddly.

**`instanceId` is unusable, and its output is also lossy.** The root GameObject, the child
GameObject, and the child's `Transform` component all report
`"instanceId": 568105589213729300`; the `BoxCollider` reports `568105589213729200`. These are
distinct objects. Two things are going on. First, this field is `Object.GetEntityId()` surfaced
under a legacy name and does not identify what its name suggests. Second, the values exceed
2^53, so JSON number parsing rounds them — the trailing `300` and `200` are artifacts of double
precision, not real values, and any round-trip through a JSON parser will corrupt them further.
Use `globalId` or `hierarchyPath`. Both were stable across every call in this run, and
`globalId` did correctly differ per object:

- `/T004-Root-A` → `...-1617077174-0`
- `/T004-Root-A/T004-Child-A` → `...-1532777299-0`
- its `Transform` → `...-1532777300-0`
- its `BoxCollider` → `...-1532777301-0`

**`get_component_properties` cannot render every type.** Its output includes
`"m_LocalRotation": "<unsupported:Quaternion>"`. It reports positions and scales as arrays
(`[1,2,3]`), while `get_serialized_fields` reports the same Vector3 as an object
(`{"x":1,"y":2,"z":3}`). Two readers, two encodings, on the same underlying field.

**What worked first try:** `create_gameobject` (both the root and the parented child),
`add_component`, and every read. Parenting at creation time via `--parent` worked, so no separate
`set_parent` call was needed.

**What did not:** the local position, which took three encodings; and the collider size, which
took two.

## Final read-back

Transform of the child, in full:

```
unity command get_component_properties --target /T004-Root-A/T004-Child-A --type Transform --json
```

```json
"result": {
  "component": {
    "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1532777300-0",
    "assetPath": null,
    "guid": null,
    "fileId": null,
    "instanceId": 568105589213729300,
    "hierarchyPath": "/T004-Root-A/T004-Child-A",
    "type": "Transform"
  },
  "properties": {
    "m_LocalRotation": "<unsupported:Quaternion>",
    "m_LocalPosition": [
      1,
      2,
      3
    ],
    "m_LocalScale": [
      1,
      1,
      1
    ],
    "m_ConstrainProportionsScale": false
  }
}
```

Collider size:

```
unity command get_serialized_fields --target /T004-Root-A/T004-Child-A --component BoxCollider --field m_Size --json
```

```json
"result": {
  "type": "BoxCollider",
  "fields": [
    {
      "name": "m_Size",
      "path": "m_Size",
      "propertyType": "Vector3",
      "isArray": false,
      "arrayLength": null,
      "value": {
        "x": 2,
        "y": 2,
        "z": 2
      }
    }
  ]
}
```

Uniqueness and placement — one root, one child, and the child's `hierarchyPath` proves the
parenting:

```
unity command find_gameobjects --name T004-Root-A --json
```

```json
"result": {
  "count": 1,
  "gameObjects": [
    {
      "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1617077174-0",
      "instanceId": 568105589213729300,
      "hierarchyPath": "/T004-Root-A",
      "type": "GameObject"
    }
  ]
}
```

```
unity command find_gameobjects --name T004-Child-A --json
```

```json
"result": {
  "count": 1,
  "gameObjects": [
    {
      "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1532777299-0",
      "instanceId": 568105589213729300,
      "hierarchyPath": "/T004-Root-A/T004-Child-A",
      "type": "GameObject"
    }
  ]
}
```

`count: 1` on both names confirms the three failed write attempts did not leave duplicates
behind — they targeted an existing object rather than creating one, so the silent failures cost
time but no stray scene objects.
