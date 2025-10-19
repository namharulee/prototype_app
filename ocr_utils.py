"""Utility helpers for OCR processing using PaddleOCR.

This module centralizes all OCR-related helpers so that the FastAPI
application can keep endpoint logic concise.  In Stage 2 we also expose a
normalization helper used as a preprocessing step before sending the OCR
output to GPT for validation.
"""

from __future__ import annotations

import io
import re
from typing import Any, Dict, Iterable, List, Tuple

import cv2
import numpy as np
from paddleocr import PaddleOCR
from PIL import Image

# Initialize the PaddleOCR model once at module import to avoid repeated loads.
OCR_MODEL = PaddleOCR(lang="en", use_angle_cls=True)


def run_paddle_ocr(image_bytes: bytes) -> List[Tuple[str, float]]:
    """Run PaddleOCR on raw image bytes.

    Args:
        image_bytes: The raw bytes read from an uploaded image file.

    Returns:
        A list of tuples containing the recognized text and the associated
        confidence score (0.0-1.0).
    """

    with Image.open(io.BytesIO(image_bytes)) as image:
        rgb_image = image.convert("RGB")
        np_image = np.array(rgb_image)

    # PaddleOCR expects images in BGR format.
    bgr_image = cv2.cvtColor(np_image, cv2.COLOR_RGB2BGR)

    results = OCR_MODEL.ocr(bgr_image, cls=True)

    ocr_lines: List[Tuple[str, float]] = []
    for page in results:
        if not page:
            continue
        for line in page:
            text, confidence = line[1]
            ocr_lines.append((text, float(confidence)))

    return ocr_lines


def _iter_unique_lines(ocr_lines: Iterable[str]) -> Iterable[str]:
    """Yield lines once while preserving their original order."""

    seen: set[str] = set()
    for line in ocr_lines:
        lowered = line.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        yield line


_KEYWORD_PATTERN = re.compile(
    r"\b(qty|quantity|total|subtotal|tax|amount|price|item|date|due|balance|cash|card|invoice)\b",
    re.IGNORECASE,
)
_NUMBER_PATTERN = re.compile(r"\b\d+[\d.,]*\b")
_CURRENCY_PATTERN = re.compile(r"[$€£¥]")


def _looks_relevant(text: str) -> bool:
    """Return True if the text resembles invoice content worth keeping."""

    if _KEYWORD_PATTERN.search(text):
        return True
    if _NUMBER_PATTERN.search(text):
        return True
    if _CURRENCY_PATTERN.search(text):
        return True
    # Lines that contain both alphabetic characters and spaces are likely item names.
    alpha = any(ch.isalpha() for ch in text)
    space = " " in text
    return alpha and space


def normalize_ocr_text(ocr_lines: List[Dict[str, Any]]) -> str:
    """Normalize OCR output into a GPT-friendly multi-line string.

    Args:
        ocr_lines: Sequence of dictionaries containing ``text`` and
            ``confidence`` keys.

    Returns:
        A ``str`` containing filtered OCR lines separated by newlines.
    """

    cleaned: List[str] = []
    for entry in ocr_lines:
        raw_text = str(entry.get("text", "")).strip()
        if not raw_text:
            continue
        normalized = re.sub(r"\s+", " ", raw_text)
        if not normalized:
            continue
        if not _looks_relevant(normalized):
            continue
        cleaned.append(normalized)

    unique_lines = list(_iter_unique_lines(cleaned))
    return "\n".join(unique_lines)
