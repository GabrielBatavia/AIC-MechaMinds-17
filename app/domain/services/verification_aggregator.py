from app.domain.confidence import Evidence, EvidenceSource, VerificationResult, MatchStrength
from typing import List

WEIGHTS = {
    EvidenceSource.MONGO: 0.95,  # official
    EvidenceSource.FAISS: 0.75,  # internal semantic
    EvidenceSource.WEB:   0.60,  # external, bervariasi
}

MATCH_MULT = {
    MatchStrength.EXACT: 1.00,
    MatchStrength.STRONG: 0.85,
    MatchStrength.MEDIUM: 0.65,
    MatchStrength.WEAK: 0.40,
    MatchStrength.NONE: 0.10,
}

def clamp(x: float, lo=0.0, hi=1.0) -> float:
    return max(lo, min(hi, x))

def score_evidence(ev: Evidence) -> float:
    base = WEIGHTS[ev.source]
    m = MATCH_MULT[ev.match_strength]
    q = ev.quality
    r = ev.recency_factor
    n = ev.name_confidence
    # Skor akhir (bisa di-tweak)
    s = base * (0.45*m + 0.25*q + 0.20*r + 0.10*n)
    return clamp(s)

def aggregate(evidence: List[Evidence]) -> VerificationResult:
    if not evidence:
        return VerificationResult(
            decision="unknown",
            confidence=0.0,
            top_source=EvidenceSource.WEB,
            explanation="No evidence from Mongo, FAISS, or Web.",
            winner=None,
            all_evidence=[],
        )

    ranked = sorted(evidence, key=score_evidence, reverse=True)
    top = ranked[0]
    top_score = score_evidence(top)

    # Keputusan sederhana:
    # - Jika ada MONGO dengan EXACT/STRONG → "valid" (kecuali payload menyebut revoked)
    # - Jika semua sumber menyimpulkan tidak terdaftar → "invalid"
    # - Selain itu "unknown" dengan confidence sesuai skor
    decision = "unknown"
    expl = []

    if top.source == EvidenceSource.MONGO and top.match_strength in {MatchStrength.EXACT, MatchStrength.STRONG}:
        status = (top.payload or {}).get("state") or (top.payload or {}).get("status")
        if str(status).lower() in {"valid","registered","aktif","active"}:
            decision = "valid"
            expl.append("Found official record in Mongo (BPOM source).")
        elif str(status).lower() in {"invalid","revoked","expired","nonaktif","not_registered"}:
            decision = "invalid"
            expl.append("Official record indicates not registered/revoked.")
        else:
            decision = "valid"
            expl.append("Official record found, status unspecified but treated as valid.")

    if decision == "unknown":
        # Jika mayoritas evidence bertema 'not found'/'unregistered'
        negatives = [ev for ev in evidence if (ev.payload or {}).get("not_found") or (ev.payload or {}).get("unregistered")]
        if len(negatives) >= 2 and top_score >= 0.5:
            decision = "invalid"
            expl.append("Multiple sources suggest unregistered product.")

    if not expl:
        expl.append(f"Top evidence from {top.source} with {top.match_strength} match.")

    return VerificationResult(
        decision=decision,
        confidence=top_score,
        top_source=top.source,
        explanation=" ".join(expl),
        winner=top,
        all_evidence=evidence,
    )
