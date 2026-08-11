"""Configuration models and parsers for mcp-cocktail."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ArmConfig:
    id: str
    name: str
    type: str  # "cli", "mcp", "api", etc.
    command: str | None = None
    mcp_server: str | None = None
    tool_prefix: str | None = None
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    setup_script: str | None = None
    # How an operator obtains this arm when it is not installed. A manifest is
    # a survey of competing arms, so most entries in a real preset are things
    # the reader does not have -- without this, doctor can only report OFFLINE
    # and leave them to guess whether that is a broken install or an arm they
    # were never expected to have.
    install_hint: str | None = None
    # Full acquisition record: {method, command, package_url, docs_url, steps,
    # client_config, requires_editor}. Every field optional, because the real
    # ecosystem does not offer one uniform install shape -- some arms are a
    # single `npx`, others are a Unity package plus a separate server process
    # with no shell installer at all, and a schema that insisted on a command
    # string could only be populated by inventing one.
    install: dict[str, Any] = field(default_factory=dict)
    # Whether this arm can be health-checked at all, and if not, why not.
    #   "auto"       -- probe normally (default); a URL health_check is an MCP
    #                   endpoint and must complete a JSON-RPC handshake
    #   "http"       -- the URL is a plain health endpoint, not MCP. 2xx means
    #                   healthy. Demanding a handshake of a liveness ping
    #                   reports a working service as a P4 warning.
    #   "none"       -- real project, but no automatable check exists: the port
    #                   is derived per project, or the transport is WebSocket
    #                   with no HTTP endpoint. Needs probe_reason.
    #   "unverified" -- the entry could not be tied to a real upstream project,
    #                   so any endpoint recorded for it is invented.
    # Probing anyway would manufacture a precise-sounding failure about an
    # endpoint that never existed, which reads as "the server is down" rather
    # than "we cannot substantiate this".
    probe: str = "auto"
    probe_reason: str = ""
    health_check: str | None = None
    # Dotted path into the health check's JSON stdout naming the project each
    # live instance is serving, e.g. "data.instances[].project". Lets doctor
    # distinguish "bound" from "bound to *this* workspace".
    binding_path: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArmConfig:
        known = {
            "id", "name", "type", "command", "mcp_server",
            "tool_prefix", "description", "capabilities", "env",
            "setup_script", "install_hint", "install", "probe", "probe_reason",
            "health_check", "binding_path"
        }
        extra = {k: v for k, v in data.items() if k not in known}
        caps = data.get("capabilities", [])
        if isinstance(caps, str):
            caps = [caps]

        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            type=data.get("type", "cli"),
            command=data.get("command"),
            mcp_server=data.get("mcp_server"),
            tool_prefix=data.get("tool_prefix"),
            description=data.get("description", ""),
            capabilities=caps,
            env=data.get("env", {}),
            setup_script=data.get("setup_script"),
            install_hint=data.get("install_hint"),
            install=data.get("install") or {},
            probe=data.get("probe", "auto"),
            probe_reason=data.get("probe_reason", ""),
            health_check=data.get("health_check"),
            binding_path=data.get("binding_path"),
            extra=extra,
        )


@dataclass
class TrialDefaults:
    concurrency: str = "serial"  # "serial" | "parallel"
    scene_strategy: str = "auto"  # "auto" | "instant_reload" | "temp_scene"
    timeout_seconds: int = 300


@dataclass
class CocktailConfig:
    name: str
    description: str
    arms: list[ArmConfig]
    trial_defaults: TrialDefaults = field(default_factory=TrialDefaults)
    traps_file: str = "traps.json"
    root_dir: Path = field(default_factory=Path.cwd)

    @classmethod
    def load(cls, path_or_dir: str | Path | None = None) -> CocktailConfig:
        target = Path(path_or_dir) if path_or_dir else Path.cwd()
        if target.is_dir():
            candidates = [
                target / ".agents" / "manifest.json",
                target / ".agents" / "mcp-cocktail.json",
                target / ".agents" / "cocktail.json",
                target / "mcp-cocktail.json",
                target / "cocktail.json",
            ]
            config_file = target / "mcp-cocktail.json"
            for c in candidates:
                if c.exists():
                    config_file = c
                    break
            ws_root = target.resolve()
        else:
            config_file = target
            ws_root = target.parent.resolve()
            if ws_root.name == ".agents":
                ws_root = ws_root.parent

        if not config_file.exists():
            return cls(
                name="default",
                description="Default configuration",
                arms=[],
                trial_defaults=TrialDefaults(),
                root_dir=ws_root,
            )

        with open(config_file, "r", encoding="utf-8") as f:
            raw = json.load(f)

        arms = [ArmConfig.from_dict(a) for a in raw.get("arms", [])]
        td_raw = raw.get("trial_defaults", {})
        td = TrialDefaults(
            concurrency=td_raw.get("concurrency", "serial"),
            scene_strategy=td_raw.get("scene_strategy", "auto"),
            timeout_seconds=td_raw.get("timeout_seconds", 300),
        )

        return cls(
            name=raw.get("name", "unnamed"),
            description=raw.get("description", ""),
            arms=arms,
            trial_defaults=td,
            traps_file=raw.get("traps_file", "traps.json"),
            root_dir=ws_root,
        )


def resolve_traps_path(root_dir: Path | str | None = None) -> Path:
    """Locate the rule store a workspace actually reads.

    `.agents/traps.json` is canonical; a bare `traps.json` is the pre-.agents
    layout and still honoured when it is the only one present. Readers and
    writers must both go through this, or a write lands on a file the loader
    never opens.
    """
    root = Path(root_dir) if root_dir else Path.cwd()
    canonical = root / ".agents" / "traps.json"

    for candidate in (canonical, root / "traps.json"):
        if candidate.exists():
            return candidate

    return canonical


@dataclass
class TrapRule:
    id: str
    message: str
    tool_matcher: str | None = None
    target_matcher: str | None = None
    cooldown_seconds: int = 0
    read_only_ignore: bool = True
    home_url: str | None = None
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrapRule:
        return cls(
            id=data["id"],
            message=data["message"],
            tool_matcher=data.get("tool_matcher"),
            target_matcher=data.get("target_matcher"),
            cooldown_seconds=data.get("cooldown_seconds", 0),
            read_only_ignore=data.get("read_only_ignore", True),
            home_url=data.get("home_url"),
            tags=data.get("tags", []),
        )


@dataclass
class TrapsConfig:
    version: str
    domain: str
    rules: list[TrapRule]

    @classmethod
    def load(cls, path_or_dir: str | Path | None = None) -> TrapsConfig:
        target = Path(path_or_dir) if path_or_dir else Path.cwd()
        file_path = resolve_traps_path(target) if target.is_dir() else target

        if not file_path.exists():
            return cls(version="1.0", domain="general", rules=[])

        with open(file_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        rules = [TrapRule.from_dict(r) for r in raw.get("rules", [])]
        return cls(
            version=raw.get("version", "1.0"),
            domain=raw.get("domain", "general"),
            rules=rules,
        )
