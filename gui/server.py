#!/usr/bin/env python3
"""
Mars Impact Crater Validation GUI - Server
Run:  python server.py
Then: open http://localhost:5000
"""

import os
import csv
import urllib.parse
from datetime import datetime
from flask import Flask, jsonify, send_file, request, abort, send_from_directory

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

# Allowed path prefixes for image serving (security check)
IMG_ROOTS = [
    os.path.normpath(OUTPUT_DIR),
    os.path.normpath(os.path.dirname(MASTER_CSV)),
]

# ─── Flask app ───────────────────────────────────────────────────────────────

GUI_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=GUI_DIR, static_url_path="")

# ─── Global state ────────────────────────────────────────────────────────────

all_rows   = []  # complete list of dicts from master CSV (every row)
pairs      = []  # filtered subset: hits > 0 (same dict objects as in all_rows)
pair_idx   = 0   # current position in pairs[]
page_idx   = 0   # current page within the current pair's hits
hits       = []  # hits for current pair, sorted descending by ARE
labeled    = {}  # prefix -> label  (in-memory; flushed to disk on next-pair)
prev_saved = {}  # prefix -> label  (already written to output CSVs in prior sessions)

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


def done_pair_count():
    return sum(1 for p in pairs if p.get("review_status", "").strip().lower() == "done")

# ─── Startup ─────────────────────────────────────────────────────────────────

def init():
    global all_rows, pairs, pair_idx, prev_saved
    ensure_output_files()
    prev_saved = load_prev_saved()
    all_rows   = load_master()
    # pairs references the SAME dict objects as all_rows, so in-place edits propagate
    pairs      = [r for r in all_rows if int(float(r.get("hits", 0) or 0)) > 0]
    pair_idx   = 0
    advance_pair()
    print(f"Loaded {len(pairs)} pairs with hits. "
          f"{done_pair_count()} already reviewed.")

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
    n_done = done_pair_count()
    if pair_idx >= len(pairs):
        return jsonify({"done": True, "total_pairs": len(pairs), "done_pairs": n_done})

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
        "done":        False,
        "pair_name":   os.path.basename(pair_path.rstrip("\\/")),
        "pair_idx":    pair_idx,
        "total_pairs": len(pairs),
        "done_pairs":  n_done,
        "page":        page_idx,
        "total_pages": total_pages(),
        "total_hits":  len(hits),
        "reg_score":   reg,
        "hits":        hits_data,
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
