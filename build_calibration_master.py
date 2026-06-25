"""
Builds calibration_master.csv — the consolidated reference table for all 43
calibration impacts used to tune the fresh-crater detection pipeline.

Sources combined:
  - Coordinates from .tfw files (crater-centred CTX crops)
  - Daubar et al. 2013 Table 1 (crater diameters, CTX before/after IDs, HiRISE IDs)
  - CTX spatial query results (calibration_ctx_sources.csv)

OUTLIER NOTES (written to bottom of CSV as comment rows):
  Cal 28 (junk):  Our coords are -13.995 N, 250.787 E.  Daubar 2013 site 28 is at
    -15.346 N, 250.627 E — 1.36 deg away, far too large to be a coordinate-centre
    mismatch.  However, the Daubar before-image (B17_016305_1653) does appear in our
    CTX spatial query for cal 28, meaning both craters lie within the same CTX swath.
    The most likely explanation is that the calibration TIF was cropped around a
    *different* impact cluster that happens to share the same CTX pair as D13 site 28,
    or that a coordinate transcription error exists in one source.  Either way, the
    correct CTX pair to use is the one listed under D13 site 28 (B17_016305_1653 /
    B18_016727_1658) since that is the only published record for this region.

  Cal 41 (good):  Our coords are 35.907 N, 201.609 E.  The nearest Daubar 2013 entry
    is site 42 (35.318 N, 201.373 E, 0.635 deg away) — a cluster of small impacts
    imaged by G05_020091_2155 and G16_024482_2155.  D13 site 41 (11.840 N, 275.694 E)
    is entirely elsewhere and is NOT in our calibration set.  The 0.635 deg offset is
    larger than all other matches (<0.006 deg) but could reflect the CTX image being
    centred between two nearby impact clusters; both G16_024482 images are confirmed
    in our spatial query.  We tentatively assign cal 41 -> D13 site 42, flagged for
    manual verification.
"""

import csv, math, os

# ---------------------------------------------------------------------------
# Daubar 2013 data  (site, diameter_m, lat, lon_360E, bctx, bdate, actx, adate, hirise)
# ---------------------------------------------------------------------------
daubar2013 = [
    ( "1",  "4.9±0.04",   9.049, 259.507, "P09_004477_1906", "2007-07-11", "P13_006178_1907", "2007-11-20", "PSP_007246_1890"),
    ( "2",  "2.1±0.1",   25.604, 188.579, "P06_003451_2035", "2007-04-22", "P13_006286_2073", "2007-11-29", "PSP_006998_2060"),
    ( "3",  "14.7±0.1",  14.524, 268.850, "P03_002169_1937", "2007-01-12", "P14_006560_1936", "2007-12-20", "PSP_007272_1945"),
    ( "4",  "1.7±0.03",  -6.242, 273.984, "P03_002103_1721", "2007-01-07", "P15_006850_1741", "2008-01-12", "PSP_007496_1735"),
    ( "5",  "3.2±0.03",  -2.955, 287.823, "P02_001997_1744", "2006-12-30", "P18_007891_1742", "2008-04-02", "PSP_010528_1770"),
    ( "6",  "4.8±0.1",   15.650, 266.216, "P12_005558_1952", "2007-10-03", "P18_007984_1959", "2008-04-09", "PSP_010621_1960"),
    ( "7",  "6.4±0.03",  -1.928, 233.131, "P06_003344_1782", "2007-04-14", "P19_008539_1776", "2008-05-22", "PSP_010319_1780"),
    ("8b",  "8.0±0.4",   46.351, 176.891, "P20_008699_2247", "2008-06-04", "P22_009556_2263", "2008-08-10", "PSP_009978_2265"),
    ( "9",  "6.6±0.07",  -2.021, 246.574, "B01_009923_1790", "2008-09-07", "B01_010213_1790", "2008-09-30", "PSP_010635_1780"),
    ("10",  "6.0±0.02",  -6.019, 236.034, "P07_003845_1749", "2007-05-23", "B05_011743_1731", "2009-01-27", "ESP_016200_1740"),
    ("11",  "2.5±0.03",   2.910, 250.769, "P17_007510_1851", "2008-03-03", "B05_011782_1818", "2009-01-30", "ESP_012349_1830"),
    ("12",  "4.8±0.04",  11.476, 255.011, "P13_005954_1927", "2007-11-03", "B06_012006_1912", "2009-02-17", "ESP_013707_1915"),
    ("13",  "11.5±0.06",  5.543, 177.891, "P02_001790_1871", "2006-12-13", "B06_012022_1845", "2009-02-18", "ESP_017969_1855"),
    ("14",  "3.5±0.04",  10.599, 186.484, "P08_004150_1923", "2007-06-15", "B07_012259_1927", "2009-03-08", "ESP_016149_1905"),
    ("15",  "4.6±0.08",   4.431, 201.397, "P18_008171_1829", "2008-04-24", "B08_012931_1847", "2009-04-30", "ESP_013287_1845"),
    ("16",  "4.7±0.03",  -8.878, 217.642, "P03_002382_1705", "2007-01-29", "B09_013181_1733", "2009-05-19", "ESP_018561_1710"),
    ("17a", "33.8±0.09", -0.630, 248.913, "P03_002394_1809", "2007-01-29", "B09_013193_1810", "2009-05-20", "ESP_015949_1795"),
    ("18",  "6.4±0.03",  -6.848, 259.395, "P21_009250_1733", "2008-07-17", "B11_013786_1729", "2009-07-05", "ESP_016331_1730"),
    ("19",  "6.0±0.01",  -4.168, 246.709, "P09_004438_1763", "2007-07-08", "B11_014037_1761", "2009-07-25", "ESP_016582_1760"),
    ("20",  "8.6±0.02",   3.241, 235.100, "P13_006113_1819", "2007-11-15", "B16_015989_1834", "2009-12-24", "ESP_023426_1835"),
    ("21",  "3.1±0.09",   4.865, 279.362, "P17_007799_1860", "2008-03-26", "B17_016172_1863", "2010-01-07", "ESP_025943_1850"),
    ("22",  "3.6±0.02",  24.106, 279.799, "B02_010370_2044", "2008-10-12", "B17_016251_2044", "2010-01-13", "ESP_026589_2045"),
    ("23",  "5.6±0.02",  -0.965,  37.833, "P07_003694_1797", "2007-05-11", "B17_016260_1788", "2010-01-14", "ESP_017038_1790"),
    ("24",  "9.4±0.08",  30.494, 178.249, "P18_008119_2106", "2008-04-20", "B17_016347_2105", "2010-01-21", "ESP_017481_2110"),
    ("25",  "4.7±0.003", -2.566, 183.966, "B03_010901_1782", "2008-11-22", "B18_016492_1798", "2010-02-01", "ESP_018404_1775"),
    ("26",  "6.4±0.04",  24.921, 245.289, "P20_008868_2048", "2008-06-17", "B18_016516_2043", "2010-02-03", "ESP_018784_2050"),
    ("27",  "4.7±0.02",  30.791, 219.235, "P13_006153_2133", "2007-11-18", "B18_016662_2087", "2010-02-14", "ESP_017229_2110"),
    ("28",  "7.1±0.01", -15.346, 250.627, "B17_016305_1653", "2010-01-17", "B18_016727_1658", "2010-02-19", "ESP_018217_1645"),
    ("29",  "7.6±0.01",   7.493, 245.188, "P17_007497_1865", "2008-03-02", "B20_017360_1895", "2010-04-10", "ESP_017927_1875"),
    ("30",  "4.6±0.003", 12.331, 271.464, "P18_007997_1935", "2008-04-10", "B20_017570_1913", "2010-04-26", "ESP_018493_1925"),
    ("31",  "3.4±0.002", 40.341, 185.501, "B17_016439_2230", "2010-01-28", "B22_018140_2231", "2010-06-09", "ESP_018707_2205"),
    ("32",  "4.2±0.04",  46.611, 133.706, "B21_017654_2279", "2010-05-03", "G01_018577_2279", "2010-07-14", "ESP_018854_2270"),
    ("33",  "2.7±0.03",   3.117,  53.383, "B01_009930_1835", "2008-09-08", "G01_018712_1840", "2010-07-24", "ESP_022536_1830"),
    ("34",  "20±0.05",   41.017, 126.301, "B19_016995_2190", "2010-03-12", "G02_019052_2214", "2010-08-20", "ESP_019830_2215"),
    ("35",  "5.4±0.03",  18.935, 202.796, "B09_013076_1989", "2009-05-11", "G02_019168_1992", "2010-08-29", "ESP_020869_1990"),
    ("36",  "4.2±0.05",  32.249, 112.389, "B07_012288_2119", "2009-03-10", "G03_019580_2127", "2010-09-30", "ESP_020714_2125"),
    ("37",  "3.5±0.01",  12.270, 196.484, "B19_016953_1945", "2010-03-09", "G04_019788_1920", "2010-10-16", "ESP_022056_1925"),
    ("38",  "7.3±0.02",   4.472, 246.893, "G02_018995_1846", "2010-08-15", "G11_022608_1848", "2011-05-24", "ESP_022964_1845"),
    ("39",  "4.2±0.05",   3.702, 275.991, "B09_012981_1844", "2009-05-03", "G14_023886_1819", "2011-08-31", "ESP_025864_1835"),
    ("40",  "10.9±0.01", 24.582, 291.109, "P17_007693_2040", "2008-03-17", "G15_024215_2048", "2011-09-26", "ESP_028659_2050"),
    ("41",  "11.2±0.04", 11.840, 275.694, "B17_016093_1915", "2010-01-01", "G16_024482_2155", "2011-10-17", "ESP_026009_1920"),
    ("42",  "3.8±0.07",  35.318, 201.373, "G05_020091_2155", "2010-11-09", "G16_024482_2155", "2011-10-17", "ESP_026038_2155"),
    ("43",  "9.0±0.07",   3.290, 246.827, "B02_010424_1849", "2008-10-16", "G17_024942_1813", "2011-11-22", "ESP_027975_1835"),
    ("44",  "11.8±0.09",  2.579, 248.522, "B09_013193_1810", "2009-05-20", "G18_025087_1836", "2011-12-03", "ESP_026221_1825"),
]

# Build a lookup by (lat, lon) -> row
def lon_dist(a, b):
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d

def dist2d(lat1, lon1, lat2, lon2):
    return math.sqrt((lat1-lat2)**2 + lon_dist(lon1, lon2)**2)

# ---------------------------------------------------------------------------
# Calibration impacts
# ---------------------------------------------------------------------------
calibration = [
    ( 1, 259.508,  9.051, 'good'),
    ( 2, 188.579, 25.605, 'good'),
    ( 3, 268.849, 14.527, 'good'),
    ( 4, 273.985, -6.241, 'junk'),
    ( 5, 287.827, -2.952, 'junk'),
    ( 6, 266.216, 15.652, 'good'),
    ( 7, 233.131, -1.928, 'junk'),
    ( 8, 176.886, 46.354, 'good'),
    ( 9, 246.569, -2.020, 'good'),
    (10, 236.034, -6.018, 'faint'),
    (11, 250.767,  2.912, 'good'),
    (12, 255.011, 11.479, 'good'),
    (13, 177.892,  5.544, 'good'),
    (14, 186.484, 10.599, 'faint'),
    (15, 201.395,  4.431, 'good'),
    (16, 217.642, -8.879, 'junk'),
    (17, 248.912, -0.632, 'good'),
    (18, 259.395, -6.847, 'good'),
    (19, 246.710, -4.168, 'good'),
    (20, 235.098,  3.242, 'good'),
    (21, 279.364,  4.866, 'good'),
    (22, 279.799, 24.106, 'good'),
    (23,  37.832, -0.964, 'good'),
    (24, 178.252, 30.494, 'good'),
    (25, 183.965, -2.566, 'good'),
    (26, 245.290, 24.921, 'good'),
    (27, 219.235, 30.792, 'junk'),
    (28, 250.787,-13.995, 'junk'),
    (29, 245.189,  7.495, 'good'),
    (30, 271.465, 12.332, 'good'),
    (31, 185.502, 40.341, 'good'),
    (32, 133.705, 46.611, 'good'),
    (33,  53.382,  3.119, 'good'),
    (34, 126.305, 41.019, 'good'),
    (35, 202.796, 18.936, 'good'),
    (36, 112.394, 32.251, 'good'),
    (37, 196.488, 12.272, 'good'),
    (38, 246.894,  4.473, 'good'),
    (39, 275.991,  3.703, 'good'),
    (40, 291.109, 24.584, 'good'),
    (41, 201.609, 35.907, 'good'),
    (42, 246.831,  3.291, 'good'),
    (43, 248.523,  2.579, 'good'),
]

# ---------------------------------------------------------------------------
# Load CTX spatial query results (n_ctx per cal ID)
# ---------------------------------------------------------------------------
ctx_src_path = r'G:\crater_flux_output_folders\Impact_flux_project\calibration_ctx_sources.csv'
n_ctx_map = {}
if os.path.exists(ctx_src_path):
    with open(ctx_src_path) as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            iid = int(row['impact_id'])
            n_ctx_map[iid] = int(row['n_ctx']) if row['n_ctx'] else 0

# ---------------------------------------------------------------------------
# Match and build master rows
# ---------------------------------------------------------------------------
OUTLIER_NOTES = {
    28: ("OUTLIER", "Coords 1.36 deg from D13 site 28 (-15.346N 250.627E). "
         "D13 before-image (B17_016305_1653) found in CTX spatial query, so both lie "
         "in same CTX swath. Likely a different nearby cluster or coord transcription "
         "error. D13 site 28 CTX pair assigned as best available."),
    41: ("OUTLIER_TENTATIVE", "Nearest D13 site is 42 (35.318N 201.373E, 0.635 deg). "
         "No D13 site exists at cal 41 coords. D13-41 (11.840N 275.694E) is a "
         "completely different location. Tentatively assigned to D13 site 42; "
         "flag for manual verification."),
}

out_path = r'G:\crater_flux_output_folders\Impact_flux_project\calibration_master.csv'

fieldnames = [
    'cal_id', 'category',
    'lat', 'lon_180', 'lon_360',
    'daubar2013_site', 'match_dist_deg',
    'diameter_m',
    'ctx_before_id', 'ctx_before_date',
    'ctx_after_id',  'ctx_after_date',
    'hirise_id',
    'n_ctx_footprints_at_point',
    'outlier_flag', 'notes',
]

rows_out = []
MATCH_TOL = 0.5

for (cid, clon360, clat, ccat) in calibration:
    clon180 = clon360 if clon360 <= 180 else clon360 - 360

    # Find best Daubar 2013 match
    best = None
    best_d = 999.0
    for row in daubar2013:
        d = dist2d(clat, clon360, row[2], row[3])
        if d < best_d:
            best_d = d
            best = row

    if best_d <= MATCH_TOL:
        site, diam, dlat, dlon, bctx, bdate, actx, adate, hirise = best
        flag, note = OUTLIER_NOTES.get(cid, ('', ''))
    else:
        site, diam, bctx, bdate, actx, adate, hirise = ('', '', '', '', '', '', '')
        flag, note = OUTLIER_NOTES.get(cid, ('UNMATCHED', 'No Daubar 2013 match within 0.5 deg'))

    n_ctx = n_ctx_map.get(cid, '')

    rows_out.append({
        'cal_id':                   cid,
        'category':                 ccat,
        'lat':                      clat,
        'lon_180':                  round(clon180, 3),
        'lon_360':                  round(clon360, 3),
        'daubar2013_site':          site,
        'match_dist_deg':           round(best_d, 4) if site else '',
        'diameter_m':               diam,
        'ctx_before_id':            bctx,
        'ctx_before_date':          bdate,
        'ctx_after_id':             actx,
        'ctx_after_date':           adate,
        'hirise_id':                hirise,
        'n_ctx_footprints_at_point': n_ctx,
        'outlier_flag':             flag,
        'notes':                    note,
    })

with open(out_path, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(rows_out)

print(f"Written: {out_path}")
print(f"\nSummary:")
print(f"  Total calibration impacts : {len(rows_out)}")
print(f"  Matched to Daubar 2013    : {sum(1 for r in rows_out if r['daubar2013_site'] and not r['outlier_flag'])}")
print(f"  Matched (tentative/outlier): {sum(1 for r in rows_out if r['outlier_flag'] in ('OUTLIER','OUTLIER_TENTATIVE'))}")
print(f"  Unmatched                 : {sum(1 for r in rows_out if r['outlier_flag']=='UNMATCHED')}")
print(f"\nPer category:")
for cat in ('good','junk','faint'):
    print(f"  {cat:5}: {sum(1 for r in rows_out if r['category']==cat)}")
