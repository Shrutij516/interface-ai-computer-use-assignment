"""End-to-end proof of the pause -> intervention request -> manual
mark-resolved -> resume flow (spec §8), against a real live Playwright
session -- no mocked browser, no faked page state.

The failure is injected deliberately: a copy of the real, evidence-backed
lookup_member_balance v1.1.0 artifact has its "click Search" step's
locator corrupted to a button that doesn't exist. Replaying it for member
10001 (a real member who would otherwise succeed, per
evidence/discovery/20260918T023723Z/ and evidence/replay/) hits a hard
failure at that step: the recorded locator can't be resolved and there's
no fallback.

run_replay() is started on a background thread so it can genuinely block
in escalation.handoff.pause_and_handoff's wait loop while this thread
plays the human operator: poll escalation/requests/ for the pending
request, then call escalation.store.mark_resolved with a manual_action
describing what a human would have done -- click the real "Search"
button, which is right there on the page, just not under the locator
string the artifact happened to record. The SAME background thread that
owns the Playwright page (never any other thread) carries out that click
once it wakes from the wait loop, re-verifies the checkpoint, completes
the extract step that never got to run, and returns success.

Run with: python -m escalation.test_escalation
"""

import threading
import time

from artifacts.schema import Locator
from artifacts.store import load_artifact
from escalation import store
from replay.engine import run_replay

MEMBER_ID = "10001"
EXPECTED_BALANCE = "$15234.56"


def _corrupt_click_step(artifact):
    corrupted = artifact.model_copy(deep=True)
    for step in corrupted.steps:
        if step.action == "click":
            step.locator = Locator(strategy="role", value="button:DoesNotExist")
    return corrupted


def _find_pending_request(capability_id: str, step_id: str, timeout: float = 15.0) -> str:
    waited = 0.0
    while waited < timeout:
        for r in store.list_requests(status="pending"):
            if r["capability_id"] == capability_id and r["step_id"] == step_id:
                return r["request_id"]
        time.sleep(0.3)
        waited += 0.3
    raise TimeoutError(f"no pending request for {capability_id}/{step_id} appeared within {timeout}s")


def main() -> None:
    artifact = load_artifact("lookup_member_balance", "1.1.0")
    corrupted = _corrupt_click_step(artifact)
    click_step_id = next(s.step_id for s in corrupted.steps if s.action == "click")

    result_holder = {}

    def _run():
        result_holder["result"] = run_replay(
            corrupted,
            {"member_id": MEMBER_ID},
            escalation_poll_interval=0.3,
            escalation_timeout=30.0,
        )

    replay_thread = threading.Thread(target=_run)
    replay_thread.start()

    print(f"--- Waiting for the injected failure at step '{click_step_id}' to raise an intervention request ---")
    request_id = _find_pending_request("lookup_member_balance", click_step_id)
    request = store.get_request(request_id)
    print("Pending request:", request)

    print("\n--- Acting as the operator: viewing context, then marking resolved with a manual fix ---")
    store.mark_resolved(
        request_id,
        manual_action={"action": "click", "strategy": "role", "value": "button:Search"},
        resolution_note="Recorded locator drifted (button:DoesNotExist); the real Search button is right there -- clicked it manually.",
    )

    replay_thread.join(timeout=30)
    result = result_holder.get("result")
    print("\n--- Final replay result after resume ---")
    print(result)

    resolved_request = store.get_request(request_id)
    handoff_log = store.get_log(request_id)
    print("\n--- Escalation request (final state) ---")
    print(resolved_request)
    print("\n--- Handoff log ---")
    print(handoff_log)

    failures = []
    if result is None:
        failures.append("replay thread did not finish in time")
    else:
        if result.get("outcome") != "success":
            failures.append(f"expected outcome=success after handoff, got {result.get('outcome')}: {result}")
        elif result["outputs"].get("savings_balance") != EXPECTED_BALANCE:
            failures.append(f"expected savings_balance={EXPECTED_BALANCE!r}, got {result['outputs'].get('savings_balance')!r}")
        if "escalation" not in result:
            failures.append("result is missing the 'escalation' record")
    if resolved_request["status"] != "resolved":
        failures.append(f"expected request status=resolved, got {resolved_request['status']}")
    if resolved_request.get("final_outcome") != "success":
        failures.append(f"expected request final_outcome=success, got {resolved_request.get('final_outcome')}")
    event_names = [e["event"] for e in handoff_log["events"]]
    if event_names != ["paused", "human_took_over", "control_returned"]:
        failures.append(f"expected handoff log events [paused, human_took_over, control_returned], got {event_names}")

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        raise SystemExit(1)
    print("PASS: pause -> intervention request -> manual resolve -> resume worked end to end.")


if __name__ == "__main__":
    main()
