# T-006 — property-name resolution across arms

**Date** 2026-08-06 · **Category** authoring / property mutation · **Mutating** yes ·
**Versions** CLI `1.0.0-beta.3`, Editor `6000.5.5f1`, Pipeline `0.4.0-exp.1`,
CoplayDev package `v10.0.0`

## Protocol deviation — read before citing this

**This was not run to the trial protocol and should not be read as one.** The protocol in
[README.md](../README.md) requires one report per arm, written by the agent that ran that arm,
before anyone compares anything. Here a **single operator ran both arms and knew each result
before running the next.** It carries a `T-` number because the scorecard already cites it
under one, which is itself a mistake worth naming: the number was assigned before the report
existed, and a reviewer caught the scorecard citing a trial with nothing behind it.

What that costs, and what it does not:

- **It does not much threaten these findings.** The measurements are mechanical — did the call
  bind, and does an independent read-back show the value. There is no step count, no friction
  judgement, and no "which felt better", which are the things blinding exists to protect.
- **It does threaten anything comparative.** Do not draw ergonomics or preference conclusions
  from this document. If those are wanted, run it properly.

## Question

Does arm C translate public C# property names into Unity's serialized field names? One data
point suggested it might: `set_property` with `property="size"` on a `BoxCollider` succeeded on
C, while A and B require `m_Size`.

## Method

One probe root `T006-Probe` with a child, carrying `BoxCollider`, `SphereCollider`,
`Rigidbody` and `Light`. For each case the public C# name was set through arm C and through
arm A, and **every success was verified by an independent read-back** rather than by the
call's own response. Arm A stands in for both A and B, which are one stack.

## Results

| # | Public name | Serialized name | Arm C | Arm A | Verified by read-back |
|---|---|---|---|---|---|
| 1 | `BoxCollider.size` | `m_Size` | success | rejected; `m_Size` succeeded | C `[3,3,3]`, A `[2,2,2]` |
| 2 | `BoxCollider.center` | `m_Center` | success | rejected; `m_Center` succeeded | C `[9,9,9]`, A `[5,5,5]` |
| 3 | `SphereCollider.radius` | `m_Radius` | success | rejected; `m_Radius` succeeded | C `6.5`, A `3.5` |
| 4 | `Rigidbody.mass` | `m_Mass` | success | rejected; `m_Mass` succeeded | C `12.5`, A `7.5` |
| 5 | `Light.intensity` | `m_Intensity` | success | rejected; `m_Intensity` succeeded | C `8.8`, A `4.2` |
| 6 | `Transform.position` | `m_LocalPosition` | success, **real setter ran** | rejected outright | world `(50,60,70)`, local `(40,55,67)` |
| 7 | `BoxCollider.notAThing` | — | rejected | rejected | unchanged |

Two further probes, not in the original plan, which are what actually settle the mechanism:

- Arm C with the **literal serialized name** `m_Size` **failed**: `Unsupported
  SerializedPropertyType: Vector3 at 'm_Size'`. Read-back confirmed the value unchanged. So the
  fallback found that field by exact string — no translation was needed or performed — and
  simply could not write a `Vector3` through it.
- Same for literal `m_LocalPosition` on `Transform`.

## Answer

**No translation exists, general or special-cased.** Arm C resolves the caller's literal string
against two backends in order:

1. **Reflection on the live component's public C# API.** An exact-name match runs the real .NET
   setter.
2. **Fallback: `SerializedObject.FindProperty(literalName)`** — same string, no case change, no
   `m_` prefixing — supporting only a subset of `SerializedPropertyType`s.

Arms A and B expose only the second layer. `size` succeeded on C because `BoxCollider.size`
**is** the public property name and tier 1 caught it.

## Case 6, which is the decisive one

`Transform.position` is world space; the backing field `m_LocalPosition` is local. The two
hypotheses predict different observable outcomes, which is why this case was chosen.

A name-mapping implementation writing the world value into the local field would leave local
`(50,60,70)` and displace the object to world `(60,65,73)`. Observed instead, on a child of a
parent at `(10,5,3)`: **world `(50,60,70)`, local `(40,55,67)` — exactly `world − parent`.**
The real setter ran and computed the local value itself.

Worth stating plainly: had C been a name-mapper, this case would have reported success while
silently displacing the object. The failure would have looked like a convenience feature.

## Honesty checks

No success/read-back mismatches on either arm across six cases each. Every failure reported
`success: false` with a specific error naming the property and component. The CLI's silent
argument-drop failure class did not appear here.

## Cleanup

`T006-Probe` and its child deleted via arm C, confirmed absent by read-back through **both**
arms. Scene not saved; Editor not restarted.
