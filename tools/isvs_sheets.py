"""Property sheets as In-Sight Vision Suite 26.1 shows them on the IS8902CX (survey on Windows,
2026-11-20: ``docs/survey-isvs-windows.md`` §1–§4, screenshots ``live/24…97``).

The help's parameter tables do not say which numbers are integers, use other choice values than
the device for some lists (Caliper's ``either`` is 3, not 2) and are parsed into the wrong shape
for several tools (Storage choices as a group, Caliper's Edge Mode, ReadIDMax's symbologies…).
ISVS gets all of this from the vision system. For the sheets the survey recorded, the parameter
list below replaces (``SHEETS``) or corrects (``PATCHES``) what ``build_catalog.py`` parses.

Every leaf: ``name``, ``kind`` (image, event, reference, text, number, bool, enum), ``default``
(the argument text ISVS writes on insert), ``integer`` for numbers, ``options`` for lists.
``ENABLE`` rules: ``{"param": P, "values": [...]}`` (P has one of the values), ``{"param": P,
"not": [...]}``, ``{"all": [...]}``, ``{"any": [...]}``; a parameter is greyed out unless its
rule holds. Choice values marked "?" in comments were not read in ISVS (inferred).
"""

from __future__ import annotations

from typing import Optional


def num(name: str, default, integer: bool = False, lo: Optional[float] = None, hi: Optional[float] = None) -> dict:
    p = {"name": name, "kind": "number", "default": str(default), "integer": integer}
    if lo is not None:
        p["min"] = float(lo)
    if hi is not None:
        p["max"] = float(hi)
    return p


def flag(name: str, default: int) -> dict:
    return {"name": name, "kind": "bool", "default": str(default),
            "options": [{"value": 0, "label": "OFF", **({"default": True} if default == 0 else {})},
                        {"value": 1, "label": "ON", **({"default": True} if default == 1 else {})}]}


def choice(name: str, default: int, options: list[tuple[int, str]]) -> dict:
    return {"name": name, "kind": "enum", "default": str(default),
            "options": [{"value": v, "label": lab, **({"default": True} if v == default else {})}
                        for v, lab in options]}


def text(name: str, default: str = '""') -> dict:
    return {"name": name, "kind": "text", "default": default}


def ref(name: str, default: str = "0") -> dict:
    return {"name": name, "kind": "reference", "default": default}


def event(name: str = "Event", default: str = "0") -> dict:
    return {"name": name, "kind": "event", "default": default}


def keep(name: str) -> dict:
    """The parameter as parsed from the help (its choices are right)."""
    return {"keep": name}


def image(name: str = "Image") -> dict:
    return {"name": name, "kind": "image", "default": "$A$0"}


def group(name: str, children: list[dict]) -> dict:
    return {"name": name, "kind": "group", "children": children}


def fixture() -> dict:
    return group("Fixture", [num("X", 0), num("Y", 0), num("Theta", 0)])


def region(name: str = "Region", w: float = 440, h: float = 320, curve: bool = True) -> dict:
    """A region group; X, Y centre it on an 800×600 image as ISVS does (fixed numbers, not
    scaled to the image: 180,140,440,320 also on the 1920×552 camera image)."""
    kids = [num("X", 0), num("Y", 0), num("Width", w), num("Height", h), num("Angle", 0)]
    kids[0]["default"], kids[1]["default"] = str(int((800 - w) / 2)), str(int((600 - h) / 2))
    if curve:
        kids.append(num("Curve", 0))
    return {"name": name, "kind": "region", "children": kids}


SHOW = [(0, "hide all"), (1, "result graphics only"), (2, "input and result graphics")]
POLARITY = [(1, "black-to-white"), (2, "white-to-black"), (3, "either")]  # either = 3 seen; 1, 2 ?
STORAGE = [(0, "Local Device"), (1, "FTP Server"), (2, "SFTP Server")]

SHEETS: dict[str, list[dict]] = {
    # FindLine($A$0,0,0,0,300,275,200,50,0,0,2,0,25,1,0,3,0)
    "FindLine": [
        image(), fixture(), region("Region", 200, 50),
        choice("Polarity", 2, [(0, "black-to-white"), (1, "white-to-black"), (2, "either")]),
        choice("Find By", 0, [(0, "best score"), (1, "first edge"), (2, "last edge")]),
        num("Accept Thresh", 25, True, 0, 100), flag("Normalize Score", 1), num("Angle Range", 0, True, 0, 10),
        num("Edge Width", 3, True, 1, 50),
        choice("Show", 0, SHOW + [(3, "show all: input, result, and chart")]),
    ],
    # Caliper($A$0,0,0,0,300,275,200,50,0,0,1,1,5,5,2,3,3,10,0)
    "Caliper": [
        image(), fixture(), region("Region", 200, 50),
        choice("Edge Mode", 1, [(1, "Single Edge")]),  # Edge Pair's value was not read
        num("Number to Find", 1, True, 1), num("Minimum Contrast", 5, True, 0, 100),
        num("Thresh: Accept", 5, True, 0, 100), num("Edge Width", 2, True, 1, 50),
        choice("Edge: First", 3, POLARITY), choice("Edge: Second", 3, POLARITY),
        num("Edge Distance", 10, True, 0),
        choice("Show", 0, SHOW + [(3, "show all: input, result, and chart")]),
    ],
    # DetectBlobs($A$0,0,0,0,180,140,440,320,0,0,0,1,-1,0,1,2,1,100,100000,0)
    "DetectBlobs": [
        image(), fixture(), region(), ref("External Region"),
        num("Number to Sort", 1, True, 0, 4096), num("Threshold", -1, True, -1, 255),
        flag("Fill Holes", 0), flag("Boundary Blobs", 1),
        choice("Color: Blob", 2, [(0, "black"), (1, "white"), (2, "either")]),
        choice("Color: Background", 1, [(0, "black"), (1, "white")]),
        num("Area Limit: Min", 100, False, 0, 100000000), num("Area Limit: Max", 100000, False, 0, 100000000),
        choice("Show", 0, SHOW),
    ],
    # FindBlobs(0,3,10,0,0,0,1000,20000,50,1,2,50,0,2,0,1000,10000,50,1,2,50,0)
    "FindBlobs": [
        ref("Blobs"), num("Number to Find", 3, True, 1, 4096), num("Accept Thresh", 10, False, 0, 100),
        group("Angle", [num("Angle", 0), num("Range", 0), num("Weight", 0)]),
        group("Area", [num("Area", 1000), num("Range", 20000), num("Weight", 50)]),
        group("Elongation", [num("Elongation", 1), num("Range", 2), num("Weight", 50)]),
        group("Holes", [num("Number", 0), num("Range", 2), num("Weight", 0)]),
        group("Perimeter", [num("Perimeter", 1000), num("Range", 10000), num("Weight", 50)]),
        group("Spread", [num("Spread", 1), num("Range", 2), num("Weight", 50)]),
        choice("Show", 0, SHOW[:2]),
    ],
    # ReadIDMax($A$0,0,0,0,180,140,440,320,0,0,0,1,1,1,0,1,1,1,0,…,0,1,1,1,1,1,0,1,0,1,0,1,3,7,0,0,2,0,2,0,0,0,1,0,2,0,0,0,0,0)
    "ReadIDMax": [
        image(), fixture(), region("Region", curve=False),
        choice("Advanced Decode Mode", 0, [(0, "IDMax"), (1, "IDQuick")]),
        flag("Enable Training", 0),
        group("1D Symbologies", [flag(n, d) for n, d in (
            ("Code 128", 1), ("Code 39", 1), ("Interleaved 2 of 5", 1), ("Pharmacode", 0), ("UPC/EAN", 1),
            ("Code 93", 1), ("Codabar", 1), ("MSI", 0), ("Code 25", 0), ("PDF 417", 0), ("DataBar", 0),
            ("DataBar Limited", 0), ("DataBar Expanded", 0), ("EAN.UCC Composite", 0), ("POSTNET", 0),
            ("PLANET", 0), ("Japan Post", 0), ("Australia Post", 0), ("UPU", 0), ("Intelligent Mail Barcode", 0))]
            + [num("1D Maximum Results", 1, True, 1)]),
        group("2D Symbologies", [
            flag("Data Matrix", 1), num("DM Maximum Results", 1, True, 1), flag("QR Code", 1),
            num("QR Maximum Results", 1, True, 1), flag("MaxiCode", 0), num("Maxicode Maximum Results", 1, True, 1),
            flag("Aztec Code", 0), num("Aztec Maximum Results", 1, True, 1), flag("DotCode", 0),
            num("DotCode Maximum Results", 1, True, 1)]),
        group("Decode Settings", [
            choice("Perspective Distortion", 3, [(3, "Moderate")]),  # Minimal / Severe: values not read
            choice("QR Mode", 7, [(1, "QR Model 1"), (2, "QR Model 2"), (3, "QR Models 1 and 2"), (4, "Micro QR"),
                                  (5, "Micro QR and QR Model 1"), (6, "Micro QR and QR Model 2"),
                                  (7, "All QR Modes")]),  # help order; only 7 read
            flag("Ignore Polarity", 0), flag("Allow Flexible Grid Size", 0),
            choice("Symbol Damage", 2, [(2, "Moderate")]),  # Extreme: value not read
            flag("Checksum", 0),
            choice("Polarity", 2, [(0, "Black"), (1, "White"), (2, "Auto")]),  # only Auto = 2 read
            flag("Omnidirectional", 0),
            choice("Sort Mode", 0, [(0, "None")]),  # other values not read
            flag("Allow Identical 1D Symbols", 0), flag("Expand UPC-E", 1), flag("Rectangular Extension", 0),
            num("Minimum Decodes Before Output", 2, True, 1)]),
        choice("Verification Mode", 0, [(0, "None")]),
        text("Trucheck Settings", "0"),
        num("Timeout", 0, True, 0),
        flag("Show Decoded Result", 0),
        choice("Show", 0, SHOW),
    ],
    # Button("",-1)
    "Button": [text("Name"), choice("Event", -1, [(-1, "None")])],
    # EditMaskedRegion($A$0,0,0,0,1,1,1,1,1,1,1,"",0)
    "EditMaskedRegion": [image(), fixture()] + [flag(n, 1) for n in (
        "Add Masks", "Remove Masks", "Edit Masks", "Move", "Size", "Rotate", "Bend")]
        + [text("Name"), choice("Show", 0, [(0, "hide all"), (1, "input graphics only")])],
    # EditCompositeRegion($A$0,0,0,0,1,1,1,1,1,"",0)
    "EditCompositeRegion": [image(), fixture()] + [flag(n, 1) for n in (
        "Add Subregions", "Remove Subregions", "Edit Subregions", "Move Entire Composite", "Rotate")]
        + [text("Name"), choice("Show", 0, [(0, "hide all"), (1, "input graphics only")])],
    # EditPolygon($A$0,0,0,0,1,1,1,1,1,1,"",0)
    "EditPolygon": [image(), fixture()] + [flag(n, 1) for n in (
        "Add Points", "Remove Points", "Move Points", "Move Entire Polygon", "Scale", "Rotate")]
        + [text("Name"), choice("Show", 0, [(0, "hide all"), (1, "input graphics only")])],
    # EditPolylinePath($A$0,0,0,0,1,1,1,1,1,1,"",0)
    "EditPolylinePath": [image(), fixture()] + [flag(n, 1) for n in (
        "Add Points", "Remove Points", "Move Points", "Move Entire Polyline", "Scale", "Rotate")]
        + [text("Name"), choice("Show", 0, [(0, "hide all"), (1, "input graphics only")])],
    # sheets read in ISVS (live/84…93), opened on an empty cell and cancelled: argument order from the
    # help's syntax line (WriteData lists Data Format before Append on the sheet)
    "WriteData": [
        text("Data"), event("Event", "$A$0"), choice("Storage", 0, STORAGE),
        text("Server"), text("User Name"), text("Password"), flag("Block Execution", 0),
        num("Timeout", 5000, True, 0), text("File Path"), text("File Name"), flag("Append", 1),
        choice("Data Format", 0, [(0, "TXT"), (1, "HTML"), (2, "XML"), (3, "CSV"), (4, "JSON"), (5, "No Type")]),
        flag("Enable File Cleanup", 0), num("Minimum Free Space %", 0, False, 0, 100),
        num("Desired Free Space %", 50, False, 0, 100),
    ],
    "WriteImage": [
        image(), event("Event", "0"), choice("Storage", 0, STORAGE + [(3, "TCP Server")]),
        text("Server"), text("User Name"), text("Password"), flag("Block Execution", 0),
        num("Timeout", 5000, True, 0), text("File Path"), text("File Name"),
        choice("File Type", 0, [(0, "BMP"), (1, "JPEG"), (2, "PNG")]),
        choice("Image Resolution", 0, [(0, "Full")]),  # other values not read
        num("Max Append Value", 999, True, 0), flag("Reset", 0),
        choice("Overlay Graphics", 1, [(0, "OFF"), (1, "SVG Overlay"), (2, "Render on Image")]),
        flag("Enable File Cleanup", 0), num("Minimum Free Space %", 0, False, 0, 100),
        num("Desired Free Space %", 50, False, 0, 100),
    ],
    "ImportData": [
        event("Event", "0"), choice("Storage", 0, STORAGE), text("Host Name"), text("User Name"),
        text("Password"), text("File Path"), text("File Name"),
    ],
    "ExportData": [
        event("Event", "0"), choice("Storage", 0, STORAGE), text("Host Name"), text("User Name"),
        text("Password"), text("File Path"), text("File Name"), ref("Data to Export"),
    ],
    # Filter: no External Region row (live/94); Filter Type values from the help (0 … 26, 16 unused)
    "Filter": [
        image(), fixture(), region("Region", curve=False),
        keep("Filter Type"),  # the choices parsed from the help (0 … 26, 16 unused)
        num("Kernel Rows", 3, True, 1, 25), num("Kernel Columns", 3, True, 1, 25),
        flag("Auto Threshold", 1), num("Threshold", 128, True, 0, 255),
        num("Min", 128, True, 0, 255), num("Max", 128, True, 0, 255),
        num("Gain", 1, False, 0, 10), num("Smoothness", 1, True, 1, 4),
        choice("Show", 0, [(0, "hide all"), (1, "result graphics only"), (2, "input graphics only")]),
    ],
}

# Corrections to a parsed parameter list ("Group/Child" addresses a group's field).
PATCHES: dict[str, dict[str, dict]] = {
    "TrainPatMaxRedLine": {
        "Coarse Granularity": {"integer": False}, "Fine Granularity": {"integer": False},
        "Feature Threshold": {"integer": False}, "Timeout": {"integer": True},
    },
    "FindPatMaxRedLine": {
        "Pattern": {"kind": "reference", "default": "0"},
        "Find Region/Width": {"default": "440"}, "Find Region/Height": {"default": "320"},  # help: 320×440
        "Number to Find": {"integer": True}, "Accept Threshold": {"integer": False},
        "Contrast Threshold": {"integer": False}, "XY Overlap": {"integer": False},
        "Timeout": {"integer": True},
        "Find Tolerances/Angle Start": {"default": "-15"}, "Find Tolerances/Angle End": {"default": "15"},
        "Find Tolerances/Scale Start": {"default": "100"}, "Find Tolerances/Scale End": {"default": "100"},
        "Advanced Settings/Use Coarse Percentage": flag("Use Coarse Percentage", 0),
        "Advanced Settings/Coarse Accept Percentage": num("Coarse Accept Percentage", 60),
    },
    "EditInt": {"Min": {"integer": True}, "Max": {"integer": True}},
}

# Expressions ISVS wrote on insert (formula bar, survey §3) — the catalog's default must match.
ISVS_DEFAULTS = {
    "TrainPatMaxRedLine": "TrainPatMaxRedLine($A$0,0,0,0,180,140,440,320,0,0,0,0,0,1,1,4,1,20,0,0,0,0)",
    "FindPatMaxRedLine": "FindPatMaxRedLine($A$0,0,0,0,180,140,440,320,0,0,0,0,1,50,0,1,0,0,-15,15,100,100,70,0,60,5000,0)",
    "Caliper": "Caliper($A$0,0,0,0,300,275,200,50,0,0,1,1,5,5,2,3,3,10,0)",
    "DetectBlobs": "DetectBlobs($A$0,0,0,0,180,140,440,320,0,0,0,1,-1,0,1,2,1,100,100000,0)",
    "FindLine": "FindLine($A$0,0,0,0,300,275,200,50,0,0,2,0,25,1,0,3,0)",
    "FindBlobs": "FindBlobs(0,3,10,0,0,0,1000,20000,50,1,2,50,0,2,0,1000,10000,50,1,2,50,0)",
    "ReadIDMax": "ReadIDMax($A$0,0,0,0,180,140,440,320,0,0,0,1,1,1,0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,"
                 "0,1,0,1,0,1,3,7,0,0,2,0,2,0,0,0,1,0,2,0,0,0,0,0)",
    "Button": 'Button("",-1)',
    "EditMaskedRegion": 'EditMaskedRegion($A$0,0,0,0,1,1,1,1,1,1,1,"",0)',
    "EditCompositeRegion": 'EditCompositeRegion($A$0,0,0,0,1,1,1,1,1,"",0)',
    "EditPolygon": 'EditPolygon($A$0,0,0,0,1,1,1,1,1,1,"",0)',
    "EditPolylinePath": 'EditPolylinePath($A$0,0,0,0,1,1,1,1,1,1,"",0)',
}

_FTP = {"param": "Storage", "values": [1, 2]}
_LOCAL = {"param": "Storage", "values": [0]}
_CLEANUP = {"all": [_LOCAL, {"param": "Enable File Cleanup", "values": [1]}]}
_KERNEL_TYPES = [1, 3, 4, 5, 7, 14, 17, 18, 19, 20, 21, 26]  # help: "This operation enables the Kernel Rows…"
_THRESHOLD_TYPES = [0, 13, 25]  # Binarize, Greyscale Distance, Threshold Range

ENABLE: dict[str, dict[str, dict]] = {
    "TrainPatMaxRedLine": {
        "Coarse Granularity": {"param": "Auto Select Coarse", "values": [0]},
        "Fine Granularity": {"param": "Auto Select Fine", "values": [0]},
    },
    "FindPatMaxRedLine": {"Coarse Accept Percentage": {"param": "Use Coarse Percentage", "values": [1]}},
    "Caliper": {"Edge: Second": {"param": "Edge Mode", "not": [1]},
                "Edge Distance": {"param": "Edge Mode", "not": [1]}},
    "ReadIDMax": {
        "Ignore Polarity": {"param": "Enable Training", "values": [1]},
        "Allow Flexible Grid Size": {"param": "Enable Training", "values": [1]},
        "Maxicode Maximum Results": {"param": "MaxiCode", "values": [1]},
        "Aztec Maximum Results": {"param": "Aztec Code", "values": [1]},
        "DotCode Maximum Results": {"param": "DotCode", "values": [1]},
        "DM Maximum Results": {"param": "Data Matrix", "values": [1]},
        "QR Maximum Results": {"param": "QR Code", "values": [1]},
        "Trucheck Settings": {"param": "Verification Mode", "values": [2]},  # TruCheck (SBG) = 2 ?
    },
    # Timeout stayed greyed for FTP/SFTP, also with Block Execution ticked (live/87)
    "WriteData": {"Server": _FTP, "User Name": _FTP, "Password": _FTP, "Block Execution": _FTP,
                  "Timeout": {"param": "Storage", "values": []},
                  "Enable File Cleanup": _LOCAL, "Minimum Free Space %": _CLEANUP, "Desired Free Space %": _CLEANUP},
    "WriteImage": {"Server": {"param": "Storage", "values": [1, 2, 3]}, "User Name": _FTP, "Password": _FTP,
                   "Block Execution": {"param": "Storage", "values": [1, 2, 3]},
                   "Timeout": {"param": "Storage", "values": [3]},
                   "File Path": {"param": "Storage", "values": [0, 1, 2]},
                   "Enable File Cleanup": _LOCAL, "Minimum Free Space %": _CLEANUP, "Desired Free Space %": _CLEANUP},
    "ImportData": {"Host Name": _FTP, "User Name": _FTP, "Password": _FTP},
    "ExportData": {"Host Name": _FTP, "User Name": _FTP, "Password": _FTP},
    "Filter": {
        "Kernel Rows": {"param": "Filter Type", "values": _KERNEL_TYPES},
        "Kernel Columns": {"param": "Filter Type", "values": _KERNEL_TYPES},
        "Auto Threshold": {"param": "Filter Type", "values": _THRESHOLD_TYPES},
        "Threshold": {"any": [{"all": [{"param": "Filter Type", "values": _THRESHOLD_TYPES},
                                       {"param": "Auto Threshold", "values": [0]}]},
                              {"param": "Filter Type", "values": [23]}]},  # Sharpen uses Threshold (help)
        "Min": {"param": "Filter Type", "values": [2, 24, 25]},  # Clip, Stretch, Threshold Range
        "Max": {"param": "Filter Type", "values": [2, 24, 25]},
        "Gain": {"param": "Filter Type", "values": [23]},
        "Smoothness": {"param": "Filter Type", "values": [23]},
    },
}
