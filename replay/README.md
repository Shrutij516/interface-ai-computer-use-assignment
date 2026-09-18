# replay

Deterministic replay engine: re-runs a saved artifact against the live
surface without the LLM in the decision loop, using stable element/control
targeting, verifying the checkpoint, and returning one of three outcomes
(spec §6): `success` (optionally with `recovered_from`), `business_outcome`,
or `failure`.

`engine.py`'s `run_replay(artifact, inputs, target_url=..., run_id=None)`:

- Loads no LLM. Walks `artifact.steps` in order; for each step, tries the
  primary `locator`, then `locator.fallback` if the primary can't be
  resolved.
- After every step, independently scans the resulting page's content for
  known business-outcome signals ("No member found", "Permission denied",
  "already exists", ...) and known hard-failure signals ("session
  expired", "internal server error", ...) -- this is separate from
  whatever `on_failure` a step declares, since an artifact recorded from
  one successful run has no idea what a not-found page looks like.
- A timeout on a locator is treated as "slow page load": wait one second
  and retry that exact strategy once before moving to the fallback,
  logging the retry under `recovered_from`. An unexpected native dialog
  is auto-dismissed the same way. If the whole fallback chain (with
  retries) is exhausted, that's a hard failure with the step id, what
  locator was expected, and what was actually observed.
- After all steps run, `artifact.checkpoint`'s locator is verified before
  any outputs are trusted -- a checkpoint that fails to resolve is a hard
  failure even if every step reported `ok`.
- Before every action, `safety.policy` (spec §9) checks the action type
  and URL against the allowlist, and, for a click/navigate whose real
  destination is a known irreversible route, that the current page
  actually shows a confirmation screen -- never auto-confirmed. A
  refusal is a hard stop returned as `{"outcome": "failure",
  "blocked_by_safety": true, ...}` and does **not** go through
  escalation (a human "resolving" a safety block would defeat the
  point). See `safety/README.md`.
- On a hard failure (from any of the four sites above -- distinct from a
  safety refusal), control passes to `escalation/` (spec §8) instead of
  returning `failure` immediately: the live browser is paused, not
  closed, and a human gets a chance to fix it on that same session
  before the run is actually reported as failed. Set `escalate=False` to
  skip this and get the raw failure result instead. Never triggered for
  `business_outcome` -- see `escalation/README.md`.
- Every run's full trace is logged to `evidence/replay/<run_id>/`
  (`steps.jsonl` + `replay_result.json`), same style as
  `agent/discover.py`'s discovery logging. Per spec §9, member IDs and
  balances (`safety/masking.py`'s `mask()`, shared with `agent/`) are
  masked (last 4 characters visible) in everything written to disk,
  including member IDs embedded in logged URLs (`mask_url()`); the real
  values only exist in the dict `run_replay` returns to its Python
  caller, for the duration of that call.

**Known schema gaps** (worth closing before a second capability exists):
`Step` has no field for which input parameter a `type` step should fill,
or which output an `extract` step's value belongs to. The engine works
around this today by (1) matching a `type` step's target accessible name
to an input parameter name after stripping case/punctuation (e.g.
"Member ID" -> `member_id`), and (2) requiring exactly as many `extract`
steps as declared outputs and binding them positionally. Both raise a
clear error rather than guessing if that 1:1 assumption doesn't hold.

## Replay check

No LLM, no discovery loop -- replays the real `lookup_member_balance`
v1.1.0 artifact (from `evidence/discovery/20260918T035315Z/`) against a
live mock_bank, once with a known member ID (expect `success`) and once
with mock_bank's documented not-found ID (expect `business_outcome`):

```
python -m replay.test_replay
```
