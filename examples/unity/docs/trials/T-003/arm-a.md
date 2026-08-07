# T-003, arm A: the `unity` CLI (`unity command`)

**Task**: In the active scene, create empty GameObject `T003-Root-A`, with
child empty GameObject `T003-Child-A` at local position (1, 2, 3), carrying a
`BoxCollider` with `size` (2, 2, 2).

**Versions**, all read directly at the start of this trial rather than
assumed:

- `unity` CLI: `1.0.0-beta.3` (`unity --version`)
- Unity Editor: `6000.5.5f1` (`unity status --json`)
- Pipeline package: `0.4.0-exp.1` (`unity pipeline list --json`)
- Project: `C:\Users\asas\UnityProjects\third-person-multiplayer-gabe`, port
  7800, PID 19092
- Scene at time of work: `OldForest MultiplayerSession`
  (`Assets/Game/Worlds/OldForest/Scenes/OldForest MultiplayerSession.unity`)

Tool surface used exclusively: `unity status`, `unity list`, `unity command
<tool> [--flag value ...]`, `unity pipeline list`. No `mcp__*` tool was used
at any point. `PATH` was extended with
`export PATH="$PATH:/c/Users/asas/AppData/Local/Unity/bin"` at the start of
the session and not touched again.

## Outcome

**Completed and verified.** All three acceptance criteria confirmed by
read-only calls made after, and separate from, the calls that wrote the
state.

## Every command run, in order

1. `export PATH="$PATH:/c/Users/asas/AppData/Local/Unity/bin"` — put the CLI
   on PATH.

2. `unity status --json` — confirmed one connected instance: port 7800,
   project `third-person-multiplayer-gabe`, version `6000.5.5f1`, PID 19092,
   state `ready`. Matched the brief exactly; did not touch the Editor beyond
   this read.

3. `unity --version` → `1.0.0-beta.3`.

4. `unity list` (human format) — enumerated the ~141 registered Pipeline
   tools with one-line descriptions. Confirmed `create_gameobjects`,
   `set_component_properties`, `add_component`, `get_component_properties`,
   `get_scene_hierarchy`, `find_gameobjects`, `delete_gameobject` all exist.

5. `unity command --help` — **unhelpful**. This is the generic help for the
   `command` subcommand itself (lists `--project-path`, `--timeout`, etc.),
   not per-tool argument help. Nothing here told me how to pass parameters to
   a specific tool.

6. `unity command set_parent --help`, `unity command set_transform --help`,
   `unity command add_component --help` — same generic help text verbatim
   each time, regardless of the tool name given. `--help` does not do
   per-tool introspection; it always renders the `command` subcommand's own
   help and ignores the tool name argument entirely. Wasted three calls
   learning this pattern once was already enough.

7. `unity command create_gameobjects --json` (**no arguments at all**,
   probing to see what an empty call would report) → **succeeded and
   created a real GameObject**, named `New Game Object`, as a side effect of
   the probe. `"parameters": {"json": true}` in the echoed response, i.e. no
   authoring parameters were sent. This was not intended as a write — I was
   trying to elicit a "missing required argument" error or usage string, and
   instead got a silent default-valued create. Cost: one stray object in the
   shared scene.

8. `python3 -c ...` piped from `unity list --json` — **failed**,
   `python3: command not found` on this machine. Not a CLI problem, just
   confirms no Python available in this shell; switched to `grep`/plain
   pipes for the rest of the session.

9. `unity command create_gameobjects name=FooTest --json` — **silently
   ignored the argument**. Response again showed `"parameters": {"json":
   true}`, no `name` key anywhere, and created a second stray `New Game
   Object`. `key=value` positional syntax is not how this CLI accepts tool
   parameters, and it fails silently rather than erroring — worse than a
   hard error, because nothing signals the argument was dropped.

10. `unity command create_gameobjects '{"name":"FooTest2"}' --json` — same
    silent failure, third stray `New Game Object` created. A JSON-blob
    positional argument is also not the accepted syntax.

11. `unity command get_scene_hierarchy --json` — read the scene to see what
    the previous three calls had actually done, since their own responses
    hadn't clarified anything.

12. `unity command find_gameobjects --name "New Game Object" --json` — this
    was the first correctly-shaped call (flag syntax), and it worked,
    returning all three strays. All three had **distinct `globalId` values
    but the identical `instanceId`, `568105589213729540`**, despite being
    three separate GameObjects. This is a real oddity in the tool's
    response, not a typo — confirmed by re-reading it below.

13. `unity list --json | grep create_gameobjects` and

14. `unity list --json | grep -A80 '"name": "create_gameobjects"'` — this is
    where I found the actual fix: `unity list --json` (not `--help` on the
    command) embeds a full parameter schema per tool — name, type,
    description, required, default. This is the correct way to learn a
    tool's arguments; `--help` is a dead end for this purpose. For
    `create_gameobjects` the schema showed `name` (string), `primitive`
    (string), `parent` (objectref), `count` (int), `positions`/`rotations`/
    `scales` (`single[][]`, one `[x,y,z]` per object).

15. `unity list --help`, `unity pipeline --help` — checked whether a
    dedicated schema/describe subcommand existed elsewhere in the CLI.
    Neither offered one; `unity list --json`'s embedded schema remains the
    only source of per-tool argument documentation found.

16. `unity list --json | grep -A20 '"name": "delete_gameobject"'` — schema
    for cleanup: single required `target` (objectref).

17-19. `unity command delete_gameobject --target "<globalId>" --json`, once
    per stray `globalId` from step 12 — all three succeeded first try,
    addressed by `globalId` (not the ambiguous shared `instanceId`, and not
    `hierarchyPath`, which was also identical — `/New Game Object` — across
    all three).

20. `unity command find_gameobjects --name "New Game Object" --json` →
    `"count": 0` — confirmed cleanup complete before starting real work.

21. `unity command create_gameobjects --name T003-Root-A --json` —
    **succeeded first try** using `--<paramName> <value>` flag syntax (the
    pattern learned from steps 7-14: schema field names become CLI flags).
    Returned `globalId
    GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-544996077-0`,
    `hierarchyPath: "/T003-Root-A"`.

22. `unity command find_gameobjects --name "T003-Root-A" --json` — re-fetched
    the root's handle (not strictly necessary, I already had the globalId
    from step 21's response, but did it out of habit after the instanceId
    confusion above).

23. `unity command create_gameobjects --name T003-Child-A --parent
    "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-544996077-0"
    --positions "[[1,2,3]]" --json` — **succeeded first try**. Returned
    `hierarchyPath: "/T003-Root-A/T003-Child-A"`, confirming correct
    parenting in the same response.

24. `unity list --json | grep -A20 '"name": "add_component"'` and

25. `unity list --json | grep -A20 '"name": "set_component_properties"'` —
    pulled schemas before calling, having learned that lesson.

26. `unity command add_component --target
    "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1250637981-0"
    --type BoxCollider --json` — **succeeded first try**.

27. `unity command set_component_properties --target
    "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1250637983-0"
    --properties '{"size":[2,2,2]}' --json` — **failed**:
    ```
    Pipeline server returned 400 Bad Request: Parameter Validation Failed.
    Component 'BoxCollider' has no serialized property 'size'.
    ```
    `size` is `BoxCollider.size`'s public C# API name; the tool wants
    Unity's internal serialized field name instead, and does not accept or
    alias the public one.

28. `unity command get_component_properties --target
    "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1250637983-0"
    --json` — read the component to find the real field name. Returned
    `m_Size: [1,1,1]` (still default — confirmed step 27 did not
    partially apply), `m_Center: [0,0,0]`.

29. `unity command set_component_properties --target
    "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1250637983-0"
    --properties '{"m_Size":[2,2,2]}' --json` — **succeeded**, response
    echoed `m_Size: [2,2,2]`.

30. `unity command get_component_properties --target
    "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1250637981-0"
    --type Transform --json` — independent read-only check, not reusing
    the create/set-transform response. Returned `m_LocalPosition: [1,2,3]`,
    `m_LocalScale: [1,1,1]`.

31. `unity command get_scene_hierarchy --json` (grepped for `T003-Root-A`) —
    independent structural check. Showed `T003-Root-A` at the scene root
    with components `["Transform"]` and one child, `T003-Child-A`, with
    components `["Transform", "BoxCollider"]`.

32. `unity command get_component_properties --target
    "GlobalObjectId_V1-2-3efd2655b3f799546abd1924c8ee760a-1250637981-0"
    --type BoxCollider --json` — independent, read-only, post-hoc check of
    the collider size, not relying on step 29's own echoed response.
    Returned `m_Size: [2,2,2]`.

33. `unity pipeline list --json` — pulled the Pipeline package version for
    this report.

34. `unity command get_scene_hierarchy --json` (grepped for `isDirty`) —
    confirmed `isDirty: true` and the scene was never saved during this
    trial (no `save_scene`/`save_all` call was ever made).

## Step count

Counting only the direct path to build and verify the required objects
(excluding the help/schema probing in steps 5-20, which was one-time
tool-learning overhead, and excluding the three accidental creates and their
cleanup): **10 steps** — create root, fetch its handle, create+parent+place
child, add BoxCollider, one failed property-set, one property read to find
the right field name, one successful property-set, and three independent
verification reads (Transform position, full hierarchy, BoxCollider size).

Counting everything actually executed against the live Editor, including the
three accidental stray-object creates and their three deletions: 14 calls
touched Editor state; 20 more were pure reads (`status`, `list`,
`get_scene_hierarchy`, `find_gameobjects`, `get_component_properties`,
`pipeline list`) or local shell probing that never reached the Editor
(`--help` calls, the failed `python3` pipe).

## What worked first try, and what didn't

**Worked first try:** `unity status --json`; `unity --version`; `unity
list`; `find_gameobjects` (once flag syntax was known); `delete_gameobject`
by `globalId` (all three); `create_gameobjects --name T003-Root-A`;
`create_gameobjects --name T003-Child-A --parent ... --positions [[1,2,3]]`
(name, parenting, and local position all landed correctly in one call);
`add_component --type BoxCollider`; every read-only verification call.

**Did not work first try:**

- `unity command <tool> --help` — never returns per-tool argument help,
  always the generic `command` subcommand usage, regardless of which tool
  name is given. Discovered only after trying it against four different
  tool names and getting byte-identical output each time.
- `unity command create_gameobjects --json` with no arguments — did not
  error or print usage; silently created a live GameObject with default
  values (`New Game Object`) in the shared scene. Given the task's stated
  concern about not disturbing a shared Editor, an argument-probing call
  that mutates the scene by default is a sharp edge.
- `key=value` positional syntax (`create_gameobjects name=FooTest`) —
  silently dropped; the tool ran, "succeeded", and created another default
  `New Game Object` with the given name ignored entirely. No error, no
  warning — the response's own echoed `parameters` block would have shown
  the drop if inspected carefully, but nothing surfaced it proactively.
- A raw JSON-object positional argument (`create_gameobjects
  '{"name":"FooTest2"}'`) — same silent drop, same stray object.
- `set_component_properties --properties '{"size":[2,2,2]}'` — hard error,
  `400 Bad Request`, `Component 'BoxCollider' has no serialized property
  'size'`. The tool wants Unity's internal serialized field name
  (`m_Size`), not the public C# property name (`size`) that the Unity
  Scripting API docs and most people's muscle memory would produce.

## Friction

- **`--help` is a dead end for per-tool arguments.** The only place a
  tool's actual parameter schema (names, types, required/default,
  descriptions) is exposed is `unity list --json`, which returns a
  `parameters` array per tool. This is not discoverable from `--help` text
  anywhere in the CLI (checked `unity command --help`, `unity command
  <tool> --help`, `unity list --help`, `unity pipeline --help`). A stranger
  would need to know to reach for `--json` output on a *different*
  subcommand than the one they're trying to call, which is not an obvious
  jump.
- **Argument-probing is not safe.** Calling a mutating tool with no/wrong
  arguments to see what happens, expecting a validation error, instead
  silently executed with defaults twice (empty call, `key=value` call) and
  once with a fully-formed-but-wrong-shaped JSON string. All three
  mutated the shared scene. Only the fourth attempt (correct `--flagName
  value` syntax) actually got recognized.
- **Serialized field names vs. public API names.** `BoxCollider.size` had
  to be spelled `m_Size` for `set_component_properties`. The error message
  when this went wrong was clear and immediate (`400`, named the wrong
  property), which limited the damage to one wasted call plus one
  discovery call — better than the silent-drop failures above, at least
  this one *told me* it failed.
- Flag syntax for array-valued parameters (`positions`) took a JSON string
  under a single `--positions` flag (`--positions "[[1,2,3]]"`) rather than
  repeated flags or space-separated numbers; this was a guess based on the
  schema saying type `single[][]`, and it happened to work first try, but
  nothing in `--help` or the schema description stated the expected CLI
  encoding for a nested-array type.

## Surprises

- **Three distinct GameObjects reported the identical `instanceId`**
  (`568105589213729540`) across three separate `create_gameobjects` calls,
  each with a different `globalId`. Confirmed by an independent
  `find_gameobjects --name "New Game Object" --json` call that listed all
  three side by side with three different `globalId`s and one shared
  `instanceId`. `hierarchyPath` was also identical across all three
  (`/New Game Object`, since none had unique names), so neither
  `instanceId` nor `hierarchyPath` was a safe handle for disambiguating
  them — only `globalId` was unique per object, and that's what
  `delete_gameobject --target` needed to clean them up individually.
- The later legitimate objects (`T003-Root-A`, `T003-Child-A`) did *not*
  repeat this problem in the same way `instanceId` was internally
  consistent per-object across their own create/read calls (checked: root's
  `instanceId` `568105589213729540` — coincidentally the very same number
  reused from the deleted strays, most likely because Unity recycles
  freed instance IDs — and child's `instanceId` `568105589213729500` stayed
  fixed and unique between the two of them throughout). So the shared-ID
  behavior in the earlier strays looks specifically tied to how three
  rapid, minimally/incorrectly-parameterized calls got resolved, not a
  general property of every object in the scene.
- A no-argument or wrong-argument call to a mutating tool did not refuse to
  run — it ran anyway with schema defaults. I did not expect probing calls
  to be write-safe by default.
- Once the `--flagName value` calling convention was known, every
  multi-parameter call (naming, parenting, and positioning a GameObject in
  one `create_gameobjects` invocation) worked exactly as the schema
  described, with no further surprises.

## Verification

All three acceptance criteria were confirmed by read-only calls made after,
and independent of, the calls that created/mutated the state:

- **Root and child exist, correctly parented:** `get_scene_hierarchy --json`
  (step 31) showed:
  ```
  "name": "T003-Root-A", "hierarchyPath": "/T003-Root-A",
  "components": ["Transform"],
  "children": [
    { "name": "T003-Child-A", "hierarchyPath": "/T003-Root-A/T003-Child-A",
      "components": ["Transform", "BoxCollider"], "children": [] }
  ]
  ```
- **Child's local position is (1, 2, 3):** a fresh
  `get_component_properties --target <child> --type Transform --json`
  (step 30), not reusing the creation call's response, returned:
  ```
  "m_LocalPosition": [1, 2, 3], "m_LocalScale": [1, 1, 1]
  ```
- **BoxCollider size is (2, 2, 2):** a fresh
  `get_component_properties --target <child> --type BoxCollider --json`
  (step 32), not reusing the `set_component_properties` call's own echoed
  response, returned:
  ```
  "m_Size": [2, 2, 2], "m_Center": [0, 0, 0]
  ```

Final state verified. Scene confirmed still dirty (`isDirty: true`) and was
never saved — no `save_scene` or `save_all` call was made at any point in
this trial. The Editor was never stopped, started, or restarted; only
`status` and `command` calls were issued against the already-running
instance on port 7800.
