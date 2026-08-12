"""Tests for mcp_cocktail.doctor module."""

import contextlib
import json
import shutil
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

from mcp_cocktail.config import CocktailConfig, ArmConfig
from mcp_cocktail.doctor import (
    MAX_REPORTED_FIELDS,
    LIVENESS_PATH,
    NO_ROUTE_MARKER,
    READY_STATUSES,
    ArmHealthResult,
    acquisition_note,
    append_note,
    evaluate_requirements,
    print_doctor_report,
    check_arm_binding,
    describe_binding,
    describe_instance,
    extract_json_path,
    first_command_token,
    doctor_check_arm,
    run_doctor,
    probe_cli_arm,
    probe_mcp_arm,
    probe_mcp_target,
    resolve_probe_binary,
    shared_probe_binaries,
    summarize_failure,
    _decode_jsonrpc_body,
)
from mcp_cocktail.installer import PRESETS_DIR


def test_probe_cli_arm_offline():
    arm = ArmConfig(id="nonexistent-cli", name="Fake CLI", type="cli", command="nonexistent_binary_xyz_123")
    res = probe_cli_arm(arm)
    assert res.status == "OFFLINE"


def test_stdio_mcp_probe_is_bounded_and_reaps_hung_process():
    proc = MagicMock()
    proc.stdin.closed = False
    proc.stdout.readline.side_effect = lambda: threading.Event().wait(30)
    proc.poll.return_value = None

    arm = ArmConfig(id="hung", name="Hung", type="mcp", mcp_server="hung-mcp")
    with patch("mcp_cocktail.doctor.shutil.which", return_value="C:/hung.exe"), \
            patch("mcp_cocktail.doctor.subprocess.Popen", return_value=proc):
        result = probe_mcp_arm(arm)

    assert result.status == "DEGRADED"
    assert result.details["timeout"] is True
    proc.terminate.assert_called_once()
    proc.wait.assert_called()


def test_sse_decoder_ignores_progress_notifications_before_matching_response():
    body = "\n".join([
        'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{"progress":1}}',
        "",
        'data: {"jsonrpc":"2.0","id":2,"result":{"content":[]}}',
        "",
    ])

    assert _decode_jsonrpc_body(body, expected_id=2)["id"] == 2
    assert _decode_jsonrpc_body(body, expected_id=99) is None


def test_target_probe_rejects_success_envelope_containing_known_failure_signal():
    replies = [
        ({"jsonrpc": "2.0", "id": 1, "result": {}}, "session", ""),
        ({
            "jsonrpc": "2.0", "id": 2,
            "result": {"content": [{"type": "text", "text": "no_unity_session"}]},
        }, "session", ""),
    ]
    spec = {
        "kind": "mcp_tool", "name": "read_console", "arguments": {},
        "reject_match": "no[_ -]?unity[_ -]?session",
    }

    with patch("mcp_cocktail.doctor._post_mcp_jsonrpc", side_effect=replies), \
            patch("mcp_cocktail.doctor.urllib.request.urlopen"):
        operational, detail, _ = probe_mcp_target("http://localhost/mcp", spec)

    assert operational is False
    assert "failure signal" in detail


def test_target_probe_requires_identity_resource_to_name_workspace(tmp_path):
    replies = [
        ({"jsonrpc": "2.0", "id": 1, "result": {}}, "session", ""),
        ({"jsonrpc": "2.0", "id": 2, "result": {
            "contents": [{"text": '{"data":{"projectRoot":"C:/elsewhere"}}'}]
        }}, "session", ""),
    ]
    spec = {
        "kind": "mcp_tool", "name": "read_console", "arguments": {},
        "identity_resource": "mcpforunity://project/info",
    }

    with patch("mcp_cocktail.doctor._post_mcp_jsonrpc", side_effect=replies), \
            patch("mcp_cocktail.doctor.urllib.request.urlopen"):
        operational, detail, _ = probe_mcp_target(
            "http://localhost/mcp", spec, tmp_path
        )

    assert operational is False
    assert "did not name this workspace" in detail


def test_target_probe_accepts_exact_nested_project_root(tmp_path):
    project_info = json.dumps({"data": {"projectRoot": str(tmp_path)}})
    replies = [
        ({"jsonrpc": "2.0", "id": 1, "result": {}}, "session", ""),
        ({"jsonrpc": "2.0", "id": 2, "result": {
            "contents": [{"text": project_info}]
        }}, "session", ""),
        ({"jsonrpc": "2.0", "id": 3, "result": {"content": []}}, "session", ""),
    ]
    spec = {
        "kind": "mcp_tool", "name": "read_console", "arguments": {},
        "identity_resource": "mcpforunity://project/info",
    }

    with patch("mcp_cocktail.doctor._post_mcp_jsonrpc", side_effect=replies), \
            patch("mcp_cocktail.doctor.urllib.request.urlopen"):
        operational, _, _ = probe_mcp_target(
            "http://localhost/mcp", spec, tmp_path
        )

    assert operational is True


def test_target_probe_uses_one_end_to_end_deadline(tmp_path):
    project_info = json.dumps({"data": {"projectRoot": str(tmp_path)}})
    replies = [
        ({"jsonrpc": "2.0", "id": 1, "result": {}}, "session", ""),
        ({"jsonrpc": "2.0", "id": 2, "result": {"contents": [{"text": project_info}]}}, "session", ""),
        ({"jsonrpc": "2.0", "id": 3, "result": {"content": []}}, "session", ""),
    ]
    seen_timeouts = []

    def post(_url, _payload, timeout, _session=None):
        seen_timeouts.append(timeout)
        return replies.pop(0)

    spec = {
        "kind": "mcp_tool", "name": "read_console", "arguments": {},
        "identity_resource": "mcpforunity://project/info", "timeout_seconds": 5,
    }
    with patch("mcp_cocktail.doctor._post_mcp_jsonrpc", side_effect=post), \
            patch("mcp_cocktail.doctor.urllib.request.urlopen"), \
            patch("mcp_cocktail.doctor.time.monotonic", side_effect=[0, 0, 1, 2, 3]):
        operational, _, _ = probe_mcp_target("http://localhost/mcp", spec, tmp_path)

    assert operational is True
    assert seen_timeouts == [5, 3, 2]


def test_health_check_runs_even_when_the_precheck_cannot_find_the_binary():
    """The child shell, not this process, decides what its own PATH resolves.

    shutil.which() and `shell=True` are two different resolvers -- shims,
    .cmd shadowing, a profile that extends PATH for the shell only -- and the
    precheck was short-circuiting to OFFLINE for arms whose health check runs
    fine one line later. A shell builtin is the cleanest portable stand-in for
    "runs in the shell, absent from PATH".
    """
    arm = ArmConfig(id="builtin", name="Builtin", type="cli",
                    command="nonexistent_binary_xyz_123", health_check="exit 0",
                    health_check_layer="target_operation")
    assert shutil.which("nonexistent_binary_xyz_123") is None
    res = probe_cli_arm(arm)

    assert res.status == "OPERATIONAL", res.message


def test_probe_mcp_arm_offline():
    arm = ArmConfig(id="fake-mcp", name="Fake MCP", type="mcp", health_check="http://127.0.0.1:59999/health")
    res = probe_mcp_arm(arm)
    assert res.status == "OFFLINE"
    # Routed through the HTTP probe, not the PATH gate.
    assert "unreachable at http://127.0.0.1:59999/health" in res.message


def test_shell_wrapped_url_never_reaches_the_http_probe():
    """Why bare URLs are mandatory in presets.

    probe_mcp_arm dispatches on hc.startswith("http"), so a URL wrapped in a
    shell command silently falls through to the PATH gate and reports a
    misleading 'not found in PATH' instead of the real connection verdict.
    """
    wrapped = ArmConfig(id="wrapped", name="Wrapped", type="mcp", mcp_server="SomeRegistryKey",
                        health_check="curl -s http://127.0.0.1:59999/health")
    wrapped_res = probe_mcp_arm(wrapped)
    assert "unreachable at" not in wrapped_res.message
    assert wrapped_res.status != "SOCKET_BOUND_ONLY"

    bare = ArmConfig(id="bare", name="Bare", type="mcp", mcp_server="SomeRegistryKey",
                     health_check="http://127.0.0.1:59999/health")
    assert "unreachable at" in probe_mcp_arm(bare).message


def test_failed_health_check_reports_not_running_not_ready():
    """A health check that runs and fails must not fall through to
    'executable found in PATH'. It is also not OFFLINE: the tool is installed
    and answered, and said its backend is down. Start the backend vs install
    the tool are different instructions to the operator."""
    arm = ArmConfig(id="failing", name="Failing", type="cli",
                    health_check="python -c \"import sys; sys.exit(3)\"")
    res = probe_cli_arm(arm)
    assert res.status == "NOT_RUNNING"
    assert res.status not in READY_STATUSES
    assert "exit 3" in res.message


def test_missing_binary_stays_offline():
    """The discriminator: both resolvers agree nothing is there, so we have no
    evidence the tool is even installed. The precheck stopped being a veto, but
    it is still evidence -- when the health check also fails, the missing binary
    and the check's own verdict are reported together."""
    arm = ArmConfig(id="absent", name="Absent", type="cli",
                    command="nonexistent_binary_xyz_123",
                    health_check="nonexistent_binary_xyz_123 --version")
    res = probe_cli_arm(arm)

    assert res.status == "OFFLINE"
    assert "not found in PATH" in res.message


def test_offline_arm_with_no_route_says_so_instead_of_looking_broken():
    """A preset is a survey and nobody has all eleven arms, so most OFFLINE
    lines are arms the reader was never expected to have. Bare OFFLINE makes
    them indistinguishable from a broken install, and a wall of failures is a
    report nobody reads to the end."""
    survey = ArmConfig(id="unowned", name="Unowned", type="cli", command="nonexistent_binary_xyz_123")
    res = doctor_check_arm(survey)

    assert res.status == "OFFLINE"
    assert NO_ROUTE_MARKER in res.message
    # The marker earns its place by being short: spelling the explanation out
    # per arm put three lines of prose on eight rows of a real report.
    assert len(res.message) < 200


def test_note_joins_onto_a_message_without_doubling_its_punctuation():
    """summarize_failure truncates mid-clause, so probe messages end on a
    comma about as often as a full stop -- and one already ending in '.' must
    not acquire a second one."""
    assert append_note("Server unreachable (timed out).", "(x)") == "Server unreachable (timed out). (x)"
    assert append_note("not recognized as a command,", "(x)") == "not recognized as a command. (x)"
    assert append_note("plain", "") == "plain"
    assert append_note("", "(x)") == "(x)"


def test_offline_arm_with_an_install_hint_reports_it():
    arm = ArmConfig(id="gettable", name="Gettable", type="cli",
                    command="nonexistent_binary_xyz_123",
                    install_hint="brew install gettable")
    res = doctor_check_arm(arm)

    assert res.status == "OFFLINE"
    assert "Install: brew install gettable" in res.message
    assert NO_ROUTE_MARKER not in res.message


def test_arms_with_a_setup_script_are_not_called_survey_entries(tmp_path: Path):
    """A declared setup_script is an acquisition route. The existing
    UNCONFIGURED message already covers the case where it is missing."""
    arm = ArmConfig(id="startable", name="Startable", type="cli",
                    command="nonexistent_binary_xyz_123",
                    setup_script="tools/start.sh")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "start.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    res = doctor_check_arm(arm, tmp_path)
    assert NO_ROUTE_MARKER not in res.message


def test_shipped_preset_gives_every_arm_a_route_or_admits_it_has_none():
    """Guards the gap this field report named: arms listed with no installer.

    Deliberately not "every arm must have a hint" -- an unverified install
    command shipped in a preset is worse than an honest silence. What must
    hold is that the report never leaves the reader guessing which case
    they are in.
    """
    config = CocktailConfig.load(PRESETS_DIR / "unity" / "manifest.json")
    assert config.arms, "preset resolved no arms"

    for arm in config.arms:
        note = acquisition_note(arm)
        assert ("Install:" in note) or (NO_ROUTE_MARKER in note) or arm.setup_script, \
            f"{arm.id} offers the reader no way to tell which case it is in"


def test_the_no_route_marker_is_explained_once_not_per_row(capsys):
    """The first cut of this feature restated its own three-line explanation
    on every marked row, which reproduced the wall of noise it was written to
    remove. The rows carry a marker; the summary explains it."""
    config = CocktailConfig.load(PRESETS_DIR / "unity" / "manifest.json")
    routeless = [
        ArmConfig(id=f"bare{i}", name=f"Bare {i}", type="cli", command="nope")
        for i in range(3)
    ]
    results = [
        ArmHealthResult(a.id, a.name, "OFFLINE", append_note("down", acquisition_note(a)), {})
        for a in routeless
    ]
    print_doctor_report(results, config)

    out = capsys.readouterr().out
    assert out.count("declare neither a setup_script nor an") == 1

    marked_rows = [ln for ln in out.splitlines() if ln.startswith("bare") and NO_ROUTE_MARKER in ln]
    assert len(marked_rows) == 3, "rows should still be individually marked"


def test_report_columns_stay_aligned_for_long_arm_names(capsys):
    """Real preset names run to 43 characters against a hardcoded width of
    24, so every long row shoved the status and diagnostic columns out of
    register and the table stopped being scannable."""
    config = CocktailConfig.load(PRESETS_DIR / "unity" / "manifest.json")
    results = [
        ArmHealthResult("short", "Short", "READY", "fine", {}),
        ArmHealthResult("a-much-longer-arm-id", "game4automation RealVirtual Digital Twin MCP",
                        "OFFLINE", "down", {}),
    ]
    print_doctor_report(results, config)

    rows = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith(("short ", "a-much-longer"))]
    assert len(rows) == 2
    assert len({row.index("[") for row in rows}) == 1, "status column is ragged"


def test_unverified_arm_is_not_probed_at_all():
    """Probing an entry nobody could tie to a real project manufactures a
    precise-sounding failure about an endpoint that never existed --
    'unreachable at 127.0.0.1:9500' reads as a server that is down."""
    arm = ArmConfig(id="ghost", name="Ghost", type="mcp",
                    health_check="http://127.0.0.1:59998/mcp",
                    probe="unverified",
                    probe_reason="No such project exists on npm or GitHub.")
    res = doctor_check_arm(arm)

    assert res.status == "UNCONFIGURED"
    assert "could not be tied to a real upstream project" in res.message
    assert "No such project exists" in res.message
    assert "unreachable" not in res.message, "it must not report on the invented endpoint"


def test_arm_with_no_automatable_check_says_so_rather_than_failing():
    arm = ArmConfig(id="ws-only", name="WebSocket only", type="mcp",
                    probe="none",
                    probe_reason="It serves WebSocket on 18711, not HTTP.")
    res = doctor_check_arm(arm)

    assert res.status == "UNCONFIGURED"
    assert "no automatable health check" in res.message
    assert "WebSocket on 18711" in res.message


def test_gui_arm_requires_external_check_without_claiming_ready_or_unconfigured():
    arm = ArmConfig(
        id="computer-use",
        name="Computer Use",
        type="gui",
        probe="none",
        probe_reason="The harness supplies computer use.",
        install_hint="Enable computer use in the harness.",
    )

    res = doctor_check_arm(arm)

    assert res.status == "EXTERNAL_CHECK_REQUIRED"
    assert res.status not in READY_STATUSES
    assert "agent harness" in res.message
    assert "visible operation" in res.message
    assert "The harness supplies computer use" in res.message


def test_doctor_report_labels_gui_arm_as_external_check(capsys):
    config = CocktailConfig(
        name="gui",
        description="",
        arms=[ArmConfig(id="computer-use", name="Computer Use", type="gui", probe="none")],
    )
    print_doctor_report(run_doctor(config), config)

    out = capsys.readouterr().out
    assert "[EXTERNAL CHECK]" in out
    assert "1 EXTERNAL_CHECK_REQUIRED" in out


def test_plain_http_health_endpoint_is_not_asked_to_speak_mcp():
    """Not every URL worth checking is an MCP endpoint. AnkleBreaker's Unity
    bridge exposes a liveness ping, and demanding a JSON-RPC handshake of it
    reported a healthy service as a P4 warning."""
    with local_server(b"pong") as url:
        arm = ArmConfig(id="bridge", name="Bridge", type="mcp", health_check=url, probe="http")
        res = probe_mcp_arm(arm)

    assert res.status == "TARGET_ONLY"
    assert "answered HTTP 200" in res.message


def test_two_arms_probing_one_binary_cannot_both_be_installed():
    """Three separate Unity CLI projects each install an executable named
    `unity-cli`. Every arm's row is individually correct and the set is a lie:
    whichever is on PATH answers for all of them, so all report READY. No
    per-arm check can see this, because the collision is a property of the set.
    """
    config = CocktailConfig(
        name="collide", description="",
        arms=[
            ArmConfig(id="a", name="A", type="cli", command="unity-cli", health_check="unity-cli --version"),
            ArmConfig(id="b", name="B", type="cli", command="unity-cli", health_check="unity-cli --version"),
            ArmConfig(id="c", name="C", type="cli", command="uloop", health_check="uloop --version"),
        ],
    )

    assert shared_probe_binaries(config) == {"unity-cli": ["a", "b"]}


def test_shipped_preset_declares_the_unity_cli_collision():
    """Guards the live case: akiojin, youngwoo and rage all install `unity-cli`."""
    config = CocktailConfig.load(PRESETS_DIR / "unity" / "manifest.json")
    shared = shared_probe_binaries(config)

    assert "unity-cli" in shared
    assert set(shared["unity-cli"]) == {"akiojin-cli", "youngwoo-cli", "rage-cli"}


def test_collision_is_reported_only_when_it_actually_inflates_the_count(capsys):
    config = CocktailConfig(
        name="collide", description="",
        arms=[
            ArmConfig(id="a", name="A", type="cli", command="unity-cli", health_check="unity-cli --version"),
            ArmConfig(id="b", name="B", type="cli", command="unity-cli", health_check="unity-cli --version"),
        ],
    )

    one_ready = [
        ArmHealthResult("a", "A", "READY", "ok", {}),
        ArmHealthResult("b", "B", "OFFLINE", "no", {}),
    ]
    print_doctor_report(one_ready, config)
    assert "P4 Warning" not in capsys.readouterr().out, "one READY arm is not a collision"

    both_ready = [
        ArmHealthResult("a", "A", "READY", "ok", {}),
        ArmHealthResult("b", "B", "READY", "ok", {}),
    ]
    print_doctor_report(both_ready, config)
    out = capsys.readouterr().out
    assert "P4 Warning" in out
    assert "unity-cli" in out


@contextlib.contextmanager
def ws_listener(behaviour: str):
    """A raw TCP listener standing in for a WebSocket server.

    `answer` replies 501 and closes, as a healthy websocket-sharp listener does
    for an unknown path. `hang` accepts and then never speaks, which is the
    documented Windows failure mode.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    stop = threading.Event()

    def serve():
        server.settimeout(0.5)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except (socket.timeout, OSError):
                continue
            with conn:
                try:
                    conn.recv(1024)
                    if behaviour == "answer":
                        conn.sendall(b"HTTP/1.1 501 Not Implemented\r\n\r\n")
                    else:
                        stop.wait(3)  # hold it open, saying nothing
                except OSError:
                    pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield server.getsockname()[1]
    finally:
        stop.set()
        server.close()
        thread.join(timeout=2)


def test_websocket_listener_answering_the_handshake_is_transport_only():
    with ws_listener("answer") as port:
        arm = ArmConfig(id="cg", name="CG", type="mcp",
                        health_check=f"ws://127.0.0.1:{port}", probe="websocket")
        res = probe_mcp_arm(arm)

    assert res.status == "TRANSPORT_ONLY"
    assert "501" in res.message


def test_websocket_listener_that_accepts_then_goes_silent_is_bound_only():
    """The failure this probe exists for. mcp-unity's known Windows state binds
    the port and accepts connections, then never answers -- the Editor reports
    healthy while every client hangs. A connect-only check calls that READY,
    which is precisely the P4 green light the tool is built to catch."""
    with ws_listener("hang") as port:
        arm = ArmConfig(id="cg", name="CG", type="mcp",
                        health_check=f"ws://127.0.0.1:{port}", probe="websocket")
        res = probe_mcp_arm(arm)

    assert res.status == "SOCKET_BOUND_ONLY"
    assert res.status not in READY_STATUSES
    assert "never answered" in res.message


def test_plain_web_server_squatting_on_the_port_is_not_ready():
    """A WebSocket-aware server answers an upgrade with 101 or a 4xx/5xx
    refusal, never a bare 200 -- that means an ordinary web server holds the
    port and ignored the Upgrade header. Calling it READY would repeat, on
    this transport, the 'HTTP 200 proves MCP' mistake."""
    with local_server(b"<html>hello</html>", content_type="text/html") as url:
        port = int(url.rsplit(":", 1)[1].split("/")[0])
        arm = ArmConfig(id="squatter", name="Squatter", type="mcp",
                        health_check=f"ws://127.0.0.1:{port}", probe="websocket")
        res = probe_mcp_arm(arm)

    assert res.status == "SOCKET_BOUND_ONLY"
    assert res.status not in READY_STATUSES
    assert "not a WebSocket endpoint" in res.message


def test_websocket_probe_on_a_closed_port_is_not_running():
    arm = ArmConfig(id="cg", name="CG", type="mcp",
                    health_check="ws://127.0.0.1:59997", probe="websocket")
    res = probe_mcp_arm(arm)

    # Whether a closed loopback port refuses or silently drops is platform- and
    # firewall-dependent, so both must land on the same verdict or the result
    # becomes a property of the machine running the test.
    assert res.status == "NOT_RUNNING", res.message
    assert "nothing" in res.message


def test_ws_url_is_never_mistaken_for_a_shell_command():
    """resolve_probe_binary treats any non-http health_check as a shell command,
    so an unguarded ws:// URL would be looked up on PATH as a binary."""
    arm = ArmConfig(id="cg", name="CG", type="mcp", mcp_server="mcp-unity",
                    health_check="ws://127.0.0.1:8090", probe="websocket")
    assert resolve_probe_binary(arm) == "mcp-unity"

    config = CocktailConfig(name="x", description="", arms=[arm])
    assert shared_probe_binaries(config) == {}


def _status_file(root: Path, name: str, port: int, project: str, age_s: float = 0.0, **extra):
    from datetime import datetime, timedelta, timezone
    stamp = (datetime.now(timezone.utc) - timedelta(seconds=age_s)).isoformat()
    payload = {"ws_port": port, "project_path": project, "last_heartbeat": stamp, "pid": 1234, **extra}
    (root / name).write_text(json.dumps(payload), encoding="utf-8")


def _discovering_arm(root: Path) -> ArmConfig:
    return ArmConfig(
        id="realvirtual-mcp", name="RealVirtual", type="mcp",
        health_check="ws://127.0.0.1:18711", probe="websocket",
        discovery={"status_glob": str(root / "unity-mcp-status-*.json"), "max_age_seconds": 30},
    )


def test_discovery_probes_the_port_the_editor_actually_took(tmp_path: Path):
    """The port walks 18711-18721 when busy, so a second Editor lands one
    along. A fixed probe reports dead for a project that is running fine."""
    with ws_listener("answer") as port:
        _status_file(tmp_path, "unity-mcp-status-aaa.json", port, str(tmp_path))
        res = probe_mcp_arm(_discovering_arm(tmp_path), workspace_root=tmp_path)

    assert res.status == "TRANSPORT_ONLY", res.message
    assert str(port) in res.message, "must report the discovered port, not the manifest's guess"


def test_discovery_flags_an_editor_serving_another_project(tmp_path: Path):
    """The status directory is ecosystem-wide, so a file found there is not
    automatically this workspace's. Bound is not bound-to-your-thing."""
    _status_file(tmp_path, "unity-mcp-status-bbb.json", 18712, r"C:\work\some-other-project")
    res = probe_mcp_arm(_discovering_arm(tmp_path), workspace_root=tmp_path)

    assert res.status == "BOUND_ELSEWHERE"
    assert "some-other-project" in res.message


def test_stale_status_files_are_ignored(tmp_path: Path):
    """The writer refreshes every few seconds; a stale file is a crashed
    Editor, not a live one."""
    _status_file(tmp_path, "unity-mcp-status-ccc.json", 18711, str(tmp_path), age_s=120)
    res = probe_mcp_arm(_discovering_arm(tmp_path), workspace_root=tmp_path)

    assert res.status == "NOT_RUNNING"
    assert "No Editor is publishing a status file" in res.message


def test_domain_reload_is_not_reported_as_a_failure(tmp_path: Path):
    """A reload takes the socket down for seconds by design. Calling that
    broken teaches the operator to ignore the row."""
    _status_file(tmp_path, "unity-mcp-status-ddd.json", 18711, str(tmp_path), reloading=True)
    res = probe_mcp_arm(_discovering_arm(tmp_path), workspace_root=tmp_path)

    assert res.status == "TRANSPORT_ONLY"
    assert "domain-reload" in res.message


def test_unreadable_status_file_does_not_crash_the_probe(tmp_path: Path):
    (tmp_path / "unity-mcp-status-eee.json").write_text("{half-written", encoding="utf-8")
    res = probe_mcp_arm(_discovering_arm(tmp_path), workspace_root=tmp_path)

    assert res.status == "NOT_RUNNING"


def test_realvirtual_arm_uses_the_verified_probe():
    config = CocktailConfig.load(PRESETS_DIR / "unity" / "manifest.json")
    arm = next(a for a in config.arms if a.id == "realvirtual-mcp")

    assert arm.probe == "websocket"
    assert arm.discovery.get("status_glob")
    # Probing /mcp registers a real session and bumps the Editor's connected
    # client count; the liveness path must stay distinct from it.
    assert LIVENESS_PATH != "/mcp"


def test_codergamester_arm_is_wired_up():
    config = CocktailConfig.load(PRESETS_DIR / "unity" / "manifest.json")
    arm = next(a for a in config.arms if a.id == "codergamester-mcp")

    assert arm.mcp_server == "mcp-unity"
    assert arm.health_check.startswith("ws://")
    assert arm.install["package_url"].endswith("mcp-unity.git")
    # The stale npm package resolves, so a plausible-looking npx command would
    # run April-2025 code against a 1.4.0 package. Warn, never emit it.
    assert "npx mcp-unity-server" not in json.dumps(arm.install).replace("Do NOT run `npx mcp-unity-server`", "")
    assert "stale" in arm.install["note"]


def test_evaluate_requirements():
    results = [
        ArmHealthResult("up", "Up", "READY", "fine", {}),
        ArmHealthResult("assumed", "Assumed", "ASSUMED_READY", "probably", {}),
        ArmHealthResult("down", "Down", "NOT_RUNNING", "start it", {}),
    ]

    assert evaluate_requirements(results, []) == ([], [])
    unmet, unknown = evaluate_requirements(results, ["up", "assumed"])
    assert [item.arm_id for item in unmet] == ["assumed"]
    assert unknown == []

    unmet, unknown = evaluate_requirements(results, ["up", "down"])
    assert [r.arm_id for r in unmet] == ["down"]
    assert unknown == []

    unmet, unknown = evaluate_requirements(results, ["typo-arm"])
    assert unmet == [] and unknown == ["typo-arm"]


def test_silent_success_still_counts_as_ready():
    arm = ArmConfig(id="quiet", name="Quiet", type="cli", health_check="python -c \"pass\"",
                    health_check_layer="target_operation")
    assert probe_cli_arm(arm).status == "OPERATIONAL"


def test_successful_generic_shell_check_is_transport_only_without_layer_declaration():
    arm = ArmConfig(id="echo", name="Echo", type="cli", health_check="echo ok")
    result = probe_cli_arm(arm)
    assert result.status == "TRANSPORT_ONLY"
    assert result.status not in READY_STATUSES


def test_probe_binary_comes_from_the_health_check_not_the_arm_identity():
    """Regression: official-unity-mcp declares health_check 'unity status --json'
    but has no `command`, so the probe resolved mcp_server='unity-editor-mcp' --
    a harness registry key -- and reported OFFLINE while the arm was serving
    140 tools."""
    mcp_arm = ArmConfig(id="official-unity-mcp", name="Official Unity MCP", type="mcp",
                        mcp_server="unity-editor-mcp", health_check="unity status --json")
    assert resolve_probe_binary(mcp_arm) == "unity"

    # An explicit command still wins when no shell health_check names a binary.
    no_hc = ArmConfig(id="some-cli", name="Some CLI", type="cli", command="unity-cli-rust")
    assert resolve_probe_binary(no_hc) == "unity-cli-rust"

    # A URL health_check names no binary; fall back to identity.
    http_arm = ArmConfig(id="coplay-mcp", name="Coplay", type="mcp", mcp_server="UnityMCP",
                         health_check="http://127.0.0.1:8080/mcp")
    assert resolve_probe_binary(http_arm) == "UnityMCP"


def test_failure_summary_reads_json_error_envelopes():
    """`unity status --json` with no Editor exits 6 and explains exactly what
    to do -- but the first line of its pretty-printed body is "{"."""
    unity_no_instances = json.dumps({
        "success": False,
        "data": {"count": 0, "instances": []},
        "errors": [{"code": "STATUS_NO_INSTANCES",
                    "message": "No Unity Editor instances found with the Pipeline package installed."}],
    }, indent=2)

    assert "No Unity Editor instances found" in summarize_failure(unity_no_instances, "")

    # Other common envelope shapes.
    assert summarize_failure(json.dumps({"error": "boom"}), "") == "boom"
    assert summarize_failure(json.dumps({"message": "nope"}), "") == "nope"

    # stderr wins when present; plain text still works; nothing degrades safely.
    assert summarize_failure("{...}", "real stderr line") == "real stderr line"
    assert summarize_failure("plain failure text", "") == "plain failure text"
    assert summarize_failure("", "") == "no output"
    assert summarize_failure("{\n}\n", "") == "no output"


def test_probe_binary_honours_quoted_paths():
    """Field log V2: whitespace splitting truncated
    `"C:\\Program Files\\Python313\\python.exe"` at the space and probed for
    `C:\\Program`, reporting OFFLINE with a misleading reason. On Windows a
    quoted absolute path is the norm, not an edge case."""
    assert first_command_token(r'"C:\Program Files\Python313\python.exe" -c "pass"') == \
        r"C:\Program Files\Python313\python.exe"
    assert first_command_token("'/usr/local/bin/my tool' --check") == "/usr/local/bin/my tool"

    # posix=False is load-bearing: posix=True would return C:Toolsunity.exe.
    assert first_command_token(r"C:\Tools\unity.exe --version") == r"C:\Tools\unity.exe"

    assert first_command_token("unity status --json") == "unity"
    # Unbalanced quotes must degrade, not raise.
    assert first_command_token('unity status --json "unterminated') == "unity"
    assert first_command_token("") == ""


def test_quoted_health_check_arm_probes_the_real_interpreter():
    arm = ArmConfig(id="quoted-hc", name="Quoted", type="cli", command="python",
                    health_check=f'"{sys.executable}" -c "pass"', health_check_layer="target_operation")
    res = probe_cli_arm(arm)
    assert res.status == "OPERATIONAL", res.message


@contextlib.contextmanager
def local_server(
    handler_body: bytes,
    content_type: str = "text/plain",
    status: int = 200,
    post_body: bytes | None = None,
    post_status: int | None = None,
):
    """Serve one canned response on an ephemeral port.

    GET and POST can differ, because for MCP's Streamable HTTP transport they
    genuinely do: POST carries the protocol and GET is only ever an event-stream
    request, which a compliant server refuses when the Accept header does not
    ask for one.
    """

    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: bytes, code: int):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send(handler_body, status)

        def do_POST(self):
            self._send(
                handler_body if post_body is None else post_body,
                status if post_status is None else post_status,
            )

        def log_message(self, *args):  # keep pytest output clean
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/mcp"
    finally:
        server.shutdown()
        server.server_close()


def test_http_200_from_a_non_mcp_server_is_not_ready():
    """Field log V4: a plain server returning 200 with the body
    'hello, I am not an MCP server' reported READY. The tool built to detect
    P4 green lights must not emit one."""
    with local_server(b"hello, I am not an MCP server") as url:
        arm = ArmConfig(id="impostor", name="Impostor", type="mcp", health_check=url)
        res = probe_mcp_arm(arm)

    assert res.status == "SOCKET_BOUND_ONLY"
    assert "did not complete an MCP handshake" in res.message


def test_http_200_from_a_real_jsonrpc_endpoint_is_transport_only():
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}).encode()
    with local_server(body, content_type="application/json") as url:
        arm = ArmConfig(id="genuine", name="Genuine", type="mcp", health_check=url)
        res = probe_mcp_arm(arm)

    assert res.status == "TRANSPORT_ONLY"


JSONRPC_OK = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}).encode()


def test_406_on_get_does_not_veto_a_server_that_speaks_mcp_on_post():
    """Rejecting a GET is what a *correct* Streamable HTTP MCP server does.

    Treating the GET status as the verdict reported BOUND_ONLY (P4) for
    coplay-mcp while a live Editor was registered against it -- the false
    negative twin of the impostor-server false positive. Only the POST
    handshake can settle it, so it has to be asked before any verdict.
    """
    with local_server(b"Not Acceptable", status=406, post_body=JSONRPC_OK, post_status=200) as url:
        arm = ArmConfig(id="coplay-mcp", name="Coplay", type="mcp", health_check=url)
        res = probe_mcp_arm(arm)

    assert res.status == "TRANSPORT_ONLY"
    assert "406" in res.message, "the GET status stays visible; it just stops being the verdict"


def test_mcp_target_check_is_required_to_earn_operational():
    with local_server(b"Not Acceptable", status=406, post_body=JSONRPC_OK, post_status=200) as url:
        arm = ArmConfig(
            id="coplay-mcp", name="Coplay", type="mcp", health_check=url,
            target_check={"kind": "mcp_tool", "name": "read_console", "arguments": {"count": "1"}},
        )
        with patch("mcp_cocktail.doctor.probe_mcp_target", return_value=(True, "read_console completed", {})):
            res = probe_mcp_arm(arm)
    assert res.status == "OPERATIONAL"
    assert "target are responsive" in res.message


def test_mcp_target_timeout_is_degraded_despite_transport_handshake():
    with local_server(b"Not Acceptable", status=406, post_body=JSONRPC_OK, post_status=200) as url:
        arm = ArmConfig(
            id="coplay-mcp", name="Coplay", type="mcp", health_check=url,
            target_check={"kind": "mcp_tool", "name": "read_console"},
        )
        with patch("mcp_cocktail.doctor.probe_mcp_target", return_value=(False, "timed out", {})):
            res = probe_mcp_arm(arm)
    assert res.status == "DEGRADED"
    assert "transport responds" in res.message


def test_fixed_mcp_port_serving_another_project_is_wrong_project_not_degraded(tmp_path: Path):
    with local_server(b"Not Acceptable", status=406, post_body=JSONRPC_OK, post_status=200) as url:
        arm = ArmConfig(
            id="coplay-mcp", name="Coplay", type="mcp", health_check=url,
            target_check={"kind": "mcp_tool", "name": "read_console"},
        )
        evidence = {"project_roots": [r"C:\UnityProjects\another"]}
        with patch(
            "mcp_cocktail.doctor.probe_mcp_target",
            return_value=(False, "identity mismatch", evidence),
        ):
            result = probe_mcp_arm(arm, tmp_path)

    assert result.status == "WRONG_PROJECT"
    assert "another Unity project" in result.message
    assert result.details["project_roots"] == [r"C:\UnityProjects\another"]


def test_406_with_no_handshake_is_still_bound_only():
    """The P4 verdict survives for a listener that really cannot serve MCP."""
    with local_server(b"Not Acceptable", status=406) as url:
        arm = ArmConfig(id="coplay-mcp", name="Coplay", type="mcp", health_check=url)
        res = probe_mcp_arm(arm)

    assert res.status == "SOCKET_BOUND_ONLY"
    assert "406" in res.message
    assert "did not complete an MCP handshake" in res.message


def test_401_names_the_credential_as_the_blocker():
    """An authenticated rejection is a different instruction to the operator
    than a listener that cannot speak the protocol at all."""
    with local_server(b"Unauthorized", status=401) as url:
        arm = ArmConfig(id="gated", name="Gated", type="mcp", health_check=url)
        res = probe_mcp_arm(arm)

    assert res.status == "SOCKET_BOUND_ONLY"
    assert "Session token or Editor registration required" in res.message


UNITY_STATUS = json.dumps({
    "success": True,
    "data": {"count": 1, "instances": [
        {"port": 7800, "project": r"C:\work\gabe", "version": "6000.5.5f1", "pid": 1416, "state": "ready"}
    ]},
})


def test_extract_json_path_maps_over_lists():
    payload = json.loads(UNITY_STATUS)
    assert extract_json_path(payload, "data.instances[].project") == [r"C:\work\gabe"]
    assert extract_json_path(payload, "data.instances[].port") == [7800]
    assert extract_json_path(payload, "data.nope[].project") == []


def test_binding_check_flags_an_arm_serving_another_project(tmp_path):
    """Field log Finding 3: the MCP arm was registered at user scope against
    HelloUnity while all work was in gabe, and every liveness check said
    'Connected'. Bound is not the same claim as bound to your thing."""
    arm = ArmConfig(id="unity", name="Unity", type="cli", command="unity",
                    health_check="unity status --json",
                    binding_path="data.instances[].project")

    elsewhere = check_arm_binding(arm, UNITY_STATUS, tmp_path / "other-project")
    assert elsewhere is not None
    assert elsewhere.status == "BOUND_ELSEWHERE"
    assert r"C:\work\gabe" in elsewhere.message

    # Correctly bound -> no complaint.
    assert check_arm_binding(arm, UNITY_STATUS, Path(r"C:\work\gabe")) is None

    # No binding_path declared, or unparseable output -> check does not apply.
    silent = ArmConfig(id="unity", name="Unity", type="cli", health_check="unity status --json")
    assert check_arm_binding(silent, UNITY_STATUS, tmp_path) is None
    assert check_arm_binding(arm, "not json", tmp_path) is None


def test_describe_binding_surfaces_the_live_facts_generically():
    """Finding 9's diagnostic half: Unity reassigns its pipeline port between
    Editor sessions (7801 then 7800), so the live value is worth reporting.
    The parent of binding_path is the instance object, so this reads whatever
    the tool reports about itself without naming any field in code."""
    arm = ArmConfig(id="unity", name="Unity", type="cli", command="unity",
                    health_check="unity status --json",
                    binding_path="data.instances[].project")

    described = describe_binding(arm, UNITY_STATUS, Path(r"C:\work\gabe"))
    assert described.startswith(r"serving C:\work\gabe")
    for fact in ("port=7800", "pid=1416", "version=6000.5.5f1", "state=ready"):
        assert fact in described
    assert "project=" not in described, "the leaf is already the subject"

    # Not applicable: wrong workspace, no binding_path, unparseable output.
    assert describe_binding(arm, UNITY_STATUS, Path(r"C:\work\other")) == ""
    assert describe_binding(ArmConfig(id="x", name="x", type="cli"), UNITY_STATUS, Path("/w")) == ""
    assert describe_binding(arm, "not json", Path(r"C:\work\gabe")) == ""


def test_wrong_project_message_carries_the_instance_facts():
    arm = ArmConfig(id="unity", name="Unity", type="cli", command="unity",
                    health_check="unity status --json",
                    binding_path="data.instances[].project")

    res = check_arm_binding(arm, UNITY_STATUS, Path(r"C:\work\elsewhere"))
    assert res is not None
    assert "port=7800" in res.message


def test_describe_instance_skips_structure_and_caps_width():
    instance = {"project": "p", "port": 1, "nested": {"a": 1}, "list": [1], "flag": True,
                "long": "x" * 200, **{f"k{i}": i for i in range(10)}}
    rendered = describe_instance(instance, "project")

    assert "nested=" not in rendered and "list=" not in rendered and "flag=" not in rendered
    assert "x" * 41 not in rendered
    assert len(rendered.split(", ")) <= MAX_REPORTED_FIELDS


def test_unity_preset_declares_a_binding_for_project_scoped_arms():
    arms = {a.id: a for a in CocktailConfig.load(PRESETS_DIR / "unity" / "manifest.json").arms}
    for arm_id in ("official-unity-cli", "official-unity-mcp"):
        assert arms[arm_id].binding_path == "data.instances[].project"
    assert arms["coplay-mcp"].target_check["name"] == "read_console"


def test_unreachable_arm_with_a_missing_setup_script_is_unconfigured(tmp_path):
    """Field log Finding 8: coplay-mcp is a standalone server nothing in the
    stack starts, and its setup_script path did not resolve -- but the PATH
    gate short-circuited before setup_script was ever looked at, so the
    documented UNCONFIGURED status was unreachable for the arm it describes."""
    arm = ArmConfig(id="coplay-mcp", name="Coplay", type="mcp", mcp_server="UnityMCP",
                    health_check="http://127.0.0.1:59999/mcp",
                    setup_script="tools/three-way-setup.sh")

    res = doctor_check_arm(arm, workspace_root=tmp_path)
    assert res.status == "UNCONFIGURED"
    assert "cannot be started" in res.message

    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "three-way-setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    assert doctor_check_arm(arm, workspace_root=tmp_path).status == "OFFLINE"


def test_preset_setup_script_resolves_after_setup():
    """setup copies <preset>/tools -> <workspace>/tools, so a setup_script
    declared as tools/... must exist at that path inside the preset."""
    preset_root = PRESETS_DIR / "unity"
    for arm in CocktailConfig.load(preset_root / "manifest.json").arms:
        if arm.setup_script:
            assert (preset_root / arm.setup_script).exists(), (
                f"{arm.id}: setup_script '{arm.setup_script}' not present in the preset"
            )


def test_shipped_presets_state_urls_bare():
    """Regression: every arm in the Unity preset wrapped its URL in `curl -s`,
    so 11/11 arms took probe_cli_arm and the HTTP + stdio branches were dead
    code. SOCKET_BOUND_ONLY (P4) was unreachable."""
    manifests = sorted(PRESETS_DIR.glob("*/manifest.json"))
    assert manifests, "expected at least one shipped preset"

    for manifest in manifests:
        for arm in CocktailConfig.load(manifest).arms:
            hc = (arm.health_check or "").strip()
            if "http://" in hc or "https://" in hc:
                assert hc.startswith(("http://", "https://")), (
                    f"{manifest.parent.parent.name}/{arm.id}: health_check wraps a URL in a shell "
                    f"command ({hc!r}); doctor will take the PATH gate instead of the HTTP probe"
                )


def test_run_doctor():
    cfg = CocktailConfig(
        name="doctor-test",
        description="Doctor testing",
        arms=[
            ArmConfig(id="python-cli", name="Python CLI", type="cli", command="python"),
            ArmConfig(id="fake-mcp", name="Fake MCP", type="mcp", health_check="http://127.0.0.1:59999/health"),
        ],
    )

    results = run_doctor(cfg)
    assert len(results) == 2
    assert results[0].status == "INSTALLED_ONLY"
    assert results[1].status == "OFFLINE"


# --- Regressions from the 2026-08-12 usability run -------------------------

def test_version_flag_does_not_earn_ready():
    """Field run: hatayama-loop reported READY because `uloop --version`
    answered, and its first real Unity call failed -- the project-side package
    had never been installed. A version probe is evidence of installation and
    nothing more."""
    arm = ArmConfig(id="versiony", name="Versiony", type="cli",
                    command="python", health_check="python --version")
    res = probe_cli_arm(arm)

    assert res.status == "INSTALLED_ONLY"
    assert res.status not in READY_STATUSES, "a binary existing is not an arm that works"
    assert "installed" in res.message


def test_capability_check_is_what_earns_ready():
    arm = ArmConfig(id="proven", name="Proven", type="cli", command="python",
                    health_check="python --version", capability_check="python -c \"pass\"")
    assert probe_cli_arm(arm).status == "OPERATIONAL"

    failing = ArmConfig(id="unproven", name="Unproven", type="cli", command="python",
                        health_check="python --version",
                        capability_check="python -c \"import sys; sys.exit(4)\"")
    res = probe_cli_arm(failing)
    assert res.status == "NOT_RUNNING"
    assert "capability check" in res.message.lower()


def test_headline_does_not_count_arms_it_is_about_to_disown(capsys):
    """Field run: three arms answering one `unity-cli --version` produced three
    READYs and a warning saying at most one is real -- the number and the prose
    contradicting each other on the same screen."""
    config = CocktailConfig(
        name="x", description="",
        arms=[ArmConfig(id=n, name=n, type="cli", command="unity-cli",
                        health_check="unity-cli --version") for n in ("a", "b", "c")],
    )
    results = [ArmHealthResult(n, n, "READY", "ok", {}) for n in ("a", "b", "c")]
    print_doctor_report(results, config)

    out = capsys.readouterr().out
    assert "1/3 arms READY" in out, "at most one of a collision group can be the real install"
    assert "+2 indistinguishable" in out
    assert "P4 Warning" in out


def test_collision_warning_survives_the_demotion_to_installed_only(capsys):
    """Demoting version-only arms out of READY must not also silence the
    warning about them: the collision is about which program owns the name."""
    config = CocktailConfig(
        name="x", description="",
        arms=[ArmConfig(id=n, name=n, type="cli", command="unity-cli",
                        health_check="unity-cli --version") for n in ("a", "b")],
    )
    results = [ArmHealthResult(n, n, "INSTALLED_ONLY", "installed", {}) for n in ("a", "b")]
    print_doctor_report(results, config)

    assert "P4 Warning" in capsys.readouterr().out


def test_arms_sharing_a_stack_on_purpose_are_not_a_collision():
    """Field run: doctor claimed at most one of official-unity-cli and
    official-unity-mcp could really be installed. They are one product reached
    two ways, so the claim was simply false."""
    config = CocktailConfig(
        name="x", description="",
        arms=[
            ArmConfig(id="cli", name="CLI", type="cli", command="unity",
                      health_check="unity status --json", binary_group="unity-official"),
            ArmConfig(id="mcp", name="MCP", type="mcp", mcp_server="u",
                      health_check="unity status --json", binary_group="unity-official"),
        ],
    )
    assert shared_probe_binaries(config) == {}


def test_mcp_arm_cannot_borrow_cli_target_health_as_delivery_proof():
    arm = ArmConfig(
        id="official-unity-mcp", name="Official MCP", type="mcp",
        health_check="unity status --json", binding_path="data.instances[].project",
    )
    target = ArmHealthResult("official-unity-mcp", "Official MCP", "OPERATIONAL", "Editor answered.", {})
    with patch("mcp_cocktail.doctor.probe_cli_arm", return_value=target):
        result = probe_mcp_arm(arm, Path.cwd())
    assert result.status == "TARGET_ONLY"
    assert "MCP delivery route" in result.message
    assert result.status not in READY_STATUSES


def test_run_doctor_marks_shared_binary_rows_ambiguous():
    config = CocktailConfig(
        name="x", description="",
        arms=[ArmConfig(id=n, name=n, type="cli", command="unity-cli",
                        health_check="unity-cli --version") for n in ("a", "b")],
    )
    installed = {
        n: ArmHealthResult(n, n, "INSTALLED_ONLY", "installed", {}) for n in ("a", "b")
    }
    with patch("mcp_cocktail.doctor.doctor_check_arm", side_effect=lambda arm, root: installed[arm.id]):
        results = run_doctor(config)
    assert [result.status for result in results] == ["AMBIGUOUS_IDENTITY", "AMBIGUOUS_IDENTITY"]


def test_shipped_preset_does_not_flag_the_official_arms():
    config = CocktailConfig.load(PRESETS_DIR / "unity" / "manifest.json")
    collisions = shared_probe_binaries(config)

    assert "unity" not in collisions, "the official CLI and MCP are one install by design"
    assert set(collisions.get("unity-cli", [])) == {"akiojin-cli", "youngwoo-cli", "rage-cli"}


def test_no_arm_ships_the_invalid_ivanmurzak_subpath():
    """Field run: the git URL recorded here pointed at
    Unity-MCP-Plugin/Assets/root, which does not exist. Unity answers a bad UPM
    git URL with a blocking modal -- 10 minutes lost to a value that was never
    verified before shipping."""
    config = CocktailConfig.load(PRESETS_DIR / "unity" / "manifest.json")

    for arm in config.arms:
        install = arm.install or {}
        # The note may (and does) explain why the path was removed. What must
        # not survive is anything a reader or an agent would act on.
        actionable = json.dumps([
            install.get("package_url"), install.get("command"),
            [s for s in (install.get("steps") or []) if isinstance(s, dict)],
        ])
        assert "Assets/root" not in actionable, f"{arm.id} still ships the invalid subpath"


def test_collision_warning_names_the_program_that_actually_won(capsys, monkeypatch):
    """The discriminator was already in hand and discarded: which() returns the
    path, and an install location identifies the winner far more reliably than
    a version string. On the field machine `unity-cli` resolved to go/bin,
    which names the Go arm outright."""
    monkeypatch.setattr("mcp_cocktail.doctor.shutil.which",
                        lambda name: r"C:\Users\dev\go\bin\unity-cli.exe" if name == "unity-cli" else None)

    config = CocktailConfig(
        name="x", description="",
        arms=[ArmConfig(id=n, name=n, type="cli", command="unity-cli",
                        health_check="unity-cli --version") for n in ("a", "b")],
    )
    results = [ArmHealthResult(n, n, "INSTALLED_ONLY", "installed", {}) for n in ("a", "b")]
    print_doctor_report(results, config)

    out = capsys.readouterr().out
    assert r"go\bin\unity-cli.exe" in out, "the resolved path is the whole answer"
