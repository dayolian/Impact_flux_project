"""
For each of the 43 calibration impact craters, find which CTX EDR image
footprints contain that point, using the global CTX shapefile.
Outputs a CSV and a printed summary.
"""

import geopandas as gpd
from shapely.geometry import Point
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

SHP = r'G:\crater_flux_output_folders\mars_mro_ctx_edr_c0a.shp'
OUT_CSV = r'G:\crater_flux_output_folders\Impact_flux_project\calibration_ctx_sources.csv'

impacts = [
    ( 1,-100.492,  9.051,'good'),
    ( 2,-171.421, 25.605,'good'),
    ( 3, -91.151, 14.527,'good'),
    ( 4, -86.015, -6.241,'junk'),
    ( 5, -72.173, -2.952,'junk'),
    ( 6, -93.784, 15.652,'good'),
    ( 7,-126.869, -1.928,'junk'),
    ( 8, 176.886, 46.354,'good'),
    ( 9,-113.431, -2.020,'good'),
    (10,-123.966, -6.018,'faint'),
    (11,-109.233,  2.912,'good'),
    (12,-104.989, 11.479,'good'),
    (13, 177.892,  5.544,'good'),
    (14,-173.516, 10.599,'faint'),
    (15,-158.605,  4.431,'good'),
    (16,-142.358, -8.879,'junk'),
    (17,-111.088, -0.632,'good'),
    (18,-100.605, -6.847,'good'),
    (19,-113.290, -4.168,'good'),
    (20,-124.902,  3.242,'good'),
    (21, -80.636,  4.866,'good'),
    (22, -80.201, 24.106,'good'),
    (23,  37.832, -0.964,'good'),
    (24, 178.252, 30.494,'good'),
    (25,-176.035, -2.566,'good'),
    (26,-114.710, 24.921,'good'),
    (27,-140.765, 30.792,'junk'),
    (28,-109.213,-13.995,'junk'),
    (29,-114.811,  7.495,'good'),
    (30, -88.535, 12.332,'good'),
    (31,-174.498, 40.341,'good'),
    (32, 133.705, 46.611,'good'),
    (33,  53.382,  3.119,'good'),
    (34, 126.305, 41.019,'good'),
    (35,-157.204, 18.936,'good'),
    (36, 112.394, 32.251,'good'),
    (37,-163.512, 12.272,'good'),
    (38,-113.106,  4.473,'good'),
    (39, -84.009,  3.703,'good'),
    (40, -68.891, 24.584,'good'),
    (41,-158.391, 35.907,'good'),
    (42,-113.169,  3.291,'good'),
    (43,-111.477,  2.579,'good'),
]

pts = gpd.GeoDataFrame(
    [(r[0], r[1], r[2], r[3]) for r in impacts],
    columns=['impact_id', 'lon', 'lat', 'category'],
    geometry=[Point(r[1], r[2]) for r in impacts],
    crs='EPSG:4326'
)

print('Loading CTX shapefile (may take a minute)...')
ctx = gpd.read_file(SHP, columns=['ProductId', 'UTCstart', 'geometry'])
ctx = ctx.set_crs('EPSG:4326', allow_override=True)
print(f'Loaded {len(ctx):,} CTX footprints')

print('Running spatial join...')
joined = gpd.sjoin(pts, ctx, how='left', predicate='within')
joined = joined.sort_values(['impact_id', 'UTCstart'])
print('Done.\n')

rows = []
for iid, grp in joined.groupby('impact_id'):
    rec = next(r for r in impacts if r[0] == iid)
    lon, lat, cat = rec[1], rec[2], rec[3]
    hits = grp.dropna(subset=['ProductId'])
    print(f'--- Impact {iid:>2} ({cat:5})  lon={lon:8.3f}  lat={lat:6.3f} ---')
    if hits.empty:
        print('  NO CTX FOOTPRINT FOUND')
        rows.append(dict(impact_id=iid, lon=lon, lat=lat, category=cat,
                         n_ctx=0, ProductId='NONE', UTCstart=''))
    else:
        print(f'  {len(hits)} CTX image(s):')
        for _, row in hits.iterrows():
            pid = row['ProductId']
            utc = row['UTCstart']
            print(f'    {pid:40s}  {utc}')
            rows.append(dict(impact_id=iid, lon=lon, lat=lat, category=cat,
                             n_ctx=len(hits), ProductId=pid, UTCstart=utc))

out = pd.DataFrame(rows)
out.to_csv(OUT_CSV, index=False)
print(f'\nSaved: {OUT_CSV}')
