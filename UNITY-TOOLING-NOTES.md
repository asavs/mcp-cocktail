# Unity CLI & MCP — Working Notes

A shared, append-only log of how the `unity` CLI and the Unity MCP server
actually behave, written by the humans and agents working in this repo.

**Purpose:** both tools are new and (in the CLI's case) explicitly experimental.
Their rough edges cost real time to rediscover. Write them down once.

## How to contribute

- Append to the relevant section; don't rewrite others' entries.
- **Record what you observed, not what you assume.** If you didn't verify it,
  say so — mark it `[unverified]`.
- Include the version you saw it on. Behaviour will change; entries should age
  legibly rather than silently become wrong.
- If a later version fixes something, don't delete the entry — mark it
  `[fixed in X]`. The history is the point.
- Anything worth sending upstream, tag `[feedback]` so it's easy to collect.

## Environment these notes were taken against

| | |
|---|---|
| Unity CLI | `1.0.0-beta.3` (beta channel — no stable channel published) |
| Unity Editor | `6000.5.5f1` (Unity 6.5, stream: SUPPORTED) |
| OS | Windows 11, PowerShell 5.1 + Git Bash |
| MCP | `unity mcp` (official, via CLI) registered as `unity-editor-mcp` |

---

## Unity CLI

### Install

- **`[feedback]` The documented Windows install command doesn't work.**
  [docs.unity.com/en-us/unity-cli/use-unity-cli](https://docs.unity.com/en-us/unity-cli/use-unity-cli)
  gives `curl -fsSL .../install.sh | UNITY_CLI_CHANNEL=beta bash`. The script
  itself hard-errors on `MINGW*|MSYS*|CYGWIN*` and redirects to the PowerShell
  installer. Correct command:
  ```powershell
  irm https://public-cdn.cloud.unity3d.com/hub/prod/cli/install.ps1 | iex
  ```
  With a channel: download it and run `install.ps1 -Channel beta`.

- **Only the beta channel exists.** `latest.json` (stable) 404s;
  `latest-beta.json` resolves. Upgrades need `-Channel beta`.

- Installs to `%LOCALAPPDATA%\Unity\bin\unity.exe`, adds it to **user** PATH,
  broadcasts `WM_SETTINGCHANGE`. Already-open shells still need a restart.
  Download is SHA-256 verified; the installer is worth reading, it's clean.

- Editors land in `C:\Program Files\Unity\Hub\Editor\<version>` (protected
  path → **UAC prompt**, which blocks silently until accepted). Change with
  `unity editors install-path`.

### Reliability / ergonomics

- **`[feedback]` Many commands are very slow to start.** `unity mcp configure
  --list` took >60s; several others exceeded a 120s timeout and completed fine
  when given longer. They look hung but aren't. Budget generously in scripts.

- **`[feedback]` Some `--help` subcommands genuinely hang** even with
  `--non-interactive` (seen on `unity license --help`). Had to kill it.

- **`[feedback]` Exit codes are unreliable on success paths.** `unity --help`,
  `unity editors info` and others return non-zero (255) while printing correct
  output. Don't gate scripts on their exit status.

- **`[feedback]` `unity open` does not resolve the current directory.** Run
  with no argument inside a project, it launches a *bare editor* that falls
  through to the "Choose project folder" picker — a second editor instance,
  no error. `unity projects info` with no argument resolves cwd correctly, so
  the inconsistency is in `open` specifically. **Always pass an explicit path.**

- **`[feedback]` `unity editors running` misreports.** With the stray picker
  instance above, it listed *both* PIDs as having the project open. Only one
  did. Cross-check against the process's `MainWindowTitle`.

- **`[feedback]` `projects create --path` won't create a missing parent
  directory** — errors `Cannot write to parent directory` instead. `mkdir`
  first.

- **`[feedback]` `install --list-components` requires the editor to already be
  installed** (`Error: Editor <v> is not installed`), so it can't preview
  modules *before* an install — which is the obvious use for it.

- `projects remove` deregisters from the Hub registry only; it does **not**
  delete files. Documented, but easy to misread as a delete.

### What works well

- `--json` / `--format` is consistent and genuinely machine-readable.
- `unity editors path <version>` prints the install dir — useful for scripting
  (but see the latency note; don't call it anywhere latency-sensitive, e.g.
  a git merge driver).
- `unity editors --releases` and `editors info <v>` expose the live stream
  labels (`LTS` / `SUPPORTED` / `BETA` / `ALPHA`) and patch numbers.
- `uninstall <version>` removed the editor and its directory cleanly.
- `install` module dependency resolution (Android → NDK/SDK/JDK/cmake) is
  automatic and correct.

---

## Unity MCP

- Registered with:
  ```
  unity mcp configure claude-code --project-path <repo>
  ```
  This **delegates** rather than writing a config file itself — it shells out to
  `claude mcp add --scope user --transport stdio unity-editor-mcp unity mcp -- --project-path <repo>`
  and modifies `~/.claude.json`.

- Note it lands at **user scope with a hardcoded `--project-path`**. That means
  it's global across all your projects but pinned to this one. If you work on
  more than one Unity project, consider re-scoping it to the project instead.

- `claude mcp list` reports it `✓ Connected`.

- **`[feedback]` `unity mcp configure` does its work and then never exits.**
  It printed the `claude mcp add` delegation, confirmed `File modified:
  ~/.claude.json`, and then hung until killed (exit -1). The configuration was
  correct and complete. This is the clearest instance of the CLI's
  doesn't-terminate behaviour: the side effect lands, the process doesn't
  return. Anything scripting the CLI needs a timeout and should verify the
  side effect rather than wait on exit.

- Registering mid-session does not expose the tools to an already-running agent
  session — restart to pick them up.

- This repo also has **CoplayDev's `com.coplaydev.unity-mcp`** in
  `Packages/manifest.json`, which is a *different* MCP server from Unity's
  official one. Worth deciding which we standardise on rather than running both.
  `[unverified]` — haven't yet compared their tool surfaces.

---

## Git / UnityYAMLMerge

See issue #1 for the full write-up. Key findings:

- **Merge driver placeholders are `%O %B %A`.** `$BASE`/`$REMOTE`/`$LOCAL`/
  `$MERGED` are **`git mergetool`** placeholders. Unity's docs show the
  mergetool form; pasting it into a `[merge "..."]` section yields a driver
  that runs but silently discards one side's edits. Cost an hour.

- **Git hands the driver temp filenames, not working-tree paths — so don't
  reason about quoting, measure it.** Two separate attempts here concluded
  that unquoted `%O %B %A` corrupts merges for paths containing spaces, both
  by *simulating* git's substitution into a shell string. Git doesn't do that.
  Logged the real arguments with a stub driver:

  ```
  ARGC=4
    [1]=<.merge_file_kfnwrn>
    [2]=<.merge_file_CEZhVD>
    [3]=<.merge_file_GHqbSY>
    [4]=<.merge_file_GHqbSY>
  ```

  Generated names, no spaces possible, and `%A` is a temp file too — not the
  path of the file being merged. `git mergetool` *does* pass real paths in
  `$BASE`/`$MERGED`, and passes them intact even unquoted: a conflict in
  `Assets/Core/TestScenes/[BB] Core.unity` arrived as four arguments with the
  space preserved, not eight.

  Both forms work. The point is the method: a stub driver that logs `"$@"`
  answers this in one merge, and simulating the substitution answers a
  different question convincingly enough to be believed twice.

- **Bare double quotes in a git config value are stripped.** `driver = ...
  "%O"` is stored as `... %O`; you need `\"%O\"` for the shell to see quotes.
  Read the value back with `git config --get` rather than trusting the file —
  the two differ, and the file is the one that lies.

- **Partial config is a footgun.** With *no* `merge.unityyamlmerge.*` keys, git
  silently falls back to a text merge. With *any* key present but no `.driver`,
  every merge of a Unity asset dies with
  `fatal: custom merge driver unityyamlmerge lacks command line.`
  Verified across `.name` only / `.recursive` only / both.

- **UnityYAMLMerge needs structurally valid Unity YAML.** A hand-written
  scene-shaped fixture fails with `Could not determine the transform parent of
  <id>` and won't merge. Test against a real scene copied from the project.

- **`[feedback]` UnityYAMLMerge blocks on a GUI in two different ways, and
  both hang git.** Pass `-h --fallback none` for any non-interactive use.
  1. Given a file it can't parse it raises a **modal error dialog** ("File is
     not a valid text serialized YAML file") and waits. Observed as a live
     `UnityYAMLMerge.exe` sitting on `MainWindowTitle: UnityYAMLMerge Error`
     with its caller stuck behind it. `-h` ("headless mode, no error dialogs")
     turns this into the same message on stderr plus exit 1 — verified.
  2. The shipped `Editor/Data/Tools/mergespecfile.txt` hands unresolved
     conflicts to whichever **GUI merge tool** it finds: Beyond Compare,
     p4merge, Araxis (invoked with `/wait`), PlasticSCM, SourceGear DiffMerge,
     Apple FileMerge. So merge behaviour depends on what a contributor happens
     to have installed, and any of them blocks the merge. `--fallback none`
     disables it.

  Neither flag is on by default and neither appears in Unity's merge-driver
  documentation. Confirmed that both flags together still merge a real scene
  correctly — two independent edits, both preserved, object count unchanged.

  **`-h` does not cover argument errors, and nothing does.** It is an option
  *of the `merge` subcommand*, so anything failing before that parses still
  raises a dialog and waits. Invoking the tool with no subcommand blocks
  indefinitely — to a terminal, redirected to a file, and with `-h` passed;
  all three verified, all three hang. The irony is that `-h` is only
  discoverable by running the tool with no arguments, which is itself the
  thing that hangs. Redirect and use a timeout if you ever run it by hand.

  Because no flag closes that path, the wrapper bounds the call with
  `timeout` where the shell has it (`UNITY_YAML_MERGE_TIMEOUT`, default 300s)
  and reports a killed merge as a conflict rather than letting git wait on a
  window nobody can see.

  **The usage text, so nobody has to run it bare again.** Transcribed below
  precisely because obtaining it costs you a stuck modal dialog. Version
  1.0.1, shipped with editor `6000.5.5f1`:

  ```
  usage: UnityYAMLMerge merge  [-l|-r|-p|-h] [-i file] [-o file]
                               [--rules rulesfile]
                               [--fallback fallbackspecfile]
                               [--force] [--nomappinginoneline] [--describe]
                               <base> <left> <right> [dest]
                               [premerge base dest] [premerge right dest]
         UnityYAMLMerge strip <left> <right>

         -l         Resolve merge conflicts using left  (theirs)
         -r         Resolve merge conflicts using right (mine)
         -i file    Resolve merge conflicts using merge file
         -o file    File to write merge conflicts into
         -p         Use premerging
         -h         Use 'headless' mode (no error dialogs)
         --rules    A files with merge rules
         --typeInfo A file with type information on objects in asset files
         --fallback Spec file defining fallback tools on conflicts if not
                    using builtin. Can be set to 'none' to disable fallback.
         --force    Force merging even on unknown file extensions
         --nomappinginoneline Force line break when length exceeds 80 chars
         --describe Include description of what has been done in the -o file
  ```

  Note the argument order: `<base> <left> <right> [dest]`, where **left is
  theirs and right is mine** — the opposite of the intuitive reading, and
  worth checking against any invocation you write.

- **Merging from WSL against a Windows Unity install works.** Verified on
  Ubuntu/WSL2 with the repo at `/mnt/c/...`: the wrapper finds
  `UnityYAMLMerge.exe` under the `/mnt/c` Hub root, `wslpath -m` converts the
  paths git supplies, and the Windows binary merges them over interop. A real
  scene came through correctly — two independent edits both preserved, 16
  objects in and out, and the result differed from the input side, so the
  merge genuinely happened rather than falling through to a copy.

  `[unverified]` for a repo living on the **Linux** filesystem (`/home/...`)
  rather than `/mnt/c`. There `wslpath -m` yields a `\\wsl.localhost\...` UNC
  path, and whether UnityYAMLMerge.exe opens those hasn't been tested.

- **PowerShell mangles `git config` values containing spaces + embedded
  quotes** — `driver = C:/Program Files/...` silently truncated to
  `C:/Program`. Use the 8.3 short path (`C:/PROGRA~1/...`) or write
  `.git/config` directly. This is how we landed in the fatal state above.

---

## Log

Newest first.

### 2026-07-28 — initial setup (Claude / Opus 5)

Installed CLI 1.0.0-beta.3 and editor 6.5.5f1 from scratch on a clean Windows
box; cloned this repo; configured the merge driver; registered the MCP server.
Everything above was observed during that session. Filed issue #1 with a
proposed portable fix for the merge-driver setup (`tools/git/unityyamlmerge`,
`.gitconfig-unity`, `tools/git/setup.sh` / `.ps1`).

Not yet exercised: the MCP tool surface itself (registered but not used), and
`unity build` / `unity test`.
