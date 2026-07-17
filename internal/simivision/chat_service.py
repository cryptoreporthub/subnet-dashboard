"""SimiVision chat — Chutes AI with local explainer fallback (ported from server_original)."""

from __future__ import annotations

import html
import json
import logging
import os
from typing import Any, AsyncIterator, Dict, Optional, Tuple

from datastore.learning_engine import LearningEngine

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 48


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
        inv_block = f"\nOn-chain investigation data (cite wallets/amounts from this):\n{json.dumps(investigation, default=str)[:6000]}\n"
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


def _maybe_investigation_context(message: str) -> Optional[Dict[str, Any]]:
    import re

    q = (message or "").lower()
    if not any(tok in q for tok in ("wallet", "sell", "selling", "undelegate", "transfer", "owner", "coldkey", "sn", "subnet")):
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
        from internal.investigation.service import build_investigation_report

        return build_investigation_report(message, netuid=netuid, wallet=wallet)
    except Exception as exc:
        logger.debug("investigation context skipped: %s", exc)
        return None


def call_llm(prompt: str, message: str, context: Dict[str, Any]) -> Tuple[str, bool]:
    """Call Chutes/OpenAI-compatible API when configured; else local explainer."""
    api_key = (
        os.environ.get("CHUTES_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("LLM_API_KEY")
    )
    base_url = os.environ.get("CHUTES_BASE_URL") or os.environ.get(
        "LLM_BASE_URL", "https://api.chutes.ai/v1"
    )
    model = os.environ.get("CHUTES_MODEL") or os.environ.get(
        "LLM_MODEL", "deepseek-ai/DeepSeek-V3.2-TEE"
    )

    if api_key:
        try:
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
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if reply:
                    return reply.strip(), True
            logger.warning(
                "LLM API call failed (%s); falling back to local explainer",
                resp.status_code,
            )
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


def build_chat_context() -> Dict[str, Any]:
    """Assemble subnet + learning context for chat (mirrors server_original)."""
    from server import _get_subnets_with_source, _safe_simivision_payload

    subnets, source = _get_subnets_with_source()
    simivision = _safe_simivision_payload()["data"]

    engine = LearningEngine()
    soul_map = engine.load_soul_map()
    stats = engine.get_stats()
    expert_weights = stats.get("expert_weights", {})

    predictions = _safe_load_json("data", "predictions.json", default={}).get(
        "predictions", []
    )
    daily_pick_data = _safe_load_json("data", "daily_picks.json", default=[{}])
    daily_pick = daily_pick_data[0] if daily_pick_data else {}

    top = simivision.get("top", [])
    return {
        "source": source,
        "simivision_picks": top,
        "market_overview": {
            "count": simivision.get("meta", {}).get("count", len(subnets)),
            "updated_at": simivision.get("meta", {}).get("updated_at"),
        },
        "expert_weights": expert_weights,
        "soul_map": soul_map,
        "predictions": predictions,
        "daily_pick": daily_pick,
    }


def _display_model(llm_used: bool) -> str:
    model_tag = os.environ.get("CHUTES_MODEL", "deepseek-ai/DeepSeek-V3.2-TEE")
    if llm_used:
        return f"chutes/{model_tag.split('/')[-1].lower()}"
    return "local-fallback"


async def handle_simivision_chat(message: str) -> Dict[str, str]:
    """Run SimiVision chat and return ``{reply, model}`` (XSS-escaped reply)."""
    if not message.strip():
        return {"reply": "Please provide a question in the `message` field.", "model": ""}

    try:
        context = build_chat_context()
        inv = _maybe_investigation_context(message)
        if inv:
            context["investigation"] = inv
        prompt = build_simivision_prompt(message, context)
        reply, llm_used = call_llm(prompt, message, context)
        return {"reply": sanitize_reply(reply), "model": _display_model(llm_used)}
    except Exception as exc:
        logger.error("SimiVision chat failed: %s", exc, exc_info=True)
        return {
            "reply": (
                "SimiVision is temporarily unavailable. The Chutes AI service may be "
                "unreachable. Please try again shortly."
            ),
            "model": "",
        }


async def iter_simivision_chat_chunks(message: str) -> AsyncIterator[str]:
    """Yield XSS-safe reply chunks for streaming clients."""
    result = await handle_simivision_chat(message)
    reply = result.get("reply") or ""
    model = result.get("model") or ""
    yield f"event: meta\ndata: {json.dumps({'model': model})}\n\n"
    if not reply:
        yield "event: done\ndata: {}\n\n"
        return
    for i in range(0, len(reply), _CHUNK_SIZE):
        chunk = reply[i : i + _CHUNK_SIZE]
        yield f"event: chunk\ndata: {json.dumps({'text': chunk})}\n\n"
    yield "event: done\ndata: {}\n\n"
