# Changelog

All notable changes to mcp-cocktail are recorded here. Versions follow Semantic Versioning;
release-candidate suffixes use Python's PEP 440 spelling in package metadata.

## 0.4.0rc2 — 2026-08-12

Acceptance follow-up after a concurrent Unity project exposed Coplay's fixed-port collision risk.

- Doctor now gives an exact-project identity mismatch the explicit `WRONG_PROJECT` status instead
  of folding it into generic degradation.
- `mcp-cocktail install coplay-mcp` now provides the pinned UPM route and refuses to proceed when
  port 8080 is occupied without independently proving this project is operational.
- The provisioned three-way helper likewise refuses to reuse or replace an answering port 8080
  unless Doctor proves it belongs to the requested project.
- Lease recovery errors now retain the CLI's structured `{ok:false,error}` response instead of
  escaping as a traceback.
- Unfiltered plans record each stage under a declared task capability (for example,
  `editor-automation`) rather than the undeclared `benchmark-task` placeholder. The chosen value
  is exposed as `evidence_capability` in `trial-tasks.json`.
- Official Pipeline acquisition notes now call out Unity Cloud/package-registry authentication;
  Cocktail does not mistake a printed remedy for proof it succeeded.

## 0.4.0rc1 — 2026-08-12

This release candidate turns Cocktail's multi-arm trial feature from a brief generator with
shallow health checks into an honest, harness-neutral orchestration core. Cocktail still does
not launch agents itself. Codex, Claude, OMP, and other runtimes execute plans through the same
explicit lifecycle and evidence contract.

### Added

- A `mcp-cocktail trial` lifecycle with `status`, `acquire`, `renew`, `recover`, `begin`,
  `finish`, and `release` actions for external harness adapters.
- Token-owned, workspace-wide mutation leases with bounded renewal, explicit stale recovery,
  exact-token validation, and durable recovery auditing.
- Dependency-aware staged trial state, fallback-arm attempts, cross-arm artifact provenance,
  verification evidence, and capability-scoped circuit breakers.
- Non-destructive, per-attempt workspace inventories covering tracked, untracked, and Unity
  `.meta` files while excluding volatile generated caches.
- A durable operational-evidence journal and retry outbox for journal delivery failures.
- Capability-specific Doctor evaluation with freshness, current-project identity, current arm
  availability, clock-skew, and recent-failure handling.
- A serial computer-use Unity arm for visible GUI automation and visual inspection.

### Changed

- `mcp-cocktail plan` is the canonical planning command. The legacy `run` command is an
  explicitly disclosed planning alias and does not execute agents.
- The legacy `--exec` option now fails before writing artifacts instead of recording an
  execution mode that Cocktail did not implement.
- Doctor distinguishes `OPERATIONAL`, `TRANSPORT_ONLY`, `TARGET_ONLY`, `DEGRADED`,
  `AMBIGUOUS_IDENTITY`, `CAPABILITY_UNKNOWN`, and `EXECUTION_REPORTED` evidence.
- A successful MCP initialize, open socket, installed executable, or external adapter report no
  longer earns independent operational readiness.
- Unity target probes validate the intended project and perform bounded target operations.
- Every planned arm claims the shared workspace mutation resource unless a future executor
  provisions genuine isolation.
- Trial publication and state updates use validated identifiers, locked atomic writes, and
  overwrite refusal.

### Migration notes from 0.3

- Replace automation that treats `mcp-cocktail run` as execution with `mcp-cocktail plan`, then
  drive `trial-tasks.json` through the `mcp-cocktail trial` lifecycle.
- Python 3.10 or newer is now declared. Earlier releases claimed Python 3.8 support despite using
  Python 3.10 union-type syntax.
- Remove `--exec`; it is intentionally unsupported.
- Update Doctor consumers to require `OPERATIONAL` for independently proven live health.
  `EXECUTION_REPORTED` is audit provenance, not a green health result.
- Bare `doctor` remains a survey and exits successfully when optional arms are unavailable. Use
  `--require ARM` or `--require ARM:CAPABILITY` for dependencies.
- Do not overlap workspace or Unity mutations. Acquire the declared shared-resource lease before
  `begin`, retain it until `finish`, and then release it.

### Acceptance gate for 0.4.0 final

The final `v0.4.0` tag is gated on a real Unity trial that demonstrates:

1. Planning and lifecycle handoff from a clean installation of the built wheel.
2. Correct-project operational probing without false READY results.
3. Serialized mutation and rejection of a competing lease holder.
4. Successful evidence/artifact capture and per-attempt workspace deltas.
5. Honest degradation when Unity becomes unresponsive, without restarting or disturbing the
   shared Editor.
6. Explicit stale-lease recovery after a simulated adapter crash.

## 0.3.0

- Previous published development release.
