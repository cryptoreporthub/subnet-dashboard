"""SimiVision chat — Chutes AI with local explainer fallback (ported from server_original)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Tuple

from datastore.learning_engine import LearningEngine

logger = logging.getLogger(__name__)


def _safe_load_json(directory: str, filename: str, default: Any = None) -> Any:
    path = os.path.join(directory, filename)
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def build_simivision_prompt(message: str, context: Dict[str, Any]) -> str:
    """Fuse user message with live SimiVision + soul_map context."""
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
    return (
        "You are SimiVision, an AI analyst for Bittensor subnets. "
        "Use the live subnet snapshot and the Council's learned expert weights below.\n\n"
        f"User question: {message}\n\n"
        f"Top SimiVision picks: {picks_str}\n"
        f"Source: {context.get('source', 'unknown')}\n"
        f"Council expert weights (self-learning loop): {weights_str}\n"
        "Answer concisely and tie the reasoning back to the picks and expert weights."
    )


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


async def handle_simivision_chat(message: str) -> Dict[str, str]:
    """Run SimiVision chat and return ``{reply, model}``."""
    if not message.strip():
        return {"reply": "Please provide a question in the `message` field.", "model": ""}

    try:
        context = build_chat_context()
        prompt = build_simivision_prompt(message, context)
        reply, llm_used = call_llm(prompt, message, context)

        model_tag = os.environ.get("CHUTES_MODEL", "deepseek-ai/DeepSeek-V3.2-TEE")
        display_model = (
            f"chutes/{model_tag.split('/')[-1].lower()}" if llm_used else "local-fallback"
        )
        return {"reply": reply, "model": display_model}
    except Exception as exc:
        logger.error("SimiVision chat failed: %s", exc, exc_info=True)
        return {
            "reply": (
                "SimiVision is temporarily unavailable. The Chutes AI service may be "
                "unreachable. Please try again shortly."
            ),
            "model": "",
        }
