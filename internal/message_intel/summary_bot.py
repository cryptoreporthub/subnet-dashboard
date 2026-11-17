"""Telegram Bot API /summary handler — SS-TG W6 (env-gated; not the Telethon listener)."""

from __future__ import annotations

from datetime import datetime, timezone

import json
import html
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_POLL_THREAD: Optional[threading.Thread] = None
_STOP = threading.Event()
_COMMANDS_REGISTERED = False
_COMMANDS_REGISTER_LOCK = threading.Lock()

# BotFather / menu autocomplete — keep in sync with handle_command + build_help_text.
_BOT_MENU_COMMANDS: List[Dict[str, str]] = [
    {"command": "start", "description": "Welcome and command list"},
    {"command": "help", "description": "Show all commands"},
    {"command": "summary", "description": "Market pulse or deep-dive one subnet"},
    {"command": "trending", "description": "ChatterPower trending (24h or 1h)"},
    {"command": "gainers", "description": "Top 5 subnet price gainers (24h)"},
    {"command": "rank", "description": "Subnet trending position"},
    {"command": "track", "description": "Pin a subnet to your watchlist"},
    {"command": "alerts", "description": "Toggle watchlist push alerts on/off"},
    {"command": "link", "description": "Connect My Desk with a link code"},
    {"command": "who", "description": "30-day author reliability leaderboard"},
    {"command": "subnetsummers", "description": "Full SubnetSummer write-ups"},
]
_RATE_LIMIT_SECONDS = 300
_last_summary_at: Dict[int, float] = {}
_last_command_at: Dict[tuple[str, int], float] = {}
_RUNNING = False

_ENABLED = frozenset({"1", "true", "yes", "on"})

# Telegram hard-caps message text at 4096 characters.
_TELEGRAM_TEXT_LIMIT = 4096


def _clamp_telegram_text(text: str, *, limit: int = _TELEGRAM_TEXT_LIMIT) -> str:
    """Trim on line boundaries so HTML tags are never cut mid-token."""
    if len(text) <= limit:
        return text
    marker = "\n…"
    kept: List[str] = []
    used = 0
    for line in text.split("\n"):
        add = len(line) + (1 if kept else 0)
        if used + add + len(marker) > limit:
            break
        kept.append(line)
        used += add
    if not kept:
        return text[: max(0, limit - len(marker))] + marker
    return "\n".join(kept) + marker


def summary_bot_enabled() -> bool:
    from internal.run_mode import stage2_hop_mode

    if stage2_hop_mode():
        return False
    return os.environ.get("TELEGRAM_SUMMARY_BOT", "off").strip().lower() in _ENABLED


def _bot_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _desk_url() -> str:
    """Canonical Telegram desk URL — OG tags live on /subnetsummer (not homepage hash)."""
    base = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    if base:
        return f"{base}/subnetsummer"
    return "https://subnet-dashboard.fly.dev/subnetsummer"


def _full_desk_url() -> str:
    return _desk_url()


def _register_bot_commands() -> bool:
    """Publish slash commands to Telegram (menu autocomplete). Idempotent per process."""
    global _COMMANDS_REGISTERED
    with _COMMANDS_REGISTER_LOCK:
        if _COMMANDS_REGISTERED:
            return True
        resp = _telegram_api("setMyCommands", {"commands": _BOT_MENU_COMMANDS})
        ok = bool(resp.get("ok"))
        if ok:
            logger.info(
                "Telegram summary bot: registered %d bot commands (setMyCommands)",
                len(_BOT_MENU_COMMANDS),
            )
            _COMMANDS_REGISTERED = True
        else:
            logger.info(
                "Telegram summary bot: setMyCommands failed: %s",
                resp.get("error") or resp,
            )
        return ok


def _telegram_api(method: str, payload: Dict[str, Any], *, timeout: float = 35.0) -> Dict[str, Any]:
    token = _bot_token()
    if not token:
        return {"ok": False, "error": "missing_token"}
    url = f"https://api.telegram.org/bot{token}/{method}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "subnet-dashboard-summary-bot"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = str(exc)
        return {"ok": False, "status": exc.code, "error": detail}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _registry_subnet_names() -> Dict[int, str]:
    from internal.message_intel.engine import _registry_subnet_names

    return _registry_subnet_names()


def _parse_command_text(text: str) -> tuple[str, str]:
    parts = str(text or "").strip().split(maxsplit=1)
    cmd = parts[0].split("@", 1)[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""
    return cmd, arg


def _command_rate_limit(key: tuple[str, int], seconds: int = 60) -> Optional[str]:
    now = time.monotonic()
    last = _last_command_at.get(key, 0.0)
    if now - last < seconds:
        return "Please wait a moment before using that command again."
    _last_command_at[key] = now
    return None


def _subnet_from_arg(arg: str) -> Optional[int]:
    m = re.search(r"\b(?:sn|subnet)?\s*(\d+)\b", str(arg or ""), re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _format_error(msg: str) -> str:
    return f"<b>Subnet Summers</b>\n\n{msg}"


def build_help_text() -> str:
    lines = [
        "<b>🤖 Subnet Summers Bot</b>",
        "",
        "Your intel desk for Bittensor subnets — trending movers, subnet stats, and the people calling them.",
        "",
        "<b>Commands</b>",
        "📊 /summary — 24h pulse: chatter, gainers, calls, council pick",
        "📊 /summary &lt;sn&gt; — deep-dive on one subnet (e.g. /summary 62)",
        "🔥 /trending — ChatterPower trending, last 24h",
        "🔥 /trending 1h — fast-moving 1-hour window",
        "📈 /gainers — top 5 subnet price gainers, last 24h",
        "🥇 /rank &lt;sn&gt; — a subnet's trending position",
        "📌 /track &lt;sn&gt; — pin a subnet to your watchlist",
        "🔔 /alerts on|off — toggle your watchlist alerts",
        "🔗 /link &lt;code&gt; — connect My Desk for personalized tracking",
        "👥 /who — 30-day author reliability leaderboard",
        "📝 /subnetsummers — full SubnetSummer write-ups",
        "",
        "💬 Posting any command registers this chat for push alerts —",
        "including the 🚨 <b>New #1 Trending</b> takeover alert.",
    ]
    return "\n".join(lines)




def _format_gainers_reply(db=None) -> str:
    """Top 5 subnets by 24h price change — honest-empty when price data is down."""
    from fetchers.merged_data import get_merged_subnet_rows_quick

    try:
        rows = get_merged_subnet_rows_quick() or []
    except Exception as exc:
        logger.warning("gainers fetch failed: %s", exc)
        rows = []
    gainers = _top_gainers(rows)
    if not gainers:
        return _format_error("No 24h price-change data available right now — try again shortly.")
    lines = ["📈 <b>Top 5 gainers — last 24h</b>", ""]
    for i, r in enumerate(gainers, 1):
        price = _local_float(r.get("price"))
        price_bit = f" · {price}τ" if price else ""
        lines.append(
            f"{i}. {_subnet_label(r.get('netuid'), r.get('name'))} · "
            f"{r['price_change_24h']:+.2f}%{price_bit}"
        )
    lines.append("")
    lines.append(f'<a href="{_desk_url()}">Open the Subnet Summers desk</a>')
    return "\n".join(lines)


def _format_trending(items: list[Dict[str, Any]], window: str) -> str:
    lines = [f"<b>ChatterPower Trending — {window}</b>", ""]
    if not items:
        lines.append("No trending subnets found in that window.")
    for row in items[:5]:
        lines.append(
            f"• SN{row.get('netuid')} {row.get('name') or ''} "
            f"({row.get('mentions', 0)} mentions, power {row.get('chatter_power', 0)})"
        )
    return "\n".join(lines)


def _format_summary_reply(db=None) -> str:
    return build_summary_text(db=db)


def _format_subnet_summary_reply(netuid: int, db=None) -> str:
    from internal.message_intel.rollup import build_subnet_telegram_conviction

    payload = build_subnet_telegram_conviction(netuid=netuid, limit=1, db=db)
    item = next((row for row in payload.get("items") or [] if int(row.get("netuid") or 0) == int(netuid)), None)
    if not item or not item.get("current_calls"):
        return _format_error(f"No recent qualified Telegram calls for SN{netuid}.")
    label = item.get("label") or "mixed"
    lines = [
        f"<b>SN{netuid} Telegram summary</b>",
        "",
        f"Current read: {label} · {item.get('call_count', 0)} calls from {item.get('contributor_count', 0)} contributors",
    ]
    for call in (item.get("current_calls") or [])[:3]:
        direction = str(call.get("direction") or "neutral").upper()
        snippet = str(call.get("content") or "").strip().replace("<", "&lt;").replace(">", "&gt;")
        if len(snippet) > 140:
            snippet = snippet[:137].rstrip() + "…"
        lines.append(f"• {direction} — {snippet or 'call recorded'}")
    lines.extend(["", "Evidence-qualified community commentary; not financial advice."])
    return "\n".join(lines)


def _format_rank(item: Dict[str, Any]) -> str:
    if not item:
        return _format_error("No matching subnet found.")
    return (
        f"<b>Subnet Rank — SN{item.get('netuid')}</b>\n\n"
        f"{item.get('name') or ''}\n"
        f"Mentions: {item.get('mentions', 0)}\n"
        f"ChatterPower: {item.get('chatter_power', 0)}\n"
        f"Why: {item.get('why') or 'n/a'}"
    )


def _format_accuracy_pct(rate: Any) -> str:
    if rate is None:
        return "n/a"
    try:
        value = float(rate)
    except (TypeError, ValueError):
        return "n/a"
    if value == int(value):
        return f"{int(value)}%"
    return f"{value:.1f}%"


def _author_display_name(item: Dict[str, Any]) -> str:
    name = str(item.get("author_name") or "").strip()
    if name:
        return html.escape(name)
    username = str(item.get("author_username") or "").strip().lstrip("@")
    if username:
        return f"@{html.escape(username)}"
    author_id = str(item.get("author_id") or "").strip()
    return html.escape(author_id or "Unknown")


def _format_author_line(item: Dict[str, Any], rank: int) -> str:
    calls = int(item.get("total_graded_calls") or item.get("graded") or 0)
    return (
        f"{rank}. {_author_display_name(item)} – "
        f"{calls} {'call' if calls == 1 else 'calls'}, "
        f"{_format_accuracy_pct(item.get('accuracy_pct'))} accuracy"
    )


def _format_author_leaderboard(rows: List[Dict[str, Any]], *, limit: int = 3) -> str:
    qualified = [
        row
        for row in rows
        if int(row.get("total_graded_calls") or row.get("graded") or 0) > 0
    ]
    qualified.sort(
        key=lambda row: (
            int(row.get("total_graded_calls") or row.get("graded") or 0),
            float(row.get("accuracy_pct") or 0.0),
        ),
        reverse=True,
    )
    top = qualified[:limit]
    if not top:
        return _format_error("No graded callers yet — leaderboard fills as calls resolve.")
    lines = ["<b>Author Leaderboard</b>", ""]
    for index, row in enumerate(top, 1):
        lines.append(_format_author_line(row, index))
    return "\n".join(lines)


def _format_author(item: Dict[str, Any], *, rank: int = 1) -> str:
    if not item:
        return _format_error("No matching author found.")
    return f"<b>Author Leaderboard</b>\n\n{_format_author_line(item, rank)}"


def _watchlist_load(owner=None):
    from internal.watchlist.store import load_watchlist

    return load_watchlist() if owner is None else load_watchlist(owner=owner)


def _watchlist_save(netuids, thresholds=None, alerts=None, owner=None):
    from internal.watchlist.store import save_watchlist

    if owner is None:
        return save_watchlist(netuids, thresholds=thresholds, alerts=alerts)
    return save_watchlist(netuids, thresholds=thresholds, alerts=alerts, owner=owner)


def _stable_telegram_user(message: Dict[str, Any]) -> str:
    from internal.message_intel.proof import stable_author_id

    return stable_author_id(message)


def _telegram_watchlist_owner(message: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(message, dict):
        return None
    telegram_owner = f"telegram:{_stable_telegram_user(message)}"
    from internal.watchlist.store import linked_owner

    return linked_owner(telegram_owner) or telegram_owner


def _subnet_label(netuid: Any, name: Any) -> str:
    """'SN39 (deprecated)' — never 'SN39 SN39 (deprecated)'.

    Registry names sometimes already carry the SN# prefix; guard so the
    prefix is applied exactly once.
    """
    sn = f"SN{netuid}"
    raw = str(name or "").strip()
    if not raw or raw.upper() == sn.upper() or raw.upper().startswith(f"{sn} "):
        label = raw or sn
    else:
        label = f"{sn} {raw}"
    return html.escape(label)


def _format_subnet_chip(row: Dict[str, Any]) -> str:
    label = _subnet_label(row.get("netuid"), row.get("name"))
    mentions = int(row.get("mentions") or 0)
    mention_word = "mention" if mentions == 1 else "mentions"
    bits = [f"{mentions} {mention_word}"]
    chg = row.get("price_change_24h")
    if chg is None:
        chg = row.get("price_change_1h")
        suffix = " 1h"
    else:
        suffix = " 24h"
    if chg is not None:
        try:
            p = float(chg)
            sign = "+" if p > 0 else ""
            bits.append(f"{sign}{p:.1f}%{suffix}")
        except (TypeError, ValueError):
            pass
    return f"{label} ({', '.join(bits)})"


def _format_pulse_line(summary: Dict[str, Any]) -> str:
    pulse = summary.get("group_pulse") or {}
    sentiment = pulse.get("sentiment") or "Mixed"
    return (
        f"{sentiment} · "
        f"{summary.get('message_count', 0)} msgs · "
        f"{summary.get('high_conviction_count', 0)} high-conviction"
    )


def _pct_bit(value: Any, *, suffix: str = "") -> str:
    try:
        p = float(value)
    except (TypeError, ValueError):
        return ""
    sign = "+" if p > 0 else ""
    return f"{sign}{p:.1f}%{suffix}"


def _useful_snippet(text: Any, *, max_len: int = 90) -> str:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(raw) < 24:
        return ""
    lowered = raw.lower()
    if "not specified" in lowered or "people argued" in lowered or "people split" in lowered:
        return ""
    if raw.endswith("…") and ("which means" in lowered or "means there is" in lowered):
        return ""
    if len(raw) > max_len:
        raw = raw[: max_len - 1].rstrip() + "…"
    return raw


def _price_rows() -> List[Dict[str, Any]]:
    try:
        from fetchers.merged_data import get_merged_subnet_rows_quick

        return get_merged_subnet_rows_quick() or []
    except Exception as exc:
        logger.warning("summary price rows failed: %s", exc)
        return []


def _price_by_netuid(rows: Optional[List[Dict[str, Any]]] = None) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for row in rows if rows is not None else _price_rows():
        try:
            netuid = int(row.get("netuid"))
        except (TypeError, ValueError):
            continue
        out[netuid] = row
    return out


def _enrich_subnet_prices(rows: List[Dict[str, Any]], prices: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            netuid = int(item.get("netuid"))
        except (TypeError, ValueError):
            enriched.append(item)
            continue
        px = prices.get(netuid) or {}
        if item.get("price_change_24h") is None and px.get("price_change_24h") is not None:
            item["price_change_24h"] = px.get("price_change_24h")
        if item.get("price_change_1h") is None and px.get("price_change_1h") is not None:
            item["price_change_1h"] = px.get("price_change_1h")
        if item.get("price") is None and px.get("price") is not None:
            item["price"] = px.get("price")
        if not item.get("name") and px.get("name"):
            item["name"] = px.get("name")
        enriched.append(item)
    return enriched


def _top_gainers(rows: List[Dict[str, Any]], *, limit: int = 5) -> List[Dict[str, Any]]:
    ranked = sorted(
        (
            r
            for r in rows
            if isinstance(r.get("price_change_24h"), (int, float)) and r["price_change_24h"] > 0
        ),
        key=lambda r: r["price_change_24h"],
        reverse=True,
    )
    return ranked[:limit]


def _published_daily_pick() -> Optional[Dict[str, Any]]:
    try:
        from internal.council.daily_pick_engine import _find_today, _load

        rec = _find_today(_load())
    except Exception as exc:
        logger.warning("summary daily pick read failed: %s", exc)
        return None
    return rec if isinstance(rec, dict) else None


def _format_pick_block(rec: Optional[Dict[str, Any]]) -> str:
    if not rec:
        return ""
    action = str(rec.get("action") or "").upper()
    pick = rec.get("pick") if isinstance(rec.get("pick"), dict) else {}
    if not pick:
        cand = rec.get("candidate")
        pick = cand if isinstance(cand, dict) else {}
    subnet = pick.get("subnet") if isinstance(pick.get("subnet"), dict) else {}
    netuid = subnet.get("netuid") or pick.get("netuid")
    name = subnet.get("name") or pick.get("name")
    conf = pick.get("confidence") or rec.get("confidence")
    if action == "HOLD" or netuid is None:
        reason = str(rec.get("reason") or rec.get("hold_reason") or "").strip()
        line = "HOLD"
        if reason:
            line += f" · {html.escape(reason[:80])}"
        return "\n".join(["<b>Council pick</b>", f"• {line}"])
    conf_bit = ""
    try:
        if conf is not None:
            c = float(conf)
            conf_bit = f" · {int(round(c * 100)) if c <= 1 else int(round(c))}%"
    except (TypeError, ValueError):
        pass
    return "\n".join(
        [
            "<b>Council pick</b>",
            f"• {_subnet_label(netuid, name)} · {html.escape(action or 'LONG')}{conf_bit}",
        ]
    )


def _format_calls_block(calls: List[Dict[str, Any]]) -> str:
    if not calls:
        return ""
    lines = ["<b>Calls</b>"]
    for row in calls[:3]:
        direction = str(row.get("direction") or "call").upper()
        if direction in ("UP", "BULLISH"):
            direction = "UP"
        elif direction in ("DOWN", "BEARISH"):
            direction = "DOWN"
        subnet = ""
        if row.get("netuid") is not None:
            subnet = f" {_subnet_label(row.get('netuid'), row.get('subnet_name'))}"
        conv = row.get("conviction")
        conv_bit = ""
        try:
            if conv is not None:
                conv_bit = f" · {int(float(conv))}%"
        except (TypeError, ValueError):
            pass
        snippet = _useful_snippet(row.get("content"), max_len=80)
        line = f"• {html.escape(direction)}{subnet}{conv_bit}"
        if snippet:
            line += f"\n   <i>{html.escape(snippet, quote=False)}</i>"
        lines.append(line)
    return "\n".join(lines)


def _format_gainers_block(gainers: List[Dict[str, Any]]) -> str:
    if not gainers:
        return ""
    lines = ["<b>Gainers 24h</b>"]
    for i, row in enumerate(gainers[:5], 1):
        pct = _pct_bit(row.get("price_change_24h"))
        price = _local_float(row.get("price"))
        price_bit = f" · {price:g}τ" if price else ""
        lines.append(f"{i}. {_subnet_label(row.get('netuid'), row.get('name'))} · {pct}{price_bit}")
    return "\n".join(lines)


def _format_chatter_block(top: List[Dict[str, Any]]) -> str:
    if not top:
        return ""
    lines = ["<b>Chatter</b>"]
    for i, row in enumerate(top[:5], 1):
        lines.append(f"{i}. {_format_subnet_chip(row)}")
        snippet = _useful_snippet(row.get("mention_context"))
        if snippet:
            lines.append(f"   <i>{html.escape(snippet, quote=False)}</i>")
    return "\n".join(lines)


def _reaction_count_from_line(line: str) -> int:
    match = re.search(r"\bwith\s+(\d+)\b", line)
    return int(match.group(1)) if match else 0


def format_summary_message(summary: Dict[str, Any], *, desk_url: Optional[str] = None) -> str:
    """24h pulse: chatter + prices + calls + pick. Skip template recap."""
    desk = desk_url or _desk_url()
    if not summary.get("ready"):
        count = int(summary.get("message_count") or 0)
        need = int(summary.get("min_messages") or 10)
        return (
            f"<b>Subnet Summers · 24h</b>\n"
            f"Not enough chatter yet ({count}/{need} messages in 24h). "
            f"Check back when the group is active.\n"
            f'<a href="{desk}">Open the Subnet Summers desk</a>'
        )

    blocks = [
        "<b>Subnet Summers · 24h</b>",
        f"<i>{html.escape(_format_pulse_line(summary), quote=False)}</i>",
    ]
    chatter = _format_chatter_block(summary.get("top_subnets") or [])
    if chatter:
        blocks.extend(["", chatter])
    gainers = _format_gainers_block(summary.get("gainers") or [])
    if gainers:
        blocks.extend(["", gainers])
    calls = _format_calls_block(summary.get("calls") or [])
    if calls:
        blocks.extend(["", calls])
    pick = _format_pick_block(summary.get("daily_pick"))
    if pick:
        blocks.extend(["", pick])
    leaders = [
        str(x).strip()
        for x in (summary.get("reaction_leaders") or [])
        if str(x).strip() and _reaction_count_from_line(str(x)) >= 3
    ]
    if leaders:
        blocks.extend(
            [
                "",
                "<b>Reactions</b>",
                *[f"• {html.escape(line, quote=False)}" for line in leaders[:3]],
            ]
        )
    blocks.extend(
        [
            "",
            "<i>Not financial advice · /gainers · /trending · /summary 55</i>",
            f'<a href="{desk}">Open the Subnet Summers desk</a>',
        ]
    )
    return "\n".join(blocks)


def _parse_iso(value: Any) -> Optional[datetime]:
    """Best-effort ISO-8601 parse; returns None for anything unusable."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _telegram_age(value: Any) -> str:
    """Compact relative age such as "2h ago"; empty when unparseable."""
    parsed = _parse_iso(value)
    if parsed is None:
        return ""
    secs = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _thousands(value: Any) -> str:
    try:
        return f"{int(value or 0):,}"
    except (TypeError, ValueError):
        return "0"


def _section_rule(title: str, width: int = 30) -> str:
    """A light divider under a section title, e.g. "<b>TOP SUBNETS</b> ─────"."""
    label = html.escape(title)
    pad = max(2, width - len(title) - 1)
    return f"<b>{label}</b> {chr(9472) * pad}"


def _local_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _rank_meta(row: Dict[str, Any]) -> str:
    parts = [f"{int(row.get('mentions') or 0)} mentions"]
    authors = row.get("authors")
    if authors:
        count = int(authors)
        parts.append(f"{count} {'author' if count == 1 else 'authors'}")
    return " · ".join(parts)


def _rank_mood(row: Dict[str, Any]) -> str:
    mood = html.escape(str(row.get("sentiment") or "Cautious"))
    delta = _local_float(row.get("delta"))
    arrow = chr(9650) if delta > 0 else (chr(9660) if delta < 0 else "·")
    return f"{mood} · {arrow} {delta:+.2f} vs prior window"

def build_subnetsummers_text(*, db=None) -> str:
    """Render the complete, bounded Telegram desk in one response."""
    from internal.message_intel.rollup import (
        build_24h_summary,
        build_author_reliability_rows,
        build_high_conviction_strip,
        build_reaction_crowns,
        build_trending_subnets,
    )

    from internal.message_intel.load_guard import LoadTimeout

    names = _registry_subnet_names()
    summary = build_24h_summary(registry_names=names, db=db)
    try:
        trending = build_trending_subnets(
            registry_names=names,
            limit=5,
            rank_hours=24,
            window_hours=24,
            db=db,
        )
    except LoadTimeout:
        trending = []
    chatter = build_high_conviction_strip(
        limit=5,
        min_conviction=60.0,
        db=db,
        registry_names=names,
    )
    crowns = build_reaction_crowns(days=7, db=db)
    desk = _full_desk_url()

    stamp = datetime.now(timezone.utc).strftime("%a %d %b")
    lines = [
        "<b>" + chr(10022) + " SUBNET SUMMERS — FULL DESK</b>",
        (
            f"{stamp} · last 24h · "
            f"{_thousands(summary.get('message_count'))} messages · "
            f"{_thousands(summary.get('high_conviction_count'))} high-conviction"
        ),
        "",
        _section_rule("TOP SUBNETS"),
    ]
    if trending:
        for index, row in enumerate(trending, 1):
            why = html.escape(str(row.get("why") or "chatter power"))
            lines.append(
                f"{index}. {_subnet_label(row.get('netuid'), row.get('name'))} · "
                f"{_rank_meta(row)}"
            )
            lines.append(f"   <i>{why}</i> · {_rank_mood(row)}")
    else:
        lines.append("No subnet ranks yet — the source needs explicit SN# or Subnet # mentions.")

    lines.extend(["", _section_rule("HIGH-CONVICTION CHATTER")])
    if chatter:
        for row in chatter:
            direction = html.escape(str(row.get("direction") or "neutral").upper())
            snippet = html.escape(str(row.get("content") or "call recorded").strip())
            if len(snippet) > 110:
                snippet = snippet[:107].rstrip() + chr(8230)
            netuid = row.get("netuid")
            subnet = (
                f" · {_subnet_label(netuid, row.get('subnet_name'))}"
                if netuid is not None
                else ""
            )
            lines.append(
                f"• <b>{direction}</b>{subnet} · {row.get('conviction', 0)}% conviction"
            )
            lines.append(f"   <i>{snippet}</i>")
            handle = str(row.get("author_username") or "").strip()
            who = f"@{handle.lstrip('@')}" if handle else str(row.get("author_name") or "Unknown")
            attribution = " · ".join(
                part
                for part in (html.escape(who), _telegram_age(row.get("timestamp")))
                if part
            )
            if attribution:
                lines.append(f"   {attribution}")
    else:
        lines.append("No high-conviction chatter yet.")

    lines.extend(["", _section_rule("CALL LEADERS — 30d")])
    try:
        reliability_rows = build_author_reliability_rows(days=30, limit=8, db=db)
        qualified = [
            row
            for row in reliability_rows
            if int(row.get("total_graded_calls") or row.get("graded") or 0) > 0
        ]
        qualified.sort(
            key=lambda row: (
                int(row.get("total_graded_calls") or row.get("graded") or 0),
                float(row.get("accuracy_pct") or 0.0),
            ),
            reverse=True,
        )
        if qualified:
            for index, row in enumerate(qualified[:3], 1):
                lines.append(f"• {_format_author_line(row, index)}")
        else:
            lines.append("No graded calls yet — call leaders appear as calls resolve.")
    except Exception as exc:
        logger.warning("subnetsummers call leaders failed: %s", exc)
        lines.append("No graded calls yet — call leaders appear as calls resolve.")

    lines.extend(["", _section_rule("REACTION CROWNS — 7d")])
    if crowns:
        for row in crowns[:5]:
            handle = html.escape(
                str(row.get("display_name") or row.get("author_name") or "Unknown")
            )
            lines.append(
                f"• {html.escape(str(row.get('emoji') or ''))} "
                f"{html.escape(str(row.get('label') or row.get('key') or 'Reaction'))}: "
                f"{handle} ({row.get('count', 0)})"
            )
    else:
        lines.append("No reaction leaders yet — reaction metrics have not arrived.")

    lines.extend(["", "<i>Windows differ per section · Not financial advice</i>"])
    link = f'<a href="{desk}">Open the full Subnet Summers desk</a>'
    body = _clamp_telegram_text(
        "\n".join(lines), limit=max(0, _TELEGRAM_TEXT_LIMIT - len(link) - 2)
    )
    return f"{body}\n\n{link}"

def build_summary_text(*, db=None) -> str:
    from internal.message_intel.rollup import (
        build_24h_summary,
        build_high_conviction_strip,
        build_today_reaction_leaders,
        format_today_reaction_leader_lines,
    )

    names = _registry_subnet_names()
    summary = build_24h_summary(registry_names=names, db=db)
    prices = _price_by_netuid()
    summary["top_subnets"] = _enrich_subnet_prices(summary.get("top_subnets") or [], prices)
    summary["gainers"] = _top_gainers(list(prices.values()))
    try:
        summary["calls"] = build_high_conviction_strip(
            limit=3, min_conviction=70.0, db=db, registry_names=names
        )
    except Exception as exc:
        logger.warning("summary high-conviction strip failed: %s", exc)
        summary["calls"] = []
    summary["daily_pick"] = _published_daily_pick()
    summary["reaction_leaders"] = format_today_reaction_leader_lines(
        build_today_reaction_leaders(db=db)
    )
    return format_summary_message(summary)


def _rate_limit_reply(chat_id: int) -> Optional[str]:
    now = time.monotonic()
    last = _last_summary_at.get(chat_id)
    elapsed = now - last if last is not None else _RATE_LIMIT_SECONDS
    if last is not None and elapsed < _RATE_LIMIT_SECONDS:
        remaining = int(_RATE_LIMIT_SECONDS - elapsed)
        mins = max(1, (remaining + 59) // 60)
        return f"Rate limited — one /summary every 5 minutes. Try again in ~{mins} min."
    _last_summary_at[chat_id] = now
    return None


def handle_summary_command(chat_id: int, *, db=None) -> tuple[str, bool]:
    """Return (text, rate_limited)."""
    limited = _rate_limit_reply(chat_id)
    if limited:
        return limited, True
    return _format_summary_reply(db=db), False


def handle_command(text: str, *, message: Optional[Dict[str, Any]] = None, db=None) -> Optional[str]:
    cmd, arg = _parse_command_text(text)
    if cmd == "/help" or cmd == "/start":
        return build_help_text()
    if cmd == "/subnetsummers":
        return build_subnetsummers_text(db=db)
    if cmd == "/summary":
        subnet = _subnet_from_arg(arg)
        if subnet is not None:
            return _format_subnet_summary_reply(subnet, db=db)
        return _format_summary_reply(db=db)
    if cmd == "/gainers":
        return _format_gainers_reply(db=db)
    if cmd == "/trending":
        window = "1h" if arg.strip() == "1h" else "24h"
        from internal.message_intel.load_guard import LoadTimeout
        from internal.message_intel.rollup import build_trending_subnets

        try:
            items = build_trending_subnets(
                limit=5, rank_hours=1 if window == "1h" else 24, window_hours=24
            )
        except LoadTimeout:
            return _format_error("Trending data is temporarily unavailable.")
        return _format_trending(items, window)
    if cmd == "/track":
        subnet = _subnet_from_arg(arg)
        if subnet is None:
            return _format_error("Usage: /track <subnet>")
        owner = _telegram_watchlist_owner(message)
        watch = _watchlist_load(owner) if owner is not None else _watchlist_load()
        pins = list(watch.get("netuids") or [])
        if subnet not in pins:
            pins.append(subnet)
            if owner is None:
                _watchlist_save(pins, thresholds=watch.get("thresholds") or {}, alerts=watch.get("alerts") or {})
            else:
                _watchlist_save(pins, thresholds=watch.get("thresholds") or {}, alerts=watch.get("alerts") or {}, owner=owner)
        return _format_error(f"Added SN{subnet} to watchlist.")
    if cmd == "/link":
        code = str(arg or "").strip().upper()
        if not code or message is None:
            return _format_error("Usage: /link <code from My Desk>")
        telegram_owner = f"telegram:{_stable_telegram_user(message)}"
        from internal.watchlist.store import claim_link_code

        if not claim_link_code(code, telegram_owner):
            return _format_error("That link code is invalid or already used.")
        return _format_error("Telegram watchlist sync is linked. Your /track and /alerts settings now use My Desk.")
    if cmd == "/rank":
        subnet = _subnet_from_arg(arg)
        from internal.message_intel.load_guard import LoadTimeout
        from internal.message_intel.rollup import build_trending_subnets

        try:
            items = build_trending_subnets(limit=50, rank_hours=1, window_hours=24)
        except LoadTimeout:
            return _format_error("Rank data is temporarily unavailable.")
        row = next((r for r in items if subnet is not None and int(r.get("netuid") or 0) == subnet), {})
        return _format_rank(row)
    if cmd == "/who":
        from internal.message_intel.rollup import build_author_reliability_rows

        rows = build_author_reliability_rows(days=30, limit=25)
        author = arg.strip().lstrip("@")
        if not author:
            return _format_author_leaderboard(rows, limit=3)
        row = next(
            (
                r
                for r in rows
                if author.lower()
                in {
                    str(r.get("author_name") or "").lower(),
                    str(r.get("author_username") or "").lower().lstrip("@"),
                    str(r.get("author_id") or "").lower(),
                }
            ),
            None,
        )
        return _format_author(row or {})
    if cmd == "/alerts" and message is not None:
        parts = arg.lower().split()
        if not parts or parts[0] not in {"on", "off"}:
            return _format_error("Usage: /alerts on|off")
        owner = _telegram_watchlist_owner(message)
        watch = _watchlist_load(owner) if owner is not None else _watchlist_load()
        user_key = _stable_telegram_user(message)
        alerts = dict(watch.get("alerts") or {})
        alerts[user_key] = {"enabled": parts[0] == "on"}
        if owner is None:
            _watchlist_save(watch.get("netuids") or [], thresholds=watch.get("thresholds") or {}, alerts=alerts)
        else:
            _watchlist_save(
                watch.get("netuids") or [],
                thresholds=watch.get("thresholds") or {},
                alerts=alerts,
                owner=owner,
            )
        return _format_error(f"Alerts turned {parts[0]} for your Telegram identity.")
    return None


def _message_has_desk_link(text: str) -> bool:
    lowered = text.lower()
    return "subnetsummer" in lowered and "<a href=" in lowered


def send_message(
    chat_id: int,
    text: str,
    *,
    parse_mode: str = "HTML",
    link_preview: bool = True,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if link_preview:
        payload["disable_web_page_preview"] = False
    else:
        payload["link_preview_options"] = {"is_disabled": True}
    return _telegram_api("sendMessage", payload)


def _process_update(update: Dict[str, Any]) -> None:
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return
    text = str(message.get("text") or "").strip()
    if not text or not text.split()[0].startswith("/"):
        return
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    try:
        chat_id = int(chat_id)
    except (TypeError, ValueError):
        return
    try:
        from internal.message_intel.trend_alert import record_seen_chat

        record_seen_chat(chat_id)
    except Exception as exc:  # best-effort capture; never break command flow
        logger.debug("trend alert chat capture failed: %s", exc)

    cmd, _ = _parse_command_text(text)
    if cmd == "/gainers":
        logger.info("summary bot: handling /gainers chat_id=%s", chat_id)
    rate_key = (cmd or "unknown", chat_id)
    limited = _command_rate_limit(rate_key)
    if limited:
        reply = limited
    else:
        reply = handle_command(text, message=message)
    if reply is None:
        return
    resp = send_message(chat_id, reply, link_preview=not _message_has_desk_link(reply))
    if not resp.get("ok"):
        logger.warning("summary bot send failed chat=%s: %s", chat_id, resp.get("error") or resp)


def _poll_loop() -> None:
    global _RUNNING
    offset = 0
    _RUNNING = True
    logger.info("Telegram summary bot polling started")
    while not _STOP.is_set():
        resp = _telegram_api(
            "getUpdates",
            {"offset": offset, "timeout": 25, "allowed_updates": ["message", "edited_message"]},
            timeout=35.0,
        )
        if not resp.get("ok"):
            err = resp.get("error") or resp
            if resp.get("status") == 409 or "409" in str(err):
                logger.warning(
                    "summary bot getUpdates conflict (409) — another client may be polling: %s",
                    err,
                )
            else:
                logger.warning("summary bot getUpdates failed: %s", err)
            if _STOP.wait(5):
                break
            continue
        for update in resp.get("result") or []:
            if not isinstance(update, dict):
                continue
            offset = int(update.get("update_id", offset)) + 1
            try:
                _process_update(update)
            except Exception as exc:
                logger.warning("summary bot update failed: %s", exc)
    _RUNNING = False
    logger.info("Telegram summary bot polling stopped")


def summary_bot_running() -> bool:
    return _RUNNING and _POLL_THREAD is not None and _POLL_THREAD.is_alive()


def start_summary_bot() -> bool:
    """Start Bot API long-poll loop when env-gated and token present."""
    global _POLL_THREAD
    if not summary_bot_enabled():
        logger.info("Telegram summary bot disabled (TELEGRAM_SUMMARY_BOT=off)")
        return False
    if not _bot_token():
        logger.info("Telegram summary bot skipped — TELEGRAM_BOT_TOKEN not set")
        return False
    if _POLL_THREAD is not None and _POLL_THREAD.is_alive():
        return True

    _register_bot_commands()
    _STOP.clear()
    _POLL_THREAD = threading.Thread(target=_poll_loop, daemon=True, name="telegram-summary-bot")
    _POLL_THREAD.start()
    return True


def stop_summary_bot() -> None:
    global _POLL_THREAD, _COMMANDS_REGISTERED
    _STOP.set()
    if _POLL_THREAD is not None:
        _POLL_THREAD.join(timeout=8)
        _POLL_THREAD = None
    _STOP.clear()
    with _COMMANDS_REGISTER_LOCK:
        _COMMANDS_REGISTERED = False

