"""Proves safety.policy's enforcement is real and wired into both
agent/executor.py (discovery) and replay/engine.py (replay) -- the same
module, not two implementations that could drift apart.

(a) An action outside the allowlist (a navigate to a domain other than
    mock_bank's) is refused and logged, on both paths:
      - agent/executor.execute_action refuses it directly -- exactly the
        function agent/discover.py calls for every action, so no LLM or
        API key is needed to prove discovery-side enforcement is real.
      - replay.engine.run_replay refuses the same way, through a
        synthetic artifact step; the refusal is both returned in the
        result and written to evidence/replay/<run_id>/steps.jsonl.

(b) mock_bank's one irreversible action -- POSTing to
    /subaccounts/confirm, which actually creates the sub-account --
    attempted cold, without ever having reached the confirmation/review
    screen first, is refused as a hard stop (spec §9: never
    auto-confirmed), via replay.engine.run_replay with a synthetic
    artifact whose only step targets that route directly from a fresh
    page.

Run with: python -m safety.test_safety
"""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from agent.executor import SafetyBlocked, execute_action
from artifacts.schema import Artifact, Checkpoint, FailureHandling, Locator, Step
from replay.engine import DEFAULT_TARGET_URL, EVIDENCE_ROOT, _is_reachable, _start_mock_bank, run_replay


def _off_allowlist_artifact() -> Artifact:
    return Artifact(
        capability_id="test_off_allowlist",
        version="0.0.1",
        description="Test fixture: a step that navigates off the allowed domain.",
        inputs=[],
        outputs=[],
        steps=[
            Step(
                step_id="step_0",
                action="navigate",
                locator=Locator(strategy="url", value="http://example.com/"),
                on_failure=FailureHandling(type="hard_failure", message="should never get this far"),
            ),
        ],
        checkpoint=Checkpoint(
            description="unreachable -- the step above should be refused first",
            locator=Locator(strategy="text", value="unused"),
        ),
    )


def _risky_without_confirmation_artifact() -> Artifact:
    return Artifact(
        capability_id="test_risky_cold",
        version="0.0.1",
        description="Test fixture: jumps straight at the sub-account confirm route with no prior review screen.",
        inputs=[],
        outputs=[],
        steps=[
            Step(
                step_id="step_0",
                action="navigate",
                locator=Locator(strategy="url", value="/members/10001/subaccounts/confirm"),
                on_failure=FailureHandling(type="hard_failure", message="should never get this far"),
            ),
        ],
        checkpoint=Checkpoint(
            description="unreachable -- the step above should be refused first",
            locator=Locator(strategy="text", value="unused"),
        ),
    )


def test_a_agent_side() -> None:
    print("--- (a) agent/executor.py: off-allowlist navigate ---")
    mock_bank_proc = None
    if not _is_reachable(DEFAULT_TARGET_URL):
        mock_bank_proc = _start_mock_bank(DEFAULT_TARGET_URL)

    raised = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(DEFAULT_TARGET_URL)
            try:
                execute_action(page, {"action": "navigate", "url": "http://example.com/"})
            except SafetyBlocked as exc:
                raised = exc
            browser.close()
    finally:
        if mock_bank_proc is not None:
            mock_bank_proc.terminate()
            mock_bank_proc.wait(timeout=5)

    print(f"SafetyBlocked raised: {raised!r}")
    assert raised is not None, "expected execute_action to refuse an off-allowlist navigate"
    print("PASS (a, agent side): off-allowlist action refused by the exact function agent/discover.py calls.\n")


def test_a_replay_side() -> dict:
    print("--- (a) replay/engine.py: off-allowlist navigate ---")
    result = run_replay(_off_allowlist_artifact(), {})
    print(result)
    assert result["outcome"] == "failure", f"expected outcome=failure, got {result}"
    assert result.get("blocked_by_safety") is True, f"expected blocked_by_safety=True, got {result}"

    log_path = EVIDENCE_ROOT / result["run_id"] / "steps.jsonl"
    logged_statuses = [json.loads(line).get("result", {}).get("status") for line in log_path.read_text().splitlines()]
    assert "blocked_by_safety" in logged_statuses, f"expected a blocked_by_safety entry in {log_path}, got {logged_statuses}"
    print(f"Confirmed logged to {log_path.relative_to(Path.cwd())} with status 'blocked_by_safety'.")
    print("PASS (a, replay side): off-allowlist action refused and logged.\n")
    return result


def test_b_replay_side() -> dict:
    print("--- (b) replay/engine.py: risky sub-account action attempted without a prior confirmation screen ---")
    result = run_replay(_risky_without_confirmation_artifact(), {})
    print(result)
    assert result["outcome"] == "failure", f"expected outcome=failure, got {result}"
    assert result.get("blocked_by_safety") is True, f"expected blocked_by_safety=True, got {result}"
    assert "confirmation" in result["observed"].lower(), (
        f"expected the refusal reason to mention a missing confirmation screen, got {result['observed']!r}"
    )
    print("PASS (b): risky/irreversible action refused as a hard stop -- no confirmation screen was ever shown.\n")
    return result


def main() -> None:
    test_a_agent_side()
    test_a_replay_side()
    test_b_replay_side()
    print("ALL PASS")


if __name__ == "__main__":
    main()
