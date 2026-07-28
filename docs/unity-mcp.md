# Unity MCP

Driving the Unity Editor from an AI agent. Written against CLI `1.0.0-beta.3`,
editor `6000.5.5f1`, Pipeline `0.4.0-exp.1`, MCP for Unity `v10.0.0`,
2026-07-28.

There are **two different MCP servers** that can drive this project. They are
unrelated implementations.

| | Unity official | CoplayDev |
|---|---|---|
| Editor package | `com.unity.pipeline` | `com.coplaydev.unity-mcp` |
| Server | bundled in the `unity` CLI | Python, run via `uvx` |
| Configured by | `unity mcp configure <client>` (CLI) | in-Editor window (GUI) |
| Editor channel | Pipeline HTTP `:7800` | HTTP MCP `:8080` (`/mcp`) |
| Clients | ~16 | 22 |
| Status here | **working, 140 tools** | **working; Claude Code, Antigravity 2.0 and Codex configured** |

`com.coplaydev.unity-mcp` is already in `Packages/manifest.json`;
`com.unity.pipeline` is currently an **uncommitted** local addition.

---

## Unity official

### Setup

Order matters. Each step looks fine when it isn't, so do them in sequence.

**1. Install the Pipeline package.** The MCP server exposes *zero tools*
without it, while still reporting itself connected.

```bash
cd <repo>
unity pipeline install        # adds com.unity.pipeline to Packages/manifest.json
```

**2. Restart the Unity Editor.** Unity does not resolve a manifest change made
while it is running. You'll see `hasPipelinePackage: true` but
`isReachable: false` until it restarts.

**3. Wait for the import.** The Pipeline HTTP server binds late — the editor
sits on "Opening project..." for a while first. Poll the machine-readable
field, not the table:

```bash
unity pipeline list --json | grep -o '"isReachable":[a-z]*'
```

**4. Register the client.**

```bash
unity mcp configure claude-code --project-path <repo>
unity mcp configure --list     # all supported clients
```

For Claude Code this **delegates** rather than writing a file itself — it shells
out to `claude mcp add --scope user --transport stdio unity-editor-mcp unity mcp -- --project-path <repo>`
and modifies `~/.claude.json`. Note that's **user scope with a hardcoded project
path**: global across your machine but pinned to this project. Re-scope it if
you work on more than one Unity project.

The command completes its work and then **never exits** — the config lands
correctly; the process just doesn't return. Verify the side effect rather than
waiting on it.

**No client restart is needed.** The server re-enumerates its tools when the
Pipeline server comes up; a client that connected earlier picks up all 140 on
its own.

### Verify

```bash
unity list                     # from the repo root; lists tools the editor exposes
claude mcp list                # should show unity-editor-mcp connected
```

`✓ Connected` alone is **not** proof it works — that's true even with zero
tools. `unity list` is the honest check, and its error names all three
prerequisites when something's missing.

### The tool surface

140 tools, all `built-in`. Scene/GameObject authoring, prefab editing in
isolated stages, script create/attach, play mode, packages, settings, bakes
(navmesh/occlusion/lighting), test runner, screenshots, console access.

The design is careful in ways worth knowing:

- **17 destructive tools require `confirm=true`** — `delete_asset`,
  `package_remove`, `write_text_file`, `switch_build_target`, every
  `set_*_settings`. Several also accept `dry_run`.
- **`set_authoring_root` confines paths** to a subtree of `Assets/`, so an agent
  can be scoped to one folder.
- **Async work polls** — `bake_navmesh` → `navmesh_bake_status`, `package_add`
  → `package_status`, anything causing a domain reload → `recompile_status`.
- **Compile order is explicit** — `create_script` documents that the type does
  not exist until a recompile finishes, and `attach_script` returns a
  *recoverable* error telling you to recompile and retry.

### Security notes

- **The HTTP API requires an auth token.** Direct requests to
  `http://127.0.0.1:7800/api/*` return `401 Unauthorized`. Go through `unity`
  or the MCP server.
- **But it binds `0.0.0.0`, not loopback** — despite reporting its own `apiUrl`
  as `127.0.0.1`. On an untrusted network that port is reachable from other
  machines. Token-gated, but not what the reported URL implies.
- **`eval` and `eval_file` run arbitrary C# in the editor.** They bypass every
  `confirm=true` guard, since anything those guards protect can be done from C#
  directly. Decide deliberately whether agents may call them.

### Manual controls

The editor gains a top-level **Pipeline** menu: `Start Server`, `Stop Server`,
`Settings...`. If the MCP goes dead, `Pipeline/Start Server` restarts it
without the CLI.

---

## CoplayDev (MCP for Unity)

The package is already in `Packages/manifest.json`. Setup is **GUI-driven** and
cannot be fully scripted.

### Prerequisites

- **Python 3.10+** — 3.13 works.
- **`uv` / `uvx`** — `winget install astral-sh.uv`, or see
  [astral.sh/uv](https://astral.sh/uv).

**`uv` must be on the Editor's PATH when the Editor starts.** Installing it
while Unity is running leaves the window reporting `uv not found in PATH`
permanently — a process reads PATH once, at startup, and the window's Refresh
button doesn't change that. Restart the Editor from a shell that already has
`uv`, or point the window at the binary explicitly. winget installs to:

```
%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_*\uv.exe
```

### Setup

Menu: **`Window > MCP for Unity > Toggle MCP Window`**. (It's a submenu with
three entries — `Toggle MCP Window`, `Local Setup Window`, `Edit EditorPrefs`.)

In the **Connect** tab:

1. Confirm the *UV Package Manager* row is green.
2. **Start Server** — transport `HTTP Local`, default `http://127.0.0.1:8080`.
3. Under **Per-client setup**, pick your client and **Configure**.

Prefer per-client setup over **Configure All Detected Clients**, which writes
config for all 22 supported clients rather than the one or two you use.

The first **Start Server** click opens a one-time confirmation explaining that
the server runs headless and logs to the Unity Console. After accepting it,
wait until the window shows both:

- `Session Active (<project-name>)`
- **Stop Server** and **Disconnect** buttons

`Starting...` is not a failure. The first run may spend several seconds
resolving the Python environment before the status changes.

> The README bundled with the package is **out of date**. It describes a
> "Server Status / Unity Bridge / MCP Client Configuration" layout with an
> **Auto-Setup** button; v10.0.0 ships Connect / Tools / Resources / Asset Gen /
> Deps / Advanced with **Configure All Detected Clients**. Follow the UI.

### Supported clients

From `Editor/Clients/Configurators/` — reading that directory is the fastest
way to answer "is X supported":

Antigravity, AntigravityIde, CherryStudio, ClaudeCode, ClaudeDesktop, Cline,
CodeBuddyCli, Codex, CopilotCli, Cursor, GeminiCli, KiloCode, KimiCode, Kiro,
OpenClaw, OpenCode, QwenCode, Rider, Trae, VSCode, VSCodeInsiders, Windsurf.

**Grok is not supported.**

### Reference: one known-good configuration

The per-client configurators write different formats to different locations.
Below is a worked example — the registrations produced for three clients on a
Windows 11 setup, 2026-07-28. Treat it as a reference for what *correct* looks
like, not as a description of your machine.

**Claude Code**

The configurator invokes Claude Code's own MCP registration flow. Verify the
result from the repository root:

```powershell
claude mcp list
```

The CoplayDev entry is named `UnityMCP` and should report:

```text
UnityMCP: http://127.0.0.1:8080/mcp (HTTP) - Connected
```

This is separate from the official server's `unity-editor-mcp` entry. One can
be healthy while the other is not.

**Antigravity 2.0**

Use the **Antigravity 2.0** configurator for the current CLI. Do not choose
**Antigravity IDE** unless configuring the IDE integration; they are separate
rows. The 2.x configurator writes:

```text
%USERPROFILE%\.gemini\config\mcp_config.json
```

with the effective shape:

```json
{
  "mcpServers": {
    "unityMCP": {
      "serverUrl": "http://127.0.0.1:8080/mcp",
      "type": "http",
      "disabled": false
    }
  }
}
```

Restart the Antigravity CLI after configuring it.

**Codex**

The configurator appends this to `%USERPROFILE%\.codex\config.toml`:

```toml
[mcp_servers.unityMCP]
url = "http://127.0.0.1:8080/mcp"
```

Codex discovers an MCP server's tool schemas when the desktop app starts. A
new task or reopened conversation is not enough. Fully quit and relaunch the
Codex desktop app while the Unity-side server is already running. If the
server was down during startup, the config can be correct while Tool Search
returns no Unity tools.

### Verify and recover

Treat these as three separate states:

1. **Configured** — the client config contains the `unityMCP` entry.
2. **Listening** — the HTTP server responds on port 8080.
3. **Loaded** — the client has discovered and exposed the Unity tool schemas.

The green client row in the Unity window proves only the first state. The
`Session Active` row proves the editor bridge is connected. To check the HTTP
listener without an MCP client:

```powershell
try {
  Invoke-WebRequest http://127.0.0.1:8080/mcp -Method Get -TimeoutSec 5
} catch {
  [int]$_.Exception.Response.StatusCode
}
```

An HTTP `406` is a healthy result for this deliberately incomplete GET: the
server is reachable but expects an MCP-compatible `Accept` header. Connection
refused or a timeout means **Start Server** is needed in the Unity window.

Recovery order:

1. Open **Window > MCP for Unity > Toggle MCP Window**.
2. Confirm Python and UV remain green.
3. Click **Start Server** and wait for `Session Active`.
4. Confirm the selected client says `Configured`.
5. Restart the affected client. For Codex, quit the whole desktop app.

Starting the server after Codex is already running may make the endpoint
healthy without adding tools to that existing Codex process.

---

## Running both at once

They coexist without conflict — separate packages, processes and ports, and MCP
clients namespace tools as `mcp__<server>__<tool>`, so identical tool names do
not collide.

The costs are subtler than a collision:

- **Selection ambiguity.** Two servers exposing `editor_play` /
  `get_scene_hierarchy` means an agent picks arbitrarily. Same task, different
  route, different bugs — hard to reason about after the fact.
- **Shared global editor state.** Calls serialize on the editor's main thread so
  there are no torn writes, but each server holds assumptions (Unity's sticky
  authoring root, selection, play mode, open scene) that the other can
  invalidate silently.
- **Domain reloads.** A recompile triggered through one can invalidate an
  in-flight operation on the other.

Reasonable for evaluation. Pick one for daily use.

## Related

- [unity-cli.md](unity-cli.md) — installing the CLI and the editor
- [../UNITY-TOOLING-NOTES.md](../UNITY-TOOLING-NOTES.md) — running log of quirks
- [../AGENTS.md](../AGENTS.md) — orientation for agents
