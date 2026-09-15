"""
Generate CTX pair intersection polygons for 6 longitude swaths,
including only pairs where at least one image was acquired after 2017-12-01.

Polygon1/Polygon2 are row indices (FID) into the 2026 footprints shapefile:
    mars_mro_ctx_edr_c0a_2026/mars_mro_ctx_edr_c0a.shp

To use with PART2, update mainRef in PART2 to point at the 2026 footprints file.

Longitude convention in source data: 0-360 degrees.
"""

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import box
import os
import time

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PROJECT_DIR = r'G:\crater_flux_output_folders\Impact_flux_project'
FOOTPRINTS_2026 = os.path.join(PROJECT_DIR, 'mars_mro_ctx_edr_c0a_2026', 'mars_mro_ctx_edr_c0a.shp')
OUTPUT_SHP = os.path.join(PROJECT_DIR, 'CTX_pair_intersections_new_swaths.shp')

CUTOFF_DATE = '2017-12-01'

# Swaths: (lon_min, lon_max) in +/-180 degrees (matches actual shapefile geometry coords),
# all from lat -75 to +75.
# Note: attribute columns (CenterLon etc.) use 0-360 but polygon geometries use +/-180.
SWATHS = [
    (0,    10),
    (80,   90),
    (130,  140),
    (-180, -170),
    (-60,  -50),
    (-115, -100),  # 15 degrees wide
]
LAT_MIN, LAT_MAX = -75, 75

# Mars mean radius for area conversion (degrees -> km2)
MARS_RADIUS_KM = 3389.5
KM_PER_DEG_LAT = np.pi * 2 * MARS_RADIUS_KM / 360.0  # ~59.27 km/deg

# ---------------------------------------------------------------------------
# Load footprints
# ---------------------------------------------------------------------------

print('Loading 2026 footprints...')
t0 = time.time()
gdf = gpd.read_file(FOOTPRINTS_2026)
print(f'  Loaded {len(gdf):,} records in {time.time()-t0:.1f}s')

# Explicit FID column = row index (matches arcpy FID for shapefiles)
gdf = gdf.reset_index(drop=True)
gdf['FID'] = gdf.index

# Parse acquisition timestamps
gdf['UTCstart_dt'] = pd.to_datetime(gdf['UTCstart'], errors='coerce')
cutoff = pd.Timestamp(CUTOFF_DATE)
gdf['is_new'] = gdf['UTCstart_dt'] > cutoff
print(f'  New images (post {CUTOFF_DATE}): {gdf["is_new"].sum():,}')
print(f'  Oldest: {gdf["UTCstart_dt"].min()}')
print(f'  Newest: {gdf["UTCstart_dt"].max()}')

# ---------------------------------------------------------------------------
# Process each swath
# ---------------------------------------------------------------------------

all_results = []
pair_id = 0

for swath_lon_min, swath_lon_max in SWATHS:
    t1 = time.time()
    print(f'\nSwath {swath_lon_min}-{swath_lon_max} deg lon ...')
    swath_geom = box(swath_lon_min, LAT_MIN, swath_lon_max, LAT_MAX)

    # All images whose footprint touches this swath
    swath_mask = gdf.intersects(swath_geom)
    swath_gdf = gdf[swath_mask].reset_index(drop=True)
    print(f'  Images in swath: {len(swath_gdf):,}')

    new_in_swath = swath_gdf[swath_gdf['is_new']]
    print(f'  New images in swath: {len(new_in_swath):,}')

    if len(new_in_swath) == 0:
        print('  No new images — skipping.')
        continue

    # Spatial index over all images in this swath
    sindex = swath_gdf.sindex

    seen_pairs = set()
    swath_results = []

    for pos, new_row in enumerate(new_in_swath.itertuples(), 1):
        if pos % 500 == 0:
            print(f'    {pos}/{len(new_in_swath)} new images processed, '
                  f'{len(swath_results)} pairs so far ...')

        fid1 = new_row.FID
        geom1 = new_row.geometry

        # Candidate overlaps via spatial index (positional indices into swath_gdf)
        candidate_pos = list(sindex.query(geom1, predicate='intersects'))
        candidates = swath_gdf.iloc[candidate_pos]

        for other_row in candidates.itertuples():
            fid2 = other_row.FID

            if fid1 == fid2:
                continue

            # Skip if both images predate the cutoff — already in old shapefile
            if not new_row.is_new and not other_row.is_new:
                continue

            pair_key = (min(fid1, fid2), max(fid1, fid2))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            geom2 = other_row.geometry
            if not geom1.intersects(geom2):
                continue

            intersection = geom1.intersection(geom2)
            if intersection.is_empty:
                continue

            # Clip to swath bounding box
            intersection = intersection.intersection(swath_geom)
            if intersection.is_empty:
                continue

            # Area in km2 using Mars radius and centroid latitude correction
            lat_rad = np.radians(intersection.centroid.y)
            km_per_deg_lon = KM_PER_DEG_LAT * np.cos(lat_rad)
            area_km2 = intersection.area * KM_PER_DEG_LAT * km_per_deg_lon

            swath_results.append({
                'Id':        pair_id,
                'Polygon1':  pair_key[0],
                'Polygon2':  pair_key[1],
                'Area':      round(area_km2, 8),
                'upper_left': round(area_km2, 8),
                'geometry':  intersection,
            })
            pair_id += 1

    print(f'  Pairs in this swath: {len(swath_results):,}  '
          f'({time.time()-t1:.0f}s)')
    all_results.extend(swath_results)

# ---------------------------------------------------------------------------
# Write output
# ---------------------------------------------------------------------------

print(f'\nTotal pairs across all swaths: {len(all_results):,}')

if not all_results:
    print('No pairs found — nothing written.')
else:
    print(f'Writing {OUTPUT_SHP} ...')
    result_gdf = gpd.GeoDataFrame(all_results, crs=gdf.crs)
    # Match column order of existing CTX_pair_intersections.shp
    result_gdf = result_gdf[['Id', 'Polygon1', 'Polygon2', 'Area', 'upper_left', 'geometry']]
    # Drop degenerate intersections (points/lines where footprints only touch at edge/corner)
    before = len(result_gdf)
    result_gdf = result_gdf[result_gdf.geometry.geom_type.isin(['Polygon', 'MultiPolygon'])]
    dropped = before - len(result_gdf)
    if dropped:
        print(f'  Dropped {dropped:,} degenerate (point/line) intersections')
    result_gdf.to_file(OUTPUT_SHP)
    print(f'  Wrote {len(result_gdf):,} pairs.')
    print('Done.')
