"""Executes a single decided action against the live Playwright page."""

from urllib.parse import urljoin

from playwright.sync_api import Page


class ActionError(Exception):
    """Raised when an action's target cannot be found or executed."""


def execute_action(page: Page, decision: dict) -> dict:
    action = decision["action"]

    if action == "navigate":
        url = decision.get("url")
        if not url:
            raise ActionError("navigate action missing 'url'")
        page.goto(urljoin(page.url, url))
        return {"url_after": page.url}

    if action == "click":
        locator = _locate(page, decision)
        locator.click()
        page.wait_for_load_state("load")
        return {"url_after": page.url}

    if action == "type":
        locator = _locate(page, decision)
        text = decision.get("text")
        if text is None:
            raise ActionError("type action missing 'text'")
        locator.fill(text)
        return {"url_after": page.url}

    if action == "extract":
        label = decision.get("label")
        if not label:
            raise ActionError("extract action missing 'label'")
        value = _extract_labeled_value(page, label)
        return {"value": value}

    raise ActionError(f"unknown action: {action}")


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
