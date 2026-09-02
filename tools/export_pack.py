#!/usr/bin/env python3
"""Extract the model pack embedded in the console and write it to models/.

The console is the single source of truth for the built-in demonstration pack;
this keeps the standalone copy in models/ identical to it. Run after editing
the <script id="builtinPack"> block.

    python3 tools/export_pack.py
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app" / "asd-decision-support.html"
OUT = ROOT / "models" / "demo-asd-pack.json"

html = APP.read_text(encoding="utf-8")
match = re.search(r'<script type="application/json" id="builtinPack">(.*?)</script>', html, re.S)
if not match:
    sys.exit("No builtinPack block found in " + str(APP))

pack = json.loads(match.group(1))
OUT.write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("wrote %s (%d variables, %d models)" % (OUT.relative_to(ROOT), len(pack["variables"]), len(pack["models"])))
