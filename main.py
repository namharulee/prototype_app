import os
import boto3, io
from botocore.config import Config as BotoConfig

B2_BUCKET   = os.getenv("B2_BUCKET")
B2_ENDPOINT = os.getenv("B2_ENDPOINT")
B2_KEY_ID   = os.getenv("B2_KEY_ID")
B2_APP_KEY  = os.getenv("B2_APP_KEY")

_S3 = None
def get_s3():
    global _S3
    if _S3 is None and all([B2_BUCKET, B2_ENDPOINT, B2_KEY_ID, B2_APP_KEY]):
        _S3 = boto3.client(
            "s3",
            endpoint_url=B2_ENDPOINT,
            aws_access_key_id=B2_KEY_ID,
            aws_secret_access_key=B2_APP_KEY,
            config=BotoConfig(signature_version="s3v4"),
        )
    return _S3

def upload_image_to_b2(image_pil, label: str, filename: str) -> str:
    """
    Uploads PIL image to B2 at key: raw/<label>/<filename>
    Returns the key (path in bucket).
    """
    s3 = get_s3()
    if not s3:
        return ""  # cloud not configured
    key = f"raw/{clean_label(label)}/{filename}"
    buf = io.BytesIO()
    image_pil.convert("RGB").save(buf, format="JPEG", quality=92)
    buf.seek(0)
    s3.upload_fileobj(buf, B2_BUCKET, key, ExtraArgs={"ContentType": "image/jpeg"})
    return key


from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi import Query
from pydantic import BaseModel
from typing import List, Optional
import pytesseract
from PIL import Image
import io, os, re, shutil, uuid, json
from datetime import datetime

app = FastAPI()

# Serve the frontend
app.mount("/static", StaticFiles(directory="static", html=True), name="static")

DATASET_ROOT = os.path.join("dataset", "raw")
os.makedirs(DATASET_ROOT, exist_ok=True)

def clean_label(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "unknown"

def save_image_to_class(img: Image.Image, label: str) -> str:
    cls = clean_label(label)
    class_dir = os.path.join(DATASET_ROOT, cls)
    os.makedirs(class_dir, exist_ok=True)
    fname = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
    path = os.path.join(class_dir, fname)
    img.convert("RGB").save(path, quality=92)
    return f"{cls}/{fname}"  # relative path for frontend

@app.get("/preview_url")
def preview_url(key: str = Query(...), expires: int = 3600):
    s3 = get_s3()
    if not s3:
        return JSONResponse({"error": "Cloud not configured"}, status_code=400)
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": B2_BUCKET, "Key": key},
        ExpiresIn=int(expires),
    )
    return {"url": url}

@app.get("/ping")
def ping():
    return {"message": "pong"}

@app.post("/invoice", response_model=InvoiceResult)
async def invoice(file: UploadFile = File(...)):
    contents = await file.read()
    image = Image.open(io.BytesIO(contents))
    raw_text = pytesseract.image_to_string(image)
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    items = [l for l in lines if 3 <= len(l.split()) <= 12]
    seen, uniq = set(), []
    for it in items:
        if it not in seen:
            uniq.append(it)
            seen.add(it)
    return {"lines": lines, "items_for_dropdown": uniq[:200], "sample": lines[:5]}

class ScanResponse(BaseModel):
    ocr_label: str
    saved_relpath: str
    note: str

@app.post("/scan", response_model=ScanResponse)
async def scan(file: UploadFile = File(...), fallback_label: Optional[str] = Form(None)):
    """
    Upload a product snapshot (from camera/file). OCR tries to read a label.
    We save the image under dataset/raw/<label>/filename.jpg
    """
    try:
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        text = pytesseract.image_to_string(image)
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        # Heuristic pick: first non-empty line; else fallback from UI; else "unknown"
        guessed = lines[0] if lines else (fallback_label or "unknown")
        relpath = save_image_to_class(image, guessed)

        # Upload to B2 (if configured)
        cloud_key = upload_image_to_b2(image, guessed, os.path.basename(relpath))  # returns key or ""

        return {
            "ocr_label": clean_label(guessed),
            "saved_relpath": relpath,         # existing local relative path
            "cloud_key": cloud_key,           # path in B2 if available
            "note": "Saved locally and to B2 (if configured)."
        }

    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


