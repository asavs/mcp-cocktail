"""Whether an arm can be installed here, as distinct from whether it is running.

doctor answers "is this arm up". It cannot answer "could I even have this",
which is the question a first-time user actually has -- and the two are not the
same. An arm needing Node 24 on a machine with Node 18 reports OFFLINE exactly
like an arm nobody has installed yet, so eleven identical red rows hide the
three that are one command away from working.

Requirements live in the manifest because they are facts about the upstream
project, not about this machine, and because prose in a note is invisible to
code: `"requires": {"tools": {"node": ">=22"}}` can be checked, "requires Node
22 or later" cannot.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from mcp_cocktail.config import ArmConfig, CocktailConfig

VERSION_RE = re.compile(r"(\d+(?:\.\d+)*)")


def parse_version(text: str) -> tuple[int, ...]:
    """First dotted-numeric run in a version string, as a comparable tuple.

    Tools disagree wildly about how to print a version -- `v22.14.0`,
    `npm 10.9.2`, `unity-cli 0.12.0 (abc123)` -- so anchor on the number
    rather than on any one layout.
    """
    match = VERSION_RE.search(text or "")
    if not match:
        return ()
    return tuple(int(p) for p in match.group(1).split("."))


def satisfies(have: str, spec: str) -> bool:
    """Check a detected version against a `>=X.Y` style requirement.

    Only `>=` and a bare version are supported, because those are the only
    forms the real manifests need. An unrecognised spec passes rather than
    fails: refusing to install over a requirement we cannot parse would be a
    worse error than proceeding.
    """
    want = parse_version(spec)
    got = parse_version(have)
    if not want or not got:
        return True

    # Compare on the precision the requirement asks for: ">=22" against
    # 22.14.0 is satisfied, and must not be read as 22 < 22.14.
    depth = len(want)
    return got[:depth] + (0,) * (depth - len(got[:depth])) >= want


def detect_tool_version(name: str, timeout: int = 5) -> str | None:
    """Installed version of a CLI tool, or None when it is absent.

    Tries the flags in the order tools actually implement them. `--version`
    covers most; `version` (no dashes) covers the Go-style ones.
    """
    # Invoke the resolved path, not the bare name: on Windows npm, openupm and
    # friends are .cmd shims, and handing CreateProcess a bare name it cannot
    # execute fails in a way that looks identical to "installed but silent".
    executable = shutil.which(name)
    if not executable:
        return None

    for flag in ("--version", "-v", "version"):
        try:
            res = subprocess.run(
                [executable, flag], capture_output=True, text=True, timeout=timeout,
                shell=executable.lower().endswith((".cmd", ".bat")),
            )
        except (subprocess.TimeoutExpired, OSError):
            continue

        output = f"{res.stdout} {res.stderr}".strip()
        if res.returncode == 0 and parse_version(output):
            return output.splitlines()[0].strip()[:80]

    return "(present, version unknown)"


def detect_unity_project(root: Path | None) -> str | None:
    """Unity version this workspace pins, from ProjectSettings/ProjectVersion.txt."""
    if not root:
        return None

    marker = Path(root) / "ProjectSettings" / "ProjectVersion.txt"
    if not marker.exists():
        return None

    try:
        for line in marker.read_text(encoding="utf-8").splitlines():
            if line.startswith("m_EditorVersion:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        return None

    return None


@dataclass
class Requirement:
    kind: str        # "tool" | "unity"
    name: str
    wanted: str
    found: str | None

    @property
    def met(self) -> bool:
        if self.found is None:
            return False
        return satisfies(self.found, self.wanted)

    def describe(self) -> str:
        if self.found is None:
            return f"{self.name} {self.wanted} -- not found"
        if not self.met:
            return f"{self.name} {self.wanted} -- found {self.found}"
        return f"{self.name} {self.found}"


@dataclass
class ArmReadiness:
    arm_id: str
    arm_name: str
    requirements: list[Requirement] = field(default_factory=list)

    @property
    def installable(self) -> bool:
        return all(r.met for r in self.requirements)

    @property
    def blockers(self) -> list[Requirement]:
        return [r for r in self.requirements if not r.met]


def check_arm(arm: ArmConfig, unity_version: str | None, cache: dict[str, str | None]) -> ArmReadiness:
    requires = arm.requires or {}
    checks: list[Requirement] = []

    for tool, wanted in (requires.get("tools") or {}).items():
        if tool not in cache:
            cache[tool] = detect_tool_version(tool)
        checks.append(Requirement("tool", tool, str(wanted), cache[tool]))

    if requires.get("unity"):
        checks.append(Requirement("unity", "Unity", str(requires["unity"]), unity_version))

    return ArmReadiness(arm.id, arm.name, checks)


def run_preflight(config: CocktailConfig) -> tuple[list[ArmReadiness], str | None]:
    """Installability of every arm, plus the workspace's Unity version."""
    unity_version = detect_unity_project(config.root_dir)
    cache: dict[str, str | None] = {}

    return [check_arm(arm, unity_version, cache) for arm in config.arms], unity_version


def print_preflight_report(
    readiness: list[ArmReadiness], unity_version: str | None, config: CocktailConfig
) -> None:
    from mcp_cocktail.console import ensure_utf8_streams

    ensure_utf8_streams()

    print("\n=== mcp-cocktail Preflight: what this machine can install ===")
    print(f"Workspace: {config.root_dir}")
    print(f"Unity project: {unity_version or 'none detected (no ProjectSettings/ProjectVersion.txt)'}\n")

    if not readiness:
        print("[UNCONFIGURED] No arms defined — nothing to check.")
        return

    unconstrained = [r for r in readiness if not r.requirements]
    ready = [r for r in readiness if r.requirements and r.installable]
    blocked = [r for r in readiness if r.requirements and not r.installable]

    if ready:
        print(f"Installable now ({len(ready)}):")
        for r in ready:
            print(f"  {r.arm_id:<22} {', '.join(c.describe() for c in r.requirements)}")

    if blocked:
        print(f"\nBlocked ({len(blocked)}):")
        for r in blocked:
            print(f"  {r.arm_id:<22} needs {', '.join(c.describe() for c in r.blockers)}")

    if unconstrained:
        # Silence here would read as "these are fine", which is the same
        # ambiguity the OFFLINE rows had before they carried an install route.
        print(f"\nNo requirements declared ({len(unconstrained)}): "
              f"{', '.join(r.arm_id for r in unconstrained)}")
        print("  Preflight cannot vouch for these -- it means nobody recorded what they need,")
        print("  not that they need nothing.")

    print(f"\nPreflight Summary: {len(ready)}/{len(readiness)} arm(s) have their prerequisites met.")
