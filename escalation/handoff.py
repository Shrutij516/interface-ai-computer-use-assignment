"""The real half of escalation & handoff (spec §8): pausing a live replay
on a live Playwright page, blocking until a human resolves the
intervention request, optionally carrying out a described manual action
on that same session, and handing control back. Everything about the
operator's *interface* is mocked (escalation/operator_app.py, or a test
calling store.mark_resolved directly) -- this module is what makes the
pause/handoff/resume itself real: the same `page` object is held the
whole time, nothing about the session is torn down or reconnected.

KNOWN, DELIBERATE PII TRADE-OFF -- read before reusing this screenshot
mechanism anywhere real: pause_and_handoff() below saves an *unmasked*
screenshot of the live page (escalation/screenshots/<request_id>.png)
and references it, unmasked, from the intervention request JSON
(escalation/requests/<request_id>.json). This is intentional, not an
oversight: an operator trying to diagnose a broken locator needs to see
the actual page (the real member ID, the real balance) to fix it --
masking the screenshot would defeat the point of showing it. This is
different from every other artifact this project writes to disk
(evidence/replay/'s steps.jsonl and replay_result.json, and this same
request JSON's own inputs_masked field), which mask member IDs/balances
per spec §9 precisely because they're meant to be safe to keep long-term
or commit to a general-purpose repo.

A production version of this mechanism would need to split these two
concerns instead of writing both to the same repo-committable directory:
  - The masked JSON logs (request metadata, handoff log, replay traces)
    can stay long-retention and are safe to commit/ship as evidence.
  - The unmasked screenshot must instead go to a separate,
    access-controlled, short-retention store (e.g. an encrypted bucket
    with a lifecycle policy measured in hours/days and audit-logged
    reads limited to on-call operators) -- never alongside the masked
    logs, and never in a general-purpose source repo. This project keeps
    them side by side under evidence/ and escalation/ purely because
    it's a take-home assignment demonstrating the mechanism, not a
    system handling real member data.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from playwright.sync_api import Page

from escalation import store


def _apply_manual_action(page: Page, manual_action: dict) -> None:
    """Carries out a human-described corrective action on the live page.
    Deliberately small: only what a mocked operator surface can plausibly
    describe without a real co-browsing UI (spec §8 says the interface is
    mocked, not the session it acts on)."""
    action = manual_action.get("action")
    strategy = manual_action.get("strategy")
    value = manual_action.get("value")

    if strategy == "role":
        role, _, name = value.partition(":")
        target = page.get_by_role(role, name=name)
    elif strategy == "text":
        target = page.get_by_text(value, exact=True)
    elif strategy == "css":
        target = page.locator(value)
    else:
        raise ValueError(f"unsupported manual_action strategy: {strategy!r}")

    if action == "click":
        target.first.click()
        page.wait_for_load_state("load")
    elif action == "type":
        target.first.fill(manual_action.get("text", ""))
    else:
        raise ValueError(f"unsupported manual_action action: {action!r}")


def pause_and_handoff(
    page: Page,
    capability_id: str,
    version: str,
    run_id: str,
    step_id: str,
    expected: str,
    observed: str,
    inputs_masked: dict,
    poll_interval: float = 0.5,
    timeout: float = None,
) -> dict:
    """Writes the intervention request + screenshot, then blocks (the
    live browser stays open -- this call runs on the same thread that
    owns `page`, so nothing else can touch it, which is exactly the
    'pause') until a human calls store.mark_resolved for this request.
    If they described a manual_action, it's carried out on this same
    live page before control returns to the caller.

    Returns the resolved request dict. Raises store.ResolutionTimeout if
    `timeout` is given and nobody resolves it in time.
    """
    request_id = f"esc_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}Z_{uuid.uuid4().hex[:6]}"

    store.SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    screenshot_path = store.SCREENSHOTS_DIR / f"{request_id}.png"
    page.screenshot(path=str(screenshot_path))

    store.create_request(
        request_id=request_id,
        capability_id=capability_id,
        version=version,
        run_id=run_id,
        step_id=step_id,
        expected=expected,
        observed=observed,
        screenshot_path=str(screenshot_path.relative_to(store.REPO_ROOT)),
        inputs_masked=inputs_masked,
    )

    resolved = store.wait_for_resolution(request_id, poll_interval=poll_interval, timeout=timeout)

    if resolved.get("manual_action"):
        _apply_manual_action(page, resolved["manual_action"])

    return resolved
