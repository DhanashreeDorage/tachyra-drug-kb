Tachyra Drug Knowledge Base - pipeline (prototype)
Python 3. Steps 1-3 use only standard Python; the Excel steps need: pip install openpyxl

STEP 1  Pull FDA labels (public data)
  python3 tachyra_druglabels.py warfarin simvastatin lisinopril metformin ...
  -> druglabels_out/<drug>.label.json, <drug>.extraction_prompt.txt, label_index.csv

STEP 2-3  AI extraction + quote check
  Set ANTHROPIC_API_KEY as an environment setting on the server (never in code or email).
  python3 tachyra_extract.py              (all labels)   or   python3 tachyra_extract.py warfarin
  -> druglabels_out/review_sheet_<time>.csv  (facts whose quoted sentence was found in the label)
  -> druglabels_out/rejected_<time>.csv      (malformed, duplicate, or quote not found)

STEP 4  Review workbook for Deepa and Annie
  python3 make_review_workbook.py druglabels_out/review_sheet_<time>.csv
  -> same name .xlsx with dropdowns and instructions. Reviewers fill in the yellow columns.

STEP 5-6  Release
  python3 tachyra_release.py druglabels_out/review_sheet_<time>.xlsx 1
  -> releases/drug_kb_release_v1.json  (only reviewed facts; contraindicated/major also need physician approval)
  -> releases/hold_report_v1.csv       (everything held back, with the reason)
  Releases are never overwritten. The engine should load only release files and log the release number per case.

Tests (offline, no network):  python3 test_druglabels.py ; python3 test_extract_release.py
Only public FDA label text is ever sent to the AI model. Never use patient information in this pipeline.
