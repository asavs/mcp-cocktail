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
- [**Patterns**](#patterns) — the five recurring shapes. Read this first; the rest is instances.
- **Unity CLI**
  - [Install](#install)
  - [Reliability / ergonomics](#reliability--ergonomics) — the confident-wrong-answer failures
  - [What works well](#what-works-well)
- **Unity MCP**
  - [Unity official](#unity-mcp) — registration, Connected-but-zero-tools
  - [The tool surface](#unity-official-the-tool-surface-once-pipeline-is-live) — 140 tools, safety model, `eval`, `0.0.0.0` binding
  - [Sequencing gotcha](#sequencing-gotcha-cost-us-two-restarts) — install → Editor restart → import → tools appear
  - [Pipeline can drop out mid-session](#pipeline-can-drop-out-of-a-live-editor-session) — the port moves, the old socket lingers
  - [CoplayDev MCP for Unity](#coplaydev-mcp-for-unity-comcoplaydevunity-mcp) — uv/PATH, stale README, client list
  - [Running both servers at once](#running-both-servers-at-once)
- [Authoring, assets and animation](#authoring-assets-and-animation) — humanoid import, edit-mode sampling, asset integrity, physics against a `Plane`
- [Instruments](#instruments) — installed package source, read-only C# probes
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
  (Historically only 16 of 52 findings ever carried this tag, so **do not use it as a
  selector** when collecting for upstream — read the sections.)

**One finding, one home.** The same trap is currently written out in full in two or three
files, and the copies drift: three of them were corrected in one place and left wrong in
another for over a week. So:

| Kind of thing | Lives in | Everything else |
|---|---|---|
| A recurring **shape** across several findings | [Patterns](#patterns), this file | links to it |
| An **observation** — a quirk, trap, version-specific behaviour | the relevant section of this file | links to it |
| A **verdict** — which arm to use, and why | [tooling-scorecard.md](docs/tooling-scorecard.md) | links to it |
| A **setup step** — how to stand the thing up | [unity-cli.md](docs/unity-cli.md) / [unity-mcp.md](docs/unity-mcp.md) | links to it |

Restating a finding elsewhere is fine when the reader needs it inline; **restating the
evidence is not.** Give the one-line version and link to the home. If you correct a
finding, search the other files for a copy before you close the loop — the copy is what the
next agent will read.

## Environment these notes were taken against

| | |
|---|---|
| Unity CLI | `1.0.0-beta.3` (beta channel — no stable channel published) |
| Unity Editor | `6000.5.5f1` (Unity 6.5, stream: SUPPORTED) |
| OS | Windows 11, PowerShell 5.1 + Git Bash |
| MCP | `unity mcp` (official, via CLI) registered as `unity-editor-mcp` |

---

## Patterns

The rest of this file is instances. This section is the shapes they fall into.

A shape earns a name at **three instances**; below that it is a coincidence and stays
where it was observed. Each pattern gives the general rule and what to do instead — the
point is that the *next* instance costs nothing rather than being solved from scratch.

Instances are listed by pointer, not restated. If you add one, add it here too; a pattern
that stops accumulating instances stops being evidence.

### P1 — reads-once-at-startup

> **A process reads its ambient state once, when it starts. Changing that state around a
> running process does nothing. Restart the process.**

The symptom is always the same and always misleading: the change is correct, the tool
reports it is not there, and every retry/refresh/reload confirms the tool.

| # | Instance | Where |
|---|---|---|
| 1 | `uv` must be on the Editor's PATH **at launch**; installing it while Unity runs leaves `uv not found in PATH` forever, and the window's Refresh does not help | [CoplayDev](#coplaydev-mcp-for-unity-comcoplaydevunity-mcp) |
| 2 | An MCP client fixes its tool list when it connects. A client started before the server was listening exposes zero tools even though the server returns all of them over raw HTTP | [unity-mcp.md](docs/unity-mcp.md#verify-and-recover) |
| 3 | The Editor snapshots its **cloud access token** at startup. `unity auth login` against a running Editor never reaches it; `Project Settings > Services` stays signed out, which reads as *"I need Unity Hub"*. It does not. Order is `unity auth login` **then** launch the Editor | [Log 2026-08-05](#2026-08-05--a-fourth-confident-wrong-answer-a-startup-snapshot-pattern-and-a-version-audit) |
| 4 | Windows GUI processes inherit a **snapshot of the user PATH** at launch. Claude Code started before the `unity` CLI was installed reports `Connection closed` for a healthy server, because the bare `unity` in the registration cannot resolve | [unity-mcp.md](docs/unity-mcp.md#setup) |
| 5 | Unity does not resolve a `Packages/manifest.json` change made while it is running — `hasPipelinePackage: true`, `isReachable: false`, indefinitely | [Sequencing gotcha](#sequencing-gotcha-cost-us-two-restarts) |
| 6 | **Claude Code snapshots its own hook configuration at session start.** A hook added to `.claude/settings.json` mid-session is not armed until a new session. Confirmed in the 2.1.222 binary: the startup path emits `setup_hooks_snapshot_ms` / `setup_hooks_captured` immediately after `setcwd` | `[source-confirmed, behaviour untested]` |

**The exception that proves the rule:** Unity's Pipeline MCP server *does* re-enumerate its
tools when Pipeline comes up late, so a client that connected first picks up all 140 on its
own. That repairs a missing *server*, not a stale *PATH* — instance 4 still requires a
restart. Do not generalise the exception.

**What to do instead.** Before blaming a config, ask what was running when it changed.
Set the ambient state first, then start the process — PATH, auth, packages, hooks, all of
it. When a tool insists something absent is present (or vice versa) and the config is
demonstrably right, restart before investigating further.

### P2 — the confident wrong answer

> **The `unity` CLI's defining failure mode is a plausible answer, not an error. Verify
> through a channel the tool does not own.**

Four instances, all in the same tool, none of which announced itself:

| # | Instance | Where |
|---|---|---|
| 1 | `unity editors running` listed **both** PIDs as having the project open when only one did | [Reliability](#reliability--ergonomics) |
| 2 | Path-less `unity open` silently launches a **second** bare Editor on the project picker rather than erroring | [Reliability](#reliability--ergonomics) |
| 3 | `unity pipeline list` resolves **cwd** as the project and invents a row — reported a "project" at `C:\Users\asas` with `Running: true` | [Reliability](#reliability--ergonomics) |
| 4 | `unity pipeline list --json` reported `isRunning: true` with zero `Unity.exe` processes, nothing bound on 7800-7810, and no `Library/EditorInstance.json` | [Log 2026-08-05](#2026-08-05--a-fourth-confident-wrong-answer-a-startup-snapshot-pattern-and-a-version-audit) |

**What to do instead.** Cross-check liveness against something the CLI does not produce:

```powershell
Get-CimInstance Win32_Process -Filter "Name='Unity.exe'" | Select ProcessId, CommandLine
Get-NetTCPConnection -State Listen | ? LocalPort -eq 7800
Test-Path .\Library\EditorInstance.json
```

Always `cd` to the project (or pass an explicit path) first. Use `--json` and read the
**narrowest honest field** — `pipelineServer.isReachable`, not `isRunning`, and never the
human table, which has several boolean-looking columns a loose grep will match wrongly.

### P3 — termination is not completion, and completion is not termination

> **Exit and success are uncorrelated in this toolchain, in both directions. Bound every
> call with a timeout and assert on the side effect.**

| # | Instance | Where |
|---|---|---|
| 1 | `unity mcp configure` writes `~/.claude.json` correctly, prints its confirmation, and then never exits | [Unity MCP](#unity-mcp) |
| 2 | `unity license --help` hangs even with `--non-interactive`; several other commands exceed 120s and finish fine when given longer | [Reliability](#reliability--ergonomics) |
| 3 | `UnityYAMLMerge` with no subcommand blocks indefinitely — to a terminal, redirected, and with `-h`. On a parse error it raises a **modal dialog** and waits, with git stuck behind it | [Git / UnityYAMLMerge](#git--unityyamlmerge) |
| 4 | A direct `Unity.exe` batch invocation **returns control** while the Editor keeps importing a fresh `Library` | [Log 2026-08-03](#2026-08-03--direct-unity-batch-mode-testing-on-windows) |
| 5 | `-quit` together with `-runTests` **exits 0** having compiled, run no tests, and written no results XML | [Log 2026-08-03](#2026-08-03--direct-unity-batch-mode-testing-on-windows) |
| 6 | `unity --help` and `unity editors info` return **255** while printing correct output | [Reliability](#reliability--ergonomics) |

**What to do instead.** Never gate on exit status. Give every invocation a generous timeout
(60s+ is normal; `tools/git/unityyamlmerge` bounds its call at 300s and reports a killed
merge as a conflict). Then assert on the artefact — the file that should have changed, the
port that should be bound, the XML that should exist.

### P4 — the green light that proves only the first of several states

> **A status field is evidence about its own layer and nothing above it. Name the states
> separately and check the last one.**

| # | Instance | Where |
|---|---|---|
| 1 | `claude mcp list` says `✓ Connected` while the server exposes **zero tools** — it is connected; it just has nothing to offer without `com.unity.pipeline` | [Unity MCP](#unity-mcp) |
| 2 | `hasPipelinePackage: true` with `isReachable: false` — the manifest entry exists, the Editor never resolved it | [Sequencing gotcha](#sequencing-gotcha-cost-us-two-restarts) |
| 3 | CoplayDev's green client row proves only **configured**. Separately: listening, and loaded by the client | [unity-mcp.md](docs/unity-mcp.md#verify-and-recover) |
| 4 | `isRunning: true` with `isReachable: false` and no Editor at all — see P2/4 | [Log 2026-08-05](#2026-08-05--a-fourth-confident-wrong-answer-a-startup-snapshot-pattern-and-a-version-audit) |
| 5 | A **bound** `0.0.0.0:7800` owned by the live Editor, refusing every connection — a stale listener from a dead Pipeline instance, while the live server had moved to 7801. `401` proves a server; *bound* proves only a socket | [Pipeline can drop out](#pipeline-can-drop-out-of-a-live-editor-session) |

Every intermediate broken state in this stack reports success *somewhere*. That is what
makes an out-of-order setup look like a broken install.

**What to do instead.** Write down the states before diagnosing — for an MCP server they are
**configured → listening → loaded**, and only the last one is what you wanted. Then find the
check that speaks to the last one: `unity list` for arm B (its error names all three
prerequisites, and it is the benchmark for what a good error looks like), `GET /health`
for arm C.

### P5 — the argument that is accepted and then ignored

> **A write that does not echo the resulting state has not been verified. Read it back.**

| # | Instance | Where |
|---|---|---|
| 1 | CoplayDev `manage_gameobject action=create` accepts `component_properties`, returns `"success": true`, adds the component, and leaves the property at its default. Source-confirmed: the create path never reads it | [scorecard T-001](docs/tooling-scorecard.md#t-001--build-the-same-gameobject-hierarchy-through-each-arm) |
| 2 | CoplayDev `set_property` returns only `{"instanceID": ...}` — no value — so a failed write is indistinguishable from a successful one | [scorecard](docs/tooling-scorecard.md#standing-observations) |
| 3 | A `[merge "unityyamlmerge"]` section with **any** key but no `.driver` kills every Unity-asset merge; with *no* keys git silently falls back to a text merge. Neither state is announced | [Git / UnityYAMLMerge](#git--unityyamlmerge) |
| 4 | Bare double quotes in a git config value are **stripped** on write — `git config --get` and the file on disk disagree, and the file is the one that lies | [Git / UnityYAMLMerge](#git--unityyamlmerge) |

**What to do instead.** Prefer the arm whose mutating calls echo state (arm B does; arm C
does not). Where you cannot, make the read-back a step of the operation rather than an
optional check — and read it from a different surface than the one you wrote through.

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

  That inner command is quoted **as the CLI emits it**, not as a form to copy.
  Its `--` sits after `unity mcp` rather than before, which is unusual — the
  conventional placement is `... unity-editor-mcp -- unity mcp --project-path`.
  Both work, and this one demonstrably did: it produced
  `{"command": "unity", "args": ["mcp", "--project-path", "<repo>"]}`, which is
  the registration this project has been driving the editor through. Recorded
  verbatim on purpose; if you're typing it yourself, prefer the conventional
  placement.

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

- Registering a **new server** mid-session does not expose its tools to an
  already-running agent session — restart to pick them up. ([P1](#p1--reads-once-at-startup))
  This is a different case from an *already-registered* server whose Pipeline comes up
  late, which needs no client restart; see the
  [sequencing gotcha](#sequencing-gotcha-cost-us-two-restarts).

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

### Pipeline can drop out of a live Editor session

**`[reproduced]`** Pipeline `0.4.0-exp.1` served an entire authoring trial and then stopped
serving in the *same* Editor session — no restart, no crash, no console error. The first
sign was an MCP client error naming a port nobody had configured:

```
Cannot connect to Unity Editor Pipeline server at 127.0.0.1:7801.
```

Five readings had to be assembled before the state was legible, and the first two are
actively misleading:

| Check | Reading | Alone, it says |
|---|---|---|
| `Get-Process Unity` | PID with the project's window title | Editor is fine — **true but irrelevant** |
| `Get-NetTCPConnection … 7800` | `0.0.0.0:7800` bound, owned by that PID | Pipeline is fine — **wrong** |
| `unity pipeline list --json` | `isRunning: true`, `port: 7801`, `isReachable: false` | the port moved |
| `GET http://127.0.0.1:7800/api/editor_status` | connection failure, **not `401`** | the 7800 listener is dead |
| the Editor's registered menu items | no `Pipeline/` entry among 443 | the editor assembly is gone |

**`401` is the health signal; "bound" is not.** The Pipeline API is token-gated, so a live
server answers an unauthenticated request with `401 Unauthorized` — see
[the HTTP API is authenticated](#unity-official-the-tool-surface-once-pipeline-is-live). A
socket that refuses the connection outright is a **stale listener** left behind by a previous
Pipeline instance: the port is bound and there is no server behind it. Every "is the port
open" check — `Test-NetConnection`, a bare `Get-NetTCPConnection` — will call that healthy.

**The decisive check is the menu list**, because it is the only one that speaks to the layer
that matters: whether Pipeline's editor assembly is loaded at all. If `Pipeline/` is absent
from the Editor's menu items, nothing is going to bind whatever the ports say. It also means
no arm can restart it from outside — `execute_menu_item "Pipeline/Start Server"` fails
because the menu item does not exist. **The recovery is an Editor restart**, the same as the
[sequencing gotcha](#sequencing-gotcha-cost-us-two-restarts), for a different cause.

Do not plan around Pipeline surviving a long session; observed after roughly eight hours of
continuous use on Editor `6000.5.5f1`. Root cause `[unverified]` — the manifest was correct
and `Library/PackageCache` still held the package throughout.

---

## Authoring, assets and animation

Everything above this point is about **standing the tooling up** — a phase each machine passes
through once. This section is about using it, which is where long sessions actually spend their
time, and it started empty. That gap was measured, not guessed: a 19-hour authoring session
consulted this file zero times and paid full price for thirteen traps, because none of them were
in it. Add what you hit here.

### Humanoid import: scale the root, never `globalScale`

**`[reproduced]` A small `ModelImporter.globalScale` builds an Avatar that passes every static
check and collapses in play mode.** Importing a 14.6 m model down to 2.6 m via
`useFileScale = false` + `globalScale = 0.0018` produced an Avatar reporting `isValid = True`,
`isHuman = True`, 53 bones mapped, and correct bind-pose bone positions in the editor — then
collapsed the whole skeleton to a point the instant the Animator evaluated.

Nothing flags it: not the editor, not the console, not the import log. **The tell is
`Animator.humanScale`** — it read `0.011` against the shipped player's `1.010`, with hips→head at
`0.008` vs `0.643`.

**Do instead:** import with `useFileScale = true` and resize via the **root transform's
`localScale`** on the prefab. Match the scale to **hips height (leg length)**, not total height —
stride length in retargeted locomotion clips follows leg length, so matching hips avoids foot
sliding. The reference in this project is `Armature.fbx`: hips at `y = 0.981`, `humanScale 1.010`.

### Verify humanoid poses in play mode, never edit mode

**`[reproduced]`** `AnimationMode.SampleAnimationClip` and `AnimationClip.SampleAnimation` both
produce **garbage poses** for these humanoid clips in the editor. A pose sampled in edit mode is
not evidence of anything, and chasing the difference is chasing a bug that does not exist. Enter
play mode to check retargeting.

This is a specific case of a general shape: the check that is cheap to run is not always the check
that is true. See [P4 — the green light that proves only its own layer](#patterns).

### Non-networked characters must declare the locomotion animation events

**`[reproduced]`** The shared locomotion clips fire animation events — `OnFootstepWalk`,
`OnFootstepRun`, `OnLand`, `TurnInPlaceStart`, `TurnInPlaceEnd` — which `CoreAnimator` normally
receives. `CoreAnimator` is a `NetworkAnimator` and requires a `NetworkObject`, so a **non-networked
NPC cannot use it**. Any character that is not the full `CorePlayer` must declare those five methods
itself, with signatures matching `CoreAnimator`'s, or Unity logs an error on every footstep.

### Telling a gutted asset from an unsmudged LFS pointer

Binary assets under `Assets/` are LFS-tracked, so a file that is *smaller than expected* has two
completely different causes and two different fixes. Check the byte size before diagnosing:

| Size | Cause | Fix |
|---|---|---|
| ~130 bytes | Unsmudged **LFS pointer** — content never fetched | `git lfs pull` |
| a few KB | Content **locally destroyed** while tracked | `git checkout -- <path>` |
| full size | Neither | Look elsewhere |

Observed on `Assets/Game/Worlds/OldForest/Data/OldForest_Terrain_Optimized.asset`: 27,603,308 bytes
intact, once seen at 8,720 bytes with the heightmap, splatmaps, detail and tree data all gone, while
`HEAD` still held the full asset. The symptom was a flat, collisionless, untextured terrain with
spawn points apparently floating — which reads as upstream damage and is not.

**Back up the damaged copy and surface it before restoring.** A wiped asset may be someone's
in-progress re-optimisation rather than corruption.

### A fresh clone opens an empty scene, and it looks exactly like broken LFS

**`[reproduced]`** Unity records *which* scene you had open in `UserSettings/`, which is
gitignored — correctly, it is per-person state. So a fresh clone, or a first launch on a new
machine, opens an **untitled empty scene** holding only `Main Camera` and `Directional
Light`. `list_open_scenes` reports `path: ""` and two roots. Nothing is missing; the project
has no record of your preference yet, and a collaborator sees a populated scene because he
opened one.

The trap is that this presents identically to an LFS smudge that never ran, which is a real
failure with a real fix. **The discriminator is a pointer grep over `Assets/`, and it costs
one call:**

```bash
rg -l '^version https://git-lfs\.github\.com' Assets/
```

Any hit means content was never fetched — `git lfs pull`. *No* hits means every binary is
materialised, and an empty-looking project is editor state rather than missing assets: open a
scene and it is over. Confirmed against 474 LFS-tracked files, zero pointers.

This answers a different question from
[telling a gutted asset from an unsmudged LFS pointer](#telling-a-gutted-asset-from-an-unsmudged-lfs-pointer):
that one is a byte-size test for a file you already suspect; this one is for a project that
looks empty and gives you no file to suspect.

Finding the scene to open costs one more read — arm B's `get_build_settings` lists the
registered scenes, and the first is the entry point.

### Unity's built-in `Plane` is a zero-thickness, single-sided collider

**`[reproduced]`** The `Plane` primitive carries a `MeshCollider` with `convex: false` over
Unity's default plane mesh — bounds `10 × 2.2e-16 × 10`. Two consequences that appear only
under physics queries. The inspector shows neither, and neither errors.

**1. It does not exist from below.** A non-convex `MeshCollider` is backface-free, so a ray
cast upward from underneath the floor misses. Not "hits the far side" — misses. The instant a
camera passes fractionally under such a floor, the floor stops existing for physics *and*
visually, and the whole level vanishes into skybox. A wall failing the same way at least
leaves you looking at geometry.

**2. `SphereCast` returns confident wrong distances within one radius of the surface.**
Casting downward-and-back from a sweep of origin heights, radius `0.4`, layer mask `1`:

| origin `y` | `SphereCast` | `Raycast` | |
|---|---|---|---|
| 0 | HIT @2.91 | HIT @3.37 | both implausible |
| 0.2 | HIT @3.11 | HIT @0.23 | the ray matches the geometry, the sphere does not |
| 0.39 | HIT @3.30 | HIT @0.45 | sphere's underside is already through the plane |
| **0.41** | HIT @0.01 | HIT @0.47 | correct — an immediate hit |
| 1.0 | HIT @0.67 | HIT @1.12 | correct |
| 1.5 | HIT @1.21 | HIT @1.65 | correct |

The break is exactly at the cast radius. Below `y = 0.4` the sphere already intersects the
zero-thickness plane at the cast origin, and Unity returns a plausible distance instead of an
immediate hit or a miss — so a caster sitting on the floor is told there are three metres of
clear space below it. `[the degenerate-overlap explanation is inferred, not confirmed]`

Anything that spherecasts from within its own radius of a plane floor inherits this: camera
deoccluders, ground checks, crouch probes. **Cross-check with a `Raycast`** — it stayed
correct at every height. This is [P2](#p2--the-confident-wrong-answer) outside the `unity`
CLI: the API does not error, it answers.

Corollary for test scenes: a sandbox floored with Unity's `Plane` is not representative of a
game floored with terrain or any mesh that has thickness. A camera bug that only reproduces
in the test scene may be the floor, not the camera.

## Instruments

Two ways of getting evidence that no tool exposes directly. Both are read-only, both settled
a question this record had previously been guessing at, and neither is obvious from any tool
list — which is why they are written down as method rather than as findings.

### `Library/PackageCache/<pkg>@<hash>/` is the installed source

Every Unity package is unpacked into `Library/PackageCache/<name>@<hash>/` with its C# intact.
That directory is the **exact version you are running**, pinned by the hash — not the tip of a
GitHub repo that may have moved, and no clone required. `Glob` and `Grep` reach it directly.

It is the fastest way to settle "is this the tool's bug or my call?", and the answer is
routinely not what black-box observation suggested. The `component_properties` finding was
recorded as *"`create` silently drops the property"* on black-box evidence; the source showed
`GameObjectCreate.cs:239-258` **does** implement per-component properties, through a nested
shape that the Python layer's schema rejects before it reaches Unity — a different bug, in a
different layer, with a different fix. See
[scorecard T-001](docs/tooling-scorecard.md#t-001--build-the-same-gameobject-hierarchy-through-each-arm).

Two cautions. `Library/` is gitignored, so a path into it is not a citation anyone else can
follow — quote the file, line and version. And it is *installed* source, so it goes stale
silently the moment the package updates; stamp the hash you read.

### Read-only C# probes, returning a table

Neither MCP arm exposes raycasts, bounds, or any physics query. The introspection tools read
serialized fields, and a serialized field cannot tell you what a cast returns — so a whole
class of geometry question has no route through the tool surface at all, which is what pushes
these questions toward `eval` / `execute_code`.

The shape that works is a snippet that **mutates nothing**, sweeps the one variable in
question, and returns a string:

```csharp
var sb = new System.Text.StringBuilder();
foreach (var h in new[] { 0f, 0.2f, 0.39f, 0.41f, 1.0f, 1.5f })
{
    // ... query at h ...
    sb.AppendLine("origin y=" + h + "  SphereCast=" + a + "  Raycast=" + b);
}
return sb.ToString();
```

The sweep is what makes it an instrument rather than an anecdote: a single query at one height
would have read as a plausible number, and the table is what exposed the discontinuity at the
radius. Including a control in the same run — the `Raycast` column — is what made "the sphere
is wrong" a claim rather than a suspicion.

`eval` / `eval_file` (arm B) and `execute_code` (arm C) are in the always-ask permission tier
and should stay there, so this is a deliberate call each time. But the read-only probe is a
genuinely different risk from an authoring call through the same tool, and the output table
drops straight into a bug report as evidence.

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
  both hang git.** Use `tools/git/unityyamlmerge` for any non-interactive use.
  It passes `-h --fallback none` — but **do not copy those flags bare**; the
  second one destroys your side of a real conflict. See the warning below.
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
  documentation. Both flags together merge a real scene correctly — two
  independent edits, both preserved, object count unchanged.

  **⚠️ `--fallback none` destroys your side of a genuine conflict. Do not pass
  it bare.** `[reproduced]` The test above cannot detect this, because
  *independent* edits are precisely the case that merges cleanly. On an
  **unresolvable same-field conflict**, UnityYAMLMerge writes **their** content
  into `dest` and exits 2 — and in driver mode `dest` **is `%A`, your own file**:

  ```
  A: base THEIRS OURS dest   -> exit=2  OURS=0  THEIRS=1
  B: base OURS THEIRS dest   -> exit=2  OURS=1  THEIRS=0   (argument order only
                                                            decides who wins)
  C: without --fallback none -> exit=1  OURS=1  THEIRS=0
  ```

  Isolated with `dest` kept separate from `ours`: `ours.unity` untouched
  (`OURS=1 THEIRS=0`) while `dest` held `OURS=0 THEIRS=1`. Git then marks the
  path conflicted holding **only their version**, so resolving by accepting the
  file silently loses local work, with nothing anywhere recording that it
  happened. Non-conflicting merges are unaffected (`exit=0`, both edits kept),
  which is why every earlier test passed.

  **`tools/git/unityyamlmerge` already handles this** — it snapshots our side
  before invoking, and on failure restores it and runs `git merge-file` so the
  conflict arrives as ordinary markers with both versions
  (`OURS=1 THEIRS=1 markers=2`). Clean merges still exit 0. **The danger is in
  copying the flag out of this file into a hand-rolled driver.** Use the
  wrapper, or reproduce its recovery path.

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

### 2026-08-05 (evening) — six findings mined from an 8-hour session, and an instruments section

Widening coverage the way the previous entry concluded it had to be widened: from a session
transcript, at [T3](docs/tooling-experiment.md#evidence-tiers), for work that was not about
this record. The source is a 2026-07-28 session, 8h14m and 393 tool calls, doing ordinary
work — standing up a clone, running a trial, chasing a camera bug. It was mined with a script;
at 4.9 MB it cannot be read.

**Pipeline stopped serving inside a live Editor session**, having worked for hours, and every
port-level check said it was fine. The two lessons generalise past this bug: `401` is the
Pipeline health signal, because a *bound* port can be a stale listener with nothing behind it;
and the check that actually settles it is whether `Pipeline/` appears in the Editor's menu
items, which speaks to the layer that matters. Recorded as
[Pipeline can drop out](#pipeline-can-drop-out-of-a-live-editor-session) and as a fifth
instance of [P4](#p4--the-green-light-that-proves-only-the-first-of-several-states).

**A fresh clone opens an untitled scene, which reads as broken LFS.** Both produce a project
that looks empty; one is normal and one needs `git lfs pull`. One pointer grep over `Assets/`
separates them. Recorded in
[Authoring](#a-fresh-clone-opens-an-empty-scene-and-it-looks-exactly-like-broken-lfs).

**Unity's built-in `Plane` is a zero-thickness, single-sided collider**, and `SphereCast`
returns confident wrong distances within one cast radius of it — three metres of clear space
that is not there, while a `Raycast` from the same origin stays correct. The record's
[P2](#p2--the-confident-wrong-answer) had only ever been written as a `unity`-CLI quirk; this
is the same shape in the physics API, which is what the pattern layer exists to make cheap.

**Two instruments, written up as method rather than as findings.**
`Library/PackageCache/<pkg>@<hash>/` holds the exact installed source, version-pinned and
grep-able without a clone; reading it turned a black-box finding
(*"`create` drops the property"*) into a different and more accurate one (*the C# implements
it; the Python schema makes the working shape unreachable*). And a read-only C# probe that
sweeps one variable and returns a table is the only route to physics and geometry questions
the tool surface does not expose — the sweep, with a control column, is what makes it evidence.
Both are in a new [Instruments](#instruments) section.

**Redundancy paid in the other direction.** The scorecard recorded B being used to stand C up;
here C carried the session after B dropped out. Verdict and the matrix row are in the
[scorecard](docs/tooling-scorecard.md#capability-matrix); the anti-capability it exposed —
arm C's `manage_scene` refusing on a dirty scene with no discard action, so the only way past
is `execute_code` — is in the
[anti-capabilities table](docs/tooling-scorecard.md#anti-capabilities).

### 2026-08-05 (later) — a pattern layer, a corrected health check, and a retrieval measurement

**A `/health` endpoint exists on CoplayDev's server, and the `406` advice was wrong.**
`docs/unity-mcp.md` told readers to `GET /mcp` and treat HTTP `406` as healthy. `406` only
proves *something* is listening and is picky about `Accept` headers. CoplayDev's own CLI
checks health properly: `cli/utils/connection.py` builds `http://{host}:{port}/health` and
treats `status_code == 200` as connected, and the same module reads `GET /api/instances`,
which additionally proves an Editor is attached. Source-confirmed against
`mcpforunityserver 10.0.0` as installed in the local `uv` cache. Corrected in place.

**`[feedback]` The Unity-side CoplayDev package has no `/health` route of its own.**
`HealthStatus.cs` defines `Healthy`/`Unhealthy` string constants for the Editor window's
own UI only. The HTTP health surface lives entirely in the Python server, so a diagnosis
that starts from the Unity package finds a health *concept* with no endpoint behind it.

**Claude Code snapshots its hook configuration at session start.** Confirmed in the
`2.1.222` binary: the startup path emits `setup_hooks_snapshot_ms` / `setup_hooks_captured`
immediately after `setcwd`, before the file watcher is installed. So a hook added to
`.claude/settings.json` mid-session is not armed until a new session — a sixth instance of
[P1](#p1--reads-once-at-startup), and one that applies to the tooling *around* this repo
rather than inside it. `[source-confirmed, runtime behaviour untested]`

**Duplicated findings drift, and the drift is one-directional.** Three findings were
corrected in one file and left wrong in another for over a week — the confident-wrong-answer
count (three in `docs/unity-cli.md`, four here), the duplicate-`instanceId` claim (marked
not-reproduced here, still asserted as a standing verdict in the scorecard), and
`mcp-for-unity-server 3.4.5` (corrected here, still in the scorecard's comparison table).
In every case the stale copy sat in the file a reader is *directed* to. Corrected, and the
[one finding, one home](#how-to-contribute) convention added so the next correction has a
defined place to propagate to.

**Retrieval measured, and the number is worse than the design assumed.** Sampled the
longest available multi-goal session (2026-08-05, ~19h wall clock, 38 human turns, 462 tool
calls, driving this Editor throughout): **the record was never opened. Not once.** Not in a
tool call, not in prose. It was present in that checkout the whole time. `AGENTS.md` and
the scorecard predate the session; `UNITY-TOOLING-NOTES.md` landed in `main` about an hour
into it.

Documented traps hit before consulting: **0**, upper bound **1**. Not because the session
was well-informed — because the record and the session barely overlapped. The record is
overwhelmingly about the `unity` CLI; that session invoked the CLI **zero times** across 88
shell calls and reached the Editor entirely through arm B. Against thirteen novel traps it
paid full price for (degenerate humanoid Avatars from `ModelImporter.globalScale`, an
asmdef silently dropping scripts from the build with no console error, `text=auto` eating
bytes from a 27 MB binary `.asset`, `.unitypackage` dependency export dragging in the URP
shader tree), the rediscovered-to-novel ratio was roughly **1:13**.

Two things follow, and the second is the uncomfortable one. Retrieval genuinely is not
automatic — nineteen hours, no consult. But the record's *coverage* is the binding
constraint before its retrieval is: a forcing function that had fired perfectly on turn 1
would have saved this session almost nothing. The corollary is that the one trap class it
does hit — [P2](#p2--the-confident-wrong-answer), verify the effect rather than the tool's
confident report — recurred three times in forms the record does not name, because it is
written as a `unity`-CLI quirk rather than as a general rule. That is what the
[Patterns](#patterns) section is for.

**Mechanism built, not wired.** `tools/agent/unity-trap-check.py` is a `PreToolUse` hook
that matches the tool call and injects the relevant finding via
`hookSpecificOutput.additionalContext` before the call runs. 17 rules, each citing a
finding already in this file; narrow triggers fire every time, broad ones at most hourly,
and it never blocks or denies. `--selftest` runs the rule set against fixtures including
the false-positive that matters (a `cd` into a path containing "unity"). Wiring it requires
an edit to `.claude/settings.json`, which is deliberately left to a human — the fragment is
in the script's header.

### 2026-08-05 — a fourth confident-wrong-answer, a startup-snapshot pattern, and a version audit

Versions at time of writing: CLI `1.0.0-beta.3`, Editor `6000.5.5f1`, Pipeline
`0.4.0-exp.1`, CoplayDev `v10.0.0` installed (`v10.1.2` current).

**Version currency.** CLI and `com.unity.pipeline` are both **exactly current** —
`latest-beta.json` pins the same CLI build and the registry's `dist-tags.latest` is
`0.4.0-exp.1`; stable `latest.json` still 404s. So CLI and Pipeline findings in this file are
live, not stale. **`com.coplaydev.unity-mcp` is three releases behind** (v10.0.2, v10.1.0,
v10.1.2) — re-confirm any arm-C finding against v10.1.2 before relying on it. Editor
`6000.5.7f1` exists; anything blamed on the Editor is unverified against current.

**`[feedback]` `unity pipeline list` reports `isRunning: true` for a project with no Editor.**
Observed with zero `Unity.exe` processes, nothing listening on 7800-7810, and no
`Library/EditorInstance.json`:
```json
"projectName": "…-gabe", "isRunning": true, "hasPipelinePackage": true,
"pipelineServer": { "isReachable": false, "apiUrl": null }
```
Only `isReachable`/`apiUrl` are honest. `unity editors running --json` — same CLI, same cwd,
same session — correctly returned `{"count": 0}`. There is no stale lock file to explain it.
This is the **fourth** instance of the confident-wrong-answer pattern (with `editors running`,
path-less `unity open`, and `pipeline list`'s invented cwd row). Cross-check liveness against
process command lines and port bindings.

**Pattern: reads-once-at-startup.** Three instances now recorded in this file, so stating the
general rule: **changing ambient state around a running process does nothing — restart it.**
1. `uv` must be on the Editor's PATH *at launch*; Refresh never recovers.
2. MCP tool lists fix at client start; a client started before the server sees no tools.
3. **New:** the Editor snapshots its cloud access token at startup. `unity auth login` while
   the Editor is running leaves it signed out indefinitely —
   `[Licensing::Module] Error: Access token is unavailable; failed to update`. After a restart
   with the CLI already authenticated: `Successfully updated the access token`. The symptom is
   a signed-out `Project Settings > Services`, which reads as *"I need Unity Hub"* — it does
   not. Verified with Hub.exe absent from the machine. Order is `unity auth login` **then**
   launch the Editor.

**`[feedback]` The CLI keeps no record of the commands you run.**
`%APPDATA%\UnityHub\logs\cli-log.json` had 1,420 entries in one day and zero record of any
invoked command — only internal modules (`CliLicensingSdkAdapter`, `CloudConfig`,
`IdentityProvider`). For a tool whose documented failure mode is returning confident wrong
answers, there is no audit trail of what was asked. Note the tension: beta.3 *"expanded the
opt-in usage analytics to record which commands run"* — command names go to analytics
(opt-in, default off) but not to the local log.

**Undocumented CLI surface worth knowing.**
- `unity status` — one line giving port, state, project, version and PID for every connected
  Editor. Strictly better than `unity editors running` for liveness.
- `unity cloud org list` / `unity cloud project list` exist; `unity cloud --help` prints no
  `Commands:` section, same trap as `editors`.
- **`[feedback]`** `unity cloud project list --cloud-org <id>` returns
  `Fetched 0 of 0 projects before failure at offset 0: Request failed with status code 403`
  for a `project guest` role. Guests cannot enumerate an org's projects; the message should
  say so. As written it reads as a missing invitation.
- `unity bug --help` does **not** hang, and states it reports *"directly to the Unity bug
  reporter"* — i.e. Unity's private QA intake, defaulting to the signed-in account's email.
  No report ID is offered anywhere in its interface.

**`[feedback]` Pipeline `get_scene_hierarchy` has no depth, limit, or pagination.**
Its only parameter is `path`. On a real scene it returned **290,642 characters / 7,883 lines**
and exceeded the client's token limit outright. `find_gameobjects` likewise has no
limit/offset. Unity has already solved this class for captures in 0.4.0-exp.1 (path-only
returns *"so agent tool results stay small"*).

**`[feedback]` Pipeline `get_component_properties` cannot read common value types.**
Returns the literal strings `"<unsupported:Quaternion>"` for `m_LocalRotation` and
`"<unsupported:LayerMask>"` for layer masks. Rotation is not an exotic field. Related: there
is no terrain introspection at all — reading `TerrainData` bounds has no read-only route,
which pushes a read-only question toward `eval`.

**⚠️ Do not install `com.unity.ai.assistant` on Unity 6.5.** It ships its own relay MCP
(named pipes) distinct from Pipeline, but on 6.5 it livelocks the AssetDatabase at startup —
main thread at 100% in `AssetDatabase::InitialRefresh` → `GuidDB::ValidateChangedGUIDs`, from
a circular dependency between `com.unity.ai.inference` and `com.unity.asset-manager-for-unity`.
The Editor never finishes loading, so *every* MCP bridge fails and gets blamed. Recovery:
remove it from `manifest.json`, **delete `packages-lock.json`**, clear `Library/`. Disabling
is insufficient — it re-adds itself.
[CoplayDev#1219](https://github.com/CoplayDev/unity-mcp/issues/1219). `[unverified]` locally —
deliberately not reproduced.

**Corrections to earlier entries.**
- The scorecard's `mcp-for-unity-server 3.4.5` is **FastMCP's version, not CoplayDev's**.
  `Server/src/main.py` constructs `FastMCP(name="mcp-for-unity-server", …)` with no `version=`
  argument, so the handshake falls back to FastMCP's own; `pyproject.toml` pins
  `fastmcp>=3.0.2,<4`. The server version tracks the package version — v10.0.0 → server
  10.0.0. There is no `mcp-for-unity-server` package on PyPI; the real one is
  `mcpforunityserver`.
- **`[not reproduced on CLI 1.0.0-beta.3]`** `unity editors running --json` exited **0** with
  correct output. The unreliable-exit-code note names `--help` and `editors info`
  specifically; this subcommand behaves.
- **`[not reproduced on Pipeline 0.4.0-exp.1]`** the duplicate-`instanceId` finding in
  `docs/tooling-scorecard.md`. Four distinct GameObjects returned four distinct ids. Three
  *components on one GameObject* did share an id while their `globalId`s differed, which is a
  different and plausibly correct behaviour.

**Naming trap.** The `unity-editor-mcp` MCP registration is **Unity's official CLI-hosted
server** (arm B). It is unrelated to the dead 10★ GitHub repo `akiojin/unity-editor-mcp`.

### 2026-08-04 — CoplayDev particle preview can persist prefab material changes

- Unity Editor `6000.5.5f1`, `com.coplaydev.unity-mcp` `v10.0.0`: while a
  third-party particle prefab was open in Prefab Mode, `manage_vfx` with
  `action="particle_play"` reported `materialReplaced: true` and
  `replacementReason: "missing_material"`. The source prefab YAML changed on
  disk even though no explicit save action was requested. A SHA-256 comparison
  against the untouched source copy caught the mutation, and restoring the
  prefab plus `.meta` returned both hashes to the originals. Preview disposable
  copies or verify source hashes when inspecting third-party VFX this way.
- The same setup's `validate_script` reported a duplicate zero-parameter
  `ResolveSelectedSpell` signature even though the source contained one method,
  Unity completed its domain reload, and the Console showed zero compiler
  errors. Treat this validator diagnostic as advisory and verify against the
  source plus actual Unity compilation.

### 2026-08-04 — CoplayDev structured script edits can drop signature indentation

- Unity Editor `6000.5.5f1`, `com.coplaydev.unity-mcp` `v10.0.0`: observed
  `script_apply_edits` with `replace_method` and `insert_method` preserve the
  supplied method body indentation but place the method signature at column 1.
  The generated C# remains valid, but formatting needs a follow-up text edit.

### 2026-07-29 — permission tiers, and an ask-vs-allow anomaly (Claude / Fable 5)

Restructured `.claude/settings.json` around Claude Code's documented rule
precedence (PR #7): rules evaluate deny → ask → allow across every settings
file, first match wins — which would make a committed `ask` rule
un-overridable by a personal `allow`, and would mean "always allow" at such a
prompt writes a local rule that never fires. Trimmed the ask list to the
arbitrary-code class accordingly; opt-ins moved to
`settings.local.json.example`.

Then tried to verify the claim live and couldn't: with `Bash(npm view *)` in
the project `ask` list and the same pattern in the user-level `allow` list,
`npm view` ran twice with no prompt (Claude Code 2.1.220). `[unverified]`
which explanation holds — mid-session reload semantics for edited rule
arrays, the session's permission mode, or the docs being wrong. Issue #8 has
the full protocol for the clean fresh-session experiment. The tier design
doesn't depend on the answer: a minimal ask list plus unlisted-by-default
opt-ins is correct under either semantics.

Installed CLI 1.0.0-beta.3 and editor 6.5.5f1 from scratch on a clean Windows
box; cloned this repo; configured the merge driver; registered the MCP server.
Everything above was observed during that session. Filed issue #1 with a
proposed portable fix for the merge-driver setup (`tools/git/unityyamlmerge`,
`.gitconfig-unity`, `tools/git/setup.sh` / `.ps1`).

Not yet exercised: the MCP tool surface itself (registered but not used), and
`unity build` / `unity test`.

### 2026-07-28 (later) — getting the MCP servers actually working

Chased down why `unity-editor-mcp` reported `✓ Connected` while exposing zero
tools: it needs `com.unity.pipeline` in the project and an Editor restart to
resolve it. Documented the full ordering above.

`[corrected]` — this entry originally added "and then a *second* MCP-client restart to
re-enumerate." That is wrong and contradicted the
[sequencing gotcha](#sequencing-gotcha-cost-us-two-restarts), which is the canonical
statement: the server re-enumerates on its own when Pipeline comes up, and only the
**Editor** restart is required. A client restart *is* required for the distinct case of a
stale PATH snapshot ([P1](#p1--reads-once-at-startup)/4) — which is what made the two
readings look compatible for a week.

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

### 2026-08-03 — direct Unity batch-mode testing on Windows

- Unity Editor `6000.5.5f1`: supplying `-quit` together with `-runTests` caused
  the Editor to compile successfully and exit with code 0 without running the
  requested EditMode tests or writing the `-testResults` XML. Removing `-quit`
  let the Test Framework own shutdown and produced the expected XML (11 tests,
  all passed in the observed run).
- A direct PowerShell invocation of `Unity.exe` returned control while the
  batch Editor process continued importing a fresh Library. `Start-Process
  -Wait -WindowStyle Hidden` kept the shell attached. Verify the actual process,
  log completion marker, and filesystem effects rather than trusting the first
  shell return.

### 2026-08-04 — URP particle upgrader needs blend-mode finalization

- Unity Editor `6000.5.5f1`, URP `17.5.0`: calling
  `UnityEditor.Rendering.Universal.ParticleUpgrader.Upgrade` directly changed
  legacy `Particles/Standard Surface` and `Particles/Standard Unlit` materials
  to their URP particle shaders and copied their textures/colors, but the
  resulting transparent materials initially retained opaque blend state
  (`_DstBlend=0`, `_ZWrite=1`) despite `_Surface=1`. Calling
  `UnityEditor.BaseShaderGUI.SetupMaterialBlendMode` afterward produced the
  expected transparent queue and blend/Z-write state. The `BaseShaderGUI` type
  is in the `UnityEditor` namespace in this package version.
