# Unity Ecosystem Benchmark & Guardrails (Reference Dataset)

This directory contains a complete reference dataset for benchmarking the Unity agent tooling ecosystem — comparing the official `unity` CLI, the Official Unity Editor MCP server, and the community CoplayDev MCP server.

It holds the **evidence**. The **preset** those findings produced — the manifest, the rule store,
and the helper scripts that `setup --preset unity` copies into a workspace — lives inside the
package at `src/mcp_cocktail/presets/unity/`, because a `pip install` has no repo to read from.

---

## Directory Layout

| File / Path | Purpose |
|---|---|
| `UNITY-TOOLING-NOTES.md` | Authoritative record of observed Unity quirks, version-specific behavior, and the 5 recurring failure patterns (P1-P5). |
| `docs/unity-cli.md` & `docs/unity-mcp.md` | Setup guides for each Unity tooling layer. |
| `docs/tooling-scorecard.md` | Comparative performance scorecards and verdicts across Unity arms. |
| `docs/findings-inbox.md` | Raw, unverified mid-task friction notes logged by subagents and humans. |
| `docs/trials/` | Blind trial reports written by subagents across trials T-001 through T-006. |
| `docs/upstream/` | Upstream bug report drafts for official Unity engineering teams. |

---

## Quickstart: Using the Unity Reference Rules

The rules and the manifest ship with the package, so there is no path to point at:

```bash
cd /path/to/your-unity-project
mcp-cocktail setup --preset unity
```

That copies `manifest.json` and `traps.json` into `.agents/`, provisions `tools/`, installs the
PreToolUse hook, and runs the doctor. Then:

```bash
mcp-cocktail run T-001 "Build scene hierarchy" --exec auto
```
