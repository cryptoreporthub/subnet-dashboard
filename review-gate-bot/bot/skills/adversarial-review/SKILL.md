---
description: Use on every pull request review. Trace each accepted value to its consumers, then push extremes through the real entry point and judge whether the result can abort a cycle or poison a later row.
---

# Adversarial review

## 1. Trace every accepted value to its consumers

For each value the diff accepts, list every place it lands:

| Source | Consumers to check |
| --- | --- |
| Environment variable | parsed where? default when malformed? import-time or call-time? |
| Config / JSON under `config/` | who reads it, when, and what a bad row does |
| Persisted state | ledger rows, predictions, soul-map, kv, SQLite columns |
| CLI argument | validated against what range |
| RPC / API response | trusted for membership, price, or identity? |

A value read at import time that raises disables a whole router. That is the
shape of a production outage, not a validation nit: name the router it turns
off.

## 2. Push extremes through the real entry point

Not a helper, not the parse function alone: the function production calls. You cannot execute code, so open that function with `read_repo_file` and walk each value through it by hand. Label the result **inferred**.

- `1e308`, `sys.float_info.max`, the denormal `5e-324`
- huge integers: `10**400`, `2**63`
- `NaN`, `inf`, `-inf`
- bad strings, empty strings, `None`
- bools where a number is expected

For each: does it raise, silently become `inf`, or get written back?

## 3. The multiplication trap

A finite input can still overflow. `1e300 * grace * 3600` is `inf`, and
`float("inf")` is a valid float, so nothing raises. Then:

- is the result compared against a timestamp? (`inf > now` is always true)
- is it persisted? (`inf` in JSON is not valid JSON)
- is it multiplied or divided again?

Find the consumer of the overflowed value. An overflow that only produces a
warning is a P3; an overflow that makes a row permanently unreachable is a P0.

## 4. Can it abort a cycle, or poison a later row?

Two different severities:

- **Aborts a cycle**: the current call dies. Recoverable on the next cycle.
- **Poisons a later row**: bad state is written and read back. Every later
  cycle inherits the defect, and a restart does not fix it.

Say which one, with the line number of the write and the line number of the
read.

## 5. Hunt for one bug the PR does not mention

The PR description is the author's model of the change, not the change. Read
the diff for what it does not discuss: a deleted guard, a changed default, a
test that asserts the implementation instead of the behaviour.

If you find nothing after a real attempt, write that down as a measured
negative. Do not invent a finding to fill the slot.

## 6. Report shape

Every finding gets: severity (P0 blocks merge), the file and line, the value or
path that triggers it, the consumer it reaches, and whether it is **measured**
(a tool returned it) or **inferred** (you read it). With no shell, nearly every
behavioural finding is inferred.
