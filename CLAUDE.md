# Impact Flux Project — Claude Code Briefing

## Science Goal
Detect fresh impact craters on Mars using pairs of CTX (Context Camera) images taken at
different times over the same location. A "fresh crater" appears as a change between the
second (B) and first (A) image. The pipeline is deliberately conservative: false negatives
(missed craters) are much worse than false positives, so the automatic detection over-flags
heavily and human validation is the final filter.

## Directory Structure

### Root: G:\crater_flux_output_folders\
- `output_<lon1>_<lon2>_<lat1>_<lat2>\` — one folder per geographic region processed
  - `footprint_clipped_<tag>.shp` — shapefile of CTX pair intersections clipped to region
  - `<CTX_ID1>_<CTX_ID2>\` — one subfolder per image pair (thousands per output_ folder)
    - `<name>_clippedB.tif` — second image (geotiff, projected Mars coordinates)
    - `<name>_clippedA.tif` — first image
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

Output CSVs from the validation GUIs (confirmed_hits.csv, potential_hits.csv, interesting.csv)
are written to `G:\crater_flux_output_folders\` (not inside Impact_flux_project).

---

## Master CSV Files (Source of Truth)

All pairsinfo CSV files live in `G:\crater_flux_output_folders\Impact_flux_project\`.

### Canonical files — use these for all analysis

| File | Rows | Description |
|------|------|-------------|
| `pairsinfo_alldata_2006-2026.csv` | 401,649 | **ALL** processed pairs, both eras, no filters. Raw pipeline output. Use for computing statistics on total surveyed area, detection rates, and filtering efficiency. |
| `pairsinfo_reviewed_2006-2026.csv` | 43,440 | Pairs that passed review thresholds (hits ≤ 20, RegistrationScore ≥ 0.25, areakm2 > 0) and were shown to the human reviewer. Has `review_status`, `datetime1`, `datetime2`, `days_between` columns. Use for all science analysis. |

The ~358k row difference between the two files represents pairs excluded by filters:
zero-hit pairs, poorly registered pairs (score < 0.25), high-hit-count pairs (> 20 hits,
likely noise), and zero-area pairs.

### Intermediate / record-keeping files — do not use for analysis

| File | Rows | Notes |
|------|------|-------|
| `pairsinfo_combo_master_alldata_to2018.csv` | 140,389 | Raw output, 2006–2018 data only. Combined into canonical alldata file. |
| `pairsinfo_combo_master_alldata_2018-2026.csv` | 261,260 | Raw output, 2018–2026 data only (G: + F: drives). Combined into canonical alldata file. |
| `pairsinfo_with_tformscore_2018-2026_Gdrive-data.csv` | 160,726 | Raw output, 2018–2026 G: drive only (subset of above, pre-combination). |
| `pairsinfo_combo_master_max20hits_withdt.csv` | 19,195 | First GUI round (2006–2018), reviewed. Combined into canonical reviewed file. |
| `pairsinfo_combo_master_max20hits_withdt_2018-2026.csv` | 24,245 | Second GUI round (2018–2026), reviewed. Combined into canonical reviewed file. |
| `pairsinfo_combo_master_max20hits - Copy - all regis scores.csv` | 57,427 | Intermediate: hits ≤ 20 filtered but before RegistrationScore ≥ 0.25 cut was applied. Kept for record. |

### Dataset coverage
- **2006–2018**: pairs where both CTX images were acquired before the dataset cutoff
- **2018–2026**: pairs where at least one image was acquired after the cutoff
- The two eras are non-overlapping (no duplicate pairs between them)
- 2018–2026 data was split across G: and F: drives for processing speed; both are included
  in the combined files

---

## Pipeline (Fresh_Crater_Finder_and_Crops.m)

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
- *(No action = rejected - needs to be distinct from not reviewed yet)*

### Buttons per subfolder
- **Skip to next pair** — implies all remaining smaller hits (lower ARE, not yet shown)
  in this subfolder are rejected. Marks them as reviewed+rejected.
- **Poor registration** — flags entire subfolder as poorly registered, skips to next pair.
  Marks all unreviewed hits as rejected.

### Reviewed vs unreviewed distinction
Critical: must distinguish between:
- **Not yet seen** — hit_list processed=0, no GUI entry
- **Actively reviewed and rejected** — seen by reviewer or skipped with button, did not flag
- **Flagged** — confirmed, potential, or interesting

### Resume behavior
On relaunch, skip subfolders where all hits have a review status. Resume at the first
subfolder with any unreviewed hits, in RegistrationScore order.

### Output
Single consolidated validation results file (location outside the output_ folder tree).
Suggested columns: wholepath, pair_name, hit_prefix, ARE, x, y, label, reviewed_timestamp, lat, lon 
Need to reconstruct actual lat lon of anything flagged from x and y and the geotiffs in subfolder
Labels: confirmed_hit | potential_hit | interesting
Must also log accumulated sum of areakm2 of all subfolders completed thus far. 

### Data sources for GUI
- `pairsinfo_with_tformscore.csv` — for subfolder ordering by RegistrationScore
- `hit_list.csv` inside each pair subfolder — lists hits with prefix and processed flag
- JPEG files: `hit_{ARE}_{x}_{y}_before.jpg` / `hit_{ARE}_{x}_{y}_after.jpg`
- `targets.csv` — for ARE values if needed

### Tech stack
Starting fresh. Suggested: Python (Flask or FastAPI) backend serving a browser-based
frontend. JPEGs served as static files. State tracked server-side in the consolidated CSV.

