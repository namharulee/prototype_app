import argparse, random, shutil, yaml, os
from pathlib import Path
from collections import defaultdict
from ultralytics import YOLO

DATASET_DIR = Path("dataset/prototype")
IMAGES_DIR = DATASET_DIR / "images"
LABELS_CSV = DATASET_DIR / "labels.csv"
YOLO_DIR = Path("dataset/yolo")

def read_labels():
    rows = []
    if not LABELS_CSV.exists():
        return rows
    for line in LABELS_CSV.read_text(encoding="utf-8").splitlines()[1:]:
        if not line.strip(): continue
        # filename,label,confidence,needs_review or filename,label,ts (legacy)
        parts = []
        cur = ""
        in_quotes = False
        for ch in line:
            if ch == '"' and not in_quotes:
                in_quotes = True; continue
            elif ch == '"' and in_quotes:
                in_quotes = False; continue
            if ch == ',' and not in_quotes:
                parts.append(cur); cur = ""
            else:
                cur += ch
        parts.append(cur)
        if len(parts) >= 2:
            rows.append({"filename": parts[0].strip(), "label": parts[1].strip()})
    return rows

def build_class_map(rows):
    classes = sorted({r["label"] for r in rows if r.get("label") and r["label"] != "Unmatched"})
    return {c:i for i,c in enumerate(classes)}

def ensure_split(rows, train=0.8, val=0.1, test=0.1):
    by_class = defaultdict(list)
    for r in rows:
        if r["label"] == "Unmatched": continue
        imgp = IMAGES_DIR / r["filename"]
        if imgp.exists():
            by_class[r["label"]].append(imgp)
    split = {"train": [], "val": [], "test": []}
    for cls, files in by_class.items():
        files = list(files); random.shuffle(files)
        n = len(files); n_train = int(n*train); n_val = int(n*val)
        split["train"] += [(f, cls) for f in files[:n_train]]
        split["val"]   += [(f, cls) for f in files[n_train:n_train+n_val]]
        split["test"]  += [(f, cls) for f in files[n_train+n_val:]]
    return split

def write_yolo(split, class_map):
    for part in ["train","val","test"]:
        (YOLO_DIR/"images"/part).mkdir(parents=True, exist_ok=True)
        (YOLO_DIR/"labels"/part).mkdir(parents=True, exist_ok=True)
    # full-image box as placeholder
    for part, pairs in split.items():
        for imgp, cls in pairs:
            dst = YOLO_DIR/"images"/part/imgp.name
            shutil.copy2(imgp, dst)
            cid = class_map[cls]
            (YOLO_DIR/"labels"/part/dst.with_suffix(".txt").name).write_text(f"{cid} 0.5 0.5 1.0 1.0\n", encoding="utf-8")
    # data.yaml
    names = {i:c for c,i in class_map.items()}
    data_yaml = {
        "path": str(YOLO_DIR.resolve()),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": names,
        "nc": len(names)
    }
    (YOLO_DIR/"data.yaml").write_text(yaml.safe_dump(data_yaml, sort_keys=False), encoding="utf-8")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--model", default="yolov8n.pt")
    ap.add_argument("--backend_weights_dir", default="backend", help="Where to copy best.pt so FastAPI can load it")
    args = ap.parse_args()

    rows = read_labels()
    if not rows:
        print("No labels to train on. Exiting."); return
    class_map = build_class_map(rows)
    if not class_map:
        print("No valid classes. Exiting."); return

    split = ensure_split(rows)
    # clear existing YOLO dir
    if YOLO_DIR.exists():
        shutil.rmtree(YOLO_DIR)
    write_yolo(split, class_map)

    model = YOLO(args.model)
    model.train(data=str(YOLO_DIR/"data.yaml"), epochs=args.epochs, imgsz=args.imgsz, batch=-1, name="prototype_retrain", pretrained=True)

    # Copy latest best.pt to backend/ if exists
    best_candidates = list(Path("runs").glob("**/prototype_retrain*/weights/best.pt"))
    if best_candidates:
        best = max(best_candidates, key=lambda p: p.stat().st_mtime)
        Path(args.backend_weights_dir).mkdir(parents=True, exist_ok=True)
        dst = Path(args.backend_weights_dir)/"best.pt"
        shutil.copy2(best, dst)
        print(f"Copied best weights to {dst}")

if __name__ == "__main__":
    main()
