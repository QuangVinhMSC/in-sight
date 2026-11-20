# Plan: a faithful In-Sight Vision Suite Spreadsheet replica

Status: investigation complete; **phases 1 (look & layout) and 2 (grid fidelity) done** (2026-11-19),
**phases 3 (cell operations), 4 (functions) and 5 (property sheet fidelity) done** (2026-11-20), phases 6–8
to do. Next: camera checks and patches in [handoff-phase5-camera.md](handoff-phase5-camera.md).

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
Title `Insert ❒Inspection` / `Delete ❒Inspection` (❒ = the sheet name glyph). Four radio buttons
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

### 4.6 Property Sheet (live `live/17…20`) — `<sheet> - Property Sheet - <Function>`, 426×720
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
* Selecting a region parameter switches the main view to image + interactive region; double-click
  or F9 enters Interactive Graphics Mode (§4.9).
* Red ⓘ/! next to OK when the function returns #ERR (tooltip = error string). OK / Cancel.
* Opens automatically after inserting a function; Insert Function on a cell with a function
  opens the sheet instead ("Edit Function…").
Implemented in phase 5 (`insight_studio/property_sheet.py`, see §7).

### 4.7 Cell State – Inspection (help image)
"Cell Range: C7", group *Cell State*: ◉ Enabled ○ Disabled ○ Conditionally Enabled
(→ ◉ Absolute ○ Relative, Cell Reference [   ] [Select Cell…]). OK / Cancel.
SDK ✅ (`setCellCondition`). Formula-bar indicator shows the state (`if 1`).

### 4.8 Edit Comment (help image) — **set aside** (§6)
"Comment for cell E4:" multi-line box "(press Ctrl+Enter to enter multiple lines)", Flag color
[Red▾], OK / Cancel; 256 chars.

### 4.9 Interactive Graphics Mode (live `live/20`, help igm-*)
Grid hidden; graphic drawn red with: corner handles (magenta squares), X/Y scan-direction
arrows, **bend handle (middle of the right edge), rotation handle (middle of the bottom edge)** —
help image `RegionLegend.png` (items 3 = Bend, 4 = Rotation). Mouse cursors change per handle;
Enter/Accept, Esc/Cancel. Types: Region (with bend → arc/annulus), Circle, Annulus, Line,
Point, Polygon (add point on edge, Shift+Alt click removes), **CompositeRegion** (right-click:
Add Subregion / Remove Subregion / change operation), **MaskedRegion** (up to 99 masks, Add/Delete
Mask). Also for **literal** region arguments inside a tool (fixture-relative) — written back into
the expression. Today only Region/Circle/Annulus/Line/Point/Polygon on Edit* cells.

### 4.10 Insert Cell Name… / name box (help + live tooltip)
Name rules: starts with a letter, `[A-Za-z0-9_]`, 1–127 chars, not cell-address-like, unique
case-insensitively (suffix `_1`). Invalid → name box outlined red and reverted. Empty + Enter
removes the name. (The *Insert Cell Name…* dialog itself was not captured — capture it.)

### 4.11 Insert Getters
Right-click on a tool → writes the tool's Vision Data Access result table to the right
(header row of labels + Get… formulas, e.g. EdgeAIClassify: Health, Num Class, Index, Label,
Num Images, Score, Is Unclassified). Refuses when there is no room. Data: the "Vision Data
Access functions … automatically inserted" tables in each tool's help page → add to the catalog.
SDK ✅ (just expressions).

### 4.12 Edit Script (help) — Script function editor
Arguments text box, JavaScript code editor (syntax highlight, line numbers, undo/redo, find),
Last Result pane, Console Log; menus Script (Test Script, Import Script…, Export Script…,
Revert Changes, Close) and Edit. **Open question:** where the script source lives (cell
expression vs. hidden cell data) — check `getCellExpression` on a Script cell. Test Script
(running JS) can only be emulated by writing and reading back the cell.

### 4.13 FormatString dialog (help) — SDK ✅ (it only builds an expression)
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
  Snippet (.cxdx, Alt+I / Alt+E). Snippet = block of cells → ✅ via expressions. The `.cxdx`
  format needs a sample exported from ISVS; until then use our own JSON format.
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
* Reading the obfuscated sheet inside `.jobx` files (would be reverse engineering).

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
   Behaviour chosen (not verified against ISVS — check when ISVS is driven again):
   * every write goes through one serialised writer (snapshot → write → refresh) and is one Undo step;
     Undo covers expressions, names and cell states written by this client (incl. Insert/Delete,
     Paste, Clear, Replace All, a whole Property Sheet session); in-cell control values and graphic edits
     are not undone. History is cleared when another job is loaded or on disconnect.
   * Cut works like Excel: the cells get a dashed outline and move on Paste (references to them follow,
     references to overwritten cells become `#REF`); Escape removes the mark.
   * Insert/Delete rewrite references to moved cells everywhere (also `$A$1`, also cell-state
     references); references to deleted cells become `#REF`; an Insert that would push non-empty cells
     off row 599 / column Z is refused. Moved control cells get their value written back; cells with a
     `dataId` and cell formats cannot move → a confirmation lists them.
   * Copy also copies cell states (shifted like references); names are not copied.
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
     `$A$0`, fixture 0, regions centred on the current image (reproduces ISVS's
     `(180,140,440,320,0,0)` for TrainPatMaxRedLine on 800×600), help defaults incl. "(0 to 100; default
     = 5)", choices' default, events `$A$0` (train/reset/clear events `0`), references `0`. When a
     parameter has no known default (76 of 220 tools have a full default today; e.g. FindPatMaxRedLine's
     Pattern, Caliper, DetectBlobs) or the device refuses it, the name goes to the formula bar as before.
   * "Edit Function…" / Insert Function on a function cell → property sheet only when the function has
     one (or is unknown to the catalog); A0's `AcquireImage()` and `Abs(A1)` get the Insert Function dialog.
5. ✅ **Property sheet fidelity** — styling, enable rules, region selection → image mode, Maximize
   Region, literal-region interactive editing (fixture transform), Edit Graphic for all types incl.
   composite/masked regions, error mark.
   Done: `property_sheet.py` — title `Inspection ❒Property Sheet ❒<Function>`, 426×720; menus Edit (Graphic F9,
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
   Behaviour chosen (check against ISVS / the camera):
   * Selecting a region parameter given by numbers (or one of its fields) hides the grid and makes the region
     editable on the image right away, with the sheet still open (live/20 shows it so); dragging updates the
     fields and writes the expression (debounced); another row brings the grid back. F9 / double-click on such a
     row just shows it again; on a reference to an Edit graphic cell they open that cell's Interactive Graphics
     Mode as before (Return/Escape). A region with cell references is not graphical (help note).
   * The region is drawn in the tool's fixture: Fixture X/Y/Theta as numbers or references to numeric cells;
     otherwise it is shown in image coordinates with a note. Maximize Region = the whole image expressed in the
     fixture (angle −Theta), curve 0; on an EditRegion cell the value becomes (0,0,W,H,0,0).
   * Bend handle: moving it from the middle of the right edge to the top/bottom corner sets curve +90/−90°
     (drawing of curved regions is still an approximation). Rotation turns about the region centre.
   * Masks are read back as bands (offset along the ROI, width) and written as Regions with the ROI's height
     and angle; a new mask is 5 % of the ROI wide (≥10) centred on the click.
   * Integer vs. float spin boxes are guessed from the parameter name (Timeout, Number…, Index…) — ISVS gets the
     type from the device.
   * Event button: presses the referenced Button cell(s); with no reference (0) it explains that training while
     the sheet is open is not available. Insert ▸ Function is enabled while a text value has focus and puts
     `Name()` at the cursor. Restore Default moved to the row's right-click menu (not in ISVS's menus).
   Not done: ISVS's own short parameter descriptions (§6), the ⊞/⊟ group boxes (Qt arrows), enable rules for
   Filter / WriteData / WriteImage / ImportData / ExportData (builder warnings, phase 4).
6. **Cell state, names, getters** — Cell State dialog + indicator, Insert Cell Name… dialog and
   name-box rules, Insert Getters.
7. **Special editors** — FormatString dialog, Edit Script dialog (after confirming storage).
8. **Panels** — Filmstrip (record/playback, settings dialog), Snippets (own format, then .cxdx),
   EasyView, Custom View, Result Queue settings, Job Validation run/state, read-only Format Cells /
   Row Height / Column Width, Dependency view (F11 family).

## 8. Open questions to settle on the device (scratch job, with permission)

1. ~~`getCellCondition` / `setCellCondition` string format~~ — answered 2026-11-20, see §1.
2. Where Script source is stored and whether `setCellExpression` round-trips it.
3. FormatString expression form produced by ISVS for a configured dialog.
4. `.cxdx` snippet format (export one from ISVS).
5. Insert Cell Name… dialog layout (not captured).
6. `loadJobData` returns **HTTP 404 while an editor (ISVS) is attached** (seen 2026-11-19) — the app
   should say "an editor is attached" instead of showing the raw 404. Also seen: force-killing
   ISVS (`wineserver -k`) leaves the camera reporting `editorAttached` for a long time (>20 min);
   closing ISVS normally (`wine taskkill /im Cognex.Explorer.exe`, no `/F`) releases it at once.
7. ~~Whether `setCellExpression` on a range in one call exists~~ — not in the HMI API; Insert/Delete
   write cell by cell (plus one `getCellCondition` per non-empty cell). Fine for typical jobs; add a
   progress dialog if big sheets turn out slow.
8. Check against ISVS: Cut semantics (mark vs. immediate clear), what ISVS writes for references to
   deleted cells, whether Copy copies cell states and names, Undo scope (control values?).
9. Phase 4 defaults: does the IS8902CX accept the default expressions (TrainPatMaxRedLine, FindLine,
   FindBlobs, Button `$A$0`…)? What does ISVS write for a tool's structure input (Patterns, Blobs,
   Histogram) and for parameters without a help default — capture the expression ISVS writes when
   inserting FindPatMaxRedLine / Caliper / DetectBlobs. Does Insert Function on A0 (AcquireImage) open
   the dialog in ISVS? Does ISVS's Functions panel list a function under each of its VDA categories?
10. Phase 5: are the property sheet's region parameters editable on the image as soon as they are selected
    (or only after double-click/F9)? Bend handle direction/scale and the exact curved-region geometry; rotation
    centre; masked-region mask geometry (the API example has masks offset in y); which parameters are integers;
    what the event button does with `0`; what the Editing object's flag names are on the IS8902CX (`beginEdit`).
