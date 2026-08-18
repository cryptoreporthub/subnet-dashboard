"""Telegram Bot API /summary handler — SS-TG W6 (env-gated; not the Telethon listener)."""

from __future__ import annotations

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
_RATE_LIMIT_SECONDS = 300
_last_summary_at: Dict[int, float] = {}
_last_command_at: Dict[tuple[str, int], float] = {}
_RUNNING = False

_ENABLED = frozenset({"1", "true", "yes", "on"})


def summary_bot_enabled() -> bool:
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
    text = str(arg or "")
    m = re.search(r"#\s*(\d{1,4})\b", text)
    if not m:
        m = re.search(r"\b(?:sn|subnet)?\s*(\d+)\b", text, re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _format_error(msg: str) -> str:
    return f"<b>Subnet Summers</b>\n\n{msg}"


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


def _escape_telegram_html(text: str) -> str:
    return str(text or "").strip().replace("<", "&lt;").replace(">", "&gt;")


def _subnet_page_url(netuid: int) -> str:
    base = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    if not base:
        base = "https://subnet-dashboard.fly.dev"
    return f"{base}/subnet/{int(netuid)}"


def _format_subnet_summary_reply(netuid: int, db=None) -> str:
    from internal.message_intel.rollup import (
        build_subnet_chatter_summary,
        build_subnet_telegram_conviction,
    )

    names = _registry_subnet_names()
    nu = int(netuid)
    chatter = build_subnet_chatter_summary(netuid=nu, registry_names=names, db=db)
    if chatter.get("empty"):
        return _format_error(f"No Subnet Summers chatter about SN{nu} in the last 24h.")

    name = html.escape(str(chatter.get("name") or f"Subnet {nu}"))
    mentions = int(chatter.get("mention_count") or 0)
    authors = int(chatter.get("author_count") or 0)
    pulse_bits = [
        f"{mentions} mention{'s' if mentions != 1 else ''}",
        f"{chatter.get('sentiment') or 'Cautious'} mood",
        f"avg confidence {float(chatter.get('avg_conviction') or 0):.0f}%",
    ]
    if authors:
        pulse_bits.append(f"{authors} contributor{'s' if authors != 1 else ''}")

    lines = [
        f"<b>{name} (SN{nu})</b>",
        "",
        f"<i>{' · '.join(pulse_bits)}</i>",
    ]

    bull = int(chatter.get("bullish_mentions") or 0)
    bear = int(chatter.get("bearish_mentions") or 0)
    if bull or bear:
        lines.append(f"Directional chatter: {bull} bullish · {bear} bearish")

    snippets = chatter.get("snippets") or []
    if snippets:
        lines.extend(["", "<b>What they're saying</b>"])
        for snip in snippets[:4]:
            text = _escape_telegram_html(snip.get("content") or "")
            if len(text) > 140:
                text = text[:137].rstrip() + "…"
            conv = snip.get("conviction")
            conv_bit = ""
            try:
                if conv is not None and float(conv) > 0:
                    conv_bit = f" · {int(float(conv))}% conv"
            except (TypeError, ValueError):
                pass
            lines.append(f"• {text}{conv_bit}")

    payload = build_subnet_telegram_conviction(netuid=nu, limit=1, db=db, registry_names=names)
    item = next((row for row in payload.get("items") or [] if int(row.get("netuid") or 0) == nu), None)
    current_calls = (item or {}).get("current_calls") or []
    if current_calls:
        label = item.get("label") or "mixed"
        score = item.get("score")
        score_bit = ""
        if item.get("ready") and score is not None:
            try:
                score_val = float(score)
                score_bit = f" ({'+' if score_val > 0 else ''}{score_val:.0f})"
            except (TypeError, ValueError):
                pass
        lines.extend(
            [
                "",
                (
                    f"<b>Proven-caller consensus</b>: {label}{score_bit} · "
                    f"{item.get('call_count', 0)} calls from {item.get('contributor_count', 0)} callers"
                ),
            ]
        )
        for call in current_calls[:2]:
            direction = str(call.get("direction") or "neutral").upper()
            snippet = _escape_telegram_html(call.get("content") or "")
            if len(snippet) > 100:
                snippet = snippet[:97].rstrip() + "…"
            lines.append(f"• {direction} — {snippet or 'call recorded'}")
    else:
        lines.append("")
        lines.append("<i>No proven-caller directional bets yet — summary is from general chatter.</i>")

    lines.extend(
        [
            "",
            f'<a href="{_subnet_page_url(nu)}">Open SN{nu} on the desk</a>',
            "Community commentary; not financial advice.",
        ]
    )
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
        f"{calls} calls, {_format_accuracy_pct(item.get('accuracy_pct'))} accuracy"
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


def _format_subnet_chip(row: Dict[str, Any]) -> str:
    netuid = row.get("netuid")
    raw_name = str(row.get("name") or "").strip()
    sn = f"SN{netuid}"
    if not raw_name or raw_name.upper() == sn.upper() or raw_name.upper().startswith(f"{sn} "):
        label = html.escape(raw_name or sn)
    else:
        label = f"{sn} {html.escape(raw_name)}"
    mentions = int(row.get("mentions") or 0)
    mention_word = "mention" if mentions == 1 else "mentions"
    bits = [f"{mentions} {mention_word}"]
    price = row.get("price_change_1h")
    if price is not None:
        try:
            p = float(price)
            sign = "+" if p > 0 else ""
            bits.append(f"{sign}{p:.1f}% 1h")
        except (TypeError, ValueError):
            pass
    return f"{label} ({', '.join(bits)})"


def _compose_today_narrative(summary: Dict[str, Any]) -> str:
    today = str(summary.get("today_narrative") or "").strip()
    if today:
        return today
    top = summary.get("top_subnets") or []
    topics = summary.get("today_topics") or []
    labels = [str(t.get("label") or t.get("topic") or "").strip() for t in topics]
    labels = [x for x in labels if x]
    bits: list[str] = []
    if labels:
        if len(labels) == 1:
            joined = labels[0]
        elif len(labels) == 2:
            joined = f"{labels[0]} and {labels[1]}"
        else:
            joined = ", ".join(labels[:-1]) + f", and {labels[-1]}"
        sentence = f"{joined.lower()} took most of the airtime."
        bits.append(sentence[:1].upper() + sentence[1:])
    if top:
        lead = top[0]
        lead_name = lead.get("name") or f"SN{lead.get('netuid')}"
        detail = f"{lead_name} led chatter"
        if len(top) > 1:
            runner = top[1]
            detail += f", ahead of {runner.get('name') or f'SN{runner.get('netuid')}'}"
        ctx = str(lead.get("mention_context") or "").strip()
        if ctx:
            detail += f" — {ctx}"
        bits.append(detail + ".")
    if bits:
        return " ".join(bits)
    pulse = summary.get("group_pulse") or {}
    sentiment = str(pulse.get("sentiment") or "mixed").lower()
    return f"Quiet recap — {summary.get('message_count', 0)} messages, {sentiment} mood."


def _format_pulse_line(summary: Dict[str, Any]) -> str:
    pulse = summary.get("group_pulse") or {}
    sentiment = pulse.get("sentiment") or "Mixed"
    return (
        f"{summary.get('message_count', 0)} msgs · "
        f"{summary.get('high_conviction_count', 0)} high conv · "
        f"{sentiment}"
    )


def _format_stats_block(summary: Dict[str, Any]) -> str:
    """Scan-friendly stats: pulse on one line, top subnets and movers as bullets."""
    lines = [f"<i>{html.escape(_format_pulse_line(summary), quote=False)}</i>"]
    top = summary.get("top_subnets") or []
    if top:
        lines.extend(["", "<b>Top</b>"])
        for row in top[:5]:
            lines.append(f"• {_format_subnet_chip(row)}")
    movers = [m for m in (summary.get("movers") or []) if int(m.get("change") or 0) != 0][:3]
    if movers:
        lines.extend(["", "<b>Movers</b>"])
        for row in movers:
            delta = int(row.get("change") or 0)
            arrow = "↑" if delta > 0 else "↓"
            name = html.escape(str(row.get("name") or f"SN{row.get('netuid')}"))
            lines.append(f"• SN{row.get('netuid')} {name} {arrow}{abs(delta)}")
    return "\n".join(lines)


def _format_bonus_line(summary: Dict[str, Any]) -> str:
    """Legacy single-line stats — prefer _format_stats_block for Telegram."""
    pulse = summary.get("group_pulse") or {}
    sentiment = pulse.get("sentiment") or "Mixed"
    parts = [
        f"{summary.get('message_count', 0)} msgs",
        f"{summary.get('high_conviction_count', 0)} high conv",
        str(sentiment),
    ]
    top = summary.get("top_subnets") or []
    if top:
        parts.append("Top " + " · ".join(_format_subnet_chip(row) for row in top[:5]))
    movers = [m for m in (summary.get("movers") or []) if int(m.get("change") or 0) != 0][:3]
    if movers:
        mover_bits = []
        for row in movers:
            delta = int(row.get("change") or 0)
            arrow = "↑" if delta > 0 else "↓"
            name = html.escape(str(row.get("name") or f"SN{row.get('netuid')}"))
            mover_bits.append(f"SN{row.get('netuid')} {name} {arrow}{abs(delta)}")
        parts.append("Movers " + " · ".join(mover_bits))
    return " · ".join(parts)


def format_summary_message(summary: Dict[str, Any], *, desk_url: Optional[str] = None) -> str:
    """Conversation recap first; stats in labeled sections below."""
    desk = desk_url or _desk_url()
    if not summary.get("ready"):
        count = int(summary.get("message_count") or 0)
        need = int(summary.get("min_messages") or 10)
        return (
            f"<b>Subnet Summers</b>\n"
            f"Not enough chatter yet ({count}/{need} messages in 24h). "
            f"Check back when the group is active.\n"
            f'<a href="{desk}">Open the Subnet Summers desk</a>'
        )

    today_lines = [str(x).strip() for x in (summary.get("today_lines") or []) if str(x).strip()]
    if today_lines:
        narrative = "\n\n".join(html.escape(line, quote=False) for line in today_lines[:3])
    else:
        narrative = html.escape(_compose_today_narrative(summary), quote=False)
    leaders = [str(x).strip() for x in (summary.get("reaction_leaders") or []) if str(x).strip()]
    leader_block = ""
    if leaders:
        leader_block = (
            "\n\n<b>Leading in reactions</b>\n"
            + "\n".join(
                f"• {html.escape(line, quote=False)}" for line in leaders[:3]
            )
        )
    stats = _format_stats_block(summary)
    return (
        f"<b>Subnet Summers</b>\n\n"
        f"{narrative}"
        f"{leader_block}\n\n"
        f"{stats}\n\n"
        f'<a href="{desk}">Open the Subnet Summers desk</a>'
    )


def build_subnetsummers_text(*, db=None) -> str:
    """Render the complete, bounded Telegram desk in one response."""
    from internal.message_intel.rollup import (
        build_24h_summary,
        build_high_conviction_strip,
        build_reaction_crowns,
        build_trending_subnets,
    )

    names = _registry_subnet_names()
    summary = build_24h_summary(registry_names=names, db=db)
    trending = build_trending_subnets(
        registry_names=names,
        limit=5,
        rank_hours=24,
        window_hours=24,
        db=db,
    )
    chatter = build_high_conviction_strip(
        limit=5,
        min_conviction=60.0,
        db=db,
        registry_names=names,
    )
    crowns = build_reaction_crowns(days=7, db=db)
    desk = _full_desk_url()

    lines = [
        "<b>Subnet Summers — Full desk</b>",
        "",
        (
            f"Messages: {summary.get('message_count', 0)} · "
            f"High conviction: {summary.get('high_conviction_count', 0)}"
        ),
        "",
        "<b>Subnet ranks</b>",
    ]
    if trending:
        for index, row in enumerate(trending, 1):
            name = html.escape(str(row.get("name") or f"Subnet {row.get('netuid')}"))
            why = html.escape(str(row.get("why") or "chatter power"))
            lines.append(
                f"{index}. SN{row.get('netuid')} {name} · "
                f"{row.get('mentions', 0)} mentions · power {row.get('chatter_power', 0)}"
            )
            lines.append(f"   <i>{why}</i>")
    else:
        lines.append("No subnet ranks yet — the source needs explicit SN# or Subnet # mentions.")

    lines.extend(["", "<b>Chatter</b>"])
    if chatter:
        for row in chatter:
            direction = html.escape(str(row.get("direction") or "neutral").upper())
            snippet = html.escape(str(row.get("content") or "call recorded").strip())
            if len(snippet) > 120:
                snippet = snippet[:117].rstrip() + "…"
            subnet = f" · SN{row.get('netuid')}" if row.get("netuid") is not None else ""
            lines.append(
                f"• {direction}{subnet} · {row.get('conviction', 0)}% conviction — {snippet}"
            )
    else:
        lines.append("No high-conviction chatter yet.")

    lines.extend(["", "<b>Reactions</b>"])
    if crowns:
        for row in crowns[:5]:
            handle = html.escape(str(row.get("display_name") or row.get("author_name") or "Unknown"))
            lines.append(
                f"• {html.escape(str(row.get('emoji') or ''))} "
                f"{html.escape(str(row.get('label') or row.get('key') or 'Reaction'))}: "
                f"{handle} ({row.get('count', 0)})"
            )
    else:
        lines.append("No reaction leaders yet — reaction metrics have not arrived.")

    lines.extend(["", f'<a href="{desk}">Open the full Subnet Summers desk</a>'])
    return "\n".join(lines)


def build_summary_text(*, db=None) -> str:
    from internal.message_intel.rollup import (
        build_24h_summary,
        build_today_conversation_summary,
        build_today_reaction_leaders,
        format_today_reaction_leader_lines,
    )

    names = _registry_subnet_names()
    summary = build_24h_summary(registry_names=names, db=db)
    today = build_today_conversation_summary(registry_names=names, db=db)
    summary["today_narrative"] = today.get("narrative") or ""
    summary["today_topics"] = today.get("topics") or []
    summary["today_lines"] = today.get("lines") or []
    summary["reaction_leaders"] = format_today_reaction_leader_lines(
        build_today_reaction_leaders(db=db)
    )
    return format_summary_message(summary)


def _rate_limit_reply(chat_id: int) -> Optional[str]:
    now = time.monotonic()
    last = _last_summary_at.get(chat_id, 0.0)
    elapsed = now - last
    if elapsed < _RATE_LIMIT_SECONDS:
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
    if cmd == "/subnetsummers":
        return build_subnetsummers_text(db=db)
    if cmd == "/summary":
        subnet = _subnet_from_arg(arg)
        if subnet is not None:
            return _format_subnet_summary_reply(subnet, db=db)
        return _format_summary_reply(db=db)
    if cmd == "/trending":
        window = "1h" if arg.strip() == "1h" else "24h"
        from internal.message_intel.rollup import build_trending_subnets

        items = build_trending_subnets(limit=5, rank_hours=1 if window == "1h" else 24, window_hours=24)
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
        from internal.message_intel.rollup import build_trending_subnets

        items = build_trending_subnets(limit=50, rank_hours=1, window_hours=24)
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

    cmd, _ = _parse_command_text(text)
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
            logger.warning("summary bot getUpdates failed: %s", resp.get("error") or resp)
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

    _STOP.clear()
    _POLL_THREAD = threading.Thread(target=_poll_loop, daemon=True, name="telegram-summary-bot")
    _POLL_THREAD.start()
    return True


def stop_summary_bot() -> None:
    global _POLL_THREAD
    _STOP.set()
    if _POLL_THREAD is not None:
        _POLL_THREAD.join(timeout=8)
        _POLL_THREAD = None
    _STOP.clear()
