# Insight Studio — notes for Claude

PySide6 replica of the In-Sight Vision Suite (ISVS) Spreadsheet editor on the public In-Sight HMI API.
Plan and phase status: `docs/isvs-spreadsheet-replica-plan.md` (§7 phases, §8 open questions, §9 survey changes).
ISVS behaviour recorded on Windows: `docs/survey-isvs-windows.md` (screenshots `live/21…130`). Property-sheet data
read in ISVS (parameter lists, integer fields, defaults, choice values, enable rules) lives in
`tools/isvs_sheets.py`; rebuild `insight_studio/data/functions.json` (untracked) with `tools/build_catalog.py`.

## Tests

* `/home/vinhdq/miniconda3/envs/insight-studio/bin/python -m pytest -q --ignore=tests/test_live.py`
  (`conda run` segfaults; the interpreter also segfaults *at exit* after the run — judge by "N passed").
* GUI tests run offscreen against `insight_studio/devtools/fake_insight.py`; make the fake mimic what the
  real camera answers.
* Live tests: `INSIGHT_HOST=192.168.1.102 … pytest tests/test_live.py` (scratch rows 590–599 only).

## Test images

`~/Downloads/*.bmp` — real images, 1920×552, 24-bit BMP (`Image_0002…0005_*.bmp`,
`s1_r15_00045x_*_FAIL.bmp`). Use them for anything that needs image content or a non-800×600 size: load into
the fake device or, offline, into the camera with `InSightDevice.load_image` (HMI `loadImage`), e.g. to train a
pattern, check Maximize Region's W/H order or fixture graphics.

## Camera (IS8902CX, 192.168.1.102, firmware 26.1.0, API 3.0)

* Ask the owner before the first write in a session. Keep it **offline**; never save a job on it, never put it online.
* Back up the active job first (HMI `saveJobData` → local `.jobx`, e.g. `~/Documents/insight-isvs-reference/`),
  work in scratch rows 590–599 and clear them, restore with `loadJobData` at the end.
* `loadJobData` returns HTTP 404 while an editor (ISVS) is attached. Close ISVS with
  `wine taskkill /im Cognex.Explorer.exe` (no `/F`); never `wineserver -k` while it is connected (the camera
  then reports editorAttached for 20+ minutes).
* A refused `setCellExpression` still leaves the text in the cell as `'#Expr…` — restore the cell afterwards. The
  camera also lists such cells as "commented-out" to ISVS (presumably until the job is reloaded); avoid refused writes in tests
  (`tests/test_live.py` makes one on purpose).
* The result's `acqImageView` has an `SVGLayer`: the device's own drawing of the graphics (exact geometry of
  curved regions, fixtures, masks) — use it to check how something is drawn.
* Driving ISVS (Wine, Xephyr `:5`) is slow and holds the editor lock: ask first. On 2026-11-20 the embedded
  Spreadsheet editor took no input inside a WM-less Xephyr, and a name-box jump to row 590 froze its painting —
  see plan §8.11. Capture `:5` with `xwd -root` (packed 24-bit BGR, row pitch 6400). Reference screenshots go to
  `~/Documents/insight-isvs-reference/live/` with the next free number.
