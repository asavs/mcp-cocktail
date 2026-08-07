"""Weakness Maximization Principle for Guardrail Generalization (Bennett, 2023).

Based on:
  Bennett, M. T. (2023). "The Optimal Choice of Hypothesis Is the Weakest, Not the Shortest."
  arXiv:2301.12987v4 [cs.AI].

Instead of selecting the shortest or most specific description (MDL), this module computes
the WEAKEST valid hypothesis rule -- the rule with maximum generality/coverage over the state
space that incurs zero false positives on safe tool calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from mcp_cocktail.config import TrapRule
from mcp_cocktail.guardrail import is_read_only


DEFAULT_SAFE_CORPUS = [
    "git status",
    "git diff",
    "git log",
    "grep -i test file.py",
    "cat README.md",
    "ls -la",
]


def compute_weakness_score(
    tool_matcher: str | None,
    target_matcher: str | None,
    sample_space: list[str],
) -> float:
    """Calculate the weakness (generality ratio) of a rule matcher over a sample space.

    Weakness = |Z_H| / |SampleSpace|, where Z_H is the set of inputs matched by H.
    """
    if not sample_space:
        return 0.0

    match_count = 0
    for sample in sample_space:
        tool_hit = not tool_matcher or bool(re.search(tool_matcher, "Bash", re.I))
        target_hit = not target_matcher or bool(re.search(target_matcher, sample, re.I))

        if tool_hit and target_hit and not is_read_only(sample):
            match_count += 1

    return match_count / len(sample_space)


def generalize_pattern(text: str) -> str:
    """Generalize specific token literals to broadest valid regex matchers.

    Example: 'unity command --name foo' -> 'unity\\s+command'
             'eval top-level using' -> 'eval'
    """
    clean = re.sub(r"^-\s*\[.*?\](?:\s*\(cost:\s*\d+m\))?\s*", "", text).strip()

    # Extract command verb or primary keywords
    words = clean.split()
    if not words:
        return r".*"

    # Look for command-like tokens
    cmd_tokens = [w for w in words if re.match(r"^[a-zA-Z0-9_-]+$", w)]

    if len(cmd_tokens) >= 2:
        # e.g., "unity command" or "pip install"
        return r"\b" + re.escape(cmd_tokens[0]) + r"\s+" + re.escape(cmd_tokens[1]) + r"\b"
    elif len(cmd_tokens) == 1:
        return r"\b" + re.escape(cmd_tokens[0]) + r"\b"

    return r"\b" + re.escape(words[0]) + r"\b"


def derive_weakest_rule(
    observation_text: str,
    safe_corpus: list[str] | None = None,
    rule_id_prefix: str = "weakness-rule",
) -> TrapRule:
    """Derive the weakest (most general) valid TrapRule from a friction observation.

    Applies Bennett's Rule of Least Specificity: 'Explanations should be no more
    specific than necessary.'
    """
    safe = safe_corpus or DEFAULT_SAFE_CORPUS
    clean_obs = re.sub(r"^-\s*\[.*?\](?:\s*\(cost:\s*\d+m\))?\s*", "", observation_text).strip()

    # Candidate 1: Broad generalized pattern
    gen_pattern = generalize_pattern(clean_obs)
    score1 = compute_weakness_score("Bash|PowerShell", gen_pattern, safe)

    # If generalized pattern triggers false positives on safe commands, fallback to literal pattern
    if score1 > 0.5:  # Overly broad / triggers on safe inputs
        gen_pattern = r"\b" + re.escape(clean_obs[:20]) + r"\b"

    rule_id = f"{rule_id_prefix}-" + re.sub(r"[^a-z0-9]", "-", clean_obs.lower())[:30].strip("-")

    return TrapRule(
        id=rule_id,
        message=f"TRAP (Weakness Optimized): {clean_obs}",
        tool_matcher="Bash|PowerShell|mcp__.*",
        target_matcher=gen_pattern,
        read_only_ignore=True,
        cooldown_seconds=0,
        tags=["rsi-derived", "weakness-maximized"],
    )
