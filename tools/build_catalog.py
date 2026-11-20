"""Builds insight_studio/data/functions.json from a local In-Sight Vision Suite installation.

Only factual data is extracted: function names, parameter lists, the toolbox category tree, the
names of the Vision Data Access functions a tool inserts (its getters) and the help page path
of every function and category (so the app can read the locally installed help: descriptions
are never copied into the catalog).

The category tree is the help's own table of contents below "In-Sight Toolbox", renamed the way
the ISVS Insert Function dialog and Functions panel show it (``Edge AI Tools`` -> ``Edge AI``,
``InspectEdge Functions`` -> ``InspectEdge``). A TOC entry is a function when its page documents
a function of that name, a category when it holds functions (its own table of functions, such
as Math, or function pages below it), and is skipped otherwise (how-to pages, examples).

Usage:
    python tools/build_catalog.py ["C:/Program Files/Cognex/In-Sight/In-Sight Vision Suite Editors/In-Sight/In-Sight 26.1.0"]
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from insight_studio.catalog import editor_versions  # noqa: E402
from insight_studio.helpdoc import function_tables, parse_html, parse_inputs  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isvs_sheets  # noqa: E402

DEFAULT_EDITOR = Path(
    "C:/Program Files/Cognex/In-Sight/In-Sight Vision Suite Editors/In-Sight/In-Sight 26.1.0"
)
OUT = Path(__file__).resolve().parent.parent / "insight_studio" / "data" / "functions.json"
TOC = "Data/Tocs/is_usp_sheet"

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
    # what ISVS 26.1 writes (survey 2026-11-20): empty Name, Show = 0; EditMaskedRegion needs Theta
    # although its help syntax omits it
    "EditPolygon": isvs_sheets.ISVS_DEFAULTS["EditPolygon"],
    "EditCompositeRegion": isvs_sheets.ISVS_DEFAULTS["EditCompositeRegion"],
    "EditMaskedRegion": isvs_sheets.ISVS_DEFAULTS["EditMaskedRegion"],
    "EditPolylinePath": isvs_sheets.ISVS_DEFAULTS["EditPolylinePath"],
    "Button": isvs_sheets.ISVS_DEFAULTS["Button"],
    "Now": "Now($A$0)",
}

# Top-level toolbox categories as ISVS names them (help TOC title -> ISVS name).
TOP_NAMES = {
    "Edge AI Tools": "Edge AI",
    "Geometry Functions": "Geometry",
    "Graphics Functions": "Graphics",
    "Mathematics Functions": "Mathematics",
    "Text Functions": "Text",
    "Coordinate Transforms Functions": "Coordinate Transforms",
    "Input/Output Functions": "Input/Output",
    "Clocked Data Storage Functions": "Clocked Data Storage",
    "Vision Data Access Functions": "Vision Data Access",
    "White Balance Functions": "White Balance",
    "Structures Functions": "Structures",
    "Focus Functions": "Focus",
}
# Categories ISVS 26.1 did not list for the IS8902CX (they depend on the vision system model):
# they are kept in the catalog (completion, property sheets) but not shown in the toolbox tree.
DEVICE_SPECIFIC = {"Advanced AI", "Focus"}

# Parameters that are greyed out in the property sheet unless another parameter has one of the
# given values (from the "Note: ... to enable this parameter" sentences of the help; the
# controlling parameter's choices are given by label and resolved to values below). Rules read
# in ISVS itself (with the device's choice values) are in isvs_sheets.ENABLE and win.
ENABLE_RULES: dict[str, dict[str, tuple[str, list[str]]]] = {
    "ValidateIDData": {"DoD UID Construct": ("Validation Options", ["DoD UID"])},
}


_SYNTAX_RE = re.compile(r'<span class="pre">((?:(?!<span class="pre">|</p>).)*?)</span>\s*</p>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r'document\.title = "In-Sight Spreadsheet - ([A-Za-z][A-Za-z0-9_]*) - ')
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


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


# ---------------------------------------------------------------------------- help TOC
def _js_object(text: str):
    """Parses the JavaScript object literal inside ``define(...)`` of a MadCap TOC file."""
    body = text[text.index("(") + 1:text.rindex(")")]
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "'":
            j, s = i + 1, []
            while body[j] != "'":
                if body[j] == "\\":
                    s.append(body[j + 1])
                    j += 2
                    continue
                s.append(body[j])
                j += 1
            out.append(json.dumps("".join(s)))
            i = j + 1
            continue
        m = _IDENT.match(body, i)
        if m and body[m.end():m.end() + 1] == ":" and (not out or out[-1][-1:] in "{,"):
            out.append(json.dumps(m.group(0)) + ":")
            i = m.end() + 1
            continue
        out.append(ch)
        i += 1
    return json.loads("".join(out))


def read_toc(help_dir: Path) -> tuple[dict, dict[int, tuple[str, str]]]:
    head = _js_object((help_dir / f"{TOC}.js").read_text(encoding="utf-8"))
    entries: dict[int, tuple[str, str]] = {}
    for k in range(head["numchunks"]):
        chunk = _js_object((help_dir / f"{TOC}_Chunk{k}.js").read_text(encoding="utf-8"))
        for url, v in chunk.items():
            for idx, title in zip(v["i"], v["t"]):
                entries[idx] = (title, url.lstrip("/"))
    return head["tree"], entries


def _find(node: dict, entries, pred) -> Optional[dict]:
    for c in node.get("n", []):
        if pred(*entries.get(c["i"], ("", ""))):
            return c
        found = _find(c, entries, pred)
        if found:
            return found
    return None


def category_name(title: str, top: bool) -> str:
    if top:
        return TOP_NAMES.get(title, title)
    for suffix in (" Vision Data Access functions", " Vision Data Access Functions", " Functions"):
        if title.endswith(suffix):
            return title[: -len(suffix)]
    return title


# ---------------------------------------------------------------------------- pages
class Page:
    def __init__(self, help_dir: Path, rel: str) -> None:
        self.rel = rel
        self.text = (help_dir / rel).read_text(encoding="utf-8", errors="replace")
        self._root = None

    @property
    def root(self):
        if self._root is None:
            self._root = parse_html(self.text)
        return self._root

    def signatures(self) -> list[tuple[str, list[str]]]:
        if "following syntax" not in self.text:
            return []
        return [p for p in (parse_params(clean(raw)) for raw in _SYNTAX_RE.findall(self.text)) if p]

    def title_function(self) -> Optional[str]:
        m = _TITLE_RE.search(self.text)
        return m.group(1) if m else None

    def tables(self) -> list[tuple[str, Optional[list[str]]]]:
        """Functions listed in "Function | Description" tables: (name, params or None)."""
        out = []
        for name, args in function_tables(self.root):
            params = None
            if args is not None:
                parsed = parse_params(f"{name}({args})")
                params = parsed[1] if parsed else []
            out.append((name, params))
        return out


def stem_key(rel: str) -> str:
    return Path(rel).stem.replace("-", "").replace("_", "").lower()


class Builder:
    def __init__(self, help_dir: Path) -> None:
        self.help_dir = help_dir
        self.pages: dict[str, Page] = {}
        self.functions: dict[str, dict] = {}

    def page(self, rel: str) -> Optional[Page]:
        if rel not in self.pages:
            path = self.help_dir / rel
            if not path.is_file():
                return None
            self.pages[rel] = Page(self.help_dir, rel)
        return self.pages[rel]

    def entry(self, name: str, params, rel: str) -> dict:
        e = self.functions.get(name.lower())
        if e is None:
            e = self.functions[name.lower()] = {"name": name, "params": params, "help": rel}
        elif e.get("params") is None and params is not None:
            e["params"] = params
        return e

    def add_function_page(self, name: str, page: Page) -> dict:
        sigs = dict((n.lower(), p) for n, p in page.signatures())
        e = self.entry(name, sigs.get(name.lower()), page.rel)
        if stem_key(page.rel) == name.lower() or e["help"] == page.rel:
            e["help"] = page.rel
            if "inputs" not in e:
                inputs = parse_inputs(page.text, keep_description=False)  # structure only
                if inputs:
                    e["inputs"] = inputs
        getters = [n for n, _ in page.tables()]
        if getters:
            e["getters"] = list(dict.fromkeys(getters))
        return e

    def function_name(self, node: dict, entries) -> Optional[str]:
        """The function a TOC entry documents, if it is a function page."""
        title, rel = entries.get(node["i"], ("", ""))
        page = self.page(rel)
        title = title.strip()
        if page is None or not _IDENT.fullmatch(title):
            return None
        names = {n.lower(): n for n, _ in page.signatures()}
        if title.lower() in names:
            return names[title.lower()]
        # Tool pages without a syntax line (TrainPatMaxRedLine, OCRMax, EdgeAI…): the page title
        # names the function. Category pages look the same but have function pages below them
        # (Vision Tools > Image) or a table of functions (Math, Logic); a tool page's table
        # only lists the getters it inserts (EdgeAIClassify).
        tf = page.title_function()
        if tf and tf.lower() == title.lower() and stem_key(rel) == title.lower() \
                and all(n.startswith("Get") for n, _ in page.tables()) \
                and not self.functions_below(node, entries):
            return tf
        return None

    def functions_below(self, node: dict, entries) -> bool:
        return any(self.function_name(c, entries) or self.functions_below(c, entries) for c in node.get("n", []))

    def walk(self, node: dict, entries, path: list[str]) -> list[dict]:
        """Categories below ``node``; records each function with its category ``path``."""
        cats: list[dict] = []
        for c in node.get("n", []):
            title, rel = entries.get(c["i"], ("", ""))
            page = self.page(rel)
            fn = self.function_name(c, entries)
            if fn and path:
                e = self.add_function_page(fn, page)
                if path not in e.setdefault("paths", []):
                    e["paths"].append(list(path))
                continue
            name = category_name(title, top=not path)
            sub_path = path + [name]
            listed = page.tables() if page else []
            for fname, params in listed:
                e = self.entry(fname, params, rel)
                if sub_path not in e.setdefault("paths", []):
                    e["paths"].append(list(sub_path))
            children = self.walk(c, entries, sub_path)
            has_functions = bool(listed) or any(
                sub_path == p[: len(sub_path)] for e in self.functions.values() for p in e.get("paths", []))
            if has_functions:
                cat = {"name": name, "help": rel}
                if children:
                    cat["children"] = children
                if not path and name in DEVICE_SPECIFIC:
                    cat["hidden"] = True
                cats.append(cat)
        return cats

    def scan_remaining(self, content: Path) -> None:
        """Function pages that are not in the toolbox TOC (older or device-specific functions)."""
        for path in sorted((content / "Topics" / "Spreadsheet").rglob("*.htm")):
            rel = path.relative_to(self.help_dir).as_posix()
            page = self.page(rel)
            for name, params in page.signatures():
                if name.lower() not in self.functions:
                    e = self.entry(name, params, rel)
                    if stem_key(rel) == name.lower():
                        inputs = parse_inputs(page.text, keep_description=False)
                        if inputs:
                            e["inputs"] = inputs
            tf = page.title_function()
            if (tf and stem_key(rel) == tf.lower() and tf.lower() not in self.functions
                    and parse_inputs(page.text, keep_description=False)):
                self.add_function_page(tf, page)

    def apply_sheets(self) -> None:
        """Parameter lists read in ISVS replace or correct the parsed ones (isvs_sheets)."""
        for fname, params in isvs_sheets.SHEETS.items():
            e = self.functions.get(fname.lower())
            if e is None:
                print(f"warning: ISVS sheet for unknown function {fname}", file=sys.stderr)
                continue
            parsed = {p["name"].lower(): p for p in e.get("inputs") or []}
            out = []
            for p in params:
                if "keep" in p:  # the parsed parameter of that name
                    name = p["keep"]
                    p = parsed.get(name.lower())
                    if p is None:
                        raise SystemExit(f"{fname}: no parsed parameter {name}")
                out.append(p)
            e["inputs"] = out
        for fname, patches in isvs_sheets.PATCHES.items():
            e = self.functions.get(fname.lower())
            if not e or not e.get("inputs"):
                print(f"warning: ISVS patches for {fname}: no parameter list", file=sys.stderr)
                continue
            for addr, fields in patches.items():
                target = None
                parts = addr.split("/")
                level = e["inputs"]
                for part in parts:
                    target = next((p for p in level if p["name"].lower() == part.lower()), None)
                    if target is None:
                        break
                    level = target.get("children") or []
                if target is None:
                    print(f"warning: ISVS patch {fname}.{addr}: parameter not found", file=sys.stderr)
                    continue
                if "name" in fields and "kind" in fields:  # a whole parameter
                    target.clear()
                target.update(fields)
        for fname, rules in isvs_sheets.ENABLE.items():
            e = self.functions.get(fname.lower())
            names = {p["name"].lower() for p in _leaves(e.get("inputs") or [])} if e else set()
            for target, rule in rules.items():
                for param in [target] + list(_rule_params(rule)):
                    if param.lower() not in names:
                        print(f"warning: ISVS enable rule {fname}.{target}: no parameter {param}", file=sys.stderr)
            if e:
                e["enable"] = rules

    def apply_enable_rules(self) -> None:
        for fname, rules in ENABLE_RULES.items():
            e = self.functions.get(fname.lower())
            if not e or not e.get("inputs"):
                print(f"warning: enable rules for {fname}: no parameter list", file=sys.stderr)
                continue
            params = {p["name"].lower(): p for p in _leaves(e["inputs"])}
            out = {}
            for target, (control, labels) in rules.items():
                ctrl = params.get(control.lower())
                if target.lower() not in params or not ctrl or not ctrl.get("options"):
                    print(f"warning: enable rule {fname}.{target} <- {control}: parameter not found",
                          file=sys.stderr)
                    continue
                values = [o["value"] for o in ctrl["options"]
                          if any(lab.lower() == o["label"].lower() for lab in labels)]
                if len(values) != len(labels):
                    print(f"warning: enable rule {fname}.{target}: choices {labels} not all in "
                          f"{[o['label'] for o in ctrl['options']]}", file=sys.stderr)
                if values:
                    out[params[target.lower()]["name"]] = {"param": ctrl["name"], "values": values}
            if out:
                e["enable"] = out


def _rule_params(rule: dict):
    if "param" in rule:
        yield rule["param"]
    for sub in rule.get("all", []) + rule.get("any", []):
        yield from _rule_params(sub)


def _leaves(params: list[dict]):
    for p in params:
        if p.get("children"):
            yield from _leaves(p["children"])
        yield p


def main() -> int:
    if len(sys.argv) > 1:
        editor = Path(sys.argv[1])
    else:
        installed = editor_versions()  # Windows install, or ISVS under Wine on Linux
        editor = installed[0] if installed else DEFAULT_EDITOR
    help_dir = editor / "Docs" / "Help_InSight"
    content = help_dir / "Content"
    if not content.is_dir():
        print(f"Help not found under {content}", file=sys.stderr)
        return 1
    tree, entries = read_toc(help_dir)
    toolbox = _find(tree, entries, lambda title, url: url.endswith("/insighttoolbox.htm"))
    if toolbox is None:
        print("The help TOC has no In-Sight Toolbox entry", file=sys.stderr)
        return 1
    b = Builder(help_dir)
    categories = b.walk(toolbox, entries, [])
    b.scan_remaining(content)
    b.apply_enable_rules()
    b.apply_sheets()
    for name, template in TEMPLATES.items():
        e = b.functions.get(name.lower()) or b.entry(name, None, "")
        e["template"] = template
    functions = sorted(b.functions.values(), key=lambda e: e["name"].lower())
    for e in functions:
        if not e.get("help"):
            e.pop("help", None)
    doc = {"source": f"In-Sight Vision Suite help ({editor.name})", "toolbox_help": entries[toolbox["i"]][1],
           "categories": categories, "functions": functions}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    in_tree = sum(1 for e in functions if e.get("paths"))
    with_inputs = sum(1 for e in functions if e.get("inputs"))
    print(f"Wrote {len(functions)} functions ({in_tree} in the toolbox tree, {with_inputs} with property "
          f"sheets, {sum(1 for e in functions if e.get('getters'))} with getters) to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
