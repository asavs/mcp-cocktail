"""Unified Command Line Interface for mcp-cocktail."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from mcp_cocktail import __version__
from mcp_cocktail.config import CocktailConfig, TrapsConfig
from mcp_cocktail.discover import (
    discover_domain_arms,
    build_discovered_manifest,
    generate_agentic_discover_task,
    merge_manifests,
)
from mcp_cocktail.doctor import run_doctor, print_doctor_report
from mcp_cocktail.guardrail import run_guardrail, selftest as guardrail_selftest
from mcp_cocktail.inbox import append_note, show_inbox
from mcp_cocktail.installer import install_hook, uninstall_hook
from mcp_cocktail.miner import cmd_sweep, print_sweep_report, summarize_transcript, parse_blocks
from mcp_cocktail.proxy import run_proxy
from mcp_cocktail.runner import create_trial
from mcp_cocktail.scorecard import generate_scorecard, propose_rsi_guardrails, generate_upstream_bug_draft
from mcp_cocktail.server import run_mcp_server
from mcp_cocktail.sync import pull_domain_rules, push_domain_contributions


def cmd_init(args: argparse.Namespace) -> int:
    agents_dir = Path.cwd() / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    target = agents_dir / "manifest.json"
    if target.exists() and not args.force:
        print(f"Error: {target} already exists. Use --force to overwrite.")
        return 1

    sample_manifest = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "name": args.name or Path.cwd().name,
        "description": "Multi-arm tooling benchmark workspace",
        "arms": [
            {
                "id": "tool-cli",
                "name": "Primary CLI",
                "type": "cli",
                "command": "tool-cli",
                "env": {},
                "health_check": "tool-cli --version"
            },
            {
                "id": "official-mcp",
                "name": "Official MCP Server",
                "type": "mcp",
                "mcp_server": "tool-mcp-server",
                "tool_prefix": "mcp__tool__",
                "health_check": "curl -s http://127.0.0.1:8080/health"
            }
        ],
        "trial_defaults": {
            "concurrency": "serial",
            "scene_strategy": "auto",
            "timeout_seconds": 300
        },
        "traps_file": "traps.json"
    }

    sample_traps = {
        "version": "1.0",
        "domain": args.name or Path.cwd().name,
        "rules": [
            {
                "id": "sample-rule-1",
                "message": "TRAP: Positional arguments in tool-cli are ignored silently.",
                "tool_matcher": "Bash|PowerShell",
                "target_matcher": "tool-cli",
                "read_only_ignore": True,
                "cooldown_seconds": 0
            }
        ]
    }

    target.write_text(json.dumps(sample_manifest, indent=2), encoding="utf-8")
    traps_target = agents_dir / "traps.json"
    if not traps_target.exists():
        traps_target.write_text(json.dumps(sample_traps, indent=2), encoding="utf-8")

    print(f"Initialized mcp-cocktail manifest at {target}")
    print(f"Initialized traps config at {traps_target}")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    """1-Command automated setup and arm health validation for any project."""
    preset = args.preset or "unity"
    repo_root = Path(__file__).resolve().parents[2]
    example_dir = repo_root / "examples" / preset

    if not example_dir.exists():
        print(f"Error: Preset '{preset}' not found in {repo_root / 'examples'}")
        return 1

    agents_dir = Path.cwd() / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    src_manifest = example_dir / "cocktail.json"
    src_traps = example_dir / "traps.json"
    src_tools = example_dir / "tools"

    dst_manifest = agents_dir / "manifest.json"
    dst_traps = agents_dir / "traps.json"
    dst_tools = Path.cwd() / "tools"

    if src_manifest.exists():
        shutil.copy(src_manifest, dst_manifest)
        print(f"Copied preset manifest -> {dst_manifest}")

    if src_traps.exists():
        shutil.copy(src_traps, dst_traps)
        print(f"Copied preset trap rules -> {dst_traps}")

    if src_tools.exists() and not dst_tools.exists():
        shutil.copytree(src_tools, dst_tools)
        print(f"Provisioned domain helper tools -> {dst_tools}")

    ok, msg = install_hook(
        harness=args.harness,
        global_settings=args.global_settings,
        target_path=args.settings,
        custom_traps=str(dst_traps) if dst_traps.exists() else None,
    )
    print(msg)

    config = CocktailConfig.load(Path.cwd())
    doc_results = run_doctor(config)
    print_doctor_report(doc_results, config)

    print(f"\n[OK] mcp-cocktail setup complete for '{preset}' domain!")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    domain = args.domain or "unity"
    print(f"Discovering open-source MCP servers and CLIs for domain '{domain}'...")

    candidates = discover_domain_arms(domain)
    discovered_manifest = build_discovered_manifest(domain, candidates)

    agents_dir = Path.cwd() / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    target_manifest = agents_dir / "manifest.json"

    docs_dir = Path.cwd() / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    discovered_doc = docs_dir / "discovered-manifest.json"

    discovered_doc.write_text(json.dumps(discovered_manifest, indent=2), encoding="utf-8")

    if target_manifest.exists():
        try:
            existing_raw = json.loads(target_manifest.read_text(encoding="utf-8"))
            final_manifest = merge_manifests(existing_raw, discovered_manifest)
            print(f"Non-destructively merged discovered arms into existing {target_manifest.name}")
        except Exception:
            final_manifest = discovered_manifest
    else:
        final_manifest = discovered_manifest

    target_manifest.write_text(json.dumps(final_manifest, indent=2), encoding="utf-8")

    print(f"\nDiscovered {len(candidates)} candidate arm(s):")
    for c in candidates:
        print(f"  - [{c.type.upper()}] {c.id:<20} ({c.name})")

    if args.agentic:
        task_spec = generate_agentic_discover_task(domain)
        task_file = Path.cwd() / f"discover-task-{domain}.json"
        task_file.write_text(json.dumps(task_spec, indent=2), encoding="utf-8")
        print(f"\nGenerated agentic scout task spec -> {task_file}")

    print(f"\nSaved discovery audit log -> {discovered_doc}")
    print(f"Updated workspace manifest -> {target_manifest}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    domain = args.domain or "unity"
    if args.push:
        ok, msg = push_domain_contributions(domain)
    else:  # Default pull
        ok, msg = pull_domain_rules(domain)
    print(msg)
    return 0 if ok else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    config = CocktailConfig.load(Path.cwd())
    doc_results = run_doctor(config)
    print_doctor_report(doc_results, config)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    if args.selftest:
        return guardrail_selftest()
    return run_guardrail(args.traps)


def cmd_install_hook(args: argparse.Namespace) -> int:
    if args.uninstall:
        ok, msg = uninstall_hook(
            harness=args.harness,
            global_settings=args.global_settings,
            target_path=args.settings,
        )
    else:
        ok, msg = install_hook(
            harness=args.harness,
            global_settings=args.global_settings,
            target_path=args.settings,
            custom_traps=args.traps,
            matcher=args.matcher,
        )
    print(msg)
    return 0 if ok else 1


def cmd_serve(args: argparse.Namespace) -> int:
    return run_mcp_server()


def cmd_proxy(args: argparse.Namespace) -> int:
    return run_proxy(args.target_cmd)


def cmd_note(args: argparse.Namespace) -> int:
    if args.show:
        print(show_inbox(args.inbox))
        return 0

    if not args.note:
        print("Error: No note text provided.")
        return 1

    text = " ".join(args.note)
    p = append_note(text, cost_mins=args.cost, inbox_path=args.inbox)
    print(f"Recorded note -> {p}")
    return 0


def cmd_upstream(args: argparse.Namespace) -> int:
    obs = " ".join(args.observation)
    arm = args.arm or "Target Tool Arm"
    p = generate_upstream_bug_draft(obs, arm)
    print(f"Generated upstream bug report draft -> {p}")
    return 0


def cmd_mine(args: argparse.Namespace) -> int:
    config = CocktailConfig.load(Path.cwd())
    if args.subcommand == "sweep":
        summaries = cmd_sweep(config, project_slug=args.project)
        print_sweep_report(summaries, config)
    elif args.subcommand == "stats":
        if not args.target:
            print("Error: target transcript file or UUID required.")
            return 1
        p = Path(args.target)
        if not p.exists():
            print(f"Error: {p} not found.")
            return 1
        s = summarize_transcript(p, config)
        print(f"Session {s.session_id}: {s.turn_count} turns, {sum(s.arm_counts.values())} arm calls.")
        for k, v in s.arm_counts.items():
            print(f"  {k}: {v}")
    else:
        print("Usage: mcp-cocktail mine [sweep|stats <uuid>]")
        return 1
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = CocktailConfig.load(Path.cwd())
    if not config.arms:
        print("Warning: No arms defined in manifest.")

    res = create_trial(
        trial_id=args.trial_id,
        task_description=args.task,
        config=config,
        arms_override=args.arms,
        exec_mode=args.exec,
        scene_strategy=args.scene_strategy,
        compare_visual=args.compare_visual,
    )
    briefs = res["briefs"]
    print(f"Created trial {args.trial_id} (Scene Isolation Strategy: {res['scene_strategy']}) with {len(briefs)} arm brief(s):")
    for arm_id in briefs:
        print(f"  - docs/trials/{args.trial_id}/brief-{arm_id}.md")
    print(f"Task payload specification generated: {res['tasks_file']}")
    return 0


def cmd_scorecard(args: argparse.Namespace) -> int:
    config = CocktailConfig.load(Path.cwd())
    out = generate_scorecard(config)
    print(out)

    if args.rsi:
        print("\n--- Proposed RSI Guardrails from Findings Inbox ---")
        candidates = propose_rsi_guardrails()
        if not candidates:
            print("No new trap candidates found in findings inbox.")
        else:
            for c in candidates:
                print(f"Rule ID: {c['rule_id_proposal']}")
                print(f"  Message: {c['suggested_message']}")
                print(f"  Source:  {c['source_line']}\n")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mcp-cocktail",
        description="mcp-cocktail: Generic RSI Engine for Multi-Arm Tooling & MCP Evaluation.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    p_init = subparsers.add_parser("init", help="Initialize a new mcp-cocktail workspace")
    p_init.add_argument("--name", help="Workspace name")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing manifest")

    p_setup = subparsers.add_parser("setup", help="1-Command automated setup and doctor validation for a target domain (e.g. unity)")
    p_setup.add_argument("--preset", default="unity", help="Domain preset name (default: unity)")
    p_setup.add_argument("--harness", default="auto", help="Target harness (claude, omp, mcp, auto)")
    p_setup.add_argument("--global", dest="global_settings", action="store_true", help="Target global settings")
    p_setup.add_argument("--settings", help="Explicit path to settings.json")

    p_disc = subparsers.add_parser("discover", help="Discover open-source MCP servers and CLIs for a domain")
    p_disc.add_argument("--domain", default="unity", help="Target software domain (e.g. unity, postgres, docker, github)")
    p_disc.add_argument("--agentic", action="store_true", help="Generate an agentic scout task spec for deep multi-source web search")

    p_sync = subparsers.add_parser("sync", help="Sync domain weakness guardrails with the global community registry")
    p_sync.add_argument("--domain", default="unity", help="Target software domain (e.g. unity, postgres, docker)")
    p_sync.add_argument("--pull", action="store_true", help="Pull latest community guardrails (default)")
    p_sync.add_argument("--push", action="store_true", help="Package locally derived weakness rules for upstream PR submission")

    subparsers.add_parser("doctor", help="Run arm health and diagnostic probes")

    p_check = subparsers.add_parser("check", help="Run PreToolUse trap guardrail check")
    p_check.add_argument("--traps", help="Path to traps.json")
    p_check.add_argument("--selftest", action="store_true", help="Run internal guardrail self-test")

    subparsers.add_parser("serve", help="Run stdio MCP server for mcp-cocktail tools")

    p_proxy = subparsers.add_parser("proxy", help="Run transparent stdio MCP proxy wrapping a target server command")
    p_proxy.add_argument("target_cmd", nargs=argparse.REMAINDER, help="Target MCP server executable and arguments")

    p_hook = subparsers.add_parser("install-hook", help="Install PreToolUse hook into harness configuration")
    p_hook.add_argument("--harness", default="auto", help="Target harness (claude, omp, mcp, auto)")
    p_hook.add_argument("--global", dest="global_settings", action="store_true", help="Target global settings")
    p_hook.add_argument("--settings", help="Explicit path to settings.json")
    p_hook.add_argument("--traps", help="Custom traps.json path for hook")
    p_hook.add_argument("--matcher", default="Bash|PowerShell|mcp__.*", help="Tool matcher pattern")
    p_hook.add_argument("--uninstall", action="store_true", help="Remove mcp-cocktail hook")

    p_note = subparsers.add_parser("note", help="Append friction note to findings inbox")
    p_note.add_argument("note", nargs="*", help="Observation prose")
    p_note.add_argument("--cost", type=int, help="Minutes lost")
    p_note.add_argument("--show", action="store_true", help="Show inbox notes")
    p_note.add_argument("--inbox", help="Inbox path")

    p_up = subparsers.add_parser("upstream", help="Generate upstream bug draft for vendor issue tracking")
    p_up.add_argument("observation", nargs="+", help="Friction observation text")
    p_up.add_argument("--arm", help="Target arm name")

    p_mine = subparsers.add_parser("mine", help="Mine session transcripts for tool usage and trap patterns")
    p_mine.add_argument("subcommand", choices=["sweep", "stats"], nargs="?", default="sweep")
    p_mine.add_argument("target", nargs="?", help="Target file or UUID for stats")
    p_mine.add_argument("--project", help="Filter by project slug")

    p_run = subparsers.add_parser("run", help="Generate subagent trial briefs for multi-arm benchmark")
    p_run.add_argument("trial_id", help="Trial identifier (e.g. T-001)")
    p_run.add_argument("task", help="Task description for trial")
    p_run.add_argument("--arms", nargs="*", help="Specific arm IDs to target")
    p_run.add_argument("--exec", choices=["auto", "omp", "claude"], help="Prepare execution task payload for subagents")
    p_run.add_argument("--scene-strategy", choices=["auto", "instant_reload", "temp_scene"], default="auto", help="Scene isolation strategy")
    p_run.add_argument("--compare-visual", action="store_true", help="Shortcut to force temp_scene mode for human visual inspection")

    p_score = subparsers.add_parser("scorecard", help="Generate comparative scorecard & RSI insights")
    p_score.add_argument("--rsi", action="store_true", help="Extract proposed trap rules from inbox")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    handler = {
        "init": cmd_init,
        "setup": cmd_setup,
        "discover": cmd_discover,
        "sync": cmd_sync,
        "doctor": cmd_doctor,
        "check": cmd_check,
        "serve": cmd_serve,
        "proxy": cmd_proxy,
        "install-hook": cmd_install_hook,
        "note": cmd_note,
        "upstream": cmd_upstream,
        "mine": cmd_mine,
        "run": cmd_run,
        "scorecard": cmd_scorecard,
    }.get(args.command)

    if handler:
        return handler(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
