# PART2 v2 — Clip downloaded CTX image pairs to their overlap polygons.
#
# Changes from PART2 (original):
#   - arcpy replaced entirely with rasterio (clip) and geopandas (shapefile)
#   - mainRef updated to 2026 footprints
#   - UTCstart used to assign before/after correctly: clippedB is always the
#     earlier image, clippedA the later one, regardless of FID order.
#     (Original used FID order which is not guaranteed to match date order.)
#   - ThreadPoolExecutor parallelises the clip step (one thread per pair)
#   - argparse: bounds and tag passed as CLI args, no file editing per swath
#   - Robust subfolder handling: skips pairs whose output folder already
#     exists so the script is safe to re-run after interruption
#   - Raw tiff deletion happens after ALL pairs are clipped, with a
#     per-image check that all its pairs were successfully processed
#   - clip_pairs.csv written with one pair directory name per row
#     (compatible with downstream MATLAB scripts)
#
# Usage:
#   python PART2_v2.py --lon1 0 --lon2 10 --lat1 -75 --lat2 75 --tag Swath0_10
#
# Requires rasterio, geopandas, pyproj (pip install rasterio geopandas)
#
# Updated June 2026 — Impact Flux Project, GALE Lab UCLA

import argparse
import csv
import os
import sys
import threading

import geopandas as gpd
import pandas as pd
import rasterio
from rasterio.mask import mask as rio_mask
from rasterio.crs import CRS
from pyproj import Transformer
from shapely.ops import transform as shp_transform
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
FOOTPRINTS  = os.path.join(SCRIPT_DIR, 'mars_mro_ctx_edr_c0a_2026',
                            'mars_mro_ctx_edr_c0a.shp')

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(
    description='Clip downloaded CTX pairs to overlap polygons.')
parser.add_argument('--lon1',       type=float, required=True)
parser.add_argument('--lon2',       type=float, required=True)
parser.add_argument('--lat1',       type=float, required=True)
parser.add_argument('--lat2',       type=float, required=True)
parser.add_argument('--tag',        type=str,   required=True)
parser.add_argument('--workers',    type=int,   default=4,
                    help='Parallel clip threads (default 4; IO-bound)')
parser.add_argument('--keep-tiffs', action='store_true',
                    help='Do not delete raw tiffs after clipping')
parser.add_argument('--output-dir', type=str,   default=None,
                    help='Root directory containing the output_new_ folder (default: script directory)')
args = parser.parse_args()

x1, x2, y1, y2 = args.lon1, args.lon2, args.lat1, args.lat2
tag        = args.tag
workers    = args.workers
output_dir = args.output_dir if args.output_dir else SCRIPT_DIR

def _fmt(v):
    return str(int(v)) if v == int(v) else str(v)

delin     = '_'
bounds    = delin.join([_fmt(x1), _fmt(x2), _fmt(y1), _fmt(y2)])
path      = os.path.join(output_dir, 'output_new_' + bounds)
fc        = os.path.join(path, 'footprint_clipped_' + tag + '.shp')
deep_path = path + os.sep

if not os.path.isdir(path):
    print(f'Output folder not found: {path}')
    sys.exit(1)

if not os.path.exists(fc):
    print(f'Clipped footprint shapefile not found: {fc}')
    print('Run PART1_v2.py first.')
    sys.exit(1)

# ---------------------------------------------------------------------------
# Load clipped pairs shapefile
# ---------------------------------------------------------------------------
print('Loading clipped pairs shapefile...')
clipped = gpd.read_file(fc)
print(f'  {len(clipped):,} pairs')

# ---------------------------------------------------------------------------
# Load footprints: FID -> ProductId, UTCstart
# ---------------------------------------------------------------------------
print('Loading 2026 footprints...')
footprints = gpd.read_file(FOOTPRINTS, columns=['ProductId', 'UTCstart'])
footprints = footprints.reset_index(drop=True)
footprints['FID'] = footprints.index
footprints['UTCstart_dt'] = pd.to_datetime(footprints['UTCstart'], errors='coerce')
FOOTPRINTS_CRS = footprints.crs
fid_to_ctxid  = dict(zip(footprints['FID'], footprints['ProductId']))
fid_to_utc    = dict(zip(footprints['FID'], footprints['UTCstart_dt']))
print(f'  {len(footprints):,} footprint records loaded.')

unique_fids = set(clipped['Polygon1']) | set(clipped['Polygon2'])
print(f'  Unique images referenced by pairs: {len(unique_fids):,}')

# ---------------------------------------------------------------------------
# Clip function (rasterio, replaces arcpy.Clip_management)
# ---------------------------------------------------------------------------

def _reproject_geom(geom, tiff_crs_wkt):
    """Reproject a shapely geometry from the footprints CRS to the tiff CRS."""
    tiff_crs = CRS.from_wkt(tiff_crs_wkt)
    if FOOTPRINTS_CRS == tiff_crs:
        return geom
    transformer = Transformer.from_crs(
        FOOTPRINTS_CRS,
        tiff_crs,
        always_xy=True,
    )
    return shp_transform(transformer.transform, geom)


_print_lock = threading.Lock()

def clip_pair(fid_before, fid_after, overlap_geom, ctr, total):
    """Clip both images in a pair to their overlap polygon.

    fid_before: FID of the earlier image  -> written as clippedB.tif
    fid_after:  FID of the later image    -> written as clippedA.tif
    overlap_geom: shapely geometry of the intersection polygon

    Returns (results_dir_name, success_bool)
    """
    ctx_before = fid_to_ctxid[fid_before]
    ctx_after  = fid_to_ctxid[fid_after]

    results_dir_name = f'{ctx_before}_{ctx_after}'
    results_dir      = os.path.join(deep_path, results_dir_name)
    file_b = os.path.join(results_dir, f'{ctx_before}_{ctx_after}_clippedB.tif')
    file_a = os.path.join(results_dir, f'{ctx_before}_{ctx_after}_clippedA.tif')

    # Skip if already done (safe to re-run)
    if os.path.exists(file_b) and os.path.exists(file_a):
        with _print_lock:
            print(f'  [{ctr}/{total}] Already clipped, skipping: {results_dir_name}')
        return results_dir_name, True

    try:
        os.makedirs(results_dir, exist_ok=True)
    except OSError as e:
        with _print_lock:
            print(f'  [{ctr}/{total}] Cannot create dir {results_dir}: {e}')
        return results_dir_name, False

    src_before = os.path.join(deep_path, ctx_before + '.tiff')
    src_after  = os.path.join(deep_path, ctx_after  + '.tiff')

    for src_path, dest_path, label in [
        (src_before, file_b, 'B'),
        (src_after,  file_a, 'A'),
    ]:
        if not os.path.exists(src_path):
            with _print_lock:
                print(f'  [{ctr}/{total}] MISSING tiff: {src_path}')
            return results_dir_name, False
        try:
            with rasterio.open(src_path) as src:
                # Reproject overlap polygon to match the tiff's CRS if needed
                tiff_crs = src.crs.to_wkt()
                geom = _reproject_geom(overlap_geom, tiff_crs)
                out_image, out_transform = rio_mask(src, [geom], crop=True)
                out_meta = src.meta.copy()
                out_meta.update({
                    'driver':    'GTiff',
                    'height':    out_image.shape[1],
                    'width':     out_image.shape[2],
                    'transform': out_transform,
                })
                with rasterio.open(dest_path, 'w', **out_meta) as dst:
                    dst.write(out_image)
        except Exception as e:
            with _print_lock:
                print(f'  [{ctr}/{total}] Clip {label} failed for {results_dir_name}: {e}')
            return results_dir_name, False

    with _print_lock:
        print(f'  [{ctr}/{total}] OK: {results_dir_name}')
    return results_dir_name, True

# ---------------------------------------------------------------------------
# Build work list, assigning before/after by UTCstart date
# ---------------------------------------------------------------------------
work_items = []  # (fid_before, fid_after, geom)

for _, row in clipped.iterrows():
    p1, p2, geom = row['Polygon1'], row['Polygon2'], row.geometry
    utc1 = fid_to_utc.get(p1)
    utc2 = fid_to_utc.get(p2)
    # Assign earlier image as "before" (clippedB), later as "after" (clippedA)
    if utc1 is not None and utc2 is not None and utc2 < utc1:
        fid_before, fid_after = p2, p1
    else:
        fid_before, fid_after = p1, p2  # default to shapefile order if dates missing
    work_items.append((fid_before, fid_after, geom))

total = len(work_items)
print(f'\nClipping {total:,} pairs ({workers} workers)...')

# ---------------------------------------------------------------------------
# Parallel clip
# ---------------------------------------------------------------------------
completed_dirs = []
failed_dirs    = []
# Track which FIDs had all their pairs clipped successfully
fid_success_counts = {fid: 0 for fid in unique_fids}
fid_pair_counts    = {fid: 0 for fid in unique_fids}
for fb, fa, _ in work_items:
    fid_pair_counts[fb] = fid_pair_counts.get(fb, 0) + 1
    fid_pair_counts[fa] = fid_pair_counts.get(fa, 0) + 1

with ThreadPoolExecutor(max_workers=workers) as executor:
    futures = {
        executor.submit(clip_pair, fb, fa, geom, i + 1, total): (fb, fa)
        for i, (fb, fa, geom) in enumerate(work_items)
    }
    for future in as_completed(futures):
        fb, fa = futures[future]
        dir_name, ok = future.result()
        if ok:
            completed_dirs.append(dir_name)
            fid_success_counts[fb] = fid_success_counts.get(fb, 0) + 1
            fid_success_counts[fa] = fid_success_counts.get(fa, 0) + 1
        else:
            failed_dirs.append(dir_name)

print(f'\nClip complete.')
print(f'  Succeeded: {len(completed_dirs):,}')
print(f'  Failed:    {len(failed_dirs):,}')

# ---------------------------------------------------------------------------
# Write clip_pairs.csv (one pair dir name per row, compatible with MATLAB)
# ---------------------------------------------------------------------------
clip_csv = os.path.join(path, 'clip_pairs.csv')
with open(clip_csv, 'w', newline='') as f:
    wr = csv.writer(f)
    for d in completed_dirs:
        wr.writerow([d])
print(f'Pair directories written to {clip_csv}')

if failed_dirs:
    fail_log = os.path.join(path, 'clip_failures.txt')
    with open(fail_log, 'w') as f:
        for d in failed_dirs:
            f.write(d + '\n')
    print(f'Failed pairs written to {fail_log}')

# ---------------------------------------------------------------------------
# Delete raw tiffs — only for images where every pair clipped successfully
# ---------------------------------------------------------------------------
if args.keep_tiffs:
    print('--keep-tiffs set: raw tiff files not deleted.')
else:
    deleted = 0
    skipped = 0
    for fid in unique_fids:
        ctx_id   = fid_to_ctxid.get(fid)
        if not ctx_id:
            continue
        tiff_path = os.path.join(deep_path, ctx_id + '.tiff')
        if not os.path.exists(tiff_path):
            continue
        # Only delete if all pairs for this image succeeded
        if fid_success_counts.get(fid, 0) >= fid_pair_counts.get(fid, 0):
            os.remove(tiff_path)
            deleted += 1
        else:
            skipped += 1
    print(f'Raw tiff cleanup: deleted {deleted:,}, kept {skipped:,} '
          f'(had failed pairs — re-run to retry).')

print('Run complete.')
