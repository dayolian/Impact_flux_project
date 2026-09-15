import geopandas as gpd
from shapely.geometry import box

SWATHS = [
    ('0-10',       0,    10),
    ('80-90',      80,   90),
    ('130-140',    130,  140),
    ('-180--170', -180, -170),
    ('-60--50',   -60,  -50),
    ('-115--100', -115, -100),
]
LAT_MIN, LAT_MAX = -75, 75

NEW_COUNTS = {
    '0-10':       37038,
    '80-90':      23018,
    '130-140':    67681,
    '-180--170':  62140,
    '-60--50':    38086,
    '-115--100':  68842,
}

print('Loading old pairs shapefile (1.4M records, may take a minute)...')
old = gpd.read_file(r'G:\crater_flux_output_folders\Impact_flux_project\CTX_pair_intersections.shp')
print(f'Total old pairs: {len(old):,}')
print()
print(f"{'Swath':<14} {'Old pairs':>12} {'New pairs':>12} {'New/Old':>10}")
print('-' * 52)

total_old = 0
total_new = 0
for name, lon_min, lon_max in SWATHS:
    swath_geom = box(lon_min, LAT_MIN, lon_max, LAT_MAX)
    old_count = int(old.intersects(swath_geom).sum())
    new_count = NEW_COUNTS[name]
    ratio = new_count / old_count if old_count else float('inf')
    print(f"{name:<14} {old_count:>12,} {new_count:>12,} {ratio:>10.2f}x")
    total_old += old_count
    total_new += new_count

print('-' * 52)
print(f"{'TOTAL':<14} {total_old:>12,} {total_new:>12,} {total_new/total_old:.2f}x")
