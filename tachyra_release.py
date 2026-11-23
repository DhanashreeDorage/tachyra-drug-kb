"""Tachyra Drug Knowledge Base — steps 5 and 6: approval check and numbered release.

Reads a completed review sheet (CSV) and builds a release file containing only facts that:
  - the reviewer accepted or corrected (reviewer_decision = Accept or Correct), with reviewer name and date, and
  - if the final severity is contraindicated or major, a physician approved (approved_by and approved_date).
Everything else is listed in a hold report so nothing is dropped silently.

    python3 tachyra_release.py druglabels_out/review_sheet_20261120-1015.csv 1
writes releases/drug_kb_release_v1.json and releases/hold_report_v1.csv.
The diagnosis engine should load only release files and record the release number for each case.
"""
import csv
import json
import os
import sys
import time

HIGH = {"contraindicated", "major"}
SEVERITIES = {"contraindicated", "major", "moderate", "minor"}


def check(row):
    """Return (fact, None) if releasable, else (None, reason)."""
    decision = row.get("reviewer_decision", "").strip().lower()
    if decision == "reject":
        return None, "rejected by reviewer"
    if decision not in ("accept", "correct"):
        return None, "not yet reviewed"
    if not row.get("reviewed_by", "").strip() or not row.get("reviewed_date", "").strip():
        return None, "missing reviewer name or date"
    severity = row.get("proposed_severity", "").strip().lower()
    if decision == "correct":
        severity = row.get("corrected_severity", "").strip().lower() or severity
    if severity not in SEVERITIES:
        return None, f"invalid severity '{severity}'"
    if severity in HIGH and (not row.get("approved_by", "").strip() or not row.get("approved_date", "").strip()):
        return None, f"{severity} fact needs physician approval"
    fact = {k: row.get(k, "") for k in ["fact_id", "drug", "rxcui", "type", "with", "effect", "label_action",
                                         "source_section", "source_quote", "label_set_id", "label_date",
                                         "dailymed_url", "reviewer_notes", "reviewed_by", "reviewed_date",
                                         "approved_by", "approved_date"]}
    fact["severity"] = severity
    return fact, None


def read_rows(sheet):
    """Read the review sheet from CSV or from the reviewers' Excel workbook."""
    if sheet.lower().endswith(".xlsx"):
        from openpyxl import load_workbook
        ws = load_workbook(sheet, data_only=True)["Review"]
        values = list(ws.iter_rows(values_only=True))
        head = [str(h) for h in values[0]]
        return [{h: ("" if v is None else str(v)) for h, v in zip(head, r)} for r in values[1:] if any(r)]
    return list(csv.DictReader(open(sheet, encoding="utf-8-sig")))


def main(sheet, version):
    rows = read_rows(sheet)
    released, held = [], []
    for r in rows:
        fact, reason = check(r)
        if fact:
            released.append(fact)
        else:
            held.append({"fact_id": r.get("fact_id", ""), "drug": r.get("drug", ""), "with": r.get("with", ""), "reason": reason})
    os.makedirs("releases", exist_ok=True)
    out = {"release": int(version), "created": time.strftime("%Y-%m-%d %H:%M"), "source_sheet": os.path.basename(sheet),
           "fact_count": len(released), "drugs": sorted({f["drug"] for f in released}), "facts": released}
    path = f"releases/drug_kb_release_v{version}.json"
    if os.path.exists(path):
        sys.exit(f"{path} already exists. Releases are never overwritten; use the next number.")
    json.dump(out, open(path, "w"), indent=2)
    with open(f"releases/hold_report_v{version}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["fact_id", "drug", "with", "reason"])
        w.writeheader()
        w.writerows(held)
    print(f"Release v{version}: {len(released)} facts ({len(out['drugs'])} drugs). Held back: {len(held)}.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
