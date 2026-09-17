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
  label/value rows).
- `discover.py` — the loop itself: starts mock_bank as a subprocess if it's
  not already reachable at `--target-url`, runs up to `--max-steps`
  iterations, and logs every step to `evidence/discovery/<run_id>/`
  (`steps.jsonl` per-step log + screenshots + `run_summary.json` with a
  `step_trace` shaped close to `artifacts/schema.py`'s `Step`/`Locator`
  fields — artifact construction itself isn't wired up yet).

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
