"""Executes a single decided action against the live Playwright page.

Every action funnels through here on its way from an LLM decision to the
live page, so this is where safety.policy's allowlist + risk gate is
enforced for discovery -- the same check replay/engine.py runs for every
step, imported from the same module so the two can't drift apart.
"""

from urllib.parse import urljoin

from playwright.sync_api import Page

from safety import policy as safety


class ActionError(Exception):
    """Raised when an action's target cannot be found or executed."""


class SafetyBlocked(ActionError):
    """Raised when safety.policy refuses an action outright (outside the
    allowlist, or a risky action attempted without a confirmed
    checkpoint). A hard stop, not a warning -- never retried, never
    auto-approved."""


def execute_action(page: Page, decision: dict) -> dict:
    action = decision["action"]

    if action == "navigate":
        url = decision.get("url")
        if not url:
            raise ActionError("navigate action missing 'url'")
        destination = urljoin(page.url, url)
        _enforce_safety(page, action, destination_url=destination)
        page.goto(destination)
        return {"url_after": page.url}

    if action == "click":
        _enforce_safety(page, action)
        locator = _locate(page, decision)
        destination = safety.resolve_click_destination(locator)
        if safety.is_risky_route(destination):
            _check_risky_confirmed(page)
        locator.click()
        page.wait_for_load_state("load")
        return {"url_after": page.url}

    if action == "type":
        _enforce_safety(page, action)
        locator = _locate(page, decision)
        text = decision.get("text")
        if text is None:
            raise ActionError("type action missing 'text'")
        locator.fill(text)
        return {"url_after": page.url}

    if action == "extract":
        _enforce_safety(page, action)
        label = decision.get("label")
        if not label:
            raise ActionError("extract action missing 'label'")
        value = _extract_labeled_value(page, label)
        return {"value": value}

    raise ActionError(f"unknown action: {action}")


def _enforce_safety(page: Page, action: str, destination_url: str = None) -> None:
    try:
        safety.check_allowlist(action, page.url, destination_url)
        if destination_url and safety.is_risky_route(destination_url):
            _check_risky_confirmed(page)
    except safety.SafetyViolation as exc:
        raise SafetyBlocked(str(exc)) from exc


def _check_risky_confirmed(page: Page) -> None:
    try:
        safety.check_risky_action_confirmed(page.locator("body").inner_text())
    except safety.SafetyViolation as exc:
        raise SafetyBlocked(str(exc)) from exc


def _locate(page: Page, decision: dict):
    role = decision.get("role")
    name = decision.get("name")
    if not role or not name:
        raise ActionError(f"{decision.get('action')} action missing 'role' or 'name'")
    locator = page.get_by_role(role, name=name)
    if locator.count() == 0:
        raise ActionError(f"no element found with role={role!r} name={name!r}")
    return locator.first


def _extract_labeled_value(page: Page, label: str) -> str:
    """Find a table row whose first cell equals `label` and return the text
    of that row's second cell. Matches the label/value table-row pattern
    used by legacy back-office screens (and mock_bank's detail page)."""
    rows = page.locator("table tr")
    for i in range(rows.count()):
        cells = rows.nth(i).locator("td")
        if cells.count() < 2:
            continue
        if cells.nth(0).inner_text().strip() == label:
            return cells.nth(1).inner_text().strip()
    raise ActionError(f"no table row found with label {label!r}")
