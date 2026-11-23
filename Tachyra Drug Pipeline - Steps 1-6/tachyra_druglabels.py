"""Tachyra Drug Knowledge Base — step 1 prototype: fetch FDA labels and prepare them for review.

For each drug name:
  1. Look up the ingredient in RxNorm (National Library of Medicine) to get its standard ID (RxCUI).
  2. Fetch the FDA prescription label from openFDA, choosing a SINGLE-INGREDIENT product so
     combination products (e.g. lisinopril-hydrochlorothiazide) are never used by mistake.
  3. Save the label sections Tachyra needs, with the label's set ID and version date, so every
     fact can be traced to its source.
  4. Write a review sheet (CSV) and an AI-extraction request for each label.

Standard library only. Run on a computer with internet access:
    python3 tachyra_druglabels.py warfarin simvastatin lisinopril metformin
Optional: set OPENFDA_API_KEY (free from open.fda.gov) for higher rate limits.

Public-domain sources: openFDA / DailyMed labels and RxNorm. Some RxNorm content requires a free
UMLS license; the "rxcui by name" lookup used here does not.
"""
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request

OUT_DIR = os.environ.get("TQD_OUT", "druglabels_out")
SECTIONS = [  # openFDA field -> what Tachyra uses it for
    ("boxed_warning", "Boxed warning"),
    ("contraindications", "Contraindications"),
    ("drug_interactions", "Drug interactions"),
    ("dosage_and_administration", "Dosing, including limits with other drugs and in kidney or liver disease"),
    ("warnings_and_cautions", "Warnings and precautions"),
    ("geriatric_use", "Use in older adults"),
    ("use_in_specific_populations", "Specific populations (kidney, liver, pregnancy)"),
    ("adverse_reactions", "Side effects"),
]


def _get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TachyraDrugKB/0.1"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 * (i + 1))
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def rxnorm_ingredient(name):
    """Return (rxcui, normalized ingredient name) for a drug name, or (None, None)."""
    q = urllib.parse.quote(name)
    d = _get(f"https://rxnav.nlm.nih.gov/REST/rxcui.json?name={q}&search=2")
    ids = (d or {}).get("idGroup", {}).get("rxnormId") or []
    if not ids:
        return None, None
    rx = ids[0]
    props = _get(f"https://rxnav.nlm.nih.gov/REST/rxcui/{rx}/properties.json") or {}
    return rx, (props.get("properties") or {}).get("name", name)


def choose_label(results, ingredient):
    """Pick the best label: a prescription product with exactly one active ingredient matching ours,
    preferring the most recently updated. Combination products are rejected."""
    ing = ingredient.lower()
    best = None
    for r in results or []:
        of = r.get("openfda", {})
        if "HUMAN PRESCRIPTION DRUG" not in [t.upper() for t in of.get("product_type", [])]:
            continue
        subs = [s.lower() for s in of.get("substance_name", [])]
        if len(subs) != 1:          # combination product -> skip
            continue
        if ing.split()[0] not in subs[0]:
            continue
        if best is None or r.get("effective_time", "") > best.get("effective_time", ""):
            best = r
    return best


def fetch_label(ingredient):
    key = os.environ.get("OPENFDA_API_KEY")
    term = urllib.parse.quote(f'openfda.generic_name:"{ingredient}"')
    url = f"https://api.fda.gov/drug/label.json?search={term}&limit=25" + (f"&api_key={key}" if key else "")
    d = _get(url)
    return choose_label((d or {}).get("results"), ingredient)


def label_record(name, rxcui, ingredient, label):
    of = label.get("openfda", {})
    rec = {
        "query": name, "ingredient": ingredient, "rxcui": rxcui,
        "set_id": label.get("set_id"), "label_version": label.get("version"),
        "effective_time": label.get("effective_time"),
        "brand_names": of.get("brand_name", []), "manufacturer": of.get("manufacturer_name", []),
        "dailymed_url": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={label.get('set_id')}",
        "sections": {},
    }
    for field, _ in SECTIONS:
        if label.get(field):
            rec["sections"][field] = "\n".join(label[field])
    return rec


EXTRACTION_PROMPT = """You are extracting drug-safety facts from an official FDA drug label for a clinical
knowledge base. Use ONLY the label text provided. Do not add knowledge from memory.

Return JSON: a list of facts. Each fact:
{
  "type": "interaction" | "contraindication" | "dose_limit" | "renal_dosing" | "hepatic_dosing" | "older_adult" | "boxed_warning",
  "drug": "<this label's ingredient>",
  "with": "<other drug, drug class, food, supplement or condition, exactly as named in the label>",
  "effect": "<what happens, in plain words>",
  "label_action": "<what the label tells the prescriber to do, e.g. 'contraindicated', 'do not exceed 20 mg daily', 'monitor INR'>",
  "proposed_severity": "contraindicated" | "major" | "moderate" | "minor",
  "source_section": "<label section number and title>",
  "source_quote": "<the exact sentence from the label supporting this fact, max 300 characters>"
}
Every fact must have a source_quote copied word for word from the label. If unsure, leave the fact out.
A clinician will review every fact before it is used.

LABEL ({ingredient}, set ID {set_id}, effective {effective_time}):
{text}
"""


def main(names):
    os.makedirs(OUT_DIR, exist_ok=True)
    rows = []
    for name in names:
        rx, ing = rxnorm_ingredient(name)
        ing = ing or name
        label = fetch_label(ing)
        if not label:
            print(f"  {name}: no single-ingredient prescription label found; flag for manual review")
            rows.append({"query": name, "ingredient": ing, "rxcui": rx, "status": "NO LABEL FOUND"})
            continue
        rec = label_record(name, rx, ing, label)
        base = os.path.join(OUT_DIR, ing.replace(" ", "_").lower())
        with open(base + ".label.json", "w") as f:
            json.dump(rec, f, indent=2)
        text = "\n\n".join(f"== {title} ==\n{rec['sections'][fld]}" for fld, title in SECTIONS if fld in rec["sections"])
        with open(base + ".extraction_prompt.txt", "w") as f:
            f.write(EXTRACTION_PROMPT.replace("{ingredient}", ing).replace("{set_id}", str(rec["set_id"]))
                    .replace("{effective_time}", str(rec["effective_time"])).replace("{text}", text))
        rows.append({"query": name, "ingredient": ing, "rxcui": rx, "set_id": rec["set_id"],
                     "effective_time": rec["effective_time"], "sections_found": ", ".join(rec["sections"]),
                     "dailymed_url": rec["dailymed_url"], "status": "LABEL SAVED - extraction pending"})
        print(f"  {name}: saved label {rec['set_id']} ({rec['effective_time']})")
        time.sleep(0.3)
    with open(os.path.join(OUT_DIR, "label_index.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["query", "ingredient", "rxcui", "set_id", "effective_time",
                                          "sections_found", "dailymed_url", "status"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in w.fieldnames})
    print(f"Done. Output in {OUT_DIR}/")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1:])
