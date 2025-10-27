from paddleocr import PaddleOCR
from PIL import Image
import io

# Initialize PaddleOCR with layout awareness
ocr = PaddleOCR(
    use_angle_cls=True,
    lang="en",
    show_log=False,
    use_space_char=True,
    structure_version="PP-StructureV2",  # enables layout parsing
    ocr_version="PP-OCRv4",
    use_gpu=False,
)

def run_vl_ocr(image_bytes):
    """
    Run PaddleOCR in layout-aware mode and return structured JSON
    grouping header, table items, and totals.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    result = ocr.ocr(img, cls=True)

    if not result or not result[0]:
        return {"error": "No text detected"}

    header, items, totals = [], [], []
    for line in result[0]:
        text = line[1][0].strip()
        lower = text.lower()
        if any(k in lower for k in ["invoice", "date", "supplier", "no"]):
            header.append(text)
        elif any(k in lower for k in ["total", "subtotal", "gst", "amount due"]):
            totals.append(text)
        else:
            items.append(text)

    return {"header": header, "table": items, "total": totals}
