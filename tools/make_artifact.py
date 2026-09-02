#!/usr/bin/env python3
"""Strip the document wrapper so the console can be published as an Artifact.

Artifacts are wrapped in their own <!doctype>/<head>/<body> at publish time, so
the published copy must contain page content only. The file written here is a
build output for publishing; app/asd-decision-support.html stays the file you
open from disk.

    python3 tools/make_artifact.py [output_path]
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app" / "asd-decision-support.html"
out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "artifact.html"

html = APP.read_text(encoding="utf-8")
head = re.search(r"<head>(.*?)</head>", html, re.S).group(1)
body = re.search(r"<body>(.*?)</body>", html, re.S).group(1)

# Keep the title, the font link and the styles; drop charset/viewport, which the
# Artifact wrapper supplies itself.
keep = "".join(
    m.group(0)
    for m in re.finditer(r"<title>.*?</title>|<link[^>]*>|<style>.*?</style>", head, re.S)
    if "preconnect" not in m.group(0)
)

out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(keep + "\n" + body + "\n", encoding="utf-8")
print("wrote %s (%d KB)" % (out, len(out.read_bytes()) // 1024))
