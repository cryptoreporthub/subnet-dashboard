# LOCK — Subnet display names

**Status:** ACTIVE (pending PR)  
**Branch:** `cursor/subnet-name-fix-4988`  
**Plan:** `full-roadmap-master-plan.md` Phase 0

## Problem

Pump desk used `registry_subnet_rows()` → 61× `Unknown` in local registry; taostat remote max SN74; `use_taostats=False` on pump paths → bare `SN{n}` on desk.

## DECISIONS

- Curator override **SN16 → Fast Thinker** (TMC/taostat remote still say BitAds; on-chain/taostats explorer is correct)
- Single resolver: `display_name_for_netuid()` in `subnet_names.py`
- Pump + hydrate: `load_subnets_for_display(timeout=4)` (TMC/live first)
- TaoStats identity fallback only when still generic after remote + row
- Client pump rows: `resolveSubnetDisplayName` / `SubnetNameRegistry`
- Do not block homepage shell — hydrate upgrades names after paint

## AC

- [ ] `pytest tests/test_subnet_display_names.py` green
- [ ] `/api/pump-alerts` names not bare `SN{n}` for TMC-known netuids on desk
- [ ] `/api/subnets` returns TMC names when feed succeeds within 4s
- [ ] Message intel trending uses canonical names

## NON-GOALS

- Rewriting entire `config/registry.json` (129 subnets) in one PR
- Curator overrides bulk import (separate ops if needed)
