"""Reads the parameter tree of a spreadsheet function from its In-Sight help page.

The Inputs table of a function's help page lists its parameters in argument order. A row's
nested table holds either sub-parameters (``X (default = 0)``: the parameter is a group of
arguments, such as Fixture or Region) or enumerated values (``1 = ON (default)``).

Used by ``tools/build_catalog.py`` (structure only: names, defaults, ranges, choices) and at
run time by the property sheet, which shows each parameter's description from the help that
is installed on this computer.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional, Union

_VOID = {"br", "img", "meta", "link", "input", "col", "hr", "wbr", "source", "area"}
_SKIP_CLASSES = ("popupBody", "MCTextPopupArrow")


class _Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict, parent: Optional["_Node"]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: list[Union["_Node", str]] = []
        self.parent = parent

    def skipped(self) -> bool:
        cls = self.attrs.get("class") or ""
        return self.tag in ("script", "style") or any(c in cls for c in _SKIP_CLASSES)

    def text(self, skip_tables: bool = False) -> str:
        out: list[str] = []
        self._collect(out, skip_tables, top=True)
        return re.sub(r"\s+", " ", "".join(out)).strip()

    def _collect(self, out: list[str], skip_tables: bool, top: bool = False) -> None:
        if not top and (self.skipped() or (skip_tables and self.tag == "table")):
            return
        if self.tag in ("p", "div", "li", "br", "tr") or (
                # glossary hot spots follow a link without a space: "FindPatMaxRedLine</a><a …>function"
                self.tag == "a" and "MCTextPopupHotSpot" in (self.attrs.get("class") or "")):
            out.append(" ")
        for c in self.children:
            if isinstance(c, str):
                out.append(c)
            else:
                c._collect(out, skip_tables)

    def elements(self) -> list["_Node"]:
        return [c for c in self.children if isinstance(c, _Node)]

    def walk(self):
        yield self
        for c in self.elements():
            yield from c.walk()


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs), self.cur)
        self.cur.children.append(node)
        if tag not in _VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(_Node(tag, dict(attrs), self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def _rows(table: _Node) -> list[_Node]:
    rows = []
    for c in table.elements():
        if c.tag == "tr":
            rows.append(c)
        elif c.tag in ("tbody", "thead"):
            rows.extend(r for r in c.elements() if r.tag == "tr")
    return rows


def _cells(row: _Node) -> list[_Node]:
    return [c for c in row.elements() if c.tag in ("td", "th")]


def _inner_tables(cell: _Node) -> list[_Node]:
    """Tables inside ``cell`` that are not inside another table of ``cell``."""
    found = []

    def visit(n: _Node) -> None:
        for c in n.elements():
            if c.tag == "table":
                found.append(c)
            else:
                visit(c)

    visit(cell)
    return found


_LABEL_DEFAULT = re.compile(r"^(.*?)\s*\(\s*default\s*(?:=\s*([^)]*))?\)\s*$", re.I)
_OPTION = re.compile(r"^(-?\d+)\s*=\s*(.+)$")
_RANGE = re.compile(r"\(\s*(-?\d+(?:\.\d+)?)\s+to\s+(-?\d+(?:\.\d+)?)\s*;\s*(-?\d+(?:\.\d+)?)\s*=\s*default\s*\)",
                    re.I)
_RANGE_DASH = re.compile(r"\(\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*,\s*default\s*=\s*(-?\d+(?:\.\d+)?)\s*\)",
                         re.I)
# "(0 to 100; default = 5)", "(1 to 4 096; default = 3)"
_RANGE_DEFAULT = re.compile(r"\(\s*(-?\d[\d ]*(?:\.\d+)?)\s+to\s+(-?\d[\d ]*(?:\.\d+)?)\s*;\s*default\s*=\s*(-?\d+(?:\.\d+)?)\s*\)",
                            re.I)
_DEFAULT_IN_TEXT = re.compile(r"\(\s*default\s*=\s*([^)]+)\)|default (?:is|setting is|value is)\s+([^\s(.,;]+)",
                              re.I)
# "Fixture origin (X, Y, Theta)." / "Region of Interest (X, Y, Width, Height, Angle)."
_INLINE_CHILDREN = re.compile(r"\(((?:[A-Z][A-Za-z ]{0,15},\s*)+[A-Z][A-Za-z ]{0,15})\)")
_HEADER_LABELS = {"Parameter", "Parameters", "Setting", "Settings", "Input", "Inputs", "Name"}
_GROUP_WORDS = ("fixture", "region", "origin", "point", "position")


def _parse_label(label: str) -> tuple[str, Optional[str], bool]:
    """``"X (default = 0)"`` -> ("X", "0", False); ``"1 = ON (default)"`` -> ("1 = ON", None, True)."""
    m = _LABEL_DEFAULT.match(label)
    if not m:
        return label.strip(), None, False
    name, value = m.group(1).strip(), m.group(2)
    return name, (value.strip() if value else None), value is None


def _parse_rows(table: _Node, header: bool) -> list[dict]:
    params: list[dict] = []
    for row in _rows(table):
        cells = _cells(row)
        if len(cells) < 2:
            continue
        label = cells[0].text()
        if not label or (header and label in _HEADER_LABELS):
            continue
        desc_cell = cells[1]
        description = desc_cell.text(skip_tables=True)
        name, default, default_flag = _parse_label(label)
        param: dict = {"name": name, "description": description}
        nested = [p for t in _inner_tables(desc_cell) for p in _parse_rows(t, header=False)]
        options = [p for p in nested if p.get("option") is not None]
        children = [p for p in nested if p.get("option") is None]
        if options and len(options) >= len(nested) / 2:
            param["options"] = [{"value": p["option"], "label": p["option_label"],
                                 **({"default": True} if p.get("is_default") else {})} for p in options]
            if not default:
                d = next((p["option"] for p in options if p.get("is_default")), None)
                default = str(d) if d is not None else None
        elif children:
            param["children"] = children
        elif any(w in name.lower() for w in _GROUP_WORDS):
            m = _INLINE_CHILDREN.search(description)
            if m:
                param["children"] = [{"name": c.strip(), "description": ""} for c in m.group(1).split(",")]
        m = _RANGE.search(description) or _RANGE_DASH.search(description) or _RANGE_DEFAULT.search(description)
        if m:
            param["min"], param["max"] = (float(m.group(1).replace(" ", "")), float(m.group(2).replace(" ", "")))
            default = default or m.group(3)
        if not default and not param.get("children"):
            m = _DEFAULT_IN_TEXT.search(description)
            if m:
                default = (m.group(1) or m.group(2)).strip()
        if default:
            param["default"] = default
        om = _OPTION.match(name)
        if om:
            param["option"] = int(om.group(1))
            param["option_label"] = om.group(2).strip()
            param["is_default"] = default_flag
        params.append(param)
    return params


def _find_inputs_table(root: _Node) -> Optional[_Node]:
    seen_inputs = False
    for n in root.walk():
        if n.skipped():
            continue
        if not seen_inputs and n.tag in ("a", "h2", "h3", "h4", "p", "span") and n.text() == "Inputs":
            seen_inputs = True
            continue
        if seen_inputs and n.tag == "table":
            return n
    for n in root.walk():  # fallback: first table headed "Parameter"
        if n.tag == "table":
            rows = _rows(n)
            heads = [_cells(r)[0].text() for r in rows[:2] if _cells(r)]
            if any(h in _HEADER_LABELS for h in heads):
                return n
    return None


def _kind(p: dict) -> str:
    name = p["name"].lower()
    desc = p.get("description", "").lower()
    if p.get("children"):
        child_names = {c["name"].lower() for c in p["children"]}
        if "region" in name or {"width", "height"} <= child_names or "radius" in child_names:
            return "region"
        return "group"
    if p.get("options"):
        values = {o["value"] for o in p["options"]}
        labels = " ".join(o["label"].lower() for o in p["options"])
        if values == {0, 1} and (("off" in labels and "on" in labels) or ("false" in labels and "true" in labels)):
            return "bool"
        return "enum"
    if name == "image" or "contains an image" in desc:
        return "image"
    if "event" in name:
        return "event"
    if "cell reference" in desc or "reference to a cell" in desc or "references a cell" in desc:
        return "reference"
    if "min" in p or re.fullmatch(r"-?\d+(\.\d+)?", p.get("default") or ""):
        return "number"
    return "text"


def _finish(params: list[dict], keep_description: bool) -> list[dict]:
    out = []
    for p in params:
        q = {k: v for k, v in p.items() if k not in ("option", "option_label", "is_default")}
        q["kind"] = _kind(p)
        if not keep_description:
            q.pop("description", None)
        if "children" in q:
            q["children"] = _finish(q["children"], keep_description)
        out.append(q)
    return out


def parse_inputs(html_text: str, keep_description: bool = True) -> Optional[list[dict]]:
    """Parameter tree from a help page: ``[{name, kind, default?, min?, max?, options?,
    children?, description?}]``. None if the page has no Inputs table."""
    b = _Builder()
    b.feed(html_text)
    table = _find_inputs_table(b.root)
    if table is None:
        return None
    params = _parse_rows(table, header=True)
    return _finish(params, keep_description) or None


def parse_html(html_text: str) -> _Node:
    b = _Builder()
    b.feed(html_text)
    return b.root


_CALL = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*$")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FUNCTION_HEADERS = {"Function", "Functions", "Function Name"}


def _function_rows(root: _Node):
    """Rows of "Function | Description" tables: (name, argument text or None, description cell)."""
    for n in root.walk():
        if n.tag != "table" or n.skipped():
            continue
        rows = _rows(n)
        if not rows:
            continue
        head = [c.text() for c in _cells(rows[0])]
        if not head or head[0] not in _FUNCTION_HEADERS:
            continue
        for r in rows[1:]:
            cs = _cells(r)
            if len(cs) < 2:
                continue
            first = cs[0].text()
            m = _CALL.match(first)
            if m:
                yield m.group(1), m.group(2), cs[1]
            elif _IDENT.match(first):
                yield first, None, cs[1]


def function_tables(root: _Node) -> list[tuple[str, Optional[str]]]:
    """Functions listed in the page's "Function | Description" tables (Math, Logic, Vision Data
    Access pages, the getters table of a tool): ``[(name, "Arg1, [Arg2]" or None)]``."""
    return [(name, args) for name, args, _cell in _function_rows(root)]


_SENTENCE_END = re.compile(r"(?<=[a-z0-9)\]])\.(?=\s+[A-Z(])")


def _first_sentences(text: str, count: int = 2, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.,;:)])", r"\1", text)
    parts = _SENTENCE_END.split(text)
    out = ""
    for part in parts[:count]:
        candidate = (out + " " if out else "") + part.strip().rstrip(".") + "."
        if out and len(candidate) > limit:
            break
        out = candidate
    return out


def short_description(html_text: str, name: Optional[str] = None) -> str:
    """One- or two-sentence description for the Insert Function dialog and the Functions panel.

    With ``name``, the row of a "Function | Description" table (Math, Vision Data Access …) is
    used when the page has one; otherwise the first paragraph of the page.
    """
    root = parse_html(html_text)
    if name:
        for fname, _args, cell in _function_rows(root):
            if fname.lower() == name.lower():
                return _first_sentences(cell.text(skip_tables=True))
    seen_title = False
    for n in root.walk():
        if n.skipped():
            continue
        if n.tag == "h1":
            seen_title = True
            continue
        if seen_title and n.tag == "p":
            text = n.text()
            if text and not text.startswith(("Note", "Tip", "Copyright")):
                return _first_sentences(text)
            if text.startswith("Copyright"):
                break
    return ""


def parse_inputs_file(path: Path, keep_description: bool = True) -> Optional[list[dict]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return parse_inputs(text, keep_description)


def leaf_count(params: list[dict]) -> int:
    """Number of expression arguments the parameters take (a group takes one per child)."""
    return sum(leaf_count(p["children"]) if p.get("children") else 1 for p in params)
