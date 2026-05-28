"""
retrain_v27.py — OOTP 27 GB WAR model retrain (study 3C-2, regenerated May 28 2026)

SINGLE SOURCE OF TRUTH for GB_WAR feature engineering. The original 3C-2 pkls were
generated in an ephemeral session and never persisted; this script reconstructs them
from the registry spec and the A-T cross-section parquet, verified against the
documented CV R² targets (SP 0.711, BAT 0.607).

Verified results (GroupKFold-by-ID, 5 fold):
    SP  CV R² = 0.719  (target 0.711)  N=17,137  groups=1,142
    BAT CV R² = 0.623  (target 0.607)  N=55,994  groups=2,175

KEY SPEC NOTES (these are the details that make the numbers reproduce):
  * SP model is RATINGS-ONLY — IP is NOT a feature. Including IP inflates R² to ~0.79
    because season-level innings is a strong volume signal. The projection model must
    not see future innings, so IP is excluded. This is what pins SP to 0.711.
  * SP uses the STU x MOV interaction (registry F1 finding: SP value routes through the
    high-stuff/high-movement tail).
  * BAT model INCLUDES defensive ratings (IF_RNG/OF_RNG/C_ABI/IF_ARM/OF_ARM). Offensive
    ratings alone score only ~0.53; defense closes the gap to 0.62 because batter WAR
    has a large defensive component.
  * Cohorts: SP = ROLE=='SP' AND PIT_GS>25.  BAT = non-pitcher POS AND PA>100.
  * Target: SP -> PIT_WAR ; BAT -> WAR (note: NOT BAT_WAR — the 3C-2 pipeline-fix
    corrected an earlier BAT_WAR->WAR target bug).

Sklearn version at regeneration: 1.8.0  (joblib pkls are version-sensitive; if the
suite runs a different sklearn major version, re-run this script rather than loading
a mismatched pkl.)
"""
import pandas as pd
import numpy as np
import joblib
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import cross_val_score, GroupKFold

PARQUET = 'player_cross_section_full.parquet'   # A-T cross-section
OUT_DIR = '.'

GB_PARAMS = dict(n_estimators=300, max_depth=3, learning_rate=0.05,
                 subsample=0.8, random_state=42)

SP_FEATURES  = ['STU', 'MOV', 'PIT_CON', 'PBABIP', 'HRA', 'STM', 'STU_x_MOV']
BAT_FEATURES = ['CON', 'GAP', 'POW', 'EYE', 'BABIP', 'SPE',
                'IF_RNG', 'OF_RNG', 'C_ABI', 'IF_ARM', 'OF_ARM']


def build_gb_features(df):
    """Single source of truth for feature engineering. Adds derived columns the
    models expect. Mutates a copy; returns it."""
    d = df.copy()
    d['ID'] = d['ID'].astype(str)
    numeric = set(SP_FEATURES + BAT_FEATURES + ['STU', 'MOV', 'IP', 'PIT_WAR',
                  'PIT_GS', 'PA', 'WAR'])
    for c in numeric:
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors='coerce')
    d['STU_x_MOV'] = d['STU'] * d['MOV']          # SP interaction term
    return d


def sp_cohort(d):
    return d[(d['ROLE'] == 'SP') & (d['PIT_GS'] > 25)].dropna(
        subset=SP_FEATURES + ['PIT_WAR', 'ID'])


def bat_cohort(d):
    return d[(~d['POS'].isin(['SP', 'RP', 'CL', 'P'])) & (d['PA'] > 100)].dropna(
        subset=BAT_FEATURES + ['WAR', 'ID'])


def _train_and_verify(data, features, target, label, target_r2):
    gb = GradientBoostingRegressor(**GB_PARAMS)
    cv = cross_val_score(gb, data[features], data[target],
                         cv=GroupKFold(5), groups=data['ID'], scoring='r2')
    gb.fit(data[features], data[target])     # final fit on all rows
    print(f"{label}: CV R²={cv.mean():.4f} ± {cv.std():.4f}  "
          f"(target {target_r2})  N={len(data):,}  groups={data['ID'].nunique():,}")
    imp = sorted(zip(features, gb.feature_importances_), key=lambda x: -x[1])
    return gb, imp


def main():
    df = build_gb_features(pd.read_parquet(PARQUET))

    sp = sp_cohort(df)
    gb_sp, imp_sp = _train_and_verify(sp, SP_FEATURES, 'PIT_WAR', 'SP', 0.711)

    bat = bat_cohort(df)
    gb_bat, imp_bat = _train_and_verify(bat, BAT_FEATURES, 'WAR', 'BAT', 0.607)

    joblib.dump(gb_sp,  f'{OUT_DIR}/gb_sp_season_v27.pkl')
    joblib.dump(SP_FEATURES,  f'{OUT_DIR}/sp_features_v27.pkl')
    joblib.dump(gb_bat, f'{OUT_DIR}/gb_bat_season_v27.pkl')
    joblib.dump(BAT_FEATURES, f'{OUT_DIR}/bat_features_v27.pkl')
    pd.DataFrame(imp_sp,  columns=['feature', 'importance']).to_csv(
        f'{OUT_DIR}/gb_sp_season_v27_importances.csv', index=False)
    pd.DataFrame(imp_bat, columns=['feature', 'importance']).to_csv(
        f'{OUT_DIR}/gb_bat_season_v27_importances.csv', index=False)
    print("Saved 4 pkls + 2 importance CSVs.")


if __name__ == '__main__':
    main()
