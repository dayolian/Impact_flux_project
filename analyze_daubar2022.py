"""
Analysis of Daubar et al. 2022 fresh impact database against:
  1. The 6 study-area swaths
  2. CTX detectability thresholds
  3. Calibration set overlap
  4. General context for the impact flux project

NOTE: Column headers in the spreadsheet are swapped —
  'Latitude (deg E, centric)' actually contains latitude values
  'Longitude (deg N)' actually contains 0-360 East longitudes
"""

import pandas as pd
import numpy as np

XLSX = r'G:\crater_flux_output_folders\Impact_flux_project\Daubaretal2022_database_SI.xlsx'

df = pd.read_excel(XLSX, sheet_name='Sheet1')

# Fix swapped column names
df = df.rename(columns={
    'Latitude (deg E, centric)': 'lat',
    'Longitude (deg N)':         'lon_360',
    'HiRISE Observation ID':     'hirise_id',
    'Diameter (m)':              'diameter_m',
    'Date of image':             'hirise_date',
    'Before Image Instrument':   'before_inst',
    'Before Image ID':           'before_id',
    'Before Image Date':         'before_date',
    'After Image Instrument':    'after_inst',
    'After Image ID':            'after_id',
    'After Image Date':          'after_date',
    'Single or cluster':         'single_cluster',
    'Ice-exposing impact':       'ice_exposing',
    'Halo':                      'halo',
    'Mars Year of image':        'mars_year',
    'Reference for previously published diameter ': 'prev_ref',
})

df['lon_180'] = df['lon_360'].apply(lambda x: x if x <= 180 else x - 360)

print(f"Total impacts in Daubar 2022: {len(df)}")
print(f"Lat range:  {df['lat'].min():.2f} to {df['lat'].max():.2f}")
print(f"Lon range (0-360): {df['lon_360'].min():.2f} to {df['lon_360'].max():.2f}")
print(f"Diameter range: {df['diameter_m'].min():.1f} to {df['diameter_m'].max():.1f} m")
print(f"Median diameter: {df['diameter_m'].median():.1f} m")
print(f"Missing diameters: {df['diameter_m'].isna().sum()}")

# ---------------------------------------------------------------------------
# 1. STUDY SWATH MEMBERSHIP
# ---------------------------------------------------------------------------
# All swaths span lat -75 to +75
LAT_S, LAT_N = -75, 75

swaths = {
    '0-10E':       (0,    10),
    '80-90E':      (80,   90),
    '130-140E':    (130, 140),
    '180-190E':    (180, 190),   # = -180 to -170W
    '300-310E':    (300, 310),   # = -60 to -50W
    '245-260E':    (245, 260),   # = -115 to -100W  (15-deg wide)
}

def in_swath(row, lon_min, lon_max):
    return (lon_min <= row['lon_360'] <= lon_max) and (LAT_S <= row['lat'] <= LAT_N)

df['in_any_swath'] = False
for name, (lo, hi) in swaths.items():
    mask = df.apply(lambda r: in_swath(r, lo, hi), axis=1)
    df[f'swath_{name}'] = mask
    df['in_any_swath'] |= mask

swath_cols = [f'swath_{n}' for n in swaths]
in_swath_df = df[df['in_any_swath']]

print(f"\n{'='*60}")
print("STUDY SWATH COVERAGE")
print(f"{'='*60}")
print(f"Total within any swath: {df['in_any_swath'].sum()} / {len(df)} "
      f"({df['in_any_swath'].mean()*100:.1f}%)")
print()
for name, (lo, hi) in swaths.items():
    col = f'swath_{name}'
    n = df[col].sum()
    lon_label = f"{lo}-{hi}E"
    print(f"  {lon_label:12s}: {n:4d} impacts")

# ---------------------------------------------------------------------------
# 2. CTX DETECTABILITY
# ---------------------------------------------------------------------------
# CTX pixel scale: ~5.3 m/px (matches calibration TIFs)
# Pipeline minimum area filter: 35 px  =>  min change-area ~983 m²  (~35m equiv. dia)
# Empirical calibration set:
#   - Smallest detected crater: 1.7 m (D13 site 4, but marked junk)
#   - Faint/missed craters: 3.5 m (site 14) and 6.0 m (site 10)
#   - Reliable detection empirically starts around ~7-8 m crater diameter
# The pipeline detects the CHANGE AREA (blast zone/halo), not the crater itself.
# Halo:crater diameter ratios on Mars typically 3-20x for fresh CTX-visible impacts.
# Conservative CTX detection threshold: crater diam > ~5m (detectable but marginal)
# Practical reliable threshold: crater diam > ~10m

CTX_MARGINAL  = 5.0   # m — detectable in favourable conditions
CTX_RELIABLE  = 10.0  # m — reliably detectable

print(f"\n{'='*60}")
print("CTX DETECTABILITY (by HiRISE-measured crater diameter)")
print(f"{'='*60}")
print(f"Note: Pipeline detects change area (halo/blast), not crater itself.")
print(f"Calibration set empirical limits: missed craters at 3.5m and 6.0m.")
print()

bins = [0, 2, 5, 10, 20, 50, 100, 500, 10000]
labels = ['<2m','2-5m','5-10m','10-20m','20-50m','50-100m','100-500m','>500m']
df['size_bin'] = pd.cut(df['diameter_m'], bins=bins, labels=labels, right=True)
size_counts = df['size_bin'].value_counts().sort_index()

for lbl, cnt in size_counts.items():
    pct = cnt / len(df) * 100
    note = ''
    if bins[labels.index(lbl)] < CTX_MARGINAL:
        note = '<-- likely below CTX sensitivity'
    elif bins[labels.index(lbl)] < CTX_RELIABLE:
        note = '<-- marginal CTX detectability'
    print(f"  {lbl:10s}: {cnt:4d}  ({pct:4.1f}%)  {note}")

below_marginal = (df['diameter_m'] < CTX_MARGINAL).sum()
marginal       = ((df['diameter_m'] >= CTX_MARGINAL) & (df['diameter_m'] < CTX_RELIABLE)).sum()
detectable     = (df['diameter_m'] >= CTX_RELIABLE).sum()

print(f"\n  Likely undetectable by CTX (<{CTX_MARGINAL}m):       {below_marginal:4d}  ({below_marginal/len(df)*100:.1f}%)")
print(f"  Marginal CTX detection ({CTX_MARGINAL}-{CTX_RELIABLE}m):     {marginal:4d}  ({marginal/len(df)*100:.1f}%)")
print(f"  Reliably CTX-detectable (>={CTX_RELIABLE}m):        {detectable:4d}  ({detectable/len(df)*100:.1f}%)")

# In-swath + detectable
in_swath_det = df[df['in_any_swath'] & (df['diameter_m'] >= CTX_RELIABLE)]
print(f"\n  In swath AND reliably CTX-detectable:  {len(in_swath_det):4d}")
in_swath_marg = df[df['in_any_swath'] & (df['diameter_m'] >= CTX_MARGINAL)]
print(f"  In swath AND marginal+reliable:        {len(in_swath_marg):4d}")

# ---------------------------------------------------------------------------
# 3. BEFORE/AFTER IMAGE INSTRUMENTS
# ---------------------------------------------------------------------------
print(f"\n{'='*60}")
print("BEFORE/AFTER IMAGE INSTRUMENTS")
print(f"{'='*60}")
print("\nBefore image instrument:")
print(df['before_inst'].value_counts().to_string())
print("\nAfter image instrument (HiRISE targets the change):")
print(df['after_inst'].value_counts().to_string())

ctx_before = df['before_inst'].str.upper().str.contains('CTX', na=False)
ctx_after  = df['after_inst'].str.upper().str.contains('CTX', na=False)
print(f"\n  Before = CTX: {ctx_before.sum()}  ({ctx_before.mean()*100:.1f}%)")
print(f"  After  = CTX: {ctx_after.sum()}   ({ctx_after.mean()*100:.1f}%)")
print(f"  Both CTX:     {(ctx_before & ctx_after).sum()}")

# ---------------------------------------------------------------------------
# 4. CALIBRATION SET OVERLAP
# ---------------------------------------------------------------------------
print(f"\n{'='*60}")
print("CALIBRATION SET OVERLAP WITH DAUBAR 2022")
print(f"{'='*60}")
# Our calibration impacts (0-360 lon)
cal = [
    ( 1, 259.508,  9.051,'good'), ( 2, 188.579, 25.605,'good'),
    ( 3, 268.849, 14.527,'good'), ( 4, 273.985, -6.241,'junk'),
    ( 5, 287.827, -2.952,'junk'), ( 6, 266.216, 15.652,'good'),
    ( 7, 233.131, -1.928,'junk'), ( 8, 176.886, 46.354,'good'),
    ( 9, 246.569, -2.020,'good'), (10, 236.034, -6.018,'faint'),
    (11, 250.767,  2.912,'good'), (12, 255.011, 11.479,'good'),
    (13, 177.892,  5.544,'good'), (14, 186.484, 10.599,'faint'),
    (15, 201.395,  4.431,'good'), (16, 217.642, -8.879,'junk'),
    (17, 248.912, -0.632,'good'), (18, 259.395, -6.847,'good'),
    (19, 246.710, -4.168,'good'), (20, 235.098,  3.242,'good'),
    (21, 279.364,  4.866,'good'), (22, 279.799, 24.106,'good'),
    (23,  37.832, -0.964,'good'), (24, 178.252, 30.494,'good'),
    (25, 183.965, -2.566,'good'), (26, 245.290, 24.921,'good'),
    (27, 219.235, 30.792,'junk'), (28, 250.787,-13.995,'junk'),
    (29, 245.189,  7.495,'good'), (30, 271.465, 12.332,'good'),
    (31, 185.502, 40.341,'good'), (32, 133.705, 46.611,'good'),
    (33,  53.382,  3.119,'good'), (34, 126.305, 41.019,'good'),
    (35, 202.796, 18.936,'good'), (36, 112.394, 32.251,'good'),
    (37, 196.488, 12.272,'good'), (38, 246.894,  4.473,'good'),
    (39, 275.991,  3.703,'good'), (40, 291.109, 24.584,'good'),
    (41, 201.609, 35.907,'good'), (42, 246.831,  3.291,'good'),
    (43, 248.523,  2.579,'good'),
]
matched_in_22 = 0
for (cid, clon, clat, ccat) in cal:
    dists = np.sqrt((df['lat'] - clat)**2 +
                    np.minimum(np.abs(df['lon_360'] - clon), 360 - np.abs(df['lon_360'] - clon))**2)
    if dists.min() < 0.05:
        matched_in_22 += 1
print(f"Calibration impacts also present in Daubar 2022: {matched_in_22} / 43")

# ---------------------------------------------------------------------------
# 5. TEMPORAL COVERAGE
# ---------------------------------------------------------------------------
print(f"\n{'='*60}")
print("TEMPORAL COVERAGE")
print(f"{'='*60}")
df['hirise_date'] = pd.to_datetime(df['hirise_date'], errors='coerce')
df['year'] = df['hirise_date'].dt.year
yr = df['year'].dropna()
print(f"HiRISE observation dates: {int(yr.min())} - {int(yr.max())}")
print(f"By year:")
print(df['year'].value_counts().sort_index().to_string())

# ---------------------------------------------------------------------------
# 6. PER-SWATH BREAKDOWN BY SIZE
# ---------------------------------------------------------------------------
print(f"\n{'='*60}")
print("PER-SWATH SIZE BREAKDOWN (CTX-detectable only, diam >= 5m)")
print(f"{'='*60}")
for name, (lo, hi) in swaths.items():
    sub = df[df[f'swath_{name}'] & (df['diameter_m'] >= CTX_MARGINAL)]
    rel = df[df[f'swath_{name}'] & (df['diameter_m'] >= CTX_RELIABLE)]
    tot = df[df[f'swath_{name}']]
    if len(tot) == 0:
        continue
    print(f"\n  {name} ({lo}-{hi}E): {len(tot)} total, "
          f"{len(sub)} marginal+reliable (>={CTX_MARGINAL}m), "
          f"{len(rel)} reliable (>={CTX_RELIABLE}m)")
    if len(tot):
        print(f"    Diameters: min={tot['diameter_m'].min():.1f}m  "
              f"median={tot['diameter_m'].median():.1f}m  "
              f"max={tot['diameter_m'].max():.1f}m")

# ---------------------------------------------------------------------------
# 7. SUMMARY TABLE FOR SAVING
# ---------------------------------------------------------------------------
out = df[['hirise_id','lat','lon_360','lon_180','diameter_m','single_cluster',
          'ice_exposing','halo','mars_year','hirise_date',
          'before_inst','before_id','before_date',
          'after_inst','after_id','after_date',
          'in_any_swath','size_bin'] + swath_cols + ['prev_ref']].copy()
out.to_csv(r'G:\crater_flux_output_folders\Impact_flux_project\daubar2022_annotated.csv', index=False)
print(f"\n\nAnnotated CSV saved: daubar2022_annotated.csv")
