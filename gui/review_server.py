#!/usr/bin/env python3
"""
Mars Impact Crater Review GUI — Phase 2 Server
For reviewing flagged hits and adding comments.
Run:  python review_server.py
Then: open http://localhost:5001

Prerequisite: run crop_generator.py first to generate 200px crops and lat/lon.
"""

import os
import csv
import json
import urllib.parse
from flask import Flask, jsonify, send_file, request, abort, send_from_directory

# ─── Config ──────────────────────────────────────────────────────────────────

OUTPUT_DIR = r"G:\crater_flux_output_folders"

INPUT_FILES = {
    "confirmed_hit": os.path.join(OUTPUT_DIR, "confirmed_hits.csv"),
    "potential_hit":  os.path.join(OUTPUT_DIR, "potential_hits.csv"),
    "interesting":    os.path.join(OUTPUT_DIR, "interesting.csv"),
}

LABEL_ORDER    = {"confirmed_hit": 0, "potential_hit": 1, "interesting": 2}
PAGE_SIZE      = 12   # 3 columns × 4 rows
IMG_ROOT       = os.path.normpath(OUTPUT_DIR)
PROGRESS_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review_progress.json")

# ─── Flask ───────────────────────────────────────────────────────────────────

GUI_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=GUI_DIR, static_url_path="")

# ─── State ───────────────────────────────────────────────────────────────────

all_hits = []   # combined ordered list of hit dicts (same objects as in CSV rows)
page_idx = 0

# ─── Progress persistence ────────────────────────────────────────────────────

def load_progress():
    """Load saved page position from disk, default to 0."""
    global page_idx
    try:
        with open(PROGRESS_FILE) as f:
            page_idx = int(json.load(f).get("page_idx", 0))
        print(f"Resuming at page {page_idx + 1}.")
    except (FileNotFoundError, ValueError, KeyError):
        page_idx = 0


def save_progress():
    """Write current page position to disk."""
    with open(PROGRESS_FILE, "w") as f:
        json.dump({"page_idx": page_idx}, f)

# ─── CSV I/O ─────────────────────────────────────────────────────────────────

def load_hits():
    global all_hits
    result = []
    for label, path in INPUT_FILES.items():
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                row.setdefault("lat",      "")
                row.setdefault("lon",      "")
                row.setdefault("comments", "")
                result.append(row)

    # confirmed first → potential → interesting, preserve CSV order within each group
    result.sort(key=lambda r: LABEL_ORDER.get(r.get("label", ""), 99))
    all_hits = result
    print(f"Loaded {len(all_hits)} flagged hits  "
          f"({sum(1 for h in all_hits if h['label']=='confirmed_hit')} confirmed, "
          f"{sum(1 for h in all_hits if h['label']=='potential_hit')} potential, "
          f"{sum(1 for h in all_hits if h['label']=='interesting')} interesting)")


def save_label_csv(label):
    """Rewrite the CSV for a given label with current in-memory state."""
    path = INPUT_FILES.get(label)
    if not path:
        return
    rows = [h for h in all_hits if h.get("label") == label]
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

# ─── Helpers ─────────────────────────────────────────────────────────────────

def page_hits():
    start = page_idx * PAGE_SIZE
    return all_hits[start : start + PAGE_SIZE]


def total_pages():
    return max(1, (len(all_hits) + PAGE_SIZE - 1) // PAGE_SIZE)


def image_urls(hit):
    pair_path  = hit["wholepath"]
    prefix     = hit["hit_prefix"]
    before_200 = os.path.join(pair_path, f"{prefix}_before_200.jpg")
    after_200  = os.path.join(pair_path, f"{prefix}_after_200.jpg")
    before_100 = os.path.join(pair_path, f"{prefix}_before.jpg")
    after_100  = os.path.join(pair_path, f"{prefix}_after.jpg")
    # Prefer 200px; fall back to 100px if generator hasn't run yet
    before = before_200 if os.path.isfile(before_200) else before_100
    after  = after_200  if os.path.isfile(after_200)  else after_100
    return (
        "/image?path=" + urllib.parse.quote(before, safe=""),
        "/image?path=" + urllib.parse.quote(after,  safe=""),
    )

# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(GUI_DIR, "review.html")


@app.route("/image")
def serve_image():
    raw  = request.args.get("path", "")
    norm = os.path.normpath(raw)
    if not norm.startswith(IMG_ROOT):
        abort(403)
    if not os.path.isfile(norm):
        abort(404)
    return send_file(norm, mimetype="image/jpeg")


@app.route("/api/state")
def api_state():
    ph = page_hits()
    hits_data = []
    for h in ph:
        before_url, after_url = image_urls(h)

        # Format lat/lon for display
        try:
            lat_str = f"{float(h['lat']):.4f}°"
            lon_str = f"{float(h['lon']):.4f}°"
        except (ValueError, TypeError):
            lat_str = lon_str = "—"

        hits_data.append({
            "hit_prefix": h["hit_prefix"],
            "label":      h.get("label", ""),
            "pair_name":  h.get("pair_name", ""),
            "ARE":        h.get("ARE", ""),
            "lat":        lat_str,
            "lon":        lon_str,
            "comments":   h.get("comments", ""),
            "before_url": before_url,
            "after_url":  after_url,
        })

    # Per-label totals and how many have been paged past (on completed pages)
    seen_cutoff = page_idx * PAGE_SIZE
    label_stats = {}
    for lbl in LABEL_ORDER:
        total = sum(1 for h in all_hits if h.get("label") == lbl)
        seen  = sum(1 for i, h in enumerate(all_hits)
                    if h.get("label") == lbl and i < seen_cutoff)
        label_stats[lbl] = {"seen": seen, "total": total}

    return jsonify({
        "page":         page_idx,
        "total_pages":  total_pages(),
        "total_hits":   len(all_hits),
        "label_stats":  label_stats,
        "hits":         hits_data,
    })


@app.route("/api/comment", methods=["POST"])
def api_comment():
    data    = request.get_json()
    prefix  = (data.get("hit_prefix") or "").strip()
    comment = data.get("comment", "")

    for h in all_hits:
        if h["hit_prefix"] == prefix:
            h["comments"] = comment
            save_label_csv(h.get("label", ""))
            return jsonify({"ok": True})

    return jsonify({"error": "hit not found"}), 404


@app.route("/api/navigate", methods=["POST"])
def api_navigate():
    global page_idx
    direction = (request.get_json() or {}).get("direction", "")
    if direction == "next" and page_idx + 1 < total_pages():
        page_idx += 1
    elif direction == "prev" and page_idx > 0:
        page_idx -= 1
    save_progress()
    return jsonify({"ok": True, "page": page_idx})


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    load_hits()
    load_progress()
    # Clamp in case total hits changed since last session
    page_idx = min(page_idx, total_pages() - 1)
    print("Open http://localhost:5001 in your browser.")
    app.run(debug=False, host="127.0.0.1", port=5001)
