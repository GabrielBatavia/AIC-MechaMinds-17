# app/services/medical_classifier.py
import re
CLASSES = {
  "verify_bpom": r"\b(bpom|nie|izin|terdaftar|registrasi)\b",
  "composition_query": r"\b(kandungan|komposisi|ingredients?|zat aktif|active ingredient)\b",
  "dosage_query": r"\b(dosis|cara pakai|takaran)\b",
  "side_effects": r"\b(efek samping|adverse|side effect)\b",
  "interactions": r"\b(interaksi|contraindication|kontraindikasi)\b",
  "pregnancy_safety": r"\b(hamil|kehamilan|menyusui|laktasi|pregnan)\b",
  "manufacturer_info": r"\b(pt|pabrik|produsen|manufacturer)\b",
  "authenticity_check": r"\b(keaslian|palsu|original|barcode|qr)\b",
}

def classify(text: str) -> str:
    t = text.lower()
    for label, pat in CLASSES.items():
        if re.search(pat, t): return label
    # domain gate
    if re.search(r"\bobat|medicine|tablet|sirup|mg|capsule|farmasi\b", t):
        return "unknown"
    return "non_medical"
