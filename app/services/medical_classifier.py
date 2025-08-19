# app/services/medical_classifier.py
from __future__ import annotations
import re
from typing import Optional, Dict

# ==== Label set (string supaya kompatibel dgn code lain) ====
VERIFY_BPOM          = "verify_bpom"
WHAT_IS              = "what_is"              # “apa itu oskadon”
COMPOSITION          = "composition"          # komposisi/kandungan/bahan
DOSAGE               = "dosage"               # dosis/takaran/frekuensi
USAGE                = "usage"                # cara pakai/aturan pakai/indikasi praktis
INTERACTIONS         = "interactions"         # interaksi obat
CONTRAINDICATIONS    = "contraindications"    # kontraindikasi, jangan digunakan pada
SIDE_EFFECTS         = "side_effects"         # efek samping
PREGNANCY            = "pregnancy"            # hamil/menyusui/laktasi
STORAGE              = "storage"              # penyimpanan/stabilitas/kedaluwarsa
WARNINGS             = "warnings"             # peringatan/perhatian
COMPARE              = "compare"              # bandingkan produk/alternatif
PRICE_AVAILABILITY   = "price_availability"   # harga/ketersediaan/tempat beli
CHEMICAL_QUERY       = "chemical_query"       # murni kimia (senyawa, reaksi, struktur)
GENERAL_DRUG_INFO    = "general_drug_info"    # fallback aman
OUT_OF_SCOPE         = "out_of_scope"         # benar2 tidak relevan

# ==== Regex util ====
RX_NIE = re.compile(r"\b([A-Z]{1,3}\w{5,12}\w?)\b", re.I)  # longgar; NIE valid disaring downstream

KEYWORDS = {
    COMPOSITION: [
        r"\bkomposisi\b", r"\bkandungan\b", r"\bbahan\b", r"\bbahan aktif\b",
        r"\bingredients?\b", r"\bzat aktif\b", r"\bformula\b"
    ],
    DOSAGE: [
        r"\bdosis\b", r"\bdosage\b", r"\btakaran\b", r"\bberapa kali\b", r"\bberapa tablet\b",
        r"\bsekali (minum|pakai)\b", r"\baturan (minum|pakai)\b"
    ],
    USAGE: [
        r"\bcara pakai\b", r"\baturan pakai\b", r"\bhow to use\b", r"\bpakainya\b", r"\bindikasi\b"
    ],
    INTERACTIONS: [
        r"\binteraksi\b", r"\bbersamaan dengan\b", r"\bdigunakan dengan\b"
    ],
    CONTRAINDICATIONS: [
        r"\bkontraindikasi\b", r"\btidak boleh\b", r"\bdilarang\b", r"\btidak dianjurkan\b"
    ],
    SIDE_EFFECTS: [
        r"\befek samping\b", r"\bside effect\b", r"\bETA\b"  # ETA jarang, tapi biarkan saja
    ],
    PREGNANCY: [
        r"\bhamil\b", r"\bmenyusui\b", r"\blaktasi\b", r"\bpregnan\w+\b", r"\blactation\b"
    ],
    STORAGE: [
        r"\bpenyimpanan\b", r"\bsimpan\b", r"\bstabilitas\b", r"\bkedaluwarsa\b", r"\bexpiry|expired\b"
    ],
    WARNINGS: [
        r"\bperingatan\b", r"\bperhatian\b", r"\bwarning\b"
    ],
    COMPARE: [
        r"\bbanding(k|)an\b", r"\bvs\b", r"\blebih (baik|ampuh|aman)\b", r"\balternatif\b"
    ],
    PRICE_AVAILABILITY: [
        r"\bharga\b", r"\bberapa rupiah\b", r"\bbeli dimana\b", r"\bdimana beli\b", r"\bketersediaan\b", r"\bavailable\b"
    ],
    CHEMICAL_QUERY: [
        r"\brumus\b", r"\bstruktur\b", r"\bikatan\b", r"\bmekanisme reaksi\b", r"\bkimia\b"
    ],
}

WHAT_IS_PATTERNS = [
    r"\bapa itu\b",
    r"\bmaksud(ku|nya)?\s+(obat|produk)\s+ini\b",
    r"\b(obat|produk)\s+apa\b",
    r"\b(ini)\s+apa\b",
]

def _match_any(text: str, patterns) -> bool:
    for p in patterns:
        if re.search(p, text, flags=re.I):
            return True
    return False

def _contains_nie(text: str) -> bool:
    return RX_NIE.search(text or "") is not None

def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()

def classify(user_text: str, ctx: Optional[Dict] = None) -> str:
    """
    Heuristik + keyword first, lalu fallback general.
    ctx (opsional) dapat berisi:
      {
        "verification": {
            "canon": {"name": "OSKADON", "nie": "DBL..."}
        },
        "user_text": "...",
      }
    """
    txt = _norm(user_text)

    # 0) JIKA ada NIE eksplisit -> verifikasi BPOM
    if _contains_nie(txt):
        return VERIFY_BPOM

    # 1) Rule-based kuat (keyword Indonesia)
    for label, patterns in KEYWORDS.items():
        if _match_any(txt, patterns):
            return label

    # 2) “Apa itu <produk>” / konteks “obat ini” bila ada canon name
    canon_name = _norm(((ctx or {}).get("verification") or {}).get("canon", {}).get("name"))
    canon_nie  = _norm(((ctx or {}).get("verification") or {}).get("canon", {}).get("nie"))
    if _match_any(txt, WHAT_IS_PATTERNS):
        # Jika ada nama/NIE aktif di session → anggap merujuk ke produk tsb
        return WHAT_IS

    # 3) Pertanyaan generik tentang “obat ini / obat tsb” → jika ada canon, treat as WHAT_IS/USAGE
    if canon_name or canon_nie:
        if re.search(r"\bobat( ini| tersebut)?\b", txt) or "oskadon" in txt:
            return WHAT_IS

    # 4) Kata kunci verifikasi implisit
    if re.search(r"\b(terdaftar|asli|palsu|valid|izin edar|bpom)\b", txt):
        return VERIFY_BPOM

    # 5) “apa itu <nama>” tanpa kata “obat” sekalipun
    if re.search(r"\bapa itu\s+\w+", txt):
        return WHAT_IS

    # 6) fallback aman → general_drug_info (jangan out_of_scope kecuali jelas)
    return GENERAL_DRUG_INFO
