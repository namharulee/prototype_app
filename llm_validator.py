
"""Helpers for validating OCR output with GPT-4o-mini."""

from __future__ import annotations

import re, json
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

def validate_invoice_text(raw_text: str):
    api_key = os.getenv("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key)

    prompt = f"""
    You are an invoice parser.
    Extract structured JSON with these keys:
    recipient, items[name, quantity, price], total, date.
    Return **only** valid JSON, no extra text or markdown.
    Invoice text:
    {raw_text}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
        temperature=0
    )

    content = response.choices[0].message.content.strip()

    
    json_match = re.search(r'\{.*\}', content, re.DOTALL)
    if not json_match:
        print("[WARN] GPT did not return JSON:", content[:100])
        return {}

    json_str = json_match.group(0)
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        print("[ERROR] Invalid JSON from GPT:", e)
        print("Raw output:", content[:200])
        return {}
