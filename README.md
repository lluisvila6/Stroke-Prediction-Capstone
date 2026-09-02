# Deformity Consultation Console

A point-of-care tool for adult spinal deformity: it runs prediction models
during the consultation and turns what they say into a document the patient
takes home.

Open **[`app/asd-decision-support.html`](app/asd-decision-support.html)** in any
browser. There is nothing to install and no server. Everything runs in the tab,
and nothing you type leaves the machine.

## What it does

- **Consultation form** — demographics, comorbidity, frailty, bone quality,
  baseline PROMs, radiographic alignment and the planned construct, generated
  from whichever model pack is loaded.
- **Live readout** — every model in the pack re-scored as you type, with a
  completeness meter naming what is still missing.
- **Prediction cards** — each estimate as a percentage *and* as a count out of
  100, an icon array, a comparison against the derivation cohort's base rate,
  the terms driving it as odds ratios against a typical case, extrapolation
  warnings, and the model's discrimination and calibration.
- **What would change it** — two separate sets of levers, what the patient can
  change and what you can change about the operation, each re-scoring every
  model.
- **Patient report** — a printable plain-language document with icon arrays,
  what the estimates cannot tell them, and questions to bring to the next
  appointment.

Three things it deliberately will not do: it does not impute (a model missing an
input produces nothing, never a number resting on a guess), it does not decide,
and it does not vouch for the models it runs.

## Running the ESSG models

The console ships with no clinical models. To run the ESSG adult spinal
deformity risk-benefit models, convert the analysis package into a pack on your
own machine and load it through **Model pack → Replace the pack**:

```
python3 tools/pack_from_essg.py /path/to/ASD_RiskBenefitPackage -o essg-asd-pack.json
python3 tools/validate_pack.py essg-asd-pack.json
```

That gives eleven models — major and neurological complications at 90 days,
reoperation, junctional failure and late fusion failure as annual cumulative
incidence with death as a competing risk, and the MCID, PASS and deterioration
outcomes at two years — each with its 95% interval and its leave-one-centre-out
validation.

Scoring reuses the arithmetic of `predict.js` from that package, which was
checked against R over the derivation cohort. The console reproduces it to the
last bit: 3,300 random cases across all eleven models give a maximum absolute
difference of exactly zero, in both the point estimates and the intervals.

**The generated pack is not in this repository and should not be.** It carries
unpublished fitted coefficients; `.gitignore` keeps `models/essg-*.json` out.

## The model pack format

A pack is one JSON file — variables, coefficients, provenance and the
patient-facing wording.

| File | |
|---|---|
| [`docs/MODEL_PACK_GUIDE.md`](docs/MODEL_PACK_GUIDE.md) | How to turn an R or Python fit into a pack |
| [`models/model-pack.schema.json`](models/model-pack.schema.json) | JSON Schema for the format |
| [`models/TEMPLATE-pack.json`](models/TEMPLATE-pack.json) | Blank skeleton to fill in |
| [`models/demo-asd-pack.json`](models/demo-asd-pack.json) | Worked example exercising every feature |
| [`tools/pack_from_essg.py`](tools/pack_from_essg.py) | Converts an ESSG analysis package into a pack |

Two ways to describe a model. Write it as **readable terms** — logistic, linear
or Cox, with centring, standardisation, log/sqrt/square transforms, categorical
indicators, thresholds, restricted cubic splines, interaction expressions and
external-model recalibration. Or hand over the **design matrix** as fitted:
coefficients, their covariance, and each continuous variable's basis sampled
over a grid, which is what natural splines and Fine-Gray models need in order to
keep their intervals honest.

Validate a pack before it reaches a consultation:

```
python3 tools/validate_pack.py my-pack.json
```

**The pack that ships in the file is a structural demonstration.** Its
coefficients are invented placeholders that exist to exercise the engine. While
it is loaded the app carries a hazard banner and every report is watermarked
SPECIMEN. Load your own pack before showing a number to anyone.

## Repository layout

```
app/asd-decision-support.html   the console — the only file you need to open
models/                          pack schema, template, and the demo pack
docs/MODEL_PACK_GUIDE.md         how to author a pack
tools/pack_from_essg.py          convert an ESSG analysis package into a pack
tools/validate_pack.py           check a pack from the command line
tools/export_pack.py             re-export the built-in pack to models/
tools/make_artifact.py           build the publishable copy
```

`app/asd-decision-support.html` is the source of truth for the built-in pack;
`models/demo-asd-pack.json` is generated from it by `tools/export_pack.py`.

## Notes

- **Offline.** The page makes exactly one network request, for the Google Fonts
  stylesheet, and it carries no case data. Offline the page falls back to system
  typefaces and works identically.
- **Data handling.** Case data lives in the tab and is gone when you close it.
  *Save case* writes a JSON file where you choose; that file contains whatever
  you entered, so treat it as a clinical record.
- **Regulatory status.** Not a medical device. Not assessed by any regulator.
  The models are the pack author's, and so is responsibility for them.
- **Weak models say so.** When a pack reports discrimination below C 0.65, or a
  calibration slope outside 0.7–1.4, the card carries a warning saying the
  estimate should carry little weight. Three of the eleven ESSG models trigger
  it.

## Earlier work in this repository

`healthcare-dataset-stroke-data.csv` and the original README belong to a stroke
prediction capstone for the EdX Data Science course; they are unrelated to the
console and are left in place.
