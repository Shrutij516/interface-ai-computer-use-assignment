# artifacts

Artifact schema and storage for recorded capabilities (spec §5), as
Pydantic models in `schema.py`:

- `Artifact` — `capability_id`, `version`, `description`, `inputs`,
  `outputs` (typed `ParameterSpec` lists), `steps`, `checkpoint`.
- `Step` — `step_id`, `action` (navigate/click/type/extract/wait/check),
  `locator`, `on_failure`, optional `expected_signals`.
- `Locator` — `strategy` (role/text/css/xpath/url), `value`, optional
  recursive `fallback`.
- `FailureHandling` — `type` (`hard_failure` / `recoverable` /
  `business_outcome`), `message`, per the spec §7 error taxonomy.
- `Checkpoint` — `description`, `locator`, optional `expected_signals`.

`store.py` has `save_artifact` / `load_artifact`, which read/write JSON
files under `capabilities/` (filename: `<capability_id>__v<version>.json`).

## Which `lookup_member_balance` version is real

`capabilities/` currently holds two versions of the same capability_id —
they are not a superseded-vs-current pair, they're different kinds of
artifact entirely:

- **`v1.0.0`** is a hand-built schema test fixture, written directly in
  `test_roundtrip.py` to exercise the `Artifact` model's shape. It is
  never run for real: its 7 steps and its `found` / `member_name` /
  `savings_balance` outputs were typed by a developer, not observed from
  a live page. Running `python -m artifacts.test_roundtrip` regenerates
  and overwrites this file every time — treat it as disposable schema
  scaffolding, not evidence.
- **`v1.1.0`** is the real, evidence-backed capability, produced by
  `from_discovery.py`'s `discovery_run_to_artifact()` from an actual
  LLM-driven discovery run (`evidence/discovery/20260918T035315Z/`). Its
  3 steps and single `savings_balance` output are exactly what that run
  did and verified — nothing hand-added. `member_id` and `member_name`
  are deliberately absent from its outputs because the run's own
  `unverified_output_keys` marked them as model-reported, not backed by
  an `extract` step.

When in doubt about which one to treat as "the" capability going
forward, it's `v1.1.0`. `v1.0.0` stays only to keep exercising the
schema round-trip.

## Building an artifact from a discovery run

`from_discovery.py`'s `discovery_run_to_artifact(run_summary,
capability_id, version)` converts a completed discovery run's
`step_trace` + `outputs` (see `agent/discover.py`) into an `Artifact`:

- Each `step_trace` entry becomes a `Step`, except the terminal `done`
  entry — it has no locator and isn't one of the schema's action types,
  so it's dropped rather than force-fit.
- Only outputs backed by a logged `extract` step (the run's
  `verified_output_keys`) are declared as artifact outputs; values the
  model only reported in `done`'s outputs are left out.

## Round-trip check

No LLM, no agent — hand-builds the "look up member and read savings
balance" capability, saves it, reloads it, and confirms an exact match:

```
python -m artifacts.test_roundtrip
```
