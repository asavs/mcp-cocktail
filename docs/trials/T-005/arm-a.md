# Setting up a parented GameObject with a BoxCollider via the `unity` CLI

Goal: in the currently open Unity scene, create a root empty GameObject named
`T005-Root-A`, a child empty named `T005-Child-A` parented under it at local
position `(1, 2, 3)`, and give the child a `BoxCollider` with `size` `(2, 2, 2)`.
Everything below was done from Git Bash with:

```
export PATH="$PATH:/c/Users/asas/AppData/Local/Unity/bin"
export MSYS_NO_PATHCONV=1
```

`MSYS_NO_PATHCONV=1` is required — without it Git Bash rewrites any argument
starting with `/` (i.e. every hierarchy path) into a Windows path before the
CLI ever sees it.

## Versions observed

- `unity --version` → `1.0.0-beta.3`
- `unity list --json` → `"count": 140` tools under `"group": "built-in"`.

## Finding the real schema

`unity command <tool> --help` does not give per-tool help. Running
`unity command create_gameobject --help` prints the generic top-level usage
block (`Usage: unity command|cmd [options] [command] [args...]` plus the
global `--project-path`, `--runtime`, `--timeout`, `--format`, etc. options) —
nothing about `create_gameobject`'s actual parameters. The real schema has to
come from the `parameters` array of each tool entry in `unity list --json`.

## Step-by-step log

**1. `unity command create_gameobject --name T005-Root-A --json`** — success on
the first try.

```
"result": {
  "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-575762310-0",
  "instanceId": 568105589213729500,
  "hierarchyPath": "/T005-Root-A",
  "type": "GameObject"
}
```

**2. `unity command create_gameobject --name T005-Child-A --parent /T005-Root-A --json`**
— success on the first try; the `--parent` flag took the hierarchy path
directly (`objectref` type accepts a plain path string) and `MSYS_NO_PATHCONV=1`
kept `/T005-Root-A` from being mangled into a Windows path.

```
"result": {
  "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1660226900-0",
  "instanceId": 568105589213729500,
  "hierarchyPath": "/T005-Root-A/T005-Child-A",
  "type": "GameObject"
}
```

Note the `instanceId` here is the literal string `568105589213729500` —
**identical**, digit for digit, to the root object's `instanceId` from step 1,
even though `globalId` and `hierarchyPath` clearly show these are two
different objects. This is not a copy-paste error on my part; it is what the
CLI printed both times. Do not compare these as numbers (they exceed 2^53 and
a JSON parser would silently round/collide them anyway) — `hierarchyPath` or
`globalId` are the only trustworthy identifiers here.

**3. `unity command set_transform --target /T005-Root-A/T005-Child-A --position 1,2,3 --json`**
— returned `"success": true`, but this was a silent no-op. The response body
contained only identity fields (`globalId`, `instanceId`, `hierarchyPath`,
`type`), no position values, so there was nothing in the response itself to
show that. I only caught it by reading the state back:

**4. `unity command get_component_properties --target /T005-Root-A/T005-Child-A --type Transform --json`**
→ `"m_LocalPosition": [0, 0, 0]`. The comma-separated string `1,2,3` was
accepted as a literal string value for a `single[]`-typed parameter and did
nothing; it did not error, it just didn't take effect.

**5. `unity command set_transform --target /T005-Root-A/T005-Child-A --position 1 2 3 --json`**
— tried space-separated values on the theory that the array parameter
consumes multiple tokens. This failed outright:

```
"success": false,
"errors": [{
  "code": "COMMAND_FAILED",
  "message": "Pipeline server returned 400 Bad Request: Parameter Validation Failed. Could not resolve 'target': No loaded object with instanceId 2."
}]
```

The trailing `2` and `3` got parsed as extra positional/flag tokens rather
than array elements, and the parser ended up trying to resolve `target` from
one of them (`2`) as if it were an instanceId. Exit code was 6.

**6. `unity command set_transform --target /T005-Root-A/T005-Child-A --position "[1,2,3]" --json`**
— quoting the value as a JSON array literal worked: `"success": true`.
Response again only carried identity fields, no position.

**7. `unity command get_component_properties --target /T005-Root-A/T005-Child-A --type Transform --json`**
→ `"m_LocalPosition": [1, 2, 3]`, `"m_LocalScale": [1, 1, 1]`. Confirmed the
write actually took effect this time.

**8. `unity command add_component --target /T005-Root-A/T005-Child-A --type BoxCollider --json`**
— success on the first try.

```
"result": {
  "globalId": "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1660226902-0",
  "instanceId": 568105589213729400,
  "hierarchyPath": "/T005-Root-A/T005-Child-A",
  "type": "BoxCollider"
}
```

(This `instanceId`, `568105589213729400`, differs from the one shared by the
two GameObjects above — so the collision in step 2 isn't universal, it just
happened to land on the same value twice there.)

**9. `unity command set_serialized_field --target /T005-Root-A/T005-Child-A --component BoxCollider --field size --value "[2,2,2]" --json`**
— tried the public API name `size` first, as instructed. It failed immediately
with a clear, specific error, not a silent default:

```
"success": false,
"errors": [{
  "code": "COMMAND_FAILED",
  "message": "Pipeline server returned 400 Bad Request: Parameter Validation Failed. Field 'size' was not found on 'BoxCollider'. Use a SerializedProperty path (e.g. 'speed', 'settings.speed', 'items.Array.data[0]')."
}]
```

So: **no, `size` does not work.** The tool requires the serialized field name.

**10. `unity command set_serialized_field --target /T005-Root-A/T005-Child-A --component BoxCollider --field m_Size --value "[2,2,2]" --json`**
— switched to `m_Size` but kept the array syntax that had worked for
`set_transform`'s `position`. This also failed, with a different error:

```
"success": false,
"errors": [{
  "code": "COMMAND_FAILED",
  "message": "Pipeline server returned 400 Bad Request: Parameter Validation Failed. Expected a JSON object with named components (e.g. { \"x\": 0 }) but received a 'Array'."
}]
```

So `set_transform`'s `position`/`rotation`/`scale` (declared type `single[]`)
and `set_serialized_field`'s `value` (declared type `jtoken`, used here for a
`Vector3`) do not accept the same array syntax — one wants `[x,y,z]`, the
other wants `{"x":..,"y":..,"z":..}`. The parameter's declared `type` in
`unity list --json` is the only way to know which is expected ahead of time.

**11. `unity command set_serialized_field --target /T005-Root-A/T005-Child-A --component BoxCollider --field m_Size --value '{"x":2,"y":2,"z":2}' --json`**
— this worked: `"success": true`. Response again carried only identity, no
size value.

**12. `unity command get_component_properties --target /T005-Root-A/T005-Child-A --type BoxCollider --json`**
— read-back proving the final state:

```
"properties": {
  "m_Material": null,
  "m_IsTrigger": false,
  "m_ProvidesContacts": false,
  "m_Size": [2, 2, 2],
  "m_Center": [0, 0, 0]
}
```

**13 & 14. Final confirmation**, `unity command find_gameobjects --hierarchy_path /T005-Root-A --json`
and `unity command find_gameobjects --hierarchy_path /T005-Root-A/T005-Child-A --json`,
both returned `"count": 1"` with exactly the expected `hierarchyPath` values,
confirming no stray duplicate objects were created by the earlier failed
attempts.

## m_Size vs size

`size` (the public C# property name) does not work and fails loudly and
specifically (`Field 'size' was not found on 'BoxCollider'`) — it does not
silently apply a default or create a stray object, at least not for
`set_serialized_field`. You must use the serialized field name `m_Size`, and
even then the value has to be a JSON object with named `x`/`y`/`z` keys, not
an array — `[2,2,2]` gets explicitly rejected too, with its own distinct error
message.

## State-echo tally

18 CLI invocations were made in total. Of those, 9 were attempts to mutate
state: 2 `create_gameobject`, 3 `set_transform`, 1 `add_component`, 3
`set_serialized_field`. Of those 9, 6 returned `"success": true` (the other 3
returned validation errors and no `result` object at all). Every single one
of the 6 successful mutating calls echoed only identity fields — `globalId`,
`assetPath`, `guid`, `fileId`, `instanceId`, `hierarchyPath`, `type` — never
the value that was actually written (no position array, no size array, no
component list). **Echoed state on 0 of 6 successful mutating calls (0 of 9
total mutating attempts).** Every value change had to be verified with a
separate `get_component_properties` call.

## instanceId values observed (verbatim strings)

- `T005-Root-A` (GameObject): `568105589213729500`
- `T005-Child-A` (GameObject): `568105589213729500` — same string as the root,
  confirmed identically on three separate calls (creation, and both later
  `find_gameobjects` lookups).
- `T005-Child-A`'s `BoxCollider` component: `568105589213729400` — different
  from the GameObject values above.

These were left as-is, exactly as printed by the CLI, since parsing them as
JSON numbers would round or otherwise corrupt them (they exceed 2^53).
`globalId` and `hierarchyPath` were used as the actual identifiers throughout
instead.

## Final state

- Root: `/T005-Root-A`, empty GameObject.
- Child: `/T005-Root-A/T005-Child-A`, local position `(1, 2, 3)`, `BoxCollider`
  with `m_Size` `(2, 2, 2)` and `m_Center` `(0, 0, 0)`.
- Task fully succeeded; nothing was deleted, nothing was saved, the Editor was
  never touched beyond these calls.

## Step count

18 CLI invocations total (including 1 version check, 2 `list --json` calls,
1 `--help` probe, and the 3 failed mutating attempts above).
