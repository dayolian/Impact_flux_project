#!/usr/bin/env python3
"""
Add datetime1, datetime2, days_between columns to pairsinfo_combo_master_max20hits.csv
by looking up each CTX image ID in the mars_mro_ctx_edr_c0a shapefile.

Run with the GUI server stopped (script rewrites the master CSV).
"""

import os
import csv
import struct
from datetime import datetime

# ─── Config ──────────────────────────────────────────────────────────────────

MASTER_CSV = r"G:\crater_flux_output_folders\Impact_flux_project\pairsinfo_combo_master_max20hits.csv"
DBF_PATH   = r"G:\crater_flux_output_folders\Impact_flux_project\mars_mro_ctx_edr_c0a.dbf"

# ─── DBF reader ──────────────────────────────────────────────────────────────

def load_dbf_lookup(dbf_path):
    """
    Read the CTX shapefile DBF and return a dict: ProductId -> UTCstart string.
    Uses only Python stdlib (struct) — no geopandas/fiona needed.
    """
    with open(dbf_path, "rb") as f:
        header      = f.read(32)
        num_records = struct.unpack_from("<I", header, 4)[0]
        header_size = struct.unpack_from("<H", header, 8)[0]
        record_size = struct.unpack_from("<H", header, 10)[0]

        # Parse field descriptors (32 bytes each, terminated by 0x0D)
        fields = []
        while True:
            fd = f.read(32)
            if fd[0] == 0x0D:
                break
            name   = fd[:11].rstrip(b"\x00").decode("ascii")
            length = fd[16]
            fields.append((name, length))

        # Byte offsets within each record (byte 0 = deletion flag)
        field_offsets = {}
        byte_pos = 1
        for name, length in fields:
            field_offsets[name] = (byte_pos, length)
            byte_pos += length

        pid_off, pid_len = field_offsets["ProductId"]
        utc_off, utc_len = field_offsets["UTCstart"]

        # Read all records into lookup dict
        f.seek(header_size)
        lookup = {}
        for _ in range(num_records):
            rec = f.read(record_size)
            if rec[0] == 0x2A:      # 0x2A = '*' marks a deleted record
                continue
            product_id = rec[pid_off : pid_off + pid_len].strip().decode("ascii", errors="ignore")
            utc_start  = rec[utc_off : utc_off + utc_len].strip().decode("ascii", errors="ignore")
            if product_id:
                lookup[product_id] = utc_start

    print(f"  Loaded {len(lookup):,} ProductId entries from DBF.")
    return lookup

# ─── Helpers ─────────────────────────────────────────────────────────────────

def split_ctx_pair(ctx_id):
    """
    Split a concatenated pair ctxID into its two component product IDs.
    Each CTX product ID has exactly 5 underscore-separated parts, so the
    concatenated pair has exactly 10 parts.
    Returns (id1, id2) or (None, None) if the format is unexpected.
    """
    parts = ctx_id.strip().split("_")
    if len(parts) != 10:
        return None, None
    return "_".join(parts[:5]), "_".join(parts[5:])


def parse_utc(s):
    """Parse ISO timestamp '2006-03-24T04:28:07.724' → datetime, or None."""
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Step 1: Loading shapefile lookup table...")
    lookup = load_dbf_lookup(DBF_PATH)

    print("\nStep 2: Reading master CSV...")
    with open(MASTER_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"  {len(rows):,} rows loaded.")

    print("\nStep 3: Matching image IDs and computing time gaps...")
    missing_ids  = set()
    n_complete   = 0
    n_partial    = 0
    n_bad_format = 0

    for row in rows:
        ctx_id   = row.get("ctxID", "").strip()
        id1, id2 = split_ctx_pair(ctx_id)

        if id1 is None:
            row["datetime1"]    = ""
            row["datetime2"]    = ""
            row["days_between"] = ""
            print(f"  WARNING: unexpected ctxID format: {repr(ctx_id)}")
            n_bad_format += 1
            continue

        utc1 = lookup.get(id1, "")
        utc2 = lookup.get(id2, "")

        if not utc1:
            missing_ids.add(id1)
        if not utc2:
            missing_ids.add(id2)

        dt1 = parse_utc(utc1)
        dt2 = parse_utc(utc2)

        row["datetime1"] = utc1
        row["datetime2"] = utc2

        if dt1 and dt2:
            days = abs((dt2 - dt1).total_seconds()) / 86400.0
            row["days_between"] = f"{days:.4f}"
            n_complete += 1
        else:
            row["days_between"] = ""
            n_partial += 1

    # Report missing IDs
    if missing_ids:
        print(f"\n  WARNING: {len(missing_ids)} image IDs not found in shapefile "
              f"(rows will have blank timestamps):")
        for mid in sorted(missing_ids)[:20]:
            print(f"    {mid}")
        if len(missing_ids) > 20:
            print(f"    ... and {len(missing_ids) - 20} more")

    print(f"\n  Complete (both timestamps found) : {n_complete:,}")
    print(f"  Partial  (one or both missing)   : {n_partial:,}")
    print(f"  Bad format (ctxID unparseable)   : {n_bad_format:,}")

    print("\nStep 4: Writing updated CSV...")
    fieldnames = list(rows[0].keys())
    # Ensure new columns are present even if they were already there
    for col in ("datetime1", "datetime2", "days_between"):
        if col not in fieldnames:
            fieldnames.append(col)

    with open(MASTER_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Saved: {MASTER_CSV}")
    print("\nDone.")


if __name__ == "__main__":
    main()
