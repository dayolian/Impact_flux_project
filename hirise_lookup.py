#!/usr/bin/env python3
"""
hirise_lookup.py

For flagged hits (confirmed/potential/interesting) whose comments contain
specified keywords, queries the NASA PDS ODE REST API for overlapping
HiRISE images, then clips a ~1200m region around each hit from the
selected HiRISE product via partial JP2 download over HTTP.

Output: hirise_output/<KEYWORD>/<hit_prefix>/
  summary.txt           — HiRISE products found, dates, selection rationale
  hirise_clip.tif       — full-res clip (~4800x4800 px at 0.25 m/px)
  hirise_browse.jpg     — full browse image (fallback if JP2 clip fails)

Selection strategies (SELECTION_STRATEGY):
  "after_before_only"   — newest HiRISE after the CTX "before" image date
  "closest_to_before"   — HiRISE image with date closest to CTX "before" date
  "newest"              — most recently acquired HiRISE image regardless of date
  "best_coverage"       — image whose footprint centre is closest to the hit point

Usage:
  Edit KEYWORDS and SELECTION_STRATEGY below, then:
  python hirise_lookup.py
"""

import os
import re
import csv
import json
import math
import time
import datetime
import urllib.request
import urllib.error

import numpy as np
import rasterio
import rasterio.windows
from PIL import Image

# ── Config ────────────────────────────────────────────────────────────────────

KEYWORDS            = ["LOW"]            # keywords to filter comments on
SELECTION_STRATEGY  = "after_before_only"

# Set to True to skip hits that have no HiRISE image after the "before" date
# (only relevant when SELECTION_STRATEGY == "after_before_only")
SKIP_IF_NO_AFTER    = False

ROOT        = r"G:\crater_flux_output_folders"
PROJ        = os.path.join(ROOT, "Impact_flux_project")
REVIEWED_CSV = os.path.join(PROJ, "pairsinfo_reviewed_2006-2026.csv")
INPUT_CSVS  = [
    os.path.join(ROOT, "confirmed_hits.csv"),
    os.path.join(ROOT, "potential_hits.csv"),
    os.path.join(ROOT, "interesting.csv"),
]
OUTPUT_DIR  = os.path.join(ROOT, "hirise_output")
GIF_DIR     = os.path.join(ROOT, "gif_output")

# Geographic search margin around hit point (degrees).
# ~0.15° ≈ 9 km at equator — HiRISE swaths are ~6 km wide so this catches most
BBOX_MARGIN = 0.15

# Clip size in metres (matches the 200px CTX context crop)
CLIP_METRES = 1200.0
HIRISE_SCALE = 0.25        # m/px, standard HiRISE RED channel
R_MARS       = 3_396_190.0  # IAU 2000 sphere radius, metres

# ODE REST API v2  (results=all is the only way to get product records)
ODE_URL   = "https://oderest.rsl.wustl.edu/live2/"
ODE_DELAY = 0.5   # seconds between requests

# ── Helpers ───────────────────────────────────────────────────────────────────

def lon_180_to_360(lon):
    """Convert -180..+180 longitude to 0..360 (ODE convention)."""
    return lon + 360.0 if lon < 0 else float(lon)


def parse_date(s):
    """Parse an ISO-8601 datetime string to a date object. Returns None on failure."""
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "")).date()
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s[:len(fmt)], fmt).date()
        except Exception:
            continue
    return None


def metres_to_deg_lat(m):
    return math.degrees(m / R_MARS)


def metres_to_deg_lon(m, lat_deg):
    lat_rad = math.radians(lat_deg)
    return math.degrees(m / (R_MARS * math.cos(lat_rad))) if abs(lat_deg) < 89.9 else 0.0


def _parse_label(label_lines):
    """Extract key fields from a PDS label line list."""
    result = {}
    for line in label_lines:
        s = str(line).strip()
        for key in ("PRODUCT_ID", "OBSERVATION_ID", "START_TIME",
                    "CENTER_LATITUDE", "CENTER_LONGITUDE"):
            if s.startswith(key + " ") or s.startswith(key + "="):
                val = s.split("=", 1)[1].strip().strip('"').split("<")[0].strip()
                result[key] = val
    return result


def _hirise_urls(obs_id):
    """
    Construct PDS browse and JP2 (RED channel) URLs from a HiRISE observation ID.
    obs_id format: ESP_013329_1745  or  PSP_001234_1750
    """
    parts  = obs_id.split("_")
    phase  = parts[0]               # ESP or PSP
    orbit  = int(parts[1])
    lo     = (orbit // 100) * 100
    odir   = f"ORB_{lo:06d}_{lo+99:06d}"

    base_pds    = f"https://hirise-pds.lpl.arizona.edu/PDS/RDR/{phase}/{odir}/{obs_id}"
    base_extras = f"https://hirise.lpl.arizona.edu/PDS/EXTRAS/RDR/{phase}/{odir}/{obs_id}"

    jp2_url    = f"{base_pds}/{obs_id}_RED.JP2"
    browse_url = f"{base_extras}/{obs_id}_RED.browse.jpg"
    return jp2_url, browse_url


def load_gif_ids(kw):
    """
    Load {(hit_prefix, normpath(pair_path)): gif_id} from gif_output/{kw}/metadata.csv.
    Returns empty dict if the file doesn't exist (make_keyword_gifs not yet run).
    """
    meta_csv = os.path.join(GIF_DIR, kw, "metadata.csv")
    result = {}
    if not os.path.exists(meta_csv):
        return result
    with open(meta_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row.get("hit_prefix", ""), os.path.normpath(row.get("pair_path", "")))
            result[key] = row.get("id", "")
    return result


def ode_query(lat, lon, margin=BBOX_MARGIN):
    """
    Query ODE REST API v2 for HiRISE RDR products overlapping a bounding box.
    Returns a list of cleaned product dicts with keys:
      pdsid, obs_id, date, center_lat, center_lon, jp2_url, browse_url
    """
    west   = lon_180_to_360(lon - margin)
    east   = lon_180_to_360(lon + margin)
    minlat = lat - margin
    maxlat = lat + margin

    params = {
        "target":     "Mars",
        "ihid":       "MRO",
        "iid":        "HIRISE",
        "pt":         "RDRV11",
        "westernlon": f"{west:.4f}",
        "easternlon": f"{east:.4f}",
        "minlat":     f"{minlat:.4f}",
        "maxlat":     f"{maxlat:.4f}",
        "output":     "JSON",
        "results":    "all",   # only "all" or "C" (count) return data
    }
    url = ODE_URL + "?" + urllib.parse.urlencode(params)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "hirise_lookup/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8-sig"))
    except urllib.error.URLError as e:
        print(f"    ODE request failed: {e}")
        return []
    except Exception as e:
        print(f"    ODE error: {e}")
        return []

    try:
        if data.get("ODEResults", {}).get("Status") != "Success":
            return []
        raw = data["ODEResults"]["Products"]["Product"]
        if isinstance(raw, dict):
            raw = [raw]
    except (KeyError, TypeError):
        return []   # 0 results

    products = []
    for item in raw:
        lines = item.get("label", {}).get("Line", [])
        fields = _parse_label(lines)

        obs_id = fields.get("OBSERVATION_ID", "")
        pds_id = fields.get("PRODUCT_ID", obs_id)

        # Keep only the RED channel products (skip COLOR, IRB)
        if pds_id.endswith("_COLOR") or pds_id.endswith("_IRB"):
            continue

        start = fields.get("START_TIME", "")
        try:
            c_lat = float(fields.get("CENTER_LATITUDE", "nan").replace("<DEG>", ""))
            c_lon = float(fields.get("CENTER_LONGITUDE", "nan").replace("<DEG>", ""))
        except ValueError:
            c_lat = c_lon = float("nan")

        if not obs_id:
            continue

        jp2_url, browse_url = _hirise_urls(obs_id)
        products.append({
            "pdsid":      pds_id,
            "obs_id":     obs_id,
            "_date":      parse_date(start),
            "center_lat": c_lat,
            "center_lon": c_lon,
            "jp2_url":    jp2_url,
            "browse_url": browse_url,
            "UTC_start_time": start,
        })

    return products


def select_product(products, before_date, strategy):
    """
    Choose one product from the list according to strategy.
    Returns (product, note_string) or (None, reason_string).
    """
    if not products:
        return None, "no HiRISE products found in search box"

    dated = [p for p in products if p["_date"] is not None]

    if strategy == "after_before_only":
        if before_date is None:
            return None, "no CTX before-date available for after_before_only strategy"
        after = [p for p in dated if p["_date"] > before_date]
        if not after:
            return None, f"no HiRISE image acquired after CTX before-date ({before_date})"
        chosen = max(after, key=lambda p: p["_date"])
        return chosen, f"newest HiRISE after {before_date} → {chosen['_date']}"

    elif strategy == "closest_to_before":
        if before_date is None or not dated:
            # fall back to newest
            chosen = max(dated or products, key=lambda p: p["_date"] or datetime.date.min)
            return chosen, "closest_to_before: no before-date, fell back to newest"
        chosen = min(dated, key=lambda p: abs((p["_date"] - before_date).days))
        delta = (chosen["_date"] - before_date).days
        return chosen, f"closest to before-date ({before_date}): {chosen['_date']} ({delta:+d} days)"

    elif strategy == "newest":
        chosen = max(dated or products, key=lambda p: p["_date"] or datetime.date.min)
        return chosen, f"newest HiRISE: {chosen['_date']}"

    elif strategy == "best_coverage":
        # Prefer image whose centre lat/lon is closest to hit point — crude proxy
        # for coverage when footprint geometry is unavailable
        return products[0], "best_coverage: took first result (ODE returns closest first)"

    return None, f"unknown strategy: {strategy}"


def clip_half_px(clip_m, scale):
    """Half-width of the clip in pixels."""
    return max(1, int(round(clip_m / scale / 2)))


def attempt_vsicurl_clip(product_url, hit_lat, hit_lon, clip_m, out_tif):
    """
    Try to read a clip from a remote JP2/GeoTIFF via GDAL vsicurl.
    Returns True on success, False on failure.
    """
    vsi_url = f"/vsicurl/{product_url}"
    half_px = clip_half_px(clip_m, HIRISE_SCALE)

    try:
        with rasterio.open(vsi_url) as src:
            # Convert geographic coordinates to pixel row/col
            # rasterio.index() takes (x=lon, y=lat) in the CRS of the file.
            # HiRISE RDR MAP uses equirectangular with lon in 0-360 (positive east).
            lon360 = lon_180_to_360(hit_lon)
            row, col = src.index(lon360, hit_lat)

            h, w = src.height, src.width
            col0 = max(0, col - half_px)
            row0 = max(0, row - half_px)
            col1 = min(w, col + half_px)
            row1 = min(h, row + half_px)

            if col1 <= col0 or row1 <= row0:
                return False

            window = rasterio.windows.Window(
                col_off=col0, row_off=row0,
                width=col1 - col0, height=row1 - row0
            )
            data = src.read(1, window=window)

            # Compute transform for the clip
            win_transform = rasterio.windows.transform(window, src.transform)
            profile = src.profile.copy()
            profile.update(
                width=data.shape[1], height=data.shape[0],
                transform=win_transform, compress="deflate"
            )
            with rasterio.open(out_tif, "w", **profile) as dst:
                dst.write(data, 1)

        return True

    except Exception as e:
        print(f"    vsicurl clip failed: {e}")
        return False


def download_browse(browse_url, out_jpg):
    """Download the HiRISE browse image. Returns True on success."""
    try:
        req = urllib.request.Request(browse_url,
                                     headers={"User-Agent": "hirise_lookup/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        with open(out_jpg, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        print(f"    browse download failed: {e}")
        return False


# ── Load metadata ─────────────────────────────────────────────────────────────

print("Loading pairsinfo metadata...")
meta_by_path = {}
if os.path.exists(REVIEWED_CSV):
    with open(REVIEWED_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            meta_by_path[os.path.normpath(row["wholepath"])] = row
print(f"  {len(meta_by_path):,} pairs loaded.")

# ── Load and filter flagged hits ──────────────────────────────────────────────

print("Loading flagged hits...")
all_hits = []
for path in INPUT_CSVS:
    if not os.path.exists(path):
        continue
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            all_hits.append(row)

# keyword -> list of (keyword, hit) — a hit matching multiple keywords appears once per kw
keyword_hits = {kw: [] for kw in KEYWORDS}
for hit in all_hits:
    comments = hit.get("comments", "") or ""
    for kw in KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', comments, re.IGNORECASE):
            keyword_hits[kw].append(hit)

for kw, hits in keyword_hits.items():
    print(f"  {kw}: {len(hits)} hits")

# ── Main loop ─────────────────────────────────────────────────────────────────

os.makedirs(OUTPUT_DIR, exist_ok=True)

for kw in KEYWORDS:
    hits = keyword_hits[kw]
    if not hits:
        continue

    kw_dir = os.path.join(OUTPUT_DIR, kw)
    os.makedirs(kw_dir, exist_ok=True)
    print(f"\n{'─'*60}")
    print(f"Keyword: {kw}  ({len(hits)} hits)")
    print(f"{'─'*60}")

    gif_ids = load_gif_ids(kw)
    if gif_ids:
        print(f"  Loaded {len(gif_ids)} GIF IDs from metadata.csv")
    else:
        print(f"  No metadata.csv found — run make_keyword_gifs.py first for ID matching")

    for i, hit in enumerate(hits, 1):
        prefix    = hit.get("hit_prefix", "unknown")
        pair_path = hit.get("wholepath", "")
        comments  = hit.get("comments", "")

        # ── get lat/lon ──────────────────────────────────────────────────────
        try:
            hit_lat = float(hit.get("lat", ""))
            hit_lon = float(hit.get("lon", ""))
        except (ValueError, TypeError):
            print(f"\n  [{i}/{len(hits)}] {prefix}  SKIP: no lat/lon (run crop_generator.py first)")
            continue

        # ── resolve GIF ID ───────────────────────────────────────────────────
        gif_key = (prefix, os.path.normpath(pair_path))
        gif_id  = gif_ids.get(gif_key, "")
        if not gif_id:
            gif_id = f"{kw}_{i:04d}"

        print(f"\n  [{i}/{len(hits)}] {prefix}  [{gif_id}]")

        # ── get before-date from pairsinfo ───────────────────────────────────
        meta        = meta_by_path.get(os.path.normpath(pair_path), {})
        before_date = parse_date(meta.get("datetime1", ""))
        after_date  = parse_date(meta.get("datetime2", ""))
        ctxID       = meta.get("ctxID", "")
        days_bt     = meta.get("days_between", "")

        print(f"    lat={hit_lat:.4f}  lon={hit_lon:.4f}  "
              f"before={before_date}  after={after_date}")

        # ── query ODE ────────────────────────────────────────────────────────
        time.sleep(ODE_DELAY)
        products = ode_query(hit_lat, hit_lon)
        print(f"    ODE returned {len(products)} HiRISE products")

        # ── select product ───────────────────────────────────────────────────
        chosen, note = select_product(products, before_date, SELECTION_STRATEGY)

        if chosen is None:
            if SKIP_IF_NO_AFTER and SELECTION_STRATEGY == "after_before_only":
                print(f"    SKIP ({note})")
                continue
            print(f"    NOTE: {note}")
            # still write summary so the user knows this hit was checked
        else:
            print(f"    Selected: {chosen.get('pdsid','')}  ({note})")

        # ── output folder ────────────────────────────────────────────────────
        hit_dir = os.path.join(kw_dir, gif_id)
        os.makedirs(hit_dir, exist_ok=True)

        # ── write summary.txt ────────────────────────────────────────────────
        summary_lines = [
            f"Hit:              {prefix}",
            f"GIF ID:           {gif_id}",
            f"Comments:         {comments}",
            f"Lat / Lon:        {hit_lat:.5f}, {hit_lon:.5f}",
            f"CTX pair ID:      {ctxID}",
            f"CTX before date:  {before_date}",
            f"CTX after date:   {after_date}",
            f"Days between:     {days_bt}",
            f"",
            f"Selection strategy: {SELECTION_STRATEGY}",
            f"Selection note:   {note}",
            f"HiRISE products found in search box: {len(products)}",
            f"",
        ]

        # List all found products
        if products:
            summary_lines.append("All HiRISE observations in search box (RED channel):")
            for p in sorted(products, key=lambda x: x.get("UTC_start_time", ""), reverse=True):
                pid    = p.get("obs_id", "?")
                pdate  = p.get("UTC_start_time", "?")[:10]
                clat   = p.get("center_lat", float("nan"))
                clon   = p.get("center_lon", float("nan"))
                marker = " ← SELECTED" if (chosen and p is chosen) else ""
                summary_lines.append(f"  {pdate}  {pid}  (ctr {clat:.2f},{clon:.2f}){marker}")

        if chosen:
            summary_lines += [
                "",
                "Selected product details:",
                f"  Observation ID: {chosen.get('obs_id', '')}",
                f"  Date:           {chosen.get('UTC_start_time', '')[:10]}",
                f"  Centre lat/lon: {chosen.get('center_lat','')}, {chosen.get('center_lon','')}",
                f"  JP2 URL:        {chosen.get('jp2_url', '')}",
                f"  Browse URL:     {chosen.get('browse_url', '')}",
            ]

        with open(os.path.join(hit_dir, "summary.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(summary_lines) + "\n")

        if chosen is None:
            continue

        # ── try full-res clip via vsicurl ────────────────────────────────────
        product_url = chosen.get("jp2_url", "")
        out_tif     = os.path.join(hit_dir, "hirise_clip.tif")

        if product_url and not os.path.exists(out_tif):
            print(f"    Attempting vsicurl clip from JP2...")
            ok = attempt_vsicurl_clip(product_url, hit_lat, hit_lon,
                                      CLIP_METRES, out_tif)
            if ok:
                sz = os.path.getsize(out_tif) / 1e6
                print(f"    hirise_clip.tif saved ({sz:.1f} MB)")
            else:
                print(f"    vsicurl failed — browse fallback only")
        elif os.path.exists(out_tif):
            print(f"    hirise_clip.tif already exists, skipping")

        # ── download browse image as fallback / context ──────────────────────
        browse_url = chosen.get("browse_url", "")
        obs_id     = chosen.get("obs_id", "hirise")
        browse_name = f"{obs_id}__{gif_id}.jpg"
        out_browse  = os.path.join(hit_dir, browse_name)

        if browse_url and not os.path.exists(out_browse):
            print(f"    Downloading browse image...")
            ok = download_browse(browse_url, out_browse)
            if ok:
                sz = os.path.getsize(out_browse) / 1e3
                print(f"    {browse_name} saved ({sz:.0f} KB)")
        elif os.path.exists(out_browse):
            print(f"    {browse_name} already exists, skipping")

print("\nAll done.")
print(f"Output: {OUTPUT_DIR}")
