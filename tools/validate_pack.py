#!/usr/bin/env python3
"""Check a model pack before loading it into the console.

Mirrors the checks the console runs at load time, so a pack can be validated in
CI or from a terminal instead of by trying it in front of a patient.

    python3 tools/validate_pack.py models/demo-asd-pack.json

Exit status is 1 if any error is found. Warnings do not fail the run.
"""
import json
import pathlib
import re
import sys

TRANSFORMS = {"identity", "center", "z", "log", "log1p", "sqrt", "square", "level", "threshold", "rcs"}
STATUSES = {"validated", "externally-validated", "internally-validated", "demonstration"}
TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+\.?\d*|<=|>=|==|!=|[-+*/^(),<>]|\s+")
FUNCS = {"abs", "sqrt", "exp", "ln", "log", "log10", "round", "floor", "ceil", "min", "max"}


def expression_identifiers(expr):
    """Identifiers referenced by an expression, and any character the grammar rejects."""
    pos, idents, bad = 0, set(), []
    while pos < len(expr):
        m = TOKEN.match(expr, pos)
        if not m:
            bad.append(expr[pos])
            pos += 1
            continue
        tok = m.group(0)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", tok) and tok not in FUNCS:
            idents.add(tok)
        pos = m.end()
    return idents, bad


def check(pack):
    errors, warnings = [], []
    err, warn = errors.append, warnings.append

    if pack.get("schemaVersion") != "1.0":
        warn('schemaVersion is %r; the console was built for "1.0".' % pack.get("schemaVersion"))
    meta = pack.get("pack") or {}
    if not meta.get("name"):
        err("pack.name is required.")
    if meta.get("validationStatus") not in STATUSES:
        err("pack.validationStatus must be one of: %s." % ", ".join(sorted(STATUSES)))
    if meta.get("validationStatus") == "demonstration":
        warn("This pack is marked demonstration: the console will watermark every report SPECIMEN.")
    if not meta.get("version"):
        warn("pack.version is empty; it is printed on every patient report.")

    variables = pack.get("variables") or []
    models = pack.get("models") or []
    if not variables:
        err("variables must be a non-empty array.")
    if not models:
        err("models must be a non-empty array.")
    if errors:
        return errors, warnings

    ids, levels = set(), {}
    for v in variables:
        vid = v.get("id")
        if not vid or not v.get("label"):
            err("Every variable needs an id and a label.")
            continue
        if vid in ids:
            err('Duplicate variable id "%s".' % vid)
        ids.add(vid)
        if v.get("type") not in {"number", "boolean", "categorical", "text"}:
            err('Variable "%s" has unknown type %r.' % (vid, v.get("type")))
        if v.get("type") == "categorical":
            opts = v.get("options") or []
            if not opts:
                err('Categorical variable "%s" has no options.' % vid)
            levels[vid] = {str(o.get("value")) for o in opts}
        rng = v.get("derivationRange")
        if rng and len(rng) == 2 and rng[0] >= rng[1]:
            err('derivationRange on "%s" is not increasing.' % vid)
        if v.get("modifiable") and v.get("optimized") is None:
            warn('Variable "%s" is marked modifiable but has no optimized value, so it never appears on the what-if screen.' % vid)

    for d in pack.get("derived") or []:
        did = d.get("id")
        if not did or not d.get("expression"):
            err("Every derived variable needs an id and an expression.")
            continue
        if did in ids:
            err('Derived id "%s" collides with a variable id.' % did)
        ids.add(did)
        refs, bad = expression_identifiers(d["expression"])
        for c in bad:
            err('Derived "%s" contains a character the expression grammar rejects: %r.' % (did, c))
        for r in refs:
            if r not in ids:
                err('Derived "%s" refers to unknown "%s".' % (did, r))

    seen_models = set()
    for m in models:
        mid = m.get("id")
        if not mid or not m.get("label"):
            err("Every model needs an id and a label.")
            continue
        if mid in seen_models:
            err('Duplicate model id "%s".' % mid)
        seen_models.add(mid)
        if m.get("type") not in {"logistic", "linear", "cox"}:
            err('Model "%s" has unsupported type %r.' % (mid, m.get("type")))
        if m.get("kind") not in {"risk", "benefit"}:
            err('Model "%s" must declare kind "risk" or "benefit".' % mid)
        if m.get("type") == "cox" and not (m.get("baselineSurvival") or []):
            err('Cox model "%s" needs baselineSurvival.' % mid)
        if m.get("type") == "cox":
            ts = [b["t"] for b in m.get("baselineSurvival") or []]
            s0 = [b["s0"] for b in m.get("baselineSurvival") or []]
            if ts != sorted(ts):
                err('baselineSurvival in "%s" is not in increasing time order.' % mid)
            if any(not 0 <= x <= 1 for x in s0):
                err('baselineSurvival s0 values in "%s" must be between 0 and 1.' % mid)
        if m.get("type") == "linear" and not m.get("sigma"):
            warn('Linear model "%s" has no sigma, so no interval or threshold probability can be shown.' % mid)
        if m.get("kind") == "risk" and m.get("type") != "linear" and not isinstance(m.get("baselineRate"), (int, float)):
            warn('Model "%s" has no baselineRate, so no cohort comparison can be drawn.' % mid)
        if not (m.get("performance") or {}).get("validation"):
            warn('Model "%s" does not say how it was validated.' % mid)
        if not (m.get("patient") or {}).get("title"):
            warn('Model "%s" has no patient wording, so it will read as the technical label on the report.' % mid)

        terms = m.get("terms") or []
        if not terms:
            err('Model "%s" has no terms.' % mid)
        for t in terms:
            if not isinstance(t.get("coef"), (int, float)):
                err('A term in "%s" has no numeric coef.' % mid)
            if t.get("expr"):
                refs, bad = expression_identifiers(t["expr"])
                for c in bad:
                    err('Model "%s" expression contains a rejected character: %r.' % (mid, c))
                for r in refs:
                    base = r if r in ids else re.sub(r"__[A-Za-z0-9_]+$", "", r)
                    if base not in ids:
                        err('Model "%s" refers to unknown "%s".' % (mid, r))
            elif t.get("var"):
                if t["var"] not in ids:
                    err('Model "%s" refers to unknown variable "%s".' % (mid, t["var"]))
                tr = t.get("transform", "identity")
                if tr not in TRANSFORMS:
                    err('Model "%s" uses unknown transform "%s".' % (mid, tr))
                if tr == "level":
                    if t.get("level") is None:
                        err('A level term in "%s" has no level.' % mid)
                    elif t["var"] in levels and str(t["level"]) not in levels[t["var"]]:
                        err('Model "%s" tests %s == "%s", which is not one of its options.' % (mid, t["var"], t["level"]))
                if tr == "rcs":
                    knots = t.get("knots") or []
                    if len(knots) < 3:
                        err('An rcs term in "%s" needs at least 3 knots.' % mid)
                    elif knots != sorted(knots):
                        err('rcs knots in "%s" must be in increasing order.' % mid)
                    elif not 1 <= t.get("basis", 1) <= len(knots) - 2:
                        err('rcs basis in "%s" must be between 1 and %d.' % (mid, len(knots) - 2))
                if tr == "center" and "center" not in t:
                    err('A center term in "%s" has no center value.' % mid)
                if tr == "z" and ("mean" not in t or "sd" not in t):
                    err('A z term in "%s" needs mean and sd.' % mid)
                if tr == "threshold" and "cut" not in t:
                    err('A threshold term in "%s" has no cut.' % mid)
            else:
                err('A term in "%s" has neither var nor expr.' % mid)

    for key in pack.get("exampleCase") or {}:
        if key not in ids:
            warn('exampleCase sets "%s", which is not a variable in this pack.' % key)

    return errors, warnings


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = pathlib.Path(sys.argv[1])
    try:
        pack = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit("%s is not valid JSON: %s" % (path, e))

    errors, warnings = check(pack)
    for w in warnings:
        print("warning: %s" % w)
    for e in errors:
        print("error:   %s" % e)
    meta = pack.get("pack") or {}
    print("\n%s v%s — %d variables, %d derived, %d models" % (
        meta.get("name", "?"), meta.get("version", "?"),
        len(pack.get("variables") or []), len(pack.get("derived") or []), len(pack.get("models") or [])))
    print("%d error(s), %d warning(s)" % (len(errors), len(warnings)))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
