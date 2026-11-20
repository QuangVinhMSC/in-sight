# Plan: a faithful In-Sight Vision Suite Spreadsheet replica

Status: investigation complete; **phases 1 (look & layout) and 2 (grid fidelity) done** (2026-11-19),
**phases 3 (cell operations), 4 (functions) and 5 (property sheet fidelity) done** (2026-11-20), phases 6–8
to do. The open ISVS questions of phases 3–5 were answered by a survey of ISVS on Windows (2026-11-20,
[survey-isvs-windows.md](survey-isvs-windows.md), screenshots `live/21…130`) and the code was corrected to
match ([§9](#9-isvs-survey-on-windows-2026-11-20--what-changed)).

Goal: make Insight Studio's spreadsheet editor match the **In-Sight Vision Suite (ISVS) 26.1
Spreadsheet** as closely as the public SDK allows — same layout, toolbars, menus, dialogs,
keyboard shortcuts and cell behaviour. Everything the SDK can do is in scope; anything it cannot
do is listed in [§6](#6-set-aside-not-possible-with-the-public-sdk) and set aside. The rest of
ISVS (home screen, utilities, EasyBuilder) only needs to be "good enough".

## 0. Sources

| Source | What it gave |
| --- | --- |
| **ISVS 26.1 running live** (under Wine, connected to the IS8902CX on a scratch job, 2026-11-19) | exact toolbar contents and tooltips/shortcuts, right-click menu and submenus, Insert / Delete / Format Cells (4 tabs) / Row Height / Column Width / Insert Function / New Job dialogs, the TrainPatMaxRedLine Property Sheet (rows, groups, menus, enable rules, descriptions) and Interactive Graphics Mode. Screenshots: `~/Documents/insight-isvs-reference/live/` |
| **ISVS help 26.1.0.133** (`…/In-Sight 26.1.0/Docs/Help_InSight`) | UI reference for every panel/dialog, the full toolbox tree (`~/Documents/insight-isvs-reference/help/help-toc-26.1.txt`), per-function parameter tables (already parsed into `insight_studio/data/functions.json` by `tools/build_catalog.py`), dialog screenshots for the parts not driven live (`…/help/*.png`) |
| **In-Sight HMI API** (protocol 3.x PDF) + **HMI Developers Guide** | what a client can read/write — the boundary of this plan |
| **In-Sight Platform API** PDF | audit log, certificates, firmware, backup only — nothing for the spreadsheet |
| **Native Mode commands** (help) | get/set values, files, jobs, events — nothing beyond the HMI API for editing |
| **ISVS 26.1 on Windows** (survey 2026-11-20, [survey-isvs-windows.md](survey-isvs-windows.md)) | property-sheet region editing, bend/rotate maths, integer fields, default expressions, choice values and enable rules of 20 tools, masked/composite/polygon IGM menus, Script / FormatString / snippet / Cell Names / Cut-Copy-Delete-Undo semantics. Screenshots `live/21…130`, files in `~/Documents/insight-isvs-reference/survey-2026-11/` |
| Cognex .NET HMI sample (`milk-production-line/base/SampleCode`) | confirms button press = `setCellValue(loc, "1")`, graphic edit = `beginEdit` + `setCellValue(region)` |
| A `.jobx` file | tar archive: plaintext `Job.json` (acquisition + HMI settings) and an **obfuscated** sheet blob. Decoding the blob would be reverse engineering → not used |

Items marked **(help)** below were taken from the help/screenshots and were not driven live;
check them against ISVS when implementing.

## 1. What the SDK can and cannot do (the boundary)

| Area | HMI API | Notes |
| --- | --- | --- |
| Cell expressions | ✅ `getCellExpressions`, `setCellExpression` | one call per cell; batch by looping. Rewriting a cell keeps its name, cell state and control value; a cell written from empty starts at the default value; clearing drops name and state. An invalid expression is refused (error −1610357770) but may be stored as text `'#…` (device, 2026-11-20) |
| Cell names | ✅ `getAllCellNames`, `setCellName` | `setCellName(loc, "")` removes a name; a name in use gets a `_1` suffix (case-sensitive); expressions **cannot** refer to a cell by its name (refused) |
| Control values / graphics | ✅ `setCellValue(s)`, `beginEdit`/`endEdit` | buttons: value `"1"` |
| Cell state (Enabled / Disabled / Conditional) | ✅ `getCellCondition`, `setCellCondition` | `""` enabled, `"0"` disabled, a cell reference (`Z594`, `$Z$594`) conditional; setting `"1"` reads back `""`; result cells carry `disabled: true` (device, 2026-11-20) |
| Cell data beyond the expression (trained patterns) | 👁 `dataId` in `getCellExpressions(range, true)` | cannot be copied to another cell → moving such a cell loses the training (warned) |
| Results, cell types, errors, graphics, images | ✅ `result`, `queryCellResults`, views/graphics layers, HTTP images | |
| Sheet format (column widths, row heights, fonts, colours, decimals, alignment) | 👁 **read only** (`getSheetFormat`) | no setter |
| Comments | ❌ | not exposed at all |
| IP protection | ❌ | |
| Jobs | ✅ new, load (device), save (device), list, download (`saveJobData`), upload (`loadJobData`) | upload is refused while an editor (ISVS) is attached |
| Online/offline, trigger, live video, load image | ✅ | |
| Results queue | ✅ `rq` | |
| Job validation | ✅ run / cancel / state | configuration itself is in the job, not editable |
| EasyView, Custom Views, HMI pages | ✅ `setEasyView`, `setCustomViewList`, `setHmiPages` | |
| Acquisition settings (exposure, trigger, …) | ❌ (read from downloaded `Job.json` only) | |
| Property-sheet metadata, short descriptions, live "train while sheet open" | ❌ | metadata comes from the help (catalog); training only via the job's own Train button |
| Execution timing per cell / total | ❌ | HmiResult carries no timing |
| Chart data (Caliper, FindLine, histograms…) | ❌ | |

## 2. Main window — target layout

Reference: `live/01-editor-with-job.png`, `live/02-editor-new-job-overlay.png`, help `sheet_UI_interface`.

```
┌ In-Sight Vision Suite │ ⌂ │ [Unsaved Job]@IS8902CX-d350e6 ×                       – ▢ × ┐
│ File  Sensor  View  Help                                                         admin │
│ [New][Open][Save▾] │ [Trigger][Repeat][Live] │ ▷ Online ▾                              │
├──────────────────────────────────────────────────────────────┬──────────────────────────┤
│ toolbar row 1: image/edit/view tools                          │ Functions            ▾   │
│ toolbar row 2: font, size, B I, align, decimals, colours, dep.│ Filter: [          ] [⧉] │
│ toolbar row 3: $ ▦ fx ▢ ⤢ │ state comment name │ ✓ ✗ │ [A0▾] = [formula……] if 1 │ ▸ Edge AI                │
├──────────────────────────────────────────────────────────────┤ ▸ Vision Tools …          │
│   A  B  C …  (grid overlaid on the image, semi-transparent)   │                          │
│ 0 ❒Image                                                      │ ─ description pane ─     │
│ 1                                                             │ All functions            │
├──────────────────────────────────────────────────────────────┤                          │
│ Record/Playback (filmstrip)                              ˅ × │                          │
│ [⚙][📁▾][Image][10⇕][Bmp▾] ●            Delay(ms)[200] ▶1 ▶ ⟳ ■ ⏮ ⏪ ⏩ ⏭ │ Functions│Acquisition│Job Validation │
│ Record/Playback │ Charts │ System Health                                               │
├────────────────────────────────────────────────────────────────────────── Total: 0.1 ms │ Offline ┤
```

* **Dark theme** (ISVS colours: window #3c3c3c, panels #464646/#505050, text #e0e0e0, accent
  yellow #ffd800 for the active tab/headers, selection blue). Grid cells light grey with dark
  grid lines; the active row/column headers are **yellow**; active cell outlined black.
* **Overlay view is the default**: the spreadsheet grid is drawn semi-transparently *over* the
  image (the image shows through where it lies under columns F–M at 100 %). *Change Split*
  (Shift+F7) toggles to the split view (what Insight Studio has today). *Show Grid* (Shift+F6)
  hides the grid → image only ("Show Pixel Values mode", pixel value in the status line under the
  image: `Approximate (R,G,B)@(x,y) = r,g,b`, exact at 1:1). Transparency ± buttons. Zoom
  combo (100 %) = grid/image zoom.
* **Selecting a cell/parameter with a region graphic hides the grid** and shows the image with
  that graphic in edit form (see §4.9).
* Session tab title `[Unsaved Job]@<device>` / `<job>@<device>`, user name at top right.
* **Yellow banner** under the toolbar for job messages (e.g. "Cannot view EasyBuilder job. Please
  convert to Spreadsheet job.", "The current job was loaded with commented-out cells… J2, J5").
* Right dock tabs: **Functions | Acquisition | Job Validation** (+ EasyView, Snippets, Profile Job
  when opened from View). Bottom dock tabs: **Record/Playback | Charts | System Health**.
* Status bar: `Total: x ms` (tooltip acquisition/inspection/queue — not available, see §6) and an
  **Online/Offline** box.

### 2.1 Toolbars (exact, from live tooltips — `live/04…06`)

| Group | Buttons (tooltip / shortcut) |
| --- | --- |
| File | New Job (Ctrl+N) · Open Job (Ctrl+O) · Save Job (Ctrl+S) ▾ (Save Job As F12) |
| Sensor | Trigger (F5) · Repeating Trigger · Live Video · ▷ Go Online (Ctrl+F8) ▾ |
| Control | Open Image (Ctrl+Shift+O) · Save Image As (Ctrl+Shift+S) · Cut (Ctrl+X) · Copy (Ctrl+C) · Paste (Ctrl+V) · Undo (Ctrl+Z) · Redo (Ctrl+Y) · Find (Ctrl+F) ▾ |
| Image display | Zoom In (Shift+Add) · Zoom Out (Shift+Subtract) · Zoom 1:1 (Shift+Multiply) · Zoom to Fill · Zoom to Fit · Rotate Image (Shift+Divide) · Show Image Saturation (Ctrl+Shift+B) · Change Split (Shift+F7) · Increase Transparency · Decrease Transparency · Show Grid (Shift+F6) · Show Graphics (Ctrl+Shift+G) · Text Scale Mode: Fixed / Scale With Image / Shrink Only · Grid Size [100 %▾] |
| Cell formatting | Font [Arial▾] · Size [9▾] · Bold (Ctrl+B) · Italic (Ctrl+I) · Align Left/Center/Right · Increase Decimal · Decrease Decimal · Background Color ▾ · Foreground Color ▾ |
| Cell dependency | Increase Dependency Levels (F11) · Decrease (Shift+F11) · Reset (Ctrl+F11) · Show Dependency Errors Only (Alt+F11) · Go To First Error (Ctrl+Shift+F11) |
| Cell editing | Insert Absolute Reference (Ctrl+Shift+A) · Insert Relative Reference (Ctrl+Shift+R) · Insert Function (Ctrl+Shift+F) · Edit Cell Graphic (F9) · Maximize Cell Region (Ctrl+Shift+M) · Edit Cell State · Insert Comment… · Insert Cell Name… · Accept Changes (Return) · Cancel Changes (Escape) · Name box [A0▾] · `=` · Formula bar · cell-state indicator (`if 1`) |

Disabled-state rules: icons grey out when not applicable (Paste with empty clipboard, Undo
without history, Accept/Cancel outside editing, Edit Cell Graphic without a graphic, Comment /
Cell Name / Cell State on empty cells…). Toolbars are movable blocks.

### 2.2 Menus

* **File** (help): New Job Ctrl+N · Open Job Ctrl+O · Save Job Ctrl+S · Save Job As F12 · Import
  Snippet Alt+I · Export Snippet Alt+E · Convert to Spreadsheet Job.
* **Sensor** (help): Trigger F5 · Repeating Trigger · Live Video · Online Ctrl+F8 · Result Queue
  Settings… · Job Status Settings… · Custom View Settings… · Discrete I/O Settings….
* **View** (help): Snippets · Profile Job · EasyView · Record/Playback · Charts.
* **Help**: help for the spreadsheet / function (F1 opens the function's page).

### 2.3 Right-click menu on a cell (live — `live/07`, `live/08`)

```
Cut / Copy / Paste
──
Insert…            Delete…            Clear ▸ (All | Contents | Formats | Comments)
──
Insert Function… / Edit Function…     (Edit when the cell holds a function with a property sheet)
Insert Absolute Reference…            Insert Relative Reference…
Insert Comment… / Edit Comment…       Insert Cell Name…      Insert Getters
──
Cell Graphic…      Cell State…        IP Licensing ▸ (Protect Cells | Unprotect Cells)
──
Format ▸ (Cell(s) | Row Height… | Column Width… | Hide | Unhide)
──
Import Snippet…    Export Snippet…
──
Publish to EasyView ▸ (Selected | Named)
──
Create Custom View
```

## 3. Grid behaviour

* 26 columns A–Z × 600 rows 0–599; default column width **64 px**, row height **20 px**; per
  job widths/heights from the sheet format (read only).
* Cell display by result type (as today), plus ISVS details to add:
  * **HMI controls are live widgets in the cell** (CheckBox, ListBox combo, EditInt/EditFloat
    spinners, EditString box, Button) — click to operate, not a dialog.
  * Structures shown as `❒Image`, `❒Patterns`… in blue-ish text; numbers right-aligned with
    the format's decimals (default 3); `#ERR` with tooltip = error string.
  * **Named cell**: blue triangle bottom-right, tooltip shows the name.
  * **Comment**: coloured triangle top-right (flag colour) — *display not possible, §6*.
  * Disabled (cell state) cells: greyed.
* Selection: click, drag, Shift+click/arrows, whole row/column via headers; active row/column
  header highlighted yellow.
* **Typing in a cell starts editing**; while typing a name, a dark dropdown of matching
  **function names only** (no signatures) appears (help image `function-typing.png`). Picking a
  function **with a property sheet opens the property sheet** immediately.
* Enter/Escape = Accept/Cancel; the formula bar mirrors the cell.
* **Cell selection mode** (Ctrl+Shift+A / R, property sheet, cell state, FormatString, EasyView,
  custom view, recording watch cell): grid shown without image, target range drawn with a red
  outline + handles, destination cell light red; double-click or Enter accepts, Esc cancels.
* **Copy/Paste** with relative/absolute/mixed shifting (done), Cut/Paste keeps references
  pointing at the moved cells, cell states copy like references.
* **Insert / Delete dialogs** (live — `live/09`, `live/10`): radio buttons *Shift cells right*,
  *Shift cells down* (default), *Entire row*, *Entire column* (Delete: *left*, *up*…). Implement
  client-side: compute the moved block, rewrite every expression in the sheet whose references
  point into the moved area (same engine as paste), move names and cell states, write with
  `setCellExpression`. Formats cannot be moved (read-only) → warn once.
* **Clear ▸** All / Contents / Formats / Comments → Contents works; All = Contents (+ name, state);
  Formats/Comments disabled (§6).
* **Hide / Unhide rows/columns**: view-only in the client (not stored in the job — note it).
* **Dependency view** (F11 …): draw precedents/dependents for the selected cell as arrows
  (green dependents, blue precedents, yellow/red when in error, dot at the precedent end,
  range outlines, red “?” for references to empty cells, dashed magenta border for dead-end
  cells), levels ±, errors-only, go to first error. Computable from expressions + results.
* **Find – Inspection** (help image): Find [history▾] · Replace [history▾] · Find Next ·
  Find Previous · Replace · Replace All · Search Order [Rows First / Columns First] · Look in
  [Expressions / Values / Comments / Names] · Match case · Match entire. Replace only offline.
  (Comments: not available.)
* **Undo/Redo**: client-side history of expression/name/state/value writes (ISVS has it).
* Drag a function from the Functions panel onto a cell = insert it (opens property sheet).
* Drag an image file onto A0 = load image.

## 4. Dialogs and popups — exact contents

### 4.1 New Job confirmation (live `live/00`)
Message box "Are you sure you wish to clear all data from the current job?" [Yes] [No], then a
modal "Initializing New Job" progress box.

### 4.2 Insert – Inspection / Delete – Inspection (live)
Title `Insert - Inspection` / `Delete - Inspection` (the Windows survey shows " - "; the ❒ in the Wine
screenshots was a missing glyph — all dialog titles corrected 2026-11-20). Four radio buttons
(see §3), OK / Cancel. 300×173.

### 4.3 Format Cells – Inspection (live `live/11`, `live/12`) — 350×400, resizable
* **Font**: Font (text box + list), Font style (Regular / Italic / Bold / Bold Italic), Size
  (box + list 8…72), Foreground color (named colour combo, default *Navy*), Background color
  (default *Transparent*), ☐ Default font, Preview box ("AaBbCcYyZz").
* **Alignment**: group *Text Alignment* — Horizontal [General▾], Vertical [General▾].
* **Number**: Decimal Places [3 ⇕].
* **Graphics** (cells with a graphic): Font (Arial / Times New Roman / Courier New) + Size list,
  Line Width [2 ⇕].
* OK / Cancel.
SDK: values can be **shown** (from the sheet format) but not written → dialog opens read-only
with a note, toolbar formatting buttons disabled (§6).

### 4.4 Row Height / Column Width (live `live/13`)
`Row Height: [20 ⇕] px` / `Column Width: [64 ⇕] px`, OK / Cancel (220×113). Read-only (§6) —
or a client-side view setting, clearly labelled.

### 4.5 Insert Function – Inspection (live `live/14…16`) — 674×432
Left: tree with icons — All ▸ Edge AI, Vision Tools (Bead, Blob, Color, Edge, Histogram, ID,
Image, InspectEdge, OCV/OCR, Pattern Match), Geometry, Graphics, Mathematics, Robotics String
Functions, Text, Coordinate Transforms, Input/Output, Clocked Data Storage, Vision Data Access,
White Balance, Structures, Scripting, Arrays and Objects (full tree:
`help/help-toc-26.1.txt`, "In-Sight Toolbox"). Right: functions of the selected category with
icons. Bottom: title, **bold short signature** (`TrainPatMaxRedLine(Image, Fixture, Region, ...)`)
and one-line description ("Extracts and trains a pattern… Returns a Patterns structure.");
category selected → category description ("Functions that extract and process image features."),
Insert disabled. [Insert] [Cancel]. F1 = help for the selection. Insert → property sheet when the
function has one, else the name goes into the cell.
Data needed: category per function and icons → extend `build_catalog.py` with the TOC tree;
one-line descriptions from the MicroContent pages; icons: draw our own per category.

### 4.6 Property Sheet (live `live/17…20`, survey `live/24…97`) — `Inspection - Property Sheet - <Function>`, 426×720
* Menu **Edit**: Graphic (F9), Maximize Region (Ctrl+Shift+M). **Insert**: Function
  (Ctrl+Shift+F), Absolute Reference (Ctrl+Shift+A), Relative Reference (Ctrl+Shift+R).
  **Help**: Property Sheet Help (F1).
* Toolbar: $ (abs ref), ▦ (rel ref), fx, Edit Graphic, Maximize Region, ?.
* Rows: label column, value column, `= result` column. Selected row: yellow label, value in a
  yellow-bordered box, references in blue (`$A$0`) with `= ❒Image`.
  Groups (Fixture, Pattern Region, Pattern Origin…) show `(0,0,0)` and expand with ⊞/⊟ to
  spin boxes with **3 decimals** (`180.000`). Booleans = **checkboxes**; enums = combo +
  `= n`; integers without decimals (Timeout `0`); floats 3 decimals (Feature Threshold
  `20.000`); event parameters = a **push button with the parameter name** (`Train Event`).
* **Enable rules**: dependent parameters grey out (Coarse/Fine Granularity disabled while Auto
  Select Coarse/Fine is checked). Needs per-function rules → derive from help text ("Disable it
  to enable this parameter") where possible, else a small hand-written table.
* Description pane (bottom): parameter name + short description
  ("Reference to a cell containing an Image structure. Default = $A$0." /
  "Region of interest: {X, Y, Width, Height, Angle, Curve}.") — ISVS's short strings are not in
  any shipped file; use the help's first sentence + default/range (as now).
* **Region parameters (survey):** while the sheet is open its region is drawn on the image (red outline,
  X/Y arrows, centre cross-hair, no handles), the sheet stays and so does the grid. Only **F9** (Edit ▸
  Graphic) edits it — a click or double-click on the row does not: the sheet hides, handles appear, the
  status line under the image reads `Location=306,78 Size=440×320 Rotation=39.0° Curve=-49.3°` (while
  dragging only the quantity that changes), ✓/✗ are enabled; **Enter** puts the new values into the sheet,
  **Esc** discards them, a click outside the region does nothing. Changed rows get a "reset to original
  value" icon (not done). The formula bar changes only on OK.
* Insert ▸ Function / Absolute / Relative Reference are always enabled; **Function on a number row switches
  it to expression mode** (text box with the value, `= value`, fx pressed) — no function list.
* Train Event button with Train Event = 0: nothing happens (no message).
* Red ⓘ/! next to OK when the function returns #ERR (tooltip = error string). OK / Cancel.
* Opens automatically after inserting a function; Insert Function on a cell with a function
  opens the sheet instead ("Edit Function…").
Implemented in phase 5 (`insight_studio/property_sheet.py`, see §7).

### 4.7 Cell State - Inspection (help image; survey live/121…123 — implemented, §7 phase 6)
"Cell Range: C7", group *Cell State*: ◉ Enabled ○ Disabled ○ Conditionally Enabled
(→ ◉ Absolute ○ Relative, Cell Reference [   ] [Select Cell…]). OK / Cancel.
SDK ✅ (`setCellCondition`). Formula-bar indicator shows the state (`if 1`).

### 4.8 Edit Comment (help image) — **set aside** (§6)
"Comment for cell E4:" multi-line box "(press Ctrl+Enter to enter multiple lines)", Flag color
[Red▾], OK / Cancel; 256 chars.

### 4.9 Interactive Graphics Mode (live `live/20`, `live/28…39`, `live/98…112`, help igm-*)
Survey 2026-11-20 (implemented in `editors.py`):
* **Rotation** turns the region about its centre; Angle grows clockwise on screen; angles are shown 0…360.
* **Bend** keeps the region's centre and its chord direction: Angle + Curve/2 stays constant, X/Y follow
  (checked to 3 decimals against the three ISVS samples). Down = positive. It stops when the inner edge
  reaches a radius of 1 px: |Curve| ≤ W/(H/2+1) rad (±156.6° for 440×320). Curve ≈ 2 × the pointer's angle
  seen from the centre against the chord (74.2° at the old corner position; our model gives 72°).
* Dragging a corner of a curved region changes all six values.
* **Double-click on a control cell** (Edit* graphic) enters IGM; F9 too. The property sheet comes from the
  cell menu's "Edit Function…".
* **EditMaskedRegion:** right-click "Add Mask" / "Delete Mask"; a new mask is a narrow full-height band at the
  **left end** of the ROI, next to the masks already there (not at the click). Default ROI 180,275,440×50.
  In the survey a drag on a mask did not move it (perhaps it must be selected first — not determined);
  Insight Studio keeps mask dragging/resizing along the ROI.
* **EditCompositeRegion:** "Add Subregion ▸ Annulus/Circle/Polygon/Region", "Remove Subregion" (greyed with
  one subregion), "Subregion Operation ▸ Add/Subtract" (greyed for the first subregion). A subregion added in
  IGM is the first one at 80 % size, centred on it, operation **Subtract**; the sheet's Regions tab "Add…"
  adds with operation Add at X 740, Y 116 (not done: the Regions tab). Enter selects the whole composite
  instead of leaving IGM; ✓ leaves (not done: Enter accepts here). 33rd subregion: not determined.
* **EditPolygon:** magenta vertices, dashed bounding box (`Size=441×321` for 180…620 — pixels counted), a
  rotation handle below the box, no scale handles. A click on an edge does **not** add a point: right-click
  an edge → "Add Point" (at the click) / "Remove Point" (greyed); on a vertex both are enabled;
  Shift+Alt+click removes a vertex.

Before the survey:
Grid hidden; graphic drawn red with: corner handles (magenta squares), X/Y scan-direction
arrows, **bend handle (middle of the right edge), rotation handle (middle of the bottom edge)** —
help image `RegionLegend.png` (items 3 = Bend, 4 = Rotation). Mouse cursors change per handle;
Enter/Accept, Esc/Cancel. Types: Region (with bend → arc/annulus), Circle, Annulus, Line,
Point, Polygon (add point on edge, Shift+Alt click removes), **CompositeRegion** (right-click:
Add Subregion / Remove Subregion / change operation), **MaskedRegion** (up to 99 masks, Add/Delete
Mask). Also for **literal** region arguments inside a tool (fixture-relative) — written back into
the expression. Today only Region/Circle/Annulus/Line/Point/Polygon on Edit* cells.

### 4.10 Insert Cell Name… / name box (help + live tooltip + survey `live/119…120`)
Name rules: starts with a letter, `[A-Za-z0-9_]`, 1–127 chars, not cell-address-like, unique
case-insensitively (suffix `_1`). Invalid → name box outlined red and reverted. Empty + Enter
removes the name.
Survey: the context menu item is "Insert Cell Name..." ("Edit Cell Name..." on a named cell) and opens
**"Cell Names"**: a table *Name | Location* of **all** names of the job, buttons [Add] [Rename] [Delete]
[Auto Name] [OK] [Cancel]. A new row for the current cell is put in edit mode with the suggestion `Result`
(then `Result01`). Invalid names (`1abc`, `A1`) are **silently reverted**. [Add] hides the dialog for cell
selection ("Click to insert reference E38"), Enter returns. A duplicate is accepted in the dialog but the
cell gets `myval_1` (the device's suffix). Named cells: blue triangle bottom-right. Formulas keep cell
references (not rewritten to names).

### 4.11 Insert Getters
Right-click on a tool → writes the tool's Vision Data Access result table to the right
(header row of labels + Get… formulas, e.g. EdgeAIClassify: Health, Num Class, Index, Label,
Num Images, Score, Is Unclassified). Refuses when there is no room. Data: the "Vision Data
Access functions … automatically inserted" tables in each tool's help page → add to the catalog.
SDK ✅ (just expressions).

### 4.12 Edit Script (help + survey `live/113…116`) — Script function editor
**Survey:** inserting Scripting ▸ Script opens "Inspection - Edit Script" directly (menus Script, Edit;
"Arguments:" box, default `10`; JavaScript editor pre-filled with a template — `"use strict";`, a `Script`
constructor with `this.total = 0`, `module.exports = Script;`, `run`, optional `save`/`load`; "Last
Result:"; "Console Log:" with [Clear]; [Test Script] [Save] [Cancel]). After Save the cell expression is
only **`Script(10)`**: the source is **not in the expression** — it is cell data the HMI API cannot read or
write → Edit Script is set aside (§6); a Script cell can be shown and its arguments edited.

Before the survey:
Arguments text box, JavaScript code editor (syntax highlight, line numbers, undo/redo, find),
Last Result pane, Console Log; menus Script (Test Script, Import Script…, Export Script…,
Revert Changes, Close) and Edit. **Open question:** where the script source lives (cell
expression vs. hidden cell data) — check `getCellExpression` on a Script cell. Test Script
(running JS) can only be emulated by writing and reading back the cell.

### 4.13 FormatString dialog (help + survey `live/117…118`) — SDK ✅ (it only builds an expression)
**Survey:** title "Inspection - Property Sheet - FormatString"; group "Starting/Ending" (Leading Text,
Trailing Text, Terminators `None` / `Carriage Return (CR)` / `Line Feed (LF)` / `CR+LF`); "☐ Use Delimiter"
with ◉ Standard [Comma▾] / ○ Other [ ]; "Arguments" table *Include Label | Label (`Label`) | Cell | Data Type
| Decimal Places | Fixed Width | Field Width (8, greyed unless Fixed Width) | Padding (`Leading Spaces`)*,
[Add] (cell selection; Enter returns; new row Floating Point, 3 decimals) [Delete] [Up] [Down]; "Output: N
characters" preview; OK / Cancel. Data types: Integer, Unsigned Integer, Integer (hex), Integer (HEX),
Integer (Octal), Floating Point, Scientific Notation, Character, String. Expression for Leading `A`, Comma,
CR+LF, items B44 (2 decimals) and C35 (String):
`FormatString("%s%.0s%.2f,%.0s%s%s\r\n","A","Label",$B$44,"Label",$C$35,"")` — the leading text is the first
`%s` argument, each item is `%.0s` (its label, hidden unless Include Label) + its conversion, the delimiter
sits between items, the trailing text is the last `%s` argument, the terminator is literal in the format.

Before the survey:
Leading/Trailing text (30), Terminators (None/LF/CR/CR+LF), Use Delimiter (Standard: Comma,
Space, Tab, Semicolon, Underscore / Other), item list with Add (cell selection mode) / Delete /
Move Up / Move Down, per item Label (12), Include Label, Cell, Data Type (Integer, Unsigned,
hex, HEX, Octal, Floating Point, Scientific, Character, String), Decimal Places (0–6, default 6),
Fixed Width (Field Width 1–30, default 8), Pad (Leading/Trailing Spaces…). Need the expression
syntax FormatString produces → read from a job that uses it (`S38 FormatString("%s%s","","")`
in the test job suggests a format-string form).

### 4.14 Other function-specific editors
* Charts panel (Caliper, FindLine, histograms…): no data via SDK → §6.
* OCRMax Auto-Tune, Edge AI labelling/training web apps, PatMax training preview → §6.

### 4.15 Panels
* **Functions panel** — header "Functions ▾", Filter box (+ clear button), category tree with
  icons, description pane at the bottom ("All functions" / category / function text).
  Drag to grid. ✅ (catalog + TOC tree).
* **EasyView panel** (help image) — Open (WebHMI), Add Cells (cell selection, named cells only),
  Add Group, Clear, –, ↑/↓, grab handles; columns Caption / Editable. ✅ `setEasyView`.
* **Custom View** (help) — list with Add/Remove/↑↓, Select Cells, Select Region, X/Y/W/H,
  Size To Contents, Show Image, Show Graphics; double-click to rename. ✅ `setCustomViewList`.
* **Snippets panel** — Cognex snippets + Custom Snippets folder; drag into grid; Import/Export
  Snippet (.cxdx, Alt+I / Alt+E). Snippet = block of cells → ✅ via expressions. **Survey:** a `.cxdx` is
  a tar with `version` (`2`), `range` (`B44:B47`), an **obfuscated** `snippet.json` and `snippet.json.sig`
  (sample in `~/Documents/insight-isvs-reference/survey-2026-11/`) — like the `.jobx` sheet blob, decoding
  it would be reverse engineering → our own JSON format only (no `.cxdx` import/export). Save dialog
  "Export Snippet", default folder Documents ▸ In-Sight Vision Suite ▸ In-Sight ▸ Snippets.
* **Record/Playback (Filmstrip)** — frames with name+counter, settings dialog (folder, prefix,
  index, type, watch-cell sort OK/NG), folder, name box, counter, format (bmp/jpg/png), record,
  delay (ms, 0–60000, default 200), playback buttons (first frame, next, loop, stop, first,
  previous, next, last), blue = selected, yellow = last played, right-click Delete Frame.
  ✅ PC-side: record = save result images; play = `loadImage` while offline.
* **Result Queue Settings** (Sensor menu) — enable, mode (Pass and Fail / Fail / Pass /
  Separate), queue size, pass/fail size. ✅ `rq`.
* **Job Validation panel** — run / cancel / show result ✅; configuring variants/tests ❌.
* **Profile Job panel** — per-cell timings ❌; dependency table ✅ (computable).
* **Acquisition panel** — ❌ (no acquisition API); could show read-only values from `Job.json`
  of a downloaded job.
* **System Health** — out of scope (minimal).

## 5. Gap analysis — Insight Studio today vs. target

| Feature | Today | To do |
| --- | --- | --- |
| Dark ISVS look | default Qt style | theme (palette + QSS), ISVS-like icons |
| Overlay grid over image | split only | overlay mode default, transparency, Show Grid, Change Split |
| Toolbars | one simple toolbar | 4 toolbar blocks per §2.1 with shortcuts, enable rules |
| Formula bar | name box + text | name box as combo (names list), `=`, Accept/Cancel buttons, cell-state indicator |
| In-cell controls | text display | live widgets (checkbox, combo, spin, button) |
| Name/comment markers | none | blue triangle for names (comments ❌) |
| Context menu | small | full §2.3 |
| Insert/Delete cells/rows/cols | ❌ | client-side reference rewrite |
| Format Cells / row / col dialogs | ❌ | read-only views |
| Insert Function dialog | flat list | category tree + icons + description, opens property sheet |
| Autocomplete | names + signatures | names only, dark list; opens property sheet on pick |
| Property sheet | functional | exact styling, enable rules, region → image, open on insert |
| Interactive graphics | 6 types on Edit* cells | + literal regions in tools, composite/masked regions, bend handle, scan arrows |
| Cell state | ❌ | dialog + indicator |
| Find/Replace | ❌ | dialog |
| Dependency view | ❌ | arrows overlay |
| Undo/Redo | ❌ | client history |
| Insert Getters | ❌ | catalog data + writer |
| FormatString / Script dialogs | ❌ | dialogs |
| Snippets | ❌ | panel + own format (+ .cxdx later) |
| Filmstrip | ❌ | panel |
| EasyView / Custom View / Result Queue | ❌ | panels/dialogs |
| Pixel values / saturation / rotate / zoom modes | partial (zoom) | add |

## 6. Set aside (not possible with the public SDK)

* Writing **cell formats** (fonts, colours, alignment, decimals, row heights, column widths),
  Clear Formats, moving formats on insert/delete. Formats are shown read-only.
* **Comments** (read or write), comment flags, Find in comments, Clear Comments.
* **IP Licensing** (Protect/Unprotect cells).
* **Acquisition panel** settings (exposure, gain, trigger, illumination, white balance…).
* Property-sheet **live training** ("training occurs while the property sheet is open"), the
  short parameter descriptions that ISVS gets from the device, **Charts** data, **Profile Job
  timings**, status-bar **processing time** breakdown.
* **Edge AI** labelling/training apps, **OCRMax Auto-Tune**, PatMax training dialogs.
* Job Validation **configuration**, System Health details, EasyBuilder.
* Reading the obfuscated sheet inside `.jobx` files and `.cxdx` snippets (would be reverse engineering).
* **Edit Script**: the JavaScript source is not part of the cell expression (`Script(10)`), so it can neither
  be read nor written (survey 2026-11-20).
* **Acquisition panel** (A0's Insert Function shows it in ISVS): no acquisition API.

## 7. Implementation phases

Each phase ends with offscreen GUI tests against the fake device (extend `fake_insight.py` as
needed) and one check on the camera (with the owner's OK — use a scratch job, back up first).

1. ✅ **Look & layout** — dark theme, ISVS toolbars/menus/shortcuts (§2.1–2.2), session tab title,
   banner, right/bottom dock tabs, status bar, overlay grid over image + Change Split / Show Grid
   / transparency / zoom modes. *Accept:* screenshot side-by-side with `live/02` matches layout.
   Done: `theme.py`, `icons.py` (own artwork), `workspace.py`, toolbars in `main_window.py`,
   tests in `tests/test_layout.py`. Also done early: Rotate, Show Saturation (≤5 / ≥240 per help),
   Text Scale Mode, Grid Size, Save Image As, client-side Repeating Trigger (500 ms, help default),
   Insert Function on a function cell → property sheet, Open/Save Job dialogs with a *PC…* choice.
   Placeholders (disabled, tooltip "Not implemented yet") for everything of later phases;
   Record/Playback and Job Validation docks show a placeholder note, Acquisition and Charts docks
   say why they are unavailable, System Health shows device info. Notes: the user's old window
   layout is ignored once (state version 2); the editor toolbars are fixed rows, not movable blocks.
2. ✅ **Grid fidelity** — in-cell live controls, name markers, #ERR tooltips, header highlighting,
   selection model, typing starts edit, autocomplete as names list, Accept/Cancel, full context
   menu skeleton (unsupported items disabled with a tooltip explaining why).
   Done: `cell_controls.py` (delegate drawing Button/CheckBox/ListBox/EditInt/EditFloat/EditString/
   edit-graphic buttons/Status/MultiStatus, name triangle), `SheetHeader` + control mouse handling,
   value box and list popup in `sheet.py`, context menu `MainWindow.build_cell_menu`, tests in
   `tests/test_grid.py`. Behaviour chosen: click operates Button/CheckBox/list/spin arrows; edit boxes
   open on a second click or double-click; typing/F2 edits the expression. "Set Value…" dialog removed.
   The HMI API gives no error text, so `#ERR` tooltips say the reason is not reported. Not done:
   opening the property sheet after an autocomplete pick (phase 4).
3. ✅ **Cell operations** — Insert/Delete dialogs (reference rewrite engine, names, states), Clear ▸,
   Cut semantics, Undo/Redo, Find/Replace, Hide/Unhide (view only), cell selection mode
   (shared component used by everything below).
   Done: `sheet_ops.py` (location mappings for Insert/Delete/Cut, `rewrite_references`, `plan_move`,
   `History`, find/replace helpers), `InSightDevice.write_cells` / `get_cell_conditions`, `cell_dialogs.py`
   (Insert/Delete `❒Inspection`, Find - Inspection), cell selection mode in `SheetView` + `ImageSheetArea`,
   tests `tests/test_sheet_ops.py`, `tests/test_cell_ops.py`; checked on the IS8902CX (rows 590–599 of a
   scratch job: insert row, undo, cut/paste move — names, states, EditInt value and references followed).
   Behaviour chosen (items marked *survey* checked against ISVS on 2026-11-20, the rest not verified):
   * every write goes through one serialised writer (snapshot → write → refresh) and is one Undo step;
     Undo covers expressions, names and cell states written by this client (incl. Insert/Delete,
     Paste, Clear, Replace All, a whole Property Sheet session); in-cell control values and graphic edits
     are not undone (*survey*: ISVS does not undo an EditInt spin either). History is cleared when another
     job is loaded or on disconnect.
   * Cut works like Excel: the cells get a dashed outline and move on Paste (references to them follow,
     references to overwritten cells become `#REF`); Escape removes the mark. *Survey:* ISVS marks the cut
     cells (marching ants) and clears them only on Paste, references follow (`B1*2` → `D1*2`), name and
     state move along, Paste is then greyed (once only). Overwritten cells: not checked.
   * Insert/Delete rewrite references to moved cells everywhere (also `$A$1`, also cell-state
     references); an Insert that would push non-empty cells off row 599 / column Z is refused. Moved
     control cells get their value written back; cells with a `dataId` and cell formats cannot move → a
     confirmation lists them. **Corrected (*survey*):** references to *deleted* cells are left as they are —
     no `#REF` (ISVS: C1 = `D1*2` still reads `D1*2` after column D is deleted and then uses the cell that
     moved into D1). Deleting a row: not checked.
   * Copy copies cell states (shifted like references) **and names** (*survey*: the copy of `Result` is
     named `Result_1`; the device adds the suffix). Corrected 2026-11-20.
   * Clear ▸ All = Contents (the device drops name and state with the contents); Formats/Comments disabled.
   * Insert Absolute/Relative Reference on an empty cell writes the reference; while editing (formula
     bar or cell) it is inserted at the cursor; on a cell with contents it is appended in the formula bar.
     Ranges (`A1:B3`, `$A$1:$B$3`) are supported. The Property Sheet `$A$1`/`A1` buttons use the same mode
     (the sheet hides while picking, as in ISVS).
   * Find: Look in Expressions / Values (grid text) / Names; Comments disabled. Replace works offline on
     Expressions and Names (rename), Replace replaces in the found cell and finds the next one.
   * Hide/Unhide only with entire rows/columns selected; view only, reset when another job is loaded.
4. ✅ **Functions** — catalog: TOC category tree, one-line descriptions, getters tables, enable rules;
   Functions panel (tree, filter, description, drag & drop); Insert Function dialog; Edit
   Function… → property sheet; open property sheet after insert/autocomplete.
   Done: `tools/build_catalog.py` now walks the help's own TOC (`Data/Tocs/is_usp_sheet*.js`) below
   "In-Sight Toolbox" → `categories` tree named as ISVS shows it (top level renamed, " Functions"
   dropped) and per function `paths`; functions documented in "Function | Description" tables (Math,
   Logic, String, Vision Data Access pages…) are included → 567 functions (was 231; Abs, If, GetX…
   were missing). Also `getters` (only 4 tool pages list them: EdgeAIClassify/Segment, ReadIDMax,
   Fixtures — the rest must come from elsewhere in phase 6) and `enable` rules (hand-written table
   for TrainPatMaxRedLine, ValidateIDData; the Filter/WriteData/WriteImage/ImportData/ExportData rules
   need parameters the help tables do not parse yet — the builder warns). Advanced AI and Focus are kept
   but hidden (ISVS did not list them for the IS8902CX). Descriptions are still not stored: `catalog.
   describe_function/describe_category` read the first sentences (or the function's table row) from
   the local help at run time. `functions_ui.py`: `FunctionsPanel`, `InsertFunctionDialog` (674×432,
   "All" + tree, list of the subtree, title / bold short signature / description, Insert disabled on a
   category, F1 = help); category icons in `icons.py` (own artwork). Drag & drop from the panel onto a
   cell (`SheetView.functionDropped`). Tests `tests/test_functions.py` (skip without the generated catalog).
   Behaviour chosen (check against ISVS / the camera):
   * Inserting a function with a property sheet (dialog, panel double-click or drop, picking it from the
     completion list when it is the whole cell) writes a **default expression** and opens the property
     sheet; Cancel restores the previous cell, OK is one Undo step. Defaults: template if known, image
     `$A$0`, fixture 0, help defaults incl. "(0 to 100; default = 5)", choices' default, events `$A$0`
     (train/reset/clear events `0`), references `0`. **Corrected (survey):** regions are ISVS's *fixed*
     numbers — 440×320 (200×50 for FindLine/Caliper) centred on 800×600, also on the camera's 1920×552
     image — not scaled to the image; the 20 sheets read in ISVS come from `tools/isvs_sheets.py`, and the
     defaults of all 12 tools whose expressions were copied in ISVS are reproduced exactly (test
     `test_default_expressions_are_what_isvs_writes`), incl. FindPatMaxRedLine, Caliper, DetectBlobs,
     FindBlobs, ReadIDMax, `Button("",-1)` and the Edit* controls with Name `""` and Show `0`. When a
     parameter has no known default or the device refuses it, the name goes to the formula bar as before.
   * "Edit Function…" / Insert Function on a function cell → property sheet only when the function has
     one (or is unknown to the catalog); `Abs(A1)` gets the Insert Function dialog. **Corrected (survey):**
     on A0's `AcquireImage()` Insert Function brings up the Acquisition tab of the right dock.
   * *Survey:* a function is listed under every category it belongs to (GetX under Blobs and CircleFit) —
     as the catalog's `paths` already do.
5. ✅ **Property sheet fidelity** — styling, enable rules, region selection → image mode, Maximize
   Region, literal-region interactive editing (fixture transform), Edit Graphic for all types incl.
   composite/masked regions, error mark.
   Done: `property_sheet.py` — title `Inspection - Property Sheet - <Function>` (was `❒`, a Wine missing glyph), 426×720; menus Edit (Graphic F9,
   Maximize Region Ctrl+Shift+M), Insert (Function Ctrl+Shift+F, Absolute Reference Ctrl+Shift+A, Relative
   Reference Ctrl+Shift+R), Help (Property Sheet Help F1) and the toolbar $ ▦ fx graphic maximize ? (new `help`
   icon); selected row = yellow label + yellow-bordered value box, references blue, third column `= ❒Image`,
   lists `= n` (check boxes none), floats with 3 decimals and integers without, event parameters = a button
   named after the parameter, enable rules grey out label and value, red `!` next to OK. `editors.py`
   rewritten — ISVS look (red graphic, magenta handles, X/Y scan arrows), four corners + sides resize, rotation
   about the centre, bend, Region/Circle/Annulus/Line/Point/Polygon (add point on an edge, Shift+Alt+click
   removes), CompositeRegion (right-click Add Subregion ▸ Annulus/Circle/Polygon/Region, Remove Subregion,
   Subregion Operation ▸ Add/Subtract; max 32), MaskedRegion (masks = hatched bands across the ROI, Add Mask /
   Delete Mask, max 99, dotted yellow scan line), PolylinePath (its regions), edit flags from the Editing
   object / result (`move`, `resize`, `rotate`, `bend`, `addRegion`, `removeRegion`, `editRegion`). Main
   window: Maximize Cell Region (toolbar, Ctrl+Shift+M) on Edit cells with a Region. Fake device: EditAnnulus,
   EditPolygon, EditCompositeRegion, EditMaskedRegion. Tests `tests/test_editors.py`, `tests/test_property_sheet.py`.
   Behaviour chosen — camera items **verified on the IS8902CX 2026-11-20** (scratch rows 590–599, device SVG
   layer as reference); the ISVS UI items were checked by the Windows survey the same day (§9):
   * **Corrected (survey):** while the sheet is open its region given by numbers (the selected one, else the
     first) is drawn on the image without handles (centre cross-hair, scan arrows); the grid stays. F9 (Edit ▸
     Graphic) hides the sheet and enters Interactive Graphics Mode with ISVS's status line; Return / ✓ puts the
     numbers into the sheet (which then writes the expression), Escape / ✗ discards; a double-click on a row does
     nothing. On a reference to an Edit graphic cell F9 opens that cell's Interactive Graphics Mode as before. A
     region with cell references is not graphical (help note).
   * **Verified:** the region is drawn in the tool's fixture — image = translate(X, Y) then rotate(Theta) clockwise,
     angles add (`Region($A$0,100,50,30,20,10,200,100,15,0,2)` → origin (112.3, 68.7), edge at 45°; same with the
     fixture as references to numeric cells). Fixtures made of anything else are shown in image coordinates with a
     note. Maximize Region = the whole image in the fixture (angle −Theta), curve 0; on an EditRegion cell
     (0,0,W,H,0,0) with W = image width (x): accepted, covers the 800×600 image and a loaded 1920×552 image.
     The device keeps oversize/negative regions as written (no clamping).
   * **Verified, drawing fixed:** a curved region is an annular sector (`graphics.curve_point`): the Y-axis edge stays
     straight, the centre line keeps the length W, the centre of curvature is at (0, H/2 + W/θ) in region
     coordinates, so the X-axis edge has radius H/2 + W/θ; positive curve bends towards +Y (checked for ±30, ±90,
     120 and with angle 20 against the device's SVG). Handles sit on the curved outline (corners, rotation = middle
     of the bottom arc, bend = middle of the right edge). Bend: the chord from the middle of the left edge to the
     handle makes θ/2 with the X axis (keeps the handle under the mouse; dragging down = positive curve — the
     previous mapping had the sign reversed). Cropping a curved region keeps its centre of curvature. Rotation
     follows the mouse around the region centre. *(How ISVS's own bend/rotate handles react: unverified.)*
   * **Verified:** masks are stored verbatim as Regions (also offset in y, shorter than the ROI, any number); the
     device's default EditMaskedRegion is a 440×50 ROI with one 10-wide full-height mask. The editor now keeps each
     mask's (x offset, width, y offset, height) in ROI coordinates; a new mask spans the ROI's height and is 5 % of
     its width (≥10) centred on the click; full-height masks follow ROI height changes. On a curved ROI the device
     keeps masks as straight Regions (the editor places them along the straight ROI axes).
   * **Verified:** Editing object flags per type (§8.10) — the editor reads them all, and polygons use their own
     `addPoints` / `removePoints` / `movePoints` flags.
   * Integer vs. float spin boxes: **from the catalog** (`integer`, read in ISVS) for the 20 surveyed sheets —
     e.g. FindLine's Accept Thresh is an integer, FindBlobs' a float; otherwise still guessed from the name.
     Group fields can be integers or check boxes too (ReadIDMax's symbologies). A list value without a known
     label is listed by its number.
   * Event button: presses the referenced Button cell(s); with no reference (0) nothing happens (*survey*), the
     tooltip explains. **Corrected (survey):** Insert ▸ Function is enabled on every row; on a spin box / check
     box / list it switches the row to a text box with the value (fx checked), in a text box it picks a function
     and puts `Name()` at the cursor. Restore Default is in the row's right-click menu (not in ISVS's menus).
   * **Enable rules** (survey + help): WriteData, WriteImage, ImportData, ExportData (Storage `Local Device` = 0,
     `FTP Server` = 1, `SFTP Server` = 2, WriteImage also `TCP Server` = 3), Filter (Filter Type × Auto
     Threshold, per-type lists from the help), Caliper (Edge Mode), FindPatMaxRedLine, ReadIDMax. Rules can
     combine conditions (`all` / `any` / `not`).
   * ⊞/⊟ boxes on groups (`property_sheet.ParamTree`), as in live/18; the spin-box arrows of the property sheet are
     now the app-wide style (`theme.STYLESHEET`).
   Not done: ISVS's own short parameter descriptions (§6); the "reset to original value" icon on changed rows;
   EditCompositeRegion's Regions tab and EditPolygon's Points tab; choice values ISVS was not seen to use
   (Caliper's Edge Pair, ReadIDMax's Perspective Distortion / Symbol Damage / Sort Mode / Verification Mode,
   WriteImage's Image Resolution, Button's events — shown by number).
6. **Cell state, names, getters** — Cell State dialog + indicator, Insert Cell Name… dialog and
   name-box rules, Insert Getters. Layouts now known (§4.7 survey, §4.10).
   **Partly done (2026-11-20):** `cell_dialogs.CellStateDialog` ("Cell State - Inspection", Cell Range, Enabled /
   Disabled / Conditionally Enabled with Absolute (default) / Relative, Cell Reference + Select Cell... via cell
   selection mode, OK greyed without a reference; a relative reference is shifted per cell of the range; one Undo
   step), the formula-bar indicator `if 1` / `if 0` / `if <cell>` (read with `getCellCondition`, live/123), and
   `cell_dialogs.CellNamesDialog` ("Cell Names": all names, Name | Location, Add via cell selection mode, Rename,
   Delete, suggested `Result` / `Result01`, invalid names silently reverted, duplicates suffixed by the device;
   "Edit Cell Name…" on a named cell). Auto Name is disabled (its behaviour was not recorded). Tests in
   `tests/test_cell_ops.py`. Still to do: name-box rules, Insert Getters, the results tables. Also: ISVS fills a **results
   table** after OK for tools returning a structure (bold headers in the row above starting one column to the
   right, values in the cell's row: FindPatMaxRedLine `Index X Y Angle Scale Score`, Caliper `Index X0 Y0 X1 Y1
   Score Contrast`, FindLine `X0 Y0 X1 Y1 Score`, ReadIDMax `Index String`, DetectBlobs/FindBlobs `Index X Y
   Angle Color Score Area …`) — the formulas of those cells were not copied (read them next time).
7. **Special editors** — FormatString dialog (expression form now known, §4.13). Edit Script: not possible
   (§6).
8. **Panels** — Filmstrip (record/playback, settings dialog), Snippets (own format, then .cxdx),
   EasyView, Custom View, Result Queue settings, Job Validation run/state, read-only Format Cells /
   Row Height / Column Width, Dependency view (F11 family).

## 8. Open questions to settle on the device (scratch job, with permission)

1. ~~`getCellCondition` / `setCellCondition` string format~~ — answered 2026-11-20, see §1.
2. ~~Where Script source is stored~~ — **answered (survey)**: not in the expression (`Script(10)`), §4.12.
3. ~~FormatString expression form~~ — **answered (survey)**, §4.13.
4. ~~`.cxdx` snippet format~~ — **answered (survey)**: obfuscated + signed, §4.15.
5. ~~Insert Cell Name… dialog layout~~ — **answered (survey)**, §4.10.
6. ~~`loadJobData` while an editor is attached~~ — **answered 2026-11-20**: HTTP 404 confirmed again with ISVS
   attached; `InSightDevice.upload_job` now says "an editor (In-Sight Vision Suite) is attached … Close the editor
   and try again" (fake device mimics it). Closing ISVS with `wine taskkill /im Cognex.Explorer.exe` (no `/F`)
   released `editorAttached` within seconds, twice.
7. ~~Whether `setCellExpression` on a range in one call exists~~ — not in the HMI API; Insert/Delete
   write cell by cell (plus one `getCellCondition` per non-empty cell). Fine for typical jobs; add a
   progress dialog if big sheets turn out slow.
8. ~~Check against ISVS: Cut semantics, references to deleted cells, Copy of states and names, Undo
   scope~~ — **answered (survey)**, §7 phase 3. Still open: references to overwritten cells on Cut + Paste,
   deleting a row.
9. Phase 4 defaults — **camera part answered 2026-11-20** (all 76 generated defaults written to rows 590–592):
   TrainPatMaxRedLine (`❒Patterns`), FindLine (`❒Edges`), Button (`Button($A$0)`) are accepted; 13 were refused,
   FindBlobs among them, because the help parser turned value tables into parameter groups (FindBlobs' relation
   rows, Timer, ReadDiscrete, FormatInputBuffer, Storage…). `catalog.default_expression` now gives no default for a
   group whose children have neither a numeric default nor choices (Fixture X/Y/Theta excepted), for references
   other than regions, and reduces `0xFF0000 (red)` to the number → no refusals left; remaining `#ERR` are expected
   (AutoFocus/GetFocusPosition without a liquid lens, ExtractCalibration, FindCurve on an empty image).
   **A refused `setCellExpression` still writes the text as `'#Expr(…)`** into the cell — the insert flow now puts
   the previous content back before handing the name to the formula bar — and the camera additionally remembers the
   cell as "commented-out" (ISVS shows a yellow bar "The current job was loaded with commented-out cells …" listing
   them) even after the cell is cleared. The saved job (`saveJobData`) is unaffected; the job was reloaded
   afterwards (expected to clear it — not re-checked in ISVS).
   ~~Still open (ISVS): the expressions ISVS writes for FindPatMaxRedLine / Caliper / DetectBlobs, Insert Function on
   A0, VDA categories~~ — **answered (survey)**, §7 phase 4.
10. Phase 5 — **camera part answered 2026-11-20**:
    * `beginEdit` returns `Editing<Kind>` with `data` (the graphic), `title` (= the Name argument), `bounds`
      (image rectangle), `fixture`, `url`, `image`, `view` and flags: EditingRegion `move resize rotate bend`;
      EditingCircle / EditingAnnulus `move resize`; EditingPolygon and EditingPolyline (EditPolylinePath, data =
      CompositeRegion of Regions) `move movePoints addPoints removePoints scale rotate`; EditingCompositeRegion
      `move rotate addRegions removeRegions editRegions` (plural); EditingMaskedRegion `move resize rotate bend
      addRegion removeRegion editRegion` (data = CompositeRegion: ROI first, masks `add: false`). Cell results are
      `HmiButtonResult` with `caption` = the Name argument and no function name → `editors.edit_flags` normalises
      the names, `editors.editing_function` maps the `$type` to the Edit* function (`MainWindow.edit_graphic`).
    * EditMaskedRegion needs 13 arguments (Image, Fixture X/Y/Theta, 7 flags, Name, Show) although the help's
      syntax line has no Theta; 12 are refused. Templates for EditPolygon / EditCompositeRegion / EditMaskedRegion /
      EditPolylinePath added to the builder.
    * Composite round trip (Region with angle, Circle, Annulus, Polygon, curved Region; Add/Subtract) is exact.
      The device accepts 33 subregions — the 32 limit is ISVS's (help note), kept in the editor. Polygons round-trip;
      `length` is recomputed from the points. A CompositeRegion written to EditPolylinePath is kept as written.
    * Masks, fixture, curve, Maximize: see §7 phase 5. The SVG layer of `acqImageView` is the device's own drawing
      (curved regions as SVG arcs, masks hatched, the masked region's scan line dashed yellow along the centre line).
    * Live regression tests in `tests/test_live.py`: `test_editing_objects`, `test_refused_expression_stays_as_text`,
      `test_curved_region_drawn_like_graphics`.
    * ~~Still open (needs ISVS): region editing on selection, bend/rotate handles, integers, Train Event with 0,
      Insert ▸ Function, Storage / Auto Threshold values~~ — **answered (survey)**, §4.6, §4.9, §7 phase 5.
11. Driving ISVS on 2026-11-20 failed. The launcher took clicks, but the embedded Spreadsheet editor (a ProcHost
    child window of another process) received no mouse or keyboard input: no popups, no cell writes, also with
    explicit X focus. A first attempt typed `B590` into the name box and the editor then stopped painting for 5+
    minutes (probably scrolling ~590 rows of in-cell child windows under Wine). Next attempt: run ISVS on the real
    display `:1` (as the 2026-11-19 screenshots were taken) or with a window manager inside Xephyr, stay in the
    top rows of a File ▸ New Job, and never jump far with the name box. §8.2–8.5, 8.8 and the ISVS parts of
    8.9/8.10 are still open. Capture `:5` with `xwd -root` decoded as packed 24-bit BGR (row pitch 6400).
12. Still open after the survey (next time ISVS is at hand): the commented-out-cells bar after a job reload
    (the original job turned out to be an EasyBuilder job); whether a 33rd composite subregion is refused;
    whether a mask can be moved/resized in y; the conditional cell state with a reference; deleting a row; the
    tooltip of the red "!" next to OK; the formulas of the results tables ISVS adds after OK; the missing choice
    values listed in §7 phase 5 "Not done". Note: the camera's job is now named `backup-before-survey.jobx` (same
    content as `NewJob.jobx`, an EasyBuilder job).

## 9. ISVS survey on Windows (2026-11-20) — what changed

| Finding (survey §) | Change |
| --- | --- |
| Region parameter only drawn when selected, F9 edits, sheet hides, Enter → sheet / Esc discards (§1.2–1.3) | `PropertySheet` preview + `regionEditRequested`, `MainWindow._property_sheet_edit_region` / `_end_param_igm`; `GraphicEditor(preview=True)` (no handles, cross-hair) |
| Status line `Location=… Size=… Rotation=… Curve=…`, only the changing part while dragging (§1.2–1.3) | `GraphicEditor.status_text`, `statusChanged`, `end_drag` (ImageView mouse release); also for cell IGM |
| Rotation about the centre, angles 0…360 (§1.4) | `editors.norm_angle` |
| Bend keeps centre and chord, clamp at 1 px inner radius (§1.5) | `RegionShape._bend` / `set_curve`, `editors.max_curve` (test against the ISVS samples) |
| Train Event with 0 does nothing; Insert ▸ Function = expression mode (§1.7–1.8) | `PropertySheet._event_clicked`, `_insert_function`, `_expr_mode` |
| Integer fields, defaults, choice values, enable rules of 20 sheets (§2–§4) | `tools/isvs_sheets.py` (SHEETS, PATCHES, ENABLE, ISVS_DEFAULTS) → `build_catalog.apply_sheets`; `is_integer_parameter` reads `integer`; compound rules in `PropertySheet._rule_holds` |
| Fixed default regions; Name `""`, Show 0; `Button("",-1)` (§3) | `catalog._region_args`, `default_expression` ignores the image size; builder TEMPLATES |
| A0 Insert Function → Acquisition tab (§3) | `MainWindow.insert_function` |
| Masks at the left end; subregions at 80 %, Subtract; first subregion's operation greyed; polygon right-click Add/Remove Point, rotate handle, no click-to-add (§5) | `GraphicEditor.add_mask`, `_new_subregion`, `build_menu`; `PolygonShape` |
| Cell Names / Cell State dialogs, `if 0` indicator (§6.4–6.5) | `cell_dialogs.CellNamesDialog`, `CellStateDialog`; `MainWindow.set_cell_name`, `edit_cell_state`, `_update_state_indicator` |
| Dialog titles use " - " (`Delete - Inspection`, `Inspection - Property Sheet - …`); the ❒ in the Wine screenshots was a missing glyph | `cell_dialogs`, `functions_ui`, `property_sheet` titles |
| Copy copies names (suffix by the device); Delete leaves references to deleted cells (§6.5) | `SheetView.copy_selection`/`paste`, `MainWindow._on_paste`; `sheet_ops.rewrite_references(keep_removed=)` for Delete |
| Script source not in the expression; `.cxdx` obfuscated (§6.1, §6.3) | §6 set aside |
