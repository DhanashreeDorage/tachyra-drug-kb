"""Turn a review sheet CSV into a formatted Excel workbook for the clinical reviewers.

    pip install openpyxl
    python3 make_review_workbook.py druglabels_out/review_sheet_20261120-1015.csv
writes the same name with .xlsx. Reviewers fill in the yellow columns; tachyra_release.py reads the .xlsx directly.
"""
import csv
import sys
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from tachyra_extract import REVIEW_COLUMNS

REVIEWER_COLS = {"reviewer_decision", "corrected_severity", "reviewer_notes", "reviewed_by", "reviewed_date",
                 "approved_by", "approved_date"}
WIDTHS = {"fact_id": 22, "drug": 14, "with": 22, "effect": 30, "label_action": 30, "source_quote": 60,
          "reviewer_notes": 30, "dailymed_url": 20}
INSTRUCTIONS = [
    "How to review",
    "1. Read each fact against its exact label sentence (column 'source_quote'). Open the DailyMed link if you need context.",
    "2. Reviewer (pharmacist): choose Accept, Correct or Reject in 'reviewer_decision'. If Correct, enter the right severity in 'corrected_severity' and explain in 'reviewer_notes'. Add your initials and the date.",
    "3. Physician approver: for every accepted or corrected fact whose final severity is contraindicated or major, add your initials and date in 'approved_by' and 'approved_date'.",
    "4. Facts are released only when these steps are complete. Unfinished rows are held back, never dropped.",
    "5. Do not add facts from memory or other references. If something important is missing from the label, note it in 'reviewer_notes' for follow-up.",
]


def build(csv_path):
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))
    wb = Workbook()
    ws = wb.active
    ws.title = "Review"
    head_fill, rev_fill = PatternFill("solid", fgColor="1F4E79"), PatternFill("solid", fgColor="FFF2CC")
    for i, c in enumerate(REVIEW_COLUMNS, 1):
        cell = ws.cell(row=1, column=i, value=c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[cell.column_letter].width = WIDTHS.get(c, 16)
    for r, row in enumerate(rows, 2):
        for i, c in enumerate(REVIEW_COLUMNS, 1):
            cell = ws.cell(row=r, column=i, value=row.get(c, ""))
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if c in REVIEWER_COLS:
                cell.fill = rev_fill
    last = max(len(rows) + 1, 2)
    col = {c: ws.cell(row=1, column=i).column_letter for i, c in enumerate(REVIEW_COLUMNS, 1)}
    dv1 = DataValidation(type="list", formula1='"Accept,Correct,Reject"', allow_blank=True)
    dv2 = DataValidation(type="list", formula1='"contraindicated,major,moderate,minor"', allow_blank=True)
    ws.add_data_validation(dv1)
    ws.add_data_validation(dv2)
    dv1.add(f"{col['reviewer_decision']}2:{col['reviewer_decision']}{last}")
    dv2.add(f"{col['corrected_severity']}2:{col['corrected_severity']}{last}")
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{col['approved_date']}{last}"
    ins = wb.create_sheet("Instructions")
    for i, t in enumerate(INSTRUCTIONS, 1):
        c = ins.cell(row=i, column=1, value=t)
        c.font = Font(bold=(i == 1), size=13 if i == 1 else 11)
        c.alignment = Alignment(wrap_text=True)
    ins.column_dimensions["A"].width = 110
    out = csv_path[:-4] + ".xlsx"
    wb.save(out)
    print(f"Wrote {out} ({len(rows)} facts)")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build(sys.argv[1])
