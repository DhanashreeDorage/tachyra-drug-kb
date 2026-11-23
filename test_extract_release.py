"""Offline tests with a made-up label and a fake model reply (no network, no real clinical content)."""
import csv, json, os, shutil, tempfile
d = tempfile.mkdtemp(); os.environ["TQD_OUT"] = d
import tachyra_extract as E, tachyra_release as R
base = os.path.join(d, "testdrug")
json.dump({"ingredient": "testdrug", "rxcui": "1", "set_id": "abc", "effective_time": "20250101",
           "dailymed_url": "u", "sections": {"drug_interactions": "Concomitant use with Otherdrug  increases exposure; do not exceed 10 mg daily.\nAvoid grapefruit juice with this product."}},
          open(base + ".label.json", "w"))
open(base + ".extraction_prompt.txt", "w").write("prompt")
good = {"type": "dose_limit", "drug": "testdrug", "with": "Otherdrug", "effect": "higher levels", "label_action": "max 10 mg",
        "proposed_severity": "major", "source_section": "7", "source_quote": "Concomitant use with Otherdrug increases exposure; do not exceed 10 mg daily."}
fake_quote = dict(good, **{"with": "Madeupdrug", "source_quote": "Concomitant use with Madeupdrug is contraindicated in all patients."})
bad_type = dict(good, type="vibes")
food = dict(good, **{"type": "interaction", "with": "grapefruit juice", "proposed_severity": "moderate",
                     "source_quote": "Avoid grapefruit juice with this product."})
reply = "Here are the facts:\n```json\n" + json.dumps([good, fake_quote, bad_type, good, food]) + "\n```"
kept, rej = E.process_label(base, ask=lambda p, k: reply)
assert [k["with"] for k in kept] == ["Otherdrug", "grapefruit juice"], kept
reasons = sorted(r["reason"] for r in rej)
assert reasons == ["duplicate", "quoted sentence not found in label", "unknown type vibes"], reasons
k2, r2 = E.process_label(base, ask=lambda p, k: "sorry, no list")
assert not k2 and "unreadable" in r2[0]["reason"]
# release: major needs approval; moderate accepted; unreviewed held
sheet = os.path.join(d, "sheet.csv")
rows = [dict(kept[0], reviewer_decision="Accept", reviewed_by="DP", reviewed_date="2026-11-20"),      # major, no approval -> hold
        dict(kept[1], reviewer_decision="Accept", reviewed_by="DP", reviewed_date="2026-11-20"),      # moderate -> release
        dict(kept[0], fact_id="x3", reviewer_decision="Correct", corrected_severity="moderate", reviewed_by="DP", reviewed_date="2026-11-20"),  # corrected down -> release
        dict(kept[0], fact_id="x4", reviewer_decision="Accept", reviewed_by="DP", reviewed_date="2026-11-20", approved_by="AC", approved_date="2026-11-21"),  # approved -> release
        dict(kept[0], fact_id="x5"), dict(kept[0], fact_id="x6", reviewer_decision="Reject")]
with open(sheet, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=E.REVIEW_COLUMNS); w.writeheader(); [w.writerow({k: r.get(k, "") for k in E.REVIEW_COLUMNS}) for r in rows]
cwd = os.getcwd(); os.chdir(d)
R.main(sheet, 1)
rel = json.load(open("releases/drug_kb_release_v1.json"))
assert sorted(f["fact_id"] for f in rel["facts"]) == sorted([kept[1]["fact_id"], "x3", "x4"]), rel["facts"]
assert next(f for f in rel["facts"] if f["fact_id"] == "x3")["severity"] == "moderate"
held = {r["fact_id"]: r["reason"] for r in csv.DictReader(open("releases/hold_report_v1.csv"))}
assert "physician approval" in held[kept[0]["fact_id"]] and held["x5"] == "not yet reviewed" and held["x6"] == "rejected by reviewer"
try:
    R.main(sheet, 1); raise AssertionError("overwrite allowed")
except SystemExit as e:
    assert "never overwritten" in str(e)
os.chdir(cwd); shutil.rmtree(d)
print("ALL TESTS PASSED")

# xlsx round trip
import tempfile as _t, make_review_workbook as M
from openpyxl import load_workbook
d2 = _t.mkdtemp(); os.chdir(d2)
p = os.path.join(d2, "s.csv")
with open(p, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=E.REVIEW_COLUMNS); w.writeheader()
    w.writerow({k: r.get(k, "") for k, r in [(k, dict(kept[1], fact_id="y1")) for k in E.REVIEW_COLUMNS]})
x = M.build(p)
wb = load_workbook(x); ws = wb["Review"]
hdr = [c.value for c in ws[1]]
ws.cell(row=2, column=hdr.index("reviewer_decision") + 1, value="Accept")
ws.cell(row=2, column=hdr.index("reviewed_by") + 1, value="DP")
ws.cell(row=2, column=hdr.index("reviewed_date") + 1, value="2026-11-20")
wb.save(x)
R.main(x, 7)
assert json.load(open("releases/drug_kb_release_v7.json"))["fact_count"] == 1
os.chdir(cwd); shutil.rmtree(d2)
print("XLSX ROUND TRIP PASSED")
