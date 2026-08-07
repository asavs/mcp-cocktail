# T-001, arm C — CoplayDev (MCP for Unity)

Stamped against: CLI `1.0.0-beta.3`, editor `6000.5.5f1`, Pipeline `0.4.0-exp.1`,
MCP for Unity `v10.0.0` (per `docs/unity-mcp.md`, 2026-07-28). Connected Unity
instance reported by `mcpforunity://instances`: `third-person-multiplayer`,
`unity_version: 6000.5.5f1`, hash `7d19c2af08626c21`.

## Task

Create `T001-Root` (empty GameObject) in the active scene, give it a child
`T001-Child` at local position (1, 2, 3) carrying a `BoxCollider` with
`size` (2, 2, 2). Tools only: `mcp__UnityMCP__*` and `mcpforunity://`
resources. No `execute_code`.

## Outcome

**Completed.** Both GameObjects exist with the required parenting, local
position, and BoxCollider size — verified by reading resources back after the
tool calls, not just by trusting the tool responses.

## Calls made, in order

1. `ReadMcpResourceTool` — server `UnityMCP`, uri `mcpforunity://instances`.
   Returned one connected instance: `third-person-multiplayer@7d19c2af08626c21`,
   `unity_version: "6000.5.5f1"`. Only one instance, so per the server's own
   instructions no `set_active_instance` call was needed.

2. `ReadMcpResourceTool` — uri `mcpforunity://custom-tools`. Returned
   `tool_count: 34`, listing this project's enabled tool set (`manage_gameobject`,
   `manage_components`, `find_gameobjects`, etc. all present). Matches the
   34-vs-47 gap documented in `docs/unity-mcp.md` (script-editing tools,
   `unity_docs`, `set_active_instance`, tool-management tools are the
   server-side-only remainder, not project-derived).

3. `mcp__UnityMCP__manage_gameobject` — `action: "create"`, `name: "T001-Root"`.
   Returned `success: true`, `instanceID: -2320`, `parentInstanceID: 0`,
   `componentNames: ["UnityEngine.Transform"]`, transform all zeros/identity
   scale. This is the tool *reporting* success — not yet independently checked.

4. `mcp__UnityMCP__manage_gameobject` — `action: "create"`, `name: "T001-Child"`,
   `parent: "-2320"`, `position: [1, 2, 3]`. Returned `success: true`,
   `instanceID: -2330`, `parentInstanceID: -2320`,
   `localPosition: {x:1, y:2, z:3}`. Because the root sits at world origin
   with identity rotation/scale, local and world position coincide here, so
   this single call doesn't by itself distinguish "set local position" from
   "set world position" — see Confidence below.

5. `mcp__UnityMCP__manage_components` — `action: "add"`, `target: -2330`,
   `search_method: "by_id"`, `component_type: "BoxCollider"`. Returned
   `success: true`, `componentInstanceID: -2344`. No size specified yet
   (Unity's BoxCollider default size is (1,1,1)).

6. `mcp__UnityMCP__manage_components` — `action: "set_property"`,
   `target: -2330`, `search_method: "by_id"`, `component_type: "BoxCollider"`,
   `property: "size"`, `value: {"x": 2, "y": 2, "z": 2}`. Returned
   `success: true`, `data: {instanceID: -2330}` — no echo of the new value in
   the response, just the target id.

At this point every call had reported success, but per the trial's own
instructions that is a different claim from the state being confirmed. Three
read-only verification calls followed:

7. `ReadMcpResourceTool` — uri `mcpforunity://scene/gameobject/-2330`.
   Returned `name: "T001-Child"`, `path: "T001-Root/T001-Child"`,
   `parent: -2320`, `transform.localPosition: {x:1, y:2, z:3}`,
   `transform.position: {x:1, y:2, z:3}` (equal because the parent is at the
   origin), `componentTypes: ["Transform", "BoxCollider"]`.

8. `ReadMcpResourceTool` — uri `mcpforunity://scene/gameobject/-2330/components`.
   Returned the full component list including the `BoxCollider` with
   `properties.size: {x:2.0, y:2.0, z:2.0}`, `center: {0,0,0}`,
   `bounds: {center: {1,2,3}, size: {2,2,2}}` — the bounds center matching the
   child's world position is itself a cross-check that the collider is on the
   right object at the right transform.

9. `ReadMcpResourceTool` — uri `mcpforunity://scene/gameobject/-2320`.
   Returned `name: "T001-Root"`, `parent: null`, `children: [-2330]`,
   `path: "T001-Root"`, `componentTypes: ["Transform"]` — confirming the root
   is a true top-level object with exactly the one expected child and no
   collider of its own.

Total: 9 calls (2 resource reads for the handshake, 4 mutating tool calls, 3
resource reads for verification).

## What was verified, and how

- **Tool-reported success vs. confirmed state**: every mutating call (steps
  3, 4, 5, 6) returned `success: true` with a data payload. That is the tool's
  claim. Independently, steps 7–9 re-read the same GameObjects and component
  through the read-only `mcpforunity://scene/gameobject/...` resources — a
  different code path than the one that performed the mutation — and the
  values matched: parent-child relationship, `localPosition (1,2,3)`, and
  `BoxCollider.size (2,2,2)` were all present in the freshly-read state, not
  just echoed back in the mutation's own response.
- The child's create response (step 4) already echoed `localPosition`, so in
  principle the read-back in step 7 is partially redundant with what the tool
  claimed — but the `set_property` response in step 6 did *not* echo the new
  size value at all, so step 8 was the only place the actual post-write size
  was observed.

## Friction / surprises

- None of the calls failed or needed retrying. No compilation was involved
  (no scripts created), so there was no need to poll `read_console` or an
  `isCompiling` field.
- The `manage_components` `set_property` response for `size` carries no
  payload of the new value — just `{"instanceID": -2330}` — so if the report's
  separation-of-claims requirement didn't already demand a read-back, this
  particular property write would have been easy to under-verify.
- `position` on `manage_gameobject create` accepts a bare `[1, 2, 3]` array
  and it was treated as local position (relative to the given `parent`) —
  matching the create tool's evident semantics of "position is local when a
  parent is given." This wasn't stated in the tool description I loaded, only
  inferred from the returned `localPosition` matching the input array
  exactly, and confirmed independently by the resource read in step 7.
- Everything else matched the reference doc (`docs/unity-mcp.md`) and the
  server's injected instructions without needing correction: single instance
  connected so no `set_active_instance` needed, `mcpforunity://custom-tools`
  tool count matched the documented 34.

## Expressiveness gaps

- None encountered for this task. `manage_gameobject create` took `name`,
  `parent`, and `position` all in one call; `manage_components` handled both
  `add` and `set_property` for the BoxCollider in two calls. Nothing about
  this task required a capability the tool surface didn't have.

## Confidence / uncertainty

- I did not do an experiment to prove that `position` on a `create` call is
  interpreted as *local* rather than *world* position in general — only that
  in this specific case (parent at world origin, identity rotation/scale) the
  two are numerically identical, so I cannot fully rule out that the tool set
  world position and it happened to coincide with the requested local
  position. The read-back in step 7 shows both `position` and `localPosition`
  equal to (1,2,3), which is consistent with either interpretation given this
  root's transform. Given the task only required local position (1,2,3) under
  a root at the origin, this is not distinguishable from the evidence I
  gathered, and I did not construct an additional test (e.g. moving the root
  first) to disambiguate since it wasn't asked for and moving the root would
  have changed committed... — no, this is a scratch scene, so it would have
  been safe to do, but I judged it out of scope for the stated Done-when
  criteria and did not want to add extra mutations beyond what was asked.
- Everything else in this report reflects state read back after the fact, not
  assumptions carried over from a tool's own success claim.
