import pandas as pd, warnings
warnings.filterwarnings('ignore')

df = pd.read_csv(
    r'G:\crater_flux_output_folders\Impact_flux_project\daubar2022_annotated.csv',
    parse_dates=['after_date', 'before_date', 'hirise_date']
)

cutoff = pd.Timestamp('2018-01-01')
swath_cols = [c for c in df.columns if c.startswith('swath_')]

sub = df[df['in_any_swath']].copy()

print(f"In-swath total: {len(sub)}")
print(f"after_date available: {sub['after_date'].notna().sum()} / {len(sub)}")
print()

for label, diam_floor in [('Reliable (>=10m)', 10), ('Marginal+ (>=5m)', 5), ('All sizes', 0)]:
    s = sub[sub['diameter_m'] >= diam_floor]
    n_pre  = (s['after_date'] < cutoff).sum()
    n_post = (s['after_date'] >= cutoff).sum()
    n_na   = s['after_date'].isna().sum()
    print(f"{label}: {len(s)} in-swath  |  pre-2018: {n_pre}  |  post-2018: {n_post}  |  no date: {n_na}")

print()
print("Per-swath breakdown (diameter >= 10m):")
print(f"{'Swath':14s}  {'Total':>6}  {'Pre-2018':>9}  {'Post-2018':>10}  {'No date':>8}")
print("-" * 55)
for col in swath_cols:
    name = col.replace('swath_', '')
    s = df[df[col] & (df['diameter_m'] >= 10)]
    n_pre  = (s['after_date'] < cutoff).sum()
    n_post = (s['after_date'] >= cutoff).sum()
    n_na   = s['after_date'].isna().sum()
    print(f"{name:14s}  {len(s):>6}  {n_pre:>9}  {n_post:>10}  {n_na:>8}")

print()
print("All reliable (>=10m) in-swath impacts, sorted by after_date:")
print(f"{'Swath':14s}  {'Diam(m)':>8}  {'After date':>12}  {'Before date':>12}  Flag  HiRISE ID")
print("-" * 90)
for col in swath_cols:
    name = col.replace('swath_', '')
    s = df[df[col] & (df['diameter_m'] >= 10)].sort_values('after_date')
    for _, r in s.iterrows():
        if pd.notna(r['after_date']):
            flag = 'PRE ' if r['after_date'] < cutoff else 'POST'
        else:
            flag = 'N/A '
        ad = str(r['after_date'])[:10] if pd.notna(r['after_date']) else 'N/A'
        bd = str(r['before_date'])[:10] if pd.notna(r['before_date']) else 'N/A'
        print(f"{name:14s}  {r['diameter_m']:>8.1f}  {ad:>12}  {bd:>12}  {flag}  {r['hirise_id']}")
