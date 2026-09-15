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
import textwrap
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


def build_metadata_line(hit, meta):
    """Format one hit's metadata as a text block."""
    prefix   = hit.get("hit_prefix", "")
    comments = hit.get("comments", "")
    lat      = hit.get("lat", "")
    lon      = hit.get("lon", "")
    label    = hit.get("_source_label", "")

    if meta:
        ctxID    = meta.get("ctxID", "")
        # ctxID is "pid1_pid2"; split on first underscore-separated pair boundary
        # CTX IDs themselves contain underscores, so split at the midpoint by
        # finding the pattern: two 18-char CTX product IDs joined by underscore
        parts = ctxID.split("_")
        # CTX product IDs have format like B01_010234_1234 (3 parts each)
        # joined pair is 6 underscore-separated tokens total
        if len(parts) >= 6:
            pid1 = "_".join(parts[:3])
            pid2 = "_".join(parts[3:])
        else:
            pid1, pid2 = ctxID, ""
        dt1      = meta.get("datetime1", "")
        dt2      = meta.get("datetime2", "")
        days     = meta.get("days_between", "")
        score    = meta.get("RegistrationScore", "")
        area     = meta.get("areakm2", "")
        hits_n   = meta.get("hits", "")
    else:
        pid1 = pid2 = dt1 = dt2 = days = score = area = hits_n = ""

    lines = [
        f"Hit:              {prefix}",
        f"Flag label:       {label}",
        f"Comments:         {comments}",
        f"Lat/Lon:          {lat}, {lon}",
        f"CTX image 1:      {pid1}",
        f"CTX image 2:      {pid2}",
        f"Date 1:           {dt1}",
        f"Date 2:           {dt2}",
        f"Days between:     {days}",
        f"Reg. score:       {score}",
        f"Pair area (km²):  {area}",
        f"N hits in pair:   {hits_n}",
        f"Pair path:        {hit.get('wholepath', '')}",
        "-" * 60,
    ]
    return "\n".join(lines)


total_gifs = 0
total_missing = 0

for kw in KEYWORDS:
    hits = keyword_hits[kw]
    if not hits:
        continue

    kw_dir = os.path.join(GIF_OUTPUT_DIR, kw)
    os.makedirs(kw_dir, exist_ok=True)

    meta_lines = [
        f"Keyword: {kw}",
        f"Hits: {len(hits)}",
        "=" * 60,
        "",
    ]

    print(f"\n── {kw} ({len(hits)} hits) ──")

    for hit in hits:
        pair_path = hit.get("wholepath", "")
        prefix    = hit.get("hit_prefix", "")
        if not pair_path or not prefix:
            continue

        # Lookup metadata
        meta = meta_by_path.get(os.path.normpath(pair_path))

        # Build GIF filename: prefix + short pair name
        pair_name = os.path.basename(os.path.normpath(pair_path))
        gif_name  = f"{prefix}__{pair_name[:40]}.gif"
        gif_path  = os.path.join(kw_dir, gif_name)

        before_path, after_path = find_200px_crops(pair_path, prefix)

        if before_path is None:
            print(f"  WARNING: crops not found for {prefix} in {pair_path}")
            total_missing += 1
            meta_lines.append(f"[MISSING CROPS] {build_metadata_line(hit, meta)}")
            continue

        try:
            make_gif(before_path, after_path, gif_path)
            print(f"  {gif_name}")
            total_gifs += 1
        except Exception as e:
            print(f"  ERROR making GIF for {prefix}: {e}")
            meta_lines.append(f"[GIF ERROR] {build_metadata_line(hit, meta)}")
            continue

        meta_lines.append(f"GIF: {gif_name}")
        meta_lines.append(build_metadata_line(hit, meta))

    # Write metadata.txt for this keyword
    meta_path = os.path.join(kw_dir, "metadata.txt")
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write("\n".join(meta_lines) + "\n")
    print(f"  → metadata.txt written ({len(hits)} entries)")

print(f"\nDone. {total_gifs} GIFs created, {total_missing} missing crops.")
print(f"Output: {GIF_OUTPUT_DIR}")
