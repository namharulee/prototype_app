
"""Helpers for validating OCR output with GPT-4o-mini."""

from __future__ import annotations

import json
import os
import re
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


def _serialise_input(raw_data: Any) -> str:
    if isinstance(raw_data, str):
        return raw_data
    try:
        return json.dumps(raw_data, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(raw_data)


def validate_invoice_text(raw_data: Any) -> Dict[str, Any]:
    """Validate PaddleOCR-VL output with GPT-4o-mini and return structured JSON."""

    client = _get_client()
    raw_text = _serialise_input(raw_data)

    prompt = f"""
You are an invoice validator.

Below is structured OCR data extracted from a supplier's invoice.
Your goal is to verify and normalize it, returning strictly valid JSON.

Rules:
1. Distinguish between the supplier (seller) and the recipient (buyer).
   - The supplier is the company issuing the invoice.
   - The recipient is the business or restaurant marked as “Delivered To”, “Ship To”, “Customer”, or similar.
   - If both are present, ALWAYS use the recipient as the value of "recipient".
2. Normalize key fields:
   - "date" → standardized format (e.g., 2024-06-14)
   - "total" → numeric (float)
   - "items" → each has {"name", "quantity", "price"}
3. Return only this JSON structure:
{{
  "supplier": "<supplier company name>",
  "recipient": "<customer or delivery destination>",
  "items": [
    {{"name": "...", "quantity": 0, "price": 0.0}}
  ],
  "total": 0.0,
  "date": "YYYY-MM-DD"
}}
4. If the invoice text does not clearly identify the recipient, leave the field as null.
5. Do NOT guess missing data, and output ONLY valid JSON with no explanations.

Structured OCR input:
{raw_text}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
        temperature=0,
    )

    content = (response.choices[0].message.content or "").strip()

    json_match = re.search(r"\{.*\}", content, re.DOTALL)
    if not json_match:
        print("[WARN] GPT did not return JSON:", content[:100])
        return {}

    json_str = json_match.group(0)
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as exc:
        print("[ERROR] Invalid JSON from GPT:", exc)
        print("Raw output:", content[:200])
        return {}
