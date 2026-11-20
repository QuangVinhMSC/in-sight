# Handoff: settle phase 1–5 open points on the camera, then patch

Written 2026-11-20 at the end of phase 5. Read first: `docs/isvs-spreadsheet-replica-plan.md` (§7 phase 5
"Behaviour chosen", §8 open questions). Memory notes: *ISVS live inspection* (Xephyr/Wine recipe, camera
backup, stale-editor pitfall) and *Running tests*.

State: phases 1–5 done, 136 tests pass (`/home/vinhdq/miniconda3/envs/insight-studio/bin/python -m pytest -q
--ignore=tests/test_live.py`; judge by "N passed", the interpreter segfaults at exit). **Everything since commit
8505c5e is uncommitted on `main`.** Ask the owner whether to commit before starting.

Camera: IS8902CX at 192.168.1.102, reachable on 2026-11-20 (ping OK, HTTP 302). ISVS was not running.

## Safety rules (every task below)

* Get the owner's OK before the first write to the camera. Keep it **offline**, never save a job on it, never
  put it online.
* Back up the active job first (HMI `saveJobData` with the current job name, into a local file), then work in
  scratch rows 590–599 (as `tests/test_live.py` does) or a File > New Job scratch job. Restore with
  `loadJobData` at the end.
* `loadJobData` returns 404 while an editor (ISVS) is attached. Close ISVS with
  `wine taskkill /im Cognex.Explorer.exe` (no `/F`) and never `wineserver -k` while it is connected: the camera
  then reports editorAttached for 20+ minutes.
* Do not drive ISVS against the camera without asking: it is slow under Wine and holds the editor lock.

## A. Checks with Insight Studio / HMI only (camera, no ISVS)

Write a small throw-away script (scratchpad), or extend `tests/test_live.py` (rows 590–599, cleared afterwards).
For each item: record the answer in the plan (§8), patch the code, and add or adjust a test (fake device in
`insight_studio/devtools/fake_insight.py` should then mimic the real answer).

1. **`beginEdit` Editing object.** For EditRegion, EditCircle, EditAnnulus, EditPolygon, EditCompositeRegion,
   EditMaskedRegion and EditPolylinePath: dump the object `beginEdit` returns and the cell result. What are
   the `$type` and the flag names (the code assumes `move`, `resize`/`size`, `rotate`, `bend`, `addRegion`,
   `removeRegion`, `editRegion`)? Is the result's `name` the function name or the cell name? Call `endEdit`
   each time.
   Patch: `editors.FLAG_KEYS` / `edit_flags`, `MainWindow.edit_graphic` (function-name fallback).
2. **Masked region geometry.** Insert `EditMaskedRegion($A$0,0,0,0,1,1,1,1,1,1,"M",2)`. Write a value with one
   and two masks, the way `GraphicEditor._sync_masks` builds it, and read it back. Does the device keep the
   masks? Does it change their x/y/h? The API example has masks offset in y. Also try an angled ROI.
   Patch: `GraphicEditor._build` (masked branch) and `_sync_masks`.
3. **Composite / polygon round trip.** Write a CompositeRegion with Add and Subtract subregions of all four
   shapes, and a Polygon with 5 points (`length`). Check that the read-back is the same and that the
   32-subregion limit is refused.
4. **Fixture transform.** Write `TrainPatMaxRedLine` (or `FindPatMaxRedLine`, Show = 2 input graphics) with
   fixture `(100,50,30)` and a literal region. Compare the input graphic the device draws with
   `property_sheet.fixture_transform` (translate, then rotate clockwise). Also check a fixture made of
   references to numeric cells.
   Patch: `fixture_transform`, `maximized_region`.
5. **Curve.** Set an EditRegion value with curve 30 and −30. Compare the device's graphic and image with
   `graphics._curved_region` and the bend-handle mapping (`RegionShape._bend`/`place_handles`: ±90° at the
   corners).
   Patch: the drawing, and the bend handle if its sign is reversed.
6. **Maximize.** Use Maximize Cell Region on an EditRegion (writes `(0,0,W,H,0,0)`). Is it accepted, and is W/H
   the right axis order on this firmware (`MainWindow._native_image_size`)?
7. **Phase 4 defaults (plan §8.9).** Insert TrainPatMaxRedLine, FindLine, FindBlobs and a Button through the
   app. Are the default expressions accepted?
8. **§8.6 message.** While an editor is attached, `loadJobData` should report "an editor is attached" instead of
   a raw HTTP 404 (`device.py`). Test this only if ISVS happens to be attached anyway.

## B. Needs ISVS driven live (ask the owner first; Xephyr recipe in memory)

Screenshots go to `~/Documents/insight-isvs-reference/live/` with the next free number.

* **Property sheet:** is a region parameter editable as soon as it is selected, or only after double-click/F9?
  Does the sheet stay visible? What do the bend and rotate handles do? What does the Train Event button do
  with `0`? Integer vs. 3-decimal fields for FindPatMaxRedLine, Caliper, DetectBlobs and ReadIDMax (fix
  `property_sheet._INTEGER_NAME` or replace the guess). When is Insert ▸ Function enabled?
* Capture the expressions ISVS writes on insert for FindPatMaxRedLine, Caliper and DetectBlobs (§8.9).
* §8.2 Script storage, §8.3 FormatString expression, §8.4 `.cxdx` export, §8.5 Insert Cell Name… dialog,
  §8.8 Cut/Copy/Undo semantics. These feed phases 6–8; just record the findings in the plan.

## C. Code only (no camera needed)

* ⊞/⊟ boxes on property sheet groups instead of Qt arrows (`property_sheet.TREE_STYLE`, branch images, or a
  delegate).
* Enable rules for Filter, WriteData, WriteImage, ImportData and ExportData (`tools/build_catalog.py`
  `ENABLE_RULES`): the builder warns because their controlling parameters are not parsed from the help
  tables. Regenerate `insight_studio/data/functions.json` afterwards.
* Optional: the spin-box arrow styling from `property_sheet.TREE_STYLE` for all spin boxes (`theme.STYLESHEET`).

## Where things are

| Topic | Code |
| --- | --- |
| Property sheet rows, enable rules, regions, Maximize | `insight_studio/property_sheet.py` (`region_spec`, `fixture`, `_emit_region`, `graphic_edited`, `_maximize`) |
| Interactive Graphics Mode | `insight_studio/editors.py` (`GraphicEditor`, `RegionShape`, `PolygonShape`, masks, menus) |
| Sheet ↔ image wiring | `MainWindow._property_sheet_region`, `_end_param_edit`, `edit_graphic`, `maximize_region` |
| Drawing graphics | `insight_studio/graphics.py` (`shape_path`, `_curved_region`) |
| Tests | `tests/test_editors.py`, `tests/test_property_sheet.py`, live: `tests/test_live.py` (`INSIGHT_HOST=192.168.1.102`) |

## Done when

Each answered question is marked in plan §8 with its date, the "Behaviour chosen" bullets in §7 phase 5 say
"verified" or are corrected, the code and tests are patched, the full suite passes, and the camera's original
job is restored. Then continue with phase 6.
