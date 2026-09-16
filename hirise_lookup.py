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

# Must be set before GDAL/rasterio import to enable vsicurl range reads
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_TIMEOUT", "120")
os.environ.setdefault("PROJ_IGNORE_CELESTIAL_BODY", "YES")

import rasterio
import rasterio.windows
from pyproj import Transformer
from PIL import Image

# ── Config ────────────────────────────────────────────────────────────────────

KEYWORDS            = ["MEDIUM"]         # keywords to filter comments on
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
# HiRISE swath is ~6 km wide (±3 km). 0.03° ≈ 3.3 km at equator, so only
# images whose swath actually contains the hit point will be returned.
# Increase if you get zero results and want to widen the net.
BBOX_MARGIN = 0.03

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


def product_covers_hit(product, hit_lat, hit_lon):
    """
    Return True if the hit lat/lon falls within the product's PDS bounding box.
    Returns True (allow through) when bounds are unavailable.
    """
    min_lat  = product.get("min_lat",  float("nan"))
    max_lat  = product.get("max_lat",  float("nan"))
    west_lon = product.get("west_lon", float("nan"))
    east_lon = product.get("east_lon", float("nan"))
    if any(math.isnan(x) for x in (min_lat, max_lat, west_lon, east_lon)):
        return True
    lat_ok = min_lat <= hit_lat <= max_lat
    # Normalise to 0..360 for longitude comparison
    h360 = hit_lon  % 360.0
    w360 = west_lon % 360.0
    e360 = east_lon % 360.0
    lon_ok = (h360 >= w360 and h360 <= e360) if w360 <= e360 else (h360 >= w360 or h360 <= e360)
    return lat_ok and lon_ok


def _project_hit_to_crs(src, hit_lat, hit_lon):
    """
    Project (hit_lat, hit_lon) WGS84 degrees into the rasterio dataset's CRS.
    Returns (x_crs, y_crs) in the file's units, or raises on failure.
    Uses pyproj with PROJ_IGNORE_CELESTIAL_BODY=YES so Mars CRS works.
    """
    # Always use lon/lat → file CRS with always_xy=True
    t = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
    return t.transform(hit_lon, hit_lat)


def attempt_vsicurl_clip(product_url, hit_lat, hit_lon, clip_m, out_tif):
    """
    Try to read a clip from a remote JP2 via GDAL vsicurl range reads.
    Returns (True, '') on success, (False, reason) on failure.
    """
    vsi_url = f"/vsicurl/{product_url}"

    try:
        with rasterio.open(vsi_url) as src:
            x_crs, y_crs = _project_hit_to_crs(src, hit_lat, hit_lon)

            h, w = src.height, src.width
            # Pixel scale from the affine transform (metres per pixel)
            px_scale = abs(src.transform.a)
            half_px = max(1, int(round(clip_m / px_scale / 2)))

            row_i, col_i = src.index(x_crs, y_crs)  # rasterio.index → (row, col)

            if not (0 <= col_i < w and 0 <= row_i < h):
                return False, (f"hit projects to col={col_i}, row={row_i} "
                               f"outside image {w}x{h} — not within this HiRISE footprint")

            col0 = max(0, col_i - half_px)
            row0 = max(0, row_i - half_px)
            col1 = min(w, col_i + half_px)
            row1 = min(h, row_i + half_px)

            window = rasterio.windows.Window(
                col_off=col0, row_off=row0,
                width=col1 - col0, height=row1 - row0
            )
            data = src.read(1, window=window)

            win_transform = rasterio.windows.transform(window, src.transform)
            profile = src.profile.copy()
            profile.update(
                width=data.shape[1], height=data.shape[0],
                transform=win_transform, compress="deflate"
            )
            with rasterio.open(out_tif, "w", **profile) as dst:
                dst.write(data, 1)

        return True, ""

    except Exception as e:
        return False, str(e)


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


def _delta_lon_deg(hit_lon, center_lon):
    """
    Signed angular difference (hit - center) in degrees, normalized to [-180, 180].
    Handles the mismatch where hit_lon is -180..+180 and ODE center_lon is 0..360.
    """
    d = (hit_lon % 360.0 - center_lon % 360.0) % 360.0
    if d > 180.0:
        d -= 360.0
    return d


def crop_browse_to_extent(browse_path, out_crop, hit_lat, hit_lon,
                          min_lat, max_lat, west_lon, east_lon, clip_m=CLIP_METRES):
    """
    Crop the full browse image to ~clip_m around the hit using the image's actual
    PDS geographic bounds.  The browse is assumed to be a north-up equirect JPEG:
      x=0 → west_lon,  x=img_w → east_lon
      y=0 → max_lat,   y=img_h → min_lat
    Draws a yellow crosshair at the hit position.
    Returns True on success, False if hit is outside image or bounds are bad.
    """
    try:
        img = Image.open(browse_path).convert("RGB")
        img_w, img_h = img.size
    except Exception:
        return False

    if any(math.isnan(x) for x in (min_lat, max_lat, west_lon, east_lon)):
        return False

    lat_span = max_lat - min_lat
    # Normalise longitudes to 0..360 and compute span
    w360     = west_lon % 360.0
    e360     = east_lon % 360.0
    lon_span = (e360 - w360) % 360.0
    if lat_span <= 0 or lon_span <= 0:
        return False

    # Fractional position of hit in image (north-up, west-left)
    frac_x = ((hit_lon % 360.0 - w360) % 360.0) / lon_span
    frac_y = (max_lat - hit_lat) / lat_span   # 0=top(north), 1=bottom(south)

    if not (0.0 <= frac_x <= 1.0 and 0.0 <= frac_y <= 1.0):
        return False

    cx = frac_x * img_w
    cy = frac_y * img_h

    # Pixel scale from actual footprint
    lat_span_m = lat_span * (math.pi / 180.0) * R_MARS
    m_per_px   = lat_span_m / img_h
    half_px    = max(20, int(round(clip_m / m_per_px / 2)))

    px = int(round(cx)); py = int(round(cy))
    if not (0 <= px < img_w and 0 <= py < img_h):
        return False

    x0 = max(0, px - half_px); x1 = min(img_w, px + half_px)
    y0 = max(0, py - half_px); y1 = min(img_h, py + half_px)

    from PIL import ImageDraw
    crop = img.crop((x0, y0, x1, y1))
    draw = ImageDraw.Draw(crop)
    cx_c = px - x0; cy_c = py - y0
    arm  = max(8, half_px // 5)
    draw.line([(max(0, cx_c - arm), cy_c), (min(crop.width  - 1, cx_c + arm), cy_c)],
              fill=(255, 220, 0), width=2)
    draw.line([(cx_c, max(0, cy_c - arm)), (cx_c, min(crop.height - 1, cy_c + arm))],
              fill=(255, 220, 0), width=2)
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

os.makedirs(OUTPUT_DIR, exist_ok=True)

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

        # Filter to products whose bounding box actually contains the hit point
        covered = [p for p in products if product_covers_hit(p, hit_lat, hit_lon)]
        if len(covered) < len(products):
            print(f"    Footprint filter: {len(products) - len(covered)} excluded "
                  f"(hit not within bbox) → {len(covered)} remain")
        products = covered

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

        # ── write summary.txt (goes directly in kw_dir) ──────────────────────
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

        with open(os.path.join(kw_dir, f"{gif_id}__summary.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(summary_lines) + "\n")

        if chosen is None:
            continue

        # ── try full-res clip via vsicurl ─────────────────────────────────────
        # Try chosen product first, then fall back to other products in date order
        out_tif = os.path.join(kw_dir, f"{gif_id}__hirise_clip.tif")
        clip_ok = False

        if os.path.exists(out_tif):
            print(f"    {gif_id}__hirise_clip.tif already exists, skipping clip")
            clip_ok = True
        else:
            # Build ordered list: chosen first, then others sorted by date desc
            candidates = []
            if chosen:
                candidates.append(chosen)
            for p in sorted(products, key=lambda x: x.get("UTC_start_time",""), reverse=True):
                if p is not chosen:
                    candidates.append(p)

            for p in candidates:
                jp2_url = p.get("jp2_url", "")
                if not jp2_url:
                    continue
                label = "chosen" if p is chosen else p.get("obs_id","?")
                print(f"    Trying vsicurl clip: {p.get('obs_id','')} ({label})")
                ok, reason = attempt_vsicurl_clip(jp2_url, hit_lat, hit_lon,
                                                   CLIP_METRES, out_tif)
                if ok:
                    sz = os.path.getsize(out_tif) / 1e6
                    print(f"    ✓ clip saved ({sz:.1f} MB)  [{p.get('obs_id','')}]")
                    clip_ok = True
                    chosen = p
                    # Write a display JPEG with proper stretch for viewing
                    jpg_out = out_tif.replace("__hirise_clip.tif", "__hirise_clip.jpg")
                    try:
                        with rasterio.open(out_tif) as src:
                            data = src.read(1).astype(float)
                        lo, hi = data.min(), data.max()
                        if hi > lo:
                            scaled = ((data - lo) / (hi - lo) * 255).clip(0, 255).astype("uint8")
                        else:
                            scaled = data.astype("uint8")
                        Image.fromarray(scaled).save(jpg_out, "JPEG", quality=92)
                        print(f"    ✓ display JPEG saved  [{os.path.basename(jpg_out)}]")
                    except Exception as e:
                        print(f"    display JPEG failed: {e}")
                    break
                else:
                    print(f"      ✗ {reason}")

            if not clip_ok:
                print(f"    No vsicurl clip succeeded — browse only")

        # ── download browse image (always, even when clip succeeded) ─────────
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

        # ── crop browse to GIF extent (~1200 m) around the hit ────────────────
        if browse_ok:
            crop_name = f"{gif_id}__{obs_id}__crop.jpg"
            out_crop  = os.path.join(kw_dir, crop_name)
            b_min_lat  = chosen.get("min_lat",  float("nan"))
            b_max_lat  = chosen.get("max_lat",  float("nan"))
            b_west_lon = chosen.get("west_lon", float("nan"))
            b_east_lon = chosen.get("east_lon", float("nan"))
            if crop_browse_to_extent(out_browse, out_crop,
                                     hit_lat, hit_lon,
                                     b_min_lat, b_max_lat,
                                     b_west_lon, b_east_lon):
                print(f"    browse crop saved: {crop_name}")
            else:
                print(f"    browse crop failed (hit outside image or missing bounds)")

print("\nAll done.")
print(f"Output: {GIF_DIR}")
