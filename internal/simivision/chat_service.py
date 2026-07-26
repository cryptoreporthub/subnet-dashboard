"""SimiVision chat — Chutes AI with local explainer fallback (ported from server_original)."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from datastore.learning_engine import LearningEngine
from internal.integrations.clients import chutes_llm_base_url

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 48
_CHAT_TIMEOUT_SEC = float(os.environ.get("SIMIVISION_CHAT_TIMEOUT_SECONDS", "35"))
_INVESTIGATION_TIMEOUT_SEC = float(os.environ.get("SIMIVISION_INVESTIGATION_TIMEOUT_SECONDS", "8"))
_CHAT_CONTEXT_TTL = float(os.environ.get("SIMIVISION_CHAT_CONTEXT_SECONDS", "30"))
_DEFAULT_THIRTY_SPOKES_BASE = "https://api.thirtyspokes.ai/v1"
_CHAT_CONTEXT_CACHE: Dict[str, Any] = {"at": 0.0, "ctx": None}


def sanitize_reply(text: str) -> str:
    """XSS-safe reply text (escape HTML specials)."""
    return html.escape(str(text or ""), quote=False)


def _safe_load_json(directory: str, filename: str, default: Any = None) -> Any:
    path = os.path.join(directory, filename)
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def build_simivision_prompt(message: str, context: Dict[str, Any]) -> str:
    """Fuse user message with live SimiVision + soul_map + on-chain investigation context."""
    top = context.get("simivision_picks", [])
    picks_str = "; ".join(
        f"#{p.get('rank')} {p.get('name')} (SN{p.get('netuid')}) "
        f"emission={p.get('emission')} apy={p.get('apy')} "
        f"chg24h={p.get('price_change_24h')}% conviction={p.get('conviction')} "
        f"rec={p.get('recommendation')}"
        for p in top
    ) or "No picks available"
    weights = context.get("expert_weights", {})
    weights_str = ", ".join(f"{k}={v}" for k, v in weights.items()) or "none"
    investigation = context.get("investigation")
    inv_block = ""
    if investigation:
        payload = investigation.get("report") if isinstance(investigation, dict) and "report" in investigation else investigation
        tools = investigation.get("tools") if isinstance(investigation, dict) else None
        inv_block = f"\nOn-chain investigation data (cite wallets/amounts from this):\n{json.dumps(payload, default=str)[:5000]}\n"
        if tools:
            inv_block += f"Tool results:\n{json.dumps(tools, default=str)[:2000]}\n"
    return (
        "You are SimiVision, an AI analyst for Bittensor subnets with on-chain investigation. "
        "When investigation data is present, answer wallet/sell/transfer questions from those facts. "
        "Say clearly when owner status cannot be confirmed from sells alone.\n\n"
        f"User question: {message}\n\n"
        f"Top SimiVision picks: {picks_str}\n"
        f"Source: {context.get('source', 'unknown')}\n"
        f"Council expert weights (self-learning loop): {weights_str}\n"
        f"{inv_block}"
        "Answer concisely and tie the reasoning back to the picks and expert weights when relevant."
    )


def _wants_investigation(message: str) -> bool:
    """TaoStats path only for explicit on-chain questions — not generic council picks."""
    import re

    text = (message or "").strip()
    if not text:
        return False
    if re.search(r"\b5[A-HJ-NP-Za-km-z1-9]{47,48}\b", text):
        return True
    q = text.lower()
    if any(
        tok in q
        for tok in (
            "wallet",
            "coldkey",
            "undelegate",
            "transfer",
            "trace",
            "seller",
            "selling",
            "who sold",
            "owner",
        )
    ):
        return True
    if "sell" in q and any(w in q for w in ("who", "wallet", "subnet", "sn", "tao")):
        return True
    if re.search(r"\b(?:sn|subnet)\s*\d+\b", text, re.I):
        return True
    return False


def _maybe_investigation_context(message: str) -> Optional[Dict[str, Any]]:
    import re

    if not _wants_investigation(message):
        return None
    netuid = None
    m = re.search(r"\b(?:sn|subnet)\s*(\d+)\b", message, re.I)
    if m:
        netuid = int(m.group(1))
    wallet = None
    wm = re.search(r"\b(5[A-HJ-NP-Za-km-z1-9]{47,48})\b", message)
    if wm:
        wallet = wm.group(1)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(build_investigation_context, message, netuid=netuid, wallet=wallet)
            return fut.result(timeout=_INVESTIGATION_TIMEOUT_SEC)
    except FuturesTimeoutError:
        logger.warning("investigation context timed out after %.0fs", _INVESTIGATION_TIMEOUT_SEC)
        return None
    except Exception as exc:
        logger.debug("investigation context skipped: %s", exc)
        return None


# §Plan Phase 3.3 — composable on-chain tools for chat / API
INVESTIGATION_TOOLS: Dict[str, Any] = {}


def _register_investigation_tools() -> Dict[str, Any]:
    from internal.investigation.service import (
        investigate_owner_check,
        investigate_subnet_sellers,
        investigate_wallet,
        trace_wallet_flow,
    )

    return {
        "get_subnet_sellers": lambda netuid, days=7: investigate_subnet_sellers(int(netuid), limit=50),
        "get_wallet_activity": lambda wallet, days=30: investigate_wallet(wallet, limit=50),
        "trace_transfers": lambda from_wallet, to_wallet=None, days=30: trace_wallet_flow(
            from_wallet, counterparty=to_wallet, limit=50
        ),
        "get_subnet_owner": lambda netuid: investigate_owner_check(int(netuid), []),
    }


def invoke_investigation_tool(name: str, **kwargs: Any) -> Dict[str, Any]:
    """Invoke a named investigation tool (TaoStats-backed)."""
    global INVESTIGATION_TOOLS
    if not INVESTIGATION_TOOLS:
        INVESTIGATION_TOOLS = _register_investigation_tools()
    fn = INVESTIGATION_TOOLS.get(name)
    if not fn:
        return {"status": "error", "error": f"unknown tool: {name}"}
    try:
        result = fn(**kwargs)
        return result if isinstance(result, dict) else {"status": "success", "data": result}
    except Exception as exc:
        logger.warning("investigation tool %s failed: %s", name, exc)
        return {"status": "error", "error": str(exc)}


def build_investigation_context(
    message: str,
    *,
    netuid: Optional[int] = None,
    wallet: Optional[str] = None,
) -> Dict[str, Any]:
    """Structured tool results for chat prompts (plan §3.3)."""
    from internal.investigation.service import build_investigation_report

    report = build_investigation_report(message, netuid=netuid, wallet=wallet)
    tools_used: List[Dict[str, Any]] = []
    q = (message or "").lower()

    if netuid is not None or "subnet" in q or "sn" in q or "sell" in q:
        n = netuid
        if n is None:
            import re

            m = re.search(r"\b(?:sn|subnet)\s*(\d+)\b", message, re.I)
            if m:
                n = int(m.group(1))
        if n is not None:
            tools_used.append({"tool": "get_subnet_sellers", "result": invoke_investigation_tool("get_subnet_sellers", netuid=n)})
            if wallet or "owner" in q:
                from internal.investigation.service import investigate_owner_check

                wallets = [wallet] if wallet else []
                tools_used.append({"tool": "get_subnet_owner", "result": investigate_owner_check(n, wallets)})

    if wallet:
        tools_used.append({"tool": "get_wallet_activity", "result": invoke_investigation_tool("get_wallet_activity", wallet=wallet)})
        if "transfer" in q or "flow" in q or "trace" in q:
            tools_used.append({"tool": "trace_transfers", "result": invoke_investigation_tool("trace_transfers", from_wallet=wallet)})

    return {"report": report, "tools": tools_used}


def _llm_api_key() -> Optional[str]:
    return (
        os.environ.get("CHUTES_API_KEY")
        or os.environ.get("THIRTY_SPOKES_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("LLM_API_KEY")
    )


def _thirty_spokes_chat_config() -> Tuple[str, str]:
    base = (
        os.environ.get("THIRTY_SPOKES_BASE_URL")
        or os.environ.get("THIRTY_SPOKES_API_BASE")
        or _DEFAULT_THIRTY_SPOKES_BASE
    ).rstrip("/")
    model = os.environ.get("THIRTY_SPOKES_MODEL", "auto")
    return base, model


def _post_chat_completion(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    *,
    timeout: int = 20,
) -> Optional[str]:
    import requests

    resp = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are SimiVision, a Bittensor subnet analyst.",
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 400,
        },
        timeout=timeout,
    )
    if resp.status_code != 200:
        logger.warning("LLM API call failed (%s) at %s", resp.status_code, base_url)
        return None
    data = resp.json()
    reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return reply.strip() if reply else None


def call_llm(prompt: str, message: str, context: Dict[str, Any]) -> Tuple[str, bool]:
    """Call Chutes or Thirty Spokes when configured; else local explainer."""
    api_key = _llm_api_key()
    chutes_base = chutes_llm_base_url()
    chutes_model = os.environ.get("CHUTES_MODEL") or os.environ.get(
        "LLM_MODEL", "deepseek-ai/DeepSeek-V3.2-TEE"
    )
    ts_base, ts_model = _thirty_spokes_chat_config()

    if api_key:
        try:
            reply = _post_chat_completion(chutes_base, api_key, chutes_model, prompt)
            if reply:
                return reply, True
            reply = _post_chat_completion(ts_base, api_key, ts_model, prompt)
            if reply:
                return reply, True
        except Exception as exc:
            logger.warning("LLM API call errored (%s); falling back to local explainer", exc)

    try:
        from internal.llm.explainer import generate_ai_response

        return generate_ai_response(message, context), False
    except Exception as exc:
        logger.warning("Local explainer failed (%s); returning canned reply", exc)
        return (
            "SimiVision is online. I can explain top subnet picks, compare APY, "
            "or analyze market trends. What would you like to know?",
            False,
        )


def _light_picks_from_registry(subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fast top-N for chat prompts — avoid full council scoring on the chat path."""
    ranked = sorted(
        [s for s in subnets if isinstance(s, dict) and s.get("netuid") is not None],
        key=lambda s: float(s.get("emission") or 0),
        reverse=True,
    )[:5]
    return [
        {
            "rank": i,
            "name": s.get("name"),
            "netuid": s.get("netuid"),
            "emission": s.get("emission"),
            "apy": s.get("apy"),
            "price_change_24h": s.get("price_change_24h"),
            "conviction": s.get("conviction"),
            "recommendation": s.get("recommendation") or s.get("action"),
        }
        for i, s in enumerate(ranked, 1)
    ]


def build_chat_context() -> Dict[str, Any]:
    """Assemble subnet + learning context for chat (file-backed; no live feed wait)."""
    now = time.monotonic()
    cached = _CHAT_CONTEXT_CACHE.get("ctx")
    if isinstance(cached, dict) and now - float(_CHAT_CONTEXT_CACHE.get("at") or 0) < _CHAT_CONTEXT_TTL:
        return dict(cached)

    from server import _normalize_registry_subnet, load_data

    subnets = [
        _normalize_registry_subnet(s) for s in load_data("config/registry.json").values()
    ]
    source = "registry-fallback"
    top = _light_picks_from_registry(subnets)

    engine = LearningEngine()
    stats = engine.get_stats()
    expert_weights = stats.get("expert_weights", {})

    daily_pick_data = _safe_load_json("data", "daily_picks.json", default=[{}])
    daily_pick = daily_pick_data[0] if daily_pick_data else {}

    ctx = {
        "source": source,
        "simivision_picks": top,
        "market_overview": {"count": len(subnets), "updated_at": None},
        "expert_weights": expert_weights,
        "daily_pick": daily_pick,
    }
    _CHAT_CONTEXT_CACHE["ctx"] = ctx
    _CHAT_CONTEXT_CACHE["at"] = now
    return dict(ctx)


def _display_model(llm_used: bool) -> str:
    if not llm_used:
        return "local-fallback"
    if os.environ.get("THIRTY_SPOKES_API_KEY") and not os.environ.get("CHUTES_API_KEY"):
        model = os.environ.get("THIRTY_SPOKES_MODEL", "auto")
        return f"thirty-spokes/{model}"
    model_tag = os.environ.get("CHUTES_MODEL", "deepseek-ai/DeepSeek-V3.2-TEE")
    return f"chutes/{model_tag.split('/')[-1].lower()}"


def _run_chat_sync(message: str) -> Dict[str, str]:
    """Blocking chat path — run in a worker thread with a hard timeout."""
    if not message.strip():
        return {"reply": "Please provide a question in the `message` field.", "model": ""}

    context = build_chat_context()
    inv = _maybe_investigation_context(message)
    if inv:
        context["investigation"] = inv
    prompt = build_simivision_prompt(message, context)
    reply, llm_used = call_llm(prompt, message, context)
    model = _display_model(llm_used)
    status = "ok" if llm_used else "local-fallback"
    return {"reply": sanitize_reply(reply), "model": model, "status": status}


async def handle_simivision_chat(message: str) -> Dict[str, str]:
    """Run SimiVision chat and return ``{reply, model}`` (XSS-escaped reply)."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_run_chat_sync, message),
            timeout=_CHAT_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.warning("SimiVision chat timed out after %.0fs", _CHAT_TIMEOUT_SEC)
        return {
            "reply": (
                "SimiVision is busy right now — the server is catching up on live data. "
                "Try again in a moment."
            ),
            "model": "",
            "status": "timeout",
        }
    except Exception as exc:
        logger.error("SimiVision chat failed: %s", exc, exc_info=True)
        return {
            "reply": (
                "SimiVision is temporarily unavailable. The Chutes AI service may be "
                "unreachable. Please try again shortly."
            ),
            "model": "",
            "status": "error",
        }


async def iter_simivision_chat_chunks(message: str) -> AsyncIterator[str]:
    """Yield XSS-safe reply chunks for streaming clients."""
    # Mobile proxies drop connections that send no bytes for ~25s; ping first.
    yield ": ok\n\n"
    yield f"event: meta\ndata: {json.dumps({'status': 'thinking'})}\n\n"
    result = await handle_simivision_chat(message)
    reply = result.get("reply") or ""
    model = result.get("model") or ""
    status = result.get("status") or ("ok" if model and model != "local-fallback" else "local-fallback")
    yield f"event: meta\ndata: {json.dumps({'model': model, 'status': status})}\n\n"
    if not reply:
        yield "event: done\ndata: {}\n\n"
        return
    for i in range(0, len(reply), _CHUNK_SIZE):
        chunk = reply[i : i + _CHUNK_SIZE]
        yield f"event: chunk\ndata: {json.dumps({'text': chunk})}\n\n"
    yield "event: done\ndata: {}\n\n"
