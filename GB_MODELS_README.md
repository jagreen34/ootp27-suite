# GB WAR Models — README (v27)

**These are May 28, 2026 reconstructions**, regenerated after the original 3C-2
pkls were lost (built in an ephemeral session, never persisted). Verified against
documented CV R² targets:

- `gb_sp_season_v27.pkl` — SP projected WAR. **CV R² 0.719** (target 0.711, GroupKFold-by-ID).
- `gb_bat_season_v27.pkl` — batter projected WAR. **CV R² 0.623** (target 0.607).

Built on **sklearn 1.8.0**. joblib pickles are sklearn-major-version sensitive: if
`/opt/ootp27-suite/` runs a different sklearn major version and a model fails to
load, **re-run `retrain_v27.py` in that environment** rather than loading a
mismatched binary. The suite degrades gracefully if the SP pkl is absent — the
Pitching module falls back to the A15 linear WAR estimate (R²=0.648) automatically.

## Key spec details (these make the numbers reproduce)
- **SP is RATINGS-ONLY — IP is NOT a feature.** Including IP inflates R² to ~0.79
  (season innings is a volume signal); a projection model must not see future
  innings. SP features: `[STU, MOV, PIT_CON, PBABIP, HRA, STM, STU_x_MOV]`.
- **BAT includes defensive ratings** (IF_RNG/OF_RNG/C_ABI/IF_ARM/OF_ARM); offense
  alone only reaches ~0.53. BAT features: `[CON, GAP, POW, EYE, BABIP, SPE,
  IF_RNG, OF_RNG, C_ABI, IF_ARM, OF_ARM]`.
- Target: SP → `PIT_WAR`; BAT → `WAR` (NOT `BAT_WAR` — no such column in OOTP 27).
- Cohorts: SP = `ROLE=='SP' AND PIT_GS>25`; BAT = non-pitcher POS AND `PA>100`.
- Loader: use **joblib**, not raw pickle (raw `pickle.load` fails).

## Files
- `retrain_v27.py` — **single source of truth.** Regenerates everything. If you
  keep one file, keep this. Models rebuild from it; it can't rebuild from them.
- `gb_sp_season_v27.pkl` / `sp_features_v27.pkl` — SP model + feature list (cache).
- `gb_bat_season_v27.pkl` / `bat_features_v27.pkl` — batter model + features (cache).
- `gb_sp_season_v27_importances.csv` / `gb_bat_season_v27_importances.csv` — what
  the models learned (SP dominated by STU×MOV 0.46 + PIT_CON 0.30).

## Consumed by
- `pitching.py` → `acquisitions.sp_war_estimate()` loads the SP model for the
  Rotation tab's Proj WAR + quality tiers, and My Team's rotation-quality verdict.
  Batter model not yet wired into a module.
