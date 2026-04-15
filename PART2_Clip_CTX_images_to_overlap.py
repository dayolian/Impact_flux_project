# UPDATED APRIL 2026 — Performance-improved version
# This script processes Mars CTX (Context Camera) image pairs.
# It reads overlap data from shapefiles, figures out which image pairs
# overlap, then clips both images in each pair down to their shared polygon.

import arcpy
import os
import sys
import csv
import time
from multiprocessing import Pool
from ctx_downloader_rqc import ctx_downloader_rqc
import pandas as pd


# =============================================================================
# CONFIGURATION
# =============================================================================
# These define the geographic bounding box we're working in (lat/lon style).
# Only image pairs inside this box will be processed.
x1 = 80
y1 = 0
x2 = 90
y2 = 75
tag = 'Area80N'

# How many clip operations to run in parallel.
# Increase if you have fast disks and many CPU cores; decrease if you hit
# memory limits or arcpy licensing errors.
PARALLEL_WORKERS = 4

# Known-broken CTX product IDs that cause arcpy to hang or crash.
# We skip any pair that includes one of these.
BROKEN_IDS = {
    'P09_004675_2306_XN_50N111W',
    'P09_004675_2233_XN_43N110W',
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def clip_ctx_images(ctx_id1, ctx_id2, polygon, deep_path):
    """
    Clips two CTX geotiff images to the area where they overlap (the polygon).

    Args:
        ctx_id1:   Product ID of the "before" image
        ctx_id2:   Product ID of the "after" image
        polygon:   An arcpy Polygon object defining the overlap area
        deep_path: Directory path where output folders/files are written

    Returns:
        True on success, False on failure.
    """
    delin = "_"
    try:
        # Create a subdirectory named like "ID1_ID2" to hold the clipped pair
        results_dir = str(ctx_id1) + delin + str(ctx_id2)
        full_results_dir = os.path.join(deep_path, results_dir)
        try:
            os.mkdir(full_results_dir)
        except OSError as e:
            # Folder might already exist — that's okay
            print(e)

        # Build output file paths for the clipped "before" and "after" images
        fileb = os.path.join(full_results_dir,
                             f"{ctx_id1}{delin}{ctx_id2}{delin}clippedB.tif")
        filea = os.path.join(full_results_dir,
                             f"{ctx_id1}{delin}{ctx_id2}{delin}clippedA.tif")

        # arcpy.Clip_management cuts a raster down to a shape boundary.
        # '0' is the nodata value for pixels outside the polygon.
        # 'ClippingGeometry' tells it to use the polygon, not a rectangle.
        arcpy.Clip_management(
            ctx_id1 + '.tiff', '#', fileb, polygon,
            '0', 'ClippingGeometry', 'NO_MAINTAIN_EXTENT'
        )
        arcpy.Clip_management(
            ctx_id2 + '.tiff', '#', filea, polygon,
            '0', 'ClippingGeometry', 'NO_MAINTAIN_EXTENT'
        )

    except Exception as e:
        print(e)
        print(f'WARNING: Download/Clip accidental termination for {ctx_id1}, {ctx_id2}')
        return False
    else:
        print(f'Success: Clip finished for {ctx_id1} & {ctx_id2}')
        return True


def clip_worker(args):
    """
    Wrapper for clip_ctx_images that unpacks a single tuple of arguments.
    multiprocessing.Pool.map only passes one argument per call, so we
    pack everything into a tuple and unpack here.

    NOTE: arcpy is imported at module level. If you get licensing errors
    in parallel, try moving `import arcpy` inside this function so each
    worker process gets its own arcpy session.
    """
    ctx0, ctx1, polygon, deep_path = args
    return clip_ctx_images(ctx0, ctx1, polygon, deep_path)


# =============================================================================
# PATH SETUP
# =============================================================================

# 'direct' = the folder this script lives in (or is executed from)
direct = os.path.dirname(os.path.realpath(__file__))

# Build a subfolder name from the bounding box, e.g. "output_80_90_0_75"
delin = "_"
bounds = delin.join([str(x1), str(x2), str(y1), str(y2)])
path = "output_" + bounds

# The clipped footprint shapefile that lists all overlapping image pairs
# within our bounding box.  Each row has Polygon1 (FID), Polygon2 (FID),
# and a SHAPE@ geometry column.
fc = os.path.join(path, f'footprint_clipped_{tag}.shp')

# The master shapefile covering the entire planet — maps every FID to its
# CTX ProductID string (the actual image filename on disk).
mainRef = os.path.join(direct, 'mars_mro_ctx_edr_c0a.shp')

# Make sure the output folder exists before we try to read from it
if os.path.isdir(path):
    print('Folder exists, good to check')
else:
    print('Cannot find the folder', path, 'and thus unable to check')
    sys.exit()


# =============================================================================
# STEP 1: READ THE CLIPPED OVERLAP SHAPEFILE
# =============================================================================
# We need five data structures from this file:
#
#   pair_to_polygon  (E) — maps (FID1, FID2) tuples to their overlap polygon
#   poly1 / poly2        — lists of FID1s and FID2s for building a DataFrame
#   unique_fids          — the set of all FIDs we'll need to look up later

pair_to_polygon = {}   # (FID1, FID2) -> arcpy Polygon
unique_fids = set()    # every FID that appears in any pair
poly1 = []             # parallel list of "left" FIDs
poly2 = []             # parallel list of "right" FIDs

try:
    # 'with' ensures the cursor is closed when done, releasing file locks
    with arcpy.da.SearchCursor(fc, ['Polygon1', 'Polygon2', 'SHAPE@']) as cur:
        for row in cur:
            fid1, fid2, shape = row[0], row[1], row[2]
            pair_to_polygon[(fid1, fid2)] = shape
            poly1.append(fid1)
            poly2.append(fid2)
            unique_fids.add(fid1)
            unique_fids.add(fid2)
except Exception as e:
    print(e)
    print('WARNING: CTX library terminated without completion.')
    sys.exit()

# Build a DataFrame from the two parallel lists so we can use groupby later
df = pd.DataFrame({'Polygon1': poly1, 'Polygon2': poly2})

print('CTX Library phase finished')


# =============================================================================
# STEP 2: BUILD THE FID -> PRODUCT ID LOOKUP (only for FIDs we need)
# =============================================================================
# The master shapefile covers the whole planet, but we only need the rows
# for FIDs that appear in our clipped subset.  We push a SQL WHERE clause
# into arcpy so it skips irrelevant rows at the database level — much faster
# than reading everything and filtering in Python.

fid_to_ctxid = {}  # FID number -> CTX product ID string

try:
    # Build a SQL filter like "FID IN (12, 45, 78, ...)"
    fid_str = ",".join(str(f) for f in unique_fids)
    where_clause = f"FID IN ({fid_str})"

    with arcpy.da.SearchCursor(mainRef, ['FID', 'ProductID'], where_clause) as cur:
        for row in cur:
            fid_to_ctxid[row[0]] = row[1]
except Exception as e:
    print(e)
    print('Main ref pairs failed to work')
    sys.exit()

print('FID-to-CTX ID lookup built')


# =============================================================================
# STEP 3: BUILD PAIR PARTICIPATION & CONNECTION MAPS (using groupby)
# =============================================================================
# pair_participation_dict (B) — how many pairs each FID appears in
# pair_connection_map     (C) — list of partner FIDs for each FID
# counter_dict            (A) — groups FIDs by their participation count
#
# Instead of looping over every unique FID and filtering the DataFrame each
# time (slow: O(unique * rows)), we use groupby which does it in one pass
# over the data (fast: O(rows)).

pair_participation_dict = {}
pair_connection_map = {}
counter_dict = {}

# Group by the "left" column: for each FID in Polygon1, collect its Polygon2 partners
g1 = df.groupby('Polygon1')['Polygon2'].agg(list)
for fid, partners in g1.items():
    pair_participation_dict[fid] = len(partners)
    pair_connection_map[fid] = partners

# Group by the "right" column: for each FID in Polygon2, collect its Polygon1 partners
# Some FIDs appear in both columns, so we add to existing counts/lists.
g2 = df.groupby('Polygon2')['Polygon1'].agg(list)
for fid, partners in g2.items():
    pair_participation_dict[fid] = pair_participation_dict.get(fid, 0) + len(partners)
    if fid in pair_connection_map:
        pair_connection_map[fid].extend(partners)
    else:
        pair_connection_map[fid] = partners

# Build counter_dict: invert pair_participation_dict so we can look up
# "which FIDs have exactly N partners?"
for fid, count in pair_participation_dict.items():
    if count in counter_dict:
        counter_dict[count].append(fid)
    else:
        counter_dict[count] = [fid]

print('Pair relationship maps built')


# =============================================================================
# STEP 4: CLIP ALL IMAGE PAIRS (parallelized)
# =============================================================================
# For each overlapping pair, we clip both CTX images to the overlap polygon.
# This is I/O-heavy (reading/writing large TIFFs), so we run multiple clips
# at once using a process pool.

deep_path = os.path.join(direct, path)
os.chdir(deep_path)

new_dir_list = []  # collects CTX IDs of successfully clipped pairs (written to CSV later)

# Build the list of work items, skipping broken IDs
work_items = []
skipped = 0

for pair, polygon in pair_to_polygon.items():
    ctx0 = fid_to_ctxid[pair[0]]
    ctx1 = fid_to_ctxid[pair[1]]

    # Skip pairs that include known-broken products.
    # Note: the original code had a bug here — `if ctx0 or ctx1 in broken`
    # always evaluates True because `bool(ctx0)` is True for any non-empty
    # string.  The correct check is `ctx0 in ... or ctx1 in ...`.
    if ctx0 in BROKEN_IDS or ctx1 in BROKEN_IDS:
        skipped += 1
        continue

    work_items.append((ctx0, ctx1, polygon, deep_path))

print(f'Queued {len(work_items)} pairs for clipping ({skipped} skipped as broken)')

# Run the clips in parallel.  Each worker calls clip_ctx_images independently.
# If arcpy throws licensing errors under multiprocessing, reduce PARALLEL_WORKERS
# to 1 (which makes it sequential) or try ThreadPoolExecutor instead.
with Pool(processes=PARALLEL_WORKERS) as pool:
    results = pool.map(clip_worker, work_items)

# Collect the CTX IDs from successful clips
for (ctx0, ctx1, _, _), success in zip(work_items, results):
    if success:
        new_dir_list.append(str(ctx0))
        new_dir_list.append(str(ctx1))
    else:
        print(f'Error processing {ctx0} and {ctx1}')

print(f'Clipping complete: {sum(results)} succeeded, {len(results) - sum(results)} failed')


# =============================================================================
# STEP 5: CLEAN UP SOURCE TIFF FILES
# =============================================================================
# After clipping, the full-size .tiff files are no longer needed.
# We delete them one by one, catching errors so one missing file doesn't
# halt the entire cleanup.

cleanup_errors = 0
for fid in unique_fids:
    tiff_path = os.path.join(deep_path, fid_to_ctxid[fid] + '.tiff')
    try:
        os.remove(tiff_path)
    except OSError as e:
        # File might already be gone or locked — log it and keep going
        print(f'Could not remove {tiff_path}: {e}')
        cleanup_errors += 1

if cleanup_errors:
    print(f'Cleanup finished with {cleanup_errors} errors (see above)')
else:
    print('Cleanup finished — all source TIFFs removed')


# =============================================================================
# STEP 6: WRITE RESULTS CSV
# =============================================================================
# Save the list of clipped CTX product IDs so the next step in the pipeline
# knows which pairs were successfully processed.

os.chdir(os.path.join(direct, path))

clip_file_name = 'clip_pairs.csv'
# 'w' with newline='' is the correct Python 3 way to write CSV files.
# (The original 'wb' mode was Python 2 syntax and would crash on Python 3.)
with open(clip_file_name, 'w', newline='') as pair_file:
    wr = csv.writer(pair_file)
    wr.writerow(new_dir_list)

print(f'New Pair IDs stored as {clip_file_name}')
print('Pipeline complete.')
