# Amended /version gate (label-driven vehicle deploys)

- GET /version must equal the deployed head SHA reported by the Fly Deploy run (SENTRY_RELEASE / run head).
- The deployed head must satisfy BOTH: merge_base(deployed_head, step1_main_sha) == step1_main_sha, AND the diff deployed_head vs step1_main_sha contains ONLY the vehicle doc file(s) under docs/deploy-vehicles/.
- PASS if trees differ only by vehicle docs; STOP on any code file, non-descendant head, or /version showing unknown/error.
- Note the motivation: fly.yml on a labeled PR checks out pull_request.head.sha, so /version reports the vehicle tip, never a squash SHA.
