# Source-derived deterministic gates; see provenance.json.
"""Findings in, gated claims out. Everything here is code; no model grades anything.

A seat writes prose, then ends with labeled blocks (plain text, not JSON):

    Finding: one factual sentence that does not go past the quote
    Quote: "text copied exactly from the source"      (1 to 6 Quote lines)
    Source: the source id or URL of a saved snapshot
    Number: 100; 40                                  (optional: numbers the finding relies on)
    Arithmetic: 100 - 40 = 60                       (optional: derived numbers, inputs from the quotes)
    Conditions: business_model=physical_products; channel=email; budget=0   (optional)
    Searched: term; term                              (gap findings: what was searched on our own pages)
    Question: Q-0004                                  (optional: the question this answers)

    Not found: what was looked for and is not in any source
    Searched: term; term
    Question: Q-0013

A block missing a required line is recorded and withheld; it is never sent back for a format repair.
Python 3.9 standard library only.
"""

from __future__ import annotations

import ast
import operator
import re

from .evidence_core import absence_check, normalize

LABEL = re.compile(
    r"^\s*(?:[-*>]\s*)?(?:\*\*|__)?\s*(Finding|Quote|Source|Number|Numbers|Arithmetic|Conditions|Searched|"
    r"Questions?|Not found|In)\s*(?:\*\*|__)?\s*:\s*(?:\*\*|__)?\s*(.*?)\s*$", re.IGNORECASE)

SEAT_TYPE = {"baseline": "baseline", "cases": "case", "failures": "failure", "competitors": "gap",
             "objection": "objection", "routes": "finding"}
CAUSAL_CLASSES = {"internal_measurement", "primary_data", "first_party_case"}
WEAK_CLASSES = {"firsthand_self_report", "x_article", "x_post", "x_article_unverified", "secondary_analysis", "tertiary"}
OWN_CLASSES = {"internal_measurement", "internal_record"}
CAUSAL_WORDS = re.compile(r"\b(caus(?:e|ed|es|ing)|led to|leads to|drove|drives|resulted in|results in|"
                          r"because of|thanks to|increased|boosted|lifted|grew|produced|generated)\b", re.I)
MAX_QUOTES = 6


def _clean_quote(value: str) -> str:
    value = value.strip()
    pairs = [('"', '"'), ("“", "”"), ("'", "'"), ("`", "`")]
    for left, right in pairs:
        if len(value) >= 2 and value.startswith(left) and value.endswith(right):
            return value[1:-1].strip()
    return value


def _quote_lines(value: str, rest: list, most: int = 12) -> str:
    """A quote that opens with a quote mark and doesn't close on its line goes on over the next lines (a list or table
    copied as it stands) up to the closing mark (2026-10-02 end-to-end test: only '"Cart and checkout' was kept)."""
    v = value.strip()
    if not v or v[0] not in "\"\u201c" or (len(v) > 1 and v[-1] in "\"\u201d"):
        return value
    out = [value]
    for line in rest[:most]:
        if LABEL.match(line) or not line.strip():
            return value                    # never closed: keep the first line, as before
        out.append(line)
        if line.rstrip()[-1:] in "\"\u201d":
            return "\n".join(out)
    return value


def parse_blocks(text: str) -> tuple:
    """Return (findings, not_found) as lists of dicts. Unlabeled prose is ignored here, not rejected."""
    findings, missing = [], []
    current = None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^\s{0,3}#{1,6}\s", line):
            current = None
            continue
        m = LABEL.match(line)
        if not m:
            continue
        label, value = m.group(1).lower(), m.group(2)
        if label == "finding":
            current = {"finding": value.strip(), "quotes": [], "source": "", "numbers": [], "arithmetic": [],
                       "conditions": {}, "searched": [], "question_ids": [], "in": ""}
            findings.append(current)
        elif label == "not found":
            current = {"not_found": value.strip(), "searched": [], "question_ids": [], "in": ""}
            missing.append(current)
        elif current is None:
            continue
        elif label == "quote":
            if "quotes" in current:
                current["quotes"].append(_clean_quote(_quote_lines(value, lines[i + 1:])))
        elif label == "source":
            if "source" in current and not current["source"]:
                current["source"] = value.strip().strip("`<>").strip()
        elif label in ("number", "numbers"):
            if "numbers" in current and value.strip().lower() not in ("", "none", "none stated"):
                current["numbers"] += [x.strip() for x in re.split(r"[;,](?!\d{3})", value) if x.strip()]
        elif label == "arithmetic":
            if "arithmetic" in current and value.strip().lower().strip(".") not in ("", "none", "n/a", "none needed"):
                current["arithmetic"].append(value.strip())
        elif label == "conditions":
            if "conditions" in current:
                for part in re.split(r";", value):
                    if "=" in part:
                        k, _, v = part.partition("=")
                        current["conditions"][k.strip().lower()] = v.strip()
        elif label == "searched":
            current["searched"] += [x.strip().strip('"') for x in value.split(";") if x.strip()]
        elif label in ("question", "questions"):
            current["question_ids"] += re.findall(r"Q-\d{4}", value)
        elif label == "in":
            current["in"] = value.strip()
    return findings, missing


# ---------------------------------------------------------------- numbers

NUM = re.compile(r"\$?(?:\d{1,3}(?:,\d{3})+(?!\d)|\d+)(?:\.\d+)?%?")


def number_value(token: str):
    token = token.replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(token)
    except ValueError:
        return None


def numbers_in(text: str) -> list:
    """Every number in the text. '1,060' is read as 1060 and also as 1 and 060, so a table row
    such as 'fixture_record,100,10,40,4' yields 100, 10, 40 and 4 whichever way it is read."""
    out = []
    for tok in NUM.findall(text):
        for piece in [tok] + (tok.split(",") if "," in tok else []):
            value = number_value(piece)
            if value is not None and value not in out:
                out.append(value)
    return out


def token_on_quote(token: str, known: list) -> bool:
    """A claim's number is on the quote. A plain number must match one; a range or a number with words ("8-12%",
    "5–12%", "12 months", "~25%") passes when every number in it is on the quote (2026-10-02 end-to-end test: every
    range was refused, so benchmark claims never verified)."""
    value = number_value(token)
    values = [value] if value is not None else [number_value(t) for t in NUM.findall(str(token))]
    return bool(values) and all(v is not None and any(abs(v - q) < 1e-9 for q in known) for v in values)


def glued_on_quote(token: str, quote: str) -> bool:
    """A table copied from a page can glue cells together ("Fixture row1001.0%0.5 – 2.0%"): a number of at
    least three characters (digits, a point or a percent sign) that appears as written inside the quote counts."""
    pieces = [t for t in NUM.findall(str(token))]
    return bool(pieces) and all(len(p.replace("$", "").replace(",", "")) >= 3 and p.replace("$", "") in quote.replace(",", "")
                                for p in pieces)


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand)
    raise ValueError("only + - * / and parentheses are allowed")


def check_arithmetic(line: str, quote_numbers: list) -> tuple:
    """'100 - 40 = 60': every input must be on the quotes and the result must be right.

    Returns (ok, result or None, reason)."""
    if line.count("=") != 1:
        return False, None, "arithmetic needs exactly one '='"
    left, right = line.split("=")
    expr = re.sub(r"(?<=\d),(?=\d{3})", "", left.replace("$", "").replace("%", "")).replace("×", "*")
    try:
        value = _eval(ast.parse(expr.strip(), mode="eval"))
    except (SyntaxError, ValueError, ZeroDivisionError) as err:
        return False, None, "arithmetic not checkable: %s" % err
    stated = number_value(right.strip().split()[0]) if right.strip() else None
    if stated is None:
        return False, None, "arithmetic result is not a number"
    for n in [number_value(tok) for tok in NUM.findall(left)]:
        if not any(abs(n - q) < 1e-9 for q in quote_numbers):
            return False, None, "arithmetic input %g is not on the quote" % n
    decimals = len(right.strip().split()[0].split(".")[1].rstrip("%")) if "." in right.strip().split()[0] else 0
    if abs(round(value, decimals) - stated) > 10 ** (-decimals) / 2 + 1e-9:
        return False, None, "arithmetic is wrong: %s gives %g" % (left.strip(), value)
    return True, stated, ""


# ---------------------------------------------------------------- fit (design section 10)

def _budget_band(value):
    try:
        return "zero" if float(str(value).replace("$", "").replace(",", "")) == 0 else "paid"
    except (TypeError, ValueError):
        return "unknown"


def fit_of(conditions: dict, us: dict, source_class: str) -> str:
    """direct / adjacent / exploratory, by bands. A claim about our own records is direct."""
    if source_class in OWN_CLASSES:
        return "direct"
    keys = ("business_model", "channel", "budget")
    if any(str(conditions.get(k, "")).strip().lower() in ("", "unknown", "none") for k in keys):
        return "exploratory"
    diffs = 0
    for key in ("business_model", "channel"):
        if str(conditions.get(key)).strip().lower() != str(us.get(key, "")).strip().lower():
            diffs += 1
    if _budget_band(conditions.get("budget")) != _budget_band(us.get("budget")):
        diffs += 1
    return "direct" if diffs == 0 else ("adjacent" if diffs == 1 else "exploratory")


# ---------------------------------------------------------------- the gate before the judge

def sentence_count(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", text.strip()) if s])


def gate_finding(block: dict, claim_id: str, seat: str, stage: str, store, card: dict, limits: dict) -> dict:
    """Design sections 10-11 in code. Returns a claim row; status 'pending' means it goes to the judge."""
    claim = {"claim_id": claim_id, "seat": seat, "stage": stage, "type": SEAT_TYPE.get(seat, "finding"),
             "finding": block.get("finding", ""), "quotes": block.get("quotes", []),
             "source_id": block.get("source", ""), "numbers": block.get("numbers", []),
             "arithmetic": block.get("arithmetic", []), "conditions": block.get("conditions", {}),
             "question_ids": block.get("question_ids", []), "status": "pending", "reasons": [],
             "source_class": None, "fit": None, "trial_only": None, "absence_check": None}
    reasons = claim["reasons"]
    finding = claim["finding"]
    if not finding:
        reasons.append("no finding sentence")
    elif len(finding) > limits["max_finding_chars"] or sentence_count(finding) > 2:
        reasons.append("compound finding: one assertion per finding (%d chars, %d sentences)"
                       % (len(finding), sentence_count(finding)))
    if not claim["quotes"]:
        reasons.append("no quote")
    if len(claim["quotes"]) > MAX_QUOTES:
        reasons.append("more than %d quotes" % MAX_QUOTES)
    if any(len(q) > limits["max_quote_chars"] for q in claim["quotes"]):
        reasons.append("quote longer than %d characters: quote the sentence, not the page" % limits["max_quote_chars"])
    if any(len(normalize(q)) < 8 for q in claim["quotes"]):
        reasons.append("quote too short to check")
    snap = store.get(claim["source_id"]) if claim["source_id"] else None
    if not claim["source_id"]:
        reasons.append("no source")
    elif snap is None:
        reasons.append("source %r is not a saved snapshot in this run" % claim["source_id"])
    if snap is not None:
        claim.update({"url": snap.url, "host": snap.host, "source_class": snap.source_class,
                      "observed_at": snap.observed_at, "snapshot_sha256": snap.sha256})
        offsets = [snap.find_quote(q) for q in claim["quotes"]]
        claim["quote_offsets"] = offsets
        if claim["quotes"] and any(o < 0 for o in offsets):
            reasons.append("quote is not in the snapshot")
    if reasons:
        claim["status"] = "unsupported"
        return claim

    quote_numbers = numbers_in(" ".join(claim["quotes"]))
    derived = []
    for line in claim["arithmetic"]:
        ok, result, why = check_arithmetic(line, quote_numbers)
        if not ok:
            reasons.append(why)
        else:
            derived.append(result)
    for token in claim["numbers"]:
        if not token_on_quote(token, quote_numbers + derived) and not glued_on_quote(token, " ".join(claim["quotes"])):
            reasons.append("number %s is not on the quote or a checked arithmetic line" % token)
    if claim["type"] == "gap":
        own = [s for s in store.all() if s.source_class in OWN_CLASSES]
        check = absence_check(block.get("searched", []), own)
        claim["absence_check"] = check
        if not check["absent"]:
            reasons.append("gap without a passing absence check on our own sources")
    if reasons:
        claim["status"] = "unsupported"
        return claim

    claim["fit"] = fit_of(claim["conditions"], card.get("us") or {}, claim["source_class"])
    claim["trial_only"] = claim["fit"] != "direct"
    if claim["source_class"] in WEAK_CLASSES and CAUSAL_WORDS.search(finding):
        claim["status"] = "disputed"
        reasons.append("%s worded as a cause" % claim["source_class"])
    if claim["source_class"] == "x_article_unverified":
        claim["status"] = "disputed"
        reasons.append("X Article text is the seat's copy, not checked against X: it supports nothing on its own")
    return claim


def dedupe_key(claim: dict) -> tuple:
    """Same source, same quotes and same arithmetic is the same claim, however it is worded."""
    return (claim.get("source_id", ""), tuple(sorted(normalize(q).lower() for q in claim.get("quotes", []))),
            tuple(sorted(re.sub(r"\s+", "", a) for a in claim.get("arithmetic", []))))


def apply_same_host_rule(claims: list) -> None:
    """More than half of one seat's claims from one outside host: those claims are disputed (section 11)."""
    by_seat = {}
    for c in claims:
        if c["status"] in ("pending", "supported") and c.get("source_class") not in OWN_CLASSES:
            by_seat.setdefault((c["seat"], c["stage"]), []).append(c)
    for group in by_seat.values():
        if len(group) < 3:
            continue
        counts = {}
        for c in group:
            counts[c["host"]] = counts.get(c["host"], 0) + 1
        for host, n in counts.items():
            if n * 2 > len(group):
                for c in group:
                    if c["host"] == host:
                        c["status"] = "disputed"
                        c["reasons"].append("more than half of this seat's claims share host %s" % host)


def gap_record(block: dict, gap_id: str, snapshots: list) -> dict:
    wanted = block.get("in", "").strip().lower()
    if wanted and wanted not in ("all", "all sources", "every source"):
        ids = {x.strip() for x in re.split(r"[;,]", block["in"])}
        snapshots = [s for s in snapshots if s.source_id in ids]
    check = absence_check(block.get("searched", []), snapshots)
    return {"gap_id": gap_id, "what": block.get("not_found", ""), "question_ids": block.get("question_ids", []),
            "absence_check": check, "documented": check["absent"]}
