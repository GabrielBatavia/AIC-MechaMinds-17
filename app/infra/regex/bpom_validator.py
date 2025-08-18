# app/infra/regex/bpom_validator.py
import re, yaml, os, time
from app.domain.validators import BpomValidator, BpomValidation

class RegexBpomValidator(BpomValidator):
    DEFAULT_ALLOW_PREFIX = ["DKL", "DBL", "DKI", "ML", "MD"]
    DEFAULT_PATTERNS = [
        r'(?:DKL|DBL|DKI)\d{8,14}',
        r'(?:ML|MD)\d{12,15}',
        r'BPOM(?:RI)?(?:ML|MD)\d{12,15}',
        r'P-?IRT\d{12,17}',
    ]
    DEFAULT_BLACKLIST = [r'(?i)SAMPLE', r'(?i)DEMO']

    def __init__(self, cfg_path: str | None = None):
        path = cfg_path or os.getenv("REGEX_CFG", "config/regex.yaml")
        cfg = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception as e:
            # fallback aman saat YAML invalid/missing
            print(f"[RegexBpomValidator] WARN: load {path} failed: {e} — using defaults")

        self.allow_prefix = cfg.get("allow_prefix", self.DEFAULT_ALLOW_PREFIX)
        pats = cfg.get("patterns", self.DEFAULT_PATTERNS)
        bls  = cfg.get("blacklist", self.DEFAULT_BLACKLIST)

        self.patterns = [re.compile(p) for p in pats]
        self.blacklist = [re.compile(p) for p in bls]

    def validate(self, text: str) -> BpomValidation:
        t0 = time.time()
        s = text.upper().replace(" ", "")
        for bl in self.blacklist:
            if bl.search(s):
                return BpomValidation(number=None, confidence=0.0, notes="blacklisted")
        for i, pat in enumerate(self.patterns):
            m = pat.search(s)
            if m:
                num = m.group(0)
                if self.allow_prefix and not any(num.startswith(p) for p in self.allow_prefix):
                    continue
                conf = min(0.99, 0.6 + 0.02*len(num))
                return BpomValidation(number=num, confidence=conf, pattern_id=f"pat_{i}")
        return BpomValidation(number=None, confidence=0.0)
