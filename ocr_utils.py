"""Utility helpers for OCR processing using PaddleOCR."""

from __future__ import annotations

import io
from typing import List, Tuple

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
