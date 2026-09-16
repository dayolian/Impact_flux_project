#!/usr/bin/env python3
"""
hirise_lookup.py

For flagged hits (confirmed/potential/interesting) whose comments contain
specified keywords, queries the NASA PDS ODE REST API for overlapping
HiRISE browse images and saves an annotated crop alongside each GIF.

Output (in gif_output/<KEYWORD>/):
  {id}__{obs_id}.jpg        — full HiRISE browse swath JPEG
  {id}__{obs_id}__crop.jpg  — 3 km crop centred on hit with colored box:
      green  = HiRISE acquired after CTX "after" image date
      yellow = HiRISE acquired between CTX before and after dates
      red    = HiRISE acquired before CTX "before" image date
  {id}__summary.txt         — selection rationale, all products found

Usage:
  Edit KEYWORDS below, then:  python hirise_lookup.py
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

from PIL import Image, ImageDraw

# ── Config ────────────────────────────────────────────────────────────────────

KEYWORDS = ["MEDIUM"]         # keywords to filter comments on

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
# HiRISE swath is ~6 km wide (±3 km). 0.03° ≈ 3.3 km at equator, so only
# images whose swath actually contains the hit point will be returned.
# Increase if you get zero results and want to widen the net.
BBOX_MARGIN = 0.03

# GIF crop size in metres (matches the 200px CTX context crop at ~6 m/px)
CLIP_METRES    = 1200.0
# Browse context crop: wider than the GIF box so you see surrounding terrain
BROWSE_CONTEXT_M = 3000.0
R_MARS         = 3_396_190.0  # IAU 2000 sphere radius, metres

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
                    "MAXIMUM_LATITUDE", "MINIMUM_LATITUDE",
                    "EASTERNMOST_LONGITUDE", "WESTERNMOST_LONGITUDE"):
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

        def _flt(key):
            v = fields.get(key, "")
            try:
                return float(v.replace("<DEG>", "")) if v else float("nan")
            except ValueError:
                return float("nan")

        max_lat  = _flt("MAXIMUM_LATITUDE")
        min_lat  = _flt("MINIMUM_LATITUDE")
        east_lon = _flt("EASTERNMOST_LONGITUDE")
        west_lon = _flt("WESTERNMOST_LONGITUDE")

        # True geographic centre of the image from its actual bounds
        # If label parsing missed bounds, try top-level ODE product fields
        def _item_flt(key):
            v = item.get(key, "")
            try:
                return float(str(v).strip()) if v not in (None, "", "null") else float("nan")
            except ValueError:
                return float("nan")

        if math.isnan(max_lat): max_lat  = _item_flt("Maximum_latitude")
        if math.isnan(min_lat): min_lat  = _item_flt("Minimum_latitude")
        if math.isnan(east_lon): east_lon = _item_flt("Easternmost_longitude")
        if math.isnan(west_lon): west_lon = _item_flt("Westernmost_longitude")

        if not any(math.isnan(x) for x in (max_lat, min_lat, east_lon, west_lon)):
            true_c_lat = (max_lat + min_lat) / 2.0
            true_c_lon = (east_lon % 360.0 + west_lon % 360.0) / 2.0
        else:
            true_c_lat = true_c_lon = float("nan")

        if not obs_id:
            continue

        jp2_url, browse_url = _hirise_urls(obs_id)
        products.append({
            "pdsid":         pds_id,
            "obs_id":        obs_id,
            "_date":         parse_date(start),
            "center_lat":    true_c_lat,
            "center_lon":    true_c_lon,
            "max_lat":       max_lat,
            "min_lat":       min_lat,
            "east_lon":      east_lon,
            "west_lon":      west_lon,
            "jp2_url":       jp2_url,
            "browse_url":    browse_url,
            "UTC_start_time": start,
        })

    return products


def select_best_product(products, before_date, after_date):
    """
    Choose the best HiRISE product and return (product, note, box_color).

    Priority (all try for newest within tier):
      green  — acquired after CTX after-image date (post-impact context)
      yellow — between CTX before and after dates
      red    — before CTX before-image date, or dates unknown

    Always returns something if products is non-empty.
    box_color is "green" | "yellow" | "red" | None (no products).
    """
    if not products:
        return None, "no HiRISE products found in search box", None

    dated = [p for p in products if p["_date"] is not None]
    newest = lambda lst: max(lst, key=lambda p: p["_date"])

    if after_date and dated:
        tier = [p for p in dated if p["_date"] > after_date]
        if tier:
            c = newest(tier)
            return c, f"after CTX after-date ({after_date}) → {c['_date']}", "green"

    if before_date and dated:
        tier = [p for p in dated if p["_date"] > before_date
                and (after_date is None or p["_date"] <= after_date)]
        if tier:
            c = newest(tier)
            return c, f"between CTX dates ({before_date}..{after_date}) → {c['_date']}", "yellow"

    # Fallback: newest available regardless of date
    if dated:
        c = newest(dated)
    else:
        c = products[0]
    return c, f"newest available → {c.get('_date','?')} (before CTX before-date or undated)", "red"




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



BOX_COLORS = {
    "green":  (0,   220, 80),
    "yellow": (255, 220, 0),
    "red":    (255, 60,  60),
}


def annotate_browse_crop(browse_path, out_crop, hit_lat, hit_lon,
                         min_lat, max_lat, west_lon, east_lon,
                         box_color_name, clip_m=CLIP_METRES,
                         context_m=BROWSE_CONTEXT_M):
    """
    Crop the full browse to context_m around the hit (for terrain context), then
    draw a colored rectangle showing the clip_m GIF extent.

    Box color encodes HiRISE date relative to CTX pair:
      green  = after CTX after-image (post-impact confirmation)
      yellow = between CTX before and after dates
      red    = before CTX before-image or date unknown

    Returns True on success.
    """
    try:
        img = Image.open(browse_path).convert("RGB")
        img_w, img_h = img.size
    except Exception:
        return False

    if any(math.isnan(x) for x in (min_lat, max_lat, west_lon, east_lon)):
        return False

    lat_span = max_lat - min_lat
    w360     = west_lon % 360.0
    e360     = east_lon % 360.0
    lon_span = (e360 - w360) % 360.0
    if lat_span <= 0 or lon_span <= 0:
        return False

    frac_x = ((hit_lon % 360.0 - w360) % 360.0) / lon_span
    frac_y = (max_lat - hit_lat) / lat_span   # 0=top(north), 1=bottom(south)

    if not (0.0 <= frac_x <= 1.0 and 0.0 <= frac_y <= 1.0):
        return False

    cx = frac_x * img_w
    cy = frac_y * img_h

    lat_span_m  = lat_span * (math.pi / 180.0) * R_MARS
    m_per_px    = lat_span_m / img_h
    ctx_half    = max(40, int(round(context_m / m_per_px / 2)))
    box_half    = max(10, int(round(clip_m    / m_per_px / 2)))

    px = int(round(cx)); py = int(round(cy))
    if not (0 <= px < img_w and 0 <= py < img_h):
        return False

    # Crop to context extent
    x0 = max(0, px - ctx_half); x1 = min(img_w, px + ctx_half)
    y0 = max(0, py - ctx_half); y1 = min(img_h, py + ctx_half)

    crop   = img.crop((x0, y0, x1, y1))
    draw   = ImageDraw.Draw(crop)
    color  = BOX_COLORS.get(box_color_name, BOX_COLORS["yellow"])

    # Rectangle showing the GIF extent, relative to crop origin
    cx_c = px - x0; cy_c = py - y0
    bx0  = max(0,            cx_c - box_half)
    bx1  = min(crop.width-1, cx_c + box_half)
    by0  = max(0,            cy_c - box_half)
    by1  = min(crop.height-1,cy_c + box_half)
    draw.rectangle([bx0, by0, bx1, by1], outline=color, width=3)

    # Small crosshair at hit centre
    arm = max(5, box_half // 6)
    draw.line([(max(0, cx_c-arm), cy_c), (min(crop.width-1,  cx_c+arm), cy_c)], fill=color, width=2)
    draw.line([(cx_c, max(0, cy_c-arm)), (cx_c, min(crop.height-1, cy_c+arm))], fill=color, width=2)

    crop.save(out_crop, "JPEG", quality=92)
    return True


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

for kw in KEYWORDS:
    hits = keyword_hits[kw]
    if not hits:
        continue

    kw_dir = os.path.join(GIF_DIR, kw)   # co-locate with GIFs in gif_output/
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
        chosen, note, box_color = select_best_product(products, before_date, after_date)

        if chosen is None:
            print(f"    NOTE: {note}")
        else:
            color_label = {"green": "after after-date", "yellow": "between CTX dates",
                           "red": "before before-date"}.get(box_color, "")
            print(f"    Selected: {chosen.get('pdsid','')}  [{box_color} — {color_label}]  ({note})")

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
            f"Selection note:   {note}",
            f"Box color:        {box_color}",
            f"HiRISE products found in search box: {len(products)}",
            f"",
        ]
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
                f"  Browse URL: {chosen.get('browse_url', '')}",
            ]
        with open(os.path.join(kw_dir, f"{gif_id}__summary.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(summary_lines) + "\n")

        if chosen is None:
            continue

        # ── download browse image ─────────────────────────────────────────────
        browse_url  = chosen.get("browse_url", "")
        obs_id      = chosen.get("obs_id", "hirise")
        browse_name = f"{gif_id}__{obs_id}.jpg"
        out_browse  = os.path.join(kw_dir, browse_name)

        browse_ok = False
        if browse_url:
            if not os.path.exists(out_browse):
                print(f"    Downloading browse image...")
                browse_ok = download_browse(browse_url, out_browse)
                if browse_ok:
                    sz = os.path.getsize(out_browse) / 1e3
                    print(f"    {browse_name} saved ({sz:.0f} KB)")
            else:
                browse_ok = True
                print(f"    {browse_name} already exists")

        # ── annotate browse crop with colored GIF-extent rectangle ────────────
        if browse_ok:
            crop_name  = f"{gif_id}__{obs_id}__crop.jpg"
            out_crop   = os.path.join(kw_dir, crop_name)
            b_min_lat  = chosen.get("min_lat",  float("nan"))
            b_max_lat  = chosen.get("max_lat",  float("nan"))
            b_west_lon = chosen.get("west_lon", float("nan"))
            b_east_lon = chosen.get("east_lon", float("nan"))
            if annotate_browse_crop(out_browse, out_crop,
                                    hit_lat, hit_lon,
                                    b_min_lat, b_max_lat,
                                    b_west_lon, b_east_lon,
                                    box_color):
                print(f"    browse crop saved: {crop_name}  [{box_color} box]")
            else:
                print(f"    browse crop failed (hit outside image or bounds missing)")

print("\nAll done.")
print(f"Output: {GIF_DIR}")
