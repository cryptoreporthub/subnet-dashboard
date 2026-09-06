# Deploy vehicle — A1 activation (2026-09-06)

Purpose: activate Section A capture hardening (A1) on the live app.

Expected outcome:
- labeled fly-deploy event resolves refs/heads/main
- /version == post-merge main SHA (8ced487)
- Section A capture endpoints respond

Refs: INCIDENT 2026-08-19 (push-to-main disabled). A1 activation is NOT automatic.
