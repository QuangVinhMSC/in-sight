from insight_studio import cells


def test_address_roundtrip():
    assert cells.address(0, 0) == "A0"
    assert cells.address(599, 25) == "Z599"
    assert cells.parse_address("B12") == (12, 1)
    assert cells.parse_address("$C$3") == (3, 2)
    assert cells.parse_address("AA1") is None
    assert cells.parse_address("A600") is None


def test_parse_range_normalises():
    assert cells.parse_range("C5:A1") == (1, 0, 5, 2)
    assert list(cells.iter_range("A0:B1")) == ["A0", "B0", "A1", "B1"]


def test_shift_relative_and_absolute():
    assert cells.shift_references("A1+B2", 1, 1) == "B2+C3"
    assert cells.shift_references("$A$0+A$1+$A1", 2, 3) == "$A$0+D$1+$A3"
    assert cells.shift_references("FindPatMaxRedLine($A$0,A2,0)", 1, 0) == "FindPatMaxRedLine($A$0,A3,0)"


def test_shift_leaves_strings_names_and_text_alone():
    assert cells.shift_references('Concatenate("A1",B1)', 1, 0) == 'Concatenate("A1",B2)'
    assert cells.shift_references("'A1 is text", 1, 0) == "'A1 is text"
    assert cells.shift_references("Blobs_1.Pass+A1", 1, 0) == "Blobs_1.Pass+A2"
    assert cells.shift_references("Count($A$0,9999999,0,0)", 5, 5) == "Count($A$0,9999999,0,0)"


def test_shift_off_sheet_becomes_ref_error():
    assert cells.shift_references("A0", -1, 0) == "#REF"
    assert cells.shift_references("Z1", 0, 1) == "#REF"


def test_display_text_by_type():
    assert cells.display_text({"$type": "HmiFloatResult", "data": 7}) == "7.000"
    assert cells.display_text({"$type": "FloatResult", "data": 1.23456}, decimals=1) == "1.2"
    assert cells.display_text({"$type": "HmiStringResult", "data": "\u0007Blobs"}) == "Blobs"
    # 26.1 firmware (IS8902CX) marks structure labels with U+2752
    assert cells.display_text({"$type": "HmiStringResult", "data": "❒Image"}) == "Image"
    assert cells.is_structure({"$type": "HmiStringResult", "data": "❒Time"})
    # errors arrive as a StringResult with error=true
    assert cells.display_text({"$type": "HmiStringResult", "error": True, "data": ""}) == "#ERR"
    assert cells.display_text({"$type": "HmiEditIntResult", "data": 12}) == "12"
    assert cells.display_text({"$type": "ErrorCellResult"}) == "#ERR"
    assert cells.display_text({"$type": "HmiListBoxResult", "data": 1, "options": ["a", "b"]}) == "b"
    assert cells.display_text({"$type": "HmiButtonResult", "data": {"$type": "Region"},
                               "caption": "Roi"}) == "[Roi]"
    assert cells.display_text(None, "'hello") == "hello"
    assert cells.display_text({"$type": "HmiEditStringResult", "data": "pw", "maskInput": True}) == "**"


def test_editable_graphic_and_values():
    region = {"$type": "HmiButtonResult", "data": {"$type": "Region", "x": 1}}
    assert cells.editable_graphic(region) == {"$type": "Region", "x": 1}
    assert cells.editable_graphic({"$type": "HmiButtonResult", "data": 0}) is None
    assert cells.is_value_editable({"$type": "HmiEditIntResult", "data": 1})
    assert not cells.is_value_editable({"$type": "HmiEditIntResult", "data": 1, "disabled": True})


def test_argb():
    assert cells.argb_to_rgba(-16744448) == (0, 128, 0, 255)
    assert cells.argb_to_rgba(4278255360) == (0, 255, 0, 255)


def test_sheet_format():
    widths, heights, fmts = cells.parse_sheet_format(
        {"columnWidths": [100, 0], "rowHeights": [], "cellFormats": [
            {"location": "a1", "bold": True, "dp": 2, "foreColor": -65536}]})
    assert widths == [100, 0]
    assert fmts["A1"].bold and fmts["A1"].decimals == 2
    assert fmts["A1"].fore == (255, 0, 0, 255)
