#!/usr/bin/env python3
"""
make_keyword_gifs.py

Reads confirmed_hits.csv, potential_hits.csv, and interesting.csv.
For each flagged hit whose 'comments' field contains one or more keywords,
creates an animated GIF (before ↔ after, 200px crops) and writes a
metadata text file, organised by keyword folder.

Output layout:
  gif_output/
    HIGH/
      hit_1234_100_200__B1234_A5678.gif
      ...
      metadata.txt
    DUNE/
      ...

Usage:
  python make_keyword_gifs.py

Edit KEYWORDS, GIF_OUTPUT_DIR, or frame timing below as needed.
"""

import os
import csv
import re
from PIL import Image

# ── Config ────────────────────────────────────────────────────────────────────

KEYWORDS = [
    "HIGH", "MEDIUM", "LOW",
    "DUNE", "ICE", "VORTEX", "CLOUD",
    "TRACK", "RSL", "IDEA",
]

ROOT       = r"G:\crater_flux_output_folders"
PROJ       = os.path.join(ROOT, "Impact_flux_project")
REVIEWED_CSV = os.path.join(PROJ, "pairsinfo_reviewed_2006-2026.csv")

INPUT_CSVS = [
    os.path.join(ROOT, "confirmed_hits.csv"),
    os.path.join(ROOT, "potential_hits.csv"),
    os.path.join(ROOT, "interesting.csv"),
]

GIF_OUTPUT_DIR = os.path.join(ROOT, "gif_output")

# GIF timing: milliseconds per frame
FRAME_MS_BEFORE = 600   # how long the "before" frame is shown
FRAME_MS_AFTER  = 600   # how long the "after" frame is shown

# ── Load pairsinfo for metadata lookup ───────────────────────────────────────

print("Loading reviewed pairsinfo for metadata...")
meta_by_path = {}   # wholepath (normalised) -> dict of metadata
if os.path.exists(REVIEWED_CSV):
    with open(REVIEWED_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = os.path.normpath(row["wholepath"])
            meta_by_path[key] = row
print(f"  {len(meta_by_path):,} entries loaded.")

# ── Load all flagged hits ─────────────────────────────────────────────────────

all_hits = []
for path in INPUT_CSVS:
    if not os.path.exists(path):
        print(f"  Not found, skipping: {path}")
        continue
    label_name = os.path.splitext(os.path.basename(path))[0]  # e.g. "confirmed_hits"
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["_source_label"] = label_name
            all_hits.append(row)

print(f"Total flagged hits loaded: {len(all_hits):,}")

# ── Match hits to keywords ────────────────────────────────────────────────────

# keyword -> list of hit dicts
keyword_hits = {kw: [] for kw in KEYWORDS}

for hit in all_hits:
    comments = hit.get("comments", "") or ""
    # Case-insensitive whole-word search
    for kw in KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', comments, re.IGNORECASE):
            keyword_hits[kw].append(hit)

for kw, hits in keyword_hits.items():
    print(f"  {kw:10s}: {len(hits):4d} hits")

# ── GIF generation ───────────────────────────────────────────────────────────

os.makedirs(GIF_OUTPUT_DIR, exist_ok=True)

def find_200px_crops(pair_path, prefix):
    """Return (before_path, after_path) for 200px crops, or (None, None)."""
    before = os.path.join(pair_path, f"{prefix}_before_200.jpg")
    after  = os.path.join(pair_path, f"{prefix}_after_200.jpg")
    if os.path.exists(before) and os.path.exists(after):
        return before, after
    # Fall back to 100px crops if 200px not yet generated
    before100 = os.path.join(pair_path, f"{prefix}_before.jpg")
    after100  = os.path.join(pair_path, f"{prefix}_after.jpg")
    if os.path.exists(before100) and os.path.exists(after100):
        return before100, after100
    return None, None


def make_gif(before_path, after_path, out_path):
    """Create a two-frame animated GIF from before/after JPEGs."""
    img_b = Image.open(before_path).convert("RGB")
    img_a = Image.open(after_path).convert("RGB")
    # Convert to palette mode for compact GIF
    img_b_p = img_b.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    img_a_p = img_a.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    img_b_p.save(
        out_path,
        format="GIF",
        save_all=True,
        append_images=[img_a_p],
        loop=0,
        duration=[FRAME_MS_BEFORE, FRAME_MS_AFTER],
    )


METADATA_FIELDS = [
    "id", "hit_prefix", "pair_name", "label", "comments",
    "lat", "lon", "ctx_id1", "ctx_id2", "date1", "date2",
    "days_between", "reg_score", "area_km2", "n_hits",
    "pair_path", "gif_file", "crops_found",
]


def build_metadata_row(gif_id, hit, meta, gif_name, crops_found):
    """Build a dict for one row of metadata.csv."""
    pair_path = hit.get("wholepath", "")
    pair_name = os.path.basename(os.path.normpath(pair_path)) if pair_path else ""

    if meta:
        ctxID = meta.get("ctxID", "")
        parts = ctxID.split("_")
        if len(parts) >= 6:
            pid1 = "_".join(parts[:3])
            pid2 = "_".join(parts[3:])
        else:
            pid1, pid2 = ctxID, ""
        dt1   = meta.get("datetime1", "")
        dt2   = meta.get("datetime2", "")
        days  = meta.get("days_between", "")
        score = meta.get("RegistrationScore", "")
        area  = meta.get("areakm2", "")
        hits_n = meta.get("hits", "")
    else:
        pid1 = pid2 = dt1 = dt2 = days = score = area = hits_n = ""

    return {
        "id":           gif_id,
        "hit_prefix":   hit.get("hit_prefix", ""),
        "pair_name":    pair_name,
        "label":        hit.get("_source_label", ""),
        "comments":     hit.get("comments", ""),
        "lat":          hit.get("lat", ""),
        "lon":          hit.get("lon", ""),
        "ctx_id1":      pid1,
        "ctx_id2":      pid2,
        "date1":        dt1,
        "date2":        dt2,
        "days_between": days,
        "reg_score":    score,
        "area_km2":     area,
        "n_hits":       hits_n,
        "pair_path":    pair_path,
        "gif_file":     gif_name,
        "crops_found":  "yes" if crops_found else "no",
    }


total_gifs = 0
total_missing = 0

for kw in KEYWORDS:
    hits = keyword_hits[kw]
    if not hits:
        continue

    kw_dir = os.path.join(GIF_OUTPUT_DIR, kw)
    os.makedirs(kw_dir, exist_ok=True)

    print(f"\n── {kw} ({len(hits)} hits) ──")

    meta_rows = []
    seq = 0  # counts ALL hits in order (including missing crops), for stable IDs

    for hit in hits:
        pair_path = hit.get("wholepath", "")
        prefix    = hit.get("hit_prefix", "")
        if not pair_path or not prefix:
            continue

        seq += 1
        gif_id   = f"{kw}_{seq:04d}"
        gif_name = f"{gif_id}.gif"
        gif_path = os.path.join(kw_dir, gif_name)

        meta = meta_by_path.get(os.path.normpath(pair_path))
        before_path, after_path = find_200px_crops(pair_path, prefix)

        crops_ok = before_path is not None

        if not crops_ok:
            print(f"  WARNING: crops not found for {prefix} ({gif_id})")
            total_missing += 1
        else:
            try:
                make_gif(before_path, after_path, gif_path)
                print(f"  {gif_name}")
                total_gifs += 1
            except Exception as e:
                print(f"  ERROR making GIF for {prefix} ({gif_id}): {e}")
                crops_ok = False

        meta_rows.append(build_metadata_row(gif_id, hit, meta, gif_name, crops_ok))

    # Write metadata.csv for this keyword
    meta_path = os.path.join(kw_dir, "metadata.csv")
    with open(meta_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=METADATA_FIELDS)
        writer.writeheader()
        writer.writerows(meta_rows)
    print(f"  → metadata.csv written ({len(meta_rows)} rows)")

print(f"\nDone. {total_gifs} GIFs created, {total_missing} missing crops.")
print(f"Output: {GIF_OUTPUT_DIR}")
