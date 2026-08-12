# mcp-cocktail

A domain-agnostic, Recursive Self-Improvement (RSI) framework for benchmarking, evaluating, and injecting real-time guardrails across competing MCP servers, CLIs, and AI agent tools.

When software vendors take months or years to release official Model Context Protocol (MCP) servers or command-line tools, open-source communities fill the vacuum with unofficial MCPs, wrappers, and CLIs. This fragmentation leads to competing tools ("arms") with varying degrees of stability, silent failures, and trap behavior.

`mcp-cocktail` provides the machinery to:
- **Inject Real-Time PreToolUse Guardrails:** Intercept tool calls right *before* a known trap is sprung (`mcp-cocktail check` / `install-hook`).
- **Plan Multi-Arm Benchmarks:** Generate consistent briefs and task payloads across available MCPs and CLIs (`mcp-cocktail plan`) for an external harness to execute.
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
  "description": "Multi-arm evaluation manifest for Unity CLI, MCP, and GUI automation",
  "arms": [
    {
      "id": "computer-use",
      "name": "Unity Editor via Computer Use",
      "type": "gui",
      "capabilities": ["editor-gui-automation", "visual-inspection"],
      "probe": "none",
      "probe_reason": "Computer use is supplied by the active agent harness."
    },
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

Reports layered evidence rather than treating every answering socket as ready:
- `[OPERATIONAL]` a bounded target operation completed through this arm against the intended project
- `[TRANSPORT ONLY]` the process/protocol answered, but no target operation was proven
- `[DELIVERY UNVERIFIED]` the shared Unity backend answered, but this arm's delivery route was not exercised
- `[DEGRADED]` transport exists but a target operation failed or timed out
- `[EXECUTION REPORTED]` an external adapter reported capability success; useful provenance, but not independent live-health proof and not accepted by `--require`
- `[AMBIGUOUS IDENTITY]` multiple arm definitions resolve to the same executable name
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

Coplay's HTTP bridge is different: it uses the fixed machine-wide port `127.0.0.1:8080` even
though Unity projects are independent. Before adding or starting that package, run
`mcp-cocktail install coplay-mcp` from the intended project. Cocktail performs a read-only
exact-project probe and blocks the install handoff if another project—or an unidentifiable
listener—already owns the port. Do not let a new Editor auto-start over that warning.

### 2a. Check Prerequisites (`mcp-cocktail preflight`)

```bash
mcp-cocktail preflight
```

`doctor` answers *is this arm running*. `preflight` answers *could I even have it* — a different
question with a different fix. An arm needing Node 24 on a Node 22 machine reports `OFFLINE`
exactly like an arm nobody has installed yet, so eleven identical red rows hide the handful that
are one command away from working. Requirements are declared in the manifest (`requires`), checked
against detected tool versions and the workspace's `ProjectSettings/ProjectVersion.txt`.

Arms with no declared requirements are listed separately and explicitly: preflight cannot vouch
for them, which means nobody recorded what they need — not that they need nothing.

### 2b. Obtain the Missing Arms (`mcp-cocktail install`)

```bash
mcp-cocktail install                      # every arm
mcp-cocktail install hatayama-loop        # just this one
```

Prints the documented install command, the editor-side package URL, the harness registration
snippet, and the gotchas — for each arm, sourced from that project's own docs. It **prints steps
and never runs them**: these install third-party software, and several need choices only you can
make (which Unity project, which port).

Every step is tagged with who can perform it, because the boundary is not where it looks:

| Tag | Meaning |
|---|---|
| `[agent: shell]` | a command an agent can run |
| `[agent: edit file]` | a file an agent can edit — adding a UPM package looks like a GUI action, but `Packages/manifest.json` is plain JSON |
| `[you: in the Editor]` | genuinely not automatable, e.g. realvirtual's "Download Python Server" button |

Across the Unity preset that is **17 of 23 steps an agent can perform**. `--json` emits the whole
plan as structured data so an agent acts on it rather than parsing prose.

`doctor` reports and exits 0; a manifest is a survey of competing arms, so it does not
fail merely because some arm is down. To assert on the arms you actually depend on:

```bash
mcp-cocktail doctor --require official-unity-cli --require official-unity-mcp
mcp-cocktail doctor --capability editmode-tests --require coplay-mcp:editmode-tests
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
- `mcp__mcp-cocktail-server__plan_trial`
- `mcp__mcp-cocktail-server__run_trial`

### 4. Plan Multi-Arm Trials
Create standardized briefs and harness-neutral task payloads. Cocktail deliberately does not
launch Codex, Claude, OMP, or another harness: their process, cancellation, and permission models
are not interchangeable. It does provide one executor-neutral lifecycle that adapters can call,
so safety and evidence semantics do not have to be reimplemented by every harness:

```bash
# Plan a serial trial (generates files only)
mcp-cocktail plan T-001 "Build scene hierarchy for vehicle physics"

# Ask the executing harness to use per-arm temporary scenes for visual comparison
mcp-cocktail plan T-001 "Build scene hierarchy" --compare-visual
```

`mcp-cocktail run` remains a backward-compatible alias for `plan`, but prints that it does
not execute agents. The legacy `--exec` option now exits with an error before generating
artifacts: earlier releases recorded the option but never invoked a harness. The generated
`trial-tasks.json` is the explicit handoff boundary for Codex, Claude, OMP, or another agent
harness.

When `--capability` is omitted, each arm's stage uses its first declared non-transport task
capability (for example, `editor-automation`, not `mcp`). The exact value appears as
`evidence_capability` in `trial-tasks.json`, so adapters know which
`doctor --require ARM:CAPABILITY` gate the resulting evidence can support.

An adapter drives the plan through machine-readable lifecycle commands:

```bash
mcp-cocktail trial acquire T-001 --owner codex-adapter
mcp-cocktail trial begin T-001 --stage arm-coplay-mcp --arm coplay-mcp --owner codex-adapter --token TOKEN
mcp-cocktail trial finish T-001 --stage arm-coplay-mcp --arm coplay-mcp --owner codex-adapter --token TOKEN --outcome succeeded --evidence '{"kind":"test-run","summary":"7/7 passed"}'
mcp-cocktail trial release T-001 --owner codex-adapter --token TOKEN
```

The lifecycle enforces dependency and capability-circuit admission, a token-owned workspace/Editor
mutation lease, per-attempt before/after inventories, and cross-arm evidence/artifact provenance.
Every planned arm is treated as potentially mutating and therefore shares the lease unless a future
executor provisions a genuinely isolated workspace. This means agents may investigate in parallel,
but mutations against one Unity project are serial. Cocktail detects changes; it never silently
resets, deletes, or rolls back user files. Expired leases are not stolen automatically.
If an adapter crashes, an operator can explicitly recover a proven-expired lease with
`mcp-cocktail trial recover T-001 --owner operator --token EXPECTED_TOKEN`; Cocktail requires
the exact old token and writes durable recovery evidence before removing it.

Trial IDs are single filesystem-safe identifiers such as `T-001`. Planning atomically reserves
the ID and refuses to replace an existing trial directory, so concurrent planners cannot overwrite
one another's briefs or evidence. Choose a new ID to rerun a trial.

GUI arms use `"type": "gui"`. Their generated briefs require exclusive mouse/keyboard
control, serial access to a shared Editor, before-and-after screenshots, and visible state
read-back after mutations. Cocktail records `requires_exclusive_input: true` in their task
payloads; the external agent harness that executes those payloads must enforce it.
An unfiltered plan now generates all 12 preset briefs, including `computer-use`; select
`--capability editor-gui-automation` for a GUI-only trial or name arms explicitly to exclude it.
`doctor` reports this arm as `EXTERNAL_CHECK_REQUIRED`: it cannot honestly infer either harness
availability or Unity responsiveness from a process or socket, and does not claim the arm READY.

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
- Multi-arm evaluation manifest (`manifest.json`) with 12 curated arms, including computer use
- Comprehensive Unity trap rule store (`traps.json`)
- Domain helper scripts (`tools/`), provisioned to `<workspace>/tools/`

The **reference dataset** — the evidence behind the preset — stays in the repo at
`examples/unity/`:
- Historic trial reports and scorecard (`examples/unity/docs/trials/`)
- Historical research log (`examples/unity/UNITY-TOOLING-NOTES.md`)
- Setup guides and upstream bug drafts (`examples/unity/docs/`)
