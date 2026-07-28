# Unity CLI

Installing and using the `unity` CLI. Written against CLI `1.0.0-beta.3` and
editor `6000.5.5f1`, verified on Windows 11, 2026-07-28.

Unity announced the CLI at Unite Seoul, July 2026. It is a standalone `unity`
binary that manages editors, modules, projects, auth and automation from a
terminal — Unity Hub is **not** required. It is explicitly experimental;
commands may change.

Behavioural quirks live in [../UNITY-TOOLING-NOTES.md](../UNITY-TOOLING-NOTES.md).
This document is the setup path.

## Install the CLI

**Windows** (PowerShell):

```powershell
$p = "$env:TEMP\install.ps1"
Invoke-WebRequest https://public-cdn.cloud.unity3d.com/hub/prod/cli/install.ps1 -OutFile $p -UseBasicParsing
& $p -Channel beta
```

Two things the official docs get wrong for Windows:

- The docs give `curl -fsSL .../install.sh | ... bash`. That script **hard-errors
  on MINGW/MSYS/Cygwin** and redirects you to `install.ps1`. Use the PowerShell
  installer.
- **Only the beta channel is published.** `latest.json` (stable) 404s;
  `latest-beta.json` resolves. Without `-Channel beta` the install fails.

**macOS / Linux:**

```bash
curl -fsSL https://public-cdn.cloud.unity3d.com/hub/prod/cli/install.sh | UNITY_CLI_CHANNEL=beta bash
```

The installer verifies a SHA-256 from a signed manifest before installing, puts
the binary in `%LOCALAPPDATA%\Unity\bin` (Windows) or `~/.local/bin` /
`~/.unity/bin` (Unix), and adds it to PATH. **Open a new terminal** afterwards —
existing shells keep their old PATH.

```console
$ unity --version
1.0.0-beta.3
```

## Sign in

```bash
unity auth login       # opens a browser flow
unity auth status
unity license          # should list "Unity Personal" or better
```

The editor will not open a project without a license.

## Install the editor

This project needs **6000.5.5f1** exactly (see
[../CONTRIBUTING.md](../CONTRIBUTING.md)).

```bash
unity install 6000.5.5f1 -a x86_64 \
  -m windows-il2cpp webgl android \
  --cm --accept-eula -y --non-interactive
```

- `-m` picks modules; `--cm` pulls their child modules (Android drags in
  NDK/SDK/OpenJDK/cmake automatically and correctly).
- Default install path is `C:\Program Files\Unity\Hub\Editor` — a protected
  path, so **Windows shows a UAC prompt that blocks the install silently until
  accepted**. Change it with `unity install-path` (top-level, *not*
  `unity editors install-path` — see the note on hidden subcommands below).
- Budget disk: editor + those three module sets is ~23 GB.

Verify:

```bash
unity editors -i
```

## Choosing a version

```bash
unity editors --releases          # available versions
unity editors info 6000.3.20f1    # stream label, changeset, release date
```

Versions are `6000.MINOR.PATCH` + build type — `6000.5.5f1` is Unity **6.5**,
patch 5, final build 1. The `6000` major exists because Unity used year-based
versions (2022.3, 2023.2) before rebranding to "Unity 6"; a bare `6.x` would
sort below `2023.x` in every version comparator.

Streams: `LTS` gets ~2 years of bugfix-only patches; `SUPPORTED` is the current
tech-stream release, newer features, maintained until superseded; `BETA` /
`ALPHA` are not for shared repos.

**Version choice is not personal here** — it's pinned by the project. Don't
"upgrade" it unilaterally.

## Everyday commands

```bash
unity editors -i                    # installed editors
unity editors running               # running editors and their projects
unity open <path>                   # open a project (see caveat below)
unity projects info                 # details for the project in the cwd
unity projects size <path>          # disk usage by folder
unity build <path>                  # batch-mode build
unity test <path>                   # EditMode/PlayMode tests + report
unity install-modules               # add build targets later
unity list                          # tools the live editor exposes (needs Pipeline)
```

`unity list` verifies only Unity's official Pipeline-backed MCP surface. It
does not inspect the CoplayDev HTTP server on `127.0.0.1:8080`. Use the
separate health and client-loading checks in
[unity-mcp.md](unity-mcp.md#verify-and-recover) when diagnosing CoplayDev.

**Always pass an explicit path to `unity open`.** With no argument it does *not*
resolve the current directory — it launches a bare editor that falls through to
the "Choose project folder" picker, as a second instance, with no error.
(`unity projects info` *does* resolve the cwd, so the inconsistency is specific
to `open`.)

## Scripting the CLI

This is the canonical account of the CLI's reliability characteristics; other
docs link here rather than restating them.

**The failure mode to design around: this CLI returns confident wrong answers
rather than errors.** Three confirmed cases so far — `editors running`
misreporting which instance had a project open, path-less `unity open` silently
launching a second editor instead of erroring, and `pipeline list` inventing a
project row from the current directory. None announced itself. Budget
verification time, and never report success on the strength of a command
appearing to work.

- **Use `--json` / `--format json`.** Output is consistent and genuinely
  machine-readable. Parsing the human tables is a trap — several have multiple
  boolean-looking columns, and a loose grep matches the wrong one.
- **Don't gate on exit codes.** Several commands return non-zero (255) while
  printing correct output.
- **Give it generous timeouts.** Startup latency is high; commands regularly
  take 60s+ and look hung when they aren't. Some `--help` subcommands genuinely
  hang — kill and move on.
- **Commands are cwd-sensitive.** `unity pipeline list` resolves the current
  directory as the project and will invent a plausible-looking row if there
  isn't one there. `cd` to the repo first.
- **Don't call it from latency-sensitive paths.** `tools/git/unityyamlmerge`
  deliberately probes the filesystem instead of calling `unity editors path`,
  because a CLI that doesn't return would hang git mid-merge.
- **`--help` hides subcommands, so don't infer the tree from it.**
  `unity editors --help` prints `Usage: unity editors|e [options] [command]`
  and then lists only flags — no `Commands:` section. But `unity editors
  running`, `unity editors info <version>` and `unity editors path <version>`
  all exist and work. The subcommands are real and undocumented by their own
  help.

  This is worth more than a curiosity, because it makes guessing actively
  dangerous. `install-path` is **top-level** (`unity install-path`, alias
  `ip`) even though its obvious siblings live under `editors`. With no
  subcommand listing to check against, `unity editors install-path` looks
  entirely reasonable and is wrong. Verify against `unity --help` for
  top-level commands, and against a real invocation for anything nested.

## Verifying your work

Because of the above, check the effect rather than the invocation:

```bash
unity list                 # tools the live editor exposes (run from the repo root)
unity test <path>          # EditMode/PlayMode tests + report
unity projects info        # confirm the project/editor version actually in use
```

`unity list` covers only Unity's official Pipeline-backed surface — for
CoplayDev's server use the checks in
[unity-mcp.md](unity-mcp.md#verify-and-recover).

For whether a change actually compiled, the fastest signal is the editor's own
console via the official MCP: `get_console_logs` with `severity: error`.

## Uninstalling

```bash
unity uninstall 6000.3.20f1 -a x86_64    # removes the editor and its directory
unity projects remove <path>             # deregisters only — does NOT delete files
unity self-uninstall                     # removes the CLI itself
```

## Related

- [unity-mcp.md](unity-mcp.md) — driving the editor programmatically
- [../UNITY-TOOLING-NOTES.md](../UNITY-TOOLING-NOTES.md) — observed quirks, with versions
