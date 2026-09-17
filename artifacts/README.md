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

## Round-trip check

No LLM, no agent — hand-builds the "look up member and read savings
balance" capability, saves it, reloads it, and confirms an exact match:

```
python -m artifacts.test_roundtrip
```
