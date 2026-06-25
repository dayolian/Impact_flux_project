cal_with_diam = [
    ( 9,246.569, -2.020,  6.6,'good'),
    (11,250.767,  2.912,  2.5,'good'),
    (12,255.011, 11.479,  4.8,'good'),
    (17,248.912, -0.632, 33.8,'good'),
    (18,259.395, -6.847,  6.4,'good'),
    (19,246.710, -4.168,  6.0,'good'),
    (26,245.290, 24.921,  6.4,'good'),
    (28,250.787,-13.995,  7.1,'junk'),
    (29,245.189,  7.495,  7.6,'good'),
    (38,246.894,  4.473,  7.3,'good'),
    (42,246.831,  3.291,  9.0,'good'),
    (43,248.523,  2.579, 11.8,'good'),
]
print("Calibration impacts in 245-260E swath:")
print(f"{'Cal':>4}  {'Diam(m)':>8}  {'Cat':6}  {'>=10m?':>7}")
print("-"*35)
for (cid, lon, lat, diam, cat) in cal_with_diam:
    flag = "YES" if diam >= 10 else "no"
    print(f"{cid:>4}  {diam:>8.1f}  {cat:6}  {flag:>7}")
print()
print(f"Total in swath:                  {len(cal_with_diam)}")
print(f">=10m (reliably detectable):     {sum(1 for r in cal_with_diam if r[3]>=10)}")
print(f"<10m (below reliable threshold): {sum(1 for r in cal_with_diam if r[3]<10)}")
