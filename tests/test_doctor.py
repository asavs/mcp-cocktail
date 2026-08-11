"""Tests for mcp_cocktail.doctor module."""

import contextlib
import json
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from mcp_cocktail.config import CocktailConfig, ArmConfig
from mcp_cocktail.doctor import (
    MAX_REPORTED_FIELDS,
    READY_STATUSES,
    ArmHealthResult,
    evaluate_requirements,
    check_arm_binding,
    describe_binding,
    describe_instance,
    extract_json_path,
    first_command_token,
    doctor_check_arm,
    run_doctor,
    probe_cli_arm,
    probe_mcp_arm,
    resolve_probe_binary,
    summarize_failure,
)
from mcp_cocktail.installer import PRESETS_DIR


def test_probe_cli_arm_offline():
    arm = ArmConfig(id="nonexistent-cli", name="Fake CLI", type="cli", command="nonexistent_binary_xyz_123")
    res = probe_cli_arm(arm)
    assert res.status == "OFFLINE"


def test_health_check_runs_even_when_the_precheck_cannot_find_the_binary():
    """The child shell, not this process, decides what its own PATH resolves.

    shutil.which() and `shell=True` are two different resolvers -- shims,
    .cmd shadowing, a profile that extends PATH for the shell only -- and the
    precheck was short-circuiting to OFFLINE for arms whose health check runs
    fine one line later. A shell builtin is the cleanest portable stand-in for
    "runs in the shell, absent from PATH".
    """
    arm = ArmConfig(id="builtin", name="Builtin", type="cli",
                    command="nonexistent_binary_xyz_123", health_check="exit 0")
    assert shutil.which("nonexistent_binary_xyz_123") is None
    res = probe_cli_arm(arm)

    assert res.status == "READY", res.message


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


def test_evaluate_requirements():
    results = [
        ArmHealthResult("up", "Up", "READY", "fine", {}),
        ArmHealthResult("assumed", "Assumed", "ASSUMED_READY", "probably", {}),
        ArmHealthResult("down", "Down", "NOT_RUNNING", "start it", {}),
    ]

    assert evaluate_requirements(results, []) == ([], [])
    assert evaluate_requirements(results, ["up", "assumed"]) == ([], [])

    unmet, unknown = evaluate_requirements(results, ["up", "down"])
    assert [r.arm_id for r in unmet] == ["down"]
    assert unknown == []

    unmet, unknown = evaluate_requirements(results, ["typo-arm"])
    assert unmet == [] and unknown == ["typo-arm"]


def test_silent_success_still_counts_as_ready():
    arm = ArmConfig(id="quiet", name="Quiet", type="cli", health_check="python -c \"pass\"")
    assert probe_cli_arm(arm).status == "READY"


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
                    health_check=f'"{sys.executable}" -c "pass"')
    res = probe_cli_arm(arm)
    assert res.status == "READY", res.message


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


def test_http_200_from_a_real_jsonrpc_endpoint_is_ready():
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}).encode()
    with local_server(body, content_type="application/json") as url:
        arm = ArmConfig(id="genuine", name="Genuine", type="mcp", health_check=url)
        res = probe_mcp_arm(arm)

    assert res.status == "READY"


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

    assert res.status == "READY"
    assert "406" in res.message, "the GET status stays visible; it just stops being the verdict"


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
    assert results[0].status == "READY"
    assert results[1].status == "OFFLINE"
