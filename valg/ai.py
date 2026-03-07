# valg/ai.py
"""
AI commentary layer for the valg election dashboard.

Requires VALG_AI_API_KEY to be set in the environment or .env file.
Gracefully degrades when not configured.
"""
from __future__ import annotations

import os


def is_ai_configured() -> bool:
    """Return True if the AI API key is set."""
    return bool(os.getenv("VALG_AI_API_KEY"))


def get_commentary(state: dict) -> str | None:
    """
    Generate AI commentary for the current election state.

    Args:
        state: dict with keys: parties, districts_reported, districts_total

    Returns:
        A string with commentary, or None if generation fails.
    """
    if not is_ai_configured():
        return None

    try:
        import openai

        client = openai.OpenAI(api_key=os.getenv("VALG_AI_API_KEY"))

        parties_summary = ", ".join(
            f"{p['letter']}: {p['votes']:,} votes ({p['seats']} seats)"
            for p in sorted(state.get("parties", []), key=lambda x: -x.get("votes", 0))[:5]
        )
        reported = state.get("districts_reported", 0)
        total = state.get("districts_total", 0)

        prompt = (
            f"Danish election update: {reported}/{total} districts reported.\n"
            f"Top parties: {parties_summary}\n"
            "Give a brief 2-3 sentence commentary in Danish on the current state."
        )

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
        )
        return response.choices[0].message.content

    except Exception:
        return None
