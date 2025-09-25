from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
import re
from difflib import SequenceMatcher

from invoice_parser import extract_invoice
from ocr_reader import read_text

INVOICE_LINES: List[str] = []
INVOICE_TEXT: str = ""
INVOICE_METHOD: str = ""

DATASET_DIR = Path("dataset/prototype")
IMAGES_DIR = DATASET_DIR/"images"
LABELS_CSV = DATASET_DIR/"labels.csv"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
if not LABELS_CSV.exists():
    LABELS_CSV.write_text("filename,label,ts\n", encoding="utf-8")

app = FastAPI(title="Prototype OCR-first Delivery Confirmation")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def normalize(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s\-\.]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def best_matches(candidates: List[str], search: str, k: int = 3) -> List[Dict[str, Any]]:
    norm_target = normalize(search)
    scored = []
    seen = set()
    for c in candidates:
        n = normalize(c)
        if not n or n in seen:
            continue
        seen.add(n)
        score = SequenceMatcher(None, n, norm_target).ratio()
        scored.append((c, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [{"text": c, "score": round(s,3)} for c,s in scored[:k]]

@app.get("/health")
def health():
    return {"status": "ok", "invoice_lines": len(INVOICE_LINES), "method": INVOICE_METHOD}

@app.post("/invoice")
async def upload_invoice(file: UploadFile = File(...)):
    global INVOICE_LINES, INVOICE_TEXT, INVOICE_METHOD
    b = await file.read()
    result = extract_invoice(b, file.filename)
    if "error" in result:
        INVOICE_LINES = []; INVOICE_TEXT = ""; INVOICE_METHOD = "error"
        return result
    INVOICE_LINES = result.get("raw_lines", [])
    INVOICE_TEXT = "\n".join(INVOICE_LINES)
    INVOICE_METHOD = result.get("method", "tesseract")
    return {"method": INVOICE_METHOD, "items": result.get("items", []), "raw_lines": INVOICE_LINES, "avg_conf": result.get("avg_conf", 0.0)}

@app.post("/scan")
async def scan_product(file: UploadFile = File(...), user_label: Optional[str] = Form(default=None)):
    global INVOICE_LINES
    img_bytes = await file.read()
    full_text, lines = read_text(img_bytes)
    ocr_join = " ".join(lines) if lines else (full_text or "")

    if user_label:
        from time import time as _now
        fname = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f") + ".jpg"
        (IMAGES_DIR/fname).write_bytes(img_bytes)
        with LABELS_CSV.open("a", encoding="utf-8") as f:
            f.write(f"{fname},{user_label},{int(_now())}\n")
        return {"confirmed": True, "label": user_label, "source": "user", "saved": str(IMAGES_DIR/fname)}

    if not INVOICE_LINES:
        return {"confirmed": False, "reason": "no_invoice_loaded", "message": "Upload invoice first using /invoice", "ocr_text": (ocr_join[:2000] if ocr_join else ""), "suggestions": []}

    norm_invoice = [normalize(x) for x in INVOICE_LINES]
    norm_ocr = normalize(ocr_join)
    exact_hits = [orig for orig, n in zip(INVOICE_LINES, norm_invoice) if n and n in norm_ocr]
    if exact_hits:
        from time import time as _now
        label = exact_hits[0]
        fname = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f") + ".jpg"
        (IMAGES_DIR/fname).write_bytes(img_bytes)
        with LABELS_CSV.open("a", encoding="utf-8") as f:
            f.write(f"{fname},{label},{int(_now())}\n")
        return {"confirmed": True, "label": label, "source": "exact_match", "saved": str(IMAGES_DIR/fname)}

    suggestions = best_matches(INVOICE_LINES, ocr_join, k=3)
    return {"confirmed": False, "suggestions": suggestions, "ocr_text": (ocr_join[:2000] if ocr_join else ""), "note": "If one of these is correct, call /scan again with form field 'user_label' to confirm and save."}
