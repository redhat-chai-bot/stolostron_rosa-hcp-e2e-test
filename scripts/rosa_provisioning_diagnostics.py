"""Bounded, fail-closed ROSA provisioning evidence for the CI log."""

import argparse
import json
import re
import subprocess


STATES = {"pending", "installing", "ready", "error", "uninstalling", "waiting"}
CONDITION_TYPES = {
    "Ready",
    "ROSAControlPlaneReady",
    "ROSAControlPlaneValid",
    "ROSAControlPlaneUpgrading",
    "ExternalAuthConfigured",
    "ROSARoleConfigReady",
}
CONDITION_STATUSES = {"True", "False", "Unknown"}


def allowed(value, choices):
    """Do not treat arbitrary API strings as safe technical content."""
    return value if isinstance(value, str) and value in choices else "[redacted]"


def timestamp(value):
    """Accept only the UTC second-resolution Kubernetes timestamp format."""
    if isinstance(value, str) and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value
    ):
        return value
    return None


def integer(value):
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


def sanitize(control_plane, events):
    """Project known fields only; omit messages, reasons, identities and specs."""
    status = control_plane.get("status", {})
    metadata = control_plane.get("metadata", {})
    uid = metadata.get("uid")
    conditions = status.get("conditions", [])
    matching_events = [
        event
        for event in events.get("items", [])
        if uid
        and event.get("involvedObject", {}).get("uid") == uid
        and event.get("involvedObject", {}).get("kind") == "ROSAControlPlane"
    ]
    return {
        "ready": status.get("ready") if type(status.get("ready")) is bool else None,
        "state": allowed(status["state"], STATES) if "state" in status else None,
        "initialized": (
            status.get("initialized")
            if type(status.get("initialized")) is bool
            else None
        ),
        "observedGeneration": integer(status.get("observedGeneration")),
        "generation": integer(metadata.get("generation")),
        "conditions": [
            {
                "type": allowed(condition.get("type"), CONDITION_TYPES),
                "status": allowed(condition.get("status"), CONDITION_STATUSES),
                "lastTransitionTime": timestamp(condition.get("lastTransitionTime")),
            }
            for condition in conditions[:32]
            if isinstance(condition, dict)
        ],
        "events": [
            {
                "type": allowed(event.get("type"), {"Normal", "Warning"}),
                "count": integer(event.get("count")),
                "firstTimestamp": timestamp(event.get("firstTimestamp")),
                "lastTimestamp": timestamp(event.get("lastTimestamp")),
            }
            for event in matching_events[-10:]
        ],
    }


def get_json(arguments):
    result = subprocess.run(
        ["oc", "--request-timeout=10s", *arguments, "-o", "json"],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    return json.loads(result.stdout)


def collect(cluster, namespace):
    """Collector failures contain no subprocess output or exception text."""
    try:
        control_plane = get_json(["get", "rosacontrolplane", cluster, "-n", namespace])
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"collection": "control-plane-unavailable"}
    try:
        events = get_json(
            [
                "get",
                "events",
                "-n",
                namespace,
                "--field-selector",
                f"involvedObject.name={cluster},involvedObject.kind=ROSAControlPlane",
                "--sort-by=.lastTimestamp",
            ]
        )
        event_collection = "collected"
    except (OSError, subprocess.SubprocessError, ValueError):
        events = {"items": []}
        event_collection = "unavailable"
    try:
        evidence = sanitize(control_plane, events)
    except (AttributeError, TypeError, ValueError):
        return {"collection": "invalid-response"}
    evidence["eventCollection"] = event_collection
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--namespace", required=True)
    args = parser.parse_args()
    print(json.dumps(collect(args.cluster, args.namespace), sort_keys=True))


if __name__ == "__main__":
    main()
