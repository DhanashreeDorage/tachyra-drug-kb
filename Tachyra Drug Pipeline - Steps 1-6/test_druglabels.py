"""Offline test of label selection using made-up records shaped like openFDA results (not real labels)."""
import tachyra_druglabels as T
fake = [
  {"set_id":"combo","effective_time":"20250101","openfda":{"product_type":["HUMAN PRESCRIPTION DRUG"],"substance_name":["LISINOPRIL","HYDROCHLOROTHIAZIDE"]}},
  {"set_id":"otc","effective_time":"20250301","openfda":{"product_type":["HUMAN OTC DRUG"],"substance_name":["LISINOPRIL"]}},
  {"set_id":"old","effective_time":"20200101","openfda":{"product_type":["HUMAN PRESCRIPTION DRUG"],"substance_name":["LISINOPRIL"]},"drug_interactions":["old text"]},
  {"set_id":"new","effective_time":"20240601","openfda":{"product_type":["HUMAN PRESCRIPTION DRUG"],"substance_name":["LISINOPRIL"]},"drug_interactions":["new text"],"contraindications":["c"]},
]
best = T.choose_label(fake, "lisinopril")
assert best["set_id"] == "new", best["set_id"]          # newest single-ingredient Rx label; combination and OTC rejected
assert T.choose_label(fake[:2], "lisinopril") is None    # only combo/OTC available -> none
rec = T.label_record("Zestril", "29046", "lisinopril", best)
assert rec["sections"]["drug_interactions"] == "new text" and "boxed_warning" not in rec["sections"]
assert rec["dailymed_url"].endswith("setid=new")
print("ALL TESTS PASSED")
