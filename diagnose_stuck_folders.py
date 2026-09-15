"""Read-only diagnostic: classify pair subfolders in a PART3 output folder.

Categories:
  - both_tifs_present : has clippedB.tif and clippedA.tif (PART2 succeeded,
                        not yet processed by PART3 or processing failed before delete)
  - missing_tifs      : missing one or both tifs (PART2 clip failed) -- these
                        are the "stuck" pairs: never recorded, never deleted
  - in_pairsinfo      : pair already has a row in pairsinfo_with_tformscore.csv
"""

import os
import pandas as pd

MAIN_DIR = r'G:\crater_flux_output_folders\Impact_flux_project'
TARGET_FOLDER = os.path.join(MAIN_DIR, 'output_new_0_10_-75_0')
PAIRSINFO = os.path.join(MAIN_DIR, 'pairsinfo_with_tformscore.csv')

print(f'Scanning: {TARGET_FOLDER}')
subdirs = [d for d in os.listdir(TARGET_FOLDER)
           if os.path.isdir(os.path.join(TARGET_FOLDER, d))]
print(f'Total subfolders found: {len(subdirs):,}')

print('Loading pairsinfo...')
df = pd.read_csv(PAIRSINFO)
in_pairsinfo = set(df['wholepath'].astype(str))

both_tifs = 0
missing_tifs = 0
in_csv = 0
not_in_csv_has_tifs = 0
not_in_csv_missing_tifs = 0
empty_folder = 0

for name in subdirs:
    pair_dir = os.path.join(TARGET_FOLDER, name)
    ctx1 = os.path.join(pair_dir, name + '_clippedB.tif')
    ctx2 = os.path.join(pair_dir, name + '_clippedA.tif')
    has_both = os.path.isfile(ctx1) and os.path.isfile(ctx2)
    is_recorded = pair_dir in in_pairsinfo

    contents = os.listdir(pair_dir)
    if len(contents) == 0:
        empty_folder += 1

    if has_both:
        both_tifs += 1
    else:
        missing_tifs += 1

    if is_recorded:
        in_csv += 1
    else:
        if has_both:
            not_in_csv_has_tifs += 1
        else:
            not_in_csv_missing_tifs += 1

print()
print(f'Both tifs present:        {both_tifs:,}')
print(f'Missing one/both tifs:    {missing_tifs:,}')
print(f'Completely empty folder:  {empty_folder:,}')
print(f'Already in pairsinfo:     {in_csv:,}')
print()
print(f'NOT in pairsinfo, has tifs (should be processed):     {not_in_csv_has_tifs:,}')
print(f'NOT in pairsinfo, missing tifs (the "stuck" pairs):   {not_in_csv_missing_tifs:,}')
