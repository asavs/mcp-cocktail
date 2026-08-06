# T-004 arm C — MCP for Unity (CoplayDev), `mcp__UnityMCP__*`

**Outcome: the objects were not created. Every call that needs the Unity Editor failed
with the same error. The MCP server process is alive and answers server-only calls; the
Unity-side plugin has not been connected to it since 2026-07-29.**

## Versions actually observed

| Thing | Value | Where it came from |
| --- | --- | --- |
| Unity Editor | `6000.5.5f1 (d16e074b49fd)` | `ProjectSettings/ProjectVersion.txt`, corroborated by the running editor's binary path `C:\Program Files\Unity\Hub\Editor\6000.5.5f1\Editor\Unity.exe` |
| MCP for Unity package (declared) | `https://github.com/CoplayDev/unity-mcp.git?path=/MCPForUnity#v10.0.0` | `Packages/manifest.json` |
| MCP for Unity package (resolved) | same URL, git hash `d49ae2953580f3481beb1e084a1da2682f0b5610`, unpacked at `Library/PackageCache/com.coplaydev.unity-mcp@7b7db7b31f4e` | `Packages/packages-lock.json` and the PackageCache directory |
| MCP server (Python side) | `10.0.0` | `debug_request_context` → `data.server.version`, and `unity_mcp_server.log`: `MCP for Unity Server v10.0.0 starting up` |
| Latest version the package knows about | `10.1.2` | Unity EditorPrefs key `MCPForUnity.LatestKnownVersion_h141901539`, last checked `2026-08-06` |

So the installed package really is v10.0.0 on both halves (Unity plugin and Python
server), and the package's own update check believes 10.1.2 is current. `manage_packages`
could not confirm this from inside Unity — see below — so the version numbers above are
read from project files and from the server's self-report, not from the editor.

Transport is HTTP. The server was launched by the Unity editor itself with:

```
mcp-for-unity --transport http --http-url http://127.0.0.1:8080 --project-scoped-tools
  --pidfile <project>/Library/MCPForUnity/RunState/mcp_http_8080.pid
  --unity-instance-token 67844e9ddd274505b776072d406d253b
```

## The failure

Every tool or resource that has to reach into the editor returns, verbatim:

```json
{"success":false,"message":null,"error":"Unity session not available; please retry","data":{"reason":"no_unity_session","retry_after_ms":250},"hint":"retry"}
```

Each such call blocks for about 20 seconds first. The server log explains why:

```
2026-08-06 12:16:12,313 - transport.plugin_hub - WARNING - No Unity plugin reconnected within 20.00s (instance=default)
```

The `retry_after_ms: 250` and `hint: "retry"` in the payload are misleading. They suggest a
transient hiccup you should retry in a quarter second. The real condition is that no Unity
plugin is attached to the hub at all, and no amount of retrying from the client side will
change that — the plugin has to dial in from the editor.

### Calls made, in order

Only the calls against this backend are listed; the diagnostics that follow were plain
file/process reads.

1. `manage_packages(action="get_package_info", package="com.coplaydev.unity-mcp")` → `no_unity_session`
2. resource `mcpforunity://instances` → `{"success": true, "transport": "http", "instance_count": 0, "instances": []}`
3. resource `mcpforunity://editor/state` → `no_unity_session`
4. resource `mcpforunity://project/info` → `{"success":false,"message":null,"error":"Unity session not available; please retry","data":null,"hint":null}` (note: this one omits the `retry_after_ms` payload the others carry)
5. resource `mcpforunity://editor/state` (retry) → `no_unity_session`
6. resource `mcpforunity://instances` (retry) → still `instance_count: 0`
7. `manage_scene(action="get_active")` → `no_unity_session`
8. `debug_request_context()` → **succeeded** (see below)
9. `find_gameobjects(search_term="T004-Root-C", search_method="by_name")` → `no_unity_session`
10. `manage_gameobject(action="create", name="T004-Root-C", position=[0,0,0])` → `no_unity_session`
11. `manage_gameobject(action="create", name="T004-Child-C", parent="T004-Root-C", position=[1,2,3], components_to_add=["BoxCollider"], component_properties={"BoxCollider": {"size": [2,2,2]}})` → `no_unity_session`
12. `manage_tools(action="list_groups")` → **succeeded**

Step count: 12 calls against this backend, of which 2 succeeded. Both successes
(`debug_request_context`, `manage_tools list_groups`) are answered entirely by the Python
server and never touch Unity. Every one of the other 10 failed identically. Around those,
roughly 20 further steps went into file, log, process, port and registry inspection to
work out what was broken.

`debug_request_context` is the single most useful call when this happens. It returns:

```json
"session_state": {
  "derived_key": "global",
  "active_instance": null,
  "all_keys_in_store": [],
  "plugin_hub_configured": true,
  "middleware_id": 2338760027040
}
```

`plugin_hub_configured: true` with `active_instance: null` and an empty instance store is
the signature: the routing layer exists and is wired up, but nothing has registered on the
Unity side.

`manage_tools(action="list_groups")` also answers without Unity, and confirms the default
group layout: `core` is enabled (25 tools including `manage_gameobject`, `manage_components`,
`find_gameobjects`, `manage_scene`); `animation`, `asset_gen`, `docs`, `probuilder`,
`profiling`, `scripting_ext`, `testing`, `ui`, `vfx` are all disabled by default. So the
tools needed here were in the enabled set — group visibility was not the problem.

## Diagnosis

The Unity editor for this project was running the whole time (`Unity.exe -projectpath
<project>`, started 10:02, human-controlled: `IsHumanControllingUs: 1`). The editor's own
log shows the package loaded and shows it managing the server process:

```
MCP-FOR-UNITY: [StartupConfigRewrite] refreshed 3 client config(s).
MCP-FOR-UNITY: Starting local HTTP server… (first run may take a minute while dependencies install)
MCP-FOR-UNITY: Stopped local HTTP server on port 8080 (PID: 14388)
MCP-FOR-UNITY: Starting local HTTP server… (first run may take a minute while dependencies install)
```

and nothing after that. There is no "connected", "registered" or "reconnecting" line, and
no error either. The plugin starts the server and then never registers with it, silently.

Corroborating evidence, all from outside the MCP stack:

- Nothing listens on the classic bridge port range 6400–6600.
- Port 8080 is listened on by the Python server (PID 26432). The only established
  connection to it is from the MCP client. The Unity editor process has **no** connection
  to 8080 — checked repeatedly, including a continuous 150-second poll.
- Port 8080 has dozens of sockets in `TIME_WAIT` — the retry traffic, all of it from the
  client side.
- The last successful plugin registration in `%LOCALAPPDATA%\UnityMCP\Logs\unity_mcp_server.log`
  is dated **2026-07-29**:
  ```
  2026-07-29 16:15:53,229 - transport.plugin_hub - INFO - Plugin registered: third-person-multiplayer (7d19c2af08626c21)
  2026-07-29 16:15:56,293 - transport.plugin_hub - INFO - Registered 34 tools for session ed985b92-2a5a-43ef-a781-144f33b40829
  2026-07-29 16:16:20,467 - transport.plugin_hub - INFO - Plugin session ed985b92-2a5a-43ef-a781-144f33b40829 disconnected (1005)
  ```
  Server sessions on 2026-08-03, 08-04 and 08-06 each log `No Unity instances found on
  startup` and never see a plugin. The stale session id from that July run is still sitting
  in EditorPrefs as `MCPForUnity.SessionId_7d19c2af08626c21_h2615286538 =
  ed985b92-2a5a-43ef-a781-144f33b40829`, which is a plausible thing to look at if you are
  chasing this: the editor may be holding a session identity that the current server has
  never heard of.

Relevant EditorPrefs, for anyone comparing setups: `MCPForUnity.UseHttpTransport = 1`,
`MCPForUnity.HttpTransportScope = local`, `MCPForUnity.HttpServerLaunchConfirmed = 1`,
`MCPForUnity.SetupCompleted = 1`, `MCPForUnity.DebugLogs = 0`. Note that last one — debug
logging is off, which is why the plugin's connection attempts (or lack of them) produce no
editor console output. If you hit this, turn `DebugLogs` on first; it is the difference
between a silent failure and a diagnosable one.

The only known ways to recover are on the Unity side: open the MCP for Unity editor window
and reconnect, force a domain reload, or restart the editor. All of those were out of scope
here, so the arm ends blocked.

## Friction and surprises

- **The error text points the wrong way.** `"please retry"` plus `retry_after_ms: 250`
  reads as backpressure. It is actually a permanent condition until someone intervenes in
  the editor GUI. A client that trusts the hint will spin forever; the `TIME_WAIT` pileup on
  port 8080 is what that looks like.
- **Twenty seconds per failed call.** The hub waits a full 20s for a plugin to appear before
  giving up, so probing costs real time. Ten failed calls is over three minutes of pure
  blocking.
- **The failure is asymmetric and undocumented in the response.** Server-only tools succeed
  normally, so the server "looks" healthy from the client. Nothing in a successful
  `manage_tools` response hints that no editor is attached. `debug_request_context` is the
  only call that tells you the truth, and it is not an obvious place to look.
- **`mcpforunity://project/info` returns a differently-shaped error** from every other
  endpoint — `"data": null, "hint": null` instead of the retry payload. Inconsistent error
  envelopes across resources make client-side handling harder than it needs to be.
- **The editor is silent about it.** The package logs that it started the server, then never
  logs another word about the connection it failed to make. With `DebugLogs = 0` (the
  default) there is no console error, no warning, nothing. An editor that has silently
  stopped being reachable looks exactly like an editor that is fine.
- **Editor liveness is not plugin liveness.** The editor was open, human-controlled, and
  had this exact project loaded for over two hours. None of that implies the MCP plugin is
  attached. If you are automating against this backend, check
  `mcpforunity://instances` for a non-zero `instance_count` before you assume anything.

## The three open questions

**1. Does this backend require the serialized name `m_Size` rather than the public `size`
when setting a BoxCollider's size?**

Unanswered — could not be tested. The call that would have tested it,
`manage_gameobject(action="create", ..., component_properties={"BoxCollider": {"size": [2,2,2]}})`,
using the public API name `size`, returned `no_unity_session` without ever reaching Unity.
The request never got as far as property resolution, so nothing was learned about which
name form the resolver accepts. I have no observation to offer here, and no basis to
confirm or contradict any prior claim.

**2. Do mutating calls echo the resulting state, or only identity?**

Unanswered — no mutating call ever executed. Both `manage_gameobject(action="create")`
attempts failed at the transport layer and returned only the error envelope: no identity
fields, no state, no partial result. Nothing was created, so there was nothing to echo.

**3. Does `instanceId` collide across distinct objects here?**

Unanswered. No object was created and no object was read, so no `instanceId` values were
returned at any point in this run. There is no pair of ids to compare.

All three questions remain open for this backend at v10.0.0 on Unity 6000.5.5f1. The
blocker is connectivity, not behaviour, and it sits entirely on the Unity plugin side.

## Read-back

There is none. No object was created, and no read-back was possible — the only search
attempted, `find_gameobjects(search_term="T004-Root-C", search_method="by_name")`, failed
with `no_unity_session` like everything else. The scene state is unknown to this backend
and was left untouched. Nothing was saved, nothing was deleted, and the editor was not
opened, closed or restarted.
