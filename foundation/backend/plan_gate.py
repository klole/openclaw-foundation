# Source-derived deterministic gates; see provenance.json.
"""The plan gate (design section 17). Code rejects the plan; no model grades it."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .claims import CAUSAL_CLASSES
def card_ladder(card):
    return list(card.get("ladder") or ["exposure", "engagement", "qualified action", "outcome"])

ITEM = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?(Play|Trial)\s+((?:PLAY|TRIAL)-\d+)(?:\*\*)?\s*:?\s*(.*)$", re.I)
FIELD = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?(Claims|Because|Expected change|Leading metric|Goal metric|Expected lag|"
                   r"Checkpoint|Compare on|Keep if|Kill if)(?:\*\*)?\s*:\s*(.*)$", re.I)
GOAL = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?Goal(?:\*\*)?\s*:\s*(.*)$", re.I)
SETUP = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?Setup(?:\*\*)?\s*:\s*(.*)$", re.I)
CONSTRAINT = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?Constraint\s+(.+?)(?:\*\*)?\s*:\s*\$?([\d,.]+)", re.I)
CLAIM_ID = re.compile(r"CLM-\d{4}")
PLAY_FIELDS = ("because", "expected change", "leading metric", "goal metric", "expected lag")


def parse_plan(text: str) -> dict:
    plan = {"goal": None, "setup": [], "items": [], "constraints": {}}
    current = None
    for line in text.splitlines():
        m = GOAL.match(line)
        if m and plan["goal"] is None:
            plan["goal"] = m.group(1).strip().strip('"').strip("“”")
            continue
        m = SETUP.match(line)
        if m:
            plan["setup"].append(m.group(1).strip())
            current = None
            continue
        m = CONSTRAINT.match(line)
        if m:
            plan["constraints"][m.group(1).strip().lower()] = float(m.group(2).replace(",", "").rstrip("."))
            continue
        m = ITEM.match(line)
        if m:
            current = {"kind": m.group(1).lower(), "id": m.group(2).upper(), "name": m.group(3).strip(), "fields": {}}
            plan["items"].append(current)
            continue
        m = FIELD.match(line)
        if m and current is not None:
            current["fields"][m.group(1).lower()] = m.group(2).strip()
    return plan


def _parse_date(text: str):
    m = re.search(r"\d{4}-\d{2}-\d{2}", text or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(), "%Y-%m-%d").date()
    except ValueError:
        return None


def plan_gate(text: str, card: dict, claims: dict, gap_question_ids: list, today: date = None) -> dict:
    """claims: claim_id -> row (only verified rows count). Returns {'pass', 'rejects', 'plan'}."""
    today = today or date.today()
    plan = parse_plan(text)
    rejects = []
    ladder = [r.lower() for r in card_ladder(card)]
    trial_days = int(card.get("trial_window_days", 14))
    verified = {cid: row for cid, row in claims.items() if row.get("status") == "supported"}

    if (plan["goal"] or "") != card["goal_exact"]:
        rejects.append("Goal line differs from the card's goal_exact")
    plays = [i for i in plan["items"] if i["kind"] == "play"]
    trials = [i for i in plan["items"] if i["kind"] == "trial"]
    if not plays and not trials:
        rejects.append("no plays or trials")
    for item in plan["items"]:
        f = item["fields"]
        ids = CLAIM_ID.findall(f.get("claims", ""))
        if not ids:
            rejects.append("%s has no claim id" % item["id"])
        for cid in ids:
            if cid not in verified:
                rejects.append("%s cites %s, which is not a verified claim" % (item["id"], cid))
        for field in PLAY_FIELDS:
            if not f.get(field):
                rejects.append("%s is missing %s" % (item["id"], field.capitalize()))
        stray = set(CLAIM_ID.findall(f.get("because", ""))) - set(ids)
        if stray:
            rejects.append("%s Because cites %s, not on that item" % (item["id"], ", ".join(sorted(stray))))
        if f.get("leading metric") and f["leading metric"].strip().lower() not in ladder:
            rejects.append("%s leading metric %r is not a rung on the ladder %s" % (item["id"], f["leading metric"], ladder))
        if f.get("goal metric") and f["goal metric"].strip() != str(card["unit"]):
            rejects.append("%s goal metric %r differs from the card unit %r" % (item["id"], f["goal metric"], card["unit"]))
        rows = [verified[c] for c in ids if c in verified]
        if item["kind"] == "play":
            if rows and any(r.get("trial_only") for r in rows):
                rejects.append("%s cites a trial_only claim; that can only be a trial" % item["id"])
            if rows and not any(r.get("source_class") in CAUSAL_CLASSES for r in rows):
                rejects.append("%s has no claim whose class can support a cause" % item["id"])
            if not f.get("checkpoint") or not re.search(r"\d", f.get("checkpoint", "")):
                rejects.append("%s checkpoint needs a date, a rung and a number" % item["id"])
        else:
            for field in ("compare on", "keep if", "kill if"):
                if not f.get(field):
                    rejects.append("%s is missing %s" % (item["id"], field.capitalize()))
            when = _parse_date(f.get("compare on", ""))
            if f.get("compare on") and (when is None or when > today + timedelta(days=trial_days) or when < today):
                rejects.append("%s compare date must be within %d days of %s" % (item["id"], trial_days, today))
    for line in plan["setup"]:
        ids = CLAIM_ID.findall(line)
        if not ids and not re.search(r"Q-\d{4}", line):
            rejects.append("Setup line has no claim id or evidence-gap question: %s" % line[:80])
        for cid in ids:
            if cid not in verified:
                rejects.append("Setup cites %s, which is not a verified claim" % cid)
    setup_text = "\n".join(plan["setup"])
    for qid in gap_question_ids:
        if qid not in setup_text:
            rejects.append("evidence gap %s has no Setup line that measures it" % qid)
    if str(card.get("baseline", "")).strip().lower() == "unknown":
        first = plan["setup"][0].lower() if plan["setup"] else ""
        if not re.search(r"measur|baseline", first):
            rejects.append("baseline is unknown, so the first Setup line must be the measurement")
    for item in card.get("constraints") or []:
        label = item["label"].lower()
        if label not in plan["constraints"]:
            rejects.append("Constraint %s is not stated" % item["label"])
        elif plan["constraints"][label] > float(item["max"]):
            rejects.append("Constraint %s is %g, above the card's %g" % (item["label"], plan["constraints"][label], item["max"]))
    lower = text.lower()
    for word in card.get("plan_must_mention") or []:
        if word.lower() not in lower:
            rejects.append("plan never mentions %r (required by the card)" % word)
    return {"pass": not rejects, "rejects": rejects, "plan": plan}
