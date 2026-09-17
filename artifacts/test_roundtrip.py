"""Standalone round-trip check for the artifact schema — no LLM, no agent.

Hand-builds the "look up member and read savings balance" capability
against mock_bank's actual markup, saves it, reloads it, and confirms the
reloaded artifact matches the original exactly.

Run with: python -m artifacts.test_roundtrip
"""

from artifacts.schema import Artifact, Checkpoint, FailureHandling, Locator, ParameterSpec, Step
from artifacts.store import load_artifact, save_artifact


def build_example_artifact() -> Artifact:
    return Artifact(
        capability_id="lookup_member_balance",
        version="1.0.0",
        description="Look up a credit union member by ID and read their current savings balance.",
        inputs=[
            ParameterSpec(
                name="member_id",
                type="string",
                description="The member ID to search for.",
                required=True,
            ),
        ],
        outputs=[
            ParameterSpec(
                name="found",
                type="boolean",
                description="Whether the member was found.",
                required=True,
            ),
            ParameterSpec(
                name="member_name",
                type="string",
                description="The member's full name.",
                required=False,
            ),
            ParameterSpec(
                name="savings_balance",
                type="number",
                description="The member's current savings balance in USD.",
                required=False,
            ),
        ],
        steps=[
            Step(
                step_id="navigate_search",
                action="navigate",
                locator=Locator(strategy="url", value="/"),
                on_failure=FailureHandling(
                    type="hard_failure",
                    message="Could not load the member search page.",
                ),
            ),
            Step(
                step_id="enter_member_id",
                action="type",
                locator=Locator(
                    strategy="role",
                    value="textbox:Member ID",
                    fallback=Locator(strategy="css", value="input[name='member_id']"),
                ),
                on_failure=FailureHandling(
                    type="hard_failure",
                    message="Member ID input field not found.",
                ),
            ),
            Step(
                step_id="submit_search",
                action="click",
                locator=Locator(
                    strategy="role",
                    value="button:Search",
                    fallback=Locator(strategy="css", value="input[type='submit']"),
                ),
                on_failure=FailureHandling(
                    type="hard_failure",
                    message="Search submit button not found.",
                ),
            ),
            Step(
                step_id="wait_for_detail_page",
                action="wait",
                locator=Locator(strategy="url", value="/members/*"),
                on_failure=FailureHandling(
                    type="recoverable",
                    message="Member detail page took too long to load; retry once.",
                ),
                expected_signals=[
                    "url matches /members/{member_id}",
                    "page title is 'Member Detail'",
                ],
            ),
            Step(
                step_id="check_member_found",
                action="check",
                locator=Locator(
                    strategy="css",
                    value="table tr:nth-child(3) td:nth-child(2)",
                    fallback=Locator(strategy="text", value="Savings Balance"),
                ),
                on_failure=FailureHandling(
                    type="business_outcome",
                    message="No member found for the given member ID.",
                ),
                expected_signals=["'No member found' text is absent"],
            ),
            Step(
                step_id="extract_member_name",
                action="extract",
                locator=Locator(
                    strategy="css",
                    value="table tr:nth-child(2) td:nth-child(2)",
                    fallback=Locator(strategy="text", value="Name"),
                ),
                on_failure=FailureHandling(
                    type="hard_failure",
                    message="Expected member name cell not found; page structure may have changed.",
                ),
            ),
            Step(
                step_id="extract_savings_balance",
                action="extract",
                locator=Locator(
                    strategy="css",
                    value="table tr:nth-child(3) td:nth-child(2)",
                    fallback=Locator(strategy="text", value="Savings Balance"),
                ),
                on_failure=FailureHandling(
                    type="hard_failure",
                    message="Expected savings balance cell not found; page structure may have changed.",
                ),
            ),
        ],
        checkpoint=Checkpoint(
            description="Member detail page loaded with a savings balance value present.",
            locator=Locator(
                strategy="css",
                value="table tr:nth-child(3) td:nth-child(2)",
                fallback=Locator(strategy="text", value="Savings Balance"),
            ),
            expected_signals=["extracted savings_balance is a valid non-negative number"],
        ),
    )


def main() -> None:
    original = build_example_artifact()
    path = save_artifact(original)
    reloaded = load_artifact(original.capability_id, original.version)

    if reloaded == original:
        print(f"PASS: artifact round-tripped exactly through {path}")
    else:
        print(f"FAIL: reloaded artifact does not match original ({path})")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
