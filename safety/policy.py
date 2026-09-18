"""Safety & allowlist enforcement (spec §9). One shared implementation,
imported by both agent/executor.py (discovery) and replay/engine.py
(replay), so the two paths can't drift into different rules. Checked
before every single action, not once at process start.

Two independent gates:
  1. Allowlist -- action type must be one of the four spec permits
     (click, type, navigate, extract), and every URL the action touches
     must be under an allowed base URL (mock bank's local URL only).
  2. Risk gate -- a click/navigate whose real destination is a known
     irreversible route (e.g. mock_bank's sub-account confirm endpoint)
     is refused unless the page currently on screen shows a genuine
     confirmation/review screen. Never auto-confirmed: the check reads
     the live page, not a flag some earlier step set.
"""

from __future__ import annotations

ALLOWED_BASE_URLS = ["http://127.0.0.1:5000"]

# Exactly the four action types spec §9 names. Note this is narrower
# than artifacts/schema.py's Step.action, which also allows "wait" and
# "check" (used only by test_roundtrip.py's hand-built, never-replayed
# v1.0.0 fixture -- see artifacts/README.md). A real artifact built from
# a discovery run (e.g. lookup_member_balance v1.1.0) never emits those,
# so this doesn't affect anything actually replayed today; an artifact
# that did use them would be refused here, which is the locked spec's
# literal allowlist working as intended, not a bug to route around.
ALLOWED_ACTIONS = {"click", "type", "navigate", "extract"}

# Route suffixes known to cause an irreversible state change in
# mock_bank. Checked against the *actual* destination a click/navigate
# resolves to (a clicked element's closest <form action> or href, or a
# navigate step's target) -- not the button's visible label, which could
# drift without the route changing.
RISKY_ROUTE_SUFFIXES = ["/subaccounts/confirm"]

# Page-content signals that the confirmation/review screen is genuinely
# showing right now. mock_bank/templates/open_subaccount_confirm.html's
# own heading.
CONFIRMATION_PAGE_SIGNALS = ["confirm sub-account details"]


class SafetyViolation(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def check_allowlist(action: str, current_url: str, destination_url: str = None) -> None:
    if action not in ALLOWED_ACTIONS:
        raise SafetyViolation(f"action type {action!r} is not on the allowlist ({sorted(ALLOWED_ACTIONS)})")
    for url in (u for u in (current_url, destination_url) if u):
        if not any(url.startswith(base) for base in ALLOWED_BASE_URLS):
            raise SafetyViolation(f"URL {url!r} is outside the allowed domains ({ALLOWED_BASE_URLS})")


def is_risky_route(url: str) -> bool:
    if not url:
        return False
    stripped = url.rstrip("/")
    return any(stripped.endswith(suffix) for suffix in RISKY_ROUTE_SUFFIXES)


def check_risky_action_confirmed(page_text: str) -> None:
    """Hard stop, not a warning: refuses a risky action unless the
    confirmation screen is actually showing on the page right now."""
    text = (page_text or "").lower()
    if not any(signal in text for signal in CONFIRMATION_PAGE_SIGNALS):
        raise SafetyViolation(
            "risky/irreversible action attempted without first reaching and showing a confirmation "
            "screen -- refused (never auto-confirmed)"
        )


def resolve_click_destination(locator) -> str:
    """Given a resolved Playwright locator about to be clicked, returns
    the real URL it will submit/navigate to (its enclosing form's action,
    or its own href), or None if it's neither (e.g. a plain button with
    no navigation effect, like 'Search' triggers via its own form)."""
    try:
        return locator.evaluate(
            "el => { const f = el.closest('form'); if (f && f.action) return f.action; "
            "if (el.href) return el.href; return null; }"
        )
    except Exception:
        return None
