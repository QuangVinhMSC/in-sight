"""Spreadsheet cell addressing, reference shifting and cell-result formatting."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

NUM_COLS = 26  # A..Z
NUM_ROWS = 600  # 0..599
FULL_RANGE = "A0:Z599"

_ADDR_RE = re.compile(r"^\$?([A-Za-z])\$?(\d{1,3})$")


def col_name(col: int) -> str:
    return chr(ord("A") + col)


def address(row: int, col: int) -> str:
    return f"{col_name(col)}{row}"


def parse_address(text: str) -> Optional[tuple[int, int]]:
    """Returns (row, col) for an address like ``B12`` or ``$B$12``; None if not an address."""
    m = _ADDR_RE.match(text.strip())
    if not m:
        return None
    col = ord(m.group(1).upper()) - ord("A")
    row = int(m.group(2))
    if not (0 <= col < NUM_COLS and 0 <= row < NUM_ROWS):
        return None
    return row, col


def parse_range(text: str) -> Optional[tuple[int, int, int, int]]:
    """Returns (row0, col0, row1, col1) normalised so that row0<=row1 and col0<=col1."""
    parts = text.split(":")
    if len(parts) == 1:
        a = parse_address(parts[0])
        return (a[0], a[1], a[0], a[1]) if a else None
    if len(parts) != 2:
        return None
    a, b = parse_address(parts[0]), parse_address(parts[1])
    if not a or not b:
        return None
    return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])


def looks_like_address(text: str) -> bool:
    return bool(re.match(r"^\$?[A-Za-z]{1,3}\$?\d+$", text.strip()))


# ---------------------------------------------------------------------------- references
# A cell reference inside an expression: optional $, column letter, optional $, row digits.
# It must not be part of a longer identifier (e.g. "Blobs_1.A2x" or a function name).
_REF_RE = re.compile(r"(?<![A-Za-z0-9_.\"])(\$?)([A-Z])(\$?)(\d{1,3})(?![A-Za-z0-9_(])")


def _split_strings(expr: str) -> list[tuple[bool, str]]:
    """Splits an expression into (is_string_literal, text) chunks. Strings use double quotes."""
    chunks: list[tuple[bool, str]] = []
    buf = []
    in_str = False
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch == '"':
            if in_str:
                # "" is an escaped quote inside a string literal
                if i + 1 < len(expr) and expr[i + 1] == '"':
                    buf.append('""')
                    i += 2
                    continue
                buf.append(ch)
                chunks.append((True, "".join(buf)))
                buf = []
                in_str = False
            else:
                if buf:
                    chunks.append((False, "".join(buf)))
                buf = [ch]
                in_str = True
        else:
            buf.append(ch)
        i += 1
    if buf:
        chunks.append((in_str, "".join(buf)))
    return chunks


def shift_references(expr: str, d_row: int, d_col: int) -> str:
    """Shifts relative cell references in ``expr`` like a spreadsheet copy/paste does.

    Absolute parts (``$A`` / ``$0``) are kept. Text constants (expressions that start with a
    single quote) and double-quoted string literals are not touched. References that would
    move off the sheet become ``#REF``.
    """
    if not expr or expr.startswith("'") or (d_row == 0 and d_col == 0):
        return expr

    def repl(m: re.Match) -> str:
        abs_col, col, abs_row, row = m.group(1), m.group(2), m.group(3), m.group(4)
        c = ord(col) - ord("A")
        r = int(row)
        if not abs_col:
            c += d_col
        if not abs_row:
            r += d_row
        if not (0 <= c < NUM_COLS and 0 <= r < NUM_ROWS):
            return "#REF"
        return f"{abs_col}{col_name(c)}{abs_row}{r}"

    out = []
    for is_str, text in _split_strings(expr):
        out.append(text if is_str else _REF_RE.sub(repl, text))
    return "".join(out)


def function_name(expr: str) -> Optional[str]:
    """Returns the outermost function name of an expression like ``EditInt(0,255)``."""
    m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(", expr or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------------------- results
def result_kind(cell: Optional[dict]) -> str:
    """The cell result type without the optional "Hmi" prefix (e.g. ``FloatResult``)."""
    if not cell:
        return ""
    t = str(cell.get("$type", ""))
    return t[3:] if t.startswith("Hmi") else t


GRAPHIC_TYPES = {
    "Region", "Circle", "Line", "Point", "Annulus", "Polygon", "CompositeRegion",
    "MaskedRegion", "PolylinePath", "MultiGraphics",
}

_LEGACY_EDIT_GRAPHIC = {
    "EditAnnulusResult", "EditPolygonResult", "EditCompositeRegionResult",
    "EditMaskedRegionResult", "EditPolylinePathResult", "EditRegionResult",
    "EditCircleResult", "EditLineResult", "EditPointResult",
}


def editable_graphic(cell: Optional[dict]) -> Optional[dict]:
    """Returns the graphic dict if the cell is an editable graphic (EditRegion etc.)."""
    kind = result_kind(cell)
    data = cell.get("data") if cell else None
    if kind in ("ButtonResult",) or kind in _LEGACY_EDIT_GRAPHIC:
        if isinstance(data, dict) and data.get("$type") in GRAPHIC_TYPES:
            return data
    return None


# Devices prefix the label of structure results (Image, Time, Patterns, ...) with a marker:
# U+2752 on 26.x firmware, BEL (U+0007) on older ones.
STRUCTURE_MARKERS = ("❒", "\u0007")


def _strip_controls(text: str) -> str:
    text = text.lstrip("".join(STRUCTURE_MARKERS))
    return "".join(ch for ch in text if ch >= " " or ch in "\t")


def is_structure(cell: Optional[dict]) -> bool:
    """True for cells that hold a data structure (shown as a label like 'Image')."""
    data = cell.get("data") if cell else None
    return isinstance(data, str) and data.startswith(STRUCTURE_MARKERS)


def argb_to_rgba(value: Any) -> Optional[tuple[int, int, int, int]]:
    if value is None:
        return None
    try:
        v = int(value) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return None
    return (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF, (v >> 24) & 0xFF


def format_number(value: Any, decimals: Optional[int] = None) -> str:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if decimals is None:
        decimals = 3
    return f"{f:.{max(0, min(int(decimals), 10))}f}"


def display_text(cell: Optional[dict], expression: str = "", decimals: Optional[int] = None) -> str:
    """Text to show in the grid for a cell result (falls back to the expression)."""
    if not cell:
        if expression.startswith("'"):
            return expression[1:]
        return expression
    kind = result_kind(cell)
    data = cell.get("data")
    if cell.get("error") or kind == "ErrorCellResult":
        return "#ERR"
    if kind in ("FloatResult", "EditFloatResult"):
        return format_number(data, decimals)
    if kind == "EditIntResult":
        try:
            return str(int(data))
        except (TypeError, ValueError):
            return str(data)
    if kind == "EditStringResult":
        text = "" if data is None else str(data)
        return "*" * len(text) if cell.get("maskInput") else text
    if kind == "StringResult":
        return _strip_controls("" if data is None else str(data))
    if kind == "ButtonResult" or kind in _LEGACY_EDIT_GRAPHIC:
        caption = cell.get("caption") or ""
        if isinstance(data, dict) and data.get("$type"):
            return f"[{caption or data['$type']}]"
        return f"[{caption or 'Button'}]"
    if kind == "CheckBoxResult":
        return f"{'☑' if data else '☐'} {cell.get('caption') or ''}".rstrip()
    if kind == "ListBoxResult":
        options = cell.get("options") or []
        try:
            return str(options[int(data)])
        except (TypeError, ValueError, IndexError):
            return str(data)
    if kind in ("StatusResult", "StatusLightResult"):
        return f"● {cell.get('caption') or ''}".rstrip()
    if kind == "MultiStatusResult":
        n = int(cell.get("numBits") or 0)
        start = int(cell.get("startBit") or 0)
        try:
            v = int(data) >> start
        except (TypeError, ValueError):
            v = 0
        bits = ["●" if (v >> i) & 1 else "○" for i in range(n)]
        if cell.get("reverse"):
            bits.reverse()
        return "".join(bits)
    if kind in ("ColorLabelResult", "ProfileViewResult", "DialogResult"):
        return _strip_controls("" if data is None else str(data))
    if kind == "UnsupportedCellResult":
        return "(not shown)"
    if data is None:
        return ""
    if isinstance(data, (int, float)):
        return format_number(data, decimals)
    if isinstance(data, dict):
        return f"[{data.get('$type', 'Object')}]"
    return _strip_controls(str(data))


STRUCTURE_GLYPH = "❒"


def grid_text(cell: Optional[dict], expression: str = "", decimals: Optional[int] = None) -> str:
    """Text shown in a grid cell: like :func:`display_text`, but structures keep ISVS's ``❒`` glyph."""
    text = display_text(cell, expression, decimals)
    if is_structure(cell) and not (cell.get("error") or result_kind(cell) == "ErrorCellResult"):
        return STRUCTURE_GLYPH + text
    return text


def is_error(cell: Optional[dict]) -> bool:
    return bool(cell) and (bool(cell.get("error")) or result_kind(cell) == "ErrorCellResult")


# In-cell HMI controls drawn as widgets in the grid (ISVS shows them as live controls).
CONTROL_KINDS = {
    "CheckBoxResult": "checkbox",
    "ListBoxResult": "listbox",
    "EditIntResult": "editint",
    "EditFloatResult": "editfloat",
    "EditStringResult": "editstring",
    "ButtonResult": "button",
    "StatusResult": "status",
    "StatusLightResult": "status",
    "MultiStatusResult": "multistatus",
}


def control_kind(cell: Optional[dict]) -> Optional[str]:
    """The kind of in-cell control for a result ("checkbox", "button", "graphic", ...), or None.

    Error cells are drawn as ``#ERR`` instead of a control.
    """
    if not cell or is_error(cell):
        return None
    kind = result_kind(cell)
    if editable_graphic(cell) is not None:
        return "graphic"
    if kind in _LEGACY_EDIT_GRAPHIC:
        return "graphic"
    return CONTROL_KINDS.get(kind)


def is_value_editable(cell: Optional[dict]) -> bool:
    """True when the cell is an HMI control whose value can be set with setCellValue."""
    if not cell or cell.get("disabled") or cell.get("error"):
        return False
    return result_kind(cell) in (
        "EditFloatResult", "EditIntResult", "EditStringResult", "CheckBoxResult", "ListBoxResult",
    )


@dataclass
class CellFormat:
    font_name: Optional[str] = None
    font_size: Optional[float] = None
    bold: bool = False
    italic: bool = False
    fore: Optional[tuple[int, int, int, int]] = None
    back: Optional[tuple[int, int, int, int]] = None
    decimals: Optional[int] = None
    h_align: Optional[int] = None
    v_align: Optional[int] = None


def parse_sheet_format(fmt: Optional[dict]) -> tuple[list[int], list[int], dict[str, CellFormat]]:
    """Parses a Sheet Format Object into (column widths, row heights, formats by location)."""
    if not isinstance(fmt, dict):
        return [], [], {}
    col_widths = [int(v or 0) for v in (fmt.get("columnWidths") or [])][:NUM_COLS]
    row_heights = [int(v or 0) for v in (fmt.get("rowHeights") or [])][:NUM_ROWS]
    formats: dict[str, CellFormat] = {}
    for f in fmt.get("cellFormats") or []:
        loc = f.get("location")
        if not loc:
            continue
        formats[str(loc).upper()] = CellFormat(
            font_name=f.get("fontName"),
            font_size=f.get("fontSize"),
            bold=bool(f.get("bold")),
            italic=bool(f.get("italics")),
            fore=argb_to_rgba(f.get("foreColor")),
            back=argb_to_rgba(f.get("backColor")),
            decimals=f.get("dp"),
            h_align=f.get("hAlign"),
            v_align=f.get("vAlign"),
        )
    return col_widths, row_heights, formats


def iter_range(range_text: str) -> Iterable[str]:
    r = parse_range(range_text)
    if not r:
        return
    r0, c0, r1, c1 = r
    for row in range(r0, r1 + 1):
        for col in range(c0, c1 + 1):
            yield address(row, col)
