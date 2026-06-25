# Impact Flux Project — To-Do List

## Calibration

- [ ] **Check whether junk calibration images pass the reference surface**
  Pairs 4,5,7,16,27,28 are hard-excluded from the surface definition but their region
  properties (PAR/ECC/CVA/ELN) have never been tested against it. Process them through
  the pipeline without including them in `datah`, run the surface check, and report/plot
  how many pass. Informs false-positive rate and surface discriminating power.

- [ ] **Resolve before/after ambiguity for the a/b TIF pairs**
  The 'a' vs 'b' file naming is inconsistent in the original TIFs for many pairs.
  Swap list is hardcoded in `make_previews.py`. Confirm whether calibration_master.csv
  ctx_before_id / ctx_after_id assignments are consistent with the corrected ordering.

## Pipeline validation

- [ ] **Assess pipeline recall against the 32 independent pre-2018 in-swath impacts**
  34 Daubar 2022 impacts are pre-2018, in-swath, and >=10m diameter. 2 are calibration
  impacts (cal 17 and cal 43). The remaining 32 are independent ground truth.
  Check how many were actually found by the pipeline in the processed output folders.
