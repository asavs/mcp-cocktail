import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_cocktail.trial_state import (
    Artifact,
    Evidence,
    LeaseBusyError,
    LeaseNotExpiredError,
    LeaseOwnershipError,
    MutationLease,
    ObservationOutcome,
    OperationalObservation,
    StageAttempt,
    StageOutcome,
    TrialStage,
    TrialStateStore,
)


def observation(outcome: str, layer: str = "target_operation") -> OperationalObservation:
    return OperationalObservation(
        arm="coplay",
        capability="editmode-tests",
        layer=layer,
        operation="unity_ping",
        outcome=outcome,
        observed_at="2026-08-12T12:00:00Z",
        latency_ms=2000,
        project_identity="project-guid",
    )


def test_composite_stages_preserve_which_arm_produced_and_verified(tmp_path: Path):
    store = TrialStateStore(tmp_path / "trial-state.json", "T-901")
    store.add_stage(TrialStage("author", "file-authoring", "official-mcp"))
    store.add_stage(TrialStage(
        "test", "editmode-tests", "official-mcp", ["coplay"], depends_on=["author"]
    ))
    store.begin_stage("author", "official-mcp")
    store.claim_finish("author", "official-mcp", None)
    store.record_attempt("author", StageAttempt(
        arm="official-mcp",
        outcome=StageOutcome.SUCCEEDED.value,
        started_at="2026-08-12T11:40:00Z",
        finished_at="2026-08-12T11:48:00Z",
        artifacts=[Artifact("Assets/Game/HealingShrine.cs", producer_arm="official-mcp")],
    ))
    store.begin_stage("test", "coplay")
    store.claim_finish("test", "coplay", None)
    state = store.record_attempt("test", StageAttempt(
        arm="coplay",
        outcome=StageOutcome.SUCCEEDED.value,
        started_at="2026-08-12T11:48:00Z",
        evidence=[Evidence("test-run", "7/7 passed", verifier_arm="coplay")],
    ))

    assert state["trial_id"] == "T-901"
    assert state["stages"][0]["attempts"][0]["artifacts"][0]["producer_arm"] == "official-mcp"
    assert state["stages"][1]["attempts"][0]["arm"] == "coplay"
    assert state["stages"][1]["attempts"][0]["evidence"][0]["verifier_arm"] == "coplay"


def test_stage_rejects_unassigned_arm_and_unknown_dependency(tmp_path: Path):
    store = TrialStateStore(tmp_path / "state.json", "T-1")
    with pytest.raises(ValueError, match="Unknown stage dependencies"):
        store.add_stage(TrialStage("test", "tests", "a", depends_on=["author"]))
    store.add_stage(TrialStage("author", "author", "a", ["b"]))
    with pytest.raises(ValueError, match="not assigned"):
        store.record_attempt("author", StageAttempt("c", "failed", "now"))


def test_contract_models_reject_unknown_outcomes():
    with pytest.raises(ValueError, match="attempt outcome"):
        StageAttempt("a", "looks-good", "now")
    with pytest.raises(ValueError, match="stage outcome"):
        TrialStage("stage", "read", "a", outcome="maybe")
    with pytest.raises(ValueError, match="observation outcome"):
        observation("socket-seemed-fine")
    with pytest.raises(ValueError, match="observation layer"):
        observation("succeeded", layer="installed")


def test_atomic_transactions_do_not_lose_concurrent_observations(tmp_path: Path):
    store = TrialStateStore(tmp_path / "state.json", "T-1")
    barrier = threading.Barrier(8)
    errors = []

    def writer(index: int):
        try:
            barrier.wait()
            store.record_observation(OperationalObservation(
                arm=f"arm-{index}", capability="read", layer="transport",
                operation="initialize", outcome="succeeded", observed_at=f"time-{index}",
            ))
        except Exception as exc:  # pragma: no cover - assertion reports thread failures
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(store.read()["observations"]) == 8
    # OS locks are crash-released; the inert lock file may remain.
    assert store.lock_path.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_target_failures_open_circuit_and_transport_success_does_not_close_it(tmp_path: Path):
    store = TrialStateStore(tmp_path / "state.json", "T-1")
    store.record_observation(observation(ObservationOutcome.TIMED_OUT.value))
    opened = store.record_observation(observation(ObservationOutcome.FAILED.value))
    assert opened["circuits"]["coplay:editmode-tests"]["state"] == "open"

    still_open = store.record_observation(observation(
        ObservationOutcome.SUCCEEDED.value, layer="transport"
    ))
    assert still_open["circuits"]["coplay:editmode-tests"]["state"] == "open"

    recovered = store.record_observation(observation(ObservationOutcome.SUCCEEDED.value))
    assert recovered["circuits"]["coplay:editmode-tests"]["state"] == "closed"
    assert recovered["circuits"]["coplay:editmode-tests"]["consecutive_failures"] == 0


def test_older_success_cannot_close_newer_open_circuit(tmp_path: Path):
    store = TrialStateStore(tmp_path / "state.json", "T-1")
    newer = observation(ObservationOutcome.TIMED_OUT.value)
    newer.observed_at = "2026-08-12T12:01:00Z"
    store.record_observation(newer, failure_threshold=1)
    older = observation(ObservationOutcome.SUCCEEDED.value)
    older.observed_at = "2026-08-12T12:00:00Z"

    state = store.record_observation(older, failure_threshold=1)

    assert state["circuits"]["coplay:editmode-tests"]["state"] == "open"


def test_observation_can_also_feed_shared_doctor_evidence(tmp_path: Path):
    store = TrialStateStore(tmp_path / "trials" / "state.json", "T-1", tmp_path)
    store.add_stage(TrialStage("read", "editor-read", "coplay"))
    assert not (tmp_path / ".agents" / "health-observations.json").exists()
    store.record_observation(observation(ObservationOutcome.TIMED_OUT.value))
    shared = json.loads((tmp_path / ".agents" / "health-observations.json").read_text("utf-8"))
    assert shared["observations"][0]["layer"] == "target_operation"
    assert shared["observations"][0]["outcome"] == "timed_out"


def test_mutation_lease_is_exclusive_and_only_owner_releases(tmp_path: Path):
    first = MutationLease(tmp_path, "arm-a", trial_id="T-1").acquire()
    assert first.holder()["owner"] == "arm-a"
    assert first.holder()["trial_id"] == "T-1"
    assert first.path == tmp_path / ".agents" / "leases" / "unity-editor-workspace.json"
    with pytest.raises(LeaseBusyError, match="arm-a"):
        MutationLease(tmp_path, "arm-b", trial_id="T-2").acquire()

    # A different instance cannot use release() to remove a lease it never held.
    MutationLease(tmp_path, "arm-b", trial_id="T-2").release()
    assert first.path.exists()
    first.release()
    assert not first.path.exists()


def test_distinct_shared_resources_can_be_leased_concurrently(tmp_path: Path):
    editor = MutationLease(
        tmp_path, "arm-a", resource="unity-editor", trial_id="T-1"
    ).acquire()
    filesystem = MutationLease(
        tmp_path, "arm-b", resource="workspace-files", trial_id="T-2"
    ).acquire()
    try:
        assert editor.path != filesystem.path
        assert editor.holder()["resource"] == "unity-editor"
        assert filesystem.holder()["resource"] == "workspace-files"
    finally:
        filesystem.release()
        editor.release()


def test_mutation_lease_rejects_resource_path_traversal(tmp_path: Path):
    with pytest.raises(ValueError, match="path-safe"):
        MutationLease(tmp_path, "arm", resource="../other")


def test_attach_and_renew_require_exact_token(tmp_path: Path):
    original = MutationLease(tmp_path, "arm-a", trial_id="T-1", ttl_seconds=10).acquire()
    with pytest.raises(LeaseBusyError, match="token"):
        MutationLease.attach(tmp_path, "arm-a", "wrong-token", trial_id="T-1")
    controller = MutationLease.attach(tmp_path, "arm-a", original.token, trial_id="T-1")
    with patch("mcp_cocktail.trial_state.time.time", return_value=100.0):
        renewed = controller.renew(original.token, ttl_seconds=30)
    assert renewed["expires_at_epoch"] == 130.0
    controller.release()


def test_stale_recovery_requires_token_and_expiry_and_is_durably_audited(tmp_path: Path):
    with patch("mcp_cocktail.trial_state.time.time", return_value=100.0):
        lease = MutationLease(tmp_path, "arm-a", trial_id="T-1", ttl_seconds=10).acquire()
    recovery = MutationLease(tmp_path, "operator")
    with patch("mcp_cocktail.trial_state.time.time", return_value=111.0):
        with pytest.raises(LeaseOwnershipError, match="token"):
            recovery.recover_stale("wrong-token", "operator")
        evidence = recovery.recover_stale(lease.token, "operator")

    assert not lease.path.exists()
    assert evidence["action"] == "stale_recovery"
    audit = [json.loads(line) for line in recovery.audit_path.read_text("utf-8").splitlines()]
    assert audit == [evidence]


def test_attach_distinguishes_missing_lease_from_wrong_token(tmp_path: Path):
    with pytest.raises(LeaseBusyError, match="no longer exists"):
        MutationLease.attach(tmp_path, "operator", "missing-token")

    held = MutationLease(tmp_path, "owner").acquire()
    try:
        with pytest.raises(LeaseBusyError, match="token does not match"):
            MutationLease.attach(tmp_path, "operator", "wrong-token")
    finally:
        held.release()


def test_renewal_winning_guard_prevents_stale_recovery_race(tmp_path: Path):
    with patch("mcp_cocktail.trial_state.time.time", return_value=100.0):
        lease = MutationLease(tmp_path, "arm-a", trial_id="T-1", ttl_seconds=10).acquire()
    with patch("mcp_cocktail.trial_state.time.time", return_value=111.0):
        lease.renew(lease.token, ttl_seconds=30)
        with pytest.raises(LeaseNotExpiredError, match="not proven expired"):
            MutationLease(tmp_path, "operator").recover_stale(lease.token, "operator")
    assert lease.path.exists()
    assert not lease.audit_path.exists()
    lease.release()


def test_recovery_winning_guard_prevents_late_renewal(tmp_path: Path):
    with patch("mcp_cocktail.trial_state.time.time", return_value=100.0):
        lease = MutationLease(tmp_path, "arm-a", trial_id="T-1", ttl_seconds=10).acquire()
    with patch("mcp_cocktail.trial_state.time.time", return_value=111.0):
        MutationLease(tmp_path, "operator").recover_stale(lease.token, "operator")
        with pytest.raises(LeaseBusyError, match="ownership changed"):
            lease.renew(lease.token)


def test_state_file_is_plain_versioned_json_for_external_harnesses(tmp_path: Path):
    path = tmp_path / "state.json"
    TrialStateStore(path, "T-1").add_stage(TrialStage("read", "editor-read", "arm-a"))
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    assert document["stages"][0]["capability"] == "editor-read"
