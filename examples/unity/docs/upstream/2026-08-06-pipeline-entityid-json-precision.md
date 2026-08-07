## `instanceId` is emitted as a bare JSON number above 2^53, so clients that parse JSON numbers as doubles silently merge distinct objects

### Environment

- `com.unity.pipeline`: `0.4.0-exp.1`
- Unity Editor: `6000.5.5f1`
- `unity` CLI: `1.0.0-beta.3`
- OS: Windows 11

### Summary

Tool responses carry an object identifier in a field named `instanceId`. On Editor 6000.4+ this is `UnityEngine.Object.GetEntityId()`, a `ulong`-backed `EntityId`, and live values are around 5.68×10¹⁷.

It is emitted as a **bare, unquoted JSON number**. JSON numbers are parsed as IEEE-754 doubles by a large share of clients — every JavaScript one, by specification. A double carries 53 bits of integer precision, and in `[2^58, 2^59)` the representable values are **64 apart**. Newly created objects receive ids only a few apart, so distinct objects routinely collapse to the same value in the client.

The identifier is correct in the Editor and correct on the wire. It is destroyed on arrival.

### Evidence

Measured in-process, two GameObjects created back to back:

```
A = 568105589213729136
B = 568105589213729132     // four apart, EntityId.Equals -> False
```

Read back through the CLI, the same kind of pair reports:

```
Probe-1   globalId GlobalObjectId_V1-2-3efd2655…-166994847-0    instanceId 568105589213729300
Probe-2   globalId GlobalObjectId_V1-2-3efd2655…-2000673772-0   instanceId 568105589213729300
```

Distinct `globalId`, identical `instanceId`. `create_gameobjects --count 2` behaves the same way.

Four apart, against a 64-wide gap between adjacent doubles at that magnitude, is exactly the predicted collapse.

The serialization path itself is not at fault, which is worth stating so the fix is aimed correctly. `ObjectIdConverter.WriteJson` calls `writer.WriteValue(ulong)`, which in Newtonsoft.Json 13.0.2 routes to the integer writer, not the floating-point one. The two paths are separate methods, and the double path always emits a decimal point or an exponent — a bare 18-digit run is the signature of the exact-integer path. So the bytes leaving the server carry the true value.

### Steps to reproduce

With an Editor open and the Pipeline server running:

```
unity command create_gameobject --name Probe-1 --json
unity command create_gameobject --name Probe-2 --json
```

Compare the two `instanceId` values. Expected: two distinct identifiers for two distinct objects. Actual: identical, while `globalId` differs.

A client whose JSON parser keeps integers exact — Python's `json`, for instance — will **not** reproduce this, because the loss happens at the client's parse rather than in Pipeline. That is likely why the issue has not surfaced widely: it depends on the consumer's JSON stack, and the two most common consumers of this API are JavaScript.

### Suggested fix

**Emit `instanceId` as a quoted JSON string.** This is the standard remedy for 64-bit identifiers that must survive arbitrary JSON tooling — Twitter/X's `id_str` alongside a numeric `id` is the familiar precedent, adopted for exactly this failure. Since the value is already intact at serialization time, quoting is sufficient; no change to how the id is carried internally is needed.

Worth flagging that this is a breaking wire-format change for any client currently reading `instanceId` as a number, so it likely wants a deliberate versioning decision rather than a patch-level one. Emitting a companion string field and deprecating the numeric one is the lower-friction path if that matters.

For comparison, another MCP server for Unity exposes an object identifier as a quoted string and does not exhibit this behaviour with its consumers.

### Naming note

Separately from the encoding: the field is named `instanceId` but no longer carries what `GetInstanceID()` returns — the name predates the `EntityId` migration. It invites the assumption that the value is a small ordinary int, which is precisely the assumption that makes a bare JSON number look safe. Renaming it, or documenting what it now holds, would reduce the chance of the same assumption being made downstream.
