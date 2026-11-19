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
| Connection | Connect / log in, keep-alive, read-only mode while ISVS/ISE/VisionView is attached |
| Image | Live result image, zoom/pan, result graphics overlay (Region, Circle, Annulus, Line, Polygon, BlobChain, Text, 4Side, Composite/Masked regions, …), graphics of the selected cells highlighted |
| Spreadsheet | 26 × 600 grid showing results by type (numbers, strings, `#ERR`, controls, status, colour labels), formula bar, cell names panel, sheet formatting from the job (column widths, fonts, colours, decimals) |
| Editing | Write any cell expression (`setCellExpression`), clear, cut/copy/paste with relative reference shifting (`A1` → `A2`, `$A$0` kept), cell names, set values of EditInt/EditFloat/EditString/CheckBox/ListBox controls |
| Graphics editing | Drag-edit EditRegion, EditCircle, EditAnnulus, EditLine, EditPoint and EditPolygon cells on the image (`beginEdit` / `setCellValue` / `endEdit`) |
| Functions | Searchable catalog of ~230 spreadsheet functions with parameter lists, Insert Function dialog, F1 opens the local ISVS help page for the function in the cell (when ISVS is installed) |
| Jobs | New job; open/save job **on the device**; **open a `.jobx` from the PC** (upload) and **save the active job as `.jobx` on the PC** (download) |
| Sensor | Online/offline, live video, manual trigger, load a BMP/JPEG/PNG as the current image |

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
Generate it on a Windows PC with ISVS installed, then copy the file to other machines (e.g.
Ubuntu) if needed:

```bash
python tools/build_catalog.py      # optional arg: path to "...\In-Sight Vision Suite Editors\In-Sight\In-Sight <ver>"
```

Without it the app works normally; only the function list is empty.

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
  sheet.py         spreadsheet model + view (clipboard)
  graphics.py      In-Sight graphic objects -> Qt items
  editors.py       interactive graphic editors
  image_view.py    image + overlay + editor host
  catalog.py       function catalog; data/functions.json
  dialogs.py       connect, insert function, set value, device files
  main_window.py   the application window
  devtools/fake_insight.py   fake device for tests
```

## Limitations (public HMI API)

* **Spreadsheet jobs only.** EasyBuilder jobs are not supported.
* Function **property sheets** (the per-tool dialogs in ISVS) are not available through the API;
  arguments are edited as text in the formula bar. The catalog gives parameter names.
* Training UIs that ISVS implements in its own editor (PatMax pattern training dialogs, OCR font
  training, **Edge AI labelling**) are not part of the public API.
* Cell formatting is read-only (there is no API to set fonts/colours/widths).
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
