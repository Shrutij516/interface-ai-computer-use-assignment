"""Standalone replay check -- no LLM, no discovery loop.

Replays the real, evidence-backed lookup_member_balance v1.1.0 artifact
twice against a live mock_bank:
  - member_id=10001: a known member -> expect `success`, and the
    extracted savings_balance should match discovery run
    evidence/discovery/20260918T023723Z/'s real output ($15234.56).
  - member_id=40404: mock_bank's documented not-found test ID
    (mock_bank/data.py's NOT_FOUND_TEST_ID) -> expect `business_outcome`
    ("not_found"), not a crash and not a false success.

Run with: python -m replay.test_replay
"""

from artifacts.store import load_artifact
from replay.engine import run_replay

KNOWN_MEMBER_ID = "10001"
KNOWN_MEMBER_EXPECTED_BALANCE = "$15234.56"
NOT_FOUND_MEMBER_ID = "40404"


def main() -> None:
    artifact = load_artifact("lookup_member_balance", "1.1.0")

    print(f"--- Replaying {artifact.capability_id} v{artifact.version} with member_id={KNOWN_MEMBER_ID} ---")
    found_result = run_replay(artifact, {"member_id": KNOWN_MEMBER_ID})
    print(found_result)

    print(f"\n--- Replaying {artifact.capability_id} v{artifact.version} with member_id={NOT_FOUND_MEMBER_ID} ---")
    not_found_result = run_replay(artifact, {"member_id": NOT_FOUND_MEMBER_ID})
    print(not_found_result)

    failures = []
    if found_result.get("outcome") != "success":
        failures.append(f"expected success for {KNOWN_MEMBER_ID}, got {found_result.get('outcome')}: {found_result}")
    elif found_result["outputs"].get("savings_balance") != KNOWN_MEMBER_EXPECTED_BALANCE:
        failures.append(
            f"expected savings_balance={KNOWN_MEMBER_EXPECTED_BALANCE!r}, "
            f"got {found_result['outputs'].get('savings_balance')!r}"
        )

    if not_found_result.get("outcome") != "business_outcome":
        failures.append(f"expected business_outcome for {NOT_FOUND_MEMBER_ID}, got {not_found_result.get('outcome')}: {not_found_result}")
    elif not_found_result.get("which") != "not_found":
        failures.append(f"expected which=not_found, got {not_found_result.get('which')}")

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        raise SystemExit(1)
    print("PASS: both replays returned the expected outcome.")


if __name__ == "__main__":
    main()
