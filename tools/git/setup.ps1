<#
.SYNOPSIS
    One-time per-clone git setup for this Unity project.

.DESCRIPTION
    Opts this clone into .gitconfig-unity, which defines the unityyamlmerge
    merge driver that .gitattributes requires. Without it, any merge touching
    a Unity asset (*.unity, *.prefab, *.asset, *.mat, *.meta, ...) aborts with
    "fatal: custom merge driver unityyamlmerge lacks command line."

    Safe to re-run.

.EXAMPLE
    .\tools\git\setup.ps1
#>

$ErrorActionPreference = 'Stop'

$root = git rev-parse --show-toplevel
if (-not $root) { throw 'Not inside a git repository.' }
Set-Location $root

# Absolute, not ../.gitconfig-unity: `--local` writes the main repo's shared
# config even from inside a worktree, where a relative path still resolves
# correctly. In a submodule, though, that config lives under the
# superproject's .git/modules/<name>/, where ../ would miss. This does trade
# away one thing the relative form had: it stops resolving if this clone is
# later moved or renamed. Re-run this script if that happens.
#
# Check-then-add, not a plain assign: `git config --local include.path X`
# fails (exit 5, "cannot overwrite multiple values with a single value") the
# moment two or more include.path entries already exist locally -- for any
# reason, not just from a prior run of this script. Verified with two
# pre-existing entries: git.exe returns 5 but does not raise a terminating
# PowerShell error on its own (native exit codes don't respect
# $ErrorActionPreference unless the stream is merged via 2>&1), so execution
# would actually fall through to the misleading "Configured" line below
# without ever having added the path, then fail later at the driver check
# with a confusing message. --get-all plus -notin keeps this idempotent
# without touching values that aren't ours.
$existing = @(git config --local --get-all include.path 2>$null)
if ("$root/.gitconfig-unity" -notin $existing) {
    git config --local --add include.path "$root/.gitconfig-unity"
}
Write-Host "Configured: include.path -> $root/.gitconfig-unity"

$driver = git config --get merge.unityyamlmerge.driver
if (-not $driver) {
    Write-Error 'Merge driver still not visible to git. Is .gitconfig-unity present at the repo root?'
    exit 1
}
Write-Host "Merge driver: $driver"

# The wrapper is POSIX sh. Git for Windows ships sh.exe but does not put it on
# PATH, so resolve it next to git.exe rather than assuming a bare `sh` works.
# Git itself invokes the driver through its own shell, so a failure to probe
# here says nothing about whether merging works -- report, never fail.
# -CommandType Application matters: plain `Get-Command git` also matches a
# function or alias named git, which plenty of shells and profiles define. For
# those, .Source is empty, and Split-Path on an empty string raises a
# ParameterBindingValidationException -- terminating, because this script sets
# 'Stop' above. So a wrapper function around git would crash setup outright.
# Asking for an Application, and reading .Path rather than .Source, resolves
# the real executable regardless. Guard the null too, for a machine with no
# git on PATH at all.
$sh = Get-Command sh -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty Path
if (-not $sh) {
    $gitCmd = Get-Command git -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($gitCmd) {
        $gitDir = Split-Path (Split-Path $gitCmd.Path)   # ...\Git\cmd -> ...\Git
        foreach ($candidate in @("$gitDir\bin\sh.exe", "$gitDir\usr\bin\sh.exe")) {
            if (Test-Path $candidate) { $sh = $candidate; break }
        }
    }
}

if ($sh) {
    # PowerShell 5.1 (and Core before 7.2) turns each stderr line from a
    # native command into a terminating NativeCommandError once merged via
    # 2>&1, if $ErrorActionPreference is 'Stop' -- which it is, script-wide,
    # above. The probe writes to stderr precisely when Unity isn't installed,
    # which is the one case this block exists to handle gracefully ("report,
    # never fail"). Relax it for just this call.
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $sh 'tools/git/unityyamlmerge' '--probe' 2>&1 | ForEach-Object { Write-Host $_ }
    } finally {
        $ErrorActionPreference = $prevEAP
    }
} else {
    Write-Host 'NOTE: could not locate sh.exe to run the probe. Setup is still complete;'
    Write-Host '      git uses its own bundled shell to run the merge driver.'
}

Write-Host 'Done.'
