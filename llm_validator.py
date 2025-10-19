
"""Helpers for validating OCR output with GPT-4o-mini."""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from openai import OpenAI

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Return a cached OpenAI client instance."""

    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable is required")
        _client = OpenAI(api_key=api_key)
    return _client


def validate_invoice_text(raw_text: str) -> Dict[str, Any]:
    """Send normalized invoice text to GPT-4o-mini for structured parsing."""

    if not raw_text.strip():
        return {}

    prompt = f"""
    You are an invoice parser.
    Extract JSON with keys:
    recipient, items[name, quantity, price], total, date
    from the following invoice text:
    {raw_text}
    """

    client = _get_client()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500,
        temperature=0,
    )

    message = response.choices[0].message.content or "{}"
    try:
        return json.loads(message)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Invalid JSON returned by GPT model: {exc}") from exc
