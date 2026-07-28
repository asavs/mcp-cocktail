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
git config --local include.path "$root/.gitconfig-unity"
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
$sh = Get-Command sh -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
if (-not $sh) {
    $gitDir = Split-Path (Split-Path (Get-Command git).Source)   # ...\Git\cmd -> ...\Git
    foreach ($candidate in @("$gitDir\bin\sh.exe", "$gitDir\usr\bin\sh.exe")) {
        if (Test-Path $candidate) { $sh = $candidate; break }
    }
}

if ($sh) {
    & $sh 'tools/git/unityyamlmerge' '--probe' 2>&1 | ForEach-Object { Write-Host $_ }
} else {
    Write-Host 'NOTE: could not locate sh.exe to run the probe. Setup is still complete;'
    Write-Host '      git uses its own bundled shell to run the merge driver.'
}

Write-Host 'Done.'
