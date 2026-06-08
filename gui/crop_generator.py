#!/usr/bin/env python3
"""
Generate 200x200 px crops for all flagged hits and compute lat/lon.
Run this ONCE before starting the review GUI (review_server.py).

Output per hit:
  hit_{ARE}_{x}_{y}_before_200.jpg
  hit_{ARE}_{x}_{y}_after_200.jpg
  (saved alongside existing 100px crops in each pair subfolder)

Also adds lat, lon, comments columns to confirmed_hits.csv,
potential_hits.csv, and interesting.csv if not already present.
"""

import os
import csv
import math
import glob
import numpy as np
from PIL import Image

# CTX GeoTIFFs can exceed Pillow's default decompression-bomb limit (~179 MP).
# These are known trusted scientific files, so we disable the check.
Image.MAX_IMAGE_PIXELS = None

# ─── Config ──────────────────────────────────────────────────────────────────

R_MARS    = 3_396_190.0  # Mars sphere radius, IAU 2000 (metres)
CROP_SIZE = 200

OUTPUT_DIR = r"G:\crater_flux_output_folders"

INPUT_FILES = {
    "confirmed_hit": os.path.join(OUTPUT_DIR, "confirmed_hits.csv"),
    "potential_hit":  os.path.join(OUTPUT_DIR, "potential_hits.csv"),
    "interesting":    os.path.join(OUTPUT_DIR, "interesting.csv"),
}

# ─── Coordinate helpers ───────────────────────────────────────────────────────

def read_tfw(tfw_path):
    """
    Read a world file (.tfw).
    Returns [A, D, B, E, C, F] where the affine transform is:
      easting  = A*col + B*row + C
      northing = D*col + E*row + F
    """
    with open(tfw_path) as f:
        return [float(line.strip()) for line in f if line.strip()]


def pixel_to_lonlat(col, row, tfw):
    """
    Convert pixel (col, row) to geographic (lon, lat) in decimal degrees.
    Assumes Mars Simple Cylindrical projection with central meridian at 180°E.
    """
    A, D, B, E, C, F = tfw
    easting  = A * col + B * row + C
    northing = D * col + E * row + F

    # Inverse Mars Simple Cylindrical (central meridian = 180°E):
    #   lon_deg = 180 + degrees(easting / R_MARS)
    #   lat_deg = degrees(northing / R_MARS)
    lon = 180.0 + math.degrees(easting / R_MARS)
    lat = math.degrees(northing / R_MARS)

    # Normalise longitude to -180 … +180
    if lon > 180.0:
        lon -= 360.0
    elif lon < -180.0:
        lon += 360.0

    return round(lon, 5), round(lat, 5)

# ─── Image helpers ────────────────────────────────────────────────────────────

def find_file(pair_path, suffix, ext):
    """Glob for *_{suffix}.{ext} in pair_path, return first match or None."""
    matches = glob.glob(os.path.join(pair_path, f"*_{suffix}.{ext}"))
    matches = [m for m in matches if m.lower().endswith(f".{ext}")]
    return matches[0] if matches else None


def load_and_stretch(tif_path):
    """
    Load a grayscale GeoTIFF and apply 2nd–98th percentile contrast stretch.
    Nodata pixels (0 and 255 in the raw uint8 source) are set to 0 in output.
    Returns a uint8 numpy array.
    """
    img = Image.open(tif_path)
    arr = np.array(img).astype(np.float32)

    nodata = (arr == 0) | (arr == 255)
    valid  = arr[~nodata]

    if len(valid) >= 100:
        p2, p98 = np.percentile(valid, [2, 98])
        if p98 > p2:
            arr = (arr - p2) / (p98 - p2) * 255.0
        else:
            arr = arr - p2
    arr = np.clip(arr, 0, 255)
    arr[nodata] = 0
    return arr.astype(np.uint8)


def make_crop(arr, col, row, size=200):
    """
    Crop a size×size region centred on pixel (col, row).
    Regions outside the image bounds are padded with black (0).
    """
    half = size // 2
    h, w = arr.shape

    # Source region clamped to image bounds
    sx1, sx2 = max(0, col - half), min(w, col + half)
    sy1, sy2 = max(0, row - half), min(h, row + half)

    # Destination offsets within the output array
    dx1 = sx1 - (col - half)
    dy1 = sy1 - (row - half)
    dx2 = dx1 + (sx2 - sx1)
    dy2 = dy1 + (sy2 - sy1)

    out = np.zeros((size, size), dtype=np.uint8)
    out[dy1:dy2, dx1:dx2] = arr[sy1:sy2, sx1:sx2]
    return out

# ─── Per-CSV processing ───────────────────────────────────────────────────────

def process_csv(csv_path, label):
    if not os.path.exists(csv_path):
        print(f"  Not found, skipping: {csv_path}")
        return

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print(f"  Empty, skipping: {csv_path}")
        return

    # Add new columns with defaults if absent
    for row in rows:
        row.setdefault("lat",      "")
        row.setdefault("lon",      "")
        row.setdefault("comments", "")

    total = len(rows)
    skipped = 0

    for i, row in enumerate(rows, 1):
        pair_path = row["wholepath"]
        prefix    = row["hit_prefix"]
        parts     = prefix.split("_")  # ["hit", ARE, x, y]
        col       = int(parts[2])
        row_px    = int(parts[3])      # "row" in pixel coords

        print(f"  [{i:>4}/{total}] {prefix}", end="", flush=True)

        # ── 200px crops ──────────────────────────────────────────────────────
        for tif_suffix, img_label in [("clippedB", "before"), ("clippedA", "after")]:
            out_jpg = os.path.join(pair_path, f"{prefix}_{img_label}_200.jpg")
            if os.path.exists(out_jpg):
                continue  # already generated

            tif = find_file(pair_path, tif_suffix, "tif")
            if not tif:
                print(f"\n    WARNING: {tif_suffix}.tif not found in {pair_path}")
                skipped += 1
                continue

            try:
                stretched = load_and_stretch(tif)
                crop      = make_crop(stretched, col, row_px, CROP_SIZE)
                Image.fromarray(crop, mode="L").save(out_jpg, "JPEG", quality=92)
            except Exception as e:
                print(f"\n    ERROR generating {out_jpg}: {e}")
                skipped += 1
                continue

        # ── lat / lon ────────────────────────────────────────────────────────
        if not row["lat"]:
            tif_b = find_file(pair_path, "clippedB", "tif")
            tfw   = find_file(pair_path, "clippedB", "tfw") if tif_b else None
            if tfw:
                try:
                    transform    = read_tfw(tfw)
                    lon, lat     = pixel_to_lonlat(col, row_px, transform)
                    row["lat"]   = f"{lat:.5f}"
                    row["lon"]   = f"{lon:.5f}"
                except Exception as e:
                    print(f"\n    WARNING: lat/lon failed for {prefix}: {e}")
            else:
                print(f"\n    WARNING: no .tfw found in {pair_path}")

        print(" ✓")

    # ── Write updated CSV ────────────────────────────────────────────────────
    fieldnames = list(rows[0].keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  → Saved {csv_path}  ({skipped} skipped)")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Generating 200px crops and computing lat/lon for all flagged hits...\n")
    for label, path in INPUT_FILES.items():
        print(f"\n── {label} ──")
        process_csv(path, label)
    print("\nAll done.")


if __name__ == "__main__":
    main()
