from typing import List, Tuple
import io, re

def _normalize_lines(lines: List[str]) -> List[str]:
    out = []
    for s in lines:
        s = s.strip()
        s = re.sub(r"\s+", " ", s)
        if s:
            out.append(s)
    return out

def read_text(image_bytes: bytes) -> Tuple[str, List[str]]:
    """
    OCR wrapper. Prefer Tesseract; fall back to EasyOCR.
    Returns: (full_text, lines)
    """
    text = ""
    lines: List[str] = []
    # Try pytesseract
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        text = pytesseract.image_to_string(img)
        lines = _normalize_lines(text.splitlines())
        if lines:
            return text, lines
    except Exception:
        pass

    # Try EasyOCR
    try:
        import easyocr
        import numpy as np
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img)
        reader = easyocr.Reader(['en'], gpu=False)
        result = reader.readtext(arr, detail=0)
        lines = _normalize_lines(result if isinstance(result, list) else [])
        text = "\n".join(lines)
        return text, lines
    except Exception:
        return "", []
