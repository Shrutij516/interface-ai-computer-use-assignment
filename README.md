# Computer-Use Automation System

An LLM-driven agent discovers how to accomplish a goal against a real
(mock) banking app, records what it did as a typed, versioned artifact,
and replays that artifact deterministically — no LLM in the loop — with
an explicit error taxonomy, safety allowlist, and human escalation/
handoff on a hard failure. Built against `interface-ai-project-spec.md`
(the locked design decisions) for the brief in `Assignment A — Computer-
Use Automation System.pdf`.

```
agent/        LLM-driven discovery loop (observe -> decide -> act)
artifacts/    the capability schema + JSON storage + discovery->artifact conversion
replay/       deterministic, LLM-free replay engine
escalation/   pause / human handoff / resume on a hard failure
safety/       shared allowlist + risk gate + PII masking
mock_bank/    the target app: a small, deliberately legacy-styled Flask site
evidence/     saved logs from real discovery and replay runs
```

Each module has its own README with implementation detail; this one is
setup + the demo path.

## Setup (fresh machine)

Tested with Python 3.9.6 on macOS. Needs Python 3.9+.

```bash
git clone https://github.com/Shrutij516/interface-ai-computer-use-assignment
cd interface-ai-computer-use-assignment

python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium     # downloads the actual browser binary --
                                 # `pip install playwright` alone does NOT do this
```

Only the discovery step calls a real LLM. Export your own key before
running it:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Nothing else needs a key, an account, or network access. `mock_bank`
(the target app) is started automatically as a local subprocess by every
script below if nothing is already listening on `http://127.0.0.1:5000`
— there's no separate service to stand up, and no external dependency
besides the Anthropic API for the one discovery call.

## Demo path

**1. Run the agent on a goal** (needs `ANTHROPIC_API_KEY`; starts
mock_bank automatically):

```bash
python -m agent.discover --goal "search for member 10001 and read their savings balance."
```

Logs every step to `evidence/discovery/<run_id>/` (`steps.jsonl` +
screenshots + `run_summary.json`). A real run is already committed at
`evidence/discovery/20260918T035315Z/` if you want to see the shape
without spending an API call.

**2. Turn that run into a saved capability artifact** (no LLM, no
network — pure conversion of the run's `step_trace` into
`artifacts/schema.py`'s `Artifact` shape; substitute your own run_id
from step 1, or use the committed one below):

```bash
python3 -c "
import json
from pathlib import Path
from artifacts.from_discovery import discovery_run_to_artifact
from artifacts.store import save_artifact

run_summary = json.loads(Path('evidence/discovery/20260918T035315Z/run_summary.json').read_text())
artifact = discovery_run_to_artifact(run_summary, capability_id='lookup_member_balance', version='1.1.0')
print('Saved to:', save_artifact(artifact))
"
```

This writes `artifacts/capabilities/lookup_member_balance__v1.1.0.json`
(already committed — this is the real, evidence-backed capability; see
`artifacts/README.md` for why a `v1.0.0` also exists and isn't this).

**3. Replay the artifact deterministically** (no LLM; starts mock_bank
automatically):

```bash
python -m replay.test_replay
```

Replays the same capability twice: `member_id=10001` (a real member —
returns `success` with the same `savings_balance` the discovery run
found) and `member_id=40404` (mock_bank's documented not-found case —
returns `business_outcome`, not a crash). Full trace logged to
`evidence/replay/<run_id>/`.

**4. See a hard failure escalate to a human and resume** (no LLM):

```bash
python -m escalation.test_escalation
```

Deliberately corrupts one step's locator, proves the live browser
pauses (not closes) on the resulting hard failure, a simulated operator
resolves the intervention request with a real corrective action on that
same session, and the run resumes and completes correctly. Evidence in
`escalation/requests/` + `escalation/screenshots/`.

**5. See the safety allowlist and risk gate refuse things** (no LLM):

```bash
python -m safety.test_safety
```

Proves an action outside the allowlist (a different domain) is refused
and logged, and that mock_bank's one irreversible action (opening a
sub-account) is refused as a hard stop if attempted without first
reaching the confirmation screen — on both the discovery and replay
code paths, via the one shared `safety/policy.py`.

## Run every test, back to back

```bash
python -m artifacts.test_roundtrip
python -m replay.test_replay
python -m escalation.test_escalation
python -m safety.test_safety
```

All four are self-contained (no `pytest` needed, no fixtures beyond what
each script sets up itself) and only the first requires nothing to be
running beforehand — the rest start mock_bank themselves. None of the
four call an LLM.

## Design write-up

See [`REPORT.md`](REPORT.md) for architecture, the artifact schema,
error handling, heterogeneity/multi-tenant design, escalation, safety,
and cuts.
