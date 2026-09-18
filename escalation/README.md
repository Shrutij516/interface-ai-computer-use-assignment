# escalation

Escalation & handoff on a hard failure (spec §8) -- never triggered by
`business_outcome`, which is a legitimate answer, not a bug.

- `store.py` -- file-based storage for intervention requests
  (`requests/<request_id>.json`) and their handoff logs
  (`requests/<request_id>_log.json`). The request's `status` field
  (`pending` -> `resolved`) is the signal between the paused replay
  process and the operator surface; they can be, and in a real
  deployment would be, separate processes.
- `handoff.py` -- `pause_and_handoff(page, ...)` is the real mechanism:
  called from `replay/engine.py` while still inside the live Playwright
  session, it screenshots the page, writes the request, and blocks
  (polling the request file) on the *same thread that owns `page`* --
  which is the "pause": nothing about the browser or session is touched,
  closed, or reconnected while this runs. Once a human resolves the
  request, if they described a `manual_action` (what they did on the
  live page), this module carries it out for real against that same
  `page` before returning control.
- `operator_app.py` -- the mocked half. A minimal Flask app
  (`python -m escalation.operator_app`, port 5050) listing pending
  requests, showing the screenshot + expected/observed context for one,
  and a form to mark it resolved. Per spec §8 the co-browsing UI is
  intentionally out of scope; on a real (headed) run, a human doesn't
  need this app to touch the browser at all -- they can see and use the
  actual open browser window directly, then come here just to say "done".
  The `manual_action` field exists for cases (like this project's
  sandboxed test) where nobody has a real screen to click through, so
  the fix still happens for real on the live session rather than being
  skipped.

## What "resume" actually does

`replay/engine.py`'s `_handle_hard_failure` (used by every one of its
four hard-failure sites -- a raised `HardFailure`, an exhausted locator
fallback chain, a hard-failure page signal, and a failed checkpoint) is
the one thing that runs after `pause_and_handoff` returns:

1. Re-verify `artifact.checkpoint` against the page's *current* state.
2. If it holds, run any `extract` steps that never got to complete and
   populate their outputs -- resuming isn't declaring victory, it's
   actually finishing the job.
3. If it still doesn't hold, that's a real `failure`, reported with the
   escalation's `request_id` attached, not a second silent retry loop.

## Test

Injects a real failure into a copy of the evidence-backed
`lookup_member_balance` v1.1.0 artifact (corrupts the "click Search"
step's locator to a nonexistent button) and replays it for a real member
(`10001`) who would otherwise succeed. Runs the replay on a background
thread so it can genuinely block in `pause_and_handoff`'s wait loop while
the main thread plays the operator: polls for the resulting pending
request, then calls `store.mark_resolved(...)` with a `manual_action`
describing the real fix (click the Search button that's actually there).
Confirms: the request reaches `resolved`, the same live session completes
the run, `savings_balance` matches the known-good value, and the handoff
log has exactly the three events `paused` / `human_took_over` /
`control_returned`.

```
python -m escalation.test_escalation
```

Note: unlike the JSON logs, the saved screenshot is not masked -- it's a
literal image of whatever was on screen (here, the real member ID typed
into the search box), because an operator resolving a real incident
needs to see the real page. This is the same tradeoff a human-in-the-loop
system always makes: whoever is trusted to fix the problem is trusted to
see the problem.
