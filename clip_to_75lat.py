#!/usr/bin/env python3
"""
Identify pairs in the four lat-extended output folders that extend beyond
±75° latitude, clip their footprint polygons to the ±75° boundary, and
compute the clipped area in km².

Output: pairs_latclip_adjustments.csv
  ctxID, wholepath, output_folder,
  lat_min, lat_max,
  areakm2_original, areakm2_clipped

No existing files are modified.
"""

import os
import csv

import geopandas as gpd
import pandas as pd
from pyproj import Geod
from shapely.geometry import box

# ── Config ────────────────────────────────────────────────────────────────────

ROOT         = r"G:\crater_flux_output_folders"
PAIRSINFO    = os.path.join(ROOT, "Impact_flux_project",
                             "pairsinfo_alldata_2006-2026.csv")
OLD_FP_SHP   = os.path.join(ROOT, "Impact_flux_project",
                             "mars_mro_ctx_edr_c0a.shp")
OUT_CSV      = os.path.join(ROOT, "Impact_flux_project",
                             "pairs_latclip_adjustments.csv")

LAT_LIMIT    = 75.0
CLIP_BOX     = box(-180, -LAT_LIMIT, 180, LAT_LIMIT)
R_MARS       = 3_396_190.0   # metres, IAU 2000

FOLDERS = {
    "output_-115_-110_-85_-70": "footprint_clipped_Area8570.shp",
    "output_-115_-110_50_85":   "footprint_clipped_Area5085.shp",
    "output_-110_-100_-85_-30": "footprint_clipped_Area110S8530.shp",
    "output_-110_-100_60_85":   "footprint_clipped_Area6085.shp",
}

# ── Spherical area (Mars) ─────────────────────────────────────────────────────

geod = Geod(a=R_MARS, b=R_MARS)

def spherical_area_km2(geom):
    """Signed spherical area in km² for a shapely geometry (Mars sphere)."""
    area_m2, _ = geod.geometry_area_perimeter(geom)
    return abs(area_m2) / 1e6

# ── Load old CTX footprints: index -> ProductId ───────────────────────────────

print("Loading old CTX footprints shapefile (FID -> ProductId)...")
fps = gpd.read_file(OLD_FP_SHP, columns=["ProductId"])
fps = fps.reset_index(drop=True)
fid_to_pid = dict(zip(fps.index, fps["ProductId"]))
print(f"  {len(fid_to_pid):,} footprint records.")

# ── Load pairsinfo: build lookup by pair folder name ─────────────────────────

print("Loading pairsinfo_alldata_2006-2026.csv...")
pairsinfo = pd.read_csv(PAIRSINFO, dtype=str)
pairsinfo["areakm2_f"] = pd.to_numeric(pairsinfo["areakm2"], errors="coerce")
pairsinfo["pair_folder"] = pairsinfo["wholepath"].apply(
    lambda p: os.path.basename(os.path.normpath(p))
)
folder_lookup = {row["pair_folder"]: row
                 for _, row in pairsinfo.iterrows()}
print(f"  {len(pairsinfo):,} rows, {len(folder_lookup):,} unique pair folders.")

# ── Process each folder ───────────────────────────────────────────────────────

results = []

for folder_name, shp_name in FOLDERS.items():
    shp_path = os.path.join(ROOT, folder_name, shp_name)
    print(f"\n── {folder_name}")
    print(f"   Shapefile: {shp_name}")

    if not os.path.isfile(shp_path):
        print("   ERROR: shapefile not found, skipping.")
        continue

    gdf = gpd.read_file(shp_path)
    print(f"   {len(gdf):,} pairs in shapefile")

    n_outside  = 0
    n_matched  = 0
    n_no_match = 0

    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue

        minx, miny, maxx, maxy = geom.bounds

        # Skip pairs fully inside ±75°
        if miny >= -LAT_LIMIT and maxy <= LAT_LIMIT:
            continue

        n_outside += 1

        # Resolve ProductIds from FIDs
        pid1 = fid_to_pid.get(int(row["Polygon1"]), "")
        pid2 = fid_to_pid.get(int(row["Polygon2"]), "")

        if not pid1 or not pid2:
            print(f"   WARNING: FID {int(row['Polygon1'])} or "
                  f"{int(row['Polygon2'])} not in footprints shapefile.")
            n_no_match += 1
            continue

        # Try both orderings to find pairsinfo row
        prow = folder_lookup.get(f"{pid1}_{pid2}")
        if prow is None:
            prow = folder_lookup.get(f"{pid2}_{pid1}")

        if prow is None:
            print(f"   WARNING: no pairsinfo match for {pid1}_{pid2}")
            n_no_match += 1
            continue

        n_matched += 1

        # Clip geometry to ±75° and compute area ratio using spherical formula
        clipped = geom.intersection(CLIP_BOX)

        if clipped.is_empty:
            areakm2_clipped = 0.0
        else:
            orig_sph  = spherical_area_km2(geom)
            clip_sph  = spherical_area_km2(clipped)
            ratio     = clip_sph / orig_sph if orig_sph > 0 else 0.0
            areakm2_clipped = float(prow["areakm2_f"]) * ratio

        results.append({
            "ctxID":            prow["ctxID"],
            "wholepath":        prow["wholepath"],
            "output_folder":    folder_name,
            "lat_min":          round(miny, 4),
            "lat_max":          round(maxy, 4),
            "areakm2_original": round(float(prow["areakm2_f"]), 4),
            "areakm2_clipped":  round(areakm2_clipped, 4),
        })

    print(f"   Pairs extending beyond ±75°: {n_outside}")
    print(f"   Matched to pairsinfo:        {n_matched}")
    print(f"   No match (warning):          {n_no_match}")

# ── Write output ──────────────────────────────────────────────────────────────

print(f"\nTotal pairs needing area adjustment: {len(results)}")

if results:
    fieldnames = ["ctxID", "wholepath", "output_folder",
                  "lat_min", "lat_max",
                  "areakm2_original", "areakm2_clipped"]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"Written: {OUT_CSV}")
else:
    print("No adjustments needed — no output file written.")

print("\nDone.")
