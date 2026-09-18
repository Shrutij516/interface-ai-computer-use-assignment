"""Deterministic replay engine (spec §6/§7): re-runs a saved Artifact's
steps against a live Playwright page with no LLM calls, using only the
locator/fallback chains already recorded in the artifact. Logs every run
to evidence/replay/<run_id>/, same style as agent/discover.py.

Raw member IDs/balances are masked (last 4 chars visible) in everything
written to evidence/replay/ -- spec §9. The value returned to the Python
caller keeps the real value in memory for the duration of the run.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from artifacts.schema import Artifact, Checkpoint, FailureHandling, Locator, Step
from escalation import handoff, store as escalation_store
from replay.masking import mask

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET_URL = "http://127.0.0.1:5000"
EVIDENCE_ROOT = REPO_ROOT / "evidence" / "replay"

ACTION_TIMEOUT_MS = 2000
RETRY_WAIT_SECONDS = 1.0

# Page-content signals the engine recognizes independently of any single
# step's own on_failure classification -- a failed locator can mean the
# page structure broke (hard_failure) or it can mean the run reached a
# perfectly legitimate real-world outcome (business_outcome). Checked
# after every step, before any locator failure gets classified.
BUSINESS_OUTCOME_SIGNALS = [
    ("no member found", "not_found", "No member found for the given member ID."),
    ("permission denied", "permission_denied", "The operator account lacks permission for this action."),
    ("already exists", "duplicate_action", "The requested action was already performed (duplicate)."),
    ("already has", "duplicate_action", "The requested action was already performed (duplicate)."),
]

HARD_FAILURE_PAGE_SIGNALS = [
    "session expired",
    "please log in",
    "please sign in",
    "internal server error",
    "traceback (most recent call last)",
    "404 not found",
]


class HardFailure(Exception):
    def __init__(self, step_id: str, expected: str, observed: str):
        self.step_id = step_id
        self.expected = expected
        self.observed = observed


class LocatorNotFound(Exception):
    """All strategies in a locator's fallback chain failed to resolve."""


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


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _scan_for_page_signals(page: Page):
    """Independent business-outcome / unexpected-page detection based on
    page content. Returns (kind, which, details) or None."""
    text = page.locator("body").inner_text().lower()
    for phrase, which, details in BUSINESS_OUTCOME_SIGNALS:
        if phrase in text:
            return "business_outcome", which, details
    for phrase in HARD_FAILURE_PAGE_SIGNALS:
        if phrase in text:
            return "hard_failure", "unexpected_page", f"Page content matched hard-failure signal: {phrase!r}"
    return None


def _extract_by_label(page: Page, label: str) -> str:
    rows = page.locator("table tr")
    for i in range(rows.count()):
        cells = rows.nth(i).locator("td")
        if cells.count() < 2:
            continue
        if cells.nth(0).inner_text().strip() == label:
            return cells.nth(1).inner_text().strip()
    raise LocatorNotFound(f"no table row found with label {label!r}")


def _resolve_clickable(page: Page, locator: Locator):
    if locator.strategy == "role":
        role, _, name = locator.value.partition(":")
        target = page.get_by_role(role, name=name)
    elif locator.strategy == "text":
        target = page.get_by_text(locator.value, exact=True)
    elif locator.strategy == "css":
        target = page.locator(locator.value)
    elif locator.strategy == "xpath":
        target = page.locator(f"xpath={locator.value}")
    else:
        raise LocatorNotFound(f"unsupported strategy for click/type: {locator.strategy!r}")
    if target.count() == 0:
        raise LocatorNotFound(f"no element found for {locator.strategy}:{locator.value}")
    return target.first


def _match_input_value(locator: Locator, inputs: dict) -> str:
    """Type steps don't carry an explicit input binding in the artifact
    schema, so the target's accessible name (e.g. 'Member ID') is matched
    to an input parameter name (e.g. 'member_id') by normalizing both to
    lowercase alphanumerics. An ambiguous or missing match is a hard
    failure, not a guess."""
    _, _, accessible_name = locator.value.partition(":")
    normalized_target = _normalize(accessible_name or locator.value)
    matches = [k for k in inputs if _normalize(k) == normalized_target]
    if len(matches) != 1:
        raise LocatorNotFound(
            f"could not uniquely match type target {accessible_name!r} to one of inputs {list(inputs)}"
        )
    return str(inputs[matches[0]])


def _apply_strategy_once(page: Page, step: Step, locator: Locator, inputs: dict):
    """Attempt a single locator strategy exactly once. Returns None for
    click/navigate/wait, or the extracted string for extract/check/type.
    Raises PlaywrightTimeoutError / LocatorNotFound if this strategy alone
    can't find its target -- the caller decides retry/fallback. Raises
    HardFailure directly for conditions that retrying can't fix."""
    action = step.action

    if action == "navigate":
        response = page.goto(urljoin(page.url, locator.value), timeout=ACTION_TIMEOUT_MS)
        if response is not None and response.status >= 400:
            raise HardFailure(step.step_id, f"navigate to {locator.value} (2xx/3xx)", f"HTTP {response.status}")
        return None

    if action == "wait":
        pattern = f"**{locator.value}" if locator.value.startswith("/") else locator.value
        page.wait_for_url(pattern, timeout=ACTION_TIMEOUT_MS)
        return None

    if action == "click":
        _resolve_clickable(page, locator).click(timeout=ACTION_TIMEOUT_MS)
        page.wait_for_load_state("load")
        return None

    if action == "type":
        text_value = _match_input_value(locator, inputs)
        _resolve_clickable(page, locator).fill(text_value, timeout=ACTION_TIMEOUT_MS)
        return text_value

    if action in ("extract", "check"):
        if locator.strategy == "text":
            return _extract_by_label(page, locator.value)
        if locator.strategy == "css":
            el = page.locator(locator.value)
            if el.count() == 0:
                raise LocatorNotFound(f"no element matched css {locator.value!r}")
            return el.first.inner_text(timeout=ACTION_TIMEOUT_MS).strip()
        if locator.strategy == "xpath":
            el = page.locator(f"xpath={locator.value}")
            if el.count() == 0:
                raise LocatorNotFound(f"no element matched xpath {locator.value!r}")
            return el.first.inner_text(timeout=ACTION_TIMEOUT_MS).strip()
        raise LocatorNotFound(f"unsupported {action} strategy {locator.strategy!r}")

    raise HardFailure(step.step_id, "a supported action", f"unsupported action {action!r}")


def _run_step_with_recovery(page: Page, step: Step, inputs: dict, recovered_from: list):
    """Try the primary locator, retrying once on a timeout ('slow page
    load' -> recoverable), then the fallback the same way. Raises
    LocatorNotFound once the whole chain is exhausted, or HardFailure
    immediately for conditions retrying can't fix."""
    tried = []
    locator = step.locator
    while locator is not None:
        try:
            return _apply_strategy_once(page, step, locator, inputs)
        except (PlaywrightTimeoutError, LocatorNotFound) as exc:
            tried.append(f"{locator.strategy}:{locator.value} -> {exc}")
            time.sleep(RETRY_WAIT_SECONDS)
            try:
                result = _apply_strategy_once(page, step, locator, inputs)
                recovered_from.append(
                    {
                        "step_id": step.step_id,
                        "condition": "slow_page_load",
                        "note": f"Retried '{locator.strategy}:{locator.value}' once after a timeout; it succeeded.",
                    }
                )
                return result
            except (PlaywrightTimeoutError, LocatorNotFound) as exc2:
                tried.append(f"{locator.strategy}:{locator.value} (retry) -> {exc2}")
                locator = locator.fallback
    raise LocatorNotFound("; ".join(tried))


def _verify_checkpoint(page: Page, checkpoint: Checkpoint) -> tuple:
    probe_step = Step(
        step_id="checkpoint",
        action="extract",
        locator=checkpoint.locator,
        on_failure=FailureHandling(type="hard_failure", message="checkpoint failed"),
    )
    try:
        value = _run_step_with_recovery(page, probe_step, {}, [])
        return True, f"resolved value {mask(value)!r}"
    except LocatorNotFound as exc:
        return False, str(exc)


def _business_outcome_result(which: str, details: str, step_id: str, run_id: str) -> dict:
    return {"outcome": "business_outcome", "which": which, "details": details, "step_id": step_id, "run_id": run_id}


def _failure_result(artifact: Artifact, step_id: str, expected: str, observed: str, run_id: str) -> dict:
    return {
        "outcome": "failure",
        "capability_id": artifact.capability_id,
        "version": artifact.version,
        "run_id": run_id,
        "step_id": step_id,
        "expected": expected,
        "observed": observed,
    }


def _persist_result(result: dict, result_path: Path) -> None:
    """Write the result to disk with any outputs masked -- spec §9."""
    persisted = dict(result)
    if "outputs" in persisted:
        persisted["outputs"] = {k: mask(v) for k, v in persisted["outputs"].items()}
    result_path.write_text(json.dumps(persisted, indent=2))


def run_replay(
    artifact: Artifact,
    inputs: dict,
    target_url: str = DEFAULT_TARGET_URL,
    run_id: str = None,
    escalate: bool = True,
    escalation_poll_interval: float = 0.5,
    escalation_timeout: float = None,
) -> dict:
    """`escalate` gates spec §8: on a hard failure, pause the live browser
    (don't close it) and hand off to escalation/ instead of returning
    `failure` outright. Never triggered for `business_outcome` -- that's
    a legitimate answer, not a bug. Set False to get the raw, immediate
    failure result instead (e.g. for testing the replay loop in
    isolation)."""
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = EVIDENCE_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "steps.jsonl"
    result_path = run_dir / "replay_result.json"

    def _log(entry: dict) -> None:
        with log_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    extract_steps = [s for s in artifact.steps if s.action == "extract"]
    if len(extract_steps) != len(artifact.outputs):
        raise NotImplementedError(
            f"{artifact.capability_id} has {len(extract_steps)} extract step(s) but "
            f"{len(artifact.outputs)} declared output(s); the schema has no explicit "
            "step->output binding yet, so 1:1 positional matching is the only mapping "
            "implemented here -- add an explicit output_key to Step before replaying "
            "an artifact with a different shape."
        )

    _log(
        {
            "event": "run_started",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "capability_id": artifact.capability_id,
            "version": artifact.version,
            "inputs_masked": {k: mask(v) for k, v in inputs.items()},
        }
    )

    recovered_from = []
    extracted = {}

    mock_bank_proc = None
    if not _is_reachable(target_url):
        mock_bank_proc = _start_mock_bank(target_url)

    def _on_dialog(dialog) -> None:
        recovered_from.append(
            {"step_id": None, "condition": "unexpected_dialog", "note": f"Dismissed unexpected dialog: {dialog.message!r}"}
        )
        dialog.dismiss()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1024, "height": 768})
            page.on("dialog", _on_dialog)
            page.goto(target_url)

            def _handle_hard_failure(step_id: str, expected: str, observed: str) -> dict:
                if not escalate:
                    result = _failure_result(artifact, step_id, expected, observed, run_id)
                    _persist_result(result, result_path)
                    return result

                _log(
                    {
                        "event": "escalating",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "step_id": step_id,
                        "expected": expected,
                        "observed": observed,
                    }
                )

                resolved = handoff.pause_and_handoff(
                    page=page,
                    capability_id=artifact.capability_id,
                    version=artifact.version,
                    run_id=run_id,
                    step_id=step_id,
                    expected=expected,
                    observed=observed,
                    inputs_masked={k: mask(v) for k, v in inputs.items()},
                    poll_interval=escalation_poll_interval,
                    timeout=escalation_timeout,
                )
                _log(
                    {
                        "event": "resumed",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "request_id": resolved["request_id"],
                        "manual_action": resolved.get("manual_action"),
                        "resolution_note": resolved.get("resolution_note"),
                    }
                )

                checkpoint_ok, checkpoint_observed = _verify_checkpoint(page, artifact.checkpoint)
                if checkpoint_ok:
                    for s in extract_steps:
                        output_name = artifact.outputs[extract_steps.index(s)].name
                        if output_name in extracted:
                            continue
                        try:
                            extracted[output_name] = _run_step_with_recovery(page, s, inputs, recovered_from)
                        except LocatorNotFound as exc:
                            checkpoint_ok = False
                            checkpoint_observed = f"post-handoff extract for step {s.step_id} still failed: {exc}"
                            break

                _log(
                    {
                        "event": "checkpoint_after_handoff",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "result": {"status": "ok" if checkpoint_ok else "hard_failure", "observed": checkpoint_observed},
                    }
                )

                final_outcome = "success" if checkpoint_ok else "failure"
                escalation_store.finalize(resolved["request_id"], final_outcome, checkpoint_observed)

                if checkpoint_ok:
                    result = {
                        "outcome": "success",
                        "capability_id": artifact.capability_id,
                        "version": artifact.version,
                        "run_id": run_id,
                        "outputs": extracted,
                        "recovered_from": recovered_from,
                        "escalation": {
                            "request_id": resolved["request_id"],
                            "manual_action": resolved.get("manual_action"),
                            "resolution_note": resolved.get("resolution_note"),
                        },
                    }
                else:
                    result = _failure_result(artifact, step_id, expected, checkpoint_observed, run_id)
                    result["escalation"] = {"request_id": resolved["request_id"], "resolution_note": resolved.get("resolution_note")}
                _persist_result(result, result_path)
                return result

            try:
                for step_index, step in enumerate(artifact.steps):
                    entry = {
                        "step_index": step_index,
                        "step_id": step.step_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "action": step.action,
                        "locator": {"strategy": step.locator.strategy, "value": step.locator.value},
                        "url_before": page.url,
                    }

                    try:
                        result_value = _run_step_with_recovery(page, step, inputs, recovered_from)
                    except HardFailure as hf:
                        entry["result"] = {"status": "hard_failure", "expected": hf.expected, "observed": hf.observed}
                        _log(entry)
                        return _handle_hard_failure(hf.step_id, hf.expected, hf.observed)
                    except LocatorNotFound as exc:
                        entry["result"] = {"status": "hard_failure", "message": str(exc)}
                        _log(entry)
                        return _handle_hard_failure(
                            step.step_id,
                            f"locator (and fallback) for {step.action} step to resolve: "
                            f"{step.locator.strategy}:{step.locator.value}",
                            str(exc),
                        )

                    if step.action == "type" and result_value is not None:
                        entry["result"] = {"status": "ok", "typed_value_masked": mask(result_value)}
                    elif step.action == "extract" and result_value is not None:
                        output_name = artifact.outputs[extract_steps.index(step)].name
                        extracted[output_name] = result_value
                        entry["result"] = {"status": "ok", "extracted_value_masked": mask(result_value)}
                    else:
                        entry["result"] = {"status": "ok"}
                    _log(entry)

                    signal = _scan_for_page_signals(page)
                    if signal is not None:
                        kind, which, details = signal
                        _log(
                            {
                                "step_index": step_index,
                                "step_id": step.step_id,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "signal_check": {"kind": kind, "which": which, "details": details},
                            }
                        )
                        if kind == "business_outcome":
                            result = _business_outcome_result(which, details, step.step_id, run_id)
                            _persist_result(result, result_path)
                            return result
                        return _handle_hard_failure(step.step_id, "no hard-failure page signal present", details)

                checkpoint_ok, checkpoint_observed = _verify_checkpoint(page, artifact.checkpoint)
                _log(
                    {
                        "checkpoint": True,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "result": {"status": "ok" if checkpoint_ok else "hard_failure", "observed": checkpoint_observed},
                    }
                )
                if not checkpoint_ok:
                    return _handle_hard_failure("checkpoint", artifact.checkpoint.description, checkpoint_observed)
            finally:
                browser.close()
    finally:
        if mock_bank_proc is not None:
            mock_bank_proc.terminate()
            mock_bank_proc.wait(timeout=5)

    result = {
        "outcome": "success",
        "capability_id": artifact.capability_id,
        "version": artifact.version,
        "run_id": run_id,
        "outputs": extracted,
        "recovered_from": recovered_from,
    }
    _persist_result(result, result_path)
    return result
