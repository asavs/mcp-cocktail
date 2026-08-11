"""Tests for mcp_cocktail.doctor module."""

import contextlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from mcp_cocktail.config import CocktailConfig, ArmConfig
from mcp_cocktail.doctor import (
    check_arm_binding,
    extract_json_path,
    first_command_token,
    doctor_check_arm,
    run_doctor,
    probe_cli_arm,
    probe_mcp_arm,
    resolve_probe_binary,
    summarize_failure,
)

PRESETS_DIR = Path(__file__).resolve().parents[1] / "examples"


def test_probe_cli_arm_offline():
    arm = ArmConfig(id="nonexistent-cli", name="Fake CLI", type="cli", command="nonexistent_binary_xyz_123")
    res = probe_cli_arm(arm)
    assert res.status == "OFFLINE"


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


def test_failed_health_check_is_offline_not_ready():
    """A health check that runs and fails must not fall through to
    'executable found in PATH'. Surfaced by repairing the probe binary
    resolver: once the health_check's own binary is resolvable, a failing
    check reached the trailing READY and green-lit a dead arm."""
    arm = ArmConfig(id="failing", name="Failing", type="cli",
                    health_check="python -c \"import sys; sys.exit(3)\"")
    res = probe_cli_arm(arm)
    assert res.status == "OFFLINE"
    assert "exit 3" in res.message


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
def local_server(handler_body: bytes, content_type: str = "text/plain", status: int = 200):
    """Serve one canned response on an ephemeral port."""

    class Handler(BaseHTTPRequestHandler):
        def _respond(self):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(handler_body)))
            self.end_headers()
            self.wfile.write(handler_body)

        do_GET = _respond
        do_POST = _respond

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
    assert "not speaking MCP" in res.message


def test_http_200_from_a_real_jsonrpc_endpoint_is_ready():
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}).encode()
    with local_server(body, content_type="application/json") as url:
        arm = ArmConfig(id="genuine", name="Genuine", type="mcp", health_check=url)
        res = probe_mcp_arm(arm)

    assert res.status == "READY"


def test_406_still_reports_bound_only_without_a_handshake():
    """coplay-mcp's verified P4 path: the 401/403/406 branch must keep its
    existing verdict rather than being re-decided by the handshake."""
    with local_server(b"Not Acceptable", status=406) as url:
        arm = ArmConfig(id="coplay-mcp", name="Coplay", type="mcp", health_check=url)
        res = probe_mcp_arm(arm)

    assert res.status == "SOCKET_BOUND_ONLY"
    assert "406" in res.message
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


def test_unity_preset_declares_a_binding_for_project_scoped_arms():
    arms = {a.id: a for a in CocktailConfig.load(PRESETS_DIR / "unity" / ".agents" / "manifest.json").arms}
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
    for arm in CocktailConfig.load(preset_root / ".agents" / "manifest.json").arms:
        if arm.setup_script:
            assert (preset_root / arm.setup_script).exists(), (
                f"{arm.id}: setup_script '{arm.setup_script}' not present in the preset"
            )


def test_shipped_presets_state_urls_bare():
    """Regression: every arm in the Unity preset wrapped its URL in `curl -s`,
    so 11/11 arms took probe_cli_arm and the HTTP + stdio branches were dead
    code. SOCKET_BOUND_ONLY (P4) was unreachable."""
    manifests = sorted(PRESETS_DIR.glob("*/.agents/manifest.json"))
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
