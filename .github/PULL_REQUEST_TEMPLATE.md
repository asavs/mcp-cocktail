## Description

Provide a clear, concise summary of the changes introduced by this Pull Request.

- **Type of Contribution:**
  - [ ] New Domain Preset (`examples/<domain>/`)
  - [ ] New / Updated Guardrail Rules (`traps.json`)
  - [ ] Core Engine Feature / Improvement (`src/mcp_cocktail/`)
  - [ ] Bug Fix / Refactoring
  - [ ] Documentation / Examples

---

## What Changes Were Made?

- Detailed bulleted list of changes made in this PR.

---

## Domain & Capability Details (If Adding/Updating a Preset)

- **Domain Name:** (e.g. `postgres`, `docker`, `figma`)
- **Tool Arms Included:**
  - [ ] Vendor CLI Arm
  - [ ] Official MCP Server Arm
  - [ ] Community MCP Server Arm(s)
- **Health Checks & Probes Verified:**
  - Ran `mcp-cocktail doctor` to verify arm diagnostic status.

---

## Checklist

- [ ] All unit and integration tests pass (`python -m pytest tests/`).
- [ ] Guardrail selftest passes (`mcp-cocktail check --selftest`).
- [ ] No conversational meta-narration (*"in this session..."*, *"I modified..."*) in permanent documentation files.
- [ ] Documentation and `README.md` updated if applicable.
