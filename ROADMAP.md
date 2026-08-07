# mcp-cocktail Roadmap

This document outlines the architectural vision and development roadmap for `mcp-cocktail`.

---

## 🟢 Current State (v0.2.0)

- **Domain-Agnostic Core:** Configurable workspace manifest (`mcp-cocktail.json`) and rule store (`traps.json`).
- **Real-Time Guardrail Engine:** PreToolUse hook execution (< 5ms stdin/stdout interception) with read-only verb filtering and session cooldown state.
- **Weakness Maximization Engine:** Bennett (2023) theoretical foundation ([arXiv:2301.12987v4](https://arxiv.org/abs/2301.12987)) for auto-deriving weakest valid rules from friction notes.
- **Native Stdio MCP Server:** In-memory JSON-RPC MCP server (`mcp-cocktail serve`) exposing `check_guardrail`, `note_friction`, `get_scorecard`, and `run_trial`.
- **Active Harness Auto-Detection:** 1-command domain setup (`mcp-cocktail setup`) that detects the active runtime environment (Claude Code, Oh My Pi, Cursor) without workspace folder pollution.
- **Multi-Arm Subagent Runner:** Benchmark generation with scene strategy selection (`instant_reload` vs `temp_scene`).
- **P1-P5 Trap Pattern Miner:** Automated transcript scanning for the 5 core failure shapes.
- **4 Exhaust Pipelines:** Machine guardrails (`traps.json`), in-repo guidance (`DOMAIN-NOTES.md`), open-source subagent patch tasks (`generate_patch_task`), and upstream vendor bug drafts (`docs/upstream/`).

---

## 🚀 Future Tiers

```
  ┌─────────────────────────────────────────────────────────────┐
  │                 mcp-cocktail Evolution Roadmap              │
  └──────────────────────────────┬──────────────────────────────┘
                                 │
   ┌───────────────────────┬─────┴─────────────┬────────────────────────┐
   ▼                       ▼                   ▼                        ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ Tier 1:          │  │ Tier 2:          │  │ Tier 3:          │  │ Tier 4:          │
│ Microsecond      │  │ Inline MCP Proxy │  │ Autonomous Swarm │  │ Federated RSI    │
│ C/Rust Engine    │  │ & Router         │  │ & PR Patch Bot   │  │ Global Network   │
└──────────────────┘  └──────────────────┘  └──────────────────┘  └──────────────────┘
```

### Tier 1: Microsecond Guardrail Core (C / Rust Engine)
- **Goal:** Sub-millisecond PreToolUse hook execution with zero runtime dependencies.
- **Deliverables:**
  - Standalone compiled C/Rust executable (`cocktail-check` $< 500\text{ KB}$).
  - Sub-100 microsecond ($0.1\text{ ms}$) evaluation over `traps.json`.
  - $< 1\text{ MB}$ RAM footprint with zero interpreter startup latency.

### Tier 2: Inline MCP Proxy & Router
- **Goal:** Transparent MCP JSON-RPC network proxying.
- **Deliverables:**
  - Inline transport proxy (`mcp-cocktail proxy`) between agent harnesses and downstream target MCP servers over stdio/HTTP.
  - In-flight parameter validation, dynamic tool routing, and invisible telemetry logging without harness hook configuration.

### Tier 3: Autonomous Swarm Benchmarking & PR Patch Bot
- **Goal:** Automated end-to-end open-source tool patching.
- **Deliverables:**
  - Parallel subagent swarm runner (`mcp-cocktail swarm`) executing benchmark waves across arms.
  - Automated TDD patch generator spawning subagents to write failing reproduction tests, patch open-source tool code, and submit GitHub Pull Requests automatically (Exhaust 3 pipeline).

### Tier 4: Global Federated RSI Network
- **Goal:** Cross-repository collective intelligence sharing.
- **Deliverables:**
  - Rule registry sync (`mcp-cocktail sync`) allowing developers and agents to pull and publish verified `traps.json` rules globally.
  - Automatic cross-repository protection against newly discovered vendor tool bugs.
