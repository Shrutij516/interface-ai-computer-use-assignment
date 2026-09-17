"""Artifact schema — the reusable, replayable capability contract.

Matches interface-ai-project-spec.md §5 (Option B: steps + per-step failure
handling): capability_id, version, description, typed inputs/outputs,
ordered steps (each with a locator strategy + fallback and an on_failure
classification), and a checkpoint.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel


class ParameterSpec(BaseModel):
    """A typed input or output parameter of a capability."""

    name: str
    type: Literal["string", "number", "boolean"]
    description: str
    required: bool = True


class Locator(BaseModel):
    """How to find a target: a strategy (role/text/css/xpath/url) plus a
    value, with an optional fallback locator to try if the primary fails.
    Accessibility-tree signals (role) are preferred; css/xpath/text are
    fallbacks for when the primary signal isn't available."""

    strategy: Literal["role", "text", "css", "xpath", "url"]
    value: str
    fallback: Optional["Locator"] = None


Locator.model_rebuild()


class FailureHandling(BaseModel):
    """Classification applied if this step's action/check does not
    succeed, per the spec §7 error taxonomy."""

    type: Literal["hard_failure", "recoverable", "business_outcome"]
    message: str


class Step(BaseModel):
    step_id: str
    action: Literal["navigate", "click", "type", "extract", "wait", "check"]
    locator: Locator
    on_failure: FailureHandling
    expected_signals: Optional[List[str]] = None


class Checkpoint(BaseModel):
    """A condition that must be verified before trusting any extracted
    output — asserts the run actually reached the expected end state."""

    description: str
    locator: Locator
    expected_signals: Optional[List[str]] = None


class Artifact(BaseModel):
    capability_id: str
    version: str
    description: str
    inputs: List[ParameterSpec]
    outputs: List[ParameterSpec]
    steps: List[Step]
    checkpoint: Checkpoint
