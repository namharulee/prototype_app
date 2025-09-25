from typing import List, Tuple, Dict, Any
import io, re

from ocr_reader import read_text

def preprocess_image(image_bytes: bytes) -> bytes:
    try:
        import cv2
        import numpy as np
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        bin_img = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 11
        )
        bin_img = cv2.medianBlur(bin_img, 3)
        edges = cv2.Canny(bin_img, 50, 150)
        coords = cv2.findNonZero(edges)
        if coords is not None:
            rect = cv2.minAreaRect(coords)
            angle = rect[-1]
            if angle < -45:
                angle = -(90 + angle)
            else:
                angle = -angle
            (h, w) = bin_img.shape[:2]
            M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
            bin_img = cv2.warpAffine(bin_img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2,2))
        bin_img = cv2.morphologyEx(bin_img, cv2.MORPH_OPEN, kernel, iterations=1)
        ok, enc = cv2.imencode(".jpg", bin_img)
        return enc.tobytes() if ok else image_bytes

    except Exception:
        from PIL import Image, ImageOps, ImageFilter
        img = Image.open(io.BytesIO(image_bytes)).convert("L")
        img = ImageOps.autocontrast(img)
        img = img.filter(ImageFilter.MedianFilter(size=3))
        thresh = img.point(lambda p: 255 if p > 180 else 0)
        out = io.BytesIO()
        thresh.convert("L").save(out, format="JPEG", quality=90)
        return out.getvalue()

def ocr_with_conf(image_bytes: bytes) -> Dict[str, Any]:
    try:
        import pytesseract
        from PIL import Image
        import pandas as pd

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DATAFRAME)  # type: ignore
        data = data[(data.conf != -1) & (data.text.notna()) & (data.text.str.strip() != "")]
        if len(data) > 0:
            lines = []
            confidences = []
            for (b, p, l), df in data.groupby(["block_num", "par_num", "line_num"]):
                txt = " ".join(df["text"].astype(str).tolist()).strip()
                if txt:
                    c = df["conf"].astype(float)
                    line_conf = max(0.0, min(1.0, c.mean()/100.0))
                    lines.append(txt)
                    confidences.append(line_conf)
            avg_conf = sum(confidences)/len(confidences) if confidences else 0.0
            raw_text = "\n".join(lines)
            if len(lines) > 0 and avg_conf >= 0.55:
                return {"method":"tesseract","lines":lines,"confidences":confidences,"avg_conf":avg_conf,"raw_text":raw_text}
    except Exception:
        pass

    try:
        import easyocr
        import numpy as np
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img)
        reader = easyocr.Reader(['en'], gpu=False)
        results = reader.readtext(arr, detail=1)
        lines, confidences = [], []
        rows = []
        for bbox, text, conf in results:
            if not text:
                continue
            y = sum([pt[1] for pt in bbox]) / 4.0
            rows.append((y, text, float(conf)))
        rows.sort(key=lambda x: x[0])
        grouped = []
        for y, text, conf in rows:
            if not grouped or abs(y - grouped[-1][0]) > 12:
                grouped.append([y, [(text, conf)]])
            else:
                grouped[-1][1].append((text, conf))
        for y, pairs in grouped:
            line = " ".join(t for t, c in pairs)
            if line.strip():
                lines.append(line.strip())
                confidences.append(max(0.0, min(1.0, sum(c for t,c in pairs)/max(1,len(pairs)))))
        avg_conf = sum(confidences)/len(confidences) if confidences else 0.0
        raw_text = "\n".join(lines)
        return {"method":"easyocr","lines":lines,"confidences":confidences,"avg_conf":avg_conf,"raw_text":raw_text}
    except Exception:
        return {"method":"error","lines":[],"confidences":[],"avg_conf":0.0,"raw_text":""}

def normalize_common_errors(s: str) -> str:
    s = re.sub(r"\b10O?p\b", "100pc", s, flags=re.IGNORECASE)
    s = re.sub(r"^[\{\[\(]+(?=\d)", "", s)
    s = re.sub(r"[^0-9a-zA-Z\s\.\-\/%:]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

_price_re = re.compile(r"([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})|\d+\.[0-9]{2}|\d+)$")
_item_no_re = re.compile(r"^\s*(\d{4,})\b")

def line_to_row(line: str) -> Dict[str, Any]:
    clean = normalize_common_errors(line)
    item_no = None; qty = None; price = None; desc = clean
    m_no = _item_no_re.search(clean)
    if m_no:
        item_no = m_no.group(1); desc = clean[m_no.end():].strip()
    m_price = _price_re.search(clean)
    if m_price:
        price_str = m_price.group(1).replace(",", "")
        try:
            price = float(price_str); desc = clean[:m_price.start()].strip()
        except Exception: pass
    m_qty = re.search(r"\bqty\s*[:x]?\s*(\d+)\b", clean, flags=re.IGNORECASE) or             re.search(r"\b(\d+)\s*x\b", clean, flags=re.IGNORECASE)
    if m_qty:
        try: qty = int(m_qty.group(1))
        except Exception: qty = None
    if qty is None: qty = 1
    return {"item_no": item_no, "desc": desc, "qty": qty, "price": price}

def structure_items(lines: List[str], confidences: List[float], avg_conf: float) -> List[Dict[str, Any]]:
    items = []
    for i, line in enumerate(lines):
        row = line_to_row(line)
        c = confidences[i] if i < len(confidences) else avg_conf
        c = float(c) if c is not None else 0.0
        row["needs_review"] = bool(c < 0.7)
        row["confidence"] = round(c, 3)
        items.append(row)
    return items

def extract_invoice(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    if filename.lower().endswith(".pdf"):
        try:
            from pdf2image import convert_from_bytes
            pages = convert_from_bytes(file_bytes)
            all_lines, all_conf, methods = [], [], []
            for im in pages:
                b = io.BytesIO()
                im.save(b, format="JPEG")
                pre = preprocess_image(b.getvalue())
                res = ocr_with_conf(pre)
                methods.append(res.get("method", "unknown"))
                all_lines.extend(res.get("lines", []))
                all_conf.extend(res.get("confidences", []))
            if not all_lines:
                return {"error": "Invoice unreadable. Please retry or upload PDF."}
            avg_conf = sum(all_conf)/len(all_conf) if all_conf else 0.0
            items = structure_items(all_lines, all_conf, avg_conf)
            return {"method": methods[0] if methods else "tesseract", "items": items, "raw_lines": all_lines, "avg_conf": round(avg_conf, 3)}
        except Exception:
            return {"error": "Invoice unreadable. Please retry or upload PDF."}
    else:
        pre = preprocess_image(file_bytes)
        res = ocr_with_conf(pre)
        lines = res.get("lines", [])
        conf = res.get("confidences", [])
        avg_conf = float(res.get("avg_conf", 0.0))
        method = res.get("method", "tesseract")
        if not lines:
            return {"error": "Invoice unreadable. Please retry or upload PDF."}
        items = structure_items(lines, conf, avg_conf)
        return {"method": method, "items": items, "raw_lines": lines, "avg_conf": round(avg_conf, 3)}

def extract_text_lines(file_bytes: bytes, filename: str):
    res = extract_invoice(file_bytes, filename)
    if "error" in res:
        return "", [], "error"
    return "\n".join(res.get("raw_lines", [])), res.get("raw_lines", []), res.get("method", "tesseract")
