# Unity CLI & MCP — Working Notes

A shared, append-only log of how the `unity` CLI and the Unity MCP server
actually behave, written by the humans and agents working in this repo.

**Purpose:** both tools are new and (in the CLI's case) explicitly experimental.
Their rough edges cost real time to rediscover. Write them down once.

**Scope:** this file is for *observations* — quirks, traps, version-specific
behaviour. Comparative verdicts about which tool to use go in
[docs/tooling-scorecard.md](docs/tooling-scorecard.md); setup instructions go
in [docs/unity-cli.md](docs/unity-cli.md) and
[docs/unity-mcp.md](docs/unity-mcp.md).

## Contents

- [How to contribute](#how-to-contribute)
- [Environment these notes were taken against](#environment-these-notes-were-taken-against)
- **Unity CLI**
  - [Install](#install)
  - [Reliability / ergonomics](#reliability--ergonomics) — the confident-wrong-answer failures
  - [What works well](#what-works-well)
- **Unity MCP**
  - [Unity official](#unity-mcp) — registration, Connected-but-zero-tools
  - [The tool surface](#unity-official-the-tool-surface-once-pipeline-is-live) — 140 tools, safety model, `eval`, `0.0.0.0` binding
  - [Sequencing gotcha](#sequencing-gotcha-cost-us-two-restarts) — install → Editor restart → import → tools appear
  - [CoplayDev MCP for Unity](#coplaydev-mcp-for-unity-comcoplaydevunity-mcp) — uv/PATH, stale README, client list
  - [Running both servers at once](#running-both-servers-at-once)
- [Git / UnityYAMLMerge](#git--unityyamlmerge) — driver placeholders, partial-config fatal
- [Log](#log) — dated session entries, newest first

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
  `unity install-path`.

- **`[feedback]` `unity editors --help` lists no subcommands, but has three.**
  It prints `Usage: unity editors|e [options] [command]` and then only flags —
  no `Commands:` section. Yet `unity editors running`, `unity editors info
  <version>` and `unity editors path <version>` all work. Anything nested has
  to be discovered by trying it.

  Caught this the expensive way: `install-path` is top-level (`unity
  install-path`, alias `ip`) while its obvious siblings sit under `editors`,
  so `unity editors install-path` reads as correct and isn't. With no
  subcommand listing to check against there was nothing to catch it.

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

- **`[feedback]` `unity pipeline list` resolves the *current directory* as the
  project, and invents a row when there isn't one.** Run from `C:\Users\asas`
  it reported:
  ```
  Project  Path            PID  Running  Pipeline  Server Reachable
  asas     C:\Users\asas        true     false     false
  ```
  There is no Unity project at `C:\Users\asas`. It named a "project" after the
  folder, claimed `Running: true`, and reported the Pipeline as absent — while
  a perfectly healthy Pipeline server was listening on `:7800` for the real
  project. Nothing indicates the answer is scoped to cwd.

  This is the third case of this CLI **returning a confident wrong answer
  instead of an error** (see also `editors running` above, and path-less
  `unity open` silently opening a second editor). That pattern is the single
  most costly thing about the tool right now: the failures are plausible, not
  loud.

  **Always `cd` to the project (or pass an explicit path) before calling it**,
  and cross-check liveness independently:
  ```powershell
  Get-NetTCPConnection -State Listen | ? LocalPort -eq 7800   # is it bound?
  Invoke-RestMethod http://127.0.0.1:7800/api/editor_status   # 401 == alive
  ```
  A polling loop built on `pipeline list` from the wrong cwd will wait forever
  on a server that is already up. Cost us two false readings — one false
  positive from a loose regex on the human table, one false negative from cwd.

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

- **`[feedback]` "Connected" does not mean "usable".** `claude mcp list` reports
  `✓ Connected` and the client restart exposes **zero tools**, with nothing
  anywhere explaining why. The server connects fine; it just has nothing to
  offer. The actual requirement is the **`com.unity.pipeline`** package in the
  project:
  ```
  unity pipeline install      # adds com.unity.pipeline to Packages/manifest.json
  ```
  `unity list` is the command that actually tells you this, and its error is
  genuinely good:
  ```
  Error: No Unity Editor instances found with reachable Pipeline servers.
  Make sure:
   • Unity Editor is running with a project open
   • The Pipeline package is installed in the project
   • The Pipeline HTTP server is running
  ```
  `unity mcp configure` should probably say this at configure time — it happily
  registers a server that cannot do anything yet.

- **Installing the package while the Editor is open is not enough.** Unity did
  not resolve the new manifest entry until the Editor was restarted;
  `unity pipeline list` showed `Pipeline: true` but `Server Reachable: false`
  with no port until then.

- **`[feedback]` The MCP stdio servers accumulate.** After a client restart,
  two `unity mcp --project-path ...` processes were left running
  simultaneously. Neither exits on its own. Check with:
  ```powershell
  Get-CimInstance Win32_Process -Filter "Name='unity.exe'" | Select ProcessId, CommandLine
  ```

### CoplayDev MCP for Unity (`com.coplaydev.unity-mcp`)

A *different* server from Unity's official one, already in this repo's
`Packages/manifest.json`. Requirements differ:

| | Unity official | CoplayDev |
|---|---|---|
| Needs | `com.unity.pipeline` package | `uv`/`uvx` + Unity Bridge running |
| Configured via | `unity mcp configure <client>` (CLI) | *Window > MCP for Unity* (Editor GUI) |
| Server | bundled in the CLI | Python, run via `uvx --from <git-url> mcp-for-unity` |
| Ports | Pipeline HTTP (varies) | Unity bridge (varies) + MCP 6500 |

- `uv` was not installed; `winget install astral-sh.uv` provides `uv`/`uvx`.
- Setup is driven from the Editor window (Auto-Setup → "Register with Claude
  Code" → Start Bridge), so it can't be fully scripted from the CLI the way
  Unity's can.
- **22 client configurators** ship in
  `Editor/Clients/Configurators/`: Antigravity, AntigravityIde, CherryStudio,
  ClaudeCode, ClaudeDesktop, Cline, CodeBuddyCli, Codex, CopilotCli, Cursor,
  GeminiCli, KiloCode, KimiCode, Kiro, OpenClaw, OpenCode, QwenCode, Rider,
  Trae, VSCode, VSCodeInsiders, Windsurf. **No Grok.** Reading that directory
  is the reliable way to answer "is <client> supported" — faster than hunting
  the dropdown.

- **`[feedback]` The bundled README does not match the shipped UI.** README
  describes "Server Status / Unity Bridge / MCP Client Configuration" areas and
  an **Auto-Setup** button; v10.0.0 actually shows tabs
  *Connect / Tools / Resources / Asset Gen / Deps / Advanced* with
  **Configure All Detected Clients**. Following the README sends you looking
  for a button that no longer exists.

- **The menu path is a submenu, not a window.** README says
  "Window > MCP for Unity"; the actual items are
  `Window/MCP for Unity/Toggle MCP Window`, `.../Local Setup Window`, and
  `.../Edit EditorPrefs`.

- **`uv` must be on the Editor's PATH at launch.** Installing uv while Unity is
  running leaves the window reporting `uv not found in PATH` forever — a
  process reads PATH once at startup, and Refresh doesn't help. Restart the
  Editor *from a shell that already has uv*, or point it at the binary
  explicitly. winget puts it at
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_*\uv.exe`.

### Running both servers at once

They coexist without conflict: separate packages, separate processes, separate
ports (Unity Pipeline `:7800`; CoplayDev bridge `:8080` + MCP `:6500`), and MCP
clients namespace tools as `mcp__<server>__<tool>` so identical tool names do
not collide.

The costs are subtler than a collision:

- **Selection ambiguity.** Two servers exposing `editor_play` /
  `get_scene_hierarchy` means the agent picks arbitrarily. Same task, different
  route, different bugs — hard to debug after the fact.
- **Shared global editor state.** Calls serialize on the Editor main thread, so
  no torn writes, but each server holds assumptions (Unity's sticky
  `authoring_root`, selection, play mode, open scene) that the other can
  invalidate silently.
- **Domain reloads.** A recompile triggered through one server can invalidate
  an in-flight operation on the other.

Fine for evaluation; pick one for daily use.

### Unity official: the tool surface (once Pipeline is live)

**140 tools**, all group `built-in`. `unity list` enumerates them; `--json`
gives structured output. Verified 2026-07-28 on Pipeline `0.4.0-exp.1`.

Coverage is broad — scene/GameObject authoring (`create_gameobjects`,
`set_parent`, `set_active`, `delete_gameobject`), prefabs
(`save_prefab_contents` opens an isolated prefab stage, nested-prefab safe),
scripts (`create_script`, `attach_script`), play mode (`editor_play/pause/stop`),
packages (`package_add/remove/resolve`), settings readers and writers,
bakes (navmesh, occlusion, lighting) and the test runner.

The design is notably careful, and worth copying if we ever build our own tools:

- **Destructive operations require `confirm=true`** — 17 of them, including
  `delete_asset`, `package_remove`, `write_text_file`, `switch_build_target`
  and every `set_*_settings`. Several also offer `dry_run`.
- **Path confinement.** `set_authoring_root` / `get_authoring_root` define a
  base folder under `Assets/` that bare paths resolve against *and are confined
  to*. An agent can be scoped to a subtree rather than the whole project.
- **Async work polls rather than blocks.** `bake_navmesh` →
  `navmesh_bake_status`, `package_add` → `package_status`, and anything that
  triggers a domain reload → `recompile_status`.
- **Compile-order honesty.** `create_script` explicitly documents that the type
  does not exist until a recompile completes, and `attach_script` returns a
  *recoverable* error telling you to recompile and retry.

**The HTTP API is authenticated.** Hitting `http://127.0.0.1:7800/api/*`
directly returns:
```json
{"error":"Unauthorized","errorDetails":"Missing or invalid authentication token"}
```
So the Pipeline server isn't an open localhost hole — go through `unity` /
the MCP server rather than curling it.

**`[feedback]` The Pipeline server binds `0.0.0.0`, not localhost.**
```
Get-NetTCPConnection -State Listen | ? LocalPort -eq 7800
  0.0.0.0:7800  <- pid <unity> (Unity)
```
…while `unity pipeline list --json` reports its own
`apiUrl: "http://127.0.0.1:7800/api/editor_status"`, which reads as
loopback-only. It is listening on every interface, so on an untrusted network
the port is reachable from other machines. Requests do require an auth token
(unauthenticated ones get `401 Unauthorized`), so this is defence-in-depth
rather than an open door — but the reported URL implies a binding that isn't
what's actually happening. Worth raising upstream.

**`eval` / `eval_file` exist.** The MCP surface includes arbitrary C#
evaluation inside the Editor. That is enormously useful and also the single
most dangerous tool in the set — it bypasses every `confirm=true` guard the
other tools have, since anything those tools protect can be done directly from
C#. Worth a deliberate decision about whether agents should be allowed to call
it, rather than inheriting it by default.

**Confirmed working end to end** (2026-07-28): `editor_status` returned
`{"status":"ready","playMode":"stopped","unityVersion":"6000.5.5f1"}`,
`list_open_scenes` and `get_console_logs` both returned live structured data
from the running Editor. This repo compiles with **zero console errors** on
6.5 with Pipeline installed.

### Sequencing gotcha (cost us two restarts)

The full order is:

1. `unity pipeline install` (adds `com.unity.pipeline` to the manifest)
2. **restart the Unity Editor** — it won't resolve a manifest change made while
   it's running (`hasPipelinePackage: true` but `isReachable: false`)
3. wait for the import to finish — the Pipeline HTTP server binds late; the
   editor sits on "Opening project..." for a while first
4. tools appear in the client **automatically** — no client restart needed

Step 4 is worth stating explicitly because the intuition is wrong: MCP tool
lists are usually fixed at connect time, but this server re-enumerates when the
Pipeline server comes up. A client that connected while the editor had no
Pipeline package will pick up all 140 tools on its own once the editor is
ready. `[corrected]` — an earlier revision of this file claimed a client
restart was required. It isn't; only the *Editor* restart matters.

Getting the Editor restart out of order looks like a broken install, because
every intermediate state reports success somewhere: `claude mcp list` says
Connected, `pipeline list` says `hasPipelinePackage: true`, and only
`isReachable` / `unity list` tell the truth.

**Poll `--json`, not the table.** `unity pipeline list`'s human table has a
`Running` column and a `Server Reachable` column, both boolean-ish; a loose
grep for `true` matches the wrong one and reports ready when nothing is. Use
`pipelineServer.isReachable` from `--json`.

---

## Git / UnityYAMLMerge

See issue #1 for the full write-up. Key findings:

- **Merge driver placeholders are `%O %B %A`.** `$BASE`/`$REMOTE`/`$LOCAL`/
  `$MERGED` are **`git mergetool`** placeholders. Unity's docs show the
  mergetool form; pasting it into a `[merge "..."]` section yields a driver
  that runs but silently discards one side's edits. Cost an hour.

- **Partial config is a footgun.** With *no* `merge.unityyamlmerge.*` keys, git
  silently falls back to a text merge. With *any* key present but no `.driver`,
  every merge of a Unity asset dies with
  `fatal: custom merge driver unityyamlmerge lacks command line.`
  Verified across `.name` only / `.recursive` only / both.

- **UnityYAMLMerge needs structurally valid Unity YAML.** A hand-written
  scene-shaped fixture fails with `Could not determine the transform parent of
  <id>` and won't merge. Test against a real scene copied from the project.

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

### 2026-07-28 (later) — getting the MCP servers actually working

Chased down why `unity-editor-mcp` reported `✓ Connected` while exposing zero
tools: it needs `com.unity.pipeline` in the project, an Editor restart to
resolve it, and then a *second* MCP-client restart to re-enumerate. Documented
the full ordering above.

Confirmed Unity's official surface is **140 tools** with a genuinely
well-considered safety model (confirm flags, authoring-root confinement,
poll-based async, authenticated HTTP API).

Installed `uv` (`winget install astral-sh.uv`) for CoplayDev's server. Its
remaining setup is GUI-only (*Window > MCP for Unity*), so it is not yet
registered — the head-to-head tool-surface comparison is still open.

Left uncommitted at the time: `Packages/manifest.json` gained `com.unity.pipeline
0.4.0-exp.1`. Deliberately kept off the PR #2 branch — adding an experimental
package to a shared project should be its own decision. (Committed shortly
after, on this branch, in `86d8a71`; see `docs/unity-mcp.md`.)
