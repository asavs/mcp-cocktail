#!/usr/bin/env sh
# One-time per-clone setup. Opts this clone into .gitconfig-unity, which
# defines the unityyamlmerge merge driver that .gitattributes requires.
#
#     sh tools/git/setup.sh
#
# Safe to re-run.

set -eu

cd "$(git rev-parse --show-toplevel)"

git config --local include.path ../.gitconfig-unity

printf 'Configured: include.path -> .gitconfig-unity\n'

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
