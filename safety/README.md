# safety

Explicit safety/allowlist enforcement (spec §9). One shared
implementation, imported by both `agent/executor.py` (discovery) and
`replay/engine.py` (replay) -- and by `escalation/handoff.py`'s
manual-action execution too (see below) -- so there's exactly one place
that could get this wrong, not three that could quietly drift apart.

- `policy.py` -- `check_allowlist(action, current_url, destination_url)`
  refuses any action type outside `{click, type, navigate, extract}` or
  any URL outside `ALLOWED_BASE_URLS` (mock bank's local URL only).
  `is_risky_route(url)` / `check_risky_action_confirmed(page_text)` are
  the risk gate: a click or navigate whose *real* destination (a clicked
  element's resolved `<form action>`/`href`, not its visible label) is
  mock_bank's sub-account confirm route is refused unless the current
  page already shows the confirmation screen. This is a hard stop, not a
  warning -- it raises `SafetyViolation` and nothing downstream is meant
  to catch and retry it.
- `masking.py` -- `mask()` (moved here from `replay/masking.py`, now
  shared) and a new `mask_url()`, which masks member-ID-shaped path
  segments in logged URLs (e.g. `/members/10001` -> `/members/*0001`).
  Added because auditing this task surfaced that both `replay/engine.py`
  and `agent/discover.py` were logging full URLs -- including the member
  ID in the path -- right next to an already-masked balance field.

## Checked before every action, not once at the start

- `replay/engine.py`'s `_apply_strategy_once` calls `check_allowlist`
  (all four action types) and, for click/navigate, the risk gate --
  inline, per step, before the action runs. A `SafetyViolation` is
  caught separately from `HardFailure`/`LocatorNotFound` in the main
  loop and returns `{"outcome": "failure", "blocked_by_safety": true,
  ...}` directly. **It deliberately does not go through
  `escalation/`'s pause-and-resume**: routing a safety refusal through
  the same mechanism that lets a human describe a `manual_action` would
  let a "resolve" bypass the very allowlist/confirmation gate it just
  blocked. A safety violation is refused, full stop.
- `agent/executor.py`'s `execute_action` -- the one function
  `agent/discover.py` calls for every action -- runs the identical
  checks and raises `SafetyBlocked` (an `ActionError` subclass).
  `agent/discover.py` catches it ahead of the generic `ActionError`
  branch and logs `status: "blocked_by_safety"` instead of `"error"`,
  without retrying or asking the LLM to try again.
- `escalation/handoff.py`'s `_apply_manual_action` also runs the same
  gate before carrying out an operator's described fix. This wasn't
  asked for directly, but leaving it out would have been a real
  loophole: a human "resolving" a paused run is still taking a real
  action on the live session, and a `manual_action` that skipped the
  gate could push through exactly the risky action a safety refusal had
  just stopped.

## A known tension worth naming

`ALLOWED_ACTIONS` is exactly spec §9's four action types
(click/type/navigate/extract). `artifacts/schema.py`'s `Step.action`
also allows `wait` and `check`, used only by `test_roundtrip.py`'s
hand-built, never-replayed `lookup_member_balance` v1.0.0 fixture (see
`artifacts/README.md`). Replaying that artifact for real would now be
refused at its `wait`/`check` steps. Nothing in this project actually
does that -- the real, evidence-backed v1.1.0 artifact only ever uses
type/click/extract -- so this doesn't change any real behavior, but it's
the locked spec's literal allowlist working as intended, not a gap to
quietly paper over by widening it.

## Test

Proves both required scenarios, without needing an LLM/API key for the
discovery-side half (it calls `agent/executor.execute_action` directly,
the exact function `agent/discover.py` calls for every action):

- **(a)** A navigate to a domain other than mock_bank's is refused on
  both paths -- directly via `execute_action`, and via
  `replay.engine.run_replay` on a synthetic artifact, where the refusal
  is also confirmed written to `evidence/replay/<run_id>/steps.jsonl`
  with `status: "blocked_by_safety"`.
- **(b)** mock_bank's one irreversible action -- POSTing to
  `/subaccounts/confirm`, which actually creates the sub-account --
  attempted cold, via a synthetic artifact whose only step targets that
  route directly from a fresh page (no prior review screen), is refused
  as a hard stop rather than silently auto-confirmed.

```
python -m safety.test_safety
```
