# Provisioning failure diagnostics

The readiness tasks already emitted status and recent events on failure. This
change replaces their unrestricted text with bounded, sanitized collection; it
does not introduce the first pre-cleanup capture or publish the local reports.

On control-plane readiness failure, the runner's Ansible output includes sanitized
provisioning evidence before cleanup. This is retained in the CI step's stdout/log
without requiring `ARTIFACT_DIR` or publishing the runner's local reports. The
readiness timeout and cleanup behavior are unchanged; this does not resolve a
service provisioning failure.

The collector uses only the current `oc` context. It allowlists boolean readiness
and initialization, known service states (when exposed by the API) and condition
types/statuses, integer generations, and UTC transition timestamps. Recent events
must match the control plane's UID and kind; only event type, count and timestamps
are retained, along with a fixed allowlist of CAPA reason constants. Unknown enums
are redacted; absent state and typed scalar fields are null. Condition types and
reasons follow CAPA's ROSA API constants, plus the standard Ready condition.

Messages, arbitrary reasons, resource names/UIDs, specs, secret references, cloud
identities, and command error text are never included. Each API request has a bounded timeout;
unavailable or invalid evidence produces a fixed marker, not a new test failure.
An invalid event response does not discard valid control-plane evidence.

Offline regression tests execute the actual readiness tasks and runner scenario
cleanup using a mocked `oc`. They require Ansible, jq, PyYAML and pytest:

```sh
python3 -m pytest tests/test_provisioning_diagnostics.py tests/test_run_test_suite.py -v
```
