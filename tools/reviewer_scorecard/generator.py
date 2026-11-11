"""Generate SCORECARD.md, scorecard.json, and comment bodies from TSV tables."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.reviewer_scorecard.blind import compute_blind
from tools.reviewer_scorecard.coverage import derive_counting
from tools.reviewer_scorecard.metrics import compute_reviewer_metrics
from tools.reviewer_scorecard.tables import ScorecardTables

GENERATOR_VERSION = "reviewer-scorecard/3.3.0-phase2"
SCHEMA_VERSION = "scorecard.json/3.3.0"


@dataclass
class GeneratedScorecard:
    scorecard_md: str
    scorecard_json: dict[str, Any]
    reviewer_comments: dict[str, str]
    peer_comments: dict[str, str]
    deterministic_bytes: bytes

    def write(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "SCORECARD.md").write_text(self.scorecard_md, encoding="utf-8")
        (out_dir / "scorecard.json").write_text(
            json.dumps(self.scorecard_json, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        comments_dir = out_dir / "comments"
        comments_dir.mkdir(exist_ok=True)
        for key, body in self.reviewer_comments.items():
            (comments_dir / f"reviewer_{key}.md").write_text(body, encoding="utf-8")
        for key, body in self.peer_comments.items():
            (comments_dir / f"peer_{key}.md").write_text(body, encoding="utf-8")
        (out_dir / "scorecard.det.json").write_bytes(self.deterministic_bytes)


def _sha7(head_sha: str) -> str:
    return head_sha.strip()[:7]


def _deterministic_reviewer_body(body: str) -> str:
    lines = body.splitlines()
    if not lines:
        return body
    first = lines[0]
    if " UTC |" in first:
        before, after = first.split(" UTC |", 1)
        before = before.rsplit(" | ", 1)[0] + " | <verdict_at>"
        lines[0] = before + " UTC |" + after
    return "\n".join(lines) + ("\n" if body.endswith("\n") else "")


def _deterministic_peer_body(body: str) -> str:
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("_Peer view | generated "):
            lines[i] = line.split("generated ", 1)[0] + "generated <clock-stripped>"
    return "\n".join(lines) + ("\n" if body.endswith("\n") else "")


def _deterministic_bundle(
    scorecard_md: str,
    scorecard_json: dict[str, Any],
    reviewer_comments: dict[str, str],
    peer_comments: dict[str, str],
) -> bytes:
    det_json = dict(scorecard_json)
    det_json["generated_at"] = None
    bundle = {
        "md": scorecard_md,
        "json": det_json,
        "reviewer_comments": {k: _deterministic_reviewer_body(v) for k, v in reviewer_comments.items()},
        "peer_comments": {k: _deterministic_peer_body(v) for k, v in peer_comments.items()},
    }
    return json.dumps(bundle, sort_keys=True).encode("utf-8")


def _reviewer_comment(row: dict[str, str], inputs_hash: str) -> str:
    head = row["head_sha"]
    verdict = row["claimed_verdict"]
    reviewer = row.get("display_name") or row["reviewer_id"]
    lines = [
        f"**{verdict} | PR #{row['pr']} | head `{_sha7(head)}` | {reviewer} | "
        f"{row.get('verdict_at', 'unknown')} UTC | confidence: {row.get('confidence', 'not_stated')}**",
        "_Valid for this head only. This comment is never edited._",
        f"_generator: {GENERATOR_VERSION}  inputs: {inputs_hash}_",
        "",
        "| Check | Result | Evidence |",
        "|---|---|---|",
        f"| Blocking (S1/S2) | {row.get('blocking_result', '0 found')} | - |",
        f"| Follow-ups (S3/S4) | {row.get('followups', '0')} | - |",
        f"| Tests / CI at this head | {row.get('ci_result', 'not run')} | - |",
        f"| Prod risk / rollback | {row.get('prod_risk', 'not stated')} | - |",
        "",
        f"**Not checked:** {row.get('not_checked', 'none')}",
    ]
    return "\n".join(lines) + "\n"


def _peer_comment(
    row: dict[str, str],
    inputs_hash: str,
    blind: str,
    peers: list[dict[str, str]],
) -> str:
    derived = f"{row['claimed_verdict']} ({row['coverage_class']})"
    counting = "yes" if derive_counting(row["coverage_class"], row.get("stage", "code"), row.get("counting", "yes")) else "no"
    peer_bits = "; ".join(f"{p['reviewer_id']} {p['claimed_verdict']}" for p in peers if p["reviewer_id"] != row["reviewer_id"])
    lines = [
        f"**{derived} | PR #{row['pr']} | head `{_sha7(row['head_sha'])}` | scoreboard line**",
        f"_Peer view | generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  inputs: {inputs_hash}_",
        f"_coverage_class: {row['coverage_class']}  counting: {counting}  blind: {blind}_",
        f"_files_reviewed / files_changed: {row.get('files_reviewed', '?')}/{row.get('files_changed', '?')}_",
        "",
        f"**Other reviewers at this head:** {peer_bits or 'none'}",
    ]
    return "\n".join(lines) + "\n"


def generate_scorecard(tables: ScorecardTables) -> GeneratedScorecard:
    inputs_hash = tables.inputs_hash()
    registry = {r["reviewer_id"]: r for r in tables.registry}

    reviewer_metrics: dict[str, Any] = {}
    for reg in tables.registry:
        m = compute_reviewer_metrics(tables, reg["reviewer_id"])
        h = m.headlines
        reviewer_metrics[reg["reviewer_id"]] = {
            "heads_reviewed": h.heads_reviewed,
            "serious_caught_blind": f"{h.serious_caught_blind} of {h.serious_at_risk_blind}",
            "false_passes": f"{h.false_passes} of {h.false_pass_denominator}",
            "false_alarms": f"{h.false_alarms} of {h.false_alarm_denominator}",
            "blocks_overturned": f"{h.blocks_overturned} of {h.blocks_overturned_denominator}",
            "non_counting_share": round(h.non_counting_share, 6),
            "degraded_pass_count": h.degraded_pass_count,
            "pass_precision_lb": m.pass_precision_lb,
            "pass_precision_display": m.pass_precision_display,
            "catching_lb": m.catching_lb,
            "catching_display": m.catching_display,
            "at_risk_bugs_reviewed": m.at_risk_bugs_reviewed,
            "repo_at_risk_bugs": m.repo_at_risk_bugs,
        }

    lines = [
        "# Reviewer scorecard (generated)",
        "",
        f"generator: {GENERATOR_VERSION}",
        f"schema: {SCHEMA_VERSION}",
        f"inputs: {inputs_hash}",
        "",
        "| reviewer | caught (blind) | false pass | PASS precision | catching | non-counting share |",
        "|---|---|---|---|---|---|",
    ]
    for reg in tables.registry:
        rid = reg["reviewer_id"]
        rm = reviewer_metrics[rid]
        lines.append(
            f"| {reg['display_name']} | {rm['serious_caught_blind']} | {rm['false_passes']} | "
            f"{rm['pass_precision_display']} | {rm['catching_display']} | {rm['non_counting_share']} |"
        )
    scorecard_md = "\n".join(lines) + "\n"

    scorecard_json: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "inputs_hash": inputs_hash,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reviewers": reviewer_metrics,
    }

    reviewer_comments: dict[str, str] = {}
    peer_comments: dict[str, str] = {}
    for row in tables.reviews:
        row = dict(row)
        row["display_name"] = registry.get(row["reviewer_id"], {}).get("display_name", row["reviewer_id"])
        key = f"{row['reviewer_id']}_{row['head_sha']}"
        if key in reviewer_comments:
            raise ValueError(
                f"duplicate review row for reviewer={row['reviewer_id']} "
                f"head={row['head_sha']} pr={row.get('pr', '?')} stage={row.get('stage', 'code')}"
            )
        reviewer_comments[key] = _reviewer_comment(row, inputs_hash)
        peers = [r for r in tables.reviews if r["head_sha"] == row["head_sha"]]
        blind = compute_blind(
            row["reviewer_id"],
            row["head_sha"],
            row.get("requested_at", ""),
            peers,
            row.get("blind"),
            row.get("same_head_peer_citation"),
        )
        peer_comments[key] = _peer_comment(row, inputs_hash, blind, peers)

    deterministic = _deterministic_bundle(scorecard_md, scorecard_json, reviewer_comments, peer_comments)

    return GeneratedScorecard(
        scorecard_md=scorecard_md,
        scorecard_json=scorecard_json,
        reviewer_comments=reviewer_comments,
        peer_comments=peer_comments,
        deterministic_bytes=deterministic,
    )


def generate_from_directory(table_dir: Path, out_dir: Path | None = None) -> GeneratedScorecard:
    tables = ScorecardTables.load(table_dir)
    result = generate_scorecard(tables)
    if out_dir is not None:
        result.write(out_dir)
    return result
