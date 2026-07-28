#!/usr/bin/env sh
# One-time per-clone setup. Opts this clone into .gitconfig-unity, which
# defines the unityyamlmerge merge driver that .gitattributes requires.
#
#     sh tools/git/setup.sh
#
# Safe to re-run.

set -eu

toplevel="$(git rev-parse --show-toplevel)"
cd "${toplevel}"

# Absolute, not ../.gitconfig-unity: `--local` writes the main repo's shared
# config even from inside a worktree, where a relative path still resolves
# correctly. In a submodule, though, that config lives under the
# superproject's .git/modules/<name>/, where ../ would miss. This does trade
# away one thing the relative form had: it stops resolving if this clone is
# later moved or renamed. Re-run this script if that happens.
git config --local include.path "${toplevel}/.gitconfig-unity"

printf 'Configured: include.path -> %s/.gitconfig-unity\n' "${toplevel}"

# Verify the driver actually resolves, so setup fails loudly rather than at
# the first merge conflict.
if git config --get merge.unityyamlmerge.driver >/dev/null 2>&1; then
    printf 'Merge driver: %s\n' "$(git config --get merge.unityyamlmerge.driver)"
else
    printf 'WARNING: merge driver still not visible to git.\n' >&2
    printf '         Check that .gitconfig-unity exists at the repo root.\n' >&2
    exit 1
fi

# Report which Unity the wrapper resolves, so a missing install shows up now
# rather than at someone's first merge conflict.
if probe=$(sh tools/git/unityyamlmerge --probe 2>&1); then
    printf '%s\n' "${probe}"
else
    printf '%s\n' "${probe}"
    printf 'NOTE: merges will fall back to plain text conflicts. That works --\n'
    printf '      they just will not be smart-merged.\n'
fi

printf 'Done.\n'
