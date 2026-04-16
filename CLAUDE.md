# Impact Flux Project — Claude Code Briefing

## Science Goal
Detect fresh impact craters on Mars using pairs of CTX (Context Camera) images taken at
different times over the same location. A "fresh crater" appears as a change between the
before (B) and after (A) image. The pipeline is deliberately conservative: false negatives
(missed craters) are much worse than false positives, so the automatic detection over-flags
heavily and human validation is the final filter.

## Repository
GitHub: https://github.com/dayolian/Impact_flux_project
Branch: main
Primary script: Fresh_Crater_Finder_and_Crops.m

## Directory Structure

### Root: G:\crater_flux_output_folders\
- `output_<lon1>_<lon2>_<lat1>_<lat2>\` — one folder per geographic region processed
  - `footprint_clipped_<tag>.shp` — shapefile of CTX pair intersections clipped to region
  - `<CTX_ID1>_<CTX_ID2>\` — one subfolder per image pair (thousands per output_ folder)
    - `<name>_clippedB.tif` — before image (geotiff, projected Mars coordinates)
    - `<name>_clippedA.tif` — after image
    - `candidates_t.mat` — MATLAB struct: ctxID, bx, by, LOC_pass, ARE_pass, PAR_pass,
                            ECC_pass, CVA_pass. Written even if zero hits.
    - `targets.csv` — same data as candidates_t in CSV form. EXISTS = pipeline ran for
                      this pair. Columns: LOC_pass_1, LOC_pass_2, ARE_pass, PAR_pass,
                      CVA_pass, ECC_pass. Empty rows = no hits.
    - `hit_list.csv` — one row per hit. Columns: prefix, processed.
                       prefix = hit_{ARE}_{x}_{y} matching jpeg filenames.
                       processed = 0 (unreviewed), set to 1 by GUI when assessed.
    - `hit_{ARE}_{x}_{y}_before.jpg` — cropped 100x100px before image around hit
    - `hit_{ARE}_{x}_{y}_after.jpg`  — cropped 100x100px after image around hit
- `pairsinfo_with_tformscore.csv` — master table, one row per pair subfolder. Columns:
    wholepath, ctxID, centerlon, centerlat, areakm2, hits, hitratio, RegistrationScore
- `folder_summary.csv` — one row per output_ folder. Columns:
    output_folder, total_pairs, has_candidates_t, has_both
- `impact_reference.mat` — reference surface for detection tuning (xgrid,ygrid,zgrid,elngrid)
- `CTX_pair_intersections.shp` — full-planet CTX image overlap shapefile

### Subfolder: Impact_flux_project\
Contains the scripts, this CLAUDE.md, and the GitHub repo.

## Pipeline (Fresh_Crater_Finder_and_Crops.m)

### What it does (in order):
1. Loads `impact_reference.mat` and master tables
2. Iterates over all `output_*` folders, then all pair subfolders within each
3. **Skip logic**: if `targets.csv` AND `hit_list.csv` both exist → pair already processed.
   Still checks pairsinfo_with_tformscore.csv and backfills the row if missing/incomplete
   (re-runs alignment to get real RegistrationScore if needed).
4. Loads both geotiffs, computes areakm2 (valid pixel count × pixel area, NOT bounding box —
   images are tilted along orbital track so bounding box overestimates area)
5. Preprocesses: uint8 → NaN out 0/255 (nodata) → int16 → contrast stretch
6. Alignment: imregcorr at 1/15 scale to get translation transform + RegistrationScore
7. Binary difference map → threshold (dt=0.35) → region filtering (ma=35 to 12000 px)
8. Compares region properties against reference surface (CVA, ELN checks)
9. Edge removal
10. Writes candidates_t.mat, targets.csv, hit_list.csv (always, even if zero hits)
11. Crops and saves JPEGs for each hit (100×100px)
12. Updates pairsinfo_with_tformscore.csv

### Key parameters:
- `dt = 0.35` — difference threshold
- `ma = 35` — minimum region area in pixels
- `scale = 15` — alignment downscale factor
- `crop_size = 100` — JPEG crop size in pixels
- `save_interval = 50` — how often to flush master table to disk
- Nodata values: 0 (black) and 255 (white) — excluded from area calc and preprocessing
- RegistrationScore = 0 is a valid result from imregcorr (not a sentinel for "missing")

### Output folders processed:
Root `output_*` folders in G:\crater_flux_output_folders (27 total).
Impact_flux_project has 4 additional output_ folders with same structure.
Script currently filters to `startsWith('output_')` — check line ~104 for any test filter.

## GUI Task (NEXT — build this)

### Goal
Manual validation interface for the cropped JPEG hit pairs. Serves before/after crops that
blink automatically so the reviewer can assess whether the detected change is a real fresh
crater.

### Reviewer
Single user (Mackenzie Day), solo validation.

### Display
- Show many blink pairs at once — target 6×3 grid or more depending on screen fit
- Each cell shows one hit: before/after JPEGs blinking automatically (auto-toggle ~0.5s)
- Hits within a subfolder shown in descending order of ARE (area in pixels, from filename)
- If all hits don't fit on one page, paginate within the subfolder

### Subfolder ordering
- Process subfolders in descending order of RegistrationScore from pairsinfo_with_tformscore.csv
- High registration score = images well-aligned = more trustworthy detections → review first

### Buttons per hit
- **Confirmed hit** — real fresh crater
- **Potential hit** — needs more investigation
- **Interesting (not crater)** — something worth logging for other projects
- *(No action = not reviewed yet — distinct from actively rejected)*

### Buttons per subfolder
- **Skip to next pair** — implies all remaining smaller hits (lower ARE, not yet shown)
  in this subfolder are rejected. Marks them as reviewed+rejected.
- **Poor registration** — flags entire subfolder as poorly registered, skips to next pair.
  Marks all unreviewed hits as rejected.

### Reviewed vs unreviewed distinction
Critical: must distinguish between:
- **Not yet seen** — hit_list processed=0, no GUI entry
- **Actively reviewed and rejected** — seen by reviewer, did not flag
- **Skipped (implicitly rejected)** — below the skip threshold in that subfolder
- **Flagged** — confirmed, potential, or interesting

### Resume behavior
On relaunch, skip subfolders where all hits have a review status. Resume at the first
subfolder with any unreviewed hits, in RegistrationScore order.

### Output
Single consolidated validation results file (location TBD, outside the output_ folder tree).
Suggested columns: wholepath, pair_name, hit_prefix, ARE, x, y, label, reviewed_timestamp
Labels: confirmed_hit | potential_hit | interesting | rejected_active | rejected_skipped |
        rejected_poor_registration

### Data sources for GUI
- `pairsinfo_with_tformscore.csv` — for subfolder ordering by RegistrationScore
- `hit_list.csv` inside each pair subfolder — lists hits with prefix and processed flag
- JPEG files: `hit_{ARE}_{x}_{y}_before.jpg` / `hit_{ARE}_{x}_{y}_after.jpg`
- `targets.csv` — for ARE values if needed

### Tech stack
Starting fresh. Suggested: Python (Flask or FastAPI) backend serving a browser-based
frontend. JPEGs served as static files. State tracked server-side in the consolidated CSV.
Previous draft files (draftGUI.html, server.py) in root dir are NOT the starting point.

## Key Decisions Already Made
- areakm2 uses pixel counting, not bounding box
- RegistrationScore=0 is valid, not a missing-data sentinel; NaN = truly missing
- All pairs get targets.csv + hit_list.csv written (even zero-hit pairs) so skip logic works
- TextType='string' used in all readtable calls to avoid cell/string assignment errors
- The pipeline massively over-detects by design — GUI validation is the true filter
