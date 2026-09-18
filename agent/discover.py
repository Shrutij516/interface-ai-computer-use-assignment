"""The discovery agent loop: observe -> decide -> act, LLM-driven, against
a live mock bank instance. Logs every decision and action to
evidence/discovery/<run_id>/.

Run with: python -m agent.discover --goal "..."
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import anthropic
from playwright.sync_api import sync_playwright

from agent.executor import ActionError, SafetyBlocked, execute_action
from agent.llm import decide_next_action
from agent.perception import capture_state
from safety.masking import mask, mask_url

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET_URL = "http://127.0.0.1:5000"
DEFAULT_MAX_STEPS = 10
EVIDENCE_ROOT = REPO_ROOT / "evidence" / "discovery"
# Set only in sandboxes that pre-install Chromium outside Playwright's usual
# cache (e.g. this dev container). On a machine with a normal
# `playwright install`, this path won't exist and we fall back to
# Playwright's default browser resolution.
_SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium")
CHROMIUM_EXECUTABLE = str(_SANDBOX_CHROMIUM) if _SANDBOX_CHROMIUM.exists() else None


def _is_reachable(url: str, timeout: float = 1.0) -> bool:
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except (urllib.error.URLError, OSError):
        return False


def _start_mock_bank(target_url: str) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "mock_bank.app"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    for _ in range(30):
        if _is_reachable(target_url):
            return proc
        time.sleep(0.5)
    proc.terminate()
    raise RuntimeError(f"mock_bank did not become reachable at {target_url} within 15s")


def _decision_to_locator(decision: dict) -> dict | None:
    action = decision.get("action")
    if action == "done":
        return None
    if action == "navigate":
        return {"strategy": "url", "value": decision.get("url", "")}
    if action == "extract":
        return {"strategy": "text", "value": decision.get("label", "")}
    return {"strategy": "role", "value": f"{decision.get('role', '')}:{decision.get('name', '')}"}


def _append_log(log_path: Path, entry: dict) -> None:
    with log_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _masked_log_entry(entry: dict) -> dict:
    """Same redaction replay/engine.py applies to its own logs (spec §9):
    member IDs/balances masked (last 4 chars visible) in anything written
    to evidence/discovery/, both in the decision that was made and in
    what executing it returned. Screenshots and the raw accessibility
    tree are the one exception -- like escalation's screenshots, they're
    an unavoidable literal capture of whatever's on screen, not a
    structured field this module can selectively redact."""
    masked = dict(entry)
    if "url_before" in masked:
        masked["url_before"] = mask_url(masked["url_before"])
    if "decision" in masked:
        decision = dict(masked["decision"])
        if decision.get("text") is not None:
            decision["text"] = mask(decision["text"])
        if decision.get("outputs"):
            decision["outputs"] = {k: mask(v) for k, v in decision["outputs"].items()}
        masked["decision"] = decision
    if "result" in masked:
        result = dict(masked["result"])
        if "value" in result:
            result["value"] = mask(result["value"])
        if "url_after" in result:
            result["url_after"] = mask_url(result["url_after"])
        masked["result"] = result
    return masked


def _masked_summary(summary: dict) -> dict:
    masked = dict(summary)
    masked["outputs"] = {k: mask(v) for k, v in summary["outputs"].items()}
    masked_trace = []
    for entry in summary["step_trace"]:
        entry = dict(entry)
        if entry.get("outputs"):
            entry["outputs"] = {k: mask(v) for k, v in entry["outputs"].items()}
        masked_trace.append(entry)
    masked["step_trace"] = masked_trace
    return masked


def run_discovery(goal: str, target_url: str = DEFAULT_TARGET_URL, max_steps: int = DEFAULT_MAX_STEPS) -> dict:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = EVIDENCE_ROOT / run_id
    screenshots_dir = run_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "steps.jsonl"
    summary_path = run_dir / "run_summary.json"

    mock_bank_proc = None
    if not _is_reachable(target_url):
        print(f"mock_bank not reachable at {target_url}; starting it as a subprocess...")
        mock_bank_proc = _start_mock_bank(target_url)

    client = anthropic.Anthropic()

    history = []
    step_trace = []
    extracted_outputs = {}
    reported_outputs = {}
    llm_call_count = 0
    success = False
    failure_reason = None
    blocked_by_safety = False
    step_count = 0

    try:
        with sync_playwright() as p:
            launch_kwargs = {"executable_path": CHROMIUM_EXECUTABLE} if CHROMIUM_EXECUTABLE else {}
            browser = p.chromium.launch(**launch_kwargs)
            page = browser.new_page(viewport={"width": 1024, "height": 768})
            page.goto(target_url)

            try:
                for step_index in range(max_steps):
                    step_count = step_index + 1
                    state = capture_state(page, screenshots_dir, step_index)

                    decision = decide_next_action(client=client, goal=goal, history=history, state=state)
                    llm_call_count += 1

                    log_entry = {
                        "step_index": step_index,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "url_before": state["url"],
                        "screenshot_path": str(state["screenshot_path"].relative_to(run_dir)),
                        "accessibility_tree": state["accessibility_tree"],
                        "decision": decision,
                    }
                    # One trace entry per step, whatever the outcome, so
                    # step_trace always has exactly `total_steps` entries and
                    # every action the agent took (including the terminal
                    # done/error step) is accounted for.
                    trace_entry = {
                        "step_id": f"step_{step_index}",
                        "action": decision["action"],
                        "locator": _decision_to_locator(decision),
                        "output_key": decision.get("output_key"),
                    }

                    if decision["action"] == "done":
                        success = bool(decision.get("goal_met"))
                        reported_outputs = decision.get("outputs", {}) or {}
                        log_entry["result"] = {"status": "done", "goal_met": success}
                        _append_log(log_path, _masked_log_entry(log_entry))
                        history.append(f"Step {step_index}: done (goal_met={success})")
                        trace_entry["status"] = "done"
                        trace_entry["outputs"] = reported_outputs
                        step_trace.append(trace_entry)
                        break

                    try:
                        result = execute_action(page, decision)
                        log_entry["result"] = {"status": "ok", **result}
                        _append_log(log_path, _masked_log_entry(log_entry))

                        target_desc = decision.get("name") or decision.get("url") or decision.get("label") or ""
                        history.append(f"Step {step_index}: {decision['action']} ({target_desc}) -> ok")

                        trace_entry["status"] = "ok"
                        step_trace.append(trace_entry)
                        if decision["action"] == "extract" and decision.get("output_key"):
                            extracted_outputs[decision["output_key"]] = result.get("value")

                    except SafetyBlocked as exc:
                        # Refused, never retried, never escalated to the
                        # LLM to "try again" -- a hard stop per spec §9.
                        log_entry["result"] = {"status": "blocked_by_safety", "reason": str(exc)}
                        _append_log(log_path, _masked_log_entry(log_entry))
                        history.append(f"Step {step_index}: {decision['action']} -> BLOCKED_BY_SAFETY: {exc}")
                        failure_reason = str(exc)
                        blocked_by_safety = True
                        trace_entry["status"] = "blocked_by_safety"
                        trace_entry["reason"] = str(exc)
                        step_trace.append(trace_entry)
                        break

                    except ActionError as exc:
                        log_entry["result"] = {"status": "error", "message": str(exc)}
                        _append_log(log_path, _masked_log_entry(log_entry))
                        history.append(f"Step {step_index}: {decision['action']} -> ERROR: {exc}")
                        failure_reason = str(exc)
                        trace_entry["status"] = "error"
                        trace_entry["error"] = str(exc)
                        step_trace.append(trace_entry)
                        break
                else:
                    failure_reason = f"max_steps ({max_steps}) exceeded without the agent reporting done"
            finally:
                browser.close()
    finally:
        if mock_bank_proc is not None:
            mock_bank_proc.terminate()
            mock_bank_proc.wait(timeout=5)

    # Extracted values (backed by a logged `extract` step) are trusted over
    # whatever the model additionally typed into `done`'s outputs by hand;
    # any key present only in the model's self-reported outputs had no
    # extract step behind it and is called out explicitly rather than
    # silently blended in as if it were verified.
    outputs = {**reported_outputs, **extracted_outputs}
    unverified_output_keys = sorted(set(reported_outputs) - set(extracted_outputs))

    summary = {
        "goal": goal,
        "target_url": target_url,
        "run_id": run_id,
        "success": success,
        "failure_reason": failure_reason,
        "blocked_by_safety": blocked_by_safety,
        "outputs": outputs,
        "verified_output_keys": sorted(extracted_outputs.keys()),
        "unverified_output_keys": unverified_output_keys,
        "total_steps": step_count,
        "llm_call_count": llm_call_count,
        "step_trace": step_trace,
    }
    # Persisted/printed copy is masked per spec §9; the raw dict returned
    # to the Python caller keeps real values in memory for this run only.
    masked_summary = _masked_summary(summary)
    summary_path.write_text(json.dumps(masked_summary, indent=2))
    print(json.dumps(masked_summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description="Run the discovery agent loop against the mock bank app.")
    parser.add_argument("--goal", default="search for member 10001 and read their savings balance.")
    parser.add_argument("--target-url", default=DEFAULT_TARGET_URL)
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    args = parser.parse_args()
    run_discovery(args.goal, args.target_url, args.max_steps)


if __name__ == "__main__":
    main()
