# Survey request: In-Sight Vision Suite (ISVS) behaviour, run on Windows

Written 2026-11-20. For a separate Claude session on a Windows PC with ISVS 26.1 installed and the IS8902CX camera
reachable at 192.168.1.102. Under Wine on Linux, ISVS's Spreadsheet editor would not accept input, so these
observations could not be made there.

**Goal:** record how ISVS itself behaves so that Insight Studio (a PySide6 replica of the ISVS Spreadsheet editor
on the In-Sight HMI API) can copy it. You only observe and record. Nothing in Insight Studio is changed in this
session.

**Deliverable:** this file with every `Answer:` line filled in, plus a folder `isvs-survey-2026-11/` holding the
screenshots (`21-….png`, `22-….png`, …; the reference set already uses 00–20) and any exported files. The owner
copies both back to Linux (`~/Documents/insight-isvs-reference/live/` and `docs/`).

Write what you **see**. If something cannot be checked, write "not checked" and the reason. Don't guess. Quote
dialog texts, menu items and expressions exactly, including capitalisation, punctuation and spaces.

---

## 0. Safety rules (read first)

* The camera is a shared device. Get the owner's OK before connecting.
* Keep it **Offline** the whole time. Do not press *Online*, and never save a job **on the camera** (no
  *Save Job* to the device, no *Startup Settings*, no firmware/network/user changes).
* Before changing anything, save the current job **to the PC**: File ▸ Save Job As… ▸ *PC*, name
  `backup-before-survey.jobx`. Expected job: `NewJob.jobx`, containing only `A0 = AcquireImage()`.
* Do the work in a scratch job: File ▸ New Job (answer "No" if asked to save).
* At the end, put the original back: File ▸ Open Job… ▸ *PC* ▸ `backup-before-survey.jobx` (this loads it onto the
  camera without saving anything there), check that only A0 is left, then close ISVS normally.
* Only one editor can be attached at a time. Insight Studio on Linux must not be connected while ISVS is.

## 0.1 First look (no changes)

1. Connect the Spreadsheet editor. Is there a yellow bar "The current job was loaded with commented-out cells …"?
   On 2026-11-20 it listed `H592, L592, R592, S592, U592, V592, X593` (left over from refused writes). The job was
   reloaded afterwards. Is the bar gone now? Screenshot if it is still there.
   Answer: Not checked for the original job. Double-clicking the device in the device list opened the
   EasyBuilder-style editor (Image / Inspect / Communication / Inputs/Outputs / Job Validation / HMI), tab
   `[Unsaved Job]@IS8902CX-d350e6`; its File menu had "Convert to Spreadsheet Job" enabled and View had only
   "Record/Playback" (`21-…`). The device page (Home) showed Current Job `NewJob.jobx`, Current State `Offline`,
   firmware `26.1.0 (3930)`, and three buttons "EasyBuilder Connect", "Spreadsheet Connect", "Open HMI".
   The original was backed up to the PC first (`backup-before-survey.jobx`, 50 176 bytes), then File ▸ New Job
   in the EasyBuilder editor (dialog "New Job": "Are you sure you wish to clear all data from the current job?"
   Yes/No). After that, "Spreadsheet Connect" showed the yellow bar "Cannot view EasyBuilder job. Please convert
   to Spreadsheet job." (`22-…`) — this was for the empty EasyBuilder scratch job, not the original job. File ▸
   New Job inside the Spreadsheet editor then gave an empty spreadsheet job with only A0 `AcquireImage()`
   (cell text "Image"), no yellow bar (`23-…`). "Convert to Spreadsheet Job" was greyed out for the empty
   EasyBuilder job.

---

## 1. Property sheet behaviour (TrainPatMaxRedLine)

Insert TrainPatMaxRedLine in an empty cell (Insert Function dialog). The property sheet opens. Reference:
`live/17`–`live/20`.

1. **Expression written on insert.** Read it from the formula bar after OK, or from Edit Function before OK.
   Insight Studio writes `TrainPatMaxRedLine($A$0,0,0,0,180,140,440,320,0,0,0,0,0,1,1,4,1,20,0,0,0,0)` for an
   800×600 image. Is ISVS's the same? Note any difference.
   Answer: Identical: `TrainPatMaxRedLine($A$0,0,0,0,180,140,440,320,0,0,0,0,0,1,1,4,1,20,0,0,0,0)` (inserted in
   B2; B2 shows "Patterns", C2 shows `1.000`) (`26-…`). How it was inserted: double-clicking an empty cell, or
   typing in it, starts in-cell text editing (a wide edit box across the row), not the Insert Function dialog.
   Double-clicking the function in the Functions panel (Vision Tools ▸ Pattern Match ▸ TrainPatMaxRedLine) with
   B2 selected opened the property sheet directly. Enter on the tree item did nothing. Sheet title:
   "Inspection - Property Sheet - TrainPatMaxRedLine"; menus Edit / Insert / Help; rows and defaults: Image
   `$A$0` "= Image"; Fixture `(0,0,0)`; Pattern Region `(180,140,440,320,0,0)`; External Region `0`; Pattern
   Origin `(0,0)`; Auto Select Coarse ☑; Auto Select Fine ☑; Coarse Granularity `4.000` (greyed); Fine
   Granularity `1.000` (greyed); Feature Threshold `20.000`; Train Event [Train Event] button; Reuse Training
   Image ☐; Timeout `0`; Show `hide all` "= 0". Help text for Pattern Region: "Region of interest: {X, Y, Width,
   Height, Angle, Curve}." (`24-…`). Note: the sheet closed and the expression was committed while I was
   clicking its Edit menu; I did not press OK, so what closed it is not known.
2. **Region editable on selection?** Click the *Pattern Region* row once. Is the region editable on the image
   immediately (handles shown, draggable)? Or only after double-click or F9 (Edit ▸ Graphic)? Does the property
   sheet stay visible while the region is edited? Does the grid hide? Screenshot.
   Answer: Not editable on selection; F9 is needed. After one click on the Pattern Region row, the row turns yellow and the region is drawn
   on the image as a red rectangle with an "X" arrow along the top edge, a "Y" arrow down the left edge and a
   centre cross-hair. No drag handles were visible (`25-…`). The property sheet stayed open, and the grid did
   not hide (the grid was overlaid on the image at that point). Double-clicking the row changed nothing visible.
   When the sheet was reopened (double-click on B2), the same red region was drawn with the Image row selected,
   so the outline appears whenever the sheet is open. Double-click on the row does not start editing either.
   **F9 starts editing** (sheet Edit menu: "Graphic  F9", "Maximize Region  Ctrl+Shift+M"). In edit mode
   (`28-…`): the property sheet is **hidden**; the grid stays visible but greyed (cell selection border gone);
   magenta square handles at the 4 corners, a magenta handle at the middle of the right edge (bend), a curved-arrow
   handle at the middle of the bottom edge (rotate); the centre cross-hair disappears; the green ✓ / red ✗ buttons
   next to the cell-name box in the toolbar become enabled; a status line under the image shows
   `Location=306,78 Size=440×320 Rotation=39.0° Curve=-49.3°` (rounded, 1 decimal for angles; Location = X,Y).
   (Layout at this point: image and grid side by side, not overlaid.)
3. **Leaving region editing.** What ends it (another row, Enter, Esc, a click outside)? Is the change written live
   while dragging, or only at the end?
   Answer: **Enter** ends editing and keeps the change: the property sheet reappears with the new value in the
   Pattern Region row (`30-…`). **Esc** ends editing and discards it: the sheet reappears with the values from
   before F9 (`36-…`). A **click on the image outside the region** does *not* end editing (handles stay, nothing
   moves). Another row / the ✓ ✗ toolbar buttons: not checked. Live: while dragging, the outline redraws live, the
   handles are hidden, and the status line shows only the quantity being changed (`Curve=74.2°` while bending,
   `Size=583×296 Curve=-128.0°` while dragging a corner) (`34-…`, `38-…`); after release it shows the full
   `Location=… Size=… Rotation=… Curve=…` again (`35-…`). Nothing is written to the sheet until Enter, and nothing
   is written to the cell (formula bar) until OK in the sheet — after Enter the formula bar still showed
   `…180,140,440,320,0,0…`. After a change, the row gets a small icon at its right end, tooltip "reset to original
   value" (also per sub-field; only on fields that differ from the committed value).
4. **Rotation handle.** Where is it (middle of the bottom edge?) and what does dragging it do? Does it rotate about
   the region centre or the origin (top-left)? Which way does Angle increase when the handle moves clockwise on
   screen?
   Answer: Middle of the bottom edge (curved-arrow icon). Dragging it rotates the region **about its centre**:
   centre stayed at (400,300) in image coordinates. Moving the handle clockwise on screen (to the left along the
   bottom) gave **Angle +14.352** — Angle increases clockwise on screen (y down). X,Y change to the rotated
   top-left corner: (180,140,440,320,0,0) → (226.527,90.46,440,320,14.352,0), which is exactly
   centre + R(14.352°)·(−220,−160) (`29-…`, `30-…`). The X/Y arrows and the handle rotate with the region. Angles
   are shown normalised to 0…360 (e.g. 342.253 for −17.747).
5. **Bend handle.** Where is it (middle of the right edge?) Drag it down a little, then up a little, and read the
   Curve field each time. Which direction gives a positive Curve? What Curve does it show with the handle at the
   bottom-right and top-right corners? Is there a maximum? Does the handle stay under the mouse? Screenshot of a
   bent region.
   Answer: Middle of the right edge (magenta). Dragging it **down → positive Curve**, **up (above the middle) →
   negative Curve**. Values after Enter: down: `(134.191,154.047,440,320,342.253,64.199)`; up:
   `(305.684,77.652,440,320,39.02,-49.335)` (`31-…`, `32-…`, `33-…`). **Bending also changes Angle and X,Y** (Width,
   Height stay): Angle + Curve/2 stays constant (= 14.352, the unbent angle): 342.253 + 64.199/2 ≡ 14.352,
   39.02 − 49.335/2 = 14.352; also seen in the status line (Rotation=0.0° with Curve=29.3°, Rotation=65.0° with
   Curve=−101.2°). Note the sheet shows `39.02` (trailing zero dropped) in the collapsed row. With the handle
   dragged to where the bottom-right corner was: `Curve=74.2°`; further down 105.5°, then it stops at
   **156.6°**; toward/over the top-right corner it stops at **−156.6°** — so there is a clamp at about ±156.6° for
   this 440×320 region (`37-…`). Curve also depends on the x position of the pointer (moving right from the
   clamp position lowered it to 134.1°). Whether the handle stays exactly under the mouse: not determined (the
   handles are hidden during the drag and the pointer is not in screenshots).
6. **Corner and side handles on a curved region.** With Curve ≠ 0, drag a corner. Which fields change (X, Y, Width,
   Height, Angle, Curve)?
   Answer: **All six change.** On a region with Curve −101.2°, dragging the top-left corner handle ~11 screen px
   (≈22 image px) changed Location 381,96 → 348,55, Size 440×320 → 583×296, Rotation 65.0° → 92.0°, Curve
   −101.2° → −128.0°; committed values `(348.288,55.415,583.443,295.523,91.69,-127.957)` — Width/Height become
   non-integer (`38-…`, `39-…`, `40-…`). Here Angle + Curve/2 is no longer the earlier constant (≈28). Side
   handles: not checked (none visible apart from the bend handle on the right).
7. **Train Event button with `0`.** With Train Event = 0, press the *Train Event* button in the sheet. What happens
   (training, a message, nothing)? Quote any message.
   Answer: Nothing visible: no message, no dialog, no change of any field (pressed by click twice and Space once
   while the button had focus) (`43-…`). Tooltip and help text of the row: "Model training event trigger." (Note:
   the image in the sheet already shows a trained-pattern preview — greyscale with green feature edges — after
   Maximize Region, without pressing the button, `41-…`.)
8. **Insert ▸ Function.** When is it enabled? Check: a number row selected, a text/reference row selected, with
   the cursor inside a value box, and with nothing being edited. What does choosing a function insert, and where?
   Answer: Sheet Insert menu: "Function  Ctrl+Shift+F", "Absolute Reference  Ctrl+Shift+A", "Relative Reference
   Ctrl+Shift+R". All three were enabled with the Train Event (button) row selected and with the Feature Threshold
   (number) row selected and its value highlighted in the box. Reference row and "nothing being edited": not
   checked. Choosing **Function** on Feature Threshold did **not** open a function list: it switched that row to
   expression mode — the spin box became a text box containing `20` with `= 20` shown to its right (same style as
   the Image row `$A$0  = Image`) and the fx button in the sheet toolbar appeared pressed (`44-…`). Cancelled
   afterwards.
9. **Maximize Region** (Ctrl+Shift+M) on Pattern Region. Resulting values? With Fixture (100,50,30), are the values
   expressed in the fixture (e.g. angle −30)?
   Answer: Without fixture: `(0,0,1920,552,0,0)` — the camera image is **1920×552** (so the insert default
   180,140,440,320 is *not* derived from the image size) (`41-…`). With Fixture `(100,50,30)`:
   `(-111.602,6.698,1920,552,-30,0)` — **yes, in fixture coordinates**: Angle −30 and X,Y = R(−30°)·(0−100, 0−50)
   (`42-…`). With that fixture a red "!" icon appeared left of the OK button (its tooltip could not be read).
   Sub-fields of Fixture are X, Y, Theta, all `0.000` (3 decimals); Pattern Region sub-fields X, Y, Width, Height,
   Angle, Curve, all 3 decimals.

## 2. Integer vs. decimal fields

Insert each function below and open its property sheet. For every **numeric** parameter, note whether the field
shows an integer (`0`) or 3 decimals (`0.000`), and its default. A screenshot of each sheet (scrolled as needed)
is enough if it is readable.

* FindPatMaxRedLine — Answer: (`45-…`, `46-…`, `47-…`) Image `$A$0`; Fixture X/Y/Theta `0.000`; Find Region
  X `180.000`, Y `140.000`, Width `440.000`, Height `320.000`, Angle `0.000`, Curve `0.000`; External Region `0`
  (text box); Pattern `0` (text box); **Number to Find `1` (integer)**; Accept Threshold `50.000`; Ignore Polarity
  ☐; Accuracy Mode list `High` = 1; Clutter in Score ☐; Contrast Threshold `0.000`; Find Tolerances: Angle Start
  `-15.000`, Angle End `15.000`, Scale Start `100.000`, Scale End `100.000`; XY Overlap `70.000`; Advanced Settings:
  Use Coarse Percentage ☐, Coarse Accept Percentage `60.000` (greyed while unchecked); **Timeout `5000`
  (integer)**; Show `hide all` = 0. Red "!" left of OK on open (Pattern = 0).
* Caliper — Answer: (`49-…`, `50-…`) Two tabs "General" / "Scoring Methods". General: Image `$A$0`; Fixture
  `(0,0,0)`; Region `(300,275,200,50,0,0)`; Edge Mode list `Single Edge` = 1; **Number to Find `1`, Minimum
  Contrast `5`, Thresh: Accept `5`, Edge Width `2` — all integers**; Edge: First list `either` = 3; Edge: Second
  `either` = 3 (greyed); Edge Distance `10` (integer, greyed); Show `hide all` = 0. Edge: Second and Edge Distance
  are greyed with Edge Mode = Single Edge. Scoring Methods tab: "Add Scoring Function" combo (`Contrast`) +
  [Add]; "Current Scoring Functions" table (OK | Scoring Method | Maximum Score) with one row `High Contrast`,
  `100`; [Delete] (disabled) [Copy]; "Edit the Scoring Method's parameters:" radio "Low Contrast Edges" /
  "High Contrast Edges" (selected) and a Score (0–100) vs Contrast (0–255) line graph from (0,0) to (255,100).
* DetectBlobs — Answer: (`52-…`) Image `$A$0`; Fixture `(0,0,0)`; Region `(180,140,440,320,0,0)`; External
  Region `0`; **Number to Sort `1` (integer)**; **Threshold `-1` (integer)**; Fill Holes ☐; Boundary Blobs ☑;
  Color: Blob list `either` = 2; Color: Background list `white` = 1; Area Limit: Min `100.000`; Area Limit: Max
  `100000.000`; Show `hide all` = 0.
* (extra) FindBlobs — (`54-…`) Blobs `0` (text, red "!"); **Number to Find `3` (integer)**; Accept Thresh
  `10.000`; groups Angle (Angle/Range/Weight `0.000`), Area (`1000.000`/`20000.000`/`50.000`), Elongation
  (`1.000`/`2.000`/`50.000`), Holes (Number `0.000`/Range `2.000`/Weight `0.000`), Perimeter
  (`1000.000`/`10000.000`/`50.000`), Spread (`1,2,50`); Show `hide all` = 0. All group sub-fields 3 decimals.
* ReadIDMax — Answer: (`73-…`–`76-…`) Image `$A$0`; Fixture `(0,0,0)`; Region `(180,140,440,320,0)` (5 values,
  no Curve); Advanced Decode Mode list `IDMax` = 0; Enable Training ☐; 1D Symbologies group
  `(1,1,1,0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,1)`: Code 128 ☑, Code 39 ☑, Interleaved 2 of 5 ☑, Pharmacode ☐, UPC/EAN ☑,
  Code 93 ☑, Codabar ☑, MSI ☐, Code 25 ☐, PDF 417 ☐, DataBar ☐, DataBar Limited ☐, DataBar Expanded ☐,
  EAN.UCC Composite ☐, POSTNET ☐, PLANET ☐, Japan Post ☐, Australia Post ☐, UPU ☐, Intelligent Mail Barcode ☐,
  **1D Maximum Results `1` (integer)**; 2D Symbologies `(1,1,1,1,0,1,0,1,0,1)`: Data Matrix ☑, **DM Maximum Results
  `1`**, QR Code ☑, **QR Maximum Results `1`**, MaxiCode ☐, Maxicode Maximum Results `1` (greyed), Aztec Code ☐,
  Aztec Maximum Results `1` (greyed), DotCode ☐, DotCode Maximum Results `1` (greyed) — each "Maximum Results" is
  greyed while its symbology is unchecked; Decode Settings `(3,7,0,0,2,0,2,0,0,0,1,0,2)`: Perspective Distortion
  `Moderate` = 3, QR Mode `All QR Modes` = 7, Ignore Polarity ☐ (greyed), Allow Flexible Grid Size ☐ (greyed),
  Symbol Damage `Moderate` = 2, Checksum ☐, Polarity `Auto` = 2, Omnidirectional ☐ (greyed), Sort Mode `None` = 0,
  Allow Identical 1D Symbols ☐, Expand UPC-E ☑, Rectangular Extension ☐, **Minimum Decodes Before Output `2`
  (integer)**; Verification Mode `None` = 0; Trucheck Settings `0` (text, greyed); **Timeout `0` (integer)**; Show
  Decoded Result ☐; Show `hide all` = 0. No 3-decimal fields on this sheet.
  Expression on OK (copied from the formula bar):
  `ReadIDMax($A$0,0,0,0,180,140,440,320,0,0,0,1,1,1,0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,0,1,0,1,0,1,3,7,0,0,2,0,2,0,0,0,1,0,2,0,0,0,0,0)`;
  B36 shows "IDMax", headers `Index String` in C35:D35, rows 36–37 `0.000 #ERR`, `1.000 #ERR` (`77-…`).

## 3. Expressions ISVS writes on insert

For each function, insert it via Insert ▸ Function in an empty cell, accept the property sheet unchanged (OK), and
copy the full expression from the formula bar.

(Observed: all were inserted by double-clicking the function in the Functions panel with the target cell
selected; the property sheet opens immediately. After OK, functions returning a structure also fill a results
table: a bold header row in the row *above* the cell, starting one column to the right, and the values in the
cell's own row to the right. Camera image is 1920×552; region defaults are the same fixed numbers as in Insight
Studio, not scaled to the image.)

| Function | Expression ISVS wrote | Result shown in the cell |
| --- | --- | --- |
| FindPatMaxRedLine | `FindPatMaxRedLine($A$0,0,0,0,180,140,440,320,0,0,0,0,1,50,0,1,0,0,-15,15,100,100,70,0,60,5000,0)` | `#ERR` in B4 (no pattern); plus a results table: headers `Index X Y Angle Scale Score` in C3:H3 (row above), values C4:H4 `0.000 #ERR #ERR #ERR #ERR 0.000` (`48-…`) |
| Caliper | `Caliper($A$0,0,0,0,300,275,200,50,0,0,1,1,5,5,2,3,3,10,0)` | "Edges" in B7; headers `Index X0 Y0 X1 Y1 Score Contrast` in C6:I6, values row 7 `0.000 #ERR #ERR #ERR #ERR 0.000 #ERR` (`51-…`). The default scoring function does not appear in the expression. |
| DetectBlobs | `DetectBlobs($A$0,0,0,0,180,140,440,320,0,0,0,1,-1,0,1,2,1,100,100000,0)` | "Blobs" in B10; headers `Index X Y Angle Color Score Area …` row 9, values row 10 `0.000 618.027 267.673 90.222 0.000 100.000 110.000` (`53-…`) |
| FindLine | `FindLine($A$0,0,0,0,300,275,200,50,0,0,2,0,25,1,0,3,0)` — differs from Insight Studio only in the region (ISVS 300,275,200,50; Insight Studio 200,150,400,300). Sheet: Region `(300,275,200,50,0,0)`, Polarity `either` = 2, Find By `best score` = 0, Accept Thresh `25`, Normalize Score ☑, Angle Range `0`, Edge Width `3` (all integer), Show `hide all` = 0 (`56-…`) | "Edges" in B18; headers `X0 Y0 X1 Y1 Score` in C17:G17 (no Index column), values row 18 `#ERR #ERR #ERR #ERR 0.000` (`57-…`) |
| FindBlobs | `FindBlobs(0,3,10,0,0,0,1000,20000,50,1,2,50,0,2,0,1000,10000,50,1,2,50,0)` | `#ERR` in B13; headers `Index X Y Angle Color Score Area` row 12, result rows from 13 (`55-…`) |
| Button | `Button("",-1)` — **not** `Button($A$0)`. Signature in the Functions panel: "Button(Name, Event)". Sheet: Name (empty text), Event list `None` = -1 (`58-…`) | an empty button-shaped control in B21 (`59-…`) |
| EditMaskedRegion | `EditMaskedRegion($A$0,0,0,0,1,1,1,1,1,1,1,"",0)` — Name `""` and Show `0` (Insight Studio: `"MaskedRegion",2`). Sheet: Image, Fixture `(0,0,0)`, Add Masks, Remove Masks, Edit Masks, Move, Size, Rotate, Bend all ☑, Name empty, Show `hide all` = 0 (`60-…`) | a control box in B24; a thin default region drawn on the image (`61-…`) |
| EditCompositeRegion | `EditCompositeRegion($A$0,0,0,0,1,1,1,1,1,"",0)` (Insight Studio: `"CompositeRegion",2`). Sheet tabs "General" / "Regions". General: Add Subregions, Remove Subregions, Edit Subregions, Move Entire Composite, Rotate ☑, Name empty, Show `hide all` = 0 (`62-…`). Regions tab: buttons "Add...", "Insert...", "Remove", "MoveUp", "MoveDown" (last two disabled); table # / Type / Operation with row `1  Region  Add`; "Region Properties" X `180.000`, Y `140.000`, Width `440.000`, Height `320.000`, Angle `0.000`, Curve `0.000` (`63-…`). The subregion is **not** part of the expression. | control box in B27; region outline on the image (`64-…`) |
| EditPolygon | `EditPolygon($A$0,0,0,0,1,1,1,1,1,1,"",0)` (Insight Studio: `"Polygon",2`). Tabs "General" / "Points". General: Add Points, Remove Points, Move Points, Move Entire Polygon, Scale, Rotate ☑, Name empty, Show `hide all` = 0 (`65-…`). Points tab: X / Y table `400.000,140.000`, `180.000,460.000`, `620.000,460.000` (a triangle), buttons [Insert], [Remove] (disabled) (`66-…`). Points are not in the expression. | control box in B30; red triangle on the image (`67-…`) |
| EditPolylinePath | `EditPolylinePath($A$0,0,0,0,1,1,1,1,1,1,"",0)` (Insight Studio: `"PolylinePath",2`). Sheet (no tabs): Add Points, Remove Points, Move Points, Move Entire Polyline, Scale, Rotate ☑, Name empty, Show `hide all` = 0 (`68-…`) | control box in B33; a two-segment polyline band drawn top-left on the image (`69-…`) |

Summary of differences vs Insight Studio: Name `""` and Show `0` for all Edit* controls; `Button("",-1)`;
FindLine/Caliper region default `300,275,200,50`; FindPatMaxRedLine, Caliper, DetectBlobs and FindBlobs do get
full default expressions in ISVS (Insight Studio has none).

Functions panel, Graphics ▸ Controls lists: Button, CheckBox, Dialog, EditAnnulus, EditCircle,
EditCompositeRegion, EditFloat, EditInt, EditLine, EditMaskedRegion, EditMultiGraphics, EditPassword, EditPoint,
EditPolygon, EditPolylinePath, EditRegion, EditString, Jump (Graphics has Controls, Displays, Image). Vision Tools
▸ Edge lists: Caliper, FindCircle, FindCircleMinMax, FindCurve, FindLine, FindMultiLine, FindSegment, PairDistance,
PairEdges, PairMaxDistance, PairMeanDistance, PairMinDistance, PairSDevDistance, PairsToEdges, SortEdges. Blob:
DetectBlobs, FindBlobs, SortBlobs. Pattern Match: FindPatMaxRedLine, SortPatterns, TrainPatMaxRedLine.

For comparison, Insight Studio writes: FindLine `FindLine($A$0,0,0,0,200,150,400,300,0,0,2,0,25,1,0,3,0)`, Button
`Button($A$0)`, EditMaskedRegion `EditMaskedRegion($A$0,0,0,0,1,1,1,1,1,1,1,"MaskedRegion",2)`, EditCompositeRegion
`EditCompositeRegion($A$0,0,0,0,1,1,1,1,1,"CompositeRegion",2)`, EditPolygon
`EditPolygon($A$0,0,0,0,1,1,1,1,1,1,"Polygon",2)`, EditPolylinePath
`EditPolylinePath($A$0,0,0,0,1,1,1,1,1,1,"PolylinePath",2)`. For FindPatMaxRedLine, Caliper, DetectBlobs and
FindBlobs it has no default (the name goes to the formula bar).

Also:
* Select A0 (`AcquireImage()`) and use Insert Function. Does ISVS open the Insert Function dialog, a property
  sheet, or nothing? Answer: Neither a dialog nor a property sheet. With A0 selected, the fx (Insert Function)
  button in the formula-bar toolbar switched the right dock to the **Acquisition** tab ("Current Job Acquisition
  Settings": Trigger — Trigger Type, Trigger Source, Debounce (ms), Delay (ms); General — Exposure (ms), Override
  Max Exposure, Gain Factor, Enable Automatic Blackleveling, Orientation, Image Buffers; Image Size — Start Row,
  Number of Rows; White Balance …). Nothing was changed there (`70-…`). (The dock's tabs are "Functions",
  "Acquisition", "Job Validation".)
* In the Functions panel (right dock), is a function listed under every category it belongs to? Example: GetX
  under several Vision Data Access subcategories? Answer: **Yes.** Vision Data Access is split into
  subcategories (Blobs, Calibrate, CircleFit, Clocked Data Storage, Color, ColorHist, Controls, Dist,
  EdgeAIAnomalyDetect, EdgeAIClassify, EdgeAIRead, EdgeAISegment, …). GetX appears under **Blobs** (GetAngle …
  GetWidth, GetX, GetY) and again under **CircleFit** (GetDistance, GetMaxDist, GetMaxDistIndex, GetNPointsUsed,
  GetRadius, GetSigma, GetX, GetY) (`71-…`, `72-…`). Help for GetX: "GetX(Structure, [Index1], [Index2]) Returns an
  X coordinate." The filter box above the tree could not be focused by the automation.

## 4. Choice values for enable rules

ISVS shows `= n` next to a choice in the property sheet. For each parameter below, select every choice in turn
and record its number and which other parameters become enabled or greyed out.

| Function | Parameter | Choice label → `= n` | Parameters greyed out / enabled per choice |
| --- | --- | --- | --- |
| WriteData | Storage | `Local Device` = 0, `FTP Server` = 1, `SFTP Server` = 2 | Local Device: Server, User Name, Password, Block Execution, Timeout greyed; Enable File Cleanup enabled. FTP/SFTP: Server, User Name, Password, Block Execution enabled; **Timeout stays greyed** (also with Block Execution ticked); Enable File Cleanup greyed (`84-…`–`87-…`) |
| WriteImage | Storage | `Local Device` = 0, `FTP Server` = 1, `SFTP Server` = 2, **`TCP Server` = 3** | Local Device: Server, User Name, Password, Block Execution, Timeout greyed. FTP/SFTP: Server, User Name, Password, Block Execution enabled, Timeout greyed. **TCP: Server, Block Execution, Timeout enabled; User Name, Password, File Path greyed** (File Name enabled). Enable File Cleanup greyed for 1/2/3 (`90-…`–`93-…`) |
| ImportData | Storage | `Local Device` = 0, `FTP Server` = 1, `SFTP Server` = 2 | Host Name, User Name, Password greyed for 0, enabled for 1 and 2 (`81-…`–`83-…`) |
| ExportData | Storage | `Local Device` = 0, `FTP Server` = 1, `SFTP Server` = 2 | same as ImportData (`78-…`–`80-…`) |
| Filter | Auto Threshold — **a checkbox** (default ☑) | ☑ / ☐ | With Filter Type `Binarize` = 0: Auto Threshold ☑ → Threshold greyed; ☐ → Threshold enabled. Kernel Rows/Columns, Min, Max, Gain, Smoothness greyed for Binarize (`94-…`, `95-…`) |

Also note any other control on these sheets that greys out other rows.

* WriteData / WriteImage: **Enable File Cleanup** ☐ greys Minimum Free Space % (`0.000`) and Desired Free Space %
  (`50.000`); ☑ enables them (Local Device only) (`89-…`). WriteData Data Format list: `TXT` = 0, `HTML`, `XML`,
  `CSV`, `JSON` = 4, `No Type` = 5 (HTML/XML/CSV are 1–3 by list order; not individually read) (`88-…`). Help:
  "Format in which to save the file. The extension for the selected file format (either .txt, .html, .xml, or
  .csv) will be automatically added to the end of the file name." WriteImage other defaults: File Type `BMP` = 0,
  Image Resolution `Full` = 0, Max Append Value `999`, Reset ☐, Overlay Graphics `SVG Overlay` = 1.
* Filter: **Filter Type** drives the enables: list Binarize, Bot Hat, Clip, Close, Dilate, Edge Magnitude,
  Equalize, Erode, Fill Dark Holes, Fill Light Holes, Gradient Full, Gradient Horizontal, Gradient Vertical, …
  (more below, not scrolled) numbered in list order (Binarize = 0, Clip = 2, Equalize = 6 seen). `Clip` = 2: Min
  and Max enabled, Auto Threshold and Threshold greyed (`97-…`); `Equalize` = 6: all parameter rows greyed.
  Defaults: Kernel Rows `3`, Kernel Columns `3`, Threshold/Min/Max `128`, Gain `1.000`, Smoothness `1` (`96-…`).
* Storage help text (all four): "The location where the data is stored: Local Device (In-Sight device or PC) or
  FTP server." ExportData Event help: "ON: exports when an input parameter is updated. OFF: does not export. Cell
  reference: exports when an Event is triggered or the formula evaluates …"; ImportData: "ON: imports when an
  input parameter is updated. OFF: imports only when the job is first loaded. Cell reference: imports whenever
  the Event is triggered or the formula …". All §4 sheets were opened on an empty cell and **cancelled** (nothing
  inserted).

## 5. Interactive Graphics Mode for masked and composite regions

1. **EditMaskedRegion:** double-click the cell (or F9) to enter Interactive Graphics Mode. Right-click inside the
   ROI. Quote the menu items exactly. Add a mask: is it a full-height band across the ROI? How wide? Is it centred
   on the click? Can a mask be resized in height or moved in y? Screenshot.
   Answer: **Double-click on a control cell enters Interactive Graphics Mode** (it does not open the property
   sheet; the sheet is reached via the cell context menu "Edit Function..."); F9 with the cell selected does the
   same. Default ROI: `Location=180,275 Size=440×50 Rotation=0.0° Curve=0.0°` (status line), with yellow
   position labels `180` / `275` next to a move cross. Right-click inside the ROI: **"Add Mask"**, **"Delete Mask"**
   (`98-…`). Add Mask adds a **full-height band** across the ROI, narrow (about 15–20 px of the 440 px ROI, judged
   from the screen), placed at the **left end of the ROI, not at the click**: a second Add Mask from a right-click
   near the right end also appeared at the left end, next to the first (the newest is drawn blue-hatched)
   (`99-…`). Dragging the hatched mask right/down did not move it (nothing changed; status unchanged) (`100-…`) —
   moving/resizing a mask in y: not determined. Esc left IGM; the masks stayed (the expression did not change —
   masks are not in the expression).
2. **EditCompositeRegion:** right-click a subregion. Quote the menu, including submenus (expected: Add Subregion ▸
   Annulus/Circle/Polygon/Region, Remove Subregion, Subregion Operation ▸ Add/Subtract). What happens when adding
   a 33rd subregion (the help says 32 max)?
   Answer: In IGM the subregion is drawn **blue** with a move cross and labels; status `Location=180,140
   Size=440×320`. Right-click on a subregion: **"Add Subregion ▸"** (submenu **"Annulus"**, **"Circle"**,
   **"Polygon"**, **"Region"**), **"Remove Subregion"** (greyed while only one subregion exists), **"Subregion
   Operation ▸"** (submenu **"Add"**, **"Subtract"** — both greyed for the single first subregion) (`101-…`,
   `102-…`). Add Subregion ▸ Region from IGM adds a region **centred on the first one at 80 % size**
   (`Location=224,172 Size=352×256`), selected (red with handles), and its operation defaults to **Subtract** (✓)
   (`103-…`, `104-…`); repeated adds land on exactly the same place. After the 2nd subregion, Remove Subregion and
   both Operation items are enabled. The sheet's Regions tab listed them as `Region / Add`, then `Region /
   Subtract` × 7 after 7 IGM adds; the "#" column shows `1` for every row (`106-…`). The Regions-tab "Add..." button
   opens a drop-down Annulus / Circle / Polygon / Region; regions added there get Operation **Add** and are placed
   at `X 740, Y 116, 440×320` (not centred). **33rd subregion: not determined** — by my count 32 existed after 8 +
   24 adds and one more Add showed no message or dialog, but the list could not be counted exactly (all "#" = 1),
   so whether the 33rd was added or silently refused is unknown (`107-…`). Cancelled the sheet afterwards. In IGM,
   Enter switched the selection to the whole composite (status `Location=180,140 Size=440×320`) instead of
   leaving IGM; the green ✓ toolbar button left IGM.
3. **EditPolygon:** how is a point added and removed (expected: click on an edge adds one, Shift+Alt+click removes
   one)? Are there scale or rotate handles?
   Answer: IGM shows magenta vertex handles, a dashed bounding box (status `Location=180,140 Size=441×321`), a
   **rotate handle** (curved arrow) just below the middle of the bottom of the box, and a move cross with labels;
   **no separate scale handles** were visible (`108-…`). A plain click on an edge does **not** add a point, nor
   does Shift+click. Right-click on an edge: **"Add Point"**, **"Remove Point"** (greyed); "Add Point" inserts a
   vertex at the clicked spot on the edge (`109-…`, `110-…`). Right-click on a vertex: both items enabled
   (`111-…`). **Shift+Alt+click on a vertex removes it** (`112-…`). Alt+click / Ctrl+click on an edge: not
   checked.

## 6. Open questions for later phases (plan §8.2–8.5, 8.8)

1. **Script storage (§8.2).** Insert a Script function and type a short script, e.g.
   `return 1+2;`. What does the formula bar show for the cell afterwards? Does the source appear anywhere in the
   expression? Screenshot of the Edit Script dialog.
   Answer: Functions panel: Scripting ▸ Script, help "Script(...) Executes the JavaScript source code (created and
   managed via the Edit Script dialog)." Inserting it opens **"Inspection - Edit Script"** directly (no property
   sheet): menus "Script", "Edit"; an **"Arguments:"** text box (default `10`); a JavaScript code editor with line
   numbers and folding, pre-filled with a template (`"use strict";`, a `function Script() { this.total = 0; }`
   constructor, `module.exports = Script;`, a `run` function that checks its argument, adds it to `this.total` and
   returns it, plus optional `save`/`load` functions, each with explanatory comment blocks); a **"Last Result:"**
   pane; a **"Console Log:"** pane with [Clear]; buttons [Test Script], [Save], [Cancel] (`113-…`–`115-…`). I
   replaced the source with a minimal `run` that does `return 1+2;`, [Test Script] → Last Result `3`, [Save]. The
   formula bar then shows **`Script(10)`** — only the arguments; **the source does not appear in the expression**
   (stored elsewhere). The cell shows `3.000` (`116-…`).
2. **FormatString (§8.3).** Insert FormatString. In its dialog, add two items (e.g. a number cell with 2 decimals,
   and a string cell), set Leading text `A`, delimiter Comma, terminator CR+LF. Then copy the expression it
   produces. Screenshot of the dialog.
   Answer: Text ▸ String ▸ FormatString opens "Inspection - Property Sheet - FormatString": group
   "Starting/Ending" (Leading Text, Trailing Text, Terminators list `None` / `Carriage Return (CR)` / `Line Feed
   (LF)` / `CR+LF`); "☐ Use Delimiter" with radio Standard (list, default `Comma`) / Other (text box); "Arguments"
   table with columns Include Label (checkbox), Label (default `Label`), Cell, Data Type, Decimal Places, Fixed Width
   (checkbox), Field Width (default `8`, greyed unless Fixed Width), Padding (default `Leading Spaces`), and buttons
   [Add] [Delete] [Up] [Down]; "Output: N characters" preview box; [OK] [Cancel]. **[Add] hides the sheet and asks
   you to click a cell** in the spreadsheet (the target cell is outlined red, the status line shows the hovered
   cell's formula); Enter returns to the sheet with a new row (Data Type default `Floating Point`, Decimal Places
   `3`). Data Type list: Integer, Unsigned Integer, Integer (hex), Integer (HEX), Integer (Octal), Floating Point,
   Scientific Notation, Character, String (Decimal Places greyed for String). With items B44 (number, 2 decimals)
   and C35 (text "Index", type String), Leading text `A`, Use Delimiter ☑ Comma, Terminator CR+LF: preview
   "Output: 13 characters" `A3.00,Index` (`117-…`). Expression (copied from the formula bar):
   `FormatString("%s%.0s%.2f,%.0s%s%s\r\n","A","Label",$B$44,"Label",$C$35,"")`; the cell shows `A3.00,Index`
   (`118-…`). (Note how labels are kept as `%.0s` arguments even when Include Label is off, and the trailing text is
   the final `%s` argument `""`.) I could not create a literal string cell: typing `"abc"` could not be committed
   (see notes at the end).
3. **Snippet export (§8.4).** Select a few cells (e.g. an EditInt and a formula using it), export them as a
   snippet (`.cxdx`), and put the file in `isvs-survey-2026-11/`.
   Answer: Done with B44 (`Script(10)`) and B47 (the FormatString that references `$B$44`), selected as B44:B47,
   right-click ▸ "Export Snippet...". Save dialog "Export Snippet", default folder Documents ▸ In-Sight Vision
   Suite ▸ In-Sight ▸ Snippets, type "CXDX files (*.cxdx)". File: `isvs-survey-2026-11/snippet-B44-B47-script-
   formatstring.cxdx` (5 632 bytes; binary — starts with the ASCII bytes `version` followed by zero bytes). (No
   EditInt in the selection; the EditInt was inserted later, at B50.)
4. **Insert Cell Name… dialog (§8.5).** Screenshot it. Quote its title, labels and buttons. What happens with an
   invalid name (e.g. `1abc`, `A1`) and with a duplicate name?
   Answer: Cell context menu "Insert Cell Name..." (shown as "Edit Cell Name..." on an already named cell) opens
   a dialog titled **"Cell Names"**: a table with columns "Name" and "Location" listing *all* names in the job;
   buttons [Add], [Rename], [Delete], [Auto Name], [OK], [Cancel]. A new row for the current cell is added and put in
   edit mode with the suggested name **`Result`** (a second one became `Result01`) (`119-…`). Invalid names `1abc`
   and `A1`: **no message; the edit is silently reverted** to the previous name. `myval` was accepted. [Add] hides
   the dialog and asks for a cell ("Click to insert reference E38" tooltip), Enter returns. **Duplicate**: renaming
   the second entry to `myval` was accepted in the dialog (both rows showed `myval`), no message on OK, but the
   cell actually got **`myval_1`** (name box) (`120-…`). Named cells show a small blue triangle in the bottom-right
   corner. Formulas keep their cell references (`$B$44`), they are not rewritten to names.
5. **Cut / Copy / Undo (§8.8).** Use cells B1 = `5`, C1 = `B1*2`, and give B1 a name and a cell state (Enabled if
   …).
   Setup: B1 = `5` (shows `5.000`), C1 = `B1*2` (`10.000`); B1 named `Result` (Cell Names dialog); B1 cell state set
   to **Disabled** (the value turns grey) (`123-…`). Cell State dialog ("Cell State - Inspection"): "Cell Range: B1",
   radio Enabled / Disabled / Conditionally Enabled (sub-radio Absolute (default) / Relative, "Cell Reference:" box
   and [Select Cell...]); OK is greyed while Conditionally Enabled has no reference (`121-…`, `122-…`). Setting a
   conditional reference was not completed: clicking the Cell Reference box closed the dialog without saving.
   (The copy test below was done before the cut test.)
   * Cut B1. Is B1 cleared immediately, or only marked until Paste? Paste into D1. What does C1 become?
     Answer: **Only marked** — after Ctrl+X, B1 still shows `5.000` with a dashed "marching ants" border (`125-…`).
     After Ctrl+V in D1: B1 is empty, D1 = `5.000` (still greyed/Disabled, keeps the name `Result`), and **C1 becomes
     `D1*2`** (still `10.000`) (`126-…`). Afterwards Paste is greyed in the context menu (the cut can be pasted once).
   * Copy B1 and paste into E1. Is the cell state copied? Is the name copied?
     Answer: **State copied** — E1 shows `5.000` greyed (Disabled). **Name copied with a suffix** — E1's name box
     shows `Result_1` (`124-…`). The copy source keeps the marching-ants border after paste.
   * Delete row/column of a referenced cell (Edit ▸ Delete…). What does a formula that referred to it show
     (`#REF`, something else)?
     Answer: Context menu "Delete..." opens "Delete - Inspection": radio "Shift cells left", "Shift cells up"
     (default), "Entire row", "Entire column"; [OK] [Cancel]. Deleted **entire column D** (D1 was referenced by
     C1). Result: **no `#REF`** — C1 still reads `D1*2` and now points at the cell that shifted into D1 (the former
     E1, `5.000`), value `10.000`. Everything right of column D shifted left (e.g. the FindPatMaxRedLine table header
     row lost its "X" column) (`127-…`). Deleting a row: not checked.
   * Change an EditInt's value with its spin arrows, then Undo. Is the control value undone?
     Answer: EditInt sheet: Min `0`, Max `255` → `EditInt(0,255)`, cell shows `0` with spin arrows. Three clicks on
     the up arrow → `3`. **Ctrl+Z and the toolbar Undo button did not change it back** (still `3`; the Undo button
     looked greyed) (`128-…`). So the control value was not undone in this test.

## 7. Finish

* Restore the backup (§0) and confirm the job is `NewJob.jobx` with only A0. The camera must be Offline.
* Close ISVS normally (window close), not by killing the process.
* Summarise in 3–5 lines what was answered and what was not.

Restore (done 2026-11-20 15:03): File ▸ Open Job ▸ "This PC" ▸ `backup-before-survey.jobx` (opened from a
byte-identical copy in `Documents\In-Sight Vision Suite\In-Sight\`, SHA-256 checked, because the automation may
not type paths under `.claude\`), confirmed "Are you sure you wish to clear all data from the current job?" → Yes.
The Spreadsheet editor then showed "Cannot view EasyBuilder job. Please convert to Spreadsheet job." — the original
job is an **EasyBuilder** job, not a spreadsheet job with only A0 (`129-…`). Device page afterwards: Current State
`Offline`, **Current Job `backup-before-survey.jobx`** (before the survey: `NewJob.jobx`; same content, the
in-memory job name now comes from the backup file name) (`130-…`). Camera stayed Offline throughout; nothing was
saved to the camera (no Save Job to device, no Startup Settings, no Online, no trigger). ISVS was closed with the
window close button; no save prompt appeared; all Cognex processes exited.

Summary: Answered §1 fully except "does the bend handle stay under the mouse" and Insert ▸ Function on a reference
row; §2 all four sheets; §3 all ten expressions plus the A0 and Functions-panel questions; §4 all five rows with
choice numbers and enables; §5 menus, mask placement, polygon point add/remove; §6 all five items (Script,
FormatString, snippet `.cxdx`, Cell Names dialog incl. invalid/duplicate names, cut/copy/delete/undo). Not
determined: whether a 33rd composite subregion is refused (no message seen, list count not verifiable), whether a
mask can be moved/resized in y, the conditional cell state with a reference, deleting a *row*, and the tooltip of
the red "!" next to OK. The original job turned out to be an EasyBuilder job, so §0.1 (commented-out-cells bar)
could not be checked.

### Notes on how the survey was run

* The automation could not see ISVS menus/dialogs until access was also granted to its helper process
  `Cognex.Explorer.ProcHost.exe`. Property sheets sometimes ignored the first click (clicking their title bar
  first helped); tooltips never appeared in screenshots.
* The Windows input language was **VIE** (Vietnamese) during the session. Typing in cells triggered ISVS's own
  function-name autocomplete (`abc` became `Abs(`), and a quoted string `"abc"` could not be committed from the
  formula bar (Enter / ✓ had no effect, text stayed red) — so no literal-string cell was created. Formulas pasted
  into the formula bar (`B1*2`) committed normally.
* The image shown was a Record/Playback image (1920×552), not a fresh acquisition; no acquisition was triggered.
* Screenshots 21–130 and the files `backup-before-survey.jobx` and `snippet-B44-B47-script-formatstring.cxdx` are in
  `isvs-survey-2026-11/`. A copy of the backup was also left at
  `C:\Users\Admin\Documents\In-Sight Vision Suite\In-Sight\backup-before-survey.jobx`, and the snippet's original at
  `C:\Users\Admin\Documents\In-Sight Vision Suite\In-Sight\Snippets\`.
