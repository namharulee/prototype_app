import argparse, sys, io, json, re
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher

from ocr_reader import read_text
from invoice_parser import extract_invoice

DATASET_DIR = Path("dataset/prototype")
IMAGES_DIR = DATASET_DIR / "images"
LABELS_CSV = DATASET_DIR / "labels.csv"
CORR_PATH = Path("corrections.json")

def load_corrections():
    try:
        return json.loads(CORR_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def apply_corrections(s: str, corr: dict) -> str:
    out = s
    for bad, good in corr.items():
        try:
            out = out.replace(bad, good)
        except Exception:
            continue
    return out

def normalize(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s\-\.]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def score_match(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()

def prompt_user_choice(candidates):
    print("\nNo strong match found. Please choose the correct item:")
    for i, it in enumerate(candidates, 1):
        print(f"  {i}) {it}")
    print("  0) Unmatched / skip")
    while True:
        try:
            sel = int(input("Select [0-{}]: ".format(len(candidates))).strip())
            if 0 <= sel <= len(candidates):
                if sel == 0: return None
                return candidates[sel-1]
        except Exception:
            pass
        print("Invalid choice. Try again.")

def maybe_add_correction(ocr_text: str, chosen: str, corr: dict):
    # Ask user if they want to add a correction pair
    try:
        ans = input("Add a correction mapping (e.g., bad->good) to improve future OCR? [y/N]: ").strip().lower()
        if ans != "y":
            return
        pair = input("Enter mapping as 'bad->good' (without quotes): ").strip()
        if "->" in pair:
            bad, good = pair.split("->", 1)
            bad = bad.strip(); good = good.strip()
            if bad and good:
                corr[bad] = good
                CORR_PATH.write_text(json.dumps(corr, indent=2), encoding="utf-8")
                print(f"Saved correction: {bad} -> {good}")
    except Exception:
        pass

def main():
    ap = argparse.ArgumentParser(description="Invoice-guided auto labeling for YOLO dataset")
    ap.add_argument("--invoice", required=True, help="Path to invoice image/PDF")
    ap.add_argument("--images", required=True, help="Folder of product images to label")
    ap.add_argument("--threshold", type=float, default=0.7, help="Auto-label threshold (0..1)")
    args = ap.parse_args()

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    if not LABELS_CSV.exists():
        LABELS_CSV.write_text("filename,label,confidence,needs_review\n", encoding="utf-8")

    # Parse invoice
    inv_bytes = Path(args.invoice).read_bytes()
    inv_res = extract_invoice(inv_bytes, Path(args.invoice).name)
    if "error" in inv_res:
        print(inv_res["error"])
        sys.exit(0)
    invoice_items = inv_res.get("items", [])
    invoice_descs = [it.get("desc","") for it in invoice_items if it.get("desc")]
    if not invoice_descs:
        print("No invoice items extracted.")
    print(f"Loaded invoice items: {len(invoice_descs)}")

    corr = load_corrections()

    total = 0
    auto_labeled = 0
    needs_review = 0

    src_dir = Path(args.images)
    for img_path in sorted(src_dir.glob("*.*")):
        if img_path.suffix.lower() not in [".jpg",".jpeg",".png",".webp"]:
            continue
        total += 1
        b = img_path.read_bytes()
        full_text, lines = read_text(b)
        raw = " ".join(lines) if lines else (full_text or "")
        raw = apply_corrections(raw, corr)

        # find best invoice desc
        best = None; best_score = 0.0
        for desc in invoice_descs:
            sc = score_match(raw, desc)
            if sc > best_score:
                best_score = sc; best = desc

        if best and best_score >= args.threshold:
            # auto-assign
            dst_name = img_path.name
            (IMAGES_DIR / dst_name).write_bytes(b)
            with LABELS_CSV.open("a", encoding="utf-8") as f:
                f.write(f"{dst_name},\"{best}\",{best_score:.3f},false\n")
            auto_labeled += 1
            print(f"[AUTO] {img_path.name} -> {best} ({best_score:.2f})")
        else:
            # prompt user
            cand = sorted(invoice_descs, key=lambda d: score_match(raw, d), reverse=True)[:5]
            choice = prompt_user_choice(cand)
            if choice:
                dst_name = img_path.name
                (IMAGES_DIR / dst_name).write_bytes(b)
                with LABELS_CSV.open("a", encoding="utf-8") as f:
                    f.write(f"{dst_name},\"{choice}\",{score_match(raw, choice):.3f},true\n")
                needs_review += 1
                print(f"[USER] {img_path.name} -> {choice}")
                maybe_add_correction(raw, choice, corr)
            else:
                with LABELS_CSV.open("a", encoding="utf-8") as f:
                    f.write(f"{img_path.name},\"Unmatched\",0.000,true\n")
                needs_review += 1
                print(f"[SKIP] {img_path.name} -> Unmatched")

    print("\n✅ Labeling Summary:")
    print(f"- Total images processed: {total}")
    print(f"- Auto-labeled: {auto_labeled}")
    print(f"- Needs review: {needs_review}")

if __name__ == "__main__":
    main()
