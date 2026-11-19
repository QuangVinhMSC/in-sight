"""Builds insight_studio/data/functions.json from a local In-Sight Vision Suite installation.

Only factual data is extracted: function names, parameter lists and the help page path (so
the app can open the locally installed help). No help prose is copied.

Usage:
    python tools/build_catalog.py ["C:/Program Files/Cognex/In-Sight/In-Sight Vision Suite Editors/In-Sight/In-Sight 26.1.0"]
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

DEFAULT_EDITOR = Path(
    "C:/Program Files/Cognex/In-Sight/In-Sight Vision Suite Editors/In-Sight/In-Sight 26.1.0"
)
OUT = Path(__file__).resolve().parent.parent / "insight_studio" / "data" / "functions.json"

# Templates that are known to produce a valid cell (sample jobs / Web SDK documentation).
TEMPLATES = {
    "AcquireImage": "AcquireImage()",
    "EditInt": "EditInt(0,255)",
    "EditFloat": "EditFloat(0,100)",
    "EditString": "EditString(32)",
    "CheckBox": 'CheckBox("Enable")',
    "ListBox": 'ListBox("Option 1","Option 2")',
    "Count": "Count($A$0,9999999,0,0)",
    "EditRegion": 'EditRegion($A$0,0,0,0,1,1,1,1,"Region",2)',
    "EditCircle": 'EditCircle($A$0,0,0,0,1,1,"Circle",2)',
    "EditAnnulus": 'EditAnnulus($A$0,0,0,0,1,1,"Annulus",2)',
    "EditLine": 'EditLine($A$0,0,0,0,1,1,"Line",2)',
    "EditPoint": 'EditPoint($A$0,0,0,0,1,"Point",2)',
    "Now": "Now($A$0)",
}

_SYNTAX_RE = re.compile(r'<span class="pre">((?:(?!<span class="pre">|</p>).)*?)</span>\s*</p>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def clean(text: str) -> str:
    text = _TAG_RE.sub("", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parse_params(sig: str) -> tuple[str, list[str]] | None:
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*$", sig)
    if not m:
        return None
    name, inner = m.group(1), m.group(2)
    # Glossary pop-ups leak their definition into the syntax text: "Fixture A fixture is ..."
    inner = re.sub(r"Fixture A fixture is[^,()]*", "Fixture", inner)
    inner = re.sub(r"White Balance White balance refers[^,()]*?(?=,|\)|$)", "White Balance", inner)
    params = [p.strip() for p in re.split(r",(?![^()]*\))", inner) if p.strip()]
    return name, params


def main() -> int:
    editor = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_EDITOR
    content = editor / "Docs" / "Help_InSight" / "Content"
    if not content.is_dir():
        print(f"Help not found under {content}", file=sys.stderr)
        return 1
    entries: dict[str, dict] = {}
    for page in sorted((content / "Topics" / "Spreadsheet").rglob("*.htm")):
        text = page.read_text(encoding="utf-8", errors="replace")
        rel = page.relative_to(content.parent).as_posix()
        category = page.parent.name if page.parent.name != "Spreadsheet" else "General"
        found = False
        if "following syntax" in text:
            for raw in _SYNTAX_RE.findall(text):
                parsed = parse_params(clean(raw))
                if not parsed:
                    continue
                name, params = parsed
                found = True
                entries.setdefault(name, {
                    "name": name, "params": params, "category": category, "help": rel,
                })
        if not found:
            m = re.search(r'document\.title = "In-Sight Spreadsheet - ([A-Za-z][A-Za-z0-9_]*) - ', text)
            if m and category == "VisionTools" and m.group(1) == page.stem.replace("-", ""):
                name = m.group(1)
                entries.setdefault(name, {"name": name, "params": None, "category": category,
                                          "help": rel})
    for name, template in TEMPLATES.items():
        entries.setdefault(name, {"name": name, "params": None, "category": "VisionTools"})
        entries[name]["template"] = template
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = {"source": f"In-Sight Vision Suite help ({editor.name})",
           "functions": sorted(entries.values(), key=lambda e: e["name"].lower())}
    OUT.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    with_params = sum(1 for e in entries.values() if e.get("params"))
    print(f"Wrote {len(entries)} functions ({with_params} with parameter lists) to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
