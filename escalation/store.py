"""File-based storage for intervention requests and their handoff logs
(spec §8). Two processes read/write these files: the paused replay
process (escalation/handoff.py) and the operator surface
(escalation/operator_app.py) -- the JSON file's `status` field is the
handoff signal between them.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUESTS_DIR = REPO_ROOT / "escalation" / "requests"
SCREENSHOTS_DIR = REPO_ROOT / "escalation" / "screenshots"


def _request_path(request_id: str) -> Path:
    return REQUESTS_DIR / f"{request_id}.json"


def _log_path(request_id: str) -> Path:
    return REQUESTS_DIR / f"{request_id}_log.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_request(
    request_id: str,
    capability_id: str,
    version: str,
    run_id: str,
    step_id: str,
    expected: str,
    observed: str,
    screenshot_path: str,
    inputs_masked: dict,
) -> dict:
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    request = {
        "request_id": request_id,
        "capability_id": capability_id,
        "version": version,
        "run_id": run_id,
        "step_id": step_id,
        "expected": expected,
        "observed": observed,
        "screenshot_path": screenshot_path,
        "inputs_masked": inputs_masked,
        "created_at": _now(),
        "status": "pending",
        "resolved_at": None,
        "manual_action": None,
        "resolution_note": None,
        "final_outcome": None,
        "control_returned_at": None,
    }
    _request_path(request_id).write_text(json.dumps(request, indent=2))
    _write_log(request_id, {"event": "paused", "timestamp": request["created_at"], "step_id": step_id, "reason": observed})
    return request


def get_request(request_id: str) -> dict:
    return json.loads(_request_path(request_id).read_text())


def list_requests(status: str = None) -> list:
    if not REQUESTS_DIR.exists():
        return []
    requests = []
    for path in sorted(REQUESTS_DIR.glob("*.json")):
        if path.name.endswith("_log.json"):
            continue
        request = json.loads(path.read_text())
        if status is None or request["status"] == status:
            requests.append(request)
    return requests


def mark_resolved(request_id: str, manual_action: dict = None, resolution_note: str = None) -> dict:
    """Called by the operator surface: a human has taken over the same
    live session, (optionally) performed a described action, and is
    signaling that automation should re-verify and resume."""
    request = get_request(request_id)
    request["status"] = "resolved"
    request["resolved_at"] = _now()
    request["manual_action"] = manual_action
    request["resolution_note"] = resolution_note
    _request_path(request_id).write_text(json.dumps(request, indent=2))
    _write_log(
        request_id,
        {
            "event": "human_took_over",
            "timestamp": request["resolved_at"],
            "manual_action": manual_action,
            "resolution_note": resolution_note,
        },
    )
    return request


def finalize(request_id: str, final_outcome: str, checkpoint_observed: str) -> dict:
    """Called by the (paused) replay process once it has resumed control,
    re-verified the checkpoint, and reached a final outcome."""
    request = get_request(request_id)
    request["final_outcome"] = final_outcome
    request["control_returned_at"] = _now()
    _request_path(request_id).write_text(json.dumps(request, indent=2))
    _write_log(
        request_id,
        {
            "event": "control_returned",
            "timestamp": request["control_returned_at"],
            "checkpoint_observed": checkpoint_observed,
            "final_outcome": final_outcome,
        },
    )
    return request


def _write_log(request_id: str, event: dict) -> None:
    log_path = _log_path(request_id)
    log = json.loads(log_path.read_text()) if log_path.exists() else {"request_id": request_id, "events": []}
    log["events"].append(event)
    log_path.write_text(json.dumps(log, indent=2))


def get_log(request_id: str) -> dict:
    return json.loads(_log_path(request_id).read_text())


class ResolutionTimeout(Exception):
    pass


def wait_for_resolution(request_id: str, poll_interval: float = 0.5, timeout: float = None) -> dict:
    """Blocks the calling thread until the request's status is 'resolved'.
    The caller is expected to be the same thread holding the live
    Playwright page -- this is the 'pause' (nothing about the browser or
    session changes while this loop runs)."""
    import time

    waited = 0.0
    while True:
        request = get_request(request_id)
        if request["status"] == "resolved":
            return request
        if timeout is not None and waited >= timeout:
            raise ResolutionTimeout(f"request {request_id} was not resolved within {timeout}s")
        time.sleep(poll_interval)
        waited += poll_interval
