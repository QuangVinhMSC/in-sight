# Insight Studio

A cross-platform (Windows / Ubuntu) **spreadsheet job editor for Cognex In-Sight** vision
systems, built with PySide6 on the public **In-Sight HMI API** that ships with the In-Sight Web
SDK. It talks to the device the same way the SDK samples do (CogSocket over a WebSocket at
`ws://<device>/ws` plus plain HTTP for images and job uploads), so no Cognex binaries are needed
on the PC.

> Not affiliated with or endorsed by Cognex. In-Sight is a trademark of Cognex Corporation.

## What it does

| Area | Features |
| --- | --- |
| Look | Modelled on the In-Sight Vision Suite 26.1 Spreadsheet: dark theme, session tab `<job>@<sensor>`, File/Sensor/View/Help menus, the ISVS toolbar blocks with the same tooltips and shortcuts (File, Sensor, Control, Image Display, Cell Formatting, Cell Dependency, Cell Editing + formula bar), yellow message banner, Functions / Acquisition / Job Validation and Record/Playback / Charts / System Health dock tabs, `Total` + Online/Offline status box. Commands the HMI API cannot do are shown disabled with the reason in the tooltip |
| Connection | Connect / log in, keep-alive, read-only mode while ISVS/ISE/VisionView is attached |
| Image | Spreadsheet grid **overlaid on the image** (default) or split view (Change Split, Shift+F7), grid transparency ±, Show Grid (Shift+F6) for pixel values under the mouse (`Approximate (R,G,B)@(x,y) = …`, exact at 1:1), Zoom In/Out/1:1/Fill/Fit, Rotate Image, Show Image Saturation (≤5 blue, ≥240 red), Text Scale Mode, Grid Size; live result image, result graphics overlay (Region, Circle, Annulus, Line, Polygon, BlobChain, Text, 4Side, Composite/Masked regions, …), graphics of the selected cells highlighted |
| Spreadsheet | 26 × 600 grid showing results by type (numbers, strings, `#ERR`, controls, status, colour labels), formula bar with name box (cell names list) and Accept/Cancel, sheet formatting from the job (column widths, fonts, colours, decimals) |
| Editing | Write any cell expression (`setCellExpression`), clear, copy/paste with relative reference shifting (`A1` → `A2`, `$A$0` kept; cell states copied too), Cut + Paste moves cells (references follow), Insert/Delete cells, rows and columns (references, names, cell states and control values follow), Undo/Redo (Ctrl+Z / Ctrl+Y) of everything written to the sheet, Find/Replace (Ctrl+F), Hide/Unhide rows and columns (view only), Insert Absolute/Relative Reference (Ctrl+Shift+A / R) in cell selection mode, cell names, set values of EditInt/EditFloat/EditString/CheckBox/ListBox controls |
| Graphics editing | Drag-edit EditRegion, EditCircle, EditAnnulus, EditLine, EditPoint and EditPolygon cells on the image (`beginEdit` / `setCellValue` / `endEdit`) |
| Functions | Functions panel and Insert Function dialog (Ctrl+Shift+F) as in ISVS: the toolbox category tree (Edge AI, Vision Tools ▸ Bead … Pattern Match, Mathematics ▸ Logic …) with icons, ~560 functions, a filter, and the description of the selected category/function from the local ISVS help; double-click or drag a function onto a cell to insert it. A function with a property sheet is written with default arguments (image `$A$0`, zero fixture, region centred on the image) and its property sheet opens — Cancel empties the cell again, OK is one Undo step; other functions go into the formula bar. Picking a tool from the completion list does the same. Function-name completion while typing (Ctrl+Space lists all; functions used in the job are offered even without the catalog); F1 opens the local help page |
| Property sheet | ISVS-style property sheet for a tool cell (double-click a training tool such as TrainPatMaxRedLine / EdgeAI*, or Insert Function (Ctrl+Shift+F) / right-click ▸ Edit Function… on a cell whose function has one): parameters grouped as in the help (Fixture, Region, …) with spin boxes, check boxes and choice lists, linked control cells edited live, Train/Button cells pressed, linked Edit graphics edited on the image, cell references picked from the sheet, parameter descriptions from the local help; OK keeps, Cancel restores |
| Jobs | New job; open/save job **on the device**; **open a `.jobx` from the PC** (upload) and **save the active job as `.jobx` on the PC** (download) |
| Sensor | Online/offline, live video, manual trigger, repeating trigger (client-side, 500 ms after each result), open a BMP/JPEG/PNG as the current image, save the displayed image |

### How job files work

`.jobx` files are created **by the device**: the app edits the job live on the camera (or the
In-Sight emulator) and then downloads it with `saveJobData`. The app does not write `.jobx`
files itself, because the device signs them (`Job.json.sig`).

## Install and run

```bash
conda env create -f environment.yml     # creates the "insight-studio" env (Python 3.12, PySide6)
conda activate insight-studio
python -m insight_studio                # or: python -m insight_studio --connect 192.168.0.10
```

Ubuntu: if Qt reports *could not load the Qt platform plugin "xcb"*, install
`sudo apt install libxcb-cursor0`.

### Function catalog (generate once)

The Functions panel / Insert Function dialog read `insight_studio/data/functions.json`. It is
**not in the repository** because it is extracted from Cognex's In-Sight Vision Suite help.
Generate it on a PC with ISVS installed — Windows, or Linux with ISVS running under Wine (the
prefix is found via `$WINEPREFIX`, `~/cognex-wine` or `~/.wine`) — or copy the file from such a
machine:

```bash
python tools/build_catalog.py      # optional arg: path to "...\In-Sight Vision Suite Editors\In-Sight\In-Sight <ver>"
```

Without it the app works normally; only the function list is empty and the property sheet lists
arguments by position. The file holds facts only — names, parameter lists, defaults, ranges and
choices, the toolbox category tree (from the help's table of contents) and help page paths; the
function, category and parameter descriptions are read from the locally installed help when present.

On the device, the Web HMI must be enabled (ISVS ▸ Utilities ▸ HMI Settings). Firmware 22.2+
serves it on port 80 and allows 5 concurrent HMI connections (ISVS counts as one).

### Trying it without a camera

A fake device that speaks the same protocol is included for development. It stores expressions
and evaluates only literals, arithmetic and a few HMI controls — it is not an emulator.

```bash
python -m insight_studio.devtools.fake_insight --port 8080
python -m insight_studio --connect 127.0.0.1:8080
```

To test against real firmware on Windows, start the In-Sight emulator from In-Sight Vision
Suite and connect to `127.0.0.1`.

## Development

```bash
python -m pytest            # unit, protocol and offscreen GUI tests (uses the fake device)
python tools/build_catalog.py   # rebuild insight_studio/data/functions.json from a local ISVS install
```

```
insight_studio/
  cogsocket.py     CogSocket client (QWebSocket): get/put/post/listen, events, timeouts
  device.py        HMI API: connect sequence, session, results, cells, jobs, HTTP
  qtasync.py       tiny awaitable runner on the Qt event loop (async/await without asyncio)
  cells.py         addresses, reference shifting, result formatting, sheet formats
  sheet.py         spreadsheet model + view (clipboard, overlay transparency, grid size)
  workspace.py     grid-over-image (overlay) / split container + pixel value strip
  theme.py         ISVS-like dark palette and style sheet
  icons.py         toolbar icons drawn with QPainter
  graphics.py      In-Sight graphic objects -> Qt items
  editors.py       interactive graphic editors
  image_view.py    image + overlay + editor host; zoom modes, rotation, saturation, text scale
  catalog.py       function catalog; data/functions.json
  dialogs.py       connect, device files
  functions_ui.py  Functions panel and Insert Function dialog
  cell_dialogs.py  Insert / Delete and Find dialogs
  sheet_ops.py     Insert/Delete/Cut move plans, reference rewriting, undo history, find
  main_window.py   the application window
  devtools/fake_insight.py   fake device for tests
```

## Limitations (public HMI API)

* **Spreadsheet jobs only.** EasyBuilder jobs are not supported.
* Function **property sheets** are rebuilt client-side from the help (the API has no property-sheet
  metadata), so short descriptions and live training while the sheet is open differ from ISVS.
* Training UIs that ISVS implements in its own editor (PatMax pattern training dialogs, OCR font
  training, **Edge AI labelling**) are not part of the public API.
* Cell formatting is read-only (there is no API to set fonts/colours/widths); the formatting
  toolbar shows the active cell's format but stays disabled. No comments, IP licensing, charts or
  processing times (`Total` in the status bar) either.
* Acquisition, I/O and communication settings have no HMI API endpoint.
## Tested hardware

| Device | Firmware | HMI API | Result |
| --- | --- | --- | --- |
| IS8902CX (colour, 800×600) | 26.1.0 (3930) | 3.0 | connect/login, results, image (BMP) + graphics/SVG layers, cell expressions/values/names, EditRegion editing (`EditingRegion`), trigger, `.jobx` download and upload — all pass (`tests/test_live.py`) |

Run the live tests against your own device (it must be offline; only scratch cells in rows
590–599 are written and then cleared):

```bash
INSIGHT_HOST=192.168.1.102 python -m pytest tests/test_live.py -v      # PowerShell: $env:INSIGHT_HOST="..."
```

Device notes learned on hardware:
* `saveJobData` renames the active job to the name passed, so the app passes the current name.
* Image URLs are only valid while the session holds that result; images are fetched immediately.
* Structure cells (Image, Time, Patterns…) arrive as strings prefixed with U+2752.
