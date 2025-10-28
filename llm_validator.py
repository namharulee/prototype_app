
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
You are an invoice parser and validator.

Your task is to interpret OCR text extracted from supplier invoices and normalize it into a consistent JSON structure. 
The output will be used for automated item matching with live camera scanning data, not just for human reading.

Follow these strict rules:

1. Identify the supplier (the company issuing the invoice) and the recipient (the customer or restaurant being billed or delivered to).
   - Supplier is usually found near "Invoice From", "Tax Invoice", "ABN", or a company header.
   - Recipient is found under "Deliver To", "Ship To", or "Invoice To".

2. Standardize all fields into this JSON schema:
{{
  "supplier": "<supplier name>",
  "recipient": "<recipient name>",
  "date": "<YYYY-MM-DD>",
  "items": [
    {{
      "name": "<product or item name>",
      "quantity": {{
        "value": <numeric quantity>,
        "unit": "<unit if available, e.g. kg, ctn, pack, pc, each, box>"
      }},
      "unit_price": <numeric unit price if available>,
      "amount": <numeric line total if available>
    }}
  ],
  "total": <numeric total amount>
}}

3. Invoices may use different column names such as:
   - “Product Description”, “Description”, “Item”, “Goods” → map to "name".
   - “Qty”, “Quantity”, “QTY/UNIT”, “Pack Size” → map to "quantity".
   - “List Price”, “Unit Price”, “Price (ex GST)”, “Unit Cost” → map to "unit_price".
   - “Amount”, “Subtotal”, “Excl GST”, “Incl GST” → map to "amount".
   Always extract by meaning, not by column title.

4. Units are optional:
   - If OCR text includes something like “3kg”, “2 ctn”, “5 pack”, “10pc”, split value and unit.
   - If no unit is clear, set "unit" = null.
   - Preserve numeric value precision.

5. Normalize numbers:
   - Strip commas, currency symbols, and spaces.
   - Convert to floats (e.g. "2,145.50" → 2145.5).

6. Normalize date to "YYYY-MM-DD". Infer missing year if necessary (e.g. invoice from “11-Sep-25” → “2025-09-11”).

7. Return strictly valid JSON — no markdown, comments, or explanations.

OCR extracted text:
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
