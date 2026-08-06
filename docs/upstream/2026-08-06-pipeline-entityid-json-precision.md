## `instanceId` returns the same value for distinct GameObjects — precision is lost before the JSON is written

### Environment

- `com.unity.pipeline`: `0.4.0-exp.1`
- Unity Editor: `6000.5.5f1`
- `unity` CLI: `1.0.0-beta.3`
- OS: Windows 11

### Summary

Tool responses carry an object identifier in a field named `instanceId`. On Editor 6000.4+ that value is `UnityEngine.Object.GetEntityId()` — a ulong-backed `EntityId`, not the `int`-sized `GetInstanceID()` — and observed values are around 5.68×10¹⁷.

**Distinct GameObjects come back with identical `instanceId` values, in the raw response text.** The objects are genuinely distinct: their `globalId` values differ, and the scene contains two separate objects afterwards. Only the `instanceId` collides.

This is not a client-side parsing artifact. The identical digits are present in the bytes the CLI prints, before any client parses them into a number.

### Steps to reproduce

With an Editor open and the Pipeline server running:

```
unity command create_gameobject --name Probe-1 --json
unity command create_gameobject --name Probe-2 --json
```

Observed, on two consecutive runs:

```
Probe-1   globalId GlobalObjectId_V1-2-3efd2655…-166994847-0    instanceId 568105589213729300
Probe-2   globalId GlobalObjectId_V1-2-3efd2655…-2000673772-0   instanceId 568105589213729300
```

`create_gameobjects --count 2` behaves the same way — both returned `568105589213729340`.

Expected: two distinct objects, two distinct identifiers. Actual: distinct `globalId`, identical `instanceId`.

### Why this appears to happen

Stated as inference, not observation — the mechanism is consistent with the output but has not been confirmed against the serializer's source.

A `double` carries 53 bits of integer precision. Above 2^53 the gap between adjacent representable values is `2^(e−52)` for the exponent bracketing the value. Values around 5.68×10¹⁷ fall in `[2^58, 2^59)`, where that gap is **64**. Any two identifiers less than 64 apart become the same value once passed through a `double`.

Two details point at that happening inside the server rather than in a client:

1. The collision is present in the emitted text, so it precedes serialization to JSON.
2. The emitted integers do not look like arbitrary 64-bit values. `568105589213729340` is not itself exactly representable as a `double` — the nearest is `568105589213729344` — which is what a `double` formatted back to 17 significant decimal digits looks like, rather than what an exact `ulong` printed as an integer looks like.

Together those suggest the identifier is being widened or passed through a floating-point type somewhere between `GetEntityId()` and the response, and that the JSON encoding is faithfully reproducing an already-damaged value.

### Why it presents as intermittent

Identifiers that happen to be allocated 64 or more apart survive and look completely normal; ones allocated closer together merge. Nothing about timing, call ordering, or batch-versus-single affects it — the determining factor is how far apart the underlying values happen to fall. That makes it easy to mistake for a nondeterministic allocation bug in the engine, which is where the investigation behind this report first went.

### Suggested fix

Two parts, and the first matters more:

1. **Carry the identifier as an integer end to end.** If it is currently widened to `double`, or serialized through a path that treats numeric values as `double`, the precision is gone before encoding and no change to the wire format recovers it.
2. **Consider emitting it as a quoted string** once it is intact. Values above 2^53 in a bare JSON number are fragile regardless, because a great many clients parse JSON numbers into doubles; quoting is the usual remedy for 64-bit ids (Twitter/X's `id_str` being the familiar precedent). Worth noting this is a breaking wire-format change for clients currently reading it as a number, so it likely wants a deliberate versioning decision rather than a patch-level one.

A useful check while testing either: compare the identifiers as **text**, not as parsed numbers. A client whose JSON library keeps integers exact — Python's `json`, for instance — will still show the collision here, because the loss is upstream of the client; but comparing as text removes any doubt about where it happened.

### Naming note

Separately from the encoding: the field is named `instanceId` but no longer carries what `GetInstanceID()` returns. The name predates the `EntityId` migration and invites the assumption that the value is a small ordinary int, which is part of what made the symptom read as an engine bug rather than a serialization one. Renaming it, or documenting what it now contains, would help independently of the precision issue.
