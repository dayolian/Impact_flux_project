"""Merge pairsinfo_with_tformscore.csv (G: drive swaths) and
pairsinfo_F_drive.csv (F: drive swaths) into a single master CSV.

Checks for duplicate wholepath entries and reports them before writing.
Output: pairsinfo_combo_master_alldata.csv in the Impact_flux_project folder.
"""

import pandas as pd
import os

G_CSV = r'G:\crater_flux_output_folders\Impact_flux_project\pairsinfo_with_tformscore.csv'
F_CSV = r'F:\pairsinfo_F_drive.csv'
OUT   = r'G:\crater_flux_output_folders\Impact_flux_project\pairsinfo_combo_master_alldata_2018-2026.csv'

print('Loading G: drive pairsinfo...')
df_g = pd.read_csv(G_CSV)
print(f'  {len(df_g):,} rows')

print('Loading F: drive pairsinfo...')
df_f = pd.read_csv(F_CSV)
print(f'  {len(df_f):,} rows')

combined = pd.concat([df_g, df_f], ignore_index=True)
print(f'\nCombined: {len(combined):,} rows')

# Check for duplicates
dupes = combined[combined.duplicated(subset='wholepath', keep=False)]
if len(dupes) > 0:
    print(f'WARNING: {len(dupes):,} duplicate wholepath entries found:')
    print(dupes['wholepath'].to_string())
else:
    print('No duplicate entries.')

combined.to_csv(OUT, index=False)
print(f'\nWritten to: {OUT}')

# Summary stats
print(f'\n--- Summary ---')
print(f'Total pairs:      {len(combined):,}')
print(f'Total hits:       {combined["hits"].sum():,.0f}')
print(f'Pairs with hits:  {(combined["hits"] > 0).sum():,}')
print(f'Mean reg score:   {combined["RegistrationScore"].mean():.3f}')
print(f'Total area (km²): {combined["areakm2"].sum():,.0f}')
