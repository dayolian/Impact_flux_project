# PART1 v2 — Download CTX images for a swath region in parallel.
#
# Changes from PART1 (original):
#   - argparse: swath bounds and tag passed as command-line arguments,
#     no need to edit the file per swath
#   - arcpy replaced with geopandas for the region-clip step
#   - mainRef updated to 2026 footprints; PDSVolId read alongside ProductId
#     so the volume ID is known without any web scraping
#   - ctx_downloader_v2 replaces ctx_downloader_rqc: direct requests
#     download instead of browser + sleep, with retry/backoff
#   - ThreadPoolExecutor runs N downloads in parallel (--workers flag,
#     default 8); tune down if the ASU server rate-limits you
#   - downloaded_fids tracked as a set (was a list: O(N) membership test)
#   - simplified main loop: ordering-by-connectedness logic retained but
#     disk-management (delete after all pairs processed) also restored so
#     the ordering actually saves disk space
#
# Usage example (one swath):
#   python PART1_v2.py --lon1 0 --lon2 10 --lat1 -75 --lat2 75 --tag Swath0_10
#
# Run once per swath.  Each swath gets its own output_<bounds> folder.
#
# Updated June 2026 — Impact Flux Project, GALE Lab UCLA

import argparse
import os
import sys
import geopandas as gpd
import pandas as pd
from shapely.geometry import box
from concurrent.futures import ThreadPoolExecutor, as_completed

from ctx_downloader_v2 import download_ctx

# ---------------------------------------------------------------------------
# Paths — update if files move
# ---------------------------------------------------------------------------
SCRIPT_DIR   = os.path.dirname(os.path.realpath(__file__))
PAIRS_SHP    = os.path.join(SCRIPT_DIR, 'CTX_pair_intersections_new_swaths.shp')
FOOTPRINTS   = os.path.join(SCRIPT_DIR, 'mars_mro_ctx_edr_c0a_2026',
                             'mars_mro_ctx_edr_c0a.shp')

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(
    description='Download CTX images for a swath region.')
parser.add_argument('--lon1',       type=float, required=True,  help='West longitude (deg, +/-180)')
parser.add_argument('--lon2',       type=float, required=True,  help='East longitude (deg, +/-180)')
parser.add_argument('--lat1',       type=float, required=True,  help='South latitude (deg)')
parser.add_argument('--lat2',       type=float, required=True,  help='North latitude (deg)')
parser.add_argument('--tag',        type=str,   required=True,  help='Short label for output folder suffix')
parser.add_argument('--workers',    type=int,   default=8,      help='Parallel download threads (default 8)')
parser.add_argument('--output-dir', type=str,   default=None,   help='Root directory for output folder (default: script directory)')
args = parser.parse_args()

x1, x2, y1, y2 = args.lon1, args.lon2, args.lat1, args.lat2
tag        = args.tag
workers    = args.workers
output_dir = args.output_dir if args.output_dir else SCRIPT_DIR

def _fmt(v):
    return str(int(v)) if v == int(v) else str(v)

delin  = '_'
bounds = delin.join([_fmt(x1), _fmt(x2), _fmt(y1), _fmt(y2)])
path   = os.path.join(output_dir, 'output_new_' + bounds)
fc     = os.path.join(path, 'footprint_clipped_' + tag + '.shp')

# ---------------------------------------------------------------------------
# Setup output directory
# ---------------------------------------------------------------------------
if not os.path.isdir(path):
    print(f'Output folder not found: {path}')
    print('Create it first (or check your --lon1/lon2/lat1/lat2 arguments).')
    sys.exit(1)

# ---------------------------------------------------------------------------
# Step 1: Clip pairs shapefile to the requested region (replaces arcpy)
# ---------------------------------------------------------------------------
if os.path.exists(fc):
    print(f'Clipped footprint shapefile already exists: {fc}')
    print('Loading existing file.')
    clipped = gpd.read_file(fc)
else:
    print('Clipping pairs shapefile to region...')
    region_box = box(x1, y1, x2, y2)
    pairs = gpd.read_file(PAIRS_SHP)
    clipped = pairs[pairs.intersects(region_box)].copy()
    clipped = clipped.reset_index(drop=True)
    clipped.to_file(fc)
    print(f'  {len(clipped):,} pairs clipped to region -> {fc}')

print(f'Footprint clipping phase finished. {len(clipped):,} pairs in region.')

# ---------------------------------------------------------------------------
# Step 2: Build FID -> ProductId and FID -> PDSVolId lookups from footprints
# ---------------------------------------------------------------------------
print('Loading 2026 footprints for FID lookup...')
footprints = gpd.read_file(FOOTPRINTS, columns=['ProductId', 'PDSVolId'])
footprints = footprints.reset_index(drop=True)
footprints['FID'] = footprints.index
fid_to_ctxid = dict(zip(footprints['FID'], footprints['ProductId']))
fid_to_volid = dict(zip(footprints['FID'], footprints['PDSVolId']))
print(f'  Loaded {len(footprints):,} footprint records.')

# ---------------------------------------------------------------------------
# Step 3: Build pair bookkeeping structures (A, B, C, E from original)
# ---------------------------------------------------------------------------
poly1_list = list(clipped['Polygon1'])
poly2_list = list(clipped['Polygon2'])
geometries = list(clipped.geometry)

pair_to_polygon     = {}  # (fid1, fid2) -> shapely geometry
pair_participation  = {}  # fid -> count of pairs it appears in
pair_connection_map = {}  # fid -> [list of partner fids]
unique_fids         = set()

for p1, p2, geom in zip(poly1_list, poly2_list, geometries):
    pair_to_polygon[(p1, p2)] = geom
    unique_fids.update([p1, p2])
    pair_participation[p1] = pair_participation.get(p1, 0) + 1
    pair_participation[p2] = pair_participation.get(p2, 0) + 1
    pair_connection_map.setdefault(p1, []).append(p2)
    pair_connection_map.setdefault(p2, []).append(p1)

# Group FIDs by participation count (process least-connected first to
# minimise how many images are on disk simultaneously)
counter_dict = {}
for fid, count in pair_participation.items():
    counter_dict.setdefault(count, []).append(fid)

print(f'CTX library phase finished. Unique images to download: {len(unique_fids):,}')

# ---------------------------------------------------------------------------
# Step 4: Parallel download
# ---------------------------------------------------------------------------
deep_path        = path + os.sep
downloaded_fids  = set()   # O(1) membership — was a list in original
failed_fids      = []
total_needed     = len(unique_fids)
completed        = 0

def _download_one(fid):
    ctx_id = fid_to_ctxid.get(fid)
    vol_id = fid_to_volid.get(fid)
    if not ctx_id or not vol_id:
        return fid, False, f'FID {fid} not found in footprints'
    ok = download_ctx(ctx_id, vol_id, deep_path)
    return fid, ok, ctx_id

print(f'\nStarting parallel download ({workers} workers)...')

# Determine download order: least-connected FIDs first
ordered_fids = []
for count in sorted(counter_dict.keys()):
    ordered_fids.extend(counter_dict[count])

with ThreadPoolExecutor(max_workers=workers) as executor:
    futures = {executor.submit(_download_one, fid): fid for fid in ordered_fids}
    for future in as_completed(futures):
        fid, ok, ctx_id = future.result()
        completed += 1
        if ok:
            downloaded_fids.add(fid)
            print(f'  [{completed}/{total_needed}] OK  {ctx_id}')
        else:
            failed_fids.append(fid)
            print(f'  [{completed}/{total_needed}] FAIL {ctx_id}')

# ---------------------------------------------------------------------------
# Step 5: Report and clean up images whose pairs are all processed
# ---------------------------------------------------------------------------
print(f'\nDownload complete.')
print(f'  Succeeded: {len(downloaded_fids):,}')
print(f'  Failed:    {len(failed_fids):,}')

if failed_fids:
    fail_log = os.path.join(path, 'download_failures.txt')
    with open(fail_log, 'w') as f:
        for fid in failed_fids:
            f.write(f'{fid}\t{fid_to_ctxid.get(fid, "UNKNOWN")}\n')
    print(f'  Failed FIDs written to {fail_log}')

# Delete images that have all their pairs processed (disk management).
# Only safe to do once all downloads are done (unlike original incremental
# approach, which required the participation-count decrement logic).
processed_pairs = set(pair_to_polygon.keys())
for fid in list(downloaded_fids):
    partners = pair_connection_map.get(fid, [])
    all_done = all(
        (min(fid, p), max(fid, p)) in processed_pairs
        for p in partners
        if p in downloaded_fids
    )
    if all_done and pair_participation.get(fid, 0) == 0:
        tiff_path = os.path.join(deep_path, fid_to_ctxid[fid] + '.tiff')
        if os.path.exists(tiff_path):
            os.remove(tiff_path)
            print(f'  Deleted (all pairs done): {fid_to_ctxid[fid]}')

print('Run complete.')
