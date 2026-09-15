#!/usr/bin/env python3
"""
Summary statistics and figures for the Mars CTX fresh-crater survey.

Reads:
  pairsinfo_alldata_2006-2026.csv      — all processed pairs (±75° cleaned)
  pairsinfo_reviewed_2006-2026.csv     — pairs shown to reviewer
  confirmed_hits.csv / potential_hits.csv / interesting.csv
  mars_mro_ctx_edr_c0a_2026 / mars_mro_ctx_edr_c0a.dbf  — total CTX image count

Outputs (all to figures/):
  summary_stats.txt
  fig01_regiscore_cdf.png
  fig02_area_cdf.png
  fig03_hits_histogram.png
  fig04_swath_barchart.png
  fig05_map_pairs.png
  fig06_temporal_baseline_pdf.png
  fig07_acquisition_timeline.png
  fig08_score_vs_hits.png
"""

import os
import re
import struct
import warnings
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning)

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT    = r"G:\crater_flux_output_folders"
PROJ    = os.path.join(ROOT, "Impact_flux_project")
FIG_DIR = os.path.join(PROJ, "figures")
os.makedirs(FIG_DIR, exist_ok=True)

ALLDATA_CSV  = os.path.join(PROJ, "pairsinfo_alldata_2006-2026.csv")
REVIEWED_CSV = os.path.join(PROJ, "pairsinfo_reviewed_2006-2026.csv")
LABEL_CSVS   = {
    "confirmed":  os.path.join(ROOT, "confirmed_hits.csv"),
    "potential":  os.path.join(ROOT, "potential_hits.csv"),
    "interesting": os.path.join(ROOT, "interesting.csv"),
}
DBF_PATH = os.path.join(PROJ, "mars_mro_ctx_edr_c0a_2026",
                         "mars_mro_ctx_edr_c0a.dbf")

# Review thresholds (kept here as the single source of truth for the report)
THRESH_HITS      = 20     # hits <= this
THRESH_REG_SCORE = 0.25   # RegistrationScore >= this
# areakm2 > 0 (strict greater-than)

# ── Swath definitions (lon_min, lon_max) ──────────────────────────────────────

SWATH_LON_PAIRS = {
    (-115, -110): "115–100°W",
    (-110, -100): "115–100°W",
    (-60,  -50):  "60–50°W",
    (-180, -170): "180–170°W",
    (0,    10):   "0–10°E",
    (80,   90):   "80–90°E",
    (130,  140):  "130–140°E",
}
SWATH_NAMES = ["0–10°E", "80–90°E", "130–140°E",
               "180–170°W", "60–50°W", "115–100°W"]
SWATH_BOXES = {  # (lon_min, lon_max)
    "0–10°E":     (0,    10),
    "80–90°E":    (80,   90),
    "130–140°E":  (130, 140),
    "180–170°W":  (-180, -170),
    "60–50°W":    (-60,  -50),
    "115–100°W":  (-115, -100),
}

def get_swath(wholepath):
    """Assign a swath name from the output folder in the wholepath."""
    for part in wholepath.replace("\\", "/").split("/"):
        if part.startswith("output_"):
            nums = re.findall(r"-?\d+", part[7:])
            if len(nums) >= 2:
                key = (int(nums[0]), int(nums[1]))
                if key in SWATH_LON_PAIRS:
                    return SWATH_LON_PAIRS[key]
    return "unknown"

# ── Dark plot theme (matches calibration map) ─────────────────────────────────

BG      = "#1a1a2e"
FG      = "white"
GRID    = "#ffffff33"
C_ALL   = "#4fc3f7"   # all pairs — blue
C_REV   = "#69ff47"   # reviewed  — green
C_LINE  = "#ff6b6b"   # threshold lines — red

def dark_fig(figsize=(12, 6)):
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.tick_params(colors=FG, labelsize=9)
    for spine in ax.spines.values():
        spine.set_edgecolor("#555555")
    ax.xaxis.label.set_color(FG)
    ax.yaxis.label.set_color(FG)
    ax.title.set_color(FG)
    ax.grid(color=GRID, linewidth=0.5)
    return fig, ax

def save_fig(fig, name):
    path = os.path.join(FIG_DIR, name)
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  Saved: {name}")

# ── Load data ─────────────────────────────────────────────────────────────────

print("Loading data...")
alldata  = pd.read_csv(ALLDATA_CSV)
reviewed = pd.read_csv(REVIEWED_CSV)

alldata["areakm2"]          = pd.to_numeric(alldata["areakm2"],          errors="coerce")
alldata["hits"]             = pd.to_numeric(alldata["hits"],             errors="coerce")
alldata["RegistrationScore"]= pd.to_numeric(alldata["RegistrationScore"],errors="coerce")
alldata["centerlat"]        = pd.to_numeric(alldata["centerlat"],        errors="coerce")
alldata["centerlon"]        = pd.to_numeric(alldata["centerlon"],        errors="coerce")

reviewed["areakm2"]          = pd.to_numeric(reviewed["areakm2"],          errors="coerce")
reviewed["hits"]             = pd.to_numeric(reviewed["hits"],             errors="coerce")
reviewed["RegistrationScore"]= pd.to_numeric(reviewed["RegistrationScore"],errors="coerce")
reviewed["days_between"]     = pd.to_numeric(reviewed["days_between"],     errors="coerce")
reviewed["datetime1"]        = pd.to_datetime(reviewed["datetime1"],       errors="coerce")

# Assign swaths
alldata["swath"]  = alldata["wholepath"].apply(get_swath)
reviewed["swath"] = reviewed["wholepath"].apply(get_swath)

# Load flagged hit CSVs
flagged = {}
for label, path in LABEL_CSVS.items():
    if os.path.exists(path):
        df = pd.read_csv(path)
        flagged[label] = df
        print(f"  {label}: {len(df):,} hits")
    else:
        flagged[label] = pd.DataFrame()
        print(f"  {label}: not found")

# Total CTX images from DBF header (fast — no need to read all records)
n_ctx_images = 0
if os.path.exists(DBF_PATH):
    with open(DBF_PATH, "rb") as f:
        hdr = f.read(32)
    n_ctx_images = struct.unpack_from("<I", hdr, 4)[0]

print(f"  alldata: {len(alldata):,} pairs")
print(f"  reviewed: {len(reviewed):,} pairs")
print(f"  CTX images in 2026 shapefile: {n_ctx_images:,}")

# ── Compute statistics ────────────────────────────────────────────────────────

print("\nComputing statistics...")

# Filters applied to build reviewed set
n_all          = len(alldata)
n_rev          = len(reviewed)
pct_rev        = 100 * n_rev / n_all if n_all else 0

# Minimum areakm2 in reviewed (to close the "was there a sliver filter?" question)
min_area_rev   = reviewed["areakm2"].min()

# Pairs excluded by each filter (from alldata + the pre-filtered pool)
# Reconstruct the original unfiltered pool for filter accounting:
# alldata is already ±75° cleaned. Add back the excluded columns from original.
# We approximate using what's in alldata (which includes all hits, scores, areas).
# Note: alldata already had ±75° pairs removed.
n_zero_hits    = (alldata["hits"]             == 0  ).sum()
n_high_hits    = (alldata["hits"]             >  THRESH_HITS).sum()
n_low_score    = (alldata["RegistrationScore"]<  THRESH_REG_SCORE).sum()
n_zero_area    = (alldata["areakm2"]          <= 0  ).sum()

# Pairs per swath
swath_stats = {}
for s in SWATH_NAMES:
    a = (alldata["swath"]  == s).sum()
    r = (reviewed["swath"] == s).sum()
    swath_stats[s] = (a, r)

# Total surveyed area
total_area_all = alldata["areakm2"].sum()
total_area_rev = reviewed["areakm2"].sum()

# Review outcome breakdown (among pairs with hits > 0 in reviewed set)
rev_with_hits = reviewed[reviewed["hits"] > 0]
n_rev_hits_total  = len(rev_with_hits)
n_done            = (rev_with_hits["review_status"] == "done").sum()
n_black_filtered  = (rev_with_hits["review_status"] != "done").sum()
n_zero_hit_rev    = (reviewed["hits"] == 0).sum()

# Flagged hits
n_confirmed   = len(flagged.get("confirmed",   pd.DataFrame()))
n_potential   = len(flagged.get("potential",   pd.DataFrame()))
n_interesting = len(flagged.get("interesting", pd.DataFrame()))
n_flagged_total = n_confirmed + n_potential + n_interesting

# Total hits the reviewer could have seen (sum of hits for 'done' pairs)
done_pairs       = reviewed[reviewed["review_status"] == "done"]
hits_in_done     = int(done_pairs["hits"].sum())

# Temporal baseline
days = reviewed["days_between"].dropna()
dt1  = reviewed["datetime1"].dropna()

# ── Write text summary ────────────────────────────────────────────────────────

lines = []
def p(s=""): lines.append(s)

p("=" * 70)
p("MARS CTX FRESH-CRATER SURVEY — SUMMARY STATISTICS")
p("=" * 70)
p()
p("DATA COVERAGE")
p("-" * 40)
p(f"  Total CTX images in 2026 shapefile:     {n_ctx_images:>10,}")
p(f"  Total processed pairs (all data):       {n_all:>10,}")
p(f"  Pairs shown to reviewer:                {n_rev:>10,}  ({pct_rev:.1f}% of all)")
p()
p("REVIEW THRESHOLDS (applied to build reviewed set)")
p("-" * 40)
p(f"  hits          <= {THRESH_HITS}   (strictly: hits <= {THRESH_HITS})")
p(f"  RegistrationScore >= {THRESH_REG_SCORE}")
p(f"  areakm2        > 0   (strictly: areakm2 > 0)")
p(f"  Minimum areakm2 in reviewed set:        {min_area_rev:.4f} km²")
p()
p("PAIRS EXCLUDED FROM REVIEW (may overlap)")
p("-" * 40)
p(f"  Zero hits (hits == 0):                  {n_zero_hits:>10,}")
p(f"  High hit count (hits > {THRESH_HITS}):           {n_high_hits:>10,}")
p(f"  Low reg score (score < {THRESH_REG_SCORE}):         {n_low_score:>10,}")
p(f"  Zero area (areakm2 <= 0):               {n_zero_area:>10,}")
p()
p("SURVEYED AREA")
p("-" * 40)
p(f"  Total area of all processed pairs:      {total_area_all:>12,.1f} km²")
p(f"  Total area of reviewed pairs:           {total_area_rev:>12,.1f} km²")
p()
p("PAIRS PER SWATH")
p("-" * 40)
p(f"  {'Swath':<14} {'All':>10} {'Reviewed':>10} {'% Reviewed':>12}")
p(f"  {'-'*46}")
for s in SWATH_NAMES:
    a, r = swath_stats[s]
    pct = 100 * r / a if a else 0
    p(f"  {s:<14} {a:>10,} {r:>10,} {pct:>11.1f}%")
p()
p("REVIEW OUTCOMES (pairs with hits > 0 in reviewed set)")
p("-" * 40)
p(f"  Pairs with hits > 0:                    {n_rev_hits_total:>10,}")
p(f"    Marked done (shown to reviewer):      {n_done:>10,}")
p(f"    Black-edge filtered (never shown):    {n_black_filtered:>10,}")
p(f"  Zero-hit pairs (skipped):               {n_zero_hit_rev:>10,}")
p()
p(f"  Total hits in 'done' pairs:             {hits_in_done:>10,}")
p(f"    Flagged confirmed:                    {n_confirmed:>10,}")
p(f"    Flagged potential:                    {n_potential:>10,}")
p(f"    Flagged interesting:                  {n_interesting:>10,}")
p(f"    Total flagged:                        {n_flagged_total:>10,}")
p()
p("TEMPORAL BASELINE (days between image pairs, reviewed set)")
p("-" * 40)
if len(days) > 0:
    p(f"  Pairs with timestamp data:              {len(days):>10,}")
    p(f"  Min:     {days.min():.1f} days  ({days.min()/365.25:.1f} yr)")
    p(f"  Max:     {days.max():.1f} days  ({days.max()/365.25:.1f} yr)")
    p(f"  Median:  {days.median():.1f} days  ({days.median()/365.25:.1f} yr)")
    p(f"  Mean:    {days.mean():.1f} days  ({days.mean()/365.25:.1f} yr)")
p()
p("=" * 70)

summary_text = "\n".join(lines)
print(summary_text)

txt_path = os.path.join(FIG_DIR, "summary_stats.txt")
with open(txt_path, "w", encoding="utf-8") as f:
    f.write(summary_text)
print(f"\n  Saved: summary_stats.txt")

# ── Figure 1: CDF of RegistrationScore ───────────────────────────────────────

print("\nGenerating figures...")
scores = alldata["RegistrationScore"].dropna().sort_values()
cdf_y  = np.arange(1, len(scores) + 1) / len(scores)

fig, ax = dark_fig((10, 5))
ax.plot(scores, cdf_y, color=C_ALL, lw=1.5, label=f"All pairs (n={len(scores):,})")
ax.axvline(THRESH_REG_SCORE, color=C_LINE, lw=1.5, ls="--",
           label=f"Review threshold ({THRESH_REG_SCORE})")
pct_below = 100 * (scores < THRESH_REG_SCORE).sum() / len(scores)
ax.text(THRESH_REG_SCORE + 0.01, 0.15,
        f"{pct_below:.1f}% below\nthreshold",
        color=C_LINE, fontsize=8)
ax.set_xlabel("Registration Score")
ax.set_ylabel("Cumulative fraction of pairs")
ax.set_title("CDF of Registration Score — All Processed Pairs", color=FG)
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
leg = ax.legend(facecolor="#111111", edgecolor="#555555", labelcolor=FG, fontsize=9)
save_fig(fig, "fig01_regiscore_cdf.png")

# ── Figure 2: CDF of areakm2 ─────────────────────────────────────────────────

all_areas = alldata["areakm2"].dropna()
rev_areas = reviewed["areakm2"].dropna()
all_areas_s = np.sort(all_areas)
rev_areas_s = np.sort(rev_areas)

fig, ax = dark_fig((10, 5))
ax.plot(all_areas_s, np.linspace(0, 1, len(all_areas_s)),
        color=C_ALL, lw=1.5, label=f"All pairs (n={len(all_areas_s):,})")
ax.plot(rev_areas_s, np.linspace(0, 1, len(rev_areas_s)),
        color=C_REV, lw=1.5, label=f"Reviewed pairs (n={len(rev_areas_s):,})")
ax.set_xscale("log")
ax.set_xlabel("Pair overlap area (km²)")
ax.set_ylabel("Cumulative fraction of pairs")
ax.set_title("CDF of Pair Overlap Area", color=FG)
ax.set_ylim(0, 1)
leg = ax.legend(facecolor="#111111", edgecolor="#555555", labelcolor=FG, fontsize=9)
save_fig(fig, "fig02_area_cdf.png")

# ── Figure 3: Histogram of hits per pair ─────────────────────────────────────

all_hits = alldata["hits"].dropna().astype(int)
max_hit  = int(all_hits.max())
bins     = np.arange(0, max_hit + 2) - 0.5

fig, ax = dark_fig((12, 5))
counts, edges, _ = ax.hist(all_hits, bins=bins, color=C_ALL, alpha=0.7,
                            log=True, label="All pairs")
# Shade the ≤20 region
ax.axvspan(-0.5, THRESH_HITS + 0.5, alpha=0.12, color=C_REV, zorder=0,
           label=f"Reviewed range (hits ≤ {THRESH_HITS})")
ax.axvline(THRESH_HITS + 0.5, color=C_LINE, lw=1.5, ls="--",
           label=f"Review cutoff (hits > {THRESH_HITS})")
ax.set_xlabel("Number of hits per pair")
ax.set_ylabel("Number of pairs (log scale)")
ax.set_title("Distribution of Hits per Pair", color=FG)
ax.set_xlim(-1, min(max_hit + 1, 200))
leg = ax.legend(facecolor="#111111", edgecolor="#555555", labelcolor=FG, fontsize=9)
save_fig(fig, "fig03_hits_histogram.png")

# ── Figure 4: Bar chart — pairs per swath ────────────────────────────────────

names  = SWATH_NAMES
totals = [swath_stats[s][0] for s in names]
revs   = [swath_stats[s][1] for s in names]
x      = np.arange(len(names))
w      = 0.38

fig, ax = dark_fig((11, 5))
ax.bar(x - w/2, totals, w, color=C_ALL,  alpha=0.85, label="All pairs")
ax.bar(x + w/2, revs,   w, color=C_REV,  alpha=0.85, label="Reviewed pairs")
for xi, (t, r) in zip(x, zip(totals, revs)):
    ax.text(xi - w/2, t + max(totals)*0.01, f"{t:,}",
            ha="center", va="bottom", color=FG, fontsize=7)
    ax.text(xi + w/2, r + max(totals)*0.01, f"{r:,}",
            ha="center", va="bottom", color=FG, fontsize=7)
ax.set_xticks(x)
ax.set_xticklabels(names, color=FG, fontsize=9)
ax.set_ylabel("Number of pairs")
ax.set_title("Pairs per Study Swath", color=FG)
leg = ax.legend(facecolor="#111111", edgecolor="#555555", labelcolor=FG, fontsize=9)
save_fig(fig, "fig04_swath_barchart.png")

# ── Figure 5: Map of pair distribution ───────────────────────────────────────

rev_ids = set(reviewed["wholepath"])
not_reviewed = alldata[~alldata["wholepath"].isin(rev_ids)]

fig, ax = plt.subplots(figsize=(18, 9))
fig.patch.set_facecolor(BG)
ax.set_facecolor("#2d1b0e")

# Graticule
for lon_g in range(-180, 181, 30):
    ax.axvline(lon_g, color="white", lw=0.3, alpha=0.2)
for lat_g in range(-90, 91, 30):
    ax.axhline(lat_g, color="white", lw=0.3, alpha=0.2)

# ±75° lat boundary
ax.axhline(75,  color=C_LINE, lw=1.0, ls=":", alpha=0.7, label="±75° lat limit")
ax.axhline(-75, color=C_LINE, lw=1.0, ls=":", alpha=0.7)

# Study-area swaths
swath_color = "#4fc3f7"
for sname, (lon_min, lon_max) in SWATH_BOXES.items():
    w = lon_max - lon_min
    for alpha, fc in [(0.13, swath_color), (0, "none")]:
        rect = mpatches.FancyBboxPatch(
            (lon_min, -75), w, 150,
            boxstyle="square,pad=0",
            linewidth=1.2, edgecolor=swath_color,
            facecolor=fc if fc == "none" else swath_color,
            alpha=alpha, zorder=2)
        ax.add_patch(rect)

# Scatter: not-reviewed (faint), reviewed (bright)
sample_nr = not_reviewed.sample(min(len(not_reviewed), 80_000), random_state=42)
ax.scatter(sample_nr["centerlon"], sample_nr["centerlat"],
           s=0.3, color=C_ALL, alpha=0.25, linewidths=0, zorder=3,
           label=f"Not reviewed (sample, n={len(not_reviewed):,})")
ax.scatter(reviewed["centerlon"], reviewed["centerlat"],
           s=0.8, color=C_REV, alpha=0.5, linewidths=0, zorder=4,
           label=f"Reviewed (n={len(reviewed):,})")

ax.set_xlim(-180, 180)
ax.set_ylim(-90, 90)
ax.set_xlabel("Longitude (°E)", color=FG, fontsize=11)
ax.set_ylabel("Latitude (°N)", color=FG, fontsize=11)
ax.set_title("CTX Image Pair Distribution — All Processed & Reviewed Pairs",
             color=FG, fontsize=13, fontweight="bold", pad=10)
ax.tick_params(colors=FG, labelsize=8)
for spine in ax.spines.values():
    spine.set_edgecolor("#555555")

lon_ticks = list(range(-180, 181, 30))
ax.set_xticks(lon_ticks)
ax.set_xticklabels([f"{abs(x)}°{'W' if x<0 else ('E' if x>0 else '')}"
                    for x in lon_ticks], color=FG, fontsize=8)
ax.set_yticks(range(-90, 91, 30))
ax.set_yticklabels([f"{abs(y)}°{'S' if y<0 else ('N' if y>0 else '')}"
                    for y in range(-90, 91, 30)], color=FG, fontsize=8)

legend_els = [
    mpatches.Patch(facecolor=C_ALL, alpha=0.5, label=f"Not reviewed (n={len(not_reviewed):,})"),
    mpatches.Patch(facecolor=C_REV, alpha=0.8, label=f"Reviewed (n={len(reviewed):,})"),
    mpatches.Patch(facecolor=swath_color, alpha=0.3,
                   edgecolor=swath_color, label="Study-area swath"),
]
from matplotlib.lines import Line2D
legend_els.append(Line2D([0],[0], color=C_LINE, ls=":", lw=1, label="±75° lat limit"))
leg = ax.legend(handles=legend_els, loc="lower left", framealpha=0.4,
                facecolor="#111111", edgecolor="#555555", labelcolor=FG, fontsize=9)
save_fig(fig, "fig05_map_pairs.png")

# ── Figure 6: PDF (histogram) of days_between ────────────────────────────────

if len(days) > 10:
    fig, ax = dark_fig((10, 5))
    max_days = days.max()
    bins6 = np.arange(0, max_days + 200, 200)
    ax.hist(days, bins=bins6, color=C_REV, alpha=0.8, edgecolor="none")
    ax.axvline(days.median(), color=C_LINE, lw=1.5, ls="--",
               label=f"Median: {days.median():.0f} days ({days.median()/365.25:.1f} yr)")
    ax.set_xlabel("Days between image acquisitions")
    ax.set_ylabel("Number of reviewed pairs")
    ax.set_title("Distribution of Temporal Baseline — Reviewed Pairs", color=FG)
    leg = ax.legend(facecolor="#111111", edgecolor="#555555", labelcolor=FG, fontsize=9)
    # Secondary x-axis in years
    ax2 = ax.twiny()
    ax2.set_xlim(ax.get_xlim()[0]/365.25, ax.get_xlim()[1]/365.25)
    ax2.set_xlabel("Years between acquisitions", color=FG)
    ax2.tick_params(colors=FG, labelsize=8)
    save_fig(fig, "fig06_temporal_baseline_pdf.png")

# ── Figure 7: Acquisition timeline ───────────────────────────────────────────

if len(dt1) > 10:
    years = dt1.dt.year.dropna()
    fig, ax = dark_fig((12, 5))
    year_bins = np.arange(years.min(), years.max() + 2) - 0.5
    ax.hist(years, bins=year_bins, color=C_ALL, alpha=0.8, edgecolor="none",
            label="Pairs by earlier image date")
    ax.set_xlabel("Year of earlier image in pair")
    ax.set_ylabel("Number of reviewed pairs")
    ax.set_title("Temporal Distribution of Reviewed Image Pairs (by earlier image date)",
                 color=FG)
    ax.set_xticks(range(int(years.min()), int(years.max()) + 1))
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", color=FG, fontsize=8)
    leg = ax.legend(facecolor="#111111", edgecolor="#555555", labelcolor=FG, fontsize=9)
    save_fig(fig, "fig07_acquisition_timeline.png")

# ── Figure 8: RegistrationScore vs hits (scatter) ────────────────────────────

# Sample alldata to keep plot manageable (up to 100k points)
sample_all = alldata[["RegistrationScore", "hits"]].dropna()
sample_all = sample_all.sample(min(len(sample_all), 100_000), random_state=42)
rev_scatter = reviewed[["RegistrationScore", "hits"]].dropna()

fig, axes = plt.subplots(1, 2, figsize=(16, 6), sharey=True, sharex=True)
fig.patch.set_facecolor(BG)
for ax in axes:
    ax.set_facecolor(BG)
    ax.tick_params(colors=FG, labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor("#555555")
    ax.grid(color=GRID, linewidth=0.5)
    ax.axvline(THRESH_REG_SCORE, color=C_LINE, lw=1.2, ls="--", alpha=0.8)

axes[0].scatter(sample_all["RegistrationScore"], sample_all["hits"],
                s=1.5, color=C_ALL, alpha=0.3, linewidths=0)
axes[0].set_title(f"All pairs (sample n={len(sample_all):,})", color=FG)
axes[0].set_xlabel("Registration Score", color=FG)
axes[0].set_ylabel("Hits per pair", color=FG)

axes[1].scatter(rev_scatter["RegistrationScore"], rev_scatter["hits"],
                s=2, color=C_REV, alpha=0.4, linewidths=0)
axes[1].set_title(f"Reviewed pairs (n={len(rev_scatter):,})", color=FG)
axes[1].set_xlabel("Registration Score", color=FG)

fig.suptitle("Registration Score vs. Hits per Pair",
             color=FG, fontsize=13, fontweight="bold", y=1.01)
plt.tight_layout()
save_fig(fig, "fig08_score_vs_hits.png")

print("\nAll done.")
