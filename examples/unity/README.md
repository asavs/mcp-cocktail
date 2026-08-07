# Unity Ecosystem Benchmark & Guardrails (Reference Dataset)

This directory contains a complete reference dataset for benchmarking the Unity agent tooling ecosystem — comparing the official `unity` CLI, the Official Unity Editor MCP server, and the community CoplayDev MCP server.

---

## Directory Layout

| File / Path | Purpose |
|---|---|
| `cocktail.json` | Workspace manifest defining the 3 Unity arms (CLI, Official MCP, CoplayDev MCP). |
| `traps.json` | Active rule store containing 15+ verified PreToolUse trap rules for Unity tooling. |
| `UNITY-TOOLING-NOTES.md` | Authoritative record of observed Unity quirks, version-specific behavior, and the 5 recurring failure patterns (P1-P5). |
| `docs/unity-cli.md` & `docs/unity-mcp.md` | Setup guides for each Unity tooling layer. |
| `docs/tooling-scorecard.md` | Comparative performance scorecards and verdicts across Unity arms. |
| `docs/findings-inbox.md` | Raw, unverified mid-task friction notes logged by subagents and humans. |
| `docs/trials/` | Blind trial reports written by subagents across trials T-001 through T-006. |
| `docs/upstream/` | Upstream bug report drafts for official Unity engineering teams. |
| `tools/` | Helper scripts (`three-way-setup.sh`, portable `UnityYAMLMerge` setup). |

---

## Quickstart: Using the Unity Reference Rules

To activate these 15+ Unity guardrail rules in your Unity project:

```bash
# Point mcp-cocktail at this reference traps file
mcp-cocktail install-hook --traps "C:/path/to/mcp-cocktail/examples/unity/traps.json"
```

To run a multi-arm benchmark trial against your Unity project:

```bash
cp examples/unity/cocktail.json /path/to/your-unity-project/mcp-cocktail.json
cd /path/to/your-unity-project
mcp-cocktail run T-001 "Build scene hierarchy" --exec auto
```
