"""Reviewer headline metrics and Wilson PASS precision / catching."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tools.reviewer_scorecard.blind import compute_blind
from tools.reviewer_scorecard.coverage import derive_counting, is_clean_pass
from tools.reviewer_scorecard.tables import ScorecardTables
from tools.reviewer_scorecard.wilson import round_metric, wilson_lower_bound

BLOCKING_SEVERITIES = {"S1 Critical", "S2 High", "S1", "S2"}
GOLDEN_STATUS = {"real"}


@dataclass
class HeadlineCounts:
    serious_caught: int = 0
    serious_at_risk: int = 0
    serious_caught_blind: int = 0
    serious_at_risk_blind: int = 0
    false_passes: int = 0
    false_pass_denominator: int = 0
    false_alarms: int = 0
    false_alarm_denominator: int = 0
    blocks_overturned: int = 0
    blocks_overturned_denominator: int = 0
    degraded_pass_count: int = 0
    non_counting_share: float = 0.0
    heads_reviewed: int = 0


@dataclass
class ScorecardMetrics:
    reviewer_id: str
    headlines: HeadlineCounts
    clean_pass_n: int = 0
    correct_clean_passes: int = 0
    pass_precision_lb: float | None = None
    pass_precision_display: str = "not eligible"
    catching_successes: int = 0
    at_risk_bugs_reviewed: int = 0
    catching_lb: float | None = None
    catching_display: str = "not eligible"
    repo_at_risk_bugs: int = 0
    per_review: list[dict[str, Any]] = field(default_factory=list)


def _bugs_by_id(tables: ScorecardTables) -> dict[str, dict[str, str]]:
    return {b["bug_id"]: b for b in tables.bugs}


def _presence_index(tables: ScorecardTables) -> dict[tuple[str, str], dict[str, str]]:
    out: dict[tuple[str, str], dict[str, str]] = {}
    for row in tables.presence:
        out[(row["bug_id"], row["head_sha"])] = row
    return out


def _at_risk_on_head(
    tables: ScorecardTables,
    head_sha: str,
    bugs_by_id: dict[str, dict[str, str]],
    presence_index: dict[tuple[str, str], dict[str, str]],
) -> list[str]:
    ids: list[str] = []
    for bug_id, bug in bugs_by_id.items():
        if bug.get("status") not in GOLDEN_STATUS:
            continue
        if bug.get("severity") not in BLOCKING_SEVERITIES:
            continue
        pres = presence_index.get((bug_id, head_sha))
        if not pres:
            continue
        if pres.get("state") != "present" or pres.get("scope") != "diff":
            continue
        ids.append(bug_id)
    return ids


def parse_caught_bug_ids(raw: str) -> set[str]:
    """Normalize caught_bug_ids TSV field to a distinct-id set (matches metrics denominators)."""
    if not raw or raw.strip().lower() in {"-", "none", ""}:
        return set()
    return {p.strip() for p in raw.split(";") if p.strip()}


def _parse_caught_bug_ids(raw: str) -> set[str]:
    return parse_caught_bug_ids(raw)


def compute_reviewer_metrics(tables: ScorecardTables, reviewer_id: str) -> ScorecardMetrics:
    bugs_by_id = _bugs_by_id(tables)
    presence_index = _presence_index(tables)
    rows = [r for r in tables.reviews if r["reviewer_id"] == reviewer_id and r.get("stage", "code") != "plan"]

    repo_at_risk: set[str] = set()
    for head in {r["head_sha"] for r in tables.reviews if r.get("stage", "code") != "plan"}:
        for bid in _at_risk_on_head(tables, head, bugs_by_id, presence_index):
            repo_at_risk.add(bid)

    headlines = HeadlineCounts()
    headlines.heads_reviewed = len({r["head_sha"] for r in rows})

    counting_rows = [r for r in rows if derive_counting(r["coverage_class"], r.get("stage", "code"), r.get("counting", "yes"))]
    non_counting_rows = [r for r in rows if not derive_counting(r["coverage_class"], r.get("stage", "code"), r.get("counting", "yes"))]
    if rows:
        headlines.non_counting_share = len(non_counting_rows) / len(rows)

    false_pass_pr_seen: set[int] = set()
    caught_bugs: set[str] = set()
    caught_bugs_blind: set[str] = set()
    at_risk_bugs_reviewed: set[str] = set()
    at_risk_bugs_blind: set[str] = set()
    clean_pass_n = 0
    correct_clean_passes = 0

    per_review: list[dict[str, Any]] = []

    for row in rows:
        head = row["head_sha"]
        pr = int(row["pr"])
        all_at_head = [r for r in tables.reviews if r["head_sha"] == head]
        blind = compute_blind(
            reviewer_id,
            head,
            row.get("requested_at", ""),
            all_at_head,
            row.get("blind"),
            row.get("same_head_peer_citation"),
        )
        counting = derive_counting(row["coverage_class"], row.get("stage", "code"), row.get("counting", "yes"))
        at_risk = _at_risk_on_head(tables, head, bugs_by_id, presence_index)

        if row["coverage_class"] == "degraded" and row["claimed_verdict"].lower() == "pass":
            headlines.degraded_pass_count += 1

        caught_here = _parse_caught_bug_ids(row.get("caught_bug_ids", ""))
        at_risk_set = set(at_risk)

        if counting and is_clean_pass(row["claimed_verdict"], row["coverage_class"]):
            clean_pass_n += 1
            missed = [b for b in at_risk if b not in caught_here]
            is_fp = bool(missed)
            if is_fp and pr not in false_pass_pr_seen:
                headlines.false_passes += 1
                false_pass_pr_seen.add(pr)
            headlines.false_pass_denominator += 1
            if not is_fp:
                correct_clean_passes += 1

        for bid in caught_here:
            if bid not in at_risk_set:
                continue
            if bid not in caught_bugs:
                caught_bugs.add(bid)
                headlines.serious_caught += 1
            if blind == "yes" and counting and bid not in caught_bugs_blind:
                caught_bugs_blind.add(bid)
                headlines.serious_caught_blind += 1

        for bid in at_risk:
            at_risk_bugs_reviewed.add(bid)
            if blind == "yes" and counting:
                at_risk_bugs_blind.add(bid)

        fa = _parse_caught_bug_ids(row.get("false_alarm_ids", ""))
        for _ in fa:
            headlines.false_alarms += 1
        if row.get("false_alarm_denominator", "").strip().lower() == "yes":
            headlines.false_alarm_denominator += 1

        if row.get("block_overturned", "").strip().lower() == "yes":
            headlines.blocks_overturned += 1
        if row.get("block_trial", "").strip().lower() == "yes":
            headlines.blocks_overturned_denominator += 1

        per_review.append(
            {
                "head_sha": head,
                "coverage_class": row["coverage_class"],
                "counting": counting,
                "blind": blind,
                "at_risk_bug_ids": at_risk,
            }
        )

    headlines.serious_at_risk = len(at_risk_bugs_reviewed)
    headlines.serious_at_risk_blind = len(at_risk_bugs_blind)

    lb = wilson_lower_bound(correct_clean_passes, clean_pass_n) if clean_pass_n else None
    pass_display = "not eligible"
    if clean_pass_n == 0:
        pass_display = "not eligible"
    elif clean_pass_n < 5:
        pass_display = f"counts only ({correct_clean_passes} of {clean_pass_n})"
    elif clean_pass_n < 10:
        pass_display = f"interval only ({round_metric(lb, 3)})"
    else:
        pass_display = f"{round_metric(lb, 6)}"

    catch_lb = (
        wilson_lower_bound(headlines.serious_caught_blind, len(at_risk_bugs_blind))
        if at_risk_bugs_blind
        else None
    )
    catching_display = "not eligible"
    if not at_risk_bugs_blind:
        catching_display = "not eligible"
    elif len(at_risk_bugs_blind) < 5:
        catching_display = f"counts only ({headlines.serious_caught_blind} of {len(at_risk_bugs_blind)})"
    elif len(at_risk_bugs_blind) < 10:
        catching_display = f"interval only ({round_metric(catch_lb, 3)})"
    else:
        catching_display = f"{round_metric(catch_lb, 6)}"

    return ScorecardMetrics(
        reviewer_id=reviewer_id,
        headlines=headlines,
        clean_pass_n=clean_pass_n,
        correct_clean_passes=correct_clean_passes,
        pass_precision_lb=round_metric(lb),
        pass_precision_display=pass_display,
        catching_successes=headlines.serious_caught_blind,
        at_risk_bugs_reviewed=len(at_risk_bugs_reviewed),
        catching_lb=round_metric(catch_lb),
        catching_display=catching_display,
        repo_at_risk_bugs=len(repo_at_risk),
        per_review=per_review,
    )
