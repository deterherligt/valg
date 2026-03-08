"""
Model-agnostic AI commentary layer.
Uses any OpenAI-compatible endpoint. Requires:
  VALG_AI_API_KEY   — API key
  VALG_AI_BASE_URL  — base URL (e.g. https://api.anthropic.com/v1)
  VALG_AI_MODEL     — model name (e.g. claude-sonnet-4-6, gpt-4o)
"""
import logging
import os
from typing import Optional

log = logging.getLogger(__name__)


def is_ai_configured() -> bool:
    return bool(os.getenv("VALG_AI_API_KEY"))


def get_ai_client():
    try:
        from openai import OpenAI
    except ImportError:
        log.warning("openai package not installed — pip install 'valg[ai]'")
        return None
    return OpenAI(
        api_key=os.getenv("VALG_AI_API_KEY"),
        base_url=os.getenv("VALG_AI_BASE_URL", "https://api.openai.com/v1"),
    )


def build_prompt(state: dict) -> str:
    parties = state.get("parties", [])
    reported = state.get("districts_reported", 0)
    total = state.get("districts_total", 0)
    lines = [
        f"Danish Folketing election. {reported}/{total} districts reported.",
        "Current standings:",
    ]
    for p in parties:
        lines.append(
            f"  Party {p['letter']}: {p['votes']:,} votes, {p['seats']} projected seats"
        )
    lines.append(
        "\nProvide a brief analytical commentary (3-5 sentences) on the current state. "
        "Note any notable trends, close races, or seat flip risks. Be factual and concise."
    )
    return "\n".join(lines)


def get_commentary(state: dict, context: Optional[str] = None) -> Optional[str]:
    """Return AI commentary string, or None if AI is not configured or fails."""
    if not is_ai_configured():
        return None
    client = get_ai_client()
    if client is None:
        return None
    model = os.getenv("VALG_AI_MODEL", "gpt-4o-mini")
    prompt = build_prompt(state)
    if context:
        prompt = f"Context: {context}\n\n{prompt}"
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.warning("AI commentary failed: %s", e)
        return None
