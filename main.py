"""FastAPI application entrypoint."""

import io
import json
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import boto3
import pytesseract
from botocore.config import Config as BotoConfig
from fastapi import File, Form, Query, UploadFile
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

from llm_validator import validate_invoice_text
from vl_ocr import run_vl_ocr

B2_BUCKET = os.getenv("B2_BUCKET")
B2_ENDPOINT = os.getenv("B2_ENDPOINT")
B2_KEY_ID = os.getenv("B2_KEY_ID")
B2_APP_KEY = os.getenv("B2_APP_KEY")


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


def clean_label(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "unknown"


def upload_image_to_b2(image_pil: Image.Image, label: str, filename: str) -> str:
    """Uploads PIL image to B2 at key: raw/<label>/<filename>."""

    s3 = get_s3()
    if not s3:
        return ""  # cloud not configured

    key = f"raw/{clean_label(label)}/{filename}"
    buf = io.BytesIO()
    image_pil.convert("RGB").save(buf, format="JPEG", quality=92)
    buf.seek(0)
    s3.upload_fileobj(buf, B2_BUCKET, key, ExtraArgs={"ContentType": "image/jpeg"})
    return key


app = FastAPI()

# Serve the frontend
app.mount("/static", StaticFiles(directory="static", html=True), name="static")

DATASET_ROOT = os.path.join("dataset", "raw")
os.makedirs(DATASET_ROOT, exist_ok=True)


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


class InvoiceResult(BaseModel):
    """Response payload for the invoice OCR endpoint."""

    ocr_raw: Dict[str, Any]
    structured: Dict[str, Any]


@app.post("/invoice", response_model=InvoiceResult)
async def invoice(file: UploadFile = File(...)):
    """Run PaddleOCR-VL on the provided invoice image and validate with GPT."""

    try:
        contents = await file.read()
        vl_json = run_vl_ocr(contents)
        structured = validate_invoice_text(json.dumps(vl_json))
        return {
            "ocr_raw": vl_json,
            "structured": structured,
        }
    except Exception as exc:  # pragma: no cover - defensive logging for runtime issues
        return JSONResponse(
            content={"error": f"OCR or GPT processing failed: {exc}"},
            status_code=500,
        )


class ScanResponse(BaseModel):
    ocr_label: str
    saved_relpath: str
    note: str


@app.post("/scan", response_model=ScanResponse)
async def scan(file: UploadFile = File(...), fallback_label: Optional[str] = Form(None)):
    """Upload a product snapshot and group it into the dataset folder."""

    try:
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        text = pytesseract.image_to_string(image)
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        guessed = lines[0] if lines else (fallback_label or "unknown")
        relpath = save_image_to_class(image, guessed)

        cloud_key = upload_image_to_b2(image, guessed, os.path.basename(relpath))
        note = f"Uploaded to B2 at {cloud_key}" if cloud_key else "Stored locally only"

        return {
            "ocr_label": guessed,
            "saved_relpath": relpath,
            "note": note,
        }
    except Exception as exc:  # pragma: no cover - defensive logging for runtime issues
        return JSONResponse(
            content={"error": f"Scan processing failed: {exc}"},
            status_code=500,
        )
