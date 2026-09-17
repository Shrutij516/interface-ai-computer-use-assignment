# interface.ai Take-Home Spec — Computer-Use Automation System

All decisions below are locked. This is the spec Claude Code will build against.

## 1. Target application
Self-built mock banking app, deliberately legacy-styled (plain HTML tables, no
test IDs, minimal semantic markup). Three pages: member search, member detail
(shows savings balance), open sub-account form + confirmation screen.

Chosen over a public sandbox site because it lets us control UI ugliness on
purpose (proving the accessibility-tree approach survives legacy markup)
without any Terms-of-Service risk, and it mirrors the brief's own example
goals almost word for word.

## 2. Computer-use mechanism
Accessibility tree as primary signal (role + name locators), screenshots as
secondary/backup signal. Chosen over pure DOM/CSS selectors (breaks on
non-semantic legacy markup) and pure screenshot+coordinates (breaks on layout
shift, no path to desktop apps).

## 3. Stack
Python + Playwright. Chosen over Node.js (no benefit), Selenium (weaker
accessibility support, dated), and a dedicated computer-use SDK (locks into
screenshot-only mechanism).

## 4. LLM provider
Claude (Anthropic API) for the discovery run's decide step.

## 5. Artifact schema (Option B: steps + per-step failure handling)
Each artifact is JSON with: `capability_id`, `version`, `description`,
`inputs` (typed), `outputs` (typed), `steps` (ordered, each with an action,
a locator with strategy + fallback, and an `on_failure` classification), and
a `checkpoint` that must be verified before trusting any extracted output.

## 6. Replay result shape (Option C, collapsed to 3 top-level outcomes)
Every replay returns one of: `success` (optionally carrying a
`recovered_from` note if something minor was auto-fixed along the way),
`business_outcome` (a legitimate real-world answer, not a bug), or
`failure` (something actually broke — stop, don't guess).

## 7. Error taxonomy
- **Business outcomes:** record/member not found, permission denied,
  duplicate action (e.g. sub-account already exists)
- **Recoverable (auto-handled, folds into a `success` with a note):**
  unexpected popup/dialog → dismiss and continue; slow page load → wait and
  retry once
- **Hard failures (stop, escalate to human):** session expired mid-flow,
  expected element not found (locator + fallback both failed), landed on an
  unexpected page, checkpoint failed after steps ran, max retries/steps
  exceeded

Session timeout is explicitly a hard failure, not auto-recoverable — in a
regulated financial context, silent re-authentication is itself a risky
action that should require a human, not something automation decides on its
own.

## 8. Escalation & handoff
On hard failure: automation pauses (does not close the browser), writes an
intervention request (capability, step, screenshot, reason) to a local file,
and waits. A human opens a minimal mocked operator surface, takes over the
same live Playwright session, performs the fix, and marks the request
resolved. Automation detects the resolved flag, re-verifies the checkpoint,
and either resumes or reports based on where things stand. Full real-time
co-browsing UI is explicitly out of scope per the brief — the mechanism
(pause/handoff/resume on the same session) is what's real; the operator UI
is intentionally mocked.

## 9. Safety & allowlist
- **Allowlist:** config listing permitted domain/routes (mock bank's local
  URL only) and permitted action types (click, type, navigate, extract),
  checked before every action, not just once at start.
- **Reversible vs risky:** read-only actions (search, view balance) run
  freely. State-changing actions (opening a sub-account) always require
  reaching and showing the confirmation checkpoint before final submission —
  never auto-confirmed. Attempting an irreversible submit without having
  reached confirmation first is a hard stop.
- **Data handling:** raw member IDs/balances/PII are never written in full to
  logs or artifacts — masked (e.g. last 4 digits) versions only. Full values
  exist only in memory during a run.

## Deliverables checklist (from the brief, Section 6)
- [ ] Public GitHub repo with `/README.md` (setup + exact demo command)
- [ ] `/REPORT.md` (~1-3 pages, exact 7 headings from Section 6.2)
- [ ] `/evidence/` — saved artifact + logs from one discovery run and one
      replay run (ideally one replay that hits an error/exceptional state)
