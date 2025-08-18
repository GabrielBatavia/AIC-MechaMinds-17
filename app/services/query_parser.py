# app/services/query_parser.py
import re
from dataclasses import dataclass

NIE_RE = re.compile(r'\b([A-Z]{2,3}\d{8,12})\b', re.I)  # adapt to real BPOM formats

@dataclass
class ParsedQuery:
    kind: str
    nie: str|None
    title: str|None
    manufacturer: str|None
    dose: str|None
    raw: str

def parse_user_query(text: str) -> ParsedQuery:
    nie = None
    m = NIE_RE.search(text.replace(' ', ''))
    if m: nie = m.group(1).upper()
    # super-light heuristics:
    manu = None
    if "pt " in text.lower():
        # extract chunk after "pt"
        manu = "PT " + text.split("pt",1)[1].strip().split()[0].title() if True else None
    # title/dose split
    title = re.sub(r'pt\s+.*', '', text, flags=re.I).strip()
    dose = None
    mdose = re.search(r'(\d+\s?mg|\d+\s?mcg|\d+\s?ml)', text, re.I)
    if mdose: dose = mdose.group(1)
    kind = "nie" if nie else ("manufacturer" if manu else "title")
    return ParsedQuery(kind, nie, title or None, manu, dose, text)
