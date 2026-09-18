# agent

The LLM-driven discovery loop: observe → decide → act against a live
mock_bank instance (spec §2, §4). Uses an ARIA accessibility-tree snapshot
as the primary signal, a screenshot as backup, per iteration.

- `perception.py` — `capture_state(page, ...)`: ARIA snapshot (via
  Playwright's `locator("body").aria_snapshot()`) + a screenshot.
- `llm.py` — `decide_next_action(...)`: one Claude API call per step, forced
  tool use (`decide_next_action`), returns exactly one of
  click/type/navigate/extract/done.
- `executor.py` — `execute_action(page, decision)`: runs the decided action
  via Playwright (`get_by_role` for click/type; a label→adjacent-cell walk
  over `<table><tr><td>` for extract, matching mock_bank's legacy
  label/value rows). Every action goes through `safety.policy`'s
  allowlist + risk gate first (spec §9) — the same shared check
  `replay/engine.py` runs, not a separate implementation. A refusal
  raises `SafetyBlocked`, which `discover.py` logs as
  `status: "blocked_by_safety"` and treats as a hard stop, never a retry.
  See `safety/README.md`.
- `discover.py` — the loop itself: starts mock_bank as a subprocess if it's
  not already reachable at `--target-url`, runs up to `--max-steps`
  iterations, and logs every step to `evidence/discovery/<run_id>/`
  (`steps.jsonl` per-step log + screenshots + `run_summary.json` with a
  `step_trace` shaped close to `artifacts/schema.py`'s `Step`/`Locator`
  fields — artifact construction itself isn't wired up yet). `step_trace`
  has exactly one entry per step, including the terminal `done`/error step
  (`status` is `ok`/`done`/`error`), so its length always equals
  `total_steps`. The `done` step's self-reported `outputs` are not blindly
  trusted: `run_summary.json` also reports `verified_output_keys` (backed by
  a logged `extract` step) and `unverified_output_keys` (present only
  because the model typed them into `done`, e.g. a value it read off the
  same page without a dedicated extract call). Per spec §9, member
  IDs/balances are masked (last 4 characters visible) in both
  `steps.jsonl` and `run_summary.json` — the decision's typed `text`,
  any extracted/reported output values, and member IDs embedded in
  logged URLs. The raw values only exist in the dict `run_discovery`
  returns to its Python caller, for the duration of that call. The one
  exception is the raw accessibility-tree snapshot and screenshots,
  which necessarily show whatever's really on screen (same tradeoff as
  `escalation/`'s screenshots — see `escalation/handoff.py`'s docstring).

No thinking (adaptive thinking is disabled for this call — it's a single
bounded decision, not a reasoning task, and disabling it keeps forced tool
use unambiguous and cheap).

## Run it

```
python -m agent.discover --goal "search for member 10001 and read their savings balance."
```

Requires `ANTHROPIC_API_KEY` in the environment. Optional flags:
`--target-url` (default `http://127.0.0.1:5000`), `--max-steps` (default
10). mock_bank is started automatically as a subprocess if nothing is
already listening on `--target-url`.
