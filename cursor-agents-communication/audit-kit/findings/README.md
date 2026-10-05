# Audit findings (Evidence Bundles)

Lane 1 and Lane 2 workers write JSON bundles here. Mission Control validates
schema and merges into the candidate matrix.

See [`../evidence-bundle-schema.md`](../evidence-bundle-schema.md).

Do not commit bundles until MC strip-validation passes (required fields present,
`refutes_if` non-empty, pin matches charter).
