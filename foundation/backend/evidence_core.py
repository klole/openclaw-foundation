"""Source-derived saved-evidence primitives; no network or credential code."""
import hashlib
import re
from datetime import date

def normalize(text: str) -> str:
    """Whitespace-insensitive, quote-mark-insensitive form used for quote matching."""
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()

def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

class Snapshot:
    def __init__(self, source_id: str, text: str, source_class: str, url: str = "", host: str = "",
                 observed_at: str = "", title: str = ""):
        self.source_id = source_id
        self.text = text
        self.source_class = source_class
        self.url = url or source_id
        self.host = host or source_id
        self.observed_at = observed_at or date.today().isoformat()
        self.title = title
        self.sha256 = sha256(text)
        self._norm = None

    @property
    def normalized(self) -> str:
        if self._norm is None:
            self._norm = normalize(self.text)
        return self._norm

    def find_quote(self, quote: str) -> int:
        """Offset of the quote in the normalized snapshot, or -1."""
        q = normalize(quote)
        return self.normalized.find(q) if q else -1

    def meta(self) -> dict:
        return {"source_id": self.source_id, "url": self.url, "host": self.host,
                "source_class": self.source_class, "observed_at": self.observed_at,
                "sha256": self.sha256, "chars": len(self.text), "title": self.title}

def absence_check(terms: list, snapshots: list) -> dict:
    """Code's absence check: none of the searched terms may appear in any listed snapshot."""
    clean = [t.strip() for t in terms if t and len(t.strip()) >= 3]
    hits = []
    for term in clean:
        low = normalize(term).lower()
        for snap in snapshots:
            if low in snap.normalized.lower():
                hits.append({"term": term, "source_id": snap.source_id})
    return {"method": "term search over saved snapshots", "queries_run": clean,
            "pages_checked": len(snapshots), "hits": hits,
            "absent": bool(clean) and bool(snapshots) and not hits}
