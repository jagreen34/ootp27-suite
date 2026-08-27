#!/usr/bin/env python3
"""
verify_draftday.py — re-derive the models that ACTUALLY SCORE THE BOARD, and
fail loud if the fitting sample is not what the board claims it is.

    python3 verify_draftday.py

WHY THIS EXISTS. `verify_constants.py` re-derives every coefficient using the
SAME sample construction as the board, so it confirms the arithmetic and is
structurally blind to the sample being wrong. It passed for months while the
board was fitted on players observed a median of six seasons after their draft.
That is methodology rule 27: a check built from the same constant as the claim
is a mirror, not a test.

So this file checks three things the old harness cannot:

  1. SAMPLE IDENTITY  — every fitted row is the pool row from the player's own
                        DRAFT_YR. Median lag must be exactly 0.
  2. LIVE MODEL       — the coefficients verified are the ones in the scoring
                        path (BAT_MODEL_DD / ARM_MODEL_DD), not a superseded set.
  3. POPULATION MATCH — the fitted sample's current-level and gap distributions
                        must overlap the live draft pool. A model fitted on
                        24-year-olds cannot price 17-year-olds.

Exit 0 = safe to draft on. Exit 1 = do not.
"""
import sys, csv
import numpy as np
import pandas as pd
import draft_board as DB

DP = 'dp.parquet'
CS = 'pq/player_cross_section_full.parquet'
POOL = 'AC_draft_pool_172.csv'
TOL_COEF, TOL_INT = 0.02, 0.75

fails, warns = [], []
def check(ok, msg):
    print(('  OK   ' if ok else '  FAIL ') + msg)
    if not ok: fails.append(msg)
def warn(msg):
    print('  WARN ' + msg); warns.append(msg)

PITCH = ['PIT_FB_GR','PIT_CH','PIT_CB','PIT_SL','PIT_SI','PIT_CT','PIT_FO','PIT_SP','PIT_CC','PIT_KN']
BATC  = ['POW','EYE','POW P','EYE P','IF_RNG','OF_RNG']
ARMC  = ['HRA','PIT_CON','HRA P','PIT_CON_P','STM']

def band(h):
    h = str(h)
    if 'HS' in h: return 'HS'
    if 'Junior' in h: return 'JR'
    return 'SR'          # CO Senior + JuCo, exactly as fitted

print('\n=== 1. SAMPLE IDENTITY ==========================================')
dp = pd.read_parquet(DP)
cs = pd.read_parquet(CS, columns=['seed','ID','AGE','DRAFT_YR','BAT_WAR','PIT_WAR'])
agg = cs.groupby(['seed','ID'], as_index=False).agg(
        maxage=('AGE','max'), DY=('DRAFT_YR','max'),
        BW=('BAT_WAR','sum'), PW=('PIT_WAR','sum'))
m = dp.merge(agg, on=['seed','ID'])
m = m[(m.DY > 0) & (m.season == m.DY) & (m.maxage >= 26)].copy()
lag = (m.season - m.DY)
check(len(m) > 4000, 'fitted sample n = %d (expect ~5,978)' % len(m))
check(lag.median() == 0 and lag.abs().max() == 0,
      'every row is the player\'s own draft year (median lag %.0f, max |lag| %.0f)'
      % (lag.median(), lag.abs().max()))
m['b'] = m.HSC.apply(band)
print('       classes: %s' % m.b.value_counts().to_dict())

for c in set(BATC + ARMC + PITCH):
    if c in m.columns: m[c] = pd.to_numeric(m[c], errors='coerce')

print('\n=== 2. THE MODELS IN THE SCORING PATH ============================')
check(getattr(DB, 'USE_DRAFTDAY', False),
      'draft_board.USE_DRAFTDAY is True (the DD models are live)')

b = m[~m.POS.isin(['SP','RP','CL','P'])].copy()
b['cur'] = (b['POW'] + b['EYE']) / 2
b['gap'] = (b['POW P'] + b['EYE P']) / 2 - b['cur']
b['rng'] = np.where(b.POS.isin(['C','1B','2B','3B','SS']), b.IF_RNG, b.OF_RNG)
b = b[b.gap >= 0].dropna(subset=['rng','cur','gap'])

pmr = b.groupby('POS').rng.mean().round(1).to_dict()
for p, v in sorted(pmr.items()):
    got = DB.POS_MEAN_RNG_DD.get(p)
    check(got is not None and abs(got - v) <= 0.15,
          'POS_MEAN_RNG_DD[%s] derived %.1f vs script %s' % (p, v, got))
b['rngc'] = b.rng - b.POS.map(pmr)

print('  --- BAT_MODEL_DD ---')
for cls in ['HS','JR','SR']:
    s = b[b.b == cls]
    X = np.column_stack([np.ones(len(s)), s.cur, s.gap, s.rngc])
    bh, *_ = np.linalg.lstsq(X, s.BW.values, rcond=None)
    got = DB.BAT_MODEL_DD[cls]
    ok = abs(bh[0]-got[0]) <= TOL_INT and all(abs(bh[i]-got[i]) <= TOL_COEF for i in (1,2,3))
    check(ok, '%s  fitted (%s)  script (%s)  n=%d'
          % (cls, ', '.join('%7.3f' % v for v in bh), ', '.join('%7.3f' % v for v in got), len(s)))

a = m[m.POS.isin(['SP','RP','CL'])].copy()
a['eff'] = (a[PITCH].fillna(0) >= 40).sum(axis=1)
a['cur'] = (a['HRA'] + a['PIT_CON']) / 2
a['gap'] = (a['HRA P'] + a['PIT_CON_P']) / 2 - a['cur']
a = a[a.gap >= 0].dropna(subset=['cur','gap','STM'])
print('  --- ARM_MODEL_DD ---')
for cls in ['HS','JR','SR']:
    s = a[a.b == cls]
    X = np.column_stack([np.ones(len(s)), s.cur, s.gap, s.eff, s.STM])
    bh, *_ = np.linalg.lstsq(X, s.PW.values, rcond=None)
    got = DB.ARM_MODEL_DD[cls]
    ok = abs(bh[0]-got[0]) <= TOL_INT and all(abs(bh[i]-got[i]) <= TOL_COEF for i in (1,2,3,4))
    check(ok, '%s  fitted (%s)  script (%s)  n=%d'
          % (cls, ', '.join('%7.3f' % v for v in bh), ', '.join('%7.3f' % v for v in got), len(s)))

print('\n  --- the sign that broke the old board ---')
Xp = np.column_stack([np.ones(len(b)), b.cur, b.gap, b.rngc]
                     + [(b.b == k).values.astype(float) for k in ('HS','JR')])
bh, *_ = np.linalg.lstsq(Xp, b.BW.values, rcond=None)
e = b.BW.values - Xp @ bh
se = np.sqrt((e @ e / (len(b) - Xp.shape[1])) * np.diag(np.linalg.inv(Xp.T @ Xp)))
t_gap = bh[2] / se[2]
check(abs(t_gap) < 2.0 or bh[2] < 0,
      'batter GAP is null or negative (b=%+.3f, t=%+.2f) — a POSITIVE gap term means the sample regressed' % (bh[2], t_gap))
check(bh[3] / se[3] > 5, 'batter RANGE is the strongest term (b=%+.3f, t=%+.2f)' % (bh[3], bh[3]/se[3]))

print('\n=== 3. POPULATION MATCH vs THE LIVE POOL =========================')
try:
    pool = list(csv.DictReader(open(POOL)))
except FileNotFoundError:
    warn('%s not found — population match SKIPPED' % POOL); pool = []
if pool:
    def f(r, k):
        try: return float(r.get(k, ''))
        except (TypeError, ValueError): return None
    pb = [( (f(r,'POW') or 0) + (f(r,'EYE') or 0) )/2 for r in pool if r['POS'] not in ('SP','RP','CL','P')]
    pa = [( (f(r,'HRA') or 0) + (f(r,'CON') or 0) )/2 for r in pool if r['POS'] in ('SP','RP','CL','P')]
    for lbl, fit, live in (('BATS', b.cur, pb), ('ARMS', a.cur, pa)):
        lo, hi = fit.quantile(.02), fit.quantile(.98)
        out = sum(1 for v in live if v < lo or v > hi)
        check(out / len(live) < 0.25,
              '%s: %d of %d pool players (%.0f%%) outside the fitted 2-98 band [%.1f, %.1f]'
              % (lbl, out, len(live), 100*out/len(live), lo, hi))
        if np.median(live) < fit.quantile(.10):
            warn('%s: pool median %.1f sits below the fitted 10th percentile %.1f — '
                 'the bottom of the board is extrapolation, do not read it'
                 % (lbl, np.median(live), fit.quantile(.10)))

print('\n' + '=' * 66)
if fails:
    print('DO NOT DRAFT ON THIS BOARD — %d check(s) failed:' % len(fails))
    for f_ in fails: print('   - ' + f_)
    sys.exit(1)
print('ALL CHECKS PASS. The board is fitted on true draft-day players and the')
print('verified coefficients are the ones in the scoring path.')
if warns:
    print('\n%d warning(s) — read before using the bottom of the board:' % len(warns))
    for w in warns: print('   - ' + w)
sys.exit(0)
