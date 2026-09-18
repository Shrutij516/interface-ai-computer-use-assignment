# REPORT

## 1. Architecture

Five independent modules, each with one job. `mock_bank/` is the target application, deliberately legacy-styled. `agent/` is the discovery loop: observe, decide, act against Claude Sonnet 5, driving Playwright via accessibility-tree snapshots as the primary signal and screenshots as backup. `artifacts/` is a Pydantic schema turning a completed run into a typed, versioned capability. `replay/` is the deterministic, LLM-free execution path enforcing the full error taxonomy. `escalation/` and `safety/` form a shared cross-cutting layer wired into both `agent/` and `replay/`, not duplicated across them.

Roughly 1,890 lines of source and 488 lines of tests, across 4 test files covering 7 distinct scenarios, all passing. This was verified twice: once in the working repo and once from a genuinely fresh clone.

Accessibility-tree-first perception was chosen over screenshot-coordinate or raw-DOM control specifically because it is the one signal that survives non-semantic legacy markup and extends to desktop applications, which have no DOM at all (Section 3.7). Playwright exposes both signals natively, so screenshots remain available as a fallback at no added cost.

`replay/engine.py` is the largest file at 529 lines, which tracks with the brief's own stated priority: deterministic execution, error taxonomy enforcement, safety gating, and escalation triggering all converge there.

## 2. Artifact schema

Each artifact captures typed inputs, typed outputs, an ordered list of steps (each with a locator strategy, an explicit fallback, and a per-step failure classification), and a checkpoint. Steps carry their own failure handling by design, so the artifact doubles as both the replay recipe and the error-handling contract in one document, instead of two things that could drift apart.

A concrete honesty mechanism came out of the real discovery run: outputs are split into `verified_output_keys` (only ever populated by a logged `extract` step) and `unverified_output_keys` (self-reported by the agent's final `done` step but never independently confirmed). In our one real capability, `savings_balance` is verified; `member_name` and `member_id` are not, since the agent read them correctly but never issued a loggable extract for them. The artifact declares only the verified output as its contract.

`Step` binds to inputs and outputs by position, not by an explicit key. This holds for one capability; a second capability would require adding that key.

## 3. Determinism & error handling

Replay executes each step with zero LLM calls, confirmed by grep: no `anthropic` import exists anywhere in `replay/`, `escalation/`, `safety/`, or `artifacts/`. Every step tries its primary locator, then its fallback, before failing.

Three top-level outcomes, matching the taxonomy designed before any code was written:

- **Business outcomes** (not a bug, a legitimate answer): not-found, permission denied, duplicate action. Verified end to end: replaying against member ID `40404` (mock_bank's documented not-found case) returns a clean `business_outcome` result, with no crash and no false success.
- **Recoverable** (handled automatically, folded into a `success` with a `recovered_from` note): an unexpected dialog gets dismissed, a slow page load gets one retry.
- **Hard failures** (stop, report, escalate): locator and fallback both exhausted, checkpoint verification fails after steps ran, an unexpected page or HTTP error is hit, or an escalation goes unresolved past a timeout.

Session timeout is classified as a hard failure requiring human escalation, not something the system auto-recovers from by re-authenticating itself. In a regulated financial context, silent automated re-login is itself a risky action that should not happen without a human in the loop, even though it would have been simpler to just retry.

This system has no dedicated drift-detection mechanism; checkpoint verification doubles as one implicitly, since a checkpoint that starts failing across previously-successful replays is itself the signal that the underlying page changed. The session-timeout path is implemented and reachable in code, but mock_bank has no real authentication system, so it has never been exercised against a genuine timeout, only injected conditions.

## 4. Heterogeneity & multi-tenant

This is a design answer, not an implementation, per the brief's scope note excluding multi-tenant and desktop support.

The architecture's seam sits between how a surface is perceived and acted on (`agent/perception.py` and `agent/executor.py`, both accessibility-tree-based) and what gets recorded (the artifact's locator strategies). Extending to a legacy web app needs no schema change, since the accessibility tree already handles non-semantic markup. Extending to a desktop app means swapping `executor.py`'s Playwright calls for an OS-level accessibility API (macOS Accessibility API, Windows UI Automation); the schema itself, locator plus fallback plus checkpoint, is unchanged, since it was never Playwright-specific.

For multi-tenant reuse, `capability_id` and step structure represent the vendor product's interaction pattern, not any one tenant's branding. A tenant with minor UI differences needs only wider locator fallback chains (already a per-step field); larger differences call for a tenant-specific override layer that replaces individual steps' locators while inheriting the rest. Drift detection reuses the same mechanism: a checkpoint failing across many tenants on the same vendor version signals the UI changed and the artifact needs a new version.

## 5. Escalation & handoff

Escalation triggers specifically on a `failure` outcome from replay, never on a `business_outcome`, since that is a normal answer, not a stuck state. On a hard failure, the live Playwright session pauses (not closes), a screenshot and full context are written to an intervention request file, and a minimal operator surface lists pending requests. A human resolves the request by describing the manual action taken; the same paused thread, holding the same live page, executes it, re-verifies the checkpoint, and only then reports success, since it never assumes the fix worked.

One real gap this process found and closed on its own: the escalation handoff initially let a human's manual action bypass the safety/allowlist gate entirely, since it was not routed through the same check as normal actions. This was caught and fixed before submission, so safety refusals now apply uniformly, including inside a human-resolved handoff, which matters precisely because a handoff path is the one place a bypass would be easiest to miss.

Verified end to end with an injected failure: a corrupted locator on the "click Search" step triggered a real pause, a written intervention request, a simulated human fix, and a successful resume producing the correct final output, the identical result the original discovery run had produced.

## 6. Safety

A single shared policy module (`safety/policy.py`) is imported by `agent/`, `replay/`, and `escalation/`, rather than three separate implementations that could drift apart. Two mechanisms: an allowlist (permitted domains and action types, checked before every single action, not once at startup) and a risk gate (state-changing actions like opening a sub-account require the artifact to have actually reached and shown a confirmation checkpoint first; attempting one cold is a hard stop, never auto-confirmed). Risk classification resolves an action's real destination (the actual form action or href Playwright sees), not its visible button label, so it is resistant to label changes.

Verified with two deliberate test cases: an action targeting a domain outside the allowlist is refused and logged; a risky action attempted without first passing through a confirmation checkpoint is refused as a hard stop.

Sensitive data handling: member IDs and balances are masked (partial values only) in every persisted log and artifact across both discovery and replay, using one shared masking utility. The one deliberate exception is escalation screenshots, which remain unmasked by design, since an operator resolving a broken locator needs to see the real page to fix it. This is documented directly in code as a named trade-off: a production version would keep masked JSON logs in long-retention, commit-safe storage, and route screenshots to a separate, access-controlled, short-retention store, never a general-purpose repository.

## 7. Cuts

- **Artifact-building from a discovery run** is a working, verified one-line command, not a dedicated CLI. Next: a proper `artifacts.build <run_id>` command as the demo path matures.
- **Positional input/output binding** on `Step` works correctly for this project's single capability. Next: an explicit `output_key`/`input_key` field, proven out by adding a second, more complex capability (for example opening a sub-account) rather than leaving the fix theoretical.
- **Multi-tenant and desktop support** were designed (Section 4) but intentionally not built, per the brief's own scope note. Next: the tenant-override layer and a second, OS-accessibility-API-based executor, to prove the described seam actually holds rather than just sounding plausible.
- **Session-timeout and UI-drift detection are both reactive, not proactive.** Session-timeout is implemented but untested against a genuine trigger; drift relies on checkpoint failures rather than active monitoring. Next: a toggleable simulated-timeout route in mock_bank to properly exercise the escalation path, and periodic checkpoint re-verification against production traffic to make drift detection proactive rather than incidental.
- With more time, beyond the above: a real operator UI past the mocked minimal surface, and multi-run stability testing (replaying N times for a flakiness signal), per the brief's own stretch goals, deliberately deprioritized in favor of full depth on the six core requirements first.
