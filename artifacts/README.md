# artifacts

Artifact schema and storage for recorded capabilities (spec §5): typed
`capability_id`, `version`, `description`, `inputs`, `outputs`, ordered
`steps` (each with an action, a locator with strategy + fallback, and an
`on_failure` classification), and a `checkpoint`.

- `capabilities/` — saved artifact JSON files (one per recorded capability).

Not yet implemented — skeleton only.
