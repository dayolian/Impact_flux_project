import geopandas as gpd
import pandas as pd
from shapely.geometry import box

FOOTPRINTS = r'G:\crater_flux_output_folders\Impact_flux_project\mars_mro_ctx_edr_c0a_2026\mars_mro_ctx_edr_c0a.shp'

SWATHS = [
    ('0-10',       0,    10),
    ('80-90',      80,   90),
    ('130-140',    130,  140),
    ('-180--170', -180, -170),
    ('-60--50',   -60,  -50),
    ('-115--100', -115, -100),
]
LAT_MIN, LAT_MAX = -75, 75

gdf = gpd.read_file(FOOTPRINTS)
gdf['UTCstart_dt'] = pd.to_datetime(gdf['UTCstart'], errors='coerce')

print(f"Total images (planet): {len(gdf):,}")
print(f"Newest image: {gdf['UTCstart_dt'].max()}")
print(f"Oldest image: {gdf['UTCstart_dt'].min()}")

all_swath = set()
print()
print(f"{'Swath':<14} {'Images in swath':>16}")
print('-' * 32)
for name, lon_min, lon_max in SWATHS:
    swath_geom = box(lon_min, LAT_MIN, lon_max, LAT_MAX)
    mask = gdf.intersects(swath_geom)
    idxs = set(gdf[mask].index)
    all_swath |= idxs
    print(f"{name:<14} {len(idxs):>16,}")

print('-' * 32)
print(f"{'TOTAL (unique)':<14} {len(all_swath):>16,}")
