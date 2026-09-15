#!/usr/bin/env python3
"""
Mars Impact Crater Validation GUI - Server
Run:  python server.py
Then: open http://localhost:5000
"""

import os
import csv
import urllib.parse
from collections import deque
from datetime import datetime
from flask import Flask, jsonify, send_file, request, abort, send_from_directory

try:
    from PIL import Image
    import numpy as np
    IMAGE_FILTER_AVAILABLE = True
except ImportError:
    IMAGE_FILTER_AVAILABLE = False
    print("WARNING: Pillow/numpy not found — black-edge filtering disabled. "
          "Run: pip install pillow numpy")

# ─── Config ──────────────────────────────────────────────────────────────────

MASTER_CSV = r"G:\crater_flux_output_folders\Impact_flux_project\pairsinfo_combo_master_max20hits.csv"
OUTPUT_DIR = r"G:\crater_flux_output_folders"

OUTPUT_FILES = {
    "confirmed_hit": os.path.join(OUTPUT_DIR, "confirmed_hits.csv"),
    "potential_hit": os.path.join(OUTPUT_DIR, "potential_hits.csv"),
    "interesting":   os.path.join(OUTPUT_DIR, "interesting.csv"),
}

OUT_COLS      = ["wholepath", "pair_name", "hit_prefix", "ARE", "x", "y", "label", "reviewed_timestamp"]
PAGE_SIZE     = 18
VALID_LABELS  = set(OUTPUT_FILES.keys())

# Black-edge filtering: skip hits where the center pixel is black (< BLACK_THRESHOLD)
# and the connected black region containing it covers more than BLACK_COVERAGE of the image.
# Threshold > 0 accounts for JPEG compression softening true-zero nodata pixels.
BLACK_THRESHOLD = 10
BLACK_COVERAGE  = 0.50

# Allowed path prefixes for image serving (security check)
IMG_ROOTS = [
    os.path.normpath(OUTPUT_DIR),
    os.path.normpath(os.path.dirname(MASTER_CSV)),
]

# ─── Flask app ───────────────────────────────────────────────────────────────

GUI_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=GUI_DIR, static_url_path="")

# ─── Global state ────────────────────────────────────────────────────────────

all_rows         = []  # complete list of dicts from master CSV (every row)
pairs            = []  # filtered subset: hits > 0 (same dict objects as in all_rows)
pair_all_indices = []  # pair_all_indices[i] = index of pairs[i] inside all_rows
pair_idx         = 0   # current position in pairs[]
page_idx         = 0   # current page within the current pair's hits
hits             = []  # hits for current pair, sorted descending by ARE
labeled          = {}  # prefix -> label  (in-memory; flushed to disk on next-pair)
prev_saved       = {}  # prefix -> label  (already written to output CSVs in prior sessions)

# ─── Master CSV helpers ──────────────────────────────────────────────────────

def load_master():
    """Read master CSV. Returns list of dicts, stripping empty keys from trailing commas."""
    with open(MASTER_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append({k.strip(): v for k, v in row.items() if k and k.strip()})
    return rows


def save_master():
    """Write all_rows back to master CSV, adding review_status column if new."""
    if not all_rows:
        return
    fieldnames = list(all_rows[0].keys())
    if "review_status" not in fieldnames:
        fieldnames.append("review_status")
    with open(MASTER_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(all_rows)

# ─── Output CSV helpers ──────────────────────────────────────────────────────

def ensure_output_files():
    for path in OUTPUT_FILES.values():
        if not os.path.exists(path):
            with open(path, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=OUT_COLS).writeheader()


def load_prev_saved():
    """Read all output CSVs; return dict of prefix -> label."""
    result = {}
    for label, path in OUTPUT_FILES.items():
        if os.path.exists(path):
            with open(path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    prefix = row.get("hit_prefix", "").strip()
                    if prefix:
                        result[prefix] = label
    return result


def flush_labels_to_csv():
    """Append newly labeled hits (not already on disk) to output CSVs."""
    if pair_idx >= len(pairs):
        return
    pair      = pairs[pair_idx]
    pair_path = pair["wholepath"]
    pair_name = os.path.basename(pair_path.rstrip("\\/"))
    now       = datetime.now().isoformat(timespec="seconds")

    rows_by_label = {lbl: [] for lbl in OUTPUT_FILES}
    for prefix, lbl in labeled.items():
        if prefix in prev_saved:
            continue  # already written in a previous session
        if lbl not in rows_by_label:
            continue
        parts = prefix.split("_")  # hit, ARE, x, y
        rows_by_label[lbl].append({
            "wholepath":          pair_path,
            "pair_name":          pair_name,
            "hit_prefix":         prefix,
            "ARE":                parts[1],
            "x":                  parts[2],
            "y":                  parts[3],
            "label":              lbl,
            "reviewed_timestamp": now,
        })

    for lbl, rows in rows_by_label.items():
        if rows:
            with open(OUTPUT_FILES[lbl], "a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=OUT_COLS).writerows(rows)

# ─── Black-edge filtering ────────────────────────────────────────────────────

def is_black_edge_hit(img_path):
    """
    Return True if the center pixel of the crop is exactly black (== 0)
    AND the connected region of black pixels containing it covers more
    than BLACK_COVERAGE of the image.

    This catches crops where the detected hit lands in the nodata padding
    at the tilted edge of the orbital image strip.
    Fails open: if the image can't be read, the hit is kept for review.
    """
    if not IMAGE_FILTER_AVAILABLE:
        return False
    try:
        img = Image.open(img_path).convert("L")
        arr = np.array(img, dtype=np.uint8)
        h, w = arr.shape
        cy, cx = h // 2, w // 2

        # Center pixel must be black
        if arr[cy, cx] >= BLACK_THRESHOLD:
            return False

        # Quick bail: total black pixels must be enough to exceed coverage
        black = arr < BLACK_THRESHOLD
        if black.sum() < h * w * BLACK_COVERAGE:
            return False

        # Flood-fill from center through connected black pixels
        visited = np.zeros((h, w), dtype=bool)
        q = deque([(cy, cx)])
        visited[cy, cx] = True
        while q:
            y, x = q.popleft()
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and arr[ny, nx] < BLACK_THRESHOLD and not visited[ny, nx]:
                    visited[ny, nx] = True
                    q.append((ny, nx))

        return visited.sum() / (h * w) > BLACK_COVERAGE

    except Exception:
        return False  # if anything fails, don't suppress the hit


def should_skip_hit(pair_path, prefix):
    """Return True if either crop image is a black-edge hit."""
    before = os.path.join(pair_path, f"{prefix}_before.jpg")
    after  = os.path.join(pair_path, f"{prefix}_after.jpg")
    return is_black_edge_hit(before) or is_black_edge_hit(after)


# ─── Hit loading ─────────────────────────────────────────────────────────────

def load_hits_for_pair(pair_row):
    """Load hit_list.csv for a pair; return list of hit dicts sorted desc by ARE."""
    hit_list_path = os.path.join(pair_row["wholepath"], "hit_list.csv")
    if not os.path.exists(hit_list_path):
        return []
    result = []
    with open(hit_list_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            prefix = row.get("prefix", "").strip()
            parts  = prefix.split("_")
            if len(parts) != 4:
                continue
            try:
                result.append({
                    "prefix": prefix,
                    "ARE":    int(parts[1]),
                    "x":      int(parts[2]),
                    "y":      int(parts[3]),
                })
            except ValueError:
                continue
    result.sort(key=lambda h: h["ARE"], reverse=True)

    # Filter out hits where a crop image is dominated by border-connected nodata black
    pair_path = pair_row["wholepath"]
    result = [h for h in result if not should_skip_hit(pair_path, h["prefix"])]

    return result

# ─── Navigation ──────────────────────────────────────────────────────────────

def advance_pair():
    """
    Scan forward from pair_idx to find the next unreviewed pair that has hits.
    Loads that pair's hits into global state. Returns True if found, False if all done.
    """
    global pair_idx, page_idx, hits, labeled
    while pair_idx < len(pairs):
        pair   = pairs[pair_idx]
        status = pair.get("review_status", "").strip().lower()
        if status == "done":
            pair_idx += 1
            continue
        h = load_hits_for_pair(pair)
        if not h:
            # No JPEG files found — skip silently
            pair_idx += 1
            continue
        hits     = h
        page_idx = 0
        # Pre-populate labels from any previous partial session for this pair
        labeled = {
            hit["prefix"]: prev_saved[hit["prefix"]]
            for hit in hits
            if hit["prefix"] in prev_saved
        }
        return True
    return False  # all pairs reviewed


def current_page_hits():
    start = page_idx * PAGE_SIZE
    return hits[start : start + PAGE_SIZE]


def total_pages():
    return max(1, (len(hits) + PAGE_SIZE - 1) // PAGE_SIZE)


def overall_progress():
    """
    Return (done_overall, total_all) for the progress bar.

    done_overall = number of rows in all_rows that appear before the current
    pair's position in the list. Every row before the current position has
    been passed: zero-hit rows implicitly, hit-bearing rows explicitly reviewed.
    Zero-hit rows that come AFTER the current position are not counted yet.
    """
    if pair_idx >= len(pairs):
        return len(all_rows), len(all_rows)
    return pair_all_indices[pair_idx], len(all_rows)

# ─── Startup ─────────────────────────────────────────────────────────────────

def init():
    global all_rows, pairs, pair_all_indices, pair_idx, prev_saved
    ensure_output_files()
    prev_saved = load_prev_saved()
    all_rows   = load_master()
    # pairs references the SAME dict objects as all_rows, so in-place edits propagate
    pairs            = [r for r in all_rows if int(float(r.get("hits", 0) or 0)) > 0]
    pair_all_indices = [i for i, r in enumerate(all_rows)
                        if int(float(r.get("hits", 0) or 0)) > 0]
    pair_idx = 0
    advance_pair()
    done_hit = sum(1 for p in pairs if p.get("review_status", "").strip().lower() == "done")
    print(f"Loaded {len(pairs)} pairs with hits. {done_hit} already reviewed.")

# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(GUI_DIR, "index.html")


@app.route("/image")
def serve_image():
    """Serve a JPEG by Windows path, with a root-prefix security check."""
    raw  = request.args.get("path", "")
    norm = os.path.normpath(raw)
    if not any(norm.startswith(root) for root in IMG_ROOTS):
        abort(403)
    if not os.path.isfile(norm):
        abort(404)
    return send_file(norm, mimetype="image/jpeg")


@app.route("/api/state")
def api_state():
    done_overall, total_all = overall_progress()
    if pair_idx >= len(pairs):
        return jsonify({"done": True, "done_overall": done_overall, "total_all": total_all})

    pair      = pairs[pair_idx]
    pair_path = pair["wholepath"]
    ph        = current_page_hits()

    hits_data = []
    for h in ph:
        before = os.path.join(pair_path, f"{h['prefix']}_before.jpg")
        after  = os.path.join(pair_path, f"{h['prefix']}_after.jpg")
        hits_data.append({
            "prefix":     h["prefix"],
            "ARE":        h["ARE"],
            "x":          h["x"],
            "y":          h["y"],
            "before_url": "/image?path=" + urllib.parse.quote(before, safe=""),
            "after_url":  "/image?path=" + urllib.parse.quote(after,  safe=""),
            "label":      labeled.get(h["prefix"], ""),
        })

    reg = pair.get("RegistrationScore", "")
    try:
        reg = f"{float(reg):.4f}"
    except (ValueError, TypeError):
        reg = str(reg)

    return jsonify({
        "done":            False,
        "pair_name":       os.path.basename(pair_path.rstrip("\\/")),
        # Label stat: completed hit-pairs / total hit-pairs
        "pair_idx":        pair_idx,           # number of hit-pairs completed so far
        "total_hit_pairs": len(pairs),
        # Progress bar: rows passed in full list / all rows
        "done_overall":    done_overall,
        "total_all":       total_all,
        "page":            page_idx,
        "total_pages":     total_pages(),
        "total_hits":      len(hits),
        "reg_score":       reg,
        "hits":            hits_data,
    })


@app.route("/api/label", methods=["POST"])
def api_label():
    """Set or clear the label for a single hit. Stored in memory until next-pair."""
    data   = request.get_json()
    prefix = (data.get("prefix") or "").strip()
    label  = (data.get("label")  or "").strip()

    if not prefix:
        return jsonify({"error": "missing prefix"}), 400
    if label == "":
        labeled.pop(prefix, None)
    elif label not in VALID_LABELS:
        return jsonify({"error": f"invalid label '{label}'"}), 400
    else:
        labeled[prefix] = label

    return jsonify({"ok": True})


@app.route("/api/next-page", methods=["POST"])
def api_next_page():
    """Advance one page within the current pair. If already on last page, finish the pair."""
    global page_idx
    if page_idx + 1 < total_pages():
        page_idx += 1
        return jsonify({"ok": True, "action": "page"})
    return _finish_pair()


@app.route("/api/next-pair", methods=["POST"])
def api_next_pair():
    return _finish_pair()


def _finish_pair():
    """Flush labels, mark pair done, advance to next."""
    global pair_idx, labeled, prev_saved

    if pair_idx >= len(pairs):
        return jsonify({"done": True})

    flush_labels_to_csv()
    prev_saved.update(labeled)
    labeled = {}

    pairs[pair_idx]["review_status"] = "done"
    save_master()  # all_rows shares dicts with pairs, so this captures the update

    pair_idx += 1
    still_going = advance_pair()
    return jsonify({"ok": True, "done": not still_going})


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init()
    print("Open http://localhost:5000 in your browser.")
    app.run(debug=False, host="127.0.0.1", port=5000)
