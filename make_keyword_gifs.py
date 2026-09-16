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
from PIL import Image, ImageDraw, ImageFont

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

CTX_M_PER_PX = 6.0      # CTX ground sampling distance (metres/pixel)
SCALEBAR_M   = 100       # length of scale bar in metres

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

def _load_font(size):
    for path in (
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _add_scalebar(img, m_per_px, font, bar_m=SCALEBAR_M):
    """Draw a black scale bar with white-outlined label at bottom-left of img."""
    draw   = ImageDraw.Draw(img)
    w, h   = img.size
    bar_px = max(5, int(round(bar_m / m_per_px)))
    margin = 10
    bar_y  = h - margin
    bar_x0 = margin
    bar_x1 = bar_x0 + bar_px
    label  = f"{bar_m} m"

    try:
        tb = draw.textbbox((0, 0), label, font=font)
        text_w, text_h = tb[2] - tb[0], tb[3] - tb[1]
    except AttributeError:
        text_w, text_h = font.getsize(label)

    text_x = bar_x0 + (bar_px - text_w) // 2
    text_y = bar_y - text_h - 5

    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        draw.text((text_x + dx, text_y + dy), label, fill=(255, 255, 255), font=font)
    draw.text((text_x, text_y), label, fill=(0, 0, 0), font=font)
    draw.line([(bar_x0, bar_y), (bar_x1, bar_y)], fill=(0, 0, 0), width=5)
    for x in (bar_x0, bar_x1):
        draw.line([(x, bar_y - 3), (x, bar_y + 3)], fill=(0, 0, 0), width=2)
    return img


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


def _add_frame_label(img, text, font):
    """Draw BEFORE / AFTER in the top-right corner of img."""
    draw = ImageDraw.Draw(img)
    w, _h = img.size
    margin = 6
    try:
        tb = draw.textbbox((0, 0), text, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
    except AttributeError:
        tw, th = font.getsize(text)
    tx = w - tw - margin
    ty = margin
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        draw.text((tx + dx, ty + dy), text, fill=(255, 255, 255), font=font)
    draw.text((tx, ty), text, fill=(0, 0, 0), font=font)
    return img


def make_gif(before_path, after_path, out_path):
    """Create a two-frame animated GIF from before/after JPEGs with scale bar."""
    font  = _load_font(11)
    img_b = _add_frame_label(_add_scalebar(Image.open(before_path).convert("RGB"), CTX_M_PER_PX, font), "BEFORE", font)
    img_a = _add_frame_label(_add_scalebar(Image.open(after_path).convert("RGB"),  CTX_M_PER_PX, font), "AFTER",  font)
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
        # Each obs ID starts with a 3-char token like D20, J02, P02, B01 …
        split_idx = next(
            (i for i, p in enumerate(parts) if i > 0 and re.match(r'^[A-Z]\d\d$', p)),
            None,
        )
        if split_idx:
            pid1 = "_".join(parts[:split_idx])
            pid2 = "_".join(parts[split_idx:])
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
total_skipped = 0

for kw in KEYWORDS:
    hits = keyword_hits[kw]
    if not hits:
        continue

    kw_dir = os.path.join(GIF_OUTPUT_DIR, kw)
    os.makedirs(kw_dir, exist_ok=True)

    print(f"\n── {kw} ({len(hits)} hits) ──")

    # ── Load existing metadata to preserve IDs and skip done GIFs ────────────
    meta_path = os.path.join(kw_dir, "metadata.csv")
    existing  = {}   # (hit_prefix, normpath(pair_path)) -> existing row dict
    all_rows  = []   # ordered list: existing rows first, new rows appended
    max_seq   = 0

    if os.path.exists(meta_path):
        with open(meta_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = (row.get("hit_prefix", ""), os.path.normpath(row.get("pair_path", "")))
                existing[key] = row
                all_rows.append(row)
                m = re.match(r'.+_(\d+)$', row.get("id", ""))
                if m:
                    max_seq = max(max_seq, int(m.group(1)))
        print(f"  Loaded {len(existing)} existing entries (max seq {max_seq})")

    seq = max_seq  # new hits count up from here

    for hit in hits:
        pair_path = hit.get("wholepath", "")
        prefix    = hit.get("hit_prefix", "")
        if not pair_path or not prefix:
            continue

        hit_key  = (prefix, os.path.normpath(pair_path))
        existing_row = existing.get(hit_key)

        if existing_row:
            gif_id   = existing_row["id"]
            gif_name = f"{gif_id}.gif"
            gif_path = os.path.join(kw_dir, gif_name)

            if os.path.exists(gif_path):
                # Already done — keep existing row unchanged
                total_skipped += 1
                print(f"  {gif_name}  (skipped — already exists)")
                continue

            # GIF file missing despite metadata entry — try to regenerate
            print(f"  {gif_name}  (re-generating missing GIF)")
        else:
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

        new_row = build_metadata_row(gif_id, hit, meta, gif_name, crops_ok)

        if existing_row:
            # Update the row in-place inside all_rows
            for r in all_rows:
                if r.get("id") == gif_id:
                    r.update(new_row)
                    break
        else:
            all_rows.append(new_row)

    # Write metadata.csv (preserves existing rows + appends new ones)
    with open(meta_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=METADATA_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"  → metadata.csv written ({len(all_rows)} rows)")

print(f"\nDone. {total_gifs} GIFs created, {total_skipped} skipped (already exist), {total_missing} missing crops.")
print(f"Output: {GIF_OUTPUT_DIR}")
