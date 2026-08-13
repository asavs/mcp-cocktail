#!/usr/bin/env bash
#
# Bring all three arms up at once, so a trial can compare them in one session.
#
#   A  the `unity` CLI                      — works from any shell, nothing to start
#   B  the official MCP (com.unity.pipeline) — starts with the Editor, port 7800
#   C  CoplayDev (com.coplaydev.unity-mcp)   — needs its server started, port 8080
#
# Arm C is the only one that needs setup, and it is *not* GUI-gated despite what the
# record said until 2026-08-06. Unity-side it is an HTTP client; the listener on 8080 is a
# separate python.exe spawned via uvx. Two EditorPrefs-and-a-call start it, both public and
# both reachable through `eval`.
#
# The gate that IS real is on the client, not the arm: Claude Code reads its MCP server list
# once, at session start. A server that was unreachable then stays absent for the whole
# session even after it comes up. So this script must run BEFORE the session that uses arm C,
# and that is the whole reason it exists as a separate step.
#
#   ./three-way-setup.sh          start arm C and verify all three
#   ./three-way-setup.sh --check  verify only, change nothing
#   ./three-way-setup.sh --stop   stop arm C's server and reset its EditorPrefs flag
#
# Every step verifies by effect — a bound port, a live HTTP response — never by an exit code
# or a "success": true. This toolchain returns both while having done nothing.

set -uo pipefail

# The Unity project to run the trial against. There is no sensible default -- this repo is
# the record, not a Unity project -- so it must be supplied.
PROJECT="${UNITY_TRIAL_PROJECT:-}"
if [ -z "$PROJECT" ]; then
  echo "UNITY_TRIAL_PROJECT is not set. Point it at the Unity project to run the trial in:" >&2
  echo "  UNITY_TRIAL_PROJECT=/c/path/to/your-unity-project ./three-way-setup.sh" >&2
  exit 2
fi
CLI_DIR="${UNITY_CLI_DIR:-$LOCALAPPDATA/Unity/bin}"
COPLAY_URL="http://127.0.0.1:8080"
MCP_NAME="UnityMCP"

export PATH="$PATH:$CLI_DIR"
# Git Bash rewrites any argument beginning with "/" into a Windows path. Unity hierarchy
# paths and menu paths both start with "/", so without this the CLI receives
# "C:/Program Files/Git/..." and fails on an argument you never typed.
export MSYS_NO_PATHCONV=1

MODE="start"
case "${1:-}" in
  --check) MODE="check" ;;
  --stop)  MODE="stop" ;;
  "")      ;;
  *) echo "usage: $0 [--check|--stop]" >&2; exit 2 ;;
esac

ok()   { printf '  ok    %s\n' "$*"; }
bad()  { printf '  FAIL  %s\n' "$*"; }
info() { printf '  ..    %s\n' "$*"; }
section() { printf '\n%s\n' "$*"; }

fail=0

# --- arm A + the Editor ------------------------------------------------------------------

section "Editor and arm A"

status="$(unity status --json 2>&1)"
if ! grep -q '"state"' <<<"$status"; then
  bad "no Editor is running. Open the project first:"
  echo "        unity open \"$PROJECT\" &"
  echo "      Then poll: unity status --json"
  echo "      Note \`unity open\` does not return when the Editor is ready — it was still"
  echo "      blocking at 3 minutes against a ~60s startup. Background it and poll."
  exit 1
fi

port="$(grep -oE '"port": *[0-9]+' <<<"$status" | head -1 | grep -oE '[0-9]+')"
proj="$(grep -oE '"project": *"[^"]*"' <<<"$status" | head -1 | sed 's/.*: *"//; s/"$//; s/\\\\/\\/g')"
ok "Editor up on port ${port:-?} — $proj"

tools="$(unity list 2>/dev/null | wc -l)"
if [ "${tools:-0}" -gt 100 ]; then
  ok "arm A reaches $tools Pipeline tools (arm B's catalogue, same stack)"
else
  bad "arm A sees only ${tools:-0} tools — Pipeline may not be serving"
  fail=1
fi

# --- arm C -------------------------------------------------------------------------------

section "Arm C (CoplayDev)"

coplay_up() {
  curl -s -o /dev/null -w '%{http_code}' --max-time 4 "$COPLAY_URL/mcp" 2>/dev/null
}

# Does any Editor actually have a session with that server?
#
# This is the check T-004 needed and did not have. The first version of this script called
# all three arms up because /mcp answered and `claude mcp list` said Connected. Both were
# true and both were irrelevant: the Editor starts C's server and does not dial into it, so
# every Editor-bound call blocked 20s and returned no_unity_session. A server answering
# proves a server. The states are *server running* -> *Editor registered*, and only the
# second one is the one you want. Do not collapse them again.
#
# Asks the server rather than the Editor, deliberately: the Editor can be internally wedged
# while still reporting a stale cached "connected".
coplay_registered() {
  local init sid body
  # -D - puts the response headers on stdout ahead of the body, so one capture gets both and
  # there is no temp file to go missing.
  init="$(curl -s -D - --max-time 10 -X POST "$COPLAY_URL/mcp" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"three-way-setup","version":"1"}}}' 2>/dev/null)"
  sid="$(tr -d '\r' <<<"$init" | grep -i '^mcp-session-id:' | sed 's/^[^:]*: *//' | head -1)"
  [ -z "$sid" ] && { echo ""; return 1; }
  body="$(curl -s --max-time 8 -X POST "$COPLAY_URL/mcp" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -H "Mcp-Session-Id: $sid" \
    -d '{"jsonrpc":"2.0","id":2,"method":"resources/read","params":{"uri":"mcpforunity://instances"}}' 2>/dev/null)"
  # The resource's payload is a JSON *string* containing JSON, so the inner quotes arrive
  # backslash-escaped: \"instance_count\": 0. Do not anchor on a literal quote character.
  grep -oE 'instance_count[^0-9]*[0-9]+' <<<"$body" | grep -oE '[0-9]+$' | head -1
}

# A bound port is necessary but not sufficient — check the JSON-RPC endpoint answers.
code="$(coplay_up)"
if [ "$code" != "000" ] && [ -n "$code" ]; then
  # Port 8080 is machine-wide, while projects are not. Reusing an answering
  # listener without proving its project can displace or drive an unrelated
  # Editor. Doctor performs the initialized, exact-project resource check.
  if (cd "$PROJECT" && mcp-cocktail doctor --require coplay-mcp >/dev/null 2>&1); then
    ok "server already answering for this exact project at $COPLAY_URL/mcp (HTTP $code)"
  else
    bad "port 8080 is already occupied but is not operational for $PROJECT"
    echo "        Refusing to reuse or replace a possibly unrelated project's bridge." >&2
    echo "        Run from the target project: mcp-cocktail doctor" >&2
    echo "        Deliberately stop/move the existing owner before retrying." >&2
    exit 3
  fi
else
  if [ "$MODE" = "check" ]; then
    bad "server not answering at $COPLAY_URL/mcp"
    fail=1
  elif [ "$MODE" = "start" ]; then
    info "starting server via eval (quiet:true skips the one confirmation dialog)"
    out="$(unity command eval --code 'UnityEditor.EditorPrefs.SetBool("MCPForUnity.UseHttpTransport", true); bool s = MCPForUnity.Editor.Services.MCPServiceLocator.Server.StartLocalHttpServer(true); return "started=" + s;' --json 2>&1)"
    if ! grep -q 'started=True' <<<"$out"; then
      bad "eval did not report a start; raw response follows"
      sed 's/^/        /' <<<"$out" | head -8
    fi
    # uvx may need to resolve the package on first run; poll rather than assume.
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
      code="$(coplay_up)"
      [ "$code" != "000" ] && [ -n "$code" ] && break
      sleep 2
    done
    if [ "$code" != "000" ] && [ -n "$code" ]; then
      ok "server answering at $COPLAY_URL/mcp (HTTP $code)"
    else
      bad "server did not come up. Check that uvx is on PATH: command -v uvx"
      fail=1
    fi
  fi
fi

if [ "$MODE" != "stop" ]; then
  inst="$(coplay_registered)"

  # Starting the server does not register the Editor with it -- that path never touches
  # Bridge/TransportManager. Nothing automated does it: AutoStartOnLoad does not (tested,
  # on a fresh Editor start with the pref set), and ResumeHttpAfterReload only fires if the
  # bridge was already running. The only other route is the Connect button in the MCP window.
  #
  # Bridge.StartAsync() does it, and is safe **only fire-and-forget**. Blocking on it with
  # .GetAwaiter().GetResult() deadlocks the Editor permanently -- it awaits without
  # ConfigureAwait(false) and eval runs on the main thread, so the continuation waits for the
  # thread that is blocked. Task.Run does not help. Discard the task; do not await it.
  if { [ -z "$inst" ] || [ "$inst" -eq 0 ] 2>/dev/null; } && [ "$MODE" = "start" ]; then
    info "no Editor registered — dispatching Bridge.StartAsync (fire-and-forget)"
    unity command eval --code 'var _ = MCPForUnity.Editor.Services.MCPServiceLocator.Bridge.StartAsync(); return "dispatched";' --json >/dev/null 2>&1
    for _ in 1 2 3 4 5 6 7 8; do
      inst="$(coplay_registered)"
      [ -n "$inst" ] && [ "$inst" -gt 0 ] 2>/dev/null && break
      sleep 3
    done
  fi

  if [ -n "$inst" ] && [ "$inst" -gt 0 ] 2>/dev/null; then
    ok "an Editor is registered with arm C's server (instance_count=$inst)"
  else
    bad "arm C's server is up, but NO Editor is registered with it (instance_count=${inst:-unknown})"
    echo "        Every Editor-bound arm-C call will block ~20s and return no_unity_session."
    echo "        This is silent by default: DebugLogs is 0."
    echo
    echo "        Registration is performed by the Connect button in"
    echo "        Window/MCP for Unity, or automatically when MCPForUnity.AutoStartOnLoad"
    echo "        is set BEFORE the Editor loads. Nothing else sets it — starting the"
    echo "        server does not, because that path never touches Bridge/TransportManager."
    echo
    if [ "$MODE" = "start" ]; then
      echo "        Bridge.StartAsync() was already dispatched above, fire-and-forget, and"
      echo "        registration still did not appear. Use the Connect button."
    else
      echo "        Re-run in start mode to dispatch Bridge.StartAsync(), or use the button."
    fi
    echo "        Either way, never *block* on that task — .GetAwaiter().GetResult() and"
    echo "        any await deadlock the Editor permanently: eval runs on the main thread"
    echo "        and StartAsync awaits without ConfigureAwait(false), so the continuation"
    echo "        waits for the thread that is blocked. Task.Run does not help. Recovery"
    echo "        is killing the process. Dispatch and discard, as above."
    fail=1
  fi
fi

if [ "$MODE" = "stop" ]; then
  info "stopping server and resetting the EditorPrefs flag"
  unity command eval --code 'MCPForUnity.Editor.Services.MCPServiceLocator.Server.StopLocalHttpServer(); UnityEditor.EditorPrefs.SetBool("MCPForUnity.UseHttpTransport", false); return "stopped";' --json >/dev/null 2>&1
  code="$(coplay_up)"
  if [ "$code" = "000" ] || [ -z "$code" ]; then
    ok "server stopped, flag reset"
  else
    bad "still answering on $COPLAY_URL/mcp"
    fail=1
  fi
  exit $fail
fi

# --- the client-side gate ----------------------------------------------------------------

section "Claude Code registration"

reg="$(claude mcp list 2>&1)"
if grep -qi "^$MCP_NAME:" <<<"$reg"; then
  line="$(grep -i "^$MCP_NAME:" <<<"$reg")"
  if grep -qi "Connected" <<<"$line"; then
    # "Connected" here proves the client reached the server's socket. It does not prove the
    # server can reach an Editor, and it stays green when it cannot -- see the registration
    # check above, which is the one that matters.
    ok "$MCP_NAME reachable from this client (proves the socket, not the Editor session)"
  else
    bad "$MCP_NAME registered but not connected:"
    printf '        %s\n' "$line"
    fail=1
  fi
else
  bad "$MCP_NAME is not registered. Add it, then start a NEW session:"
  echo "        claude mcp add --transport http $MCP_NAME $COPLAY_URL/mcp"
  fail=1
fi

section "Result"
if [ "$fail" -eq 0 ]; then
  cat <<'EOF'
  All three arms are up.

  Arm C's tools will NOT appear in a session that was already running when its server was
  down — Claude Code reads the server list once, at session start. Start a fresh session
  from this directory and the mcp__UnityMCP__* tools will be present alongside
  mcp__unity-editor-mcp__* (arm B) and the CLI (arm A).

  Run the arms SERIALLY. One Editor serves all three, so concurrent arms are several agents
  mutating one scene rather than several trials.

  The trial brief to hand that session is in tools/trials/arm-brief.md — it carries the task,
  the per-arm constraints, and the traps that would otherwise be rediscovered.
EOF
else
  echo "  Not ready — see the failures above."
fi
exit $fail
