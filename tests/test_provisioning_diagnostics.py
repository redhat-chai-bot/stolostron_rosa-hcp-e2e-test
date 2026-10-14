"""Offline consumer-path tests using Ansible and a fake oc executable."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


BASE_DIR = Path(__file__).resolve().parent.parent


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


diagnostics = load_module(
    "diagnostics", BASE_DIR / "scripts/rosa_provisioning_diagnostics.py"
)
runner_module = load_module("diagnostics_runner", BASE_DIR / "run-test-suite.py")
SENSITIVE = "DO_NOT_EMIT_SENSITIVE_FIXTURE"


def control_plane():
    return {
        "metadata": {"uid": "fixture-uid", "name": SENSITIVE, "generation": 2},
        "spec": {"credentialsSecretRef": {"name": SENSITIVE}},
        "status": {
            "state": "installing",
            "ready": False,
            "observedGeneration": 1,
            "failureMessage": SENSITIVE,
            "failureReason": SENSITIVE,
            "conditions": [
                {
                    "type": "Ready",
                    "status": "False",
                    "reason": SENSITIVE,
                    "message": SENSITIVE,
                    "lastTransitionTime": "2026-01-01T00:00:00Z",
                },
                {"type": SENSITIVE, "status": SENSITIVE},
            ],
        },
    }


def events():
    return {
        "items": [
            {
                "involvedObject": {"uid": uid, "kind": "ROSAControlPlane"},
                "type": "Warning",
                "count": 3,
                "message": SENSITIVE,
                "reason": SENSITIVE,
                "lastTimestamp": "2026-01-01T00:00:01Z",
            }
            for uid in ("unrelated-uid", "fixture-uid")
        ]
    }


def test_sanitization_is_fail_closed():
    result = diagnostics.sanitize(control_plane(), events())
    assert SENSITIVE not in json.dumps(result)
    assert "fixture-uid" not in json.dumps(result)
    assert result["state"] == "installing"
    assert result["ready"] is False
    assert result["generation"] == 2
    assert result["observedGeneration"] == 1
    assert result["conditions"][0] == {
        "type": "Ready",
        "status": "False",
        "reason": "[redacted]",
        "lastTransitionTime": "2026-01-01T00:00:00Z",
    }
    assert len(result["events"]) == 1
    assert result["events"][0]["count"] == 3
    assert diagnostics.timestamp(SENSITIVE) is None
    assert diagnostics.integer(True) is None
    assert diagnostics.integer(-1) is None
    payload = control_plane()
    payload["status"].update(state=SENSITIVE, ready=SENSITIVE)
    payload["metadata"]["generation"] = SENSITIVE
    assert SENSITIVE not in json.dumps(diagnostics.sanitize(payload, events()))


def test_progress_fields_and_event_filtering():
    payload = control_plane()
    del payload["status"]["state"]
    for initialized in (True, False, SENSITIVE):
        payload["status"]["initialized"] = initialized
        result = diagnostics.sanitize(payload, events())
        assert result["state"] is None
        assert result["initialized"] is (
            initialized if type(initialized) is bool else None
        )
    payload["status"]["conditions"] = [
        {"type": condition_type, "status": "Unknown"}
        for condition_type in sorted(diagnostics.CONDITION_TYPES)
    ]
    assert all(
        condition["type"] != "[redacted]"
        for condition in diagnostics.sanitize(payload, events())["conditions"]
    )
    mixed_events = events()
    mixed_events["items"] += [mixed_events["items"][0]] * 12
    assert len(diagnostics.sanitize(payload, mixed_events)["events"]) == 1


@pytest.mark.parametrize(
    "error",
    [
        OSError(SENSITIVE),
        ValueError(SENSITIVE),
        subprocess.TimeoutExpired(SENSITIVE, 15),
    ],
)
def test_collection_errors_do_not_include_exception_text(error):
    with patch.object(diagnostics, "get_json", side_effect=error):
        assert diagnostics.collect("fixture", "fixture") == {
            "collection": "control-plane-unavailable"
        }


def test_event_failure_retains_status():
    with patch.object(
        diagnostics, "get_json", side_effect=[control_plane(), OSError(SENSITIVE)]
    ):
        result = diagnostics.collect("fixture", "fixture")
    assert result["state"] == "installing"
    assert result["eventCollection"] == "unavailable"
    assert SENSITIVE not in json.dumps(result)


@pytest.mark.parametrize("invalid_events", [None, {"items": None}, {"items": [None]}])
def test_invalid_events_do_not_discard_control_plane_status(invalid_events):
    with patch.object(
        diagnostics, "get_json", side_effect=[control_plane(), invalid_events]
    ):
        result = diagnostics.collect("fixture", "fixture")
    assert result["state"] == "installing"
    assert result["ready"] is False
    assert result["eventCollection"] == "unavailable"
    assert SENSITIVE not in json.dumps(result)


def test_known_reasons_are_retained_without_freeform_text():
    for reason in diagnostics.CONDITION_REASONS:
        payload = control_plane()
        payload["status"]["conditions"][0]["reason"] = reason
        progress_events = events()
        progress_events["items"][1]["reason"] = reason
        result = diagnostics.sanitize(payload, progress_events)
        assert result["conditions"][0]["reason"] == reason
        assert result["events"][0]["reason"] == reason
        assert SENSITIVE not in json.dumps(result)


def test_invalid_response_is_not_dumped():
    with patch.object(diagnostics, "get_json", side_effect=[{"status": None}, {}]):
        assert diagnostics.collect("fixture", "fixture") == {
            "collection": "invalid-response"
        }


@pytest.mark.parametrize(
    "mode", ["success", "failure", "collector-failure", "command-failure"]
)
def test_actual_wait_failure_and_runner_cleanup(tmp_path, monkeypatch, capsys, mode):
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    fake_oc = binary_dir / "oc"
    calls = tmp_path / "calls"
    fake_oc.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"with open({str(calls)!r}, 'a') as stream:\n"
        "    stream.write(' '.join(sys.argv[1:]) + '\\n')\n"
        "if '--request-timeout=10s' not in sys.argv:\n"
        f"    print(json.dumps({{'status': {{'ready': {mode == 'success'!r}}}}}))\n"
        "else:\n"
        f"    if {mode!r} == 'collector-failure':\n"
        f"        print({SENSITIVE!r}, file=sys.stderr)\n"
        "        sys.exit(1)\n"
        "    if 'events' in sys.argv:\n"
        f"        print(json.dumps({events()!r}))\n"
        "    else:\n"
        f"        print(json.dumps({control_plane()!r}))\n"
    )
    fake_oc.chmod(0o755)
    monkeypatch.setenv(
        "PATH", f"{binary_dir}:{Path(sys.executable).parent}:/usr/bin:/bin"
    )
    monkeypatch.delenv("ARTIFACT_DIR", raising=False)
    assert shutil.which("ansible-playbook"), "Ansible is required for offline tests"
    assert shutil.which("jq"), "The actual wait task uses jq"
    monkeypatch.setenv("ANSIBLE_NOCOLOR", "1")
    suite_dir = tmp_path / "test-suites"
    suite_dir.mkdir()
    for name, tasks in (
        (
            "provision",
            [
                {
                    "ansible.builtin.include_tasks": str(
                        BASE_DIR / "tasks/wait_for_rosa_control_plane_ready.yml"
                    )
                }
            ],
        ),
        ("cleanup", [{"ansible.builtin.debug": {"msg": "CLEANUP_EXECUTED"}}]),
    ):
        playbook = tmp_path / f"{name}.yml"
        playbook.write_text(
            yaml.safe_dump(
                [
                    {
                        "hosts": "localhost",
                        "connection": "local",
                        "gather_facts": False,
                        "tasks": tasks,
                    }
                ]
            )
        )
        (suite_dir / f"{name}.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "playbooks": [{"name": name, "file": playbook.name}],
                }
            )
        )
    runner = runner_module.TestSuiteRunner(
        base_dir=tmp_path,
        extra_vars={
            "cluster_name": "fixture",
            "AUTOMATION_PATH": str(tmp_path if mode == "command-failure" else BASE_DIR),
            "retry_count": 1,
            "delay": 0,
        },
    )
    passed = runner.run_scenario(
        {
            "name": "offline",
            "description": "offline",
            "features": [],
            "stages": [
                {"suite": "provision", "always": False},
                {"suite": "cleanup", "always": True},
            ],
        }
    )
    assert passed is (mode == "success")
    provision = runner.results["suites"][0]["playbooks"][0]
    cleanup = runner.results["suites"][1]["playbooks"][0]
    assert cleanup["success"]
    assert "CLEANUP_EXECUTED" in cleanup["output"]
    assert SENSITIVE not in provision["output"]
    transcript = capsys.readouterr().out
    assert SENSITIVE not in transcript
    if mode == "success":
        assert "--request-timeout" not in calls.read_text()
    else:
        assert "ROSA HCP cluster did not become ready" in provision["error"]
        assert "captured before teardown" in provision["output"]
        assert transcript.index("captured before teardown") < transcript.index(
            "CLEANUP_EXECUTED"
        )
        assert ("--request-timeout=10s" in calls.read_text()) is (
            mode != "command-failure"
        )
        if mode == "failure":
            assert "installing" in provision["output"]
            assert '"ready": false' in provision["output"]
        elif mode == "collector-failure":
            assert "control-plane-unavailable" in provision["output"]
        else:
            assert (
                "Diagnostics unavailable; readiness failure unchanged"
                in provision["output"]
            )
