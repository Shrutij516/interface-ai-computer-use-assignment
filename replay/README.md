# replay

Deterministic replay engine: re-runs a saved artifact against the live
surface without the LLM in the decision loop, using stable element/control
targeting, verifying the checkpoint, and returning one of three outcomes
(spec §6): `success` (optionally with `recovered_from`), `business_outcome`,
or `failure`.

Not yet implemented — skeleton only.
