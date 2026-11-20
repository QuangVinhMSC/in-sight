"""Spreadsheet function catalog used by the Insert Function dialog and the Functions panel.

The catalog (``data/functions.json``, built by ``tools/build_catalog.py``) holds facts only:
function names, parameter lists, the toolbox category tree and help page paths. The one-line
descriptions shown by the Insert Function dialog and the Functions panel are read from the In-Sight
help installed on this computer (see :func:`describe_function`); without it only signatures show.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

DATA = Path(__file__).resolve().parent / "data" / "functions.json"

# Where In-Sight Vision Suite keeps its spreadsheet help (used to open help pages locally).
_EDITORS = Path("Program Files/Cognex/In-Sight/In-Sight Vision Suite Editors/In-Sight")
DEFAULT_HELP_ROOTS = [Path("C:/") / _EDITORS]


def help_roots() -> list[Path]:
    """ISVS editor folders on this computer: the Windows install, or one inside a Wine prefix."""
    if sys.platform == "win32":
        return list(DEFAULT_HELP_ROOTS)
    prefixes = [Path(os.environ["WINEPREFIX"])] if os.environ.get("WINEPREFIX") else []
    prefixes += [Path.home() / "cognex-wine", Path.home() / ".wine"]
    return [p / "drive_c" / _EDITORS for p in prefixes]


def editor_versions(extra_roots: Optional[list[Path]] = None) -> list[Path]:
    """Installed ``In-Sight <version>`` editor folders, newest first."""
    found: list[Path] = []
    for root in list(extra_roots or []) + help_roots():
        if root.is_dir():
            found += sorted((d for d in root.iterdir() if d.is_dir()), reverse=True)
    return found


@dataclass
class FunctionInfo:
    name: str
    params: Optional[list[str]]
    category: str
    help: Optional[str] = None
    template: Optional[str] = None
    inputs: Optional[list[dict]] = None  # parameter tree from the help page (see helpdoc)
    paths: list[tuple[str, ...]] = field(default_factory=list)  # toolbox categories
    getters: Optional[list[str]] = None  # Vision Data Access functions the tool inserts
    enable: Optional[dict[str, dict]] = None  # {parameter: {"param": controlling parameter, "values": [...]}}

    @property
    def signature(self) -> str:
        if self.params is None:
            return f"{self.name}(…)"
        return f"{self.name}({', '.join(self.params)})"

    @property
    def short_signature(self) -> str:
        """As the Insert Function dialog shows it: ``TrainPatMaxRedLine(Image, Fixture, Region, ...)``."""
        if self.params is not None:
            return self.signature
        if self.inputs:
            names = [p["name"] for p in self.inputs]
            return f"{self.name}({', '.join(names[:3])}{', ...' if len(names) > 3 else ''})"
        return self.signature

    @property
    def has_property_sheet(self) -> bool:
        return bool(self.inputs)

    def insert_text(self) -> str:
        """Text placed in the formula bar when the function is inserted."""
        if self.template:
            return self.template
        return f"{self.name}()"


@dataclass
class Category:
    name: str
    path: tuple[str, ...]
    help: Optional[str] = None
    children: list["Category"] = field(default_factory=list)
    hidden: bool = False  # depends on the vision system model; not shown in the toolbox tree


def _categories(items: list[dict], parent: tuple[str, ...] = ()) -> list[Category]:
    out = []
    for c in items or []:
        path = parent + (c["name"],)
        out.append(Category(c["name"], path, c.get("help"), _categories(c.get("children"), path),
                            bool(c.get("hidden"))))
    return out


class Catalog:
    def __init__(self, functions: list[FunctionInfo], categories: Optional[list[Category]] = None,
                 toolbox_help: Optional[str] = None) -> None:
        self.functions = sorted(functions, key=lambda f: f.name.lower())
        self._by_name = {f.name.lower(): f for f in self.functions}
        self.categories = categories or []
        self.toolbox_help = toolbox_help

    @classmethod
    def load(cls, path: Path = DATA, extra: Optional[Path] = None) -> "Catalog":
        functions: dict[str, FunctionInfo] = {}
        categories: list[Category] = []
        toolbox_help = None
        for p in [path, extra]:
            if p is None or not p.is_file():
                continue
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if doc.get("categories"):
                categories = _categories(doc["categories"])
                toolbox_help = doc.get("toolbox_help")
            for e in doc.get("functions", []):
                if not e.get("name"):
                    continue
                paths = [tuple(x) for x in e.get("paths") or []]
                functions[e["name"].lower()] = FunctionInfo(
                    name=e["name"], params=e.get("params"),
                    category=e.get("category") or (paths[0][-1] if paths else "Other"),
                    help=e.get("help"), template=e.get("template"), inputs=e.get("inputs"), paths=paths,
                    getters=e.get("getters"), enable=e.get("enable"),
                )
        return cls(list(functions.values()), categories, toolbox_help)

    def get(self, name: str) -> Optional[FunctionInfo]:
        return self._by_name.get((name or "").lower())

    def search(self, text: str) -> list[FunctionInfo]:
        t = (text or "").strip().lower()
        if not t:
            return list(self.functions)
        starts = [f for f in self.functions if f.name.lower().startswith(t)]
        contains = [f for f in self.functions if t in f.name.lower() and f not in starts]
        return starts + contains

    # ------------------------------------------------------------------ toolbox tree
    def tree(self) -> list[Category]:
        """The toolbox categories shown in the Functions panel and the Insert Function dialog."""
        return [c for c in self.categories if not c.hidden]

    def _hidden_roots(self) -> set[str]:
        return {c.name for c in self.categories if c.hidden}

    def functions_in(self, path: tuple[str, ...] = ()) -> list[FunctionInfo]:
        """Functions of a category and its subcategories, by name (``()`` = All: every function
        of the visible toolbox tree; without a tree, every function)."""
        if not self.categories:
            return list(self.functions) if not path else [f for f in self.functions if f.category == path[-1]]
        hidden = self._hidden_roots()
        n = len(path)
        return [f for f in self.functions
                if any(p[:n] == path and (n or p[0] not in hidden) for p in f.paths)]

    def direct_functions(self, path: tuple[str, ...]) -> list[FunctionInfo]:
        """Functions filed directly in a category (not in one of its subcategories)."""
        return [f for f in self.functions if path in f.paths]

    def find_category(self, path: tuple[str, ...]) -> Optional[Category]:
        items = self.categories
        found = None
        for name in path:
            found = next((c for c in items if c.name == name), None)
            if found is None:
                return None
            items = found.children
        return found


# ---------------------------------------------------------------------------- local help
def help_file(rel: Optional[str], extra_roots: Optional[list[Path]] = None) -> Optional[Path]:
    """A page of the locally installed ISVS help (``rel`` relative to ``Docs/Help_InSight``)."""
    if not rel:
        return None
    for version_dir in editor_versions(extra_roots):
        candidate = version_dir / "Docs" / "Help_InSight" / rel
        if candidate.is_file():
            return candidate
    return None


def find_help_file(info: FunctionInfo, extra_roots: Optional[list[Path]] = None) -> Optional[Path]:
    """Locates the locally installed ISVS help page for a function."""
    return help_file(info.help, extra_roots)


@lru_cache(maxsize=1024)
def _describe(rel: str, name: Optional[str]) -> str:
    from .helpdoc import short_description

    path = help_file(rel)
    if path is None:
        return ""
    try:
        return short_description(path.read_text(encoding="utf-8", errors="replace"), name)
    except (OSError, ValueError):
        return ""


def describe_function(info: FunctionInfo) -> str:
    """One- or two-sentence description from the local help ("" when it is not installed)."""
    return _describe(info.help, info.name) if info.help else ""


def describe_category(cat: Category) -> str:
    return _describe(cat.help, None) if cat.help else ""


# ---------------------------------------------------------------------------- inserting a function
_NUMBER = re.compile(r"-?\d+(\.\d+)?")
DEFAULT_IMAGE_SIZE = (800, 600)


def _num(v: float) -> str:
    return str(int(round(v)))


def _region_args(children: list[dict], size: tuple[int, int]) -> list[Optional[str]]:
    """Default geometry of a region-like group, centred on the image as ISVS does
    (TrainPatMaxRedLine on 800×600: Pattern Region = (180,140,440,320,0,0))."""
    w, h = size
    names = [c["name"].lower() for c in children]
    defaults = {c["name"].lower(): c.get("default") for c in children}

    def num(key: str, fallback: float) -> float:
        d = defaults.get(key)
        return float(d) if d is not None and _NUMBER.fullmatch(d.strip()) else fallback

    out: list[Optional[str]] = []
    if "width" in names and "height" in names:
        rw, rh = num("width", w / 2), num("height", h / 2)
        geo = {"x": (w - rw) / 2, "y": (h - rh) / 2, "width": rw, "height": rh}
    elif any("radius" in n for n in names):
        r = min(w, h)
        geo = {"x": w / 2, "y": h / 2, "radius": num("radius", r / 4),
               "inner radius": num("inner radius", r / 8), "outer radius": num("outer radius", r / 4)}
    else:
        geo = {"x": w / 2, "y": h / 2, "x 0": w / 4, "y 0": h / 2, "x 1": 3 * w / 4, "y 1": h / 2,
               "x0": w / 4, "y0": h / 2, "x1": 3 * w / 4, "y1": h / 2}
    for c in children:
        key = c["name"].lower()
        if key in geo:
            out.append(_num(geo[key]) if key not in defaults or defaults[key] is None
                       or key in ("x", "y") else defaults[key])
        else:
            d = c.get("default")
            out.append(d if d is not None and _NUMBER.fullmatch(d.strip()) else "0")
    return out


def _leaf_arg(p: dict) -> Optional[str]:
    kind = p.get("kind")
    name = p["name"].lower()
    default = p.get("default")
    if kind == "image":
        return "$A$0"
    if p.get("options"):
        d = next((o["value"] for o in p["options"] if o.get("default")), None)
        if d is None and default is not None and _NUMBER.fullmatch(default.strip()):
            return default.strip()
        return str(d if d is not None else p["options"][0]["value"])
    if kind == "event":
        # an acquisition event retrains / resets on every image: start those without an event
        return "0" if any(w in name for w in ("train", "reset", "clear")) else "$A$0"
    if default is not None and _NUMBER.fullmatch(default.strip()):
        return default.strip()
    if kind == "reference":
        return "0"  # e.g. External Region = 0 (ISVS property sheet)
    if default is not None and default.strip() and not default.strip().startswith(("$", "'")):
        return '"' + default.strip().strip('"').replace('"', '""') + '"'
    return None


def default_expression(info: FunctionInfo, image_size: Optional[tuple[int, int]] = None) -> Optional[str]:
    """The expression a newly inserted tool starts with before its property sheet opens: the
    help's defaults, the image in ``$A$0``, a zero fixture and a region centred on the image.

    None when a parameter has no default the help states (then the function name goes to the
    formula bar instead, as for functions without a property sheet).
    """
    if info.template:
        return info.template
    if not info.inputs:
        return None
    size = image_size if image_size and image_size[0] > 0 and image_size[1] > 0 else DEFAULT_IMAGE_SIZE
    args: list[Optional[str]] = []
    for p in info.inputs:
        children = p.get("children")
        if not children:
            args.append(_leaf_arg(p))
        elif p.get("kind") == "region":
            args += _region_args(children, size)
        else:  # Fixture, Pattern Origin, …
            for c in children:
                d = c.get("default")
                if c.get("options"):
                    args.append(_leaf_arg(c))
                else:
                    args.append(d.strip() if d is not None and _NUMBER.fullmatch(d.strip()) else "0")
    if any(a is None for a in args):
        return None
    return f"{info.name}({','.join(args)})"
