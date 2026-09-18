"""Convert a completed discovery run (agent/discover.py's run_summary) into
a saved Artifact (schema.py), instead of hand-authoring one like
test_roundtrip.py does.

A discovery run's step_trace has one entry per loop iteration, including
the terminal `done` report. `done` carries no locator and isn't a
Literal["navigate", "click", "type", "extract", "wait", "check"] action in
the artifact schema -- it's the agent's own summary of the run, not a page
action -- so it's dropped when building the artifact's replayable steps.

Only outputs backed by a logged `extract` step (run_summary's
verified_output_keys) become declared artifact outputs; values the model
only reported in `done`'s outputs (unverified_output_keys) are left out,
per the same verified/unverified split run_discovery() already applies.
"""

from artifacts.schema import Artifact, Checkpoint, FailureHandling, Locator, ParameterSpec, Step

_ACTION_FAILURE = {
    "navigate": lambda value: FailureHandling(
        type="hard_failure",
        message=f"Could not navigate to '{value}'.",
    ),
    "type": lambda value: FailureHandling(
        type="hard_failure",
        message=f"Could not enter text into the target field ({value}).",
    ),
    "click": lambda value: FailureHandling(
        type="hard_failure",
        message=f"Could not click the target element ({value}).",
    ),
    "extract": lambda value: FailureHandling(
        type="hard_failure",
        message=f"Expected value not found for extraction ({value}); page structure may have changed.",
    ),
    "wait": lambda value: FailureHandling(
        type="recoverable",
        message=f"Timed out waiting for '{value}'; retry once.",
    ),
    "check": lambda value: FailureHandling(
        type="business_outcome",
        message=f"Check on '{value}' did not hold.",
    ),
}


def _trace_entry_to_step(entry: dict) -> Step:
    locator = Locator(**entry["locator"])
    return Step(
        step_id=entry["step_id"],
        action=entry["action"],
        locator=locator,
        on_failure=_ACTION_FAILURE[entry["action"]](locator.value),
    )


def discovery_run_to_artifact(
    run_summary: dict,
    capability_id: str,
    version: str,
) -> Artifact:
    """Build an Artifact from a discovery run's step_trace + outputs.

    Only member_id (input) and savings_balance (output) are declared --
    member_name is left out too, since it's unverified in this run's own
    verified_output_keys / unverified_output_keys split.
    """
    step_trace = run_summary["step_trace"]

    actionable_entries = [e for e in step_trace if e["action"] != "done"]
    steps = [_trace_entry_to_step(e) for e in actionable_entries]

    checkpoint_entry = next(e for e in step_trace if e["step_id"] == "step_2")
    checkpoint_locator = Locator(**checkpoint_entry["locator"])

    return Artifact(
        capability_id=capability_id,
        version=version,
        description=(
            "Look up a credit union member by ID and read their current "
            f"savings balance, recorded from verified discovery run {run_summary['run_id']}."
        ),
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
                name="savings_balance",
                type="string",
                description="The member's current savings balance, as displayed (e.g. '$15234.56').",
                required=True,
            ),
        ],
        steps=steps,
        checkpoint=Checkpoint(
            description="Savings balance value extracted from the member detail page.",
            locator=checkpoint_locator,
            expected_signals=["extracted savings_balance is a non-empty string"],
        ),
    )
