"""Layout-aware OCR wrapper using PaddleOCR-VL."""

from __future__ import annotations

import io
import re
from typing import Any, Dict, Iterable, List

import numpy as np
from PIL import Image

try:
    from paddleocr_vl import PaddleOCRVL  # type: ignore
except ImportError:  # pragma: no cover - dependency optional in tests
    PaddleOCRVL = None

try:  # pragma: no cover - fallback for environments without paddleocr-vl
    from paddleocr import PaddleOCR  # type: ignore
except ImportError:  # pragma: no cover - dependency optional in tests
    PaddleOCR = None


_VL_ENGINE = None
_FALLBACK_ENGINE = None


def _load_vl_engine():
    """Initialise the PaddleOCR-VL engine once."""

    global _VL_ENGINE
    if _VL_ENGINE is None and PaddleOCRVL is not None:
        try:
            _VL_ENGINE = PaddleOCRVL()
        except Exception:  # pragma: no cover - surface initialisation failures at runtime
            _VL_ENGINE = None
    return _VL_ENGINE


def _load_fallback_engine():
    """Fallback to standard PaddleOCR when VL variant is unavailable."""

    global _FALLBACK_ENGINE
    if _FALLBACK_ENGINE is None and PaddleOCR is not None:
        _FALLBACK_ENGINE = PaddleOCR(lang="en", use_angle_cls=True)
    return _FALLBACK_ENGINE


def _ensure_engine():
    engine = _load_vl_engine()
    if engine is not None:
        return engine, "vl"
    fallback = _load_fallback_engine()
    if fallback is not None:
        return fallback, "paddle"
    raise RuntimeError("PaddleOCR-VL is not installed and no fallback PaddleOCR engine is available")


def _bytes_to_array(image_bytes: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(image_bytes)) as img:
        rgb = img.convert("RGB")
        return np.array(rgb)


def _iter_texts(result: Any) -> Iterable[str]:
    """Yield recognised text strings from different PaddleOCR result formats."""

    if result is None:
        return []

    texts: List[str] = []

    if isinstance(result, dict):
        for key in ("header", "table", "total", "texts", "ocr"):
            value = result.get(key)
            if isinstance(value, dict):
                texts.extend(str(v) for v in value.values())
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        texts.extend(str(v) for v in item.values())
                    else:
                        texts.append(str(item))
        other = result.get("text")
        if other:
            if isinstance(other, list):
                texts.extend(str(x) for x in other)
            else:
                texts.append(str(other))
        return texts

    if isinstance(result, list):
        for entry in result:
            if isinstance(entry, list):
                for sub in entry:
                    if isinstance(sub, (list, tuple)) and len(sub) >= 2:
                        texts.append(str(sub[1][0]))
                    elif isinstance(sub, dict):
                        texts.extend(str(v) for v in sub.values())
                    else:
                        texts.append(str(sub))
            elif isinstance(entry, dict):
                texts.extend(str(v) for v in entry.values())
            else:
                texts.append(str(entry))
        return texts

    texts.append(str(result))
    return texts


_DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b"),
    re.compile(r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b"),
    re.compile(r"\b([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})\b"),
]
_INVOICE_NO_PATTERN = re.compile(r"invoice\s*(?:no\.?|number|#)\s*[:#-]?\s*([A-Za-z0-9-]+)", re.IGNORECASE)
_AMOUNT_PATTERN = re.compile(r"(-?\d+[\d,.]*)")


def _normalise_total(texts: Iterable[str]) -> str:
    for text in texts:
        if "total" in text.lower():
            numbers = _AMOUNT_PATTERN.findall(text)
            if numbers:
                return numbers[-1].replace(",", "")
    for text in texts:
        match = _AMOUNT_PATTERN.search(text)
        if match:
            return match.group(1).replace(",", "")
    return ""


def _extract_header(texts: List[str]) -> Dict[str, str]:
    header: Dict[str, str] = {}
    for text in texts:
        lowered = text.lower()
        if "invoice" in lowered:
            match = _INVOICE_NO_PATTERN.search(text)
            if match and "invoice_no" not in header:
                header["invoice_no"] = match.group(1).strip()
    for text in texts:
        for pattern in _DATE_PATTERNS:
            match = pattern.search(text)
            if match and "invoice_date" not in header:
                header["invoice_date"] = match.group(1).strip()
                break
        if "invoice_date" in header:
            break
    return header


_ROW_PATTERN = re.compile(r"^(?P<name>.+?)\s+(?P<qty>\d+[\d.,]*)\s+(?P<price>\d+[\d.,]*)$")


def _extract_table(texts: List[str]) -> List[Dict[str, str]]:
    table: List[Dict[str, str]] = []
    for text in texts:
        match = _ROW_PATTERN.match(text.strip())
        if match:
            table.append(
                {
                    "description": match.group("name").strip(),
                    "qty": match.group("qty").replace(",", ""),
                    "price": match.group("price").replace(",", ""),
                }
            )
    return table


def _structure_from_result(result: Any) -> Dict[str, Any]:
    if isinstance(result, dict) and {"header", "table", "total"} <= result.keys():
        return {
            "header": dict(result.get("header") or {}),
            "table": list(result.get("table") or []),
            "total": str(result.get("total") or ""),
        }

    texts = list(_iter_texts(result))
    header = _extract_header(texts)
    table = _extract_table(texts)
    total = _normalise_total(texts)

    structured: Dict[str, Any] = {
        "header": header,
        "table": table,
        "total": total,
    }
    if texts:
        structured["raw_text"] = "\n".join(texts)
    return structured


def run_vl_ocr(image_bytes: bytes) -> Dict[str, Any]:
    """Run PaddleOCR-VL (or PaddleOCR fallback) and return structured data."""

    engine, mode = _ensure_engine()
    np_image = _bytes_to_array(image_bytes)

    if mode == "vl" and hasattr(engine, "predict"):
        result = engine.predict(np_image)  # type: ignore[attr-defined]
    elif hasattr(engine, "ocr"):
        result = engine.ocr(np_image, cls=True)  # type: ignore[attr-defined]
    else:
        result = engine(np_image)

    structured = _structure_from_result(result)
    structured.setdefault("engine", mode)
    return structured
