"""Tachyra Drug Knowledge Base — steps 2 and 3: AI extraction and quote check.

Reads the output of tachyra_druglabels.py (druglabels_out/*.label.json and *.extraction_prompt.txt),
asks the AI model to propose drug-safety facts from each label, then keeps only facts whose
quoted sentence really appears in that label. Results go to a review sheet for the clinical team.

Standard library only. Run on Tachyra's server:
    export ANTHROPIC_API_KEY=...        # stored in Render settings, never in code or email
    python3 tachyra_extract.py                     # every label in druglabels_out/
    python3 tachyra_extract.py warfarin simvastatin   # only these

Optional settings: TQD_OUT (folder, default druglabels_out), TQD_MODEL (model name).
Only public FDA label text is sent to the model. Never send patient information through this script.
"""
import csv
import glob
import json
import os
import re
import sys
import time
import urllib.request

OUT_DIR = os.environ.get("TQD_OUT", "druglabels_out")
MODEL = os.environ.get("TQD_MODEL", "claude-sonnet-5-5")
API_URL = "https://api.anthropic.com/v1/messages"

FACT_TYPES = {"interaction", "contraindication", "dose_limit", "renal_dosing", "hepatic_dosing",
              "older_adult", "boxed_warning"}
SEVERITIES = {"contraindicated", "major", "moderate", "minor"}
REQUIRED = ["type", "drug", "with", "effect", "label_action", "proposed_severity", "source_section", "source_quote"]

REVIEW_COLUMNS = ["fact_id", "drug", "rxcui", "type", "with", "effect", "label_action", "proposed_severity",
                  "source_section", "source_quote", "label_set_id", "label_date", "dailymed_url",
                  "reviewer_decision", "corrected_severity", "reviewer_notes", "reviewed_by", "reviewed_date",
                  "approved_by", "approved_date"]


def normalize(text):
    """Lower-case, unify quotes and dashes, collapse whitespace, so formatting differences don't fail a real quote."""
    t = text.lower()
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = t.replace("–", "-").replace("—", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", t).strip()


def quote_in_label(quote, label_text):
    q = normalize(quote).rstrip(".")
    return len(q) >= 20 and q in normalize(label_text)


def validate(fact):
    """Return a reason string if the fact is malformed, else None."""
    if not isinstance(fact, dict):
        return "not an object"
    for k in REQUIRED:
        if not str(fact.get(k, "")).strip():
            return f"missing {k}"
    if fact["type"] not in FACT_TYPES:
        return f"unknown type {fact['type']}"
    if fact["proposed_severity"] not in SEVERITIES:
        return f"unknown severity {fact['proposed_severity']}"
    return None


def parse_json_list(text):
    """Pull the JSON list out of the model's reply, even if it adds a sentence or code fence."""
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("no JSON list in reply")
    return json.loads(text[start:end + 1])


def call_model(prompt, api_key, tries=3):
    body = json.dumps({"model": MODEL, "max_tokens": 8000,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    for i in range(tries):
        try:
            req = urllib.request.Request(API_URL, data=body, headers={
                "x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read().decode())
            return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        except Exception as e:  # rate limits or network: wait and retry
            if i == tries - 1:
                raise
            time.sleep(10 * (i + 1))


def process_label(base, ask=call_model, api_key=None):
    """Extract and check facts for one label. Returns (kept_rows, rejected_rows)."""
    rec = json.load(open(base + ".label.json"))
    prompt = open(base + ".extraction_prompt.txt").read()
    label_text = "\n".join(rec["sections"].values())
    reply = ask(prompt, api_key)
    try:
        facts = parse_json_list(reply)
    except Exception as e:
        return [], [{"drug": rec["ingredient"], "reason": f"unreadable reply: {e}", "fact": reply[:500]}]
    kept, rejected, seen = [], [], set()
    for n, f in enumerate(facts, 1):
        reason = validate(f)
        if not reason and not quote_in_label(f["source_quote"], label_text):
            reason = "quoted sentence not found in label"
        key = (str(f.get("with", "")).lower(), f.get("type"), normalize(str(f.get("source_quote", ""))))
        if not reason and key in seen:
            reason = "duplicate"
        if reason:
            rejected.append({"drug": rec["ingredient"], "reason": reason, "fact": json.dumps(f)[:500]})
            continue
        seen.add(key)
        kept.append({
            "fact_id": f"{rec['ingredient'].replace(' ', '-').lower()}-{rec.get('effective_time', '')}-{len(kept) + 1:03d}",
            "drug": rec["ingredient"], "rxcui": rec.get("rxcui", ""), "type": f["type"], "with": f["with"],
            "effect": f["effect"], "label_action": f["label_action"], "proposed_severity": f["proposed_severity"],
            "source_section": f["source_section"], "source_quote": f["source_quote"],
            "label_set_id": rec.get("set_id", ""), "label_date": rec.get("effective_time", ""),
            "dailymed_url": rec.get("dailymed_url", ""),
        })
    return kept, rejected


def main(names):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Set ANTHROPIC_API_KEY in the server's environment settings first.")
    bases = sorted(p[:-len(".label.json")] for p in glob.glob(os.path.join(OUT_DIR, "*.label.json")))
    if names:
        wanted = {n.lower().replace(" ", "_") for n in names}
        bases = [b for b in bases if os.path.basename(b) in wanted]
    all_kept, all_rej = [], []
    for b in bases:
        kept, rej = process_label(b, api_key=api_key)
        print(f"  {os.path.basename(b)}: {len(kept)} facts for review, {len(rej)} rejected")
        all_kept += kept
        all_rej += rej
    stamp = time.strftime("%Y%m%d-%H%M")
    review = os.path.join(OUT_DIR, f"review_sheet_{stamp}.csv")
    with open(review, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig opens cleanly in Excel
        w = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS)
        w.writeheader()
        for r in all_kept:
            w.writerow({k: r.get(k, "") for k in REVIEW_COLUMNS})
    with open(os.path.join(OUT_DIR, f"rejected_{stamp}.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["drug", "reason", "fact"])
        w.writeheader()
        w.writerows(all_rej)
    print(f"Review sheet: {review} ({len(all_kept)} facts). Rejected: {len(all_rej)}.")


if __name__ == "__main__":
    main(sys.argv[1:])
