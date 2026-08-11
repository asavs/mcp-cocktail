"""Rule registry sync and global domain scorecard aggregator for mcp-cocktail.

Bridges local scorecards & weakness rules with global community registries.
Enables non-destructive pulling of crowdsourced domain guardrails (pull)
and packaging of locally derived RSI rules for upstream contribution (push).
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

from mcp_cocktail.config import CocktailConfig, TrapsConfig, TrapRule, resolve_traps_path
from mcp_cocktail.scorecard import propose_rsi_guardrails

# Serves the same preset tree the wheel ships, so a `sync pull` and a
# `setup --preset` agree on what the domain's rules are.
REMOTE_REGISTRY_BASE_URL = (
    "https://raw.githubusercontent.com/asavs/mcp-cocktail/main/src/mcp_cocktail/presets"
)


def fetch_remote_domain_traps(domain: str) -> dict[str, Any] | None:
    """Fetch live domain traps.json from the remote community registry."""
    url = f"{REMOTE_REGISTRY_BASE_URL}/{domain}/traps.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mcp-cocktail-sync"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def merge_traps_config(existing_raw: dict[str, Any], remote_raw: dict[str, Any]) -> dict[str, Any]:
    """Non-destructively merge remote weakness rules into local traps.json."""
    merged = dict(existing_raw)
    existing_rules = merged.get("rules", [])
    existing_ids = {r.get("id") for r in existing_rules if isinstance(r, dict)}

    remote_rules = remote_raw.get("rules", [])
    added_count = 0

    for r_rule in remote_rules:
        if isinstance(r_rule, dict) and r_rule.get("id") not in existing_ids:
            existing_rules.append(r_rule)
            added_count += 1

    merged["rules"] = existing_rules
    merged["_added_rules_count"] = added_count
    return merged


def pull_domain_rules(domain: str, root_dir: Path | str | None = None) -> tuple[bool, str]:
    """Pull and non-destructively merge latest community weakness guardrails into local traps.json."""
    root = Path(root_dir) if root_dir else Path.cwd()
    local_traps_path = resolve_traps_path(root)

    remote_data = fetch_remote_domain_traps(domain)
    if not remote_data:
        return False, f"Could not fetch remote community rules for domain '{domain}' from registry."

    if local_traps_path.exists():
        try:
            local_raw = json.loads(local_traps_path.read_text(encoding="utf-8"))
        except Exception:
            local_raw = {"version": "1.0", "domain": domain, "rules": []}
    else:
        local_raw = {"version": "1.0", "domain": domain, "rules": []}

    merged = merge_traps_config(local_raw, remote_data)
    added_count = merged.pop("_added_rules_count", 0)

    local_traps_path.parent.mkdir(parents=True, exist_ok=True)
    local_traps_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")

    return True, f"Successfully synced community rules for '{domain}'. Merged {added_count} new guardrail rule(s) into {local_traps_path}."


def push_domain_contributions(domain: str, root_dir: Path | str | None = None) -> tuple[bool, str]:
    """Package locally derived weakness rules and friction notes for upstream PR contribution."""
    root = Path(root_dir) if root_dir else Path.cwd()
    docs_dir = root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    candidates = propose_rsi_guardrails(root_dir=root)
    bundle_path = docs_dir / f"sync-contribution-bundle-{domain}.json"

    bundle = {
        "domain": domain,
        "proposed_rules_count": len(candidates),
        "proposed_rules": candidates,
        "instructions": "Submit this bundle in a PR to src/mcp_cocktail/presets/<domain>/traps.json on the mcp-cocktail registry repository.",
    }

    bundle_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    return True, f"Packaged {len(candidates)} locally derived weakness rule candidate(s) into {bundle_path} for upstream PR submission."
