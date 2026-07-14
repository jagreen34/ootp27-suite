"""
rating_scale.py — shared 1-100 ↔ 20-80 rating-scale conversion.

Single source of truth for the scale toggle used by every uploader in the suite
(draft, my_team, acquisitions). Extracted from draft.py (B3.1) so the draft board,
My Team, and Acquisitions all convert identically instead of three modules each
carrying — or silently missing — their own copy.

The suite/model is built on the 20-80 scale. A 1-100 export run through the model
untouched reads every player as replacement-level filler (silent-zero). The toggle
in each uploader routes 1-100 files through _convert_1to100_to_2080 BEFORE any
rename/guard/prep touches the ratings.

Operates on SHORT CSV names (pre-rename): 'CON', 'FB', 'CON_1', … — i.e. call it
on the raw read_csv frame, before prep_data / the engine-detection guard.

Function name keeps its leading underscore for verification/call-site continuity
across the three consumers (grep target `_convert_1to100_to_2080`); it is the
module's public entry point despite the underscore.
"""
from __future__ import annotations
import pandas as pd


def _convert_1to100_to_2080(raw: pd.DataFrame) -> pd.DataFrame:
    """Convert 1-100 rating columns to the 20-80 scale the whole suite/model was
    trained on. Formula VERIFIED against a paired export (same 193 prospects, both
    scales): 20-80 = round_to_nearest_5(20 + 0.6 * v1_100) — 95.2% exact, the rest
    off by exactly one 5-step (rounding boundary, within the fog). Applied ONLY to
    rating columns; identity/stat/counting columns are left untouched.
    """
    df = raw.copy()
    # rating columns (short CSV names, pre-rename) that live on the 1-100/20-80 scale
    RATING_COLS = [
        # batter
        'CON','BABIP','GAP','POW','EYE',"K's",'CON P','GAP P','POW P','EYE P','K P',
        'BUN','BFH','SPE','SR','STE','RUN',
        # pitcher core + potentials
        'STU','MOV','CON_1','PBABIP','HRA','STU P','MOV P','CON P_1','PBABIP P','HRA P',
        # pitch grades + potentials (all 12)
        'FB','FBP','CH','CHP','CB','CBP','SL','SLP','SI','SIP','SP','SPP','CT','CTP',
        'FO','FOP','CC','CCP','SC','SCP','KC','KCP','KN','KNP',
        # fielding tools
        'C ABI','C FRM','C ARM','IF RNG','IF ERR','IF ARM','TDP',
        'OF RNG','OF ERR','OF ARM',
        # position ratings + potentials
        'P','C','1B','2B','3B','SS','LF','CF','RF',
        'P Pot','C Pot','1B Pot','2B Pot','3B Pot','SS Pot','LF Pot','CF Pot','RF Pot',
        'STM','PT',
    ]
    for c in RATING_COLS:
        if c in df.columns:
            v = pd.to_numeric(df[c], errors='coerce')
            conv = (20.0 + 0.6 * v)
            conv = (conv / 5.0).round() * 5.0          # round to nearest 5
            # keep NaN where the source was non-numeric/blank; ints elsewhere
            df[c] = conv.where(v.notna(), df[c])
    return df
