"""Cell operations logic (phase 3): reference rewriting, Insert/Delete/Cut plans, history, find."""

import pytest

from insight_studio import sheet_ops as ops
from insight_studio.sheet_ops import CellState, EMPTY


def S(expr, name="", cond="", value=None):
    return CellState(expr, name, cond, value)


def test_rewrite_references_insert_rows():
    m = ops.insert_mapping((3, 0, 4, 25), ops.ENTIRE_ROW)  # two rows at 3
    assert ops.rewrite_references("A2+A3+$B$4+B$5+$C9", m) == "A2+A5+$B$6+B$7+$C11"
    assert ops.rewrite_references('Concat("A3",A3)', m) == 'Concat("A3",A5)'
    assert ops.rewrite_references("'A3 text", m) == "'A3 text"
    assert ops.rewrite_references("Sum(A1:A4)", m) == "Sum(A1:A6)"  # a range spanning the insert grows


def test_delete_mapping_makes_ref_errors():
    m = ops.delete_mapping((2, 1, 2, 1), ops.SHIFT_UP)  # delete B2, shift up
    assert m(2, 1) is None and m(3, 1) == (2, 1) and m(3, 2) == (3, 2) and m(1, 1) == (1, 1)
    assert ops.rewrite_references("B2*B3+C3", m) == "#REF*B2+C3"


def test_shift_right_and_left():
    ins = ops.insert_mapping((1, 1, 2, 2), ops.SHIFT_RIGHT)
    assert ins(1, 1) == (1, 3) and ins(2, 5) == (2, 7) and ins(3, 1) == (3, 1) and ins(1, 0) == (1, 0)
    assert ins(1, 24) is None  # pushed off the sheet
    dele = ops.delete_mapping((0, 0, 599, 0), ops.ENTIRE_COLUMN)
    assert dele(5, 0) is None and dele(5, 1) == (5, 0)


def test_plan_insert_moves_names_conditions_and_values():
    states = {
        "A0": S("AcquireImage()", "Image"),
        "A3": S("EditInt(0,100)", "Threshold", "", 42),
        "A4": S("A3*2", "", "A3"),
        "B9": S("$A$3+A4"),
    }
    targets = ops.plan_move(states, ops.insert_mapping((3, 0, 3, 0), ops.SHIFT_DOWN))
    assert targets == {
        "A3": EMPTY,
        "A4": S("EditInt(0,100)", "Threshold", "", 42),
        "A5": S("A4*2", "", "A4"),
        "B9": S("$A$4+A5"),  # not moved: rewritten in place, value/name left alone
    }


def test_plan_delete_shift_left():
    states = {"A1": S("1"), "B1": S("2", "Two"), "C1": S("B1+A1"), "D1": S("C1")}
    targets = ops.plan_move(states, ops.delete_mapping((1, 1, 1, 1), ops.SHIFT_LEFT))
    assert targets == {"B1": S("#REF+A1"), "C1": S("B1"), "D1": EMPTY}


def test_move_mapping_cut_paste():
    states = {"A1": S("5", "Five"), "A2": S("A1+1"), "C1": S("9"), "D1": S("C1")}
    m = ops.move_mapping((1, 0, 1, 0), 0, 2)  # cut A1, paste to C1
    targets = ops.plan_move(states, m)
    assert targets == {"A1": EMPTY, "C1": S("5", "Five"), "A2": S("C1+1"), "D1": S("#REF")}


def test_would_lose():
    states = {"A599": S("1"), "B10": S("2")}
    assert ops.would_lose(states, (5, 0, 5, 0), ops.SHIFT_DOWN) == ["A599"]
    assert ops.would_lose(states, (5, 1, 5, 1), ops.SHIFT_DOWN) == []


def test_history():
    h = ops.History()
    assert not h.can_undo()
    h.push(ops.Change("a", {"A1": EMPTY}, {"A1": S("1")}))
    h.push(ops.Change("b", {"A1": S("1")}, {"A1": S("2")}))
    assert h.take_undo().label == "b" and h.can_redo()
    assert h.take_redo().label == "b"
    h.take_undo()
    h.push(ops.Change("c", {}, {"B1": S("3")}))
    assert not h.can_redo() and [c.label for c in h.undo_stack] == ["a", "c"]


@pytest.mark.parametrize("by_rows,expected", [(True, (0, 2)), (False, (1, 0))])
def test_find_order(by_rows, expected):
    texts = {"A0": "x", "C0": "foo", "A1": "foo"}
    assert ops.find_cell(texts, "foo", (0, 0), by_rows=by_rows) == expected


def test_find_wraps_case_entire_and_backwards():
    texts = {"B2": "Threshold", "A5": "thresh"}
    assert ops.find_cell(texts, "THRESH", (3, 0)) == (5, 0)
    assert ops.find_cell(texts, "THRESH", (5, 0)) == (2, 1)  # wraps
    assert ops.find_cell(texts, "THRESH", (5, 0), match_case=True) is None
    assert ops.find_cell(texts, "thresh", (0, 0), entire=True) == (5, 0)
    assert ops.find_cell(texts, "thresh", (5, 0), forward=False) == (2, 1)
    assert ops.find_cell(texts, "", (2, 0)) == (2, 0 + 2)  # next empty cell after A2 is C2 (B2 has text)


def test_replace_text():
    assert ops.replace_text("A1+a1", "a1", "B2", match_case=False, entire=False) == "B2+B2"
    assert ops.replace_text("A1+a1", "a1", "B2", match_case=True, entire=False) == "A1+B2"
    assert ops.replace_text("A1", "a1", "B2", match_case=False, entire=True) == "B2"
    assert ops.replace_text("A1+1", "a1", "B2", match_case=False, entire=True) == "A1+1"
