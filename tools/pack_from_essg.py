#!/usr/bin/env python3
"""Convert the ESSG ASD reproducibility package into a console model pack.

Reads the exported fits (results/tool_models.json), the per-model
specifications and the internal-external cross-validation performance, and
writes a model pack the Deformity Consultation Console can load.

    python3 tools/pack_from_essg.py /path/to/ASD_RiskBenefitPackage -o essg-asd-pack.json

The output contains fitted coefficients, their covariance, baseline hazards and
per-centre validation figures. It contains no patient records. It is still
unpublished research output, so it is written outside the repository by default
and is covered by .gitignore if you put it in models/.
"""
import argparse
import csv
import json
import pathlib
import re
import sys

# ---------------------------------------------------------------- variables --
# Labels, units and grouping for the 18 predictors of the prespecified core set.
VARIABLES = [
    ("edad",          "Age",                         "years",  "demographics", 0),
    ("sexo",          "Sex",                         None,     "demographics", None),
    ("imc",           "Body mass index",             "kg/m²",  "demographics", 1),
    ("fumador",       "Current smoker",              None,     "demographics", None),
    ("asa",           "ASA physical status",         "I–III",  "comorbidity",  0),
    ("charlson",      "Charlson comorbidity index",  None,     "comorbidity",  1),
    ("cir_previa",    "Previous spine surgery",      None,     "comorbidity",  None),
    ("odi_b",         "Oswestry Disability Index",   "0–100",  "proms",        0),
    ("srs_sub_b",     "SRS-22 subtotal",             "1–5",    "proms",        1),
    ("nrs_lumbar",    "Low back pain",               "NRS 0–10", "proms",      0),
    ("cobb_mayor",    "Major curve Cobb angle",      "°",      "radiographic", 0),
    ("ip",            "Pelvic incidence",            "°",      "radiographic", 0),
    ("gt",            "Global tilt",                 "°",      "radiographic", 0),
    ("niveles",       "Posterior levels instrumented", "levels", "plan",       0),
    ("fij_pelvica",   "Pelvic fixation",             None,     "plan",         None),
    ("tco",           "Three-column osteotomy",      None,     "plan",         None),
    ("intersomatica", "Interbody fusion",            None,     "plan",         None),
    ("estadios",      "Staged surgery",              None,     "plan",         None),
]

HELP = {
    "asa": "Entered as a number, as it was modelled: 1, 2 or 3.",
    "charlson": "Derived from the registry comorbidity sheet.",
    "gt": "Global tilt. Chosen over SVA and PT in the analysis plan to limit sagittal collinearity; the sagittal block is GT and PI only.",
    "srs_sub_b": "SRS-22 subtotal before surgery, 1 (worst) to 5 (best).",
    "niveles": "Posterior instrumented levels of the index operation.",
    "cir_previa": "Any previous spinal surgery on the segment being addressed.",
}

# Which levers the console offers on the what-if screen, and the value it moves
# them to. Surgical levers are the ones the index operation can actually vary.
MODIFIABLE = {
    "fumador":       ("patient", False),
    "imc":           ("patient", 26.0),
    "niveles":       ("plan",    8),
    "fij_pelvica":   ("plan",    False),
    "tco":           ("plan",    False),
    "intersomatica": ("plan",    True),
    "estadios":      ("plan",    False),
}

GROUPS = [
    {"id": "identity",     "label": "Case reference",
     "note": "Optional. Stays on this device — it is never transmitted and is not saved unless you save the case yourself."},
    {"id": "demographics", "label": "Demographics"},
    {"id": "comorbidity",  "label": "General condition"},
    {"id": "proms",        "label": "Baseline patient-reported outcomes"},
    {"id": "radiographic", "label": "Preoperative radiographs",
     "note": "Standing full-length films"},
    {"id": "plan",         "label": "Index operation as planned"},
]

# ------------------------------------------------------------------- models --
# label, short label, risk or benefit, timepoint, primary horizon (years, CIF
# models only), and the plain-language wording the patient report uses.
MODELS = {
    "R1": dict(
        label="Major complication within 90 days", short="Major complication",
        kind="risk", timepoint="in the first 90 days",
        patient=dict(
            title="A major complication in the first three months",
            positive="had a complication recorded as major — one that needed extra treatment, a longer stay, or another operation",
            negative="got through the first three months without a major complication",
            explain="Major complications after deformity surgery include infection, a problem with the implants, a blood clot, or a medical problem such as pneumonia. Most are treatable, but they can slow recovery down considerably."),
    ),
    "R5": dict(
        label="Neurological complication within 90 days", short="Neurological complication",
        kind="risk", timepoint="in the first 90 days",
        patient=dict(
            title="A nerve problem in the first three months",
            positive="had a nerve complication recorded — new weakness, numbness or nerve pain",
            negative="did not have a nerve complication",
            explain="Correcting a deformity moves the spinal cord and nerve roots. Most nerve problems that occur are partial and recover over weeks to months, but not all of them do."),
    ),
    "R2": dict(
        label="Unplanned reoperation", short="Reoperation",
        kind="risk", timepoint="within 2 years", horizon=2,
        patient=dict(
            title="Needing another operation",
            positive="needed a further, unplanned operation",
            negative="did not need a further operation",
            explain="Long fusions sometimes need revisiting — for an implant that has loosened, a bone that has not healed, or a problem at the top or bottom of the construct. This is one of the most important numbers to weigh, because a second operation means a second recovery."),
    ),
    "R3": dict(
        label="Junctional failure (PJK or PJF)", short="Junctional failure",
        kind="risk", timepoint="within 2 years", horizon=2,
        patient=dict(
            title="The spine bending forward just above the fusion",
            positive="had this recorded",
            negative="did not have this recorded",
            explain="The joint immediately above a long fusion carries extra load and can tip forward over time. Many patients who show it on an X-ray never notice it. A smaller number develop pain or a change in posture and need a further operation."),
    ),
    "R4": dict(
        label="Late fusion failure (pseudarthrosis or rod fracture)", short="Fusion failure",
        kind="risk", timepoint="within 5 years", horizon=5,
        patient=dict(
            title="The fusion not healing, or a rod breaking",
            positive="had a fusion that did not heal, or a broken rod",
            negative="had neither",
            explain="The fusion has to turn into solid bone. When it does not, the metal carries load it was never meant to carry indefinitely, and a rod can break. This usually shows up in the second year or later, which is why it is read at five years rather than two."),
    ),
    "B1_odi": dict(
        label="Meaningful improvement in disability (ODI ≥ 12.8 points)", short="Meaningful ODI gain",
        kind="benefit", timepoint="by 2 years after surgery",
        patient=dict(
            title="A clear improvement in day-to-day disability",
            positive="improved by an amount they would notice in daily life",
            negative="did not improve by that much — they may have improved a little, stayed the same, or got worse",
            explain="Disability is measured with a questionnaire about everyday activities: walking, sitting, sleeping, dressing, lifting. An improvement of about 13 points on that questionnaire is the size of change patients describe as worthwhile."),
    ),
    "B1_pain": dict(
        label="Meaningful improvement in pain (SRS-22 pain ≥ 0.4)", short="Meaningful pain gain",
        kind="benefit", timepoint="by 2 years after surgery",
        patient=dict(
            title="A clear improvement in pain",
            positive="improved on the pain questions by an amount they would notice",
            negative="did not improve by that much",
            explain="These are the five pain questions of the SRS-22 questionnaire, scored 1 to 5. A gain of 0.4 is the smallest change patients report as meaningful."),
    ),
    "B1_si": dict(
        label="Meaningful improvement in self-image (SRS-22 ≥ 0.4)", short="Meaningful self-image gain",
        kind="benefit", timepoint="by 2 years after surgery",
        patient=dict(
            title="A clear improvement in how you feel about your shape",
            positive="improved on the appearance questions by an amount they would notice",
            negative="did not improve by that much",
            explain="How the back looks, and how a person feels about it, is one of the main reasons patients seek deformity surgery. It is measured separately from pain because the two do not always move together."),
    ),
    "B2_odi": dict(
        label="Acceptable symptom state (ODI ≤ 18)", short="Acceptable state, ODI",
        kind="benefit", timepoint="by 2 years after surgery",
        patient=dict(
            title="Reaching a state you would find acceptable — disability",
            positive="reached a level of disability that patients describe as acceptable to live with",
            negative="did not reach that level",
            explain="This is a different question from improving. A patient can improve a great deal and still be limited; another can start closer to normal and end up comfortable. This figure is about where you finish, not how far you travel."),
    ),
    "B2_srs": dict(
        label="Acceptable symptom state (SRS-22 subtotal > 3.5)", short="Acceptable state, SRS-22",
        kind="benefit", timepoint="by 2 years after surgery",
        patient=dict(
            title="Reaching a state you would find acceptable — overall",
            positive="reached an overall score patients describe as acceptable",
            negative="did not reach that score",
            explain="The SRS-22 subtotal combines pain, function, appearance and mental health into one score from 1 to 5."),
    ),
    "B3": dict(
        label="Deterioration by at least the MCID at 2 years", short="Deterioration",
        kind="risk", timepoint="by 2 years after surgery",
        patient=dict(
            title="Being worse two years after than before",
            positive="were worse at two years than they were before the operation, by an amount they would notice",
            negative="were not worse",
            explain="Surgery does not always help, and a minority of patients end up worse than they started. This is the number that most deserves to be said out loud before a decision."),
    ),
}

# events_summary.csv keys, which do not match the model ids.
EVENT_KEY = {
    "R1": "R1 mayor<=90d", "R5": "R5 neuro<=90d",
    "B1_odi": "B1 MCID ODI", "B1_pain": "B1 MCID pain", "B1_si": "B1 MCID SI",
    "B2_odi": "B2 PASS ODI", "B2_srs": "B2 PASS SRS", "B3": "B3 deterioro",
}

EXAMPLE = {
    "patient_ref": "Example case — not a real patient", "surgeon": "", "consult_date": "",
    "edad": 64, "sexo": "Female", "imc": 27.5, "fumador": False,
    "asa": 2, "charlson": 2, "cir_previa": False,
    "odi_b": 48, "srs_sub_b": 2.6, "nrs_lumbar": 7,
    "cobb_mayor": 46, "ip": 55, "gt": 32,
    "niveles": 11, "fij_pelvica": True, "tco": False,
    "intersomatica": True, "estadios": False,
}


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def num(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def performance_binary(rows):
    """Pooled internal-external cross-validation figures for a binary model."""
    out = {"validation": "internal-external cross-validation, leave-one-centre-out (7 centres)"}
    for r in rows:
        if r["nivel"].startswith("POOL_IECV"):
            out.update(c=num(r.get("c")), cLo=num(r.get("c_lo")), cHi=num(r.get("c_hi")),
                       calibrationSlope=num(r.get("slope")), oe=num(r.get("oe")),
                       brier=num(r.get("brier")), n=int(num(r["n"])), events=int(num(r["eventos"])))
        elif r["nivel"] == "APARENTE":
            out["cApparent"] = num(r.get("c"))
        elif r["nivel"] == "CORREGIDO_OPTIMISMO":
            out["cOptimismCorrected"] = num(r.get("c"))
    out["centres"] = sum(1 for r in rows if r["nivel"].endswith(" Op"))
    return out


def performance_cif(rows, horizon):
    """Pooled time-dependent AUC at the model's primary horizon."""
    out = {"validation": "internal-external cross-validation, leave-one-centre-out (7 centres)"}
    for r in rows:
        if r["nivel"] == "POOL_IECV" and int(num(r["horizonte"])) == horizon:
            out.update(c=num(r.get("auc")), cLo=num(r.get("auc_lo")), cHi=num(r.get("auc_hi")),
                       oe=num(r.get("oe_mediana")), tau2=num(r.get("tau2")))
    out["byHorizon"] = [
        {"year": int(num(r["horizonte"])), "c": num(r.get("auc")),
         "cLo": num(r.get("auc_lo")), "cHi": num(r.get("auc_hi"))}
        for r in rows if r["nivel"] == "POOL_IECV"
    ]
    return out


def spec_counts(text):
    """N analytic and event count, read from the model spec file.

    The Fine-Gray specs write "eventos causa 1: 321", so take the number after
    the colon rather than every digit in the fragment.
    """
    out = {}
    m = re.search(r"N analitico[^:]*:\s*(\d+)", text)
    if m:
        out["n"] = int(m.group(1))
    m = re.search(r"eventos(?:\s+causa\s+\d+)?\s*:\s*(\d+)", text)
    if m:
        out["events"] = int(m.group(1))
    return out


def build(pkg, version):
    tool = json.loads((pkg / "results" / "tool_models.json").read_text(encoding="utf-8"))
    events = {r["outcome"]: (int(num(r["n"])), num(r["denominador"])) for r in read_csv(pkg / "results" / "events_summary.csv")}
    cif_obs = {c["model"]: c for c in tool["context"]["cif_observed"]}

    fits = tool["models"]
    used = {v for m in fits.values() for v in m["vars"]}

    variables = [
        {"id": "patient_ref", "label": "Patient name or reference", "type": "text", "group": "identity",
         "help": "Free text. Appears on the printed report only if you choose to include it."},
        {"id": "surgeon", "label": "Surgeon", "type": "text", "group": "identity"},
        {"id": "consult_date", "label": "Consultation date", "type": "text", "group": "identity",
         "help": "Free text, e.g. 2 September 2026."},
    ]
    for vid, label, unit, group, decimals in VARIABLES:
        if vid not in used:
            continue
        # Take the range and reference value from whichever fit carries the variable.
        spec = next(m["vars"][vid] for m in fits.values() if vid in m["vars"])
        v = {"id": vid, "label": label, "group": group}
        if unit:
            v["unit"] = unit
        if spec["type"] == "continuous":
            lo, hi = round(spec["lo"], 2), round(spec["hi"], 2)
            v.update(type="number", min=lo, max=hi, decimals=decimals,
                     derivationRange=[lo, hi], reference=spec.get("median"))
            if decimals == 1:
                v["step"] = 0.1
        elif spec["type"] == "binary":
            v.update(type="boolean", reference=False)
        else:
            v.update(type="categorical",
                     options=[{"value": k, "label": k} for k in spec["keys"]],
                     reference=spec["keys"][0])
        if vid in HELP:
            v["help"] = HELP[vid]
        if vid in MODIFIABLE:
            v["modifiable"], v["optimized"] = MODIFIABLE[vid]
        variables.append(v)

    models = []
    for mid, meta in MODELS.items():
        fit = fits[mid]
        spec_file = pkg / "results" / ("model_%s_spec.txt" % mid)
        counts = spec_counts(spec_file.read_text(encoding="utf-8")) if spec_file.exists() else {}
        perf_rows = read_csv(pkg / "results" / ("model_%s_performance_iecv.csv" % mid))
        horizon = meta.get("horizon")

        if fit["kind"] == "competing_risks":
            perf = performance_cif(perf_rows, horizon)
            obs = cif_obs.get(mid)
            base = obs["cif"][obs["years"].index(horizon)] if obs else None
            cohort_curve = [{"year": y, "risk": c} for y, c in zip(obs["years"], obs["cif"])] if obs else None
        else:
            perf = performance_binary(perf_rows)
            key = EVENT_KEY.get(mid)
            base = (events[key][0] / events[key][1]) if key in events and events[key][1] else None
            cohort_curve = None
        perf.update({k: v for k, v in counts.items() if v})

        model = {
            "id": mid,
            "label": meta["label"],
            "shortLabel": meta["short"],
            "kind": meta["kind"],
            "engine": "design",
            "timepoint": meta["timepoint"],
            "performance": {k: v for k, v in perf.items() if v is not None},
            "patient": meta["patient"],
            "design": {k: fit[k] for k in
                       ("kind", "cols", "beta", "vcov", "vars", "horizons",
                        "baseline_H0", "var_a", "var_b") if k in fit},
        }
        if base is not None:
            model["baselineRate"] = round(base, 4)
        if horizon:
            model["primaryHorizon"] = horizon
        if cohort_curve:
            model["cohortCurve"] = cohort_curve
        models.append(model)

    return {
        "schemaVersion": "1.1",
        "pack": {
            "id": "essg-asd-riskbenefit",
            "name": "ESSG adult spinal deformity risk-benefit",
            "version": version,
            "population": tool["meta"]["source"],
            "validationStatus": "internally-validated",
            "authors": "European Spine Study Group",
            "institution": "European Spine Study Group registry",
            "citation": "Unpublished. Models fitted per the frozen statistical analysis plan; see 02_SAP.md and SAP.lock.json in the reproducibility package.",
            "lastUpdated": tool["meta"]["generated"],
            "notes": tool["meta"]["disclaimer"] + " " + tool["meta"]["interval_note"],
        },
        "report": {
            "intro": "Your surgeon has used a computer tool to estimate what this operation is likely to do for you. The estimates come from the records of about 2,300 patients across seven European centres who had a similar operation. They describe groups, not individuals — nobody can tell you exactly what will happen to you.",
            "naturalHistory": "This report describes what may happen if you have the operation. It does not describe what happens if you do not. Your surgeon will talk to you separately about how your symptoms are likely to change without surgery, and about non-surgical treatment.",
            "questions": [
                "Which of these numbers matters most in my case, and why?",
                "How wide is the uncertainty on the numbers that matter to me?",
                "What would you expect my recovery to look like in the first three months?",
                "If a complication happened, what would treating it involve?",
                "What happens to me if I decide not to have surgery, or to wait?",
                "Is there anything I should do before surgery to improve these numbers?",
            ],
            "closing": "You do not have to decide today. Take this report home, read it again, and bring your questions to your next appointment.",
        },
        "variableGroups": GROUPS,
        "variables": variables,
        "exampleCase": EXAMPLE,
        "models": models,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("package", help="Root of the reproducibility package (contains results/ and scripts/)")
    ap.add_argument("-o", "--out", default="essg-asd-pack.json")
    ap.add_argument("--version", default="2.0.0")
    args = ap.parse_args()

    pkg = pathlib.Path(args.package)
    if not (pkg / "results" / "tool_models.json").exists():
        sys.exit("No results/tool_models.json under " + str(pkg))

    pack = build(pkg, args.version)
    out = pathlib.Path(args.out)
    out.write_text(json.dumps(pack, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print("wrote %s (%.1f MB, %d variables, %d models)" % (
        out, out.stat().st_size / 1e6, len(pack["variables"]), len(pack["models"])))
    for m in pack["models"]:
        p = m["performance"]
        c = p.get("c")
        print("  %-8s %-10s C %s  slope %s  n %s" % (
            m["id"], m["kind"],
            ("%.3f" % c) if c else "  —  ",
            ("%.2f" % p["calibrationSlope"]) if p.get("calibrationSlope") else " — ",
            p.get("n", "—")))


if __name__ == "__main__":
    main()
