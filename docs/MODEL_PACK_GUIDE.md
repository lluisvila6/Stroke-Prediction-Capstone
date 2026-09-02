# Turning your models into a model pack

The console holds no models. Everything it predicts comes from a single JSON
file — a *model pack* — that declares the variables to collect, the models to
fit them to, and where those models came from. Replace the pack and the whole
console reshapes around it: the consultation form, the readout, the prediction
cards, the what-if levers and the patient report are all generated from it.

Start from `models/TEMPLATE-pack.json`. Check your work with:

```
python3 tools/validate_pack.py my-pack.json
```

The template deliberately fails validation until you fill in `pack.name` — an
unnamed pack should never reach a consultation. Load a finished pack through
**Model pack → Replace the pack**; it is read in the browser and never uploaded.

---

## 1. The shape of a pack

```
schemaVersion   "1.0"
pack            who made it, what population, how well validated
report          the plain-language text of the patient document
variableGroups  the sections of the consultation form, in display order
variables       everything the surgeon types in
derived         values computed from other variables (PI − LL, unit conversions)
mcid            the thresholds your outcome definitions rest on, for the record
models          the models themselves
exampleCase     what loads when the pack opens, so the console is never an empty shell
```

`models/model-pack.schema.json` is the full JSON Schema, and
`models/demo-asd-pack.json` is a worked example that exercises every feature.

---

## 2. Variables

```json
{ "id": "pi", "label": "Pelvic incidence", "type": "number", "unit": "°",
  "group": "radiographic", "min": 20, "max": 95, "decimals": 0,
  "derivationRange": [30, 80] }
```

`id` is what model terms refer to; keep it a plain identifier
(`[A-Za-z_][A-Za-z0-9_]*`). Four types: `number`, `boolean`, `categorical`
(needs `options`) and `text` (never enters a model — use it for the case
reference and the surgeon's name).

Two fields carry more weight than they look:

**`derivationRange`** is the range actually present in the cohort the model was
fitted on — not the range the field physically allows. A case outside it is
flagged amber in the form and every prediction card that uses the variable says
the estimate is an extrapolation. Set it honestly; it is the main defence
against a confident number about a patient the model has never seen.

**`modifiable` / `optimized`** put a variable on the *What would change it*
screen. `"modifiable": "patient"` is for things the patient controls (smoking,
BMI, albumin, opioid use) and appears in the patient report; `"plan"` is for
things you control (construct length, upper instrumented vertebra, osteotomy).
`optimized` is the value the what-if screen moves the variable to.

### Derived variables

```json
{ "id": "pi_ll", "label": "PI − LL mismatch", "unit": "°",
  "group": "radiographic", "expression": "pi - ll", "decimals": 0 }
```

Shown read-only on the form and usable in model terms like any other variable.
If an input it needs is missing, the derived value is missing too and every
model that uses it reports missing data rather than a number.

---

## 3. The expression grammar

Expressions appear in `derived[].expression` and in `terms[].expr`. They are
parsed and walked by the console, never handed to `eval`, so a pack file cannot
execute code. Anything outside this grammar is rejected at load time.

| | |
|---|---|
| Numbers | `0.5`, `28`, `1e3` is **not** supported — write `1000` |
| Variables | any variable or derived id |
| Category indicators | `smoking__current` — the id, two underscores, the option value; 1 when that level is selected, 0 otherwise |
| Booleans | the id itself, 1 or 0 |
| Arithmetic | `+ - * / ^` and parentheses |
| Comparisons | `< <= > >= == !=`, each yielding 1 or 0 |
| Functions | `abs sqrt exp ln log log10 round floor ceil min max` |

```json
{ "expr": "asd_fi * (levels_fused - 8)", "coef": 0.12,
  "label": "Frailty × construct length" }
{ "expr": "(age > 70) * smoking__current", "coef": 0.31,
  "label": "Current smoker over 70" }
```

---

## 4. Terms

Every term is a coefficient multiplied by one transformed value. Give each one a
`label` written for a clinician — it is what appears in the driver chart on the
prediction card, and `pi_ll` reads badly to a patient looking over a shoulder.

| `transform` | Value used | Extra fields |
|---|---|---|
| `identity` | `x` | — |
| `center` | `x − c` | `center` |
| `z` | `(x − μ) / σ` | `mean`, `sd` |
| `log` `log1p` `sqrt` `square` | as named | — |
| `level` | 1 if the category equals `level` | `level` |
| `threshold` | 1 if the comparison holds | `cut`, optional `op` (default `>=`) |
| `rcs` | Harrell restricted cubic spline basis | `knots`, `basis` |

**Categoricals** need one `level` term per non-reference category. The category
you omit is the reference:

```json
{ "var": "smoking", "transform": "level", "level": "current", "coef": 0.35 }
```

**Splines.** A restricted cubic spline with *k* knots contributes a linear term
plus *k − 2* basis terms. Encode the linear part as `identity` or `center`, then
one `rcs` term per basis, numbered from 1:

```json
{ "var": "bmi", "transform": "center", "center": 28, "coef": 0.020 },
{ "var": "bmi", "transform": "rcs", "knots": [22, 28, 36], "basis": 1, "coef": 0.012 }
```

The basis follows Harrell's parameterisation — the same one `rms::rcs()` and
`Hmisc::rcspline.eval()` produce — so coefficients from an `rms` fit transfer
directly as long as you carry the knot locations across with them.

---

## 5. The three model types

### Logistic — a yes/no outcome

```json
{ "type": "logistic", "intercept": -2.60, "terms": [...] }
```
`p = 1 / (1 + exp(−lp))`, where `lp = intercept + Σ coef × term`.

### Linear — a score

```json
{ "type": "linear", "intercept": 4.0, "sigma": 12.5,
  "unit": "ODI points", "lowerIsBetter": true,
  "thresholds": [{ "label": "ODI 20 or below", "op": "<=", "value": 20 }] }
```
`sigma` is the residual standard deviation. It buys the prediction interval and
the "chance of reaching" figures, which are computed from the normal
distribution — without it the card shows a bare point estimate, which is worse
than useless for a patient. `thresholds` should name levels that mean something
clinically, not round numbers.

### Cox — time to an event

```json
{ "type": "cox", "horizonMonths": 24, "lpMean": 0.45,
  "baselineSurvival": [{ "t": 12, "s0": 0.90 }, { "t": 24, "s0": 0.82 }] }
```
`risk = 1 − S₀(t) ^ exp(lp − lpMean)`. There is no `intercept` — the baseline
hazard lives in `baselineSurvival`. `lpMean` is the mean linear predictor in the
derivation cohort, which `S₀` is centred on; get it wrong and every risk is
shifted. If you fitted with `survival::coxph`, `lpMean` is
`mean(predict(fit, type = "lp"))` over the derivation data.

### Recalibration

To run someone else's published model on your population, keep their
coefficients and add:

```json
"recalibration": { "intercept": -0.32, "slope": 0.88 }
```
applied as `lp' = a + b·lp` before the link. This is the honest way to import an
external model: the update is visible in the file rather than baked into the
coefficients.

---

## 6. Exporting from R

```r
library(jsonlite)

logistic_model <- function(fit, id, label, kind, timepoint, baseline_rate, labels = list()) {
  co <- coef(fit)
  terms <- lapply(setdiff(names(co), "(Intercept)"), function(nm) {
    list(var = nm, transform = "identity", coef = unname(co[nm]),
         label = if (!is.null(labels[[nm]])) labels[[nm]] else nm)
  })
  list(id = id, label = label, shortLabel = label, kind = kind, type = "logistic",
       timepoint = timepoint, baselineRate = baseline_rate,
       intercept = unname(co["(Intercept)"]), terms = terms,
       performance = list(
         auc = as.numeric(pROC::auc(pROC::roc(fit$y, fitted(fit)))),
         n = length(fit$y), events = sum(fit$y), validation = "apparent"))
}
```

Two things this simple version does not do, and that you must do by hand:

- **Factors.** `glm` names a dummy `smokingcurrent`. That has to become
  `{"var": "smoking", "transform": "level", "level": "current"}`.
- **Splines and interactions.** `rcs(bmi, 3)` produces `bmi` and `bmi'`; the
  first is the linear term, the second is `basis: 1`, and you must carry the
  knots over from `attr(rcs(bmi, 3), "parms")`.

For a Cox fit:

```r
fit  <- coxph(Surv(months, reop) ~ ., data = df)
sf   <- survfit(fit, newdata = data.frame(t(colMeans(model.matrix(fit)[, -1, drop = FALSE]))))
s0   <- approx(sf$time, sf$surv, xout = c(6, 12, 24))$y
lp_mean <- mean(predict(fit, type = "lp"))
```

## 7. Exporting from Python

```python
import json
import numpy as np
from sklearn.metrics import roc_auc_score

def logistic_model(fit, X, y, *, id, label, kind, timepoint, labels=None):
    labels = labels or {}
    return {
        "id": id, "label": label, "shortLabel": label, "kind": kind,
        "type": "logistic", "timepoint": timepoint,
        "baselineRate": float(np.mean(y)),
        "intercept": float(fit.intercept_[0]),
        "terms": [
            {"var": c, "transform": "identity", "coef": float(b),
             "label": labels.get(c, c)}
            for c, b in zip(X.columns, fit.coef_[0])
        ],
        "performance": {
            "auc": float(roc_auc_score(y, fit.predict_proba(X)[:, 1])),
            "n": int(len(y)), "events": int(y.sum()), "validation": "apparent",
        },
    }
```

A regularised `sklearn` fit is not calibrated by default. Either fit without
penalty, or calibrate and record the result — `calibrationSlope` and
`calibrationIntercept` are printed under every estimate on the card, and a
slope far from 1 is the fastest way for a reader to see that a number should
not be trusted.

---

## 8. Writing the patient text

Each model carries a `patient` block, and it is the part of the pack that
reaches the person making the decision:

```json
"patient": {
  "title": "A serious complication in the first three months",
  "positive": "will have a serious complication — something that needs extra treatment, a longer stay, or another operation",
  "negative": "will get through the first three months without a serious complication",
  "explain": "Serious complications after deformity surgery include infection, a problem with the implants, a blood clot, or a medical problem such as pneumonia. Most are treatable, but they can slow recovery down considerably."
}
```

`positive` completes *"About 23 in 100 patients with this profile …"* and
`negative` completes *"The other 77 …"*. Both are stated, always. Write them as
you would say them out loud: no odds, no relative risks, no percentages inside
the sentence, and no adjective that does the patient's judging for them — "23 in
100" is information, "a low risk" is your opinion wearing a number's clothes.

---

## 9. Before a pack is used with a patient

`validationStatus` is the one field the console enforces. Anything other than
`validated`, `externally-validated` or `internally-validated` puts a hazard
banner across the app and a SPECIMEN watermark on every report. Set it to what
is true, and treat this list as the bar for claiming any of the three:

- [ ] Coefficients transcribed from the fit, not retyped, and spot-checked
      against the source model on at least three cases.
- [ ] `derivationRange` on every continuous variable reflects the real cohort.
- [ ] Discrimination and calibration recorded per model, with `validation`
      saying how they were obtained. Apparent performance is not validation.
- [ ] `lpMean` and `baselineSurvival` checked for every Cox model — an error
      here shifts every patient's risk and produces no warning.
- [ ] `patient` text read aloud to someone outside medicine.
- [ ] `population` describes who the models apply to, precisely enough that a
      reader can tell when a patient falls outside it.
- [ ] Local governance sign-off obtained. The console is not a medical device
      and has not been assessed by any regulator; the models are yours, and so
      is the responsibility for them.
