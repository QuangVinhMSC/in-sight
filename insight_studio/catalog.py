"""Spreadsheet function catalog used by the Insert Function dialog and the Functions panel."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DATA = Path(__file__).resolve().parent / "data" / "functions.json"

# Where In-Sight Vision Suite keeps its spreadsheet help (used to open help pages locally).
DEFAULT_HELP_ROOTS = [
    Path("C:/Program Files/Cognex/In-Sight/In-Sight Vision Suite Editors/In-Sight"),
]


@dataclass
class FunctionInfo:
    name: str
    params: Optional[list[str]]
    category: str
    help: Optional[str] = None
    template: Optional[str] = None

    @property
    def signature(self) -> str:
        if self.params is None:
            return f"{self.name}(…)"
        return f"{self.name}({', '.join(self.params)})"

    def insert_text(self) -> str:
        """Text placed in the formula bar when the function is inserted."""
        if self.template:
            return self.template
        return f"{self.name}()"


class Catalog:
    def __init__(self, functions: list[FunctionInfo]) -> None:
        self.functions = sorted(functions, key=lambda f: f.name.lower())
        self._by_name = {f.name.lower(): f for f in self.functions}

    @classmethod
    def load(cls, path: Path = DATA, extra: Optional[Path] = None) -> "Catalog":
        functions: dict[str, FunctionInfo] = {}
        for p in [path, extra]:
            if p is None or not p.is_file():
                continue
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for e in doc.get("functions", []):
                if not e.get("name"):
                    continue
                functions[e["name"].lower()] = FunctionInfo(
                    name=e["name"], params=e.get("params"), category=e.get("category") or "Other",
                    help=e.get("help"), template=e.get("template"),
                )
        return cls(list(functions.values()))

    def get(self, name: str) -> Optional[FunctionInfo]:
        return self._by_name.get((name or "").lower())

    def search(self, text: str) -> list[FunctionInfo]:
        t = (text or "").strip().lower()
        if not t:
            return list(self.functions)
        starts = [f for f in self.functions if f.name.lower().startswith(t)]
        contains = [f for f in self.functions if t in f.name.lower() and f not in starts]
        return starts + contains

    def categories(self) -> list[str]:
        return sorted({f.category for f in self.functions})


def find_help_file(info: FunctionInfo, extra_roots: Optional[list[Path]] = None) -> Optional[Path]:
    """Locates the locally installed ISVS help page for a function (Windows only)."""
    if not info.help:
        return None
    roots = list(extra_roots or []) + (DEFAULT_HELP_ROOTS if sys.platform == "win32" else [])
    for root in roots:
        if not root.is_dir():
            continue
        for version_dir in sorted(root.iterdir(), reverse=True):
            candidate = version_dir / "Docs" / "Help_InSight" / info.help
            if candidate.is_file():
                return candidate
    return None
