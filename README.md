# mcp-cocktail

A domain-agnostic, Recursive Self-Improvement (RSI) framework for benchmarking, evaluating, and injecting real-time guardrails across competing MCP servers, CLIs, and AI agent tools.

When software vendors take months or years to release official Model Context Protocol (MCP) servers or command-line tools, open-source communities fill the vacuum with unofficial MCPs, wrappers, and CLIs. This fragmentation leads to competing tools ("arms") with varying degrees of stability, silent failures, and trap behavior.

`mcp-cocktail` provides the machinery to:
- **Inject Real-Time PreToolUse Guardrails:** Intercept tool calls right *before* a known trap is sprung (`mcp-cocktail check` / `install-hook`).
- **Benchmark Multi-Arm Ecosystems:** Run subagents in unison across all available MCPs and CLIs (`mcp-cocktail run`).
- **Log & Mine Friction:** Capture real-time friction notes (`mcp-cocktail note`) and mine subagent transcripts for failure patterns P1-P5 (`mcp-cocktail mine`).
- **Drive Weakness-Maximizing RSI Loops:** Synthesize scorecards (`mcp-cocktail scorecard --rsi`) and auto-derive **Weakest Valid Guardrails** (`traps.json`) based on Bennett (2023).

---

## ⚡ Quickstart (30 Seconds)

```bash
# 1. Install mcp-cocktail
pip install -e .

# 2. Automated Setup & Doctor Health Check for your domain (e.g. unity)
mcp-cocktail setup --preset unity

# 3. Test Guardrail Execution (< 5ms interception)
mcp-cocktail check --selftest
```

---

## 🤝 Zero-Friction Collaborator Setup (Committing Rules to Git)

By committing `mcp-cocktail.json`, `traps.json`, and harness configuration files (`.claude/settings.json`, `.omp/settings.json`, `mcp.json`) directly to your project's Git repository, **every teammate and AI agent on your team inherits the guardrails automatically**:

```bash
# Inside your project repo:
git add mcp-cocktail.json traps.json .claude/ .omp/ docs/
git commit -m "chore: add mcp-cocktail guardrails and tool manifest"
git push
```

When a collaborator clones or pulls the repository:
- Their agent harness (Claude Code, Oh My Pi, Cursor, VS Code) automatically detects the guardrails and configuration files on startup.
- Teammates enjoy real-time trap shielding without needing any manual setup!

---

## 📖 Progressive Walkthrough

### 1. Initialize or Discover Workspace Manifests
Create a workspace config (`mcp-cocktail.json`) manually or auto-discover candidate MCPs and CLIs from GitHub and registries:

```bash
# Auto-discover open-source MCPs & CLIs for a domain (non-destructive merge)
mcp-cocktail discover --domain postgres

# Generate an agentic scout subagent task for deep web discovery
mcp-cocktail discover --domain unity --agentic
```

`mcp-cocktail.json` structure:
```json
{
  "name": "unity-ecosystem",
  "description": "Multi-arm evaluation manifest for Unity CLI and MCP servers",
  "arms": [
    {
      "id": "unity-cli",
      "name": "Official Unity CLI",
      "type": "cli",
      "command": "unity",
      "health_check": "unity status --json"
    },
    {
      "id": "official-mcp",
      "name": "Official Unity MCP",
      "type": "mcp",
      "mcp_server": "unity-editor-mcp",
      "tool_prefix": "mcp__unity-editor-mcp__",
      "health_check": "unity status --json"
    },
    {
      "id": "coplay-mcp",
      "name": "CoplayDev Unity MCP",
      "type": "mcp",
      "mcp_server": "UnityMCP",
      "tool_prefix": "mcp__UnityMCP__",
      "setup_script": "tools/three-way-setup.sh"
    }
  ],
  "trial_defaults": {
    "concurrency": "serial",
    "scene_strategy": "auto",
    "timeout_seconds": 300
  }
}
```

### 2. Validate Arm Health (`mcp-cocktail doctor`)
Probe CLI binary PATHs, stdio MCP `initialize` capabilities, HTTP endpoints, and WebSocket
listeners to report an honest status summary:

```bash
mcp-cocktail doctor
```

Reports:
- 🟢 `[READY]` (health check passed, or an MCP `initialize` handshake was acknowledged)
- 🟡 `[BOUND_ONLY (P4)]` (something is listening, but it is not a usable MCP session — unauthenticated, unregistered, not speaking MCP at all, or accepting connections and then never answering)
- 🟡 `[WRONG_PROJECT (P4)]` (arm is live and healthy, but serving a different project than this workspace)
- 🟠 `[NOT_RUNNING]` (the tool is installed and answered — its backend is down. Start it, or fall back to the CLI)
- 🟠 `[UNCONFIGURED]` (unreachable *and* its setup script is missing; or not probed at all, because
  the arm has no automatable check or could not be tied to a real upstream project)
- 🔴 `[OFFLINE]` (binary not on PATH, or the port is unreachable — no evidence it is installed)

Arms that are not installed carry their acquisition route on the same line, so a survey entry you
were never meant to have is distinguishable from something that broke. `doctor` also warns when
two arms report READY on the same binary — three separate Unity CLI projects all install an
executable named `unity-cli`, and only one of them can own that name on PATH.

### 2b. Obtain the Missing Arms (`mcp-cocktail install`)

```bash
mcp-cocktail install                      # every arm
mcp-cocktail install hatayama-loop        # just this one
```

Prints the documented install command, the editor-side package URL, the harness registration
snippet, and the gotchas — for each arm, sourced from that project's own docs. It **prints steps
and never runs them**: these install third-party software, and several need choices only you can
make (which Unity project, which port).

`doctor` reports and exits 0; a manifest is a survey of competing arms, so it does not
fail merely because some arm is down. To assert on the arms you actually depend on:

```bash
mcp-cocktail doctor --require official-unity-cli --require official-unity-mcp
```

Exits `1` if a required arm is not READY, `2` if a requirement names an unknown arm or the
workspace has no manifest at all.

### 3. Native MCP Server Interface (`mcp-cocktail serve`) & Transparent Proxy (`mcp-cocktail proxy`)
Mount `mcp-cocktail` directly into your agent's MCP config (`.claude/settings.json` or `mcp.json`) to expose native tools or wrap target MCP servers:

```json
{
  "mcpServers": {
    "mcp-cocktail": {
      "command": "mcp-cocktail",
      "args": ["serve"]
    },
    "unity-editor-mcp": {
      "command": "mcp-cocktail",
      "args": ["proxy", "--", "unity-editor-mcp"]
    }
  }
}
```

Exposes:
- `mcp__mcp-cocktail-server__note_friction`
- `mcp__mcp-cocktail-server__check_guardrail`
- `mcp__mcp-cocktail-server__get_scorecard`
- `mcp__mcp-cocktail-server__run_trial`

### 4. Generate Multi-Arm Trial Briefs & Subagent Payloads
Create standardized briefs and subagent task payloads for subagents to execute the same task independently across defined arms:

```bash
# Standard serial trial run (< 1s instant baseline scene reload)
mcp-cocktail run T-001 "Build scene hierarchy for vehicle physics" --exec auto

# Visual comparison mode (leaves temporary scene files for human Unity Editor review)
mcp-cocktail run T-001 "Build scene hierarchy" --compare-visual
```

Generates:
- `docs/trials/T-001/brief-unity-cli.md`
- `docs/trials/T-001/brief-official-mcp.md`
- `docs/trials/T-001/trial-meta.json`
- `docs/trials/T-001/trial-tasks.json`

### 5. Log Friction & Mine Transcripts for P1-P5 Patterns
Subagents or humans can capture friction observations mid-task:

```bash
mcp-cocktail note "CLI command ignores positional table filter silently" --cost 15
```

Mine session transcripts to rank tool usage, identify error clusters, and auto-detect recurring trap patterns (**P1** Startup Snapshot, **P2** Confident Wrong Answer, **P3** Termination $\neq$ Completion, **P4** Green Light, **P5** Ignored Arguments):

```bash
mcp-cocktail mine sweep
mcp-cocktail mine stats <session-uuid>
```

---

## 🔄 The 4 RSI Exhaust Pipelines

When an agent encounters a bug, silent failure, or trap in a tool arm, `mcp-cocktail` generates 4 distinct, purpose-built exhaust deliverables:

| Exhaust Pipeline | Target Audience | Format / Location | Action Taken |
|---|---|---|---|
| **1. Machine Guardrail** | Active session & future local agents | `traps.json` | Weakness Maximization computes a regex matcher + warning payload (< 5ms interception). |
| **2. In-Repo Guidance** | Humans & agents in the repo | `DOMAIN-NOTES.md` | Promoted into structured pattern entries (**P1-P5**). Teaches agents *how* to use the tools correctly. |
| **3. Open-Source Patch** | Community MCPs / CLIs | Subagent Task Spec (`generate_patch_task`) | Spawns a subagent task to write a failing test, fix the source code (`CoplayDev/unity-mcp`), and open a PR. |
| **4. Upstream Vendor Draft** | Vendor engineering teams | `docs/upstream/*.md` (`mcp-cocktail upstream`) | Generates structured markdown issue templates with verbatim payloads, step sequences, and diagnostic PID/socket evidence. |

---

## 🔬 Theoretical Foundation: Weakness Maximization (Bennett, 2023)

Standard AI theory often relies on Ockham’s Razor or Minimum Description Length (MDL) — assuming that the *shortest* hypothesis is the most likely to generalize.

As proven by **Michael Timothy Bennett (2023)** in *"The Optimal Choice of Hypothesis Is the Weakest, Not the Shortest"* ([arXiv:2301.12987v4](https://arxiv.org/abs/2301.12987)):
> Compression/length is neither necessary nor sufficient for generalization. Instead, to maximize the probability that an inferred hypothesis generalizes, it is necessary and sufficient to select the **WEAKEST** valid hypothesis — the explanation with maximum generality (least specificity) that remains consistent with observations.

### How `mcp-cocktail` Applies Weakness Maximization:
- An over-fitted guardrail rule (e.g. matching `unity command --foo --bar --baz`) fails to protect agents calling `unity command --other`.
- `mcp-cocktail` uses the **Rule of Least Specificity** in `mcp_cocktail.weakness`: it generalizes raw friction observations into the broadest valid regex matchers that maximize coverage over potential tool call spaces while maintaining zero false positives on safe/read-only calls.

```bash
mcp-cocktail scorecard --rsi
```

---

## 📁 Architecture & Data Layout

```
my-project/
├── mcp-cocktail.json              # 1. Manifest: Arms, health checks, CLI commands, capabilities
├── traps.json                     # 2. Rule Store: Active PreToolUse trap rules & matchers
├── .claude/
│   └── settings.json              # 3. Client Config: PreToolUse hook pointing to mcp-cocktail check
└── docs/
    ├── findings-inbox.md          # 4. Raw Friction Inbox: Mid-task append-only notes
    ├── tooling-scorecard.md       # 5. Synthesized Scorecard: Automated ranking table
    ├── upstream/                  # 6. Upstream Vendor Bug Reports: Feedback drafts for official tools
    └── trials/                    # 7. Benchmark Data Store: Trial briefs, meta, tasks, and reports
        └── T-001/
            ├── brief-unity-cli.md
            ├── unity-cli.md
            ├── trial-meta.json
            └── trial-tasks.json
```

---

## 🎮 Reference Datasets

The Unity domain ships in two halves.

The **preset** — what `setup --preset unity` actually copies into your workspace — lives inside
the package at `src/mcp_cocktail/presets/unity/`, so it travels in the wheel:
- Multi-arm evaluation manifest (`manifest.json`) with 11 curated arms
- Comprehensive Unity trap rule store (`traps.json`)
- Domain helper scripts (`tools/`), provisioned to `<workspace>/tools/`

The **reference dataset** — the evidence behind the preset — stays in the repo at
`examples/unity/`:
- Historic trial reports and scorecard (`examples/unity/docs/trials/`)
- Historical research log (`examples/unity/UNITY-TOOLING-NOTES.md`)
- Setup guides and upstream bug drafts (`examples/unity/docs/`)
