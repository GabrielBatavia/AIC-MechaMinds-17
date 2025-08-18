import os, shutil, yaml

ROOT = r"C:/Users/GabrielBatavia/Documents/github_project/medverify-ai-agent/data/yolo_title"
OUT_ROOT = r"C:/Users/GabrielBatavia/Documents/github_project/medverify-ai-agent/data/yolo_title_clean"

# Copy images ke folder baru (sekali saja)
if not os.path.exists(OUT_ROOT):
    shutil.copytree(ROOT, OUT_ROOT, ignore=shutil.ignore_patterns("labels", "data.yaml"))

LABEL_DIRS = ["train", "valid", "test"]

def map_class(old_cls: int):
    if old_cls % 3 == 1:   # xx-01
        return None
    elif old_cls % 3 == 2: # xx-02
        return 0  # title
    elif old_cls % 3 == 0: # xx-03
        return 1  # body

for split in LABEL_DIRS:
    in_dir = os.path.join(ROOT, "labels", split)
    out_dir = os.path.join(OUT_ROOT, "labels", split)
    os.makedirs(out_dir, exist_ok=True)

    if not os.path.exists(in_dir):
        continue

    for fname in os.listdir(in_dir):
        if not fname.endswith(".txt"):
            continue
        fpath = os.path.join(in_dir, fname)
        outpath = os.path.join(out_dir, fname)

        new_lines = []
        with open(fpath, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 5:
                    continue
                old_cls = int(parts[0])
                new_cls = map_class(old_cls)
                if new_cls is None:
                    continue
                parts[0] = str(new_cls)
                new_lines.append(" ".join(parts))

        with open(outpath, "w") as f:
            f.write("\n".join(new_lines))

# Buat data.yaml baru
clean_yaml = {
    "path": OUT_ROOT,
    "train": "images/train",
    "val": "images/valid",
    "test": "images/test",
    "nc": 2,
    "names": {0: "title", 1: "body"}
}
with open(os.path.join(OUT_ROOT, "data.yaml"), "w") as f:
    yaml.safe_dump(clean_yaml, f)

print("✅ Dataset cleaned & saved to:", OUT_ROOT)
