#!/usr/bin/env python3
"""
quakers.py — apply THE CARD to any OOTP roster/player export. LOCKED 2026-08-26.

    python3 quakers.py new.csv                 # whole league
    python3 quakers.py new.csv --org Philad    # one org
    python3 quakers.py qua4.csv -o graded.csv

NO MODELS. NO FITTING. Bars, gates and counts only — every number below is a
measured constant with its finding cited. If a rule is wrong it gets a new
finding and a reversal entry, not an edit here.

Design rule: FAIL LOUD. A missing load-bearing column is an error, never a
silent zero (methodology rule 22).
"""
import csv, sys, argparse

# ============================ LOCKED CONSTANTS ============================

# --- Rule 1/2/3: top-quartile bars. AC values (percentiles of AC regulars).
# wRC+ is normalised inside a league, so the tag must be too. Parquet values
# differ on EYE (50) and GAP (55) — do NOT use them on AC players. [card §00]
BARS_AC = {'POW': 50, 'EYE': 60, 'BABIP': 55, 'CON': 55, 'GAP': 50}

# Only power and eye stand alone; the other three are complements. [A92/§04]
LEAD_TOOLS = ('POW', 'EYE')

# --- Rule 5: glove floors, on the TOOLS. Never the position rating (it drifts
# with games played). 3B is range+arm because on ZR they are a dead heat
# (+0.310 v +0.290, n=17,459). [A73 + measured 2026-08-26]
RANGE_GATE = {'SS': 60, '2B': 55, 'CF': 65}
GATE_3B_SUM = 120                      # IF RNG + IF ARM
NO_GATE = ('C', '1B', 'LF', 'RF', 'DH')  # catcher defence is a null, p=.921 [A58a]

# --- Rule 8: a pitch is a real weapon at 40 — EXCEPT the changeup at 45.
# 40 is the engine's hinge, not a percentile: a pitch at 35 at age 20-21 reaches
# 45 by 25 only 5% of the time; at 40 it is 30% (counting washouts). [A41]
PITCH_FLOOR = 40
PITCH_FLOOR_CH = 45
PITCHES = ['FB', 'CH', 'CB', 'SL', 'SI', 'CT', 'FO', 'SC', 'KN', 'SP']
STARTER_EFF = 3                        # career WAR 10.8 -> 15.2 across this line

# --- Rule 9: control is convex. A point at 70 is worth 57x a point at 30. [A79]
CTL_INERT = 45                         # below this the tool is nearly worthless
CTL_BUY = 50                           # at/above this it is worth paying for

# --- Rule 10: stamina buys innings, not quality. Buy 50 and stop. [A14 S1/A80]
STM_GATE = 50

# --- Rule 7: HRA is the arm's best tool, ~2x control. Read HRA, never Overall
# Movement — MOV is a derived display field that does not move home runs. [A88/A69]
HRA_OK = 55

# --- Rule 12: what an edge can carry, in wRC+.
BAND_IGNORE, BAND_TIEBREAK = 4, 10
PER_GRADE = {'POW': 3.46, 'EYE': 2.94, 'BABIP': 1.47, 'GAP': 0.99,
             'CON': 0.78, 'AVK': 0.33}   # wRC+ per 5 display points

# Tiebreak ladder, wRC+ equivalent (1 run = 1.47 wRC+ over a season).
TIEBREAK = [('position: C vs 1B', 24.5), ('elite legs vs average', 11.3),
            ('one grade of glove at 2B', 10.4), ('at SS', 10.1), ('at CF', 9.9),
            ('at 3B', 6.9), ('at RF', 6.0), ('at LF', 5.8),
            ('at 1B', 2.4), ('one year past 30', 2.3)]

ARM_POS = ('SP', 'RP', 'CL', 'P')

# ============================== MACHINERY ==============================

def num(row, key, name, required=True):
    v = row.get(key, '')
    try:
        return float(v)
    except (TypeError, ValueError):
        if required:
            raise SystemExit("FATAL: %s has no usable '%s' (got %r)" % (name, key, v))
        return None

def grade_bat(r, name):
    pos = r.get('POS', '?')
    cleared = [t for t in BARS_AC if num(r, t, name) >= BARS_AC[t]]
    lead = any(t in cleared for t in LEAD_TOOLS)
    # glove
    if pos in RANGE_GATE:
        col = 'IF RNG' if pos in ('SS', '2B') else 'OF RNG'
        v = num(r, col, name)
        glove = ('PASS' if v >= RANGE_GATE[pos] else 'FAIL',
                 '%s %.0f v %d' % (col, v, RANGE_GATE[pos]))
    elif pos == '3B':
        s = num(r, 'IF RNG', name) + num(r, 'IF ARM', name)
        glove = ('PASS' if s >= GATE_3B_SUM else 'FAIL',
                 'rng+arm %.0f v %d' % (s, GATE_3B_SUM))
    elif pos in NO_GATE:
        glove = ('n/a', 'no gate')
    else:
        glove = ('?', 'unknown pos %s' % pos)
    return {'side': 'BAT', 'tools': len(cleared), 'bars': '+'.join(cleared) or '-',
            'lead_tool': 'yes' if lead else 'NO',
            'glove': glove[0], 'glove_detail': glove[1],
            'verdict': bat_verdict(len(cleared), lead, glove[0])}

def bat_verdict(n, lead, glove):
    if glove == 'FAIL':
        return 'GLOVE FAILS THE GATE'
    if n == 0:
        return 'no top-quartile tool'
    if not lead:
        return 'RULE 2: no power or eye — below a no-tool bat'
    if n >= 3:
        return 'core bat'
    if n == 2:
        return 'qualifying bat'
    return 'one-tool: playable, not a building block'

def grade_arm(r, name):
    eff = 0
    for p in PITCHES:
        v = num(r, p, name, required=False) or 0
        if v >= (PITCH_FLOOR_CH if p == 'CH' else PITCH_FLOOR):
            eff += 1
    ctl = num(r, 'CON_1', name, required=False)
    if ctl is None:
        ctl = num(r, 'CON', name)          # some exports name it plainly
    hra = num(r, 'HRA', name)
    stm = num(r, 'STM', name)
    ctl_v = 'buy zone' if ctl >= CTL_BUY else ('marginal' if ctl >= CTL_INERT else 'INERT')
    role = 'STARTER' if eff >= STARTER_EFF else 'reliever'
    flags = []
    if eff < STARTER_EFF: flags.append('under %d pitches' % STARTER_EFF)
    if ctl < CTL_INERT:   flags.append('control inert')
    if stm < STM_GATE:    flags.append('stamina short')
    if hra < HRA_OK:      flags.append('HRA light')
    return {'side': 'ARM', 'eff': eff, 'role': role, 'HRA': hra, 'control': ctl,
            'ctl_band': ctl_v, 'STM': stm,
            'verdict': 'clean pass' if not flags else '; '.join(flags)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv')
    ap.add_argument('--org', default=None, help='substring match on ORG')
    ap.add_argument('--minpa', type=float, default=0)
    ap.add_argument('-o', '--out', default=None)
    a = ap.parse_args()

    rows = list(csv.DictReader(open(a.csv)))
    if not rows:
        raise SystemExit('FATAL: %s is empty' % a.csv)
    for need in ('POS', 'Name'):
        if need not in rows[0]:
            raise SystemExit("FATAL: %s has no '%s' column" % (a.csv, need))

    out = []
    for r in rows:
        if a.org and a.org.lower() not in str(r.get('ORG', '')).lower():
            continue
        name = r.get('Name', '?')
        try:
            g = grade_arm(r, name) if r['POS'] in ARM_POS else grade_bat(r, name)
        except SystemExit as e:
            print('  SKIP %-22s %s' % (name, e)); continue
        g.update({'Name': name, 'POS': r['POS'], 'Age': r.get('Age', ''),
                  'PA': r.get('PA', ''), 'IP': r.get('IP', ''),
                  'wRC+': r.get('wRC+', ''), 'FIP-': r.get('FIP-', '')})
        out.append(g)

    bats = [x for x in out if x['side'] == 'BAT']
    arms = [x for x in out if x['side'] == 'ARM']
    bats.sort(key=lambda x: (-x['tools'], x['glove'] == 'FAIL'))
    arms.sort(key=lambda x: (-x['eff'], -(x['control'] or 0)))

    print('\n=== BATS (%d) — bars: %s ===' % (len(bats),
          ' '.join('%s%d' % (k, v) for k, v in BARS_AC.items())))
    print('%-20s %-3s %-4s %-5s %-24s %-4s %-22s %s'
          % ('name', 'pos', 'age', 'tool', 'bars cleared', 'lead', 'glove', 'verdict'))
    for x in bats:
        print('%-20s %-3s %-4s %-5d %-24s %-4s %-22s %s'
              % (x['Name'][:20], x['POS'], x['Age'], x['tools'], x['bars'],
                 x['lead_tool'], '%s %s' % (x['glove'], x['glove_detail']), x['verdict']))

    print('\n=== ARMS (%d) ===' % len(arms))
    print('%-20s %-3s %-4s %-4s %-9s %-5s %-9s %-5s %s'
          % ('name', 'pos', 'age', 'eff', 'role', 'HRA', 'control', 'STM', 'verdict'))
    for x in arms:
        print('%-20s %-3s %-4s %-4d %-9s %-5.0f %-9s %-5.0f %s'
              % (x['Name'][:20], x['POS'], x['Age'], x['eff'], x['role'],
                 x['HRA'], '%.0f %s' % (x['control'], x['ctl_band']), x['STM'], x['verdict']))

    core = [x for x in bats if x['tools'] >= 2 and x['lead_tool'] == 'yes']
    print('\n--- SUMMARY ---')
    print('  qualifying bats (2+ tools incl. power or eye): %d   [target 3-4, A94]' % len(core))
    print('  bats failing rule 2 (no power/eye): %d' % sum(1 for x in bats if x['tools'] and x['lead_tool'] == 'NO'))
    print('  bats failing their glove gate:      %d' % sum(1 for x in bats if x['glove'] == 'FAIL'))
    print('  arms at %d+ effective pitches:       %d of %d' % (STARTER_EFF, sum(1 for x in arms if x['eff'] >= STARTER_EFF), len(arms)))
    print('  arms with control in the buy zone:  %d' % sum(1 for x in arms if x['ctl_band'] == 'buy zone'))
    print('  arms with control INERT (<%d):       %d' % (CTL_INERT, sum(1 for x in arms if x['ctl_band'] == 'INERT')))
    print('\n  RULE 12 — an edge under %d wRC+ is noise; %d-%d is a tiebreak only; %d+ you can pay for.'
          % (BAND_IGNORE, BAND_IGNORE, BAND_TIEBREAK - 1, BAND_TIEBREAK))
    print('  One grade of any single rating is %s wRC+ — all noise. A whole tool is 9.5-15.8.'
          % '/'.join('%.1f' % v for v in list(PER_GRADE.values())[:3]))

    if a.out:
        keys = sorted({k for x in out for k in x})
        with open(a.out, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(out)
        print('\nwrote %s' % a.out)

if __name__ == '__main__':
    main()
