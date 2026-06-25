import pandas as pd, math, warnings
warnings.filterwarnings('ignore')

df = pd.read_csv(
    r'G:\crater_flux_output_folders\Impact_flux_project\daubar2022_annotated.csv',
    parse_dates=['after_date']
)
cutoff = pd.Timestamp('2018-01-01')
pre = df[df['in_any_swath'] & (df['diameter_m'] >= 10) & (df['after_date'] < cutoff)].copy()

cal_lon360 = [
    ( 1,259.508, 9.051,'good'), ( 2,188.579,25.605,'good'), ( 3,268.849,14.527,'good'),
    ( 6,266.216,15.652,'good'), ( 8,176.886,46.354,'good'), ( 9,246.569,-2.020,'good'),
    (10,236.034,-6.018,'faint'),(11,250.767, 2.912,'good'),(12,255.011,11.479,'good'),
    (13,177.892, 5.544,'good'),(14,186.484,10.599,'faint'),(15,201.395, 4.431,'good'),
    (17,248.912,-0.632,'good'),(18,259.395,-6.847,'good'),(19,246.710,-4.168,'good'),
    (20,235.098, 3.242,'good'),(21,279.364, 4.866,'good'),(22,279.799,24.106,'good'),
    (23, 37.832,-0.964,'good'),(24,178.252,30.494,'good'),(25,183.965,-2.566,'good'),
    (26,245.290,24.921,'good'),(29,245.189, 7.495,'good'),(30,271.465,12.332,'good'),
    (31,185.502,40.341,'good'),(32,133.705,46.611,'good'),(33, 53.382, 3.119,'good'),
    (34,126.305,41.019,'good'),(35,202.796,18.936,'good'),(36,112.394,32.251,'good'),
    (37,196.488,12.272,'good'),(38,246.894, 4.473,'good'),(39,275.991, 3.703,'good'),
    (40,291.109,24.584,'good'),(41,201.609,35.907,'good'),(42,246.831, 3.291,'good'),
    (43,248.523, 2.579,'good'),
]

def nearest_cal(lat, lon):
    best_id, best_d = None, 999.0
    for (cid, clon, clat, ccat) in cal_lon360:
        dlon = abs(lon - clon) % 360
        dlon = min(dlon, 360 - dlon)
        d = math.sqrt((lat - clat)**2 + dlon**2)
        if d < best_d:
            best_d, best_id = d, cid
    return best_id if best_d < 0.05 else None

pre['cal_id'] = pre.apply(lambda r: nearest_cal(r['lat'], r['lon_360']), axis=1)

n_cal = pre['cal_id'].notna().sum()
n_new = pre['cal_id'].isna().sum()

print(f"Pre-2018, in-swath, >=10m:          {len(pre)}")
print(f"  Are calibration impacts:           {n_cal}")
print(f"  Are NOT in calibration set (new):  {n_new}")

print("\nImpacts NOT in calibration set:")
print(f"{'HiRISE ID':30s} {'lat':>7} {'lon':>8} {'diam':>7} {'after_date':>12}")
print("-" * 70)
for _, r in pre[pre['cal_id'].isna()].sort_values('after_date').iterrows():
    print(f"{r['hirise_id']:30s} {r['lat']:>7.3f} {r['lon_360']:>8.3f} "
          f"{r['diameter_m']:>7.1f} {str(r['after_date'])[:10]:>12}")

print("\nCalibration impacts that ARE in this set:")
for _, r in pre[pre['cal_id'].notna()].sort_values('cal_id').iterrows():
    print(f"  cal {int(r['cal_id']):>2}  {r['hirise_id']:30s}  diam={r['diameter_m']:.1f}m")
