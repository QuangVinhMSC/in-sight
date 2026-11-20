"""Cell operations done on the client: moving blocks of cells (Insert / Delete / Cut + Paste),
reference rewriting, undo history and Find.

The In-Sight HMI API only writes one cell at a time (expression, name, cell state, value), so
operations that ISVS performs inside the sheet are computed here as a set of target cell states
and written by :meth:`InSightDevice.write_cells`.

Device behaviour this relies on (checked on an IS8902CX, firmware 26.1.0, 2026-11-20):

* rewriting the expression of a cell keeps its name, cell state and control value; a cell written
  from empty starts with the default value; clearing a cell removes its name and cell state;
* expressions cannot refer to cells by name, so only ``A1``-style references need rewriting;
* ``setCellName(loc, "")`` removes a name; a name already in use gets a ``_1`` suffix;
* cell state (``getCellCondition``): ``""`` enabled, ``"0"`` disabled, a cell reference
  (``Z594`` / ``$Z$594``) conditionally enabled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable, Optional

from . import cells

RC = tuple[int, int]
Block = tuple[int, int, int, int]  # row0, col0, row1, col1 (inclusive)
Mapping = Callable[[int, int], Optional[RC]]  # new position of a cell, None when it is removed

REF_ERROR = "#REF"

# ISVS dialog choices (live/09, live/10)
SHIFT_RIGHT, SHIFT_DOWN, ENTIRE_ROW, ENTIRE_COLUMN = "right", "down", "row", "column"
SHIFT_LEFT, SHIFT_UP = "left", "up"


@dataclass(frozen=True)
class CellState:
    """What can be written to a cell through the HMI API.

    ``name`` / ``condition`` / ``value`` = None means "leave as it is" when writing and
    "unknown" in a snapshot. ``condition`` "" = enabled, "0" = disabled, a reference = conditional.
    """

    expr: str = ""
    name: Optional[str] = None
    condition: Optional[str] = None
    value: Any = None


EMPTY = CellState("", "", "", None)


def loc_of(rc: RC) -> str:
    return cells.address(*rc)


def rc_of(loc: str) -> RC:
    rc = cells.parse_address(loc)
    if rc is None:
        raise ValueError(f"not a cell address: {loc}")
    return rc


# ---------------------------------------------------------------------------- references
def rewrite_references(expr: Optional[str], mapping: Mapping, keep_removed: bool = False) -> Optional[str]:
    """Points every cell reference in ``expr`` at the new position of the cell it refers to.

    Absolute/relative markers are kept (Insert/Delete move ``$A$1`` too, like a spreadsheet).
    References to removed cells become ``#REF`` — or stay as they are with ``keep_removed``
    (ISVS's Delete: ``D1*2`` still reads ``D1*2`` after column D is deleted and then refers to the
    cell that moved into D1; survey 2026-11-20). Text constants and string literals are kept.
    """
    if not expr or expr.startswith("'"):
        return expr

    def repl(m: re.Match) -> str:
        abs_col, col, abs_row, row = m.group(1), m.group(2), m.group(3), m.group(4)
        r, c = int(row), ord(col) - ord("A")
        if not (0 <= r < cells.NUM_ROWS and 0 <= c < cells.NUM_COLS):
            return m.group(0)
        new = mapping(r, c)
        if new is None:
            return m.group(0) if keep_removed else REF_ERROR
        return f"{abs_col}{cells.col_name(new[1])}{abs_row}{new[0]}"

    out = []
    for is_str, text in cells._split_strings(expr):
        out.append(text if is_str else cells._REF_RE.sub(repl, text))
    return "".join(out)


def references(expr: Optional[str]) -> list[RC]:
    """The cells an expression refers to (each end of a range counts as one reference)."""
    found: list[RC] = []
    rewrite_references(expr, lambda r, c: found.append((r, c)) or (r, c))
    return found


def shift_condition(condition: Optional[str], d_row: int, d_col: int) -> Optional[str]:
    """Cell states copy like references: a relative condition cell moves with the paste."""
    if not condition or condition == "0":
        return condition
    return cells.shift_references(condition, d_row, d_col)


# ---------------------------------------------------------------------------- blocks
def normalise_block(block: Block, mode: str) -> Block:
    r0, c0, r1, c1 = block
    if mode == ENTIRE_ROW:
        return r0, 0, r1, cells.NUM_COLS - 1
    if mode == ENTIRE_COLUMN:
        return 0, c0, cells.NUM_ROWS - 1, c1
    return block


def is_entire_rows(block: Block) -> bool:
    return block[1] == 0 and block[3] == cells.NUM_COLS - 1


def is_entire_columns(block: Block) -> bool:
    return block[0] == 0 and block[2] == cells.NUM_ROWS - 1


def block_text(block: Block) -> str:
    r0, c0, r1, c1 = block
    a, b = cells.address(r0, c0), cells.address(r1, c1)
    return a if a == b else f"{a}:{b}"


def _inside(r: int, c: int, block: Block) -> bool:
    return block[0] <= r <= block[2] and block[1] <= c <= block[3]


def _on_sheet(r: int, c: int) -> Optional[RC]:
    return (r, c) if 0 <= r < cells.NUM_ROWS and 0 <= c < cells.NUM_COLS else None


def insert_mapping(block: Block, mode: str) -> Mapping:
    """Insert: the cells at and after ``block`` move right/down by its size."""
    r0, c0, r1, c1 = normalise_block(block, mode)
    down = mode in (SHIFT_DOWN, ENTIRE_ROW)
    n = (r1 - r0 + 1) if down else (c1 - c0 + 1)

    def mapping(r: int, c: int) -> Optional[RC]:
        if down and c0 <= c <= c1 and r >= r0:
            return _on_sheet(r + n, c)
        if not down and r0 <= r <= r1 and c >= c0:
            return _on_sheet(r, c + n)
        return r, c

    return mapping


def delete_mapping(block: Block, mode: str) -> Mapping:
    """Delete: the cells of ``block`` go away, the ones after it move left/up."""
    r0, c0, r1, c1 = normalise_block(block, mode)
    up = mode in (SHIFT_UP, ENTIRE_ROW)
    n = (r1 - r0 + 1) if up else (c1 - c0 + 1)

    def mapping(r: int, c: int) -> Optional[RC]:
        if _inside(r, c, (r0, c0, r1, c1)):
            return None
        if up and c0 <= c <= c1 and r > r1:
            return r - n, c
        if not up and r0 <= r <= r1 and c > c1:
            return r, c - n
        return r, c

    return mapping


def move_mapping(source: Block, d_row: int, d_col: int) -> Mapping:
    """Cut + Paste: the source cells move; the cells they land on are replaced."""
    r0, c0, r1, c1 = source
    dest = (r0 + d_row, c0 + d_col, r1 + d_row, c1 + d_col)

    def mapping(r: int, c: int) -> Optional[RC]:
        if _inside(r, c, source):
            return _on_sheet(r + d_row, c + d_col)
        if _inside(r, c, dest):
            return None
        return r, c

    return mapping


def plan_move(states: dict[str, CellState], mapping: Mapping, rewrite_all: bool = True,
              keep_removed: bool = False) -> dict[str, CellState]:
    """Target states for moving cells according to ``mapping``.

    ``states`` holds the current state of every non-empty cell (names and conditions known).
    Returns only the cells that change. Moved cells take their name, condition and control
    value along; references everywhere are rewritten (``keep_removed``: see
    :func:`rewrite_references`). Cells mapped to None disappear (check :func:`would_lose` first
    for an Insert).
    """
    new: dict[str, CellState] = {}
    for loc, st in states.items():
        if not st.expr:
            continue
        r, c = rc_of(loc)
        dest = mapping(r, c)
        if dest is None:
            continue
        moved = dest != (r, c)
        expr = rewrite_references(st.expr, mapping, keep_removed) if rewrite_all or moved else st.expr
        cond = (rewrite_references(st.condition, mapping, keep_removed) if st.condition not in (None, "", "0")
                else st.condition)
        new[loc_of(dest)] = CellState(expr=expr, name=st.name or "", condition=cond,
                                      value=st.value if moved else None)
    targets: dict[str, CellState] = {}
    for loc in set(states) | set(new):
        cur = states.get(loc, EMPTY)
        tgt = new.get(loc, EMPTY)
        if tgt.expr == cur.expr and (tgt.name or "") == (cur.name or "") and tgt.condition == cur.condition \
                and tgt.value is None:
            continue
        targets[loc] = tgt
    return targets


def would_lose(states: dict[str, CellState], block: Block, mode: str) -> list[str]:
    """Non-empty cells that an Insert would push off the sheet."""
    mapping = insert_mapping(block, mode)
    return [loc for loc, st in states.items() if st.expr and mapping(*rc_of(loc)) is None]


# ---------------------------------------------------------------------------- undo history
@dataclass
class Change:
    label: str
    before: dict[str, CellState]
    after: dict[str, CellState]


class History:
    """Client-side Undo/Redo of what this client wrote to the sheet."""

    LIMIT = 100

    def __init__(self) -> None:
        self.undo_stack: list[Change] = []
        self.redo_stack: list[Change] = []

    def push(self, change: Change) -> None:
        if not change.before and not change.after:
            return
        self.undo_stack.append(change)
        del self.undo_stack[:-self.LIMIT]
        self.redo_stack.clear()

    def clear(self) -> None:
        self.undo_stack.clear()
        self.redo_stack.clear()

    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    def can_redo(self) -> bool:
        return bool(self.redo_stack)

    def take_undo(self) -> Optional[Change]:
        if not self.undo_stack:
            return None
        ch = self.undo_stack.pop()
        self.redo_stack.append(ch)
        return ch

    def take_redo(self) -> Optional[Change]:
        if not self.redo_stack:
            return None
        ch = self.redo_stack.pop()
        self.undo_stack.append(ch)
        return ch


def restore_targets(states: dict[str, CellState]) -> dict[str, CellState]:
    """Targets that bring cells back to recorded states (unknown names/conditions become empty)."""
    return {loc: replace(st, name=st.name or "") if st.expr else EMPTY for loc, st in states.items()}


# ---------------------------------------------------------------------------- find / replace
LOOK_EXPRESSIONS, LOOK_VALUES, LOOK_COMMENTS, LOOK_NAMES = "Expressions", "Values", "Comments", "Names"
ROWS_FIRST, COLUMNS_FIRST = "Rows First", "Columns First"


def cell_order(by_rows: bool) -> list[RC]:
    if by_rows:
        return [(r, c) for r in range(cells.NUM_ROWS) for c in range(cells.NUM_COLS)]
    return [(r, c) for c in range(cells.NUM_COLS) for r in range(cells.NUM_ROWS)]


def text_matches(text: str, what: str, match_case: bool, entire: bool) -> bool:
    if not match_case:
        text, what = text.lower(), what.lower()
    return text == what if entire else what in text


def find_cell(texts: dict[str, str], what: str, start: Optional[RC], forward: bool = True, by_rows: bool = True,
              match_case: bool = False, entire: bool = False, is_empty: Optional[Callable[[str], bool]] = None
              ) -> Optional[RC]:
    """The next (or previous) cell after ``start`` whose text matches, wrapping around.

    ``texts`` maps locations to the searched text. An empty ``what`` finds the next empty cell
    (ISVS: "the next cell without a formula, value, or comment"); ``is_empty`` decides that.
    """
    order = cell_order(by_rows)
    if not forward:
        order.reverse()
    n = len(order)
    i0 = order.index(start) + 1 if start in order else 0
    for k in range(n):
        r, c = order[(i0 + k) % n]
        loc = cells.address(r, c)
        if what == "":
            if (is_empty(loc) if is_empty else not texts.get(loc)):
                return r, c
        elif loc in texts and text_matches(texts[loc], what, match_case, entire):
            return r, c
    return None


def replace_text(text: str, what: str, with_: str, match_case: bool, entire: bool) -> str:
    """Replaces every occurrence (or the whole text when ``entire``)."""
    if entire:
        return with_ if text_matches(text, what, match_case, True) else text
    flags = 0 if match_case else re.IGNORECASE
    return re.sub(re.escape(what), lambda _m: with_, text, flags=flags)


def iter_block(block: Block) -> Iterable[str]:
    r0, c0, r1, c1 = block
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            yield cells.address(r, c)
