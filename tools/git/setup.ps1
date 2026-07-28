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

git config --local include.path ../.gitconfig-unity
Write-Host 'Configured: include.path -> .gitconfig-unity'

$driver = git config --get merge.unityyamlmerge.driver
if (-not $driver) {
    Write-Error 'Merge driver still not visible to git. Is .gitconfig-unity present at the repo root?'
    exit 1
}
Write-Host "Merge driver: $driver"

# The wrapper is POSIX sh. Git for Windows ships sh.exe, so this works in
# PowerShell too -- but only report a problem, never fail setup over it.
try {
    $probe = & sh 'tools/git/unityyamlmerge' '--probe' 2>&1
    Write-Host $probe
} catch {
    Write-Host 'NOTE: could not run the probe (is sh on PATH?). Setup itself is still complete.'
}

Write-Host 'Done.'
