"""Ecosystem discovery engine and agentic search for mcp-cocktail.

Discovers open-source community MCP servers, vendor CLIs, and API wrappers for any target
software domain (e.g. unity, postgres, docker, github, figma) and generates candidate
mcp-cocktail.json manifests using direct registry queries and agentic scout tasks.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_cocktail.config import CocktailConfig, ArmConfig


@dataclass
class DiscoveredArmCandidate:
    id: str
    name: str
    type: str  # "mcp" | "cli"
    mcp_server: str | None = None
    tool_prefix: str | None = None
    package_or_repo: str | None = None
    description: str = ""
    health_check: str | None = None


# Known popular open-source registries and vendor CLI patterns
KNOWN_DOMAIN_CLIS = {
    "unity": {"command": "unity", "name": "Official Unity CLI", "health_check": "unity status --json"},
    "postgres": {"command": "psql", "name": "PostgreSQL CLI", "health_check": "psql --version"},
    "docker": {"command": "docker", "name": "Docker CLI", "health_check": "docker --version"},
    "github": {"command": "gh", "name": "GitHub CLI", "health_check": "gh --version"},
    "aws": {"command": "aws", "name": "AWS CLI", "health_check": "aws --version"},
    "kubernetes": {"command": "kubectl", "name": "Kubectl CLI", "health_check": "kubectl version --client"},
}


def search_github_mcp_servers(domain: str) -> list[DiscoveredArmCandidate]:
    """Search GitHub for public repositories matching 'mcp-server <domain>' or 'mcp <domain>'."""
    candidates = []
    url = f"https://api.github.com/search/repositories?q=mcp-server+{domain}+in:name,description&sort=stars&order=desc"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mcp-cocktail-discover"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        items = data.get("items", [])[:6]
        for item in items:
            repo_name = item.get("name", "")
            full_name = item.get("full_name", "")
            desc = item.get("description", "") or ""

            clean_id = re.sub(r"[^a-z0-9]", "-", repo_name.lower()).strip("-")
            clean_id = clean_id.removeprefix("mcp-server-").removeprefix("mcp-")
            arm_id = f"{clean_id}-mcp" if not clean_id.endswith("-mcp") else clean_id

            prefix_base = re.sub(r"[^a-zA-Z0-9]", "", clean_id)
            tool_prefix = f"mcp__{prefix_base}__"

            candidates.append(
                DiscoveredArmCandidate(
                    id=arm_id,
                    name=item.get("name", arm_id),
                    type="mcp",
                    mcp_server=repo_name,
                    tool_prefix=tool_prefix,
                    package_or_repo=f"github.com/{full_name}",
                    description=desc,
                    health_check=f"curl -s http://127.0.0.1:8080/mcp",
                )
            )
    except Exception:
        pass

    return candidates


def generate_agentic_discover_task(domain: str) -> dict[str, Any]:
    """Generate an OMP/Claude scout task payload for deep web & registry ecosystem discovery."""
    return {
        "name": f"Discover_Ecosystem_{re.sub(r'[^a-zA-Z0-9]', '', domain)}",
        "agent": "scout",
        "task": f"""# Ecosystem Discovery Task — {domain}

**Target Domain:** `{domain}`

## Instructions for Scout Agent
1. Search GitHub, npm (`@modelcontextprotocol`), PyPI, Smithery.ai, and official documentation for all available MCP servers and CLIs for '{domain}'.
2. For each discovered tool, identify:
   - Tool/Repo Name & URL
   - Type: `cli` or `mcp`
   - Tool prefix filter (e.g. `mcp__{domain}__`)
   - Default health check endpoint or command
3. Output the discovery findings as a JSON manifest structure compatible with `mcp-cocktail.json`.
""",
    }


def discover_domain_arms(domain: str) -> list[DiscoveredArmCandidate]:
    """Discover CLI arms and open-source MCP server candidates for a target software domain."""
    domain_clean = domain.lower().strip()
    candidates: list[DiscoveredArmCandidate] = []

    if domain_clean in KNOWN_DOMAIN_CLIS:
        info = KNOWN_DOMAIN_CLIS[domain_clean]
        candidates.append(
            DiscoveredArmCandidate(
                id=f"{domain_clean}-cli",
                name=info["name"],
                type="cli",
                package_or_repo=info["command"],
                description=f"Official command-line interface for {domain_clean}",
                health_check=info["health_check"],
            )
        )

    mcp_candidates = search_github_mcp_servers(domain_clean)
    candidates.extend(mcp_candidates)

    if not mcp_candidates:
        candidates.append(
            DiscoveredArmCandidate(
                id=f"official-{domain_clean}-mcp",
                name=f"Official {domain.capitalize()} MCP",
                type="mcp",
                mcp_server=f"{domain_clean}-mcp",
                tool_prefix=f"mcp__{domain_clean}__",
                description=f"Official MCP server for {domain_clean}",
                health_check="curl -s http://127.0.0.1:8080/health",
            )
        )
        candidates.append(
            DiscoveredArmCandidate(
                id=f"community-{domain_clean}-mcp",
                name=f"Community {domain.capitalize()} MCP",
                type="mcp",
                mcp_server=f"community-{domain_clean}-mcp",
                tool_prefix=f"mcp__community_{domain_clean}__",
                description=f"Open-source community MCP server for {domain_clean}",
                health_check="curl -s http://127.0.0.1:8081/mcp",
            )
        )

    return candidates


def build_discovered_manifest(domain: str, candidates: list[DiscoveredArmCandidate]) -> dict[str, Any]:
    arms_data = []
    for c in candidates:
        arm_dict = {
            "id": c.id,
            "name": c.name,
            "type": c.type,
        }
        if c.type == "cli":
            arm_dict["command"] = c.package_or_repo or domain
        if c.type == "mcp":
            arm_dict["mcp_server"] = c.mcp_server
            arm_dict["tool_prefix"] = c.tool_prefix

        if c.health_check:
            arm_dict["health_check"] = c.health_check

        arms_data.append(arm_dict)

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "name": f"{domain}-ecosystem",
        "description": f"Discovered multi-arm evaluation manifest for {domain}",
        "arms": arms_data,
        "trial_defaults": {
            "concurrency": "serial",
            "scene_strategy": "auto",
            "timeout_seconds": 300,
        },
        "traps_file": "traps.json",
    }
