# Tooling scorecard

Which of the three arms to reach for, and the trials that justify it.

Protocol: [tooling-experiment.md](tooling-experiment.md). Arms: **A** = `unity`
CLI, **B** = MCP official (`mcp__unity-editor-mcp__*`), **C** = MCP CoplayDev
(`mcp__unityMCP__*` — but see below).

The tool prefix is derived from **the client's own config key**, so C's
namespace differs per client and neither spelling is canonical: Codex's
`config.toml` declares `[mcp_servers.unityMCP]` and Codex sees
`mcp__unityMCP__*`; `~/.claude.json` declares `"UnityMCP"` and Claude Code sees
`mcp__UnityMCP__*`. Searching for the other client's casing returns nothing,
which reads as "the tools aren't loaded". Check your own config before
concluding that.

---

## Capability matrix

The working answer to "which arm should I use". Update it when a trial changes
the picture, and cite the trial.

| Use case | Best | Avoid | Confidence | Evidence |
|---|---|---|---|---|
| Install / uninstall editors and modules | **A** | B, C — impossible | High | Structural: MCPs need a live Editor |
| Open / close projects, license, auth | **A** | B, C — impossible | High | Structural |
| Headless / CI / no Editor running | **A** | B, C — impossible | High | Structural |
| Live scene-graph inspection | **B** or **C** | A — impossible | High | Structural: CLI has no scene access |
| Reading Editor console / compile errors | **B** | — | Medium | T-000; `get_console_logs` returned structured data immediately |
| Invoking Editor menu items | **B** | — | Medium | T-000; `menu` executed and listed all 873 items |
| Editor lifecycle (quit, play mode) | **B** | — | Low | T-000; `File/Exit` worked but errored on response as the server died |
| Scripted / repeatable setup | **A** | — | Medium | T-000; every CLI step was reproducible, GUI steps were not |
| GameObject / prefab authoring | ? | — | None | **Untested** |
| Script creation + attach + recompile | ? | — | None | **Untested** |
| Builds and test runs | ? | — | None | **Untested** — A and B both offer it |
| Asset import / settings changes | ? | — | None | **Untested** |
| Multi-client environments | **C** | — | Medium | 22 configurators vs ~16; structural |

Most rows are empty on purpose. Six of the filled ones are **structural** —
true by architecture, not worth a trial. The interesting rows are the `?`s.

### Standing observations

Short version, with the detail living elsewhere — this file is for verdicts,
[UNITY-TOOLING-NOTES.md](../UNITY-TOOLING-NOTES.md) is for observations.

- **A fails quietly** — returns confident wrong answers rather than errors.
  [Detail](unity-cli.md#scripting-the-cli).
- **B has the better safety model** (`confirm=true`, `dry_run`, path
  confinement) — and ships `eval`/`eval_file`, which bypass all of it.
  [Detail](unity-mcp.md#security-notes).
- **B's errors are unusually good** — `unity list` names all three
  prerequisites when the Pipeline isn't reachable. Use it as the benchmark.
- **C is GUI-gated** — setup can't be fully scripted, making it the most
  expensive arm to stand up on a fresh machine.
  [Detail](unity-mcp.md#coplaydev-mcp-for-unity).
- **B can be allowlisted read-only, C mostly can't** — 44 of 140 vs 9 of 47,
  because a permission rule can only be as precise as the tool it names.
  [Detail](#tool-surfaces-at-a-glance).
- **C binds loopback, B binds every interface.** CoplayDev listens on
  `127.0.0.1:8080`; Unity's Pipeline listens on `0.0.0.0:7800` while reporting
  its own URL as `127.0.0.1`. On this one dimension C is the better-behaved
  server. [Detail](unity-mcp.md#security-notes).

---

## Tool surfaces at a glance

Captured 2026-07-28. B via `unity list`; C by speaking MCP directly to
`http://127.0.0.1:8080/mcp` (see [unity-mcp.md](unity-mcp.md#verify-and-recover)).

| | B — Unity official | C — CoplayDev |
|---|---|---|
| Server | Pipeline `0.4.0-exp.1` | `mcp-for-unity-server 3.4.5` |
| Tools | **140** | **47** |
| Granularity | fine-grained — `create_gameobject`, `set_parent`, `set_active` | coarse dispatchers — `manage_gameobject`, `manage_scene` + an `action` argument |
| Arbitrary code | `eval` / `eval_file` | `execute_code` |

Granularity is the real difference, and it cuts both ways. B's 140 tools are
self-documenting: the schema tells you what the call does, and a wrong call
fails at validation. C's 47 are compact — far less context to load — but each
one hides a sub-API you have to learn from its description, and a wrong
`action` fails at runtime.

**Granularity also decides what can be pre-approved.** A permission rule names
a tool, so it can only be as precise as the tool is. B's read/write split falls
on tool boundaries — `get_scene_hierarchy` cannot write, `set_transform` cannot
not-write — so 44 of its 140 are allowlistable as read-only with no judgement
call. C's dispatchers put both sides of that line inside one name:
`manage_scene` covers `get_hierarchy` and `delete`, `manage_asset` covers
reading and deleting. Only 9 of C's 47 could be allowlisted, and one of those,
`read_console`, is a compromise — its `clear` action mutates console state,
which is ephemeral UI rather than project data. The rest are unreachable
without prompting on every call, however harmless the `action`. See
[`.claude/settings.json`](../.claude/settings.json).

This is the first non-structural difference found without running a trial, and
it favours B for unattended agent work specifically.

**Only in C:**

- `unity_reflect` / `unity_docs` — verify Unity APIs against the actual
  assemblies. The server's own instructions say *"LLM training data frequently
  contains incorrect, outdated, or hallucinated Unity APIs"* and tell agents to
  reflect before answering. Nothing in B addresses hallucinated APIs, and for
  agent work this may be C's strongest argument.
- `generate_image` / `generate_model` — AI asset generation.
- `manage_probuilder`, `manage_vfx`, `manage_profiler`, `manage_ui` — B has no
  equivalents.
- `set_active_instance` — explicit routing when several Editors are connected.
  B has no multi-instance concept.
- `batch_execute` — several operations per call, which partly offsets the
  latency of coarse dispatchers.

**Only in B:** `set_authoring_root` path confinement, and `confirm=true` /
`dry_run` guards on destructive tools. C's guards, if any, are inside each
dispatcher and not visible from the tool list. `[unverified]`

C's tools have since been invoked through a normal client (`read_console`
returned structured console data), so the raw-HTTP procedure above is a
diagnostic for when a client won't load them, not the working path.

**Not yet compared:** actual behaviour. Everything above is read off the tool
lists, not from running the same task through both. That's what a T-001
authoring trial is for.

## Trials

Newest first. Template at the bottom.

### T-000 — initial setup of CLI, both MCP servers, and the git merge driver

**Date** 2026-07-28 · **Category** setup · **Mutating** yes ·
**Versions** CLI `1.0.0-beta.3`, Editor `6000.5.5f1`, Pipeline `0.4.0-exp.1`,
MCP for Unity `v10.0.0`

Not a controlled trial — this was the bootstrap, done before the protocol
existed. Recorded because it's the only evidence behind several matrix rows and
because "how hard was each arm to stand up" is itself a finding.

| Arm | Outcome | Friction |
|---|---|---|
| **A** CLI | Completed | Docs give a Windows install command that cannot work; only the beta channel is published; several commands return non-zero on success; commands are cwd-sensitive and invent plausible wrong answers; some `--help` subcommands hang |
| **B** MCP official | Completed | Reports `✓ Connected` while exposing **zero** tools without `com.unity.pipeline`; needs an Editor restart to resolve the package; server binds late. Once up: 140 tools, worked first time |
| **C** MCP CoplayDev | Completed | `uv` must be on the Editor's PATH **at launch** — installing it while Unity runs is unrecoverable without a restart; bundled README describes a UI that no longer exists; setup is GUI-only |

**Notable:** B was used to set up C — `menu` opened CoplayDev's own
configuration window. Cross-arm bootstrapping works.

**Verdict** — A is the only arm that can install anything, so it's not
optional. B was the least painful to reach a working state *given* the CLI
already existed. C cost the most human intervention, entirely because of the
GUI dependency.

**Follow-ups**
- Compare B and C on the same authoring task — the first real trial.
- `unity build` (A) vs `build` (B) on the same target.
- Does C offer anything B doesn't, beyond client breadth?

---

## Trial template

```markdown
### T-NNN — <one-line task>

**Date** YYYY-MM-DD · **Category** <setup|inspection|authoring|build-test|debug>
· **Mutating** yes/no · **Versions** CLI x, Pipeline y, MCP-for-Unity z, Editor w

**Task** <what was asked>
**Done when** <acceptance criteria, written before running>

| Arm | Outcome | Steps | Friction | Verifiable? |
|---|---|---|---|---|
| A CLI | completed/partial/blocked/N-A | | | |
| B MCP official | | | | |
| C MCP CoplayDev | | | | |

**Verdict** <which arm, and why — not step count alone>
**Matrix changes** <rows updated, or "none">
**Follow-ups** <what this raises>
```
