# Rev-21 Amendment — Review-Board Adoption

**Status:** proposal · pending orchestrator confirmation
**Created:** 2026-09-14
**Depends on:** `cursor-agents-communication/review-board.md` (same relay)
**Base:** `30190aea19acd6930ead4330b8ad5cc51f423025`

---

## 0. Declared unknowns

Read this before treating anything below as settled.

> **`UNVERIFIED` — §9 list numbering.**
> The Card 6 rule text below is quoted from a rev-20 memory read that truncated
> at **8,373 characters**, cutting the document at §3. The surrounding §9
> numbered-list state was **not observable** in that read.
> Therefore: **the Card 6 insertion point is a proposal, not a confirmed slot.**
> An orchestrator with a full rev-20 read must confirm or correct the numbering
> before this amendment is treated as authoritative.
>
> Per standing constraint C3, this unknown is declared in the artifact rather
> than resolved by assumption. If the numbering below does not match the live
> §9 list, the **text** stands and the **number** is wrong — fix the number, keep
> the rule.

---

## 1. What this amendment does

Adds the **Card 6 rule** to the review protocol's §9 numbered list, and pins the
§2.7 wording that the review board depends on.

This amendment does **not** modify any guard, check, or protection. It is an
addition. If revision reveals that adding these items requires removing an
existing guard, **stop** — that removal is a separate tradeoff requiring its own
review (see: silent-regression rule).

---

## 2. Verbatim §2.7 wording (as carried)

> *(§2.7 text as retrieved from rev-20 memory — quoted, not paraphrased.)*

---

## 3. Card 6 rule — proposed insertion

> *(Card 6 rule text as retrieved from rev-20 memory — quoted, not paraphrased.)*

**Proposed placement:** §9 numbered list, appended as the next ordinal,
**pending confirmation** (see §0).

---

## 4. Exit condition

This amendment moves to `CLOSED` when:
1. A full rev-20 read is obtained, and
2. §9 numbering is confirmed or corrected, and
3. A commit SHA introducing the corrected version is recorded in
   `review-board.md` §4 (Closed items).

Until all three hold, this document is a **proposal**.
