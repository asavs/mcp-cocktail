name: Bug / Trap Report
description: Report a tool bug, silent failure, or mcp-cocktail issue
title: '[Bug]: <Brief Description>'
labels: ['bug', 'triage']
body:
  - type: textarea
    id: summary
    attributes:
      label: Summary
      description: Describe the bug, trap, or unexpected behavior.
      placeholder: e.g. Tool command X silently drops argument Y
    validations:
      required: true
  - type: textarea
    id: reproduction
    attributes:
      label: Reproduction Steps & Invocations
      description: Exact tool call payload or command that triggered the issue.
      placeholder: e.g. Bash("unity open") without path parameter
    validations:
      required: true
  - type: textarea
    id: environment
    attributes:
      label: Environment & OS
      description: OS, Python version, agent harness (Claude Code, OMP, Cursor).
      placeholder: Windows 11, Python 3.13, Claude Code
    validations:
      required: false
