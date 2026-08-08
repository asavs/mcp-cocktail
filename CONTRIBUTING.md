# Contributing to mcp-cocktail

Thank you for your interest in contributing to `mcp-cocktail`!

`mcp-cocktail` is a domain-agnostic Recursive Self-Improvement (RSI) engine designed to benchmark competing MCP servers and CLIs, capture friction mid-task, and enforce real-time PreToolUse guardrails.

While the project started with a deep reference suite for Unity (`examples/unity/`), **the framework is 100% domain-agnostic**. We welcome contributions for all software domains—including PostgreSQL, Docker, Kubernetes, AWS, Figma, Blender, Salesforce, and beyond!

---

## 🌐 How to Pool & Crowdsource Domain Intelligence (e.g. Unity, Postgres)

To prevent developers and AI agents around the world from rediscovering the same bugs, deadlocks, and silent drops from scratch, `mcp-cocktail` provides **4 mechanisms for pooling collective domain intelligence**:

```
  ┌─────────────────────────────────────────────────────────────┐
  │                 Community Domain Pooling                    │
  └──────────────────────────────┬──────────────────────────────┘
                                 │
   ┌───────────────────────┬─────┴─────────────┬────────────────────────┐
   ▼                       ▼                   ▼                        ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ Strategy 1:      │  │ Strategy 2:      │  │ Strategy 3:      │  │ Strategy 4:      │
│ In-Repo Presets  │  │ Automated RSI    │  │ Central Rule Sync│  │ Community Score  │
│ (examples/unity) │  │ Inbox Merging    │  │ (mcp-cocktail    │  │ Leaderboard      │
│                  │  │ (note -> PR)     │  │  sync)           │  │                  │
└──────────────────┘  └──────────────────┘  └──────────────────┘  └──────────────────┘
```

### 1. Upstream Preset Curation (`examples/<domain>/`)
- **How it works:** `examples/<domain>/` acts as the canonical gold-standard preset repository.
- **Pooling Action:** When you or your AI agent discover a new MCP server or CLI quirk, submit a 1-line PR updating `examples/<domain>/traps.json` or `examples/<domain>/cocktail.json`.
- **Benefit:** Anyone running `mcp-cocktail setup --preset <domain>` anywhere in the world instantly receives the pooled collective intelligence of every contributor!

### 2. Automated RSI Inbox Merging (`findings-inbox.md` $\rightarrow$ Weakness Rules)
- **How it works:** When agents work on real-world projects, they log friction via `mcp-cocktail note "..."`.
- **Pooling Action:** Submit your project's `docs/findings-inbox.md` observations. Running `mcp-cocktail scorecard --rsi` auto-aggregates observations and computes **Bennett (2023) Weakness Rules** for the shared domain preset!

### 3. Ecosystem Scorecard Leaderboards (`tooling-scorecard.md`)
- **How it works:** Submit subagent trial reports (`docs/trials/T-xxx/`) back to the repository.
- **Pooling Action:** `mcp-cocktail scorecard` aggregates trial metrics across hundreds of sessions, maintaining an empirical **Leaderboard** of which MCP servers are currently the most reliable for specific workloads (e.g. ShaderGraph, Terrain, Physics, Audio).

### 4. Rule Registry Sync (`mcp-cocktail sync`)
- **How it works:** Pull live crowdsourced trap rules directly into local workspaces without waiting for python package releases:
  ```bash
  # Pull latest crowdsourced weakness guardrails for a domain
  mcp-cocktail sync --domain unity
  ```

---

## 🌟 Ways to Contribute

1. **Add a New Domain Preset (`examples/<domain>/`):** Curate official and open-source MCPs/CLIs for a new software ecosystem.
2. **Contribute Trap Rules (`traps.json`):** Add real-time guardrail rules for unhandled bugs, silent parameter drops, or deadlocks in existing tools.
3. **Enhance Core Engine Modules (`src/mcp_cocktail/`):** Improve transcript mining, stdio MCP proxying, or doctor health probes.
4. **Submit Upstream Bug Reports:** Turn mined friction into reproducible upstream vendor issue drafts.

---

## 📁 1. How to Add a New Domain Preset

To add a new software domain (e.g., `postgres`, `docker`, `figma`):

1. Create a directory under `examples/<domain>/`:
   ```bash
   mkdir -p examples/postgres/docs examples/postgres/tools
   ```

2. Create `examples/<domain>/cocktail.json` defining the available arms:
   ```json
   {
     "$schema": "https://json-schema.org/draft/2020-12/schema",
     "name": "postgres-ecosystem",
     "description": "Multi-arm evaluation manifest for PostgreSQL CLIs and MCP servers",
     "arms": [
       {
         "id": "postgres-cli",
         "name": "PostgreSQL CLI",
         "type": "cli",
         "command": "psql",
         "health_check": "psql --version"
       },
       {
         "id": "official-postgres-mcp",
         "name": "Official Postgres MCP",
         "type": "mcp",
         "mcp_server": "postgres-mcp",
         "tool_prefix": "mcp__postgres__"
       }
     ],
     "trial_defaults": {
       "concurrency": "serial",
       "scene_strategy": "auto",
       "timeout_seconds": 300
     },
     "traps_file": "traps.json"
   }
   ```

3. Create `examples/<domain>/traps.json` with initial guardrail rules for that domain.
4. Create `examples/<domain>/README.md` explaining setup and tool usage for that domain.

---

## 🛡️ 2. How to Contribute Guardrail Rules (`traps.json`)

Guardrail rules protect AI agents from springing known traps right before a tool call executes (< 5ms interception).

Appends rule to `traps.json`:

```json
{
  "id": "cli-flag-binding",
  "message": "TRAP: Positional arguments in tool-cli are ignored silently. Use explicit --flag value syntax.",
  "tool_matcher": "^(Bash|PowerShell)$",
  "target_matcher": "\\btool-cli\\s+command\\b",
  "cooldown_seconds": 0,
  "read_only_ignore": true
}
```

### Applying Bennett (2023) Weakness Maximization
When writing rules, follow the **Rule of Least Specificity** ([arXiv:2301.12987v4](https://arxiv.org/abs/2301.12987)):
> Explanations should be no more specific than necessary.

Formulate the broadest regex matcher that covers potential trap calls without triggering false positives on safe/read-only commands.

---

## 🛠️ Development Setup & Running Tests

1. Clone the repository and install in editable mode:
   ```bash
   git clone https://github.com/asavs/mcp-cocktail.git
   cd mcp-cocktail
   pip install -e .
   ```

2. Run the test suite:
   ```bash
   python -m pytest tests/
   ```

3. Run the guardrail selftest:
   ```bash
   python -m mcp_cocktail check --selftest
   ```

---

## 📋 Pull Request Process

1. Create a descriptive feature branch (`git checkout -b feat/add-postgres-preset`).
2. Ensure all tests pass (`python -m pytest tests/`).
3. Ensure no meta-narration (*"in this session..."*, *"I modified..."*) is present in permanent documentation artifacts.
4. Open a Pull Request on GitHub using the PR template.
