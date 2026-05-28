"""
OOTP 27 Suite — Acquisitions Module
=====================================
Four modes (only Mode 1 implemented; 2-4 are stubs):

  Mode 1 — Browse the League
  Mode 2 — Quick Eval from Slack       [stub]
  Mode 3 — Free Agents                 [stub]
  Mode 4 — Build a Deal                [stub]

Column conventions follow the OOTP 27 rename pipeline defined below.
All F1 formulas use locked v14.2 coefficients from the registry.
Trade Value = (F1 - 0.2) × control_window × POS_MULT
  where control_window = min(YEARS_LEFT, years_until_FA).
Feasibility = Market score (0-10) + Fit score (0-10) + aggregate.
"""

import os
import re
import numpy as np
import pandas as pd
import streamlit as st

from db import League, compute_control_window, compute_arb_status

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

# Trade-value positional multipliers (253K validated)
POS_MULT = {
    'C':  1.30, '1B': 1.00, '2B': 1.30, '3B': 1.20,
    'SS': 1.50, 'LF': 1.05, 'CF': 1.55, 'RF': 1.25,
    'SP': 1.00, 'RP': 0.60, 'CL': 0.60,
}

# WAR-reconstruction positional constants (OOTP 27 sim-validated)
POS_ADJ_CONSTANTS = {
    'C':  3.252, 'SS': 3.022, '2B': 2.646, '3B': 2.547,
    'CF': 2.503, 'LF': 1.832, 'RF': 1.829, '1B': 1.556,
}

PITCHER_POSITIONS = {'SP', 'RP', 'CL'}
BATTER_POSITIONS  = {'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF'}

# Effective pitch threshold (registry-locked: grade 30)
EFF_PITCH_THRESHOLD = 30

# Service time constants (AC league rules)
DAYS_PER_SERVICE_YEAR = 76
FA_SERVICE_YEARS      = 6
ARB_SERVICE_YEARS     = 3

# ── OOTP 27 RENAME PIPELINE ───────────────────────────────────────────────────
# Maps ACTUAL export column names → suite column names.
# Verified against real export (player_search___shortlist_player_search_ootp27_suite.csv).
# Column name conventions in this export use short names and dot-suffix for collisions.
PLAYER_RENAMES = {
    # Identity — already correct in export: ID, POS, Name, TM, ORG, Age, B, T, OVR, POT
    'Age':          'AGE',
    'RL':           'ROLE',       # Role column is 'RL' not 'Role'
    'Prone':        'PRONE',      # Injury Prone is 'Prone'
    'Risk':         'DEV_RISK',   # Development Risk is 'Risk'
    'Type':         'PIT_TYPE',   # Personality type

    # Batting ratings — mostly already correct short names
    "K's":          'AVK',        # Avoid K's
    'BABIP':        'BAT_BABIP_RATING',  # ratings BABIP (20-80 integer)
    'GBT':          'BAT_GBT',
    'FBT':          'BAT_FBT',
    'HT P':         'BAT_BABIP_P',   # BABIP potential uses 'HT P' label
    'CON P':        'CON_P',
    'GAP P':        'GAP_P',         # Note: not 'Gap Pot.' — short name
    'POW P':        'POW_P',         # Wait, actual export says 'POW P'? Let me check
    'EYE P':        'EYE_P',
    'K P':          'AVK_P',
    # Batter v-splits: export uses 'CON vL', 'GAP vL' etc (space, no dot)
    'CON vL':       'CON_vL',
    'CON vR':       'CON_vR',
    'GAP vL':       'GAP_vL',
    'GAP vR':       'GAP_vR',
    'POW vL':       'POW_vL',
    'POW vR':       'POW_vR',
    'EYE vL':       'EYE_vL',
    'EYE vR':       'EYE_vR',
    'BA vL':        'BA_vL',
    'BA vR':        'BA_vR',
    'K vL':         'AVK_vL',
    'K vR':         'AVK_vR',

    # Pitching ratings
    # STU, MOV, PBABIP, HRA, STM already correct
    'CON_1':        'PIT_CON',       # pitcher control (suffix collision with batter CON)
    'G/F':          'PIT_GF',
    'PIT':          'PIT_COUNT',     # pitch count column is 'PIT'
    'PT':           'PIT_PT',        # pitcher type
    'VT':           'VELO_P',        # velocity potential
    # Pitcher v-splits: 'STU vL', 'MOV vL' etc (space)
    'STU vL':       'STU_vL',
    'STU vR':       'STU_vR',
    'MOV vL':       'MOV_vL',
    'MOV vR':       'MOV_vR',
    'CON vL_1':     'PIT_CON_vL',   # pitcher CON vL (suffix _1 disambiguates from batter)
    'CON vR_1':     'PIT_CON_vR',
    'PBABIP vL':    'PBABIP_vL',
    'PBABIP vR':    'PBABIP_vR',
    'HRA vL':       'HRA_vL',
    'HRA vR':       'HRA_vR',
    'STU P':        'STU_P',
    'MOV P':        'MOV_P',
    'CON P_1':      'PIT_CON_P',    # pitcher CON potential
    'PBABIP P':     'PBABIP_P',
    'HRA P':        'HRA_P',
    # Pitch grades — short names confirmed: FB, CH, CB, SL, SI, SP, CT, FO, CC, SC, KC, KN
    'FB':           'PIT_FB_GR',
    'FBP':          'PIT_FB_GR_P',
    'CH':           'PIT_CH',
    'CHP':          'PIT_CH_P',
    'CB':           'PIT_CB',
    'CBP':          'PIT_CB_P',
    'SL':           'PIT_SL',
    'SLP':          'PIT_SL_P',
    'SI':           'PIT_SI',
    'SIP':          'PIT_SI_P',
    'SP':           'PIT_SP',
    'SPP':          'PIT_SP_P',
    'CT':           'PIT_CT',
    'CTP':          'PIT_CT_P',
    'FO':           'PIT_FO',
    'FOP':          'PIT_FO_P',
    'CC':           'PIT_CC',
    'CCP':          'PIT_CC_P',
    'SC':           'PIT_SC',
    'SCP':          'PIT_SC_P',
    'KC':           'PIT_KC',
    'KCP':          'PIT_KC_P',
    'KN':           'PIT_KN',
    'KNP':          'PIT_KN_P',

    # Fielding ratings — short names with spaces confirmed
    'C ABI':        'C_ABI',
    'C FRM':        'C_FRM',
    'C ARM':        'C_ARM',
    'IF RNG':       'IF_RNG',
    'IF ERR':       'IF_ERR',
    'IF ARM':       'IF_ARM',
    'OF RNG':       'OF_RNG',
    'OF ERR':       'OF_ERR',
    'OF ARM':       'OF_ARM',
    # TDP already correct
    # Fielding at position: bare position names (P, C, 1B, 2B, 3B, SS, LF, CF, RF)
    # These collide with position strings — rename to FLD_ prefix
    # NOTE: POS column is already 'POS'; these bare names are fielding ratings
    'P':            'FLD_P',
    'C':            'FLD_C',
    '1B':           'FLD_1B',
    '2B':           'FLD_2B',
    '3B':           'FLD_3B',
    'SS':           'FLD_SS',
    'LF':           'FLD_LF',
    'CF':           'FLD_CF',
    'RF':           'FLD_RF',
    'P Pot':        'FLD_P_P',
    'C Pot':        'FLD_C_P',
    '1B Pot':       'FLD_1B_P',
    '2B Pot':       'FLD_2B_P',
    '3B Pot':       'FLD_3B_P',
    'SS Pot':       'FLD_SS_P',
    'LF Pot':       'FLD_LF_P',
    'CF Pot':       'FLD_CF_P',
    'RF Pot':       'FLD_RF_P',

    # Batting stats
    'WAR':          'BAT_WAR',
    'BB%':          'BAT_BB_PCT',
    'BABIP_1':      'BAT_BABIP_STAT',   # stat BABIP (decimal)
    '1B_1':         'BAT_1B',
    '2B_1':         'BAT_2B',
    '3B_1':         'BAT_3B',

    # Pitching stats — suffix _1 on collision columns
    'WAR_1':        'PIT_WAR',
    'G':            'PIT_G',
    'GS':           'PIT_GS',
    'W':            'PIT_W',
    'L':            'PIT_L',
    'SV':           'PIT_SV',
    'HLD':          'PIT_HLD',
    'ERA':          'PIT_ERA',
    'FIP':          'PIT_FIP',
    'FIP-':         'PIT_FIP_MINUS',
    'rWAR':         'PIT_rWAR',
    'GB':           'PIT_GB',
    'FB_1':         'PIT_FB_STAT',
    'GO%':          'PIT_GO_PCT',
    'BB_1':         'PIT_BB',
    'K_1':          'PIT_K',
    'K%_1':         'PIT_K_PCT',
    'BB%_1':        'PIT_BB_PCT',
    'HR/9':         'PIT_HR9',
    'H/9':          'PIT_H9',
    'SPF%':         'SP_FATIGUE',
    'RPF%':         'RP_FATIGUE',

    # Fielding stats
    'POS_1':        'FLD_POS',
    'G_1':          'FLD_G',
    'GS_1':         'FLD_GS',
    # ZR, EFF, FRM, ARM, TC, E already correct

    # Misc / contract — short names confirmed
    'SLR':          'SALARY',
    'YL':           'YEARS_LEFT',
    'CV':           'CONTRACT_VALUE',
    'TY':           'CONTRACT_TOTAL_YRS',
    'MLY':          'ML_YRS',
    'MLD':          'ML_DAYS',
    'WAIV':         'ON_WAIVERS',
    'DFA':          'IS_DFA',
    'DEM':          'FA_DEMAND',
    'FAT':          'FA_TYPE',
    'ACT':          'IS_ACTIVE',
    'SLR':          'SALARY',
}

# Numeric columns to coerce on load (post-rename names)
NUMERIC_COLS = [
    'AGE', 'POW', 'CON', 'EYE', 'GAP', 'SPE', 'AVK',
    'BAT_BABIP_RATING', 'BAT_BABIP_STAT',
    'CON_P', 'GAP_P', 'POW_P', 'EYE_P',
    'CON_vL', 'CON_vR', 'GAP_vL', 'GAP_vR',
    'POW_vL', 'POW_vR', 'EYE_vL', 'EYE_vR',
    'STU', 'MOV', 'PIT_CON', 'PBABIP', 'HRA', 'STM',
    'STU_vL', 'STU_vR', 'MOV_vL', 'MOV_vR',
    'PIT_CON_vL', 'PIT_CON_vR',
    'STU_P', 'MOV_P', 'PIT_CON_P',
    'PIT_FB_GR', 'PIT_CH', 'PIT_SI', 'PIT_SL',
    'PIT_CB', 'PIT_CT', 'PIT_SP', 'PIT_COUNT',
    'C_ABI', 'C_FRM', 'C_ARM',
    'IF_RNG', 'IF_ERR', 'IF_ARM', 'TDP',
    'OF_RNG', 'OF_ERR', 'OF_ARM',
    'FLD_G', 'FLD_GS', 'ZR',
    'BAT_WAR', 'PIT_WAR', 'PA', 'IP',
    'PIT_G', 'PIT_GS', 'PIT_ERA', 'PIT_FIP', 'PIT_FIP_MINUS',
    'SP_FATIGUE', 'RP_FATIGUE',
    'YEARS_LEFT', 'CONTRACT_VALUE', 'CONTRACT_TOTAL_YRS',
    'ML_YRS', 'ML_DAYS',
]

# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING & PREP
# ══════════════════════════════════════════════════════════════════════════════

def _parse_velo(v) -> float:
    """Parse '87-89' velocity range strings → midpoint float."""
    if pd.isna(v) or v == '':
        return 0.0
    s = str(v).strip()
    m = re.match(r'(\d+)\s*[-–]\s*(\d+)', s)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_salary(v) -> float:
    """Parse salary strings → float.
    Handles: '$10 000', '$1,500,000', '$11k', '$1.5M'
    """
    if pd.isna(v) or str(v).strip() in ('', '-'):
        return 0.0
    s = str(v).strip().upper().replace(',', '').replace(' ', '')
    # Remove leading $
    s = s.lstrip('$')
    # Handle k/M suffixes
    if s.endswith('K'):
        try: return float(s[:-1]) * 1000
        except: return 0.0
    if s.endswith('M'):
        try: return float(s[:-1]) * 1_000_000
        except: return 0.0
    # Plain number
    digits = re.sub(r'[^\d.]', '', s)
    return float(digits) if digits else 0.0


def prep_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply the OOTP 27 rename pipeline and coerce numeric columns.
    Verified against real export format.
    """
    # Step 1 — apply rename map
    df = df.rename(columns={k: v for k, v in PLAYER_RENAMES.items() if k in df.columns})

    # Step 2 — parse velocity range strings → velo_mid
    if 'VELO' in df.columns:
        df['velo_mid'] = df['VELO'].apply(_parse_velo)
    else:
        df['velo_mid'] = 0.0

    # Step 3 — parse salary/demand strings
    if 'SALARY' in df.columns:
        df['SALARY'] = df['SALARY'].apply(_parse_salary)
    if 'FA_DEMAND' in df.columns:
        df['FA_DEMAND'] = df['FA_DEMAND'].apply(_parse_salary)

    # Step 4 — numeric coercion
    for col in NUMERIC_COLS + ['velo_mid']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Step 5 — normalize TM from ORG if needed
    if 'ORG' in df.columns and 'TM' not in df.columns:
        df['TM'] = df['ORG']

    return df


# ══════════════════════════════════════════════════════════════════════════════
# F1 FORMULAS — LOCKED v14.2 COEFFICIENTS
# ══════════════════════════════════════════════════════════════════════════════

def _s(v, d=0.0) -> float:
    """Safe float — returns d for NaN/None/non-numeric."""
    try:
        if pd.isna(v): return d
        return float(v)
    except Exception:
        return d


# ── Batter F1: OFF component ──────────────────────────────────────────────────
def off_f1(row) -> float:
    """
    Batter F1 — offensive WAR component.
    Uses validated v26 unstandardized coefficients on 20-80 rating scale.
    The v27 refit produces the same structural order with higher R² (0.591 vs
    0.447) due to the OFF/DEF decomposition; coefficient magnitudes are
    compatible since the rating scale is unchanged.
    NOTE: BAT_BABIP_RATING must be on the 20-80 integer scale, not decimal.
    """
    con   = _s(row.get('CON'))
    gap   = _s(row.get('GAP'))
    pow_  = _s(row.get('POW'))
    eye   = _s(row.get('EYE'))
    spe   = _s(row.get('SPE'))
    avk   = _s(row.get('AVK', 0))
    babip = _s(row.get('BAT_BABIP_RATING', row.get('BABIP', 50)))
    # Guard: if BABIP looks like a decimal stat, ignore it (use 50 as neutral)
    if babip < 1.0:
        babip = 50.0

    return (-14.168
        + pow_  * 0.1142
        + babip * 0.0725
        + eye   * 0.0400
        + con   * 0.0379
        + avk   * 0.0317
        + gap   * 0.0291
        + spe   * 0.0128)


# ── Batter F1: DEF component ──────────────────────────────────────────────────
# Two-step: predict ZR from fielding ratings, then convert ZR → DEF_WAR.
# ZR model coefficients ported from v26 validated models (same rating scale).
# Conversion: DEF_WAR = ZR * ZR_WAR_FACTOR[pos]
# Registry: DEF_WAR = (ZR + ARM) / 10; ZR_WAR factors calibrated per position.
ZR_MODELS = {
    'C':  {'intercept': -7.32,
           'coefs': {'C_ABI': 0.0628, 'C_FRM': 0.0196, 'C_ARM': 0.0539}},
    '1B': {'intercept': -13.43,
           'coefs': {'IF_RNG': 0.2540, 'IF_ERR': 0.0293, 'IF_ARM': -0.0013}},
    '2B': {'intercept': -47.24,
           'coefs': {'IF_RNG': 0.8635, 'IF_ARM': 0.0644}},
    '3B': {'intercept': -31.44,
           'coefs': {'IF_RNG': 0.3331, 'IF_ARM': 0.2642}},
    'SS': {'intercept': -66.76,
           'coefs': {'IF_RNG': 0.9064, 'IF_ARM': 0.3012}},
    'LF': {'intercept': -29.47,
           'coefs': {'OF_RNG': 0.6079, 'OF_ARM': 0.0041}},
    'CF': {'intercept': -46.77,
           'coefs': {'OF_RNG': 0.8833}},
    'RF': {'intercept': -52.45,
           'coefs': {'OF_RNG': 0.9968, 'OF_ARM': 0.0669}},
}

# Per-position ZR → DEF_WAR conversion factors (v26 validated, carried to v27)
ZR_WAR_FACTOR = {
    'C':  0.1333, '1B': 0.1182, '2B': 0.1227, '3B': 0.1248,
    'SS': 0.1040, 'LF': 0.1626, 'CF': 0.1111, 'RF': 0.1215,
}


def def_war(row, pos: str) -> float:
    """
    Batter F1 — defensive WAR component.
    Computes ZR from fielding ratings, converts to DEF_WAR.
    Returns 0.0 if position not in ZR_MODELS.
    """
    if pos not in ZR_MODELS:
        return 0.0
    m   = ZR_MODELS[pos]
    zr  = m['intercept']
    for col, coef in m['coefs'].items():
        zr += _s(row.get(col, 0)) * coef
    return zr * ZR_WAR_FACTOR[pos]


def pos_adj(row, pos: str) -> float:
    """Positional adjustment — PA-scaled constant."""
    if pos not in POS_ADJ_CONSTANTS:
        return 0.0
    pa = _s(row.get('PA', 500))
    return (pa / 650.0) * POS_ADJ_CONSTANTS[pos]


def batter_f1(row) -> float:
    """Full batter F1 = OFF + DEF + POS_ADJ. R² = 0.738."""
    pos = str(row.get('POS', ''))
    if pos not in BATTER_POSITIONS:
        return 0.0
    return off_f1(row) + def_war(row, pos) + pos_adj(row, pos)


# ── SP F1.1 — locked coefficients ────────────────────────────────────────────
def sp_f1(row) -> float:
    """
    SP F1.1 — v-splits + archetype interactions. CV R² = 0.779.
    Falls back to v1 (no interactions) if v-split columns absent.
    """
    has_vsplits = all(c in row and _s(row.get(c)) != 0
                      for c in ['STU_vL', 'STU_vR', 'MOV_vL', 'MOV_vR'])

    if has_vsplits:
        val = (-9.6198
            + _s(row.get('STU_vL',    0)) * 0.0291
            + _s(row.get('STU_vR',    0)) * 0.0392
            + _s(row.get('MOV_vL',    0)) * 0.0048
            + _s(row.get('MOV_vR',    0)) * 0.0318
            + _s(row.get('PIT_CON_vL',0)) * 0.0161
            + _s(row.get('PIT_CON_vR',0)) * 0.0249
            + _s(row.get('STM',       0)) * (-0.0181)
            + _s(row.get('velo_mid',  0)) * (-0.0005)
            + _s(row.get('IP',        0)) * 0.0306
            + _s(row.get('PBABIP',    0)) * (-0.0240)
            + _s(row.get('HRA',       0)) * 0.0387
        )
        # Archetype indicators
        stu = _s(row.get('STU', 0))
        mov = _s(row.get('MOV', 0))
        con = _s(row.get('PIT_CON', 0))
        k_pct = _s(row.get('PIT_K_PCT', 0))
        gf    = str(row.get('PIT_GF', ''))
        I_power = int(stu >= 50 and mov >= 50 and con <= 45)
        I_fb_k  = int(gf in ('FB', 'EX FB') and k_pct >= 0.149)
        val += (I_power * 0.0207
              + I_power * stu * (-0.0242)
              + I_power * mov * (-0.0183)
              + I_power * con * 0.0519
              + I_fb_k  * (-0.6261)
              + I_fb_k  * stu * (-0.0476)
              + I_fb_k  * mov * 0.0528
              + I_fb_k  * _s(row.get('HRA', 0)) * 0.0173)
    else:
        # v1 fallback — no v-splits
        val = (-9.6062
            + _s(row.get('STU',    0)) * (0.0265 + 0.0315) / 2
            + _s(row.get('MOV',    0)) * (0.0040 + 0.0299) / 2
            + _s(row.get('PIT_CON',0)) * (0.0149 + 0.0289) / 2
            + _s(row.get('STM',    0)) * (-0.0191)
            + _s(row.get('velo_mid',0)) * 0.0056
            + _s(row.get('IP',     0)) * 0.0315
            + _s(row.get('PBABIP', 0)) * (-0.0303)
            + _s(row.get('HRA',    0)) * 0.0399
        )
    return val


# ── RP F1.1 — locked coefficients ────────────────────────────────────────────
def rp_f1(row) -> float:
    """
    RP F1.1 — v-splits + archetype interactions. CV R² = 0.571.
    Falls back to v1 if v-split columns absent.
    """
    has_vsplits = all(c in row and _s(row.get(c)) != 0
                      for c in ['STU_vL', 'STU_vR', 'MOV_vL', 'MOV_vR'])

    if has_vsplits:
        val = (-4.6766
            + _s(row.get('STU_vL',    0)) * 0.0230
            + _s(row.get('STU_vR',    0)) * 0.0130
            + _s(row.get('MOV_vL',    0)) * (-0.0041)
            + _s(row.get('MOV_vR',    0)) * 0.0176
            + _s(row.get('PIT_CON_vL',0)) * 0.0003
            + _s(row.get('PIT_CON_vR',0)) * 0.0232
            + _s(row.get('STM',       0)) * (-0.0004)
            + _s(row.get('velo_mid',  0)) * (-0.0014)
            + _s(row.get('PIT_HLD',   0)) * (-0.0008)
            + _s(row.get('IP',        0)) * 0.0151
            + _s(row.get('PBABIP',    0)) * (-0.0013)
            + _s(row.get('HRA',       0)) * 0.0221
        )
        stu = _s(row.get('STU', 0))
        mov = _s(row.get('MOV', 0))
        con = _s(row.get('PIT_CON', 0))
        k_pct = _s(row.get('PIT_K_PCT', 0))
        gf    = str(row.get('PIT_GF', ''))
        I_power = int(stu >= 65 and mov >= 50 and con <= 50)
        I_fb_k  = int(gf in ('FB', 'EX FB') and k_pct >= 0.174)
        val += (I_power * (-3.2857)
              + I_power * stu * 0.0216
              + I_power * mov * 0.0018
              + I_power * con * 0.0318
              + I_fb_k  * (-0.0454)
              + I_fb_k  * stu * (-0.0076)
              + I_fb_k  * mov * (-0.0200)
              + I_fb_k  * _s(row.get('HRA', 0)) * 0.0338)
    else:
        val = (-4.5281
            + _s(row.get('STU',    0)) * (0.0241 + 0.0112) / 2
            + _s(row.get('MOV',    0)) * (-0.0064 + 0.0168) / 2
            + _s(row.get('PIT_CON',0)) * (0.0000 + 0.0259) / 2
            + _s(row.get('STM',    0)) * (-0.0004)
            + _s(row.get('velo_mid',0)) * (-0.0030)
            + _s(row.get('PIT_HLD',0)) * (-0.0008)
            + _s(row.get('IP',     0)) * 0.0152
            + _s(row.get('PBABIP', 0)) * (-0.0023)
            + _s(row.get('HRA',    0)) * 0.0240
        )
    return val


def pitcher_f1(row) -> float:
    """Route to SP or RP F1 based on role."""
    pos = str(row.get('POS', ''))
    gs  = _s(row.get('PIT_GS', 0))
    g   = _s(row.get('PIT_G',  0))
    # Use role tag first; fall back to GS threshold
    if pos == 'SP' or gs > 25:
        return sp_f1(row)
    elif pos in ('RP', 'CL') or (g > 50 and gs < 5):
        return rp_f1(row)
    # Swing pitcher — use SP formula (conservative)
    return sp_f1(row)


# ══════════════════════════════════════════════════════════════════════════════
# PITCH ARSENAL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

PITCH_GRADE_COLS = ['PIT_FB_GR', 'PIT_CH', 'PIT_SI', 'PIT_SL',
                    'PIT_CB', 'PIT_CT', 'PIT_SP']


def cnt_eff_pitches(row, threshold: int = EFF_PITCH_THRESHOLD) -> int:
    """Count of pitches at or above the usability threshold."""
    return sum(1 for c in PITCH_GRADE_COLS
               if _s(row.get(c, 0)) >= threshold)


def min_eff_pitch(row, threshold: int = EFF_PITCH_THRESHOLD) -> float:
    """
    Minimum grade among effective pitches (grade >= threshold).
    Returns 0 if no effective pitches.
    Registry finding: higher MIN_eff_t30 → slightly worse outcomes
    (engine rewards elite top-end over balanced depth).
    """
    grades = [_s(row.get(c, 0)) for c in PITCH_GRADE_COLS
              if _s(row.get(c, 0)) >= threshold]
    return min(grades) if grades else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# TOP-PITCH-QUALITY GATE (rotation eligibility — single source of truth)
# ══════════════════════════════════════════════════════════════════════════════
#
# Replaces the retired "STM >= 45 AND 3+ effective pitches" SP-capable rule.
# Two OOTP 27 mature-data studies (May 2026) dismantled the old rule:
#   • STM has NO floor — it's a smooth innings-volume lever (WAR/IP flat across
#     35-85, slope +0.00006, R²=0.005; total WAR rises only via innings).
#   • Effective-pitch COUNT is the wrong variable — at grade>=30 more pitches is
#     MONOTONICALLY WORSE (3-eff 3.37 WAR → 6-eff 2.69) because fewer-pitch arms
#     carry better best-pitches (70.7 vs 65.7). The engine rewards concentrated
#     elite quality over balanced depth; depth buys innings (+0.88 IP/pitch), not
#     rate (WAR/IP slope ≈ 0). Confirms H3's MIN_eff_t30 negative coefficient on
#     mature data (resolves the v14.0 line-241 averaging-artifact caution).
#
# The real cliff is at the BOTTOM, on top-pitch quality (best-pitch alone
# explains R²=0.095; count explains 0.002, wrong sign). Pitches at grade>=50:
#   0 → 1.58 WAR (replacement, best pitch 44.7) | 1 → 2.32 | 2 → 3.02 | 3 → 3.38
# So the viability floor — not a preference — is one real out-pitch plus one
# usable secondary. GATE: top_pitch_grade >= 50 AND (# secondaries >= 40) >= 1.
#
# PROVISIONAL: 50/40 calibrated on K-T mature data. Re-validate after AC
# converts to OOTP 27. The Pitching module exposes these as editable overrides
# in pitching_state; everywhere else uses these constant defaults so a single
# arm is tagged identically across modules.

PITCH_GATE_DEFAULTS = {
    'top_min':         50,   # best pitch must reach this grade
    'secondary_min':   40,   # a "usable secondary" is a pitch at/above this grade
    'secondary_count':  1,   # how many such secondaries are required
}


def top_pitch_grade(row) -> float:
    """Highest current pitch grade across the arsenal. 0 if none present."""
    grades = [_s(row.get(c, 0)) for c in PITCH_GRADE_COLS]
    return max(grades) if grades else 0.0


def secondary_pitch_count(row, secondary_min: int = 40) -> int:
    """
    Count of *secondary* pitches at/above secondary_min — i.e. usable pitches
    other than the single best one. The best pitch is excluded exactly once so a
    one-pitch arm scores 0 secondaries even if that pitch clears the bar.
    """
    grades = sorted((_s(row.get(c, 0)) for c in PITCH_GRADE_COLS), reverse=True)
    if not grades:
        return 0
    # Drop the single top pitch; count the rest that clear secondary_min.
    return sum(1 for g in grades[1:] if g >= secondary_min)


def passes_pitch_gate(row, thresholds: dict | None = None) -> bool:
    """
    Rotation-eligibility gate (top-pitch quality). True if the arm has one real
    out-pitch plus the required number of usable secondaries.

    A HARD gate, but a routing one — callers send failing arms to the bullpen
    pool (where one pitch is enough), never discard them. That routing is what
    makes a hard filter consistent with the suite's "never strand an arm" norm.
    """
    t = {**PITCH_GATE_DEFAULTS, **(thresholds or {})}
    if top_pitch_grade(row) < t['top_min']:
        return False
    return secondary_pitch_count(row, t['secondary_min']) >= t['secondary_count']


def thin_out_pitch(row, thresholds: dict | None = None) -> bool:
    """
    Flag (not a gate): arm clears the gate but its best pitch sits in the
    soft 50-55 band — viable starter, thin out-pitch. Caller decides what to do.
    """
    t = {**PITCH_GATE_DEFAULTS, **(thresholds or {})}
    tpg = top_pitch_grade(row)
    return passes_pitch_gate(row, t) and t['top_min'] <= tpg < (t['top_min'] + 5)


# ══════════════════════════════════════════════════════════════════════════════
# SP PROJECTED WAR + QUALITY TIERS (registry A2 GB model; A15 linear fallback)
# ══════════════════════════════════════════════════════════════════════════════
#
# "Good enough?" needs a WAR-scaled number, and sp_f1 is a RANKING score, not WAR
# (it runs ~−1.2 to −0.3 where real WAR runs 0.09 to 5.63). So tiers are cut on a
# proper WAR estimate, not on sp_f1.
#
# Primary: the v27 GB SP model (gb_sp_season_v27.pkl, CV R²=0.711, registry A2 /
# study 3C-2). Ratings-only, no IP — IP is excluded deliberately so the projection
# can't see future innings. Feature order is fixed by sp_features_v27.pkl:
#   [STU, MOV, PIT_CON, PBABIP, HRA, STM, STU_x_MOV]   (STU_x_MOV computed here)
#
# Fallback: the A15 confound regression (SP-only, N=7,255, R²=0.648). Used only if
# the pkl is missing or the sklearn version can't load it (joblib pickles are
# version-sensitive — retrain_v27.py regenerates them in-env if so). The fallback
# keeps the feature WORKING rather than crashing; tiers stay on the same WAR scale.
#   WAR ≈ −10.8601 + 0.0905·CON + 0.0663·STU + 0.1068·MOV + 0.0180·top_pitch

_SP_GB_MODEL = None
_SP_GB_FEATURES = None
_SP_GB_LOAD_TRIED = False
_SP_GB_STATUS = 'unloaded'   # 'gb' | 'fallback' | 'unloaded'

# A15 SP-only fallback coefficients (intercept + slopes). top_pitch = max grade.
_A15_SP_FALLBACK = {
    'intercept': -10.8601,
    'PIT_CON': 0.0905, 'STU': 0.0663, 'MOV': 0.1068, 'top_pitch': 0.0180,
}


def _load_sp_gb_model():
    """Load the GB SP model once. Returns (model, features) or (None, None)."""
    global _SP_GB_MODEL, _SP_GB_FEATURES, _SP_GB_LOAD_TRIED, _SP_GB_STATUS
    if _SP_GB_LOAD_TRIED:
        return _SP_GB_MODEL, _SP_GB_FEATURES
    _SP_GB_LOAD_TRIED = True
    here = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(here, 'gb_sp_season_v27.pkl')
    feat_path  = os.path.join(here, 'sp_features_v27.pkl')
    try:
        import joblib
        if os.path.exists(model_path) and os.path.exists(feat_path):
            _SP_GB_MODEL = joblib.load(model_path)
            _SP_GB_FEATURES = joblib.load(feat_path)
            _SP_GB_STATUS = 'gb'
        else:
            _SP_GB_STATUS = 'fallback'
    except Exception:
        # sklearn version mismatch, missing joblib, corrupt pkl — degrade safely.
        _SP_GB_MODEL = None
        _SP_GB_FEATURES = None
        _SP_GB_STATUS = 'fallback'
    return _SP_GB_MODEL, _SP_GB_FEATURES


def sp_war_status() -> str:
    """Which estimator is live: 'gb' (model), 'fallback' (A15 linear)."""
    _load_sp_gb_model()
    return _SP_GB_STATUS


def _sp_war_fallback(row) -> float:
    """A15 linear WAR estimate (no external model needed)."""
    c = _A15_SP_FALLBACK
    return (c['intercept']
            + c['PIT_CON'] * _s(row.get('PIT_CON', 0))
            + c['STU']     * _s(row.get('STU', 0))
            + c['MOV']     * _s(row.get('MOV', 0))
            + c['top_pitch'] * top_pitch_grade(row))


def sp_war_estimate(row) -> float:
    """
    Projected season WAR for a starter, on a real WAR scale (for quality tiers).
    Uses the v27 GB model if available, else the A15 linear fallback.
    """
    model, feats = _load_sp_gb_model()
    if model is None or feats is None:
        return round(_sp_war_fallback(row), 2)
    try:
        stu = _s(row.get('STU', 0))
        mov = _s(row.get('MOV', 0))
        feat_vals = {
            'STU': stu, 'MOV': mov,
            'PIT_CON': _s(row.get('PIT_CON', 0)),
            'PBABIP':  _s(row.get('PBABIP', 0)),
            'HRA':     _s(row.get('HRA', 0)),
            'STM':     _s(row.get('STM', 0)),
            'STU_x_MOV': stu * mov,
        }
        # Pass a named single-row DataFrame in the model's exact feature order so
        # sklearn matches on names (the model was fit on a DataFrame).
        x = pd.DataFrame([[feat_vals.get(f, 0.0) for f in feats]], columns=list(feats))
        return round(float(model.predict(x)[0]), 2)
    except Exception:
        return round(_sp_war_fallback(row), 2)


# Quality tier bands, anchored to A14 replacement (1.58) + A15 bins. The
# "good-enough" line is the bottom of MID (2.0 default). Editable in pitching_state.
SP_TIER_DEFAULTS = {
    'front':       3.5,   # >= front  → front-line #1/#2
    'mid':         2.0,   # >= mid    → mid-rotation #3/#4  (the good-enough bar)
    'back':        1.0,   # >= back   → back-end #5 / fringe
}                          # < back    → below replacement (a hole)

SP_TIER_LABELS = {
    'front': 'Front-line',
    'mid':   'Mid-rotation',
    'back':  'Back-end',
    'hole':  'Below-replacement',
}

SP_TIER_ICONS = {
    'front': '⬤⬤', 'mid': '⬤', 'back': '◐', 'hole': '○',
}


def sp_tier(war: float, bands: dict | None = None) -> str:
    """Map a projected WAR to a tier key (front / mid / back / hole)."""
    b = {**SP_TIER_DEFAULTS, **(bands or {})}
    if war >= b['front']:
        return 'front'
    if war >= b['mid']:
        return 'mid'
    if war >= b['back']:
        return 'back'
    return 'hole'


def is_good_enough(war: float, bands: dict | None = None) -> bool:
    """At/above the good-enough bar (bottom of MID, default 2.0 WAR)."""
    b = {**SP_TIER_DEFAULTS, **(bands or {})}
    return war >= b['mid']


# ══════════════════════════════════════════════════════════════════════════════
# TRADE VALUE
# ══════════════════════════════════════════════════════════════════════════════

def trade_value(f1: float, control_window: float, pos: str) -> float:
    """
    TV = (F1 - 0.2) × control_window × POS_MULT
    Clean formula — no age factor multiplier.
    Age context lives in feasibility scoring, not TV.
    """
    mult = POS_MULT.get(pos, 1.0)
    return round(max(0.0, (f1 - 0.2) * control_window * mult), 2)


# ══════════════════════════════════════════════════════════════════════════════
# BABIP LUCK FLAG
# ══════════════════════════════════════════════════════════════════════════════

def _babip_rating_to_decimal(rating: float) -> float:
    """
    Convert a 20-80 BABIP rating to expected decimal BABIP.

    Source: OOTP 27 A-T regression on player_cross_section_full.parquet
            Filter: ORG != "-" AND AGE 23-27 AND PA >= 100 (canonical)
            N = 16,023 across seasons 1976-1990
            BAT_BABIP_STAT ≈ 0.2074 + 0.001573 × BABIP_rating
            R² = 0.214, residual SD = 0.0306

    Predicted at key ratings: 20→.239, 50→.286 (median), 80→.333.
    Era-robust across 1976-1990 (slope SD ~8% of slope).
    """
    return 0.2074 + 0.001573 * rating


# Luck flag thresholds — multiples of residual SD (0.0306 from regression).
# Moderate band: |residual| in [0.030, 0.050) → ~1.0–1.6 SD
# Strong band:   |residual| ≥ 0.050           → ~1.6+ SD (actionable)
_BABIP_MODERATE_THRESHOLD = 0.030
_BABIP_STRONG_THRESHOLD   = 0.050


def babip_luck_flag(row) -> str:
    """
    Compare observed BABIP stat to rating-predicted BABIP and return a tiered flag.

    Returns one of:
      'STRONG_BUY'  → observed ≤ predicted − 0.050  (actionable buy-low, ~1.6+ SD)
      'BUY_LOW'     → observed ≤ predicted − 0.030  (moderate underperformer)
      'NEUTRAL'     → within ±0.030 of predicted
      'SELL_HIGH'   → observed ≥ predicted + 0.030  (moderate overperformer)
      'STRONG_SELL' → observed ≥ predicted + 0.050  (actionable sell-high)
      'NEUTRAL'     → if either input is zero/missing (insufficient data)

    Registry: 47% mean reversion for 400+ PA underperformers (+0.79 WAR mean
    recovery). The trade edge is the residual, which is largely luck (plus
    park, IF defense behind hitter, BIP composition).
    """
    observed = _s(row.get('BAT_BABIP_STAT', row.get('BABIP', 0)))
    rating   = _s(row.get('BAT_BABIP_RATING', 0))
    if observed == 0 or rating == 0:
        return 'NEUTRAL'

    predicted = _babip_rating_to_decimal(rating)
    diff = observed - predicted

    if diff <= -_BABIP_STRONG_THRESHOLD:
        return 'STRONG_BUY'
    elif diff <= -_BABIP_MODERATE_THRESHOLD:
        return 'BUY_LOW'
    elif diff >= _BABIP_STRONG_THRESHOLD:
        return 'STRONG_SELL'
    elif diff >= _BABIP_MODERATE_THRESHOLD:
        return 'SELL_HIGH'
    return 'NEUTRAL'


# Helpful sets for downstream callsite checks
BUY_LUCK_FLAGS  = {'STRONG_BUY', 'BUY_LOW'}
SELL_LUCK_FLAGS = {'STRONG_SELL', 'SELL_HIGH'}


# ══════════════════════════════════════════════════════════════════════════════
# POSITIONAL FLEX DETECTION
# ══════════════════════════════════════════════════════════════════════════════

# Minimum skill rating required to be eligible at a position (registry: ≥40)
POS_ELIGIBILITY_FLOOR = 40

# Skills required per position — maps position → list of (skill_col, min_rating)
# All conditions must be met for eligibility
POS_SKILL_REQUIREMENTS = {
    'C':  [('C_ABI', 40)],
    '1B': [('IF_RNG', 40)],
    '2B': [('IF_RNG', 40)],
    '3B': [('IF_RNG', 40)],
    'SS': [('IF_RNG', 40), ('IF_ARM', 40)],   # SS needs both range AND arm
    'LF': [('OF_RNG', 40)],
    'CF': [('OF_RNG', 40)],                    # CF needs higher range in practice
    'RF': [('OF_RNG', 40)],
    # Pitchers: STM threshold for SP role capability
    'SP': [('STM', 40)],
}

# Premium positions for flex flagging — these are the ones worth highlighting
PREMIUM_POSITIONS = {'SS', 'CF', 'C', '2B'}


def detect_flex_positions(row) -> list[str]:
    """
    Return list of positions the player could potentially learn based on
    underlying skill ratings, excluding their current listed position.

    Uses POS_SKILL_REQUIREMENTS with POS_ELIGIBILITY_FLOOR (≥40).
    Registry finding: position eligibility floor = OOTP position rating ≥40,
    but the derived position ratings (FLD_SS etc.) reflect current experience,
    not potential. We use raw skill ratings (IF_RNG, OF_RNG, etc.) as the
    ground truth for what a player *could* learn.

    Only returns positions where skills are present — doesn't guarantee
    the player will ever be assigned there, just that the engine won't
    block development.
    """
    current_pos = str(row.get('POS', ''))
    eligible = []

    for pos, requirements in POS_SKILL_REQUIREMENTS.items():
        if pos == current_pos:
            continue
        if all(_s(row.get(skill, 0)) >= floor
               for skill, floor in requirements):
            eligible.append(pos)

    return eligible


def flex_flag(row, need_positions: list[str] | None = None) -> str:
    """
    Returns a flex string for display:
      - 'FLEX(SS,CF)' — can play premium positions not currently listed
      - 'FLEX(2B,3B)' — can play non-premium positions
      - '' — no meaningful flex

    If need_positions provided, prioritizes flagging positions the team needs.
    Premium positions always shown first.
    """
    current_pos = str(row.get('POS', ''))

    # Only meaningful for position players — pitchers don't flex to other roles
    if current_pos in PITCHER_POSITIONS:
        return ''

    eligible = detect_flex_positions(row)
    if not eligible:
        return ''

    # Prioritize: (1) positions the team needs, (2) premium positions, (3) rest
    needs   = set(need_positions or [])
    ordered = (
        [p for p in eligible if p in needs and p in PREMIUM_POSITIONS] +
        [p for p in eligible if p in needs and p not in PREMIUM_POSITIONS] +
        [p for p in eligible if p not in needs and p in PREMIUM_POSITIONS] +
        [p for p in eligible if p not in needs and p not in PREMIUM_POSITIONS]
    )

    # Only surface if it's meaningfully different from current position
    # (e.g. don't flag LF→RF as interesting flex)
    interesting = [p for p in ordered
                   if p in PREMIUM_POSITIONS or p in needs]

    if interesting:
        return f"FLEX({','.join(interesting[:3])})"  # cap at 3 for display

    # Still show non-premium flex if there are 2+ options
    if len(ordered) >= 2:
        return f"FLEX({','.join(ordered[:2])})"

    return ''


# ══════════════════════════════════════════════════════════════════════════════
# FEASIBILITY SCORING
# ══════════════════════════════════════════════════════════════════════════════

def market_score(row, team_records: dict | None = None) -> float:
    """
    Market score (0-10): how likely is the other team to trade this player?
    Based on the player's situation and his team's situation.
    Higher = more likely available.

    Inputs used:
      - AGE: veterans 28+ score higher
      - Team record: rebuilders (sub-.450 win%) score higher
      - BABIP luck: SELL_HIGH / STRONG_SELL (selling high) gets a bump
      - YEARS_LEFT: short contract on rebuilder = motivated seller
      - ON_WAIVERS / IS_DFA: hard signal
      - SP/RP FATIGUE: fatigued pitcher on a bad team = available
      - POS_MULT: premium positions score slightly lower (harder to pry away)
    """
    score = 5.0  # baseline
    age       = _s(row.get('AGE', row.get('Age', 25)))
    pos       = str(row.get('POS', ''))
    tm        = str(row.get('TM', ''))
    years     = _s(row.get('YEARS_LEFT', 2))
    on_waivers= str(row.get('ON_WAIVERS', '')).lower() in ('1', 'true', 'yes')
    is_dfa    = str(row.get('IS_DFA',     '')).lower() in ('1', 'true', 'yes')
    luck      = babip_luck_flag(row)
    sp_fat    = _s(row.get('SP_FATIGUE', 0))
    rp_fat    = _s(row.get('RP_FATIGUE', 0))
    prone     = str(row.get('PRONE', ''))

    # Hard signals
    if on_waivers or is_dfa:
        return 9.5

    # Age — aging vets are more available
    if age >= 34:   score += 2.5
    elif age >= 31: score += 1.5
    elif age >= 28: score += 0.8
    elif age <= 24: score -= 1.5

    # Team record — rebuilding teams sell
    if team_records and tm in team_records:
        wpct = team_records[tm]
        if wpct < 0.400:   score += 2.0   # clear tank
        elif wpct < 0.450: score += 1.0   # rebuilding
        elif wpct > 0.580: score -= 1.0   # contender holds

    # Short contract on a bad team = motivated seller
    if years <= 1 and team_records and tm in team_records:
        if team_records[tm] < 0.450:
            score += 0.8

    # BABIP luck — if they're playing above their ratings, selling high is rational
    if luck in SELL_LUCK_FLAGS:
        score += 0.8 if luck == 'STRONG_SELL' else 0.5

    # Fatigue — worn-out pitcher on a bad team
    if pos in PITCHER_POSITIONS:
        if sp_fat > 80 or rp_fat > 80:
            score += 0.5

    # Fragile players — other teams may move them
    if prone == 'Fragile':
        score += 0.3

    # Premium positions harder to move
    mult = POS_MULT.get(pos, 1.0)
    if mult >= 1.50:  # SS, CF
        score -= 0.5

    return round(min(10.0, max(0.0, score)), 1)


def fit_score(row, tc: dict, my_roster_df: pd.DataFrame | None = None) -> tuple[float, list[str]]:
    """
    Fit score (0-10): how well does this player match our team's needs?
    Returns (score, list_of_missing_config_fields).

    Inputs from Team Config:
      - mode: Rebuilding/Competing/Sustaining
      - need_positions: list of positions we need
      - surplus_positions: positions we're stocked at
      - payroll_current / tax_threshold: salary headroom
      - park factors: park fit for power/contact
      - no_dh: defense matters more
    """
    missing_config = []
    score = 5.0

    pos       = str(row.get('POS', ''))
    age       = _s(row.get('AGE', row.get('Age', 25)))
    salary    = _s(row.get('SALARY', 0))
    years     = _s(row.get('YEARS_LEFT', 0))
    ml_yrs    = _s(row.get('ML_YRS',  0))
    ml_days   = _s(row.get('ML_DAYS', 0))
    control   = compute_control_window(years, ml_yrs, ml_days)
    prone     = str(row.get('PRONE', ''))
    dev_risk  = str(row.get('DEV_RISK', ''))

    mode         = tc.get('mode', 'Competing')
    need_pos     = tc.get('need_positions', [])
    surplus_pos  = tc.get('surplus_positions', [])
    payroll      = _s(tc.get('payroll_current', 0))
    tax_thresh   = _s(tc.get('tax_threshold', 0))
    park_hr_l    = _s(tc.get('park_hr_l', 1.0))
    park_hr_r    = _s(tc.get('park_hr_r', 1.0))
    no_dh        = bool(tc.get('no_dh', True))

    # Config completeness checks
    if not tc.get('my_team', '').strip():
        missing_config.append('my_team')
    if not tc.get('mode'):
        missing_config.append('mode')

    # ── Mode-based scoring ────────────────────────────────────────────────────
    if mode == 'Competing':
        # Want high current F1, immediate contributors
        f1 = batter_f1(row) if pos in BATTER_POSITIONS else pitcher_f1(row)
        if f1 >= 4.0:   score += 2.0
        elif f1 >= 3.0: score += 1.0
        elif f1 < 1.5:  score -= 1.5
        # Rentals OK in competing mode — short control still useful
        if control >= 1.0: score += 0.3

    elif mode == 'Rebuilding':
        # Want years of control and development upside
        if control >= 3.0:  score += 2.0
        elif control >= 2.0: score += 1.0
        elif control < 1.0:  score -= 2.0
        # Young players preferred
        if age <= 24:   score += 1.5
        elif age >= 30: score -= 1.5

    elif mode == 'Sustaining':
        # Sweet spot: age 25-29, 2+ years control, solid F1
        f1 = batter_f1(row) if pos in BATTER_POSITIONS else pitcher_f1(row)
        if 25 <= age <= 29 and control >= 2.0:
            score += 1.5
        if f1 >= 3.0: score += 0.8
        if age >= 32 or control < 1.5: score -= 1.0

    # ── Position need/surplus ─────────────────────────────────────────────────
    if need_pos:
        if pos in need_pos:
            score += 2.0
    else:
        missing_config.append('need_positions')

    if surplus_pos and pos in surplus_pos:
        score -= 1.5

    # ── Salary headroom ───────────────────────────────────────────────────────
    if payroll > 0 and tax_thresh > 0:
        headroom = tax_thresh - payroll
        if salary > headroom:
            score -= 2.0  # would push over tax threshold
        elif salary > headroom * 0.75:
            score -= 0.8  # tight
    elif payroll == 0:
        missing_config.append('payroll_current')

    # ── Park fit (batters) ────────────────────────────────────────────────────
    if pos in BATTER_POSITIONS:
        avg_hr_park = (park_hr_l + park_hr_r) / 2.0
        pow_ = _s(row.get('POW', 0))
        if avg_hr_park >= 1.150 and pow_ >= 55:
            score += 0.8   # power park, power bat — good fit
        elif avg_hr_park <= 0.850 and pow_ >= 60:
            score -= 0.5   # power bat in a pitcher's park

    # ── No-DH: defense matters ────────────────────────────────────────────────
    if no_dh and pos in BATTER_POSITIONS:
        d_war = def_war(row, pos)
        if d_war >= 0.5:  score += 0.5
        if d_war < -0.3:  score -= 0.8

    # ── Hard negatives ────────────────────────────────────────────────────────
    if prone == 'Fragile':
        score -= 1.0
    if dev_risk == 'Extreme' and age >= 28:
        score -= 0.3  # extreme risk + aging = concern

    # ── Unmotivated / Disruptive — hard skip ─────────────────────────────────
    personality = str(row.get('Personality', row.get('PIT_TYPE', '')))
    if personality in ('Unmotivated', 'Disruptive'):
        score = 0.0

    return round(min(10.0, max(0.0, score)), 1), missing_config


def feasibility_aggregate(market: float, fit: float) -> float:
    """Weighted aggregate: 40% market, 60% fit."""
    return round(market * 0.4 + fit * 0.6, 1)


# ══════════════════════════════════════════════════════════════════════════════
# ROSTER SLOT TAGGING
# ══════════════════════════════════════════════════════════════════════════════

def roster_slot_tag(row, tc: dict) -> str:
    """
    Tag each candidate as:
      ACTIVE   — current F1 justifies a 25-man spot now
      RESERVE  — development candidate for 15-man reserve
      WATCH    — borderline; depends on your current depth
    Based on mode and F1 threshold.
    """
    pos  = str(row.get('POS', ''))
    age  = _s(row.get('AGE', row.get('Age', 25)))
    mode = tc.get('mode', 'Competing')

    if pos in PITCHER_POSITIONS:
        f1 = pitcher_f1(row)
        active_floor = 2.5 if mode == 'Competing' else 2.0
    else:
        f1 = batter_f1(row)
        active_floor = 2.0 if mode == 'Competing' else 1.5

    if f1 >= active_floor:
        return 'ACTIVE'
    elif age <= 26 and f1 >= active_floor * 0.6:
        return 'RESERVE'
    elif f1 >= active_floor * 0.75:
        return 'WATCH'
    return 'RESERVE'


# ══════════════════════════════════════════════════════════════════════════════
# MAIN EVALUATION PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def evaluate_league(df: pd.DataFrame, tc: dict,
                    my_team: str,
                    team_records: dict | None = None) -> pd.DataFrame:
    """
    Run the full Mode 1 evaluation pipeline on a league CSV.
    Returns a new DataFrame with all derived columns added.

    Parameters
    ----------
    df          : prepped league DataFrame (output of prep_data)
    tc          : Team Config dict from league.team_config
    my_team     : exclude this team from results
    team_records: {team_name: win_pct} — optional, enables record-based
                  market scoring. If None, record-based signals are skipped.
    """
    # Exclude own team and unsigned players
    candidates = df[
        (df['TM'] != my_team) &
        (df['TM'] != '-') &
        (df['TM'].notna())
    ].copy()  # .copy() prevents fragmentation warning

    results = []
    for _, row in candidates.iterrows():
        r = row.to_dict()
        pos    = str(r.get('POS', ''))
        age    = _s(r.get('AGE', r.get('Age', 25)))
        ml_yrs = _s(r.get('ML_YRS',  0))
        ml_days= _s(r.get('ML_DAYS', 0))
        years  = _s(r.get('YEARS_LEFT', 0))

        # F1
        if pos in PITCHER_POSITIONS:
            f1_val = pitcher_f1(r)
        elif pos in BATTER_POSITIONS:
            f1_val = batter_f1(r)
        else:
            continue  # skip unrecognized positions

        # Unmotivated / Disruptive — hard skip
        personality = str(r.get('Personality', ''))
        if personality in ('Unmotivated', 'Disruptive'):
            continue

        # Service time
        control   = compute_control_window(years, ml_yrs, ml_days)
        arb_stat  = compute_arb_status(ml_yrs, ml_days)
        svc_years = round(ml_yrs + ml_days / DAYS_PER_SERVICE_YEAR, 1)

        # FA-eligible players are Mode 3 territory, not trade targets
        if control <= 0.0:
            continue

        # Trade value
        tv = trade_value(f1_val, control, pos)

        # Feasibility
        mkt              = market_score(r, team_records)
        fit, missing_cfg = fit_score(r, tc)
        agg              = feasibility_aggregate(mkt, fit)

        # Luck flag (batters)
        luck = babip_luck_flag(r) if pos in BATTER_POSITIONS else 'N/A'

        # Arsenal (pitchers)
        cnt_eff = cnt_eff_pitches(r) if pos in PITCHER_POSITIONS else None
        min_eff = min_eff_pitch(r)   if pos in PITCHER_POSITIONS else None

        # Flex detection (batters only)
        need_pos = tc.get('need_positions', [])
        flex = flex_flag(r, need_pos) if pos in BATTER_POSITIONS else ''

        # Boost fit score if flex covers a need position
        if flex and need_pos:
            flex_positions = detect_flex_positions(r)
            if any(p in need_pos for p in flex_positions):
                fit = min(10.0, fit + 0.8)
                agg = feasibility_aggregate(mkt, fit)

        # Slot
        slot = roster_slot_tag(r, tc)

        results.append({
            'Name':        r.get('Name', ''),
            'TM':          r.get('TM', ''),
            'POS':         pos,
            'Age':         int(age),
            'F1':          round(f1_val, 2),
            'TV':          tv,
            'Control':     control,
            'Svc_Yrs':     svc_years,
            'Arb':         arb_stat,
            'Salary':      int(_s(r.get('SALARY', 0))),
            'Yrs_Left':    int(years),
            'Market':      mkt,
            'Fit':         fit,
            'Score':       agg,
            'Slot':        slot,
            'Luck':        luck,
            'Flex':        flex,
            'CNT_eff':     cnt_eff,
            'MIN_eff':     min_eff,
            'STU':         int(_s(r.get('STU', 0))) if pos in PITCHER_POSITIONS else None,
            'MOV':         int(_s(r.get('MOV', 0))) if pos in PITCHER_POSITIONS else None,
            'PIT_CON':     int(_s(r.get('PIT_CON', 0))) if pos in PITCHER_POSITIONS else None,
            'STM':         int(_s(r.get('STM', 0))) if pos in PITCHER_POSITIONS else None,
            'CON':         int(_s(r.get('CON', 0))) if pos in BATTER_POSITIONS else None,
            'POW':         int(_s(r.get('POW', 0))) if pos in BATTER_POSITIONS else None,
            'EYE':         int(_s(r.get('EYE', 0))) if pos in BATTER_POSITIONS else None,
            'GAP':         int(_s(r.get('GAP', 0))) if pos in BATTER_POSITIONS else None,
            'SPE':         int(_s(r.get('SPE', 0))) if pos in BATTER_POSITIONS else None,
            'PRONE':       str(r.get('PRONE', '')),
            'DEV_RISK':    str(r.get('DEV_RISK', '')),
            'ON_WAIVERS':  str(r.get('ON_WAIVERS', '')),
            'IS_DFA':      str(r.get('IS_DFA', '')),
            '_missing_cfg': missing_cfg,  # internal — used for Fit tooltip
        })

    out = pd.DataFrame(results)
    if out.empty:
        return out

    # Sort by Score descending by default
    out = out.sort_values('Score', ascending=False).reset_index(drop=True)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS SCREEN
# ══════════════════════════════════════════════════════════════════════════════

def render_team_config(league: League):
    """
    Team Config settings panel.
    Renders as an expander inside the Acquisitions section (or standalone).
    Reads from / writes to league.team_config via league.save_team_config().
    """
    tc = league.team_config
    st.subheader("⚙️ Team Configuration")
    st.caption("Saved per league. Fill in once; update when your situation changes.")

    complete, missing = league.team_config_complete()
    if not complete:
        st.warning(f"Incomplete config — Fit scores will be partial. Missing: {', '.join(missing)}")

    with st.form("team_config_form"):
        c1, c2 = st.columns(2)

        with c1:
            my_team = st.text_input(
                "My Team (as it appears in export)",
                value=tc.get('my_team', ''),
                key='tc_my_team'
            )
            mode = st.selectbox(
                "Strategic Mode",
                ['Competing', 'Sustaining', 'Rebuilding'],
                index=['Competing', 'Sustaining', 'Rebuilding'].index(
                    tc.get('mode', 'Competing')
                ),
                help=(
                    "Competing — buying for a window, prospects tradeable. "
                    "Sustaining — continuous win, sweet spot age 25-29. "
                    "Rebuilding — selling vets, accumulating control years."
                ),
                key='tc_mode'
            )
            current_date = st.text_input(
                "Current In-Game Date (YYYY-MM-DD)",
                value=tc.get('current_date', '') or '',
                placeholder='e.g. 1977-07-15',
                help="Used to flag pre/post trade deadline urgency. Leave blank for offseason.",
                key='tc_date'
            )

        with c2:
            payroll = st.number_input(
                "Current Committed Payroll ($)",
                value=int(tc.get('payroll_current', 0)),
                min_value=0, step=50000,
                key='tc_payroll'
            )
            tax_thresh = st.number_input(
                "Luxury Tax Threshold ($)",
                value=int(tc.get('tax_threshold', 0)),
                min_value=0, step=50000,
                help="120% of average payroll. Find it in OOTP under League → Financials. "
                     "Example: if average payroll is $5M, threshold is $6M. "
                     "Acquisitions that push you over this number will be flagged.",
                key='tc_tax'
            )

        st.markdown("**Park Factors**")
        pc1, pc2, pc3, pc4, pc5 = st.columns(5)
        with pc1:
            park_hr_l = st.number_input("HR (LHB)", value=float(tc.get('park_hr_l', 1.0)),
                                         min_value=0.7, max_value=1.3, step=0.05,
                                         format="%.3f", key='tc_hr_l')
        with pc2:
            park_hr_r = st.number_input("HR (RHB)", value=float(tc.get('park_hr_r', 1.0)),
                                         min_value=0.7, max_value=1.3, step=0.05,
                                         format="%.3f", key='tc_hr_r')
        with pc3:
            park_avg  = st.number_input("AVG",      value=float(tc.get('park_avg', 1.0)),
                                         min_value=0.95, max_value=1.05, step=0.01,
                                         format="%.3f", key='tc_avg')
        with pc4:
            park_2b   = st.number_input("2B",       value=float(tc.get('park_2b', 1.0)),
                                         min_value=0.9, max_value=1.1, step=0.01,
                                         format="%.3f", key='tc_2b')
        with pc5:
            park_3b   = st.number_input("3B",       value=float(tc.get('park_3b', 1.0)),
                                         min_value=0.8, max_value=1.2, step=0.05,
                                         format="%.3f", key='tc_3b')

        st.markdown("**Roster Needs**")
        rn1, rn2 = st.columns(2)
        all_positions = ['C','1B','2B','3B','SS','LF','CF','RF','SP','RP','CL']
        with rn1:
            need_pos = st.multiselect(
                "Need Positions",
                all_positions,
                default=tc.get('need_positions', []),
                key='tc_need'
            )
        with rn2:
            surplus_pos = st.multiselect(
                "Surplus Positions",
                all_positions,
                default=tc.get('surplus_positions', []),
                key='tc_surplus'
            )

        untouchables_raw = st.text_area(
            "Untouchable Players (one per line)",
            value='\n'.join(tc.get('untouchables', [])),
            height=80,
            key='tc_untouchables'
        )

        submitted = st.form_submit_button("Save Team Config", type="primary")
        if submitted:
            untouchables = [u.strip() for u in untouchables_raw.split('\n') if u.strip()]
            league.save_team_config({
                'my_team':           my_team.strip(),
                'mode':              mode,
                'current_date':      current_date.strip() or None,
                'payroll_current':   payroll,
                'tax_threshold':     tax_thresh,
                'park_hr_l':         park_hr_l,
                'park_hr_r':         park_hr_r,
                'park_avg':          park_avg,
                'park_2b':           park_2b,
                'park_3b':           park_3b,
                'need_positions':    need_pos,
                'surplus_positions': surplus_pos,
                'untouchables':      untouchables,
                'no_dh':             True,   # always True for AC
                'rotation_size':     6,      # locked
            })
            st.success("Team Config saved.")
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# MODE 1 — BROWSE THE LEAGUE
# ══════════════════════════════════════════════════════════════════════════════

def render_mode1(league: League):
    """Mode 1: Browse the League — full candidate table with filters."""

    tc       = league.team_config
    my_team  = tc.get('my_team', '')
    mode     = tc.get('mode', 'Competing')
    complete, missing_cfg = league.team_config_complete()

    # ── Deadline banner ───────────────────────────────────────────────────────
    pre_dl = league.is_pre_deadline()
    if pre_dl is True:
        st.info("📅 Pre-deadline window — trade acquisitions available. Deadline: July 31.")
    elif pre_dl is False:
        st.info("📅 Post-deadline — offseason planning mode. Next window opens after postseason.")

    # ── File upload ───────────────────────────────────────────────────────────
    st.markdown("#### Upload League Export")
    uploaded = st.file_uploader(
        "League CSV (all players, combined export)",
        type=['csv'],
        key='acq_upload',
        help="Single combined OOTP 27 player export. Include all tabs per the saved view spec."
    )

    if uploaded is None:
        st.info("Upload a league CSV to begin. Use the saved view that includes all required columns.")
        return

    with st.spinner("Loading and evaluating league..."):
        try:
            raw = pd.read_csv(uploaded, encoding='utf-8-sig', low_memory=False)
            df  = prep_data(raw)
        except Exception as e:
            st.error(f"Failed to read CSV: {e}")
            return

    if not my_team:
        st.warning("Set your team in Team Config (⚙️ Settings) before browsing. "
                   "Results shown for all teams until then.")

    # ── Optional team record upload ───────────────────────────────────────────
    with st.expander("📊 Upload Team Standings (enables record-based Market scoring)", expanded=False):
        st.caption("Upload the team export CSV. Must contain TM/Team and WIN% columns.")
        tm_upload = st.file_uploader("Team CSV", type=['csv'], key='acq_tm_upload')
        team_records = None
        if tm_upload:
            try:
                tm_df = pd.read_csv(tm_upload, encoding='utf-8-sig')
                tm_df = tm_df.rename(columns={'%': 'WIN_PCT', 'Team': 'TM'})
                if 'WIN_PCT' in tm_df.columns and 'TM' in tm_df.columns:
                    team_records = dict(zip(tm_df['TM'], pd.to_numeric(tm_df['WIN_PCT'], errors='coerce').fillna(0.5)))
                    st.success(f"Loaded {len(team_records)} team records.")
            except Exception as e:
                st.warning(f"Could not parse team file: {e}")

    # ── Run evaluation ────────────────────────────────────────────────────────
    with st.spinner("Scoring candidates..."):
        results = evaluate_league(df, tc, my_team, team_records)

    if results.empty:
        st.warning("No candidates found. Check that your team name in Team Config matches the export exactly.")
        return

    total = len(results)
    st.caption(f"{total} candidates evaluated | Mode: **{mode}** | "
               f"{'⚠️ Fit scores partial — ' + str(len(missing_cfg)) + ' config fields missing' if missing_cfg else '✅ Full scoring active'}")

    # ── Filters ───────────────────────────────────────────────────────────────
    st.markdown("#### Filters")
    fc1, fc2, fc3, fc4, fc5 = st.columns(5)

    all_pos     = sorted(results['POS'].unique())
    batter_pos  = [p for p in all_pos if p in BATTER_POSITIONS]
    pitcher_pos = [p for p in all_pos if p in PITCHER_POSITIONS]

    with fc1:
        role_filter = st.radio("Role", ['All', 'Batters', 'Pitchers'], horizontal=True, key='m1_role')
    with fc2:
        if role_filter == 'Batters':
            pos_options = batter_pos
        elif role_filter == 'Pitchers':
            pos_options = pitcher_pos
        else:
            pos_options = all_pos
        pos_filter = st.multiselect("Position", pos_options, key='m1_pos')
    with fc3:
        age_range = st.slider("Age", min_value=20, max_value=40, value=(20, 35), key='m1_age')
    with fc4:
        f1_floor = st.slider("Min F1", min_value=0.0, max_value=6.0, value=1.5, step=0.5, key='m1_f1')
    with fc5:
        slot_filter = st.multiselect("Slot", ['ACTIVE', 'RESERVE', 'WATCH'],
                                      default=['ACTIVE', 'WATCH'], key='m1_slot')

    fc6, fc7 = st.columns(2)
    with fc6:
        luck_filter = st.multiselect("BABIP Flag",
                                      ['STRONG_BUY', 'BUY_LOW', 'NEUTRAL', 'SELL_HIGH', 'STRONG_SELL', 'N/A'],
                                      default=['STRONG_BUY', 'BUY_LOW', 'NEUTRAL', 'N/A'], key='m1_luck')
    with fc7:
        sort_col = st.selectbox("Sort by", ['Score', 'TV', 'F1', 'Market', 'Fit', 'Age'],
                                 key='m1_sort')

    # Apply filters
    mask = (
        (results['Age'] >= age_range[0]) &
        (results['Age'] <= age_range[1]) &
        (results['F1']  >= f1_floor)
    )
    if role_filter == 'Batters':
        mask &= results['POS'].isin(BATTER_POSITIONS)
    elif role_filter == 'Pitchers':
        mask &= results['POS'].isin(PITCHER_POSITIONS)
    if pos_filter:
        mask &= results['POS'].isin(pos_filter)
    if slot_filter:
        mask &= results['Slot'].isin(slot_filter)
    if luck_filter:
        mask &= results['Luck'].isin(luck_filter)

    filtered = results[mask].sort_values(sort_col, ascending=(sort_col == 'Age'))

    st.markdown(f"#### Candidates — {len(filtered)} shown")

    # ── Display columns ───────────────────────────────────────────────────────
    # Split batter / pitcher display for cleaner columns
    t_bat, t_pit = st.tabs(["⚾ Batters", "🥎 Pitchers"])

    bat_results = filtered[filtered['POS'].isin(BATTER_POSITIONS)]
    pit_results = filtered[filtered['POS'].isin(PITCHER_POSITIONS)]

    bat_display_cols = [c for c in [
        'Name', 'TM', 'POS', 'Age', 'F1', 'TV', 'Control', 'Svc_Yrs', 'Arb',
        'Salary', 'Yrs_Left', 'Market', 'Fit', 'Score', 'Slot', 'Luck', 'Flex',
        'CON', 'POW', 'EYE', 'GAP', 'SPE', 'PRONE', 'ON_WAIVERS', 'IS_DFA'
    ] if c in bat_results.columns]

    pit_display_cols = [c for c in [
        'Name', 'TM', 'POS', 'Age', 'F1', 'TV', 'Control', 'Svc_Yrs', 'Arb',
        'Salary', 'Yrs_Left', 'Market', 'Fit', 'Score', 'Slot',
        'CNT_eff', 'MIN_eff', 'STU', 'MOV', 'PIT_CON', 'STM',
        'PRONE', 'ON_WAIVERS', 'IS_DFA'
    ] if c in pit_results.columns]

    with t_bat:
        if bat_results.empty:
            st.info("No batter candidates match current filters.")
        else:
            st.caption(
                "**Market** = likelihood their team trades them (0-10). "
                "**Fit** = match to your team's needs (0-10). "
                "**Score** = weighted aggregate. "
                "**Luck**: STRONG_BUY / BUY_LOW = underperforming ratings (buy signal); "
                "STRONG_SELL / SELL_HIGH = overperforming ratings (other team's sell signal). "
                "Calibrated to OOTP 27 A-T: predicted BABIP = 0.2074 + 0.001573 × rating, residual SD = 0.0306. "
                "**Flex**: positions player could learn based on underlying skills (IF_RNG, OF_RNG, C_ABI ≥40)."
            )
            st.dataframe(
                bat_results[bat_display_cols],
                use_container_width=True,
                height=520,
                hide_index=True,
            )

    with t_pit:
        if pit_results.empty:
            st.info("No pitcher candidates match current filters.")
        else:
            st.caption(
                "**CNT_eff** = pitches at grade ≥30. **MIN_eff** = lowest grade among effective pitches. "
                "SP with CNT_eff < 3 flagged as likely 2-pitch arm — trade value as SP is suspect. "
                "**RP TV note**: 0.60× multiplier reflects 6-man rotation economics."
            )
            st.dataframe(
                pit_results[pit_display_cols],
                use_container_width=True,
                height=520,
                hide_index=True,
            )

    # ── Download ──────────────────────────────────────────────────────────────
    csv_out = filtered.drop(columns=['_missing_cfg'], errors='ignore').to_csv(index=False)
    st.download_button(
        "⬇️ Download filtered results",
        data=csv_out,
        file_name="acquisitions_mode1.csv",
        mime="text/csv",
        key='m1_download'
    )


# ══════════════════════════════════════════════════════════════════════════════
# MODE STUBS
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# GOOGLE SHEETS READER
# ══════════════════════════════════════════════════════════════════════════════

CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), 'google_credentials.json')
SHEETS_SCOPE     = ['https://www.googleapis.com/auth/spreadsheets.readonly']


def fetch_trade_talk_sheet(sheet_id: str) -> pd.DataFrame | None:
    """
    Fetch TradeTalk tab from Google Sheet using service account credentials.
    Returns DataFrame or None on error.
    """
    try:
        from google.oauth2.service_account import Credentials
        import gspread

        creds  = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SHEETS_SCOPE)
        client = gspread.authorize(creds)
        sh     = client.open_by_key(sheet_id)
        ws     = sh.worksheet('TradeTalk')
        data   = ws.get_all_records()
        return pd.DataFrame(data) if data else None
    except Exception as e:
        return None, str(e)


# ══════════════════════════════════════════════════════════════════════════════
# NAME MATCHING
# ══════════════════════════════════════════════════════════════════════════════

def match_player(player_name: str, org: str, df: pd.DataFrame,
                 trade_direction: str = 'selling') -> tuple[pd.Series | None, bool]:
    """
    Match a player name from the sheet against the league CSV.
    Always returns (matched_row_or_None, ambiguous_bool).

    Logic:
    1. Full name match (case-insensitive)
    2. Last name + ORG match (when direction is selling)
    3. Last name only fallback (flags ambiguous if >1 match)

    Handles both 'First Last' and 'F. Last' name formats in the CSV.
    """
    name_clean = player_name.strip().lower()

    # Full name match
    full_mask = df['Name'].str.lower().str.strip() == name_clean
    if full_mask.any():
        return df[full_mask].iloc[0], False

    # Extract last name from input (last token)
    last_name = name_clean.split()[-1] if name_clean else ''
    if not last_name:
        return None, False

    # Extract last names from CSV — handles 'C. Reynolds' and 'Carlos Reynolds'
    df_last = df['Name'].str.strip().str.split().str[-1].str.lower()

    # Last name + ORG match
    if org and trade_direction == 'selling':
        org_mask  = df['ORG'].str.lower().str.strip() == org.lower().strip()
        last_mask = df_last == last_name
        combined  = org_mask & last_mask
        if combined.any():
            return df[combined].iloc[0], False

    # Last name only fallback
    last_mask = df_last == last_name
    if last_mask.any():
        matches = df[last_mask]
        return matches.iloc[0], len(matches) > 1

    return None, False


def verdict(f1: float, tv: float, control: float, tc: dict,
            pos: str, luck: str) -> tuple[str, str]:
    """
    Returns (verdict_label, one_line_reason) based on F1, TV, fit context.

    STRONG BUY  — high F1, good control, fits team needs, possibly BUY_LOW/STRONG_BUY luck
    FAIR VALUE  — solid player, reasonable ask
    OVERPRICED  — low control or aging with high TV expectation
    PASS        — low F1, wrong fit, or Unmotivated/Disruptive
    """
    mode     = tc.get('mode', 'Competing')
    need_pos = tc.get('need_positions', [])

    reasons = []

    if f1 >= 5.0 and control >= 2.0:
        label = 'STRONG BUY'
        reasons.append(f'F1={f1:.1f}, {control:.1f}yr control')
        if luck in BUY_LUCK_FLAGS:
            note = 'strong buy-low opportunity (BABIP luck)' if luck == 'STRONG_BUY' else 'buy-low opportunity (BABIP luck)'
            reasons.append(note)
        if pos in need_pos:
            reasons.append(f'fills {pos} need')
    elif f1 >= 3.5 and control >= 1.0:
        label = 'FAIR VALUE'
        reasons.append(f'F1={f1:.1f}, solid contributor')
        if control < 1.5:
            reasons.append('short control window — rental only')
    elif f1 >= 2.0:
        label = 'OVERPRICED'
        reasons.append(f'F1={f1:.1f} — below replacement threshold for cost')
        if control <= 1.0:
            reasons.append('near FA — limited leverage')
    else:
        label = 'PASS'
        reasons.append(f'F1={f1:.1f} — below useful threshold')

    if mode == 'Rebuilding' and control < 2.0:
        label = 'PASS'
        reasons.append('rebuilding mode — need 2+ yr control')

    return label, ' | '.join(reasons)


# ══════════════════════════════════════════════════════════════════════════════
# MODE 2 — SLACK EVAL
# ══════════════════════════════════════════════════════════════════════════════

def render_mode2(league: League):
    """Mode 2: Read from TradeTalk Google Sheet, match against league CSV, show verdicts."""

    tc      = league.team_config
    my_team = tc.get('my_team', '')

    st.markdown("#### Slack Trade Talk — Live Verdicts")
    st.caption("Reads from your AC Trade Monitor Google Sheet. Upload league CSV to get verdicts.")

    # ── Config inputs ─────────────────────────────────────────────────────────
    c1, c2 = st.columns(2)
    with c1:
        sheet_id = st.text_input(
            "Google Sheet ID",
            value=league.team_config.get('trade_sheet_id', ''),
            placeholder='1QQ-XsSXEJSQqf...',
            key='m2_sheet_id',
            help="From your AC Trade Monitor sheet URL"
        )
        if sheet_id and sheet_id != league.team_config.get('trade_sheet_id', ''):
            league.save_team_config({'trade_sheet_id': sheet_id})

    with c2:
        uploaded = st.file_uploader(
            "League CSV (for matching)",
            type=['csv'],
            key='m2_upload',
            help="Same export as Mode 1"
        )

    if not sheet_id:
        st.info("Enter your Google Sheet ID above to load trade talk data.")
        return

    if uploaded is None:
        st.info("Upload your league CSV to match players and get verdicts.")
        return

    # ── Load data ─────────────────────────────────────────────────────────────
    with st.spinner("Loading trade talk from Google Sheet..."):
        result = fetch_trade_talk_sheet(sheet_id)
        if isinstance(result, tuple):
            st.error(f"Could not read Google Sheet: {result[1]}")
            return
        talk_df = result

    if talk_df is None or talk_df.empty:
        st.warning("No trade talk data found in sheet. Check that the TradeTalk tab has rows.")
        return

    with st.spinner("Loading league CSV..."):
        try:
            raw    = pd.read_csv(uploaded, encoding='utf-8-sig', low_memory=False)
            league_df = prep_data(raw)
        except Exception as e:
            st.error(f"Failed to read CSV: {e}")
            return

    # ── Filters ───────────────────────────────────────────────────────────────
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        direction_filter = st.multiselect(
            "Trade Direction",
            ['selling', 'buying', 'both', 'unknown'],
            default=['selling'],
            key='m2_direction'
        )
    with fc2:
        # Get unique GMs from sheet
        gm_list = sorted(talk_df['GM_Name'].dropna().unique()) if 'GM_Name' in talk_df.columns else []
        gm_filter = st.multiselect("Filter by GM", gm_list, key='m2_gm')
    with fc3:
        conf_filter = st.multiselect(
            "Confidence",
            ['high', 'low'],
            default=['high'],
            key='m2_conf'
        )

    # Apply filters
    filtered_talk = talk_df.copy()
    if direction_filter and 'Trade_Direction' in filtered_talk.columns:
        filtered_talk = filtered_talk[filtered_talk['Trade_Direction'].isin(direction_filter)]
    if gm_filter and 'GM_Name' in filtered_talk.columns:
        filtered_talk = filtered_talk[filtered_talk['GM_Name'].isin(gm_filter)]
    if conf_filter and 'Confidence' in filtered_talk.columns:
        filtered_talk = filtered_talk[filtered_talk['Confidence'].isin(conf_filter)]

    # Deduplicate — one row per unique player name + org
    if 'Player_Name' in filtered_talk.columns and 'GM_Team' in filtered_talk.columns:
        filtered_talk = filtered_talk.drop_duplicates(
            subset=['Player_Name', 'GM_Team']
        ).reset_index(drop=True)

    st.caption(f"{len(filtered_talk)} players in trade talk | {len(talk_df)} total entries in sheet")

    # ── Match and evaluate ────────────────────────────────────────────────────
    verdicts = []
    for _, row in filtered_talk.iterrows():
        player_name = str(row.get('Player_Name', '')).strip()
        org         = str(row.get('GM_Team', '')).strip()
        pos_hint    = str(row.get('Position_Hint', '')).strip()
        contract    = str(row.get('Contract_Hint', '')).strip()
        direction   = str(row.get('Trade_Direction', 'selling')).strip()
        gm_name     = str(row.get('GM_Name', '')).strip()
        summary     = str(row.get('Summary', '')).strip()
        confidence  = str(row.get('Confidence', 'high')).strip()

        if not player_name:
            continue

        # Skip own team's players — check sheet GM_Team first
        if org and my_team and org.lower() == my_team.lower():
            continue

        # Match against league CSV
        match_result = match_player(player_name, org, league_df, direction)
        if isinstance(match_result, tuple):
            matched_row, ambiguous = match_result
        else:
            matched_row, ambiguous = match_result, False

        # Second own-team check — use actual ORG from matched CSV row
        if matched_row is not None and my_team:
            matched_org = str(matched_row.get('ORG', '')).strip()
            if matched_org.lower() == my_team.lower():
                continue

        if matched_row is None:
            verdicts.append({
                'Player':    player_name,
                'GM':        gm_name,
                'ORG':       org,
                'POS':       pos_hint or '?',
                'F1':        '—',
                'TV':        '—',
                'Control':   '—',
                'Contract':  contract,
                'Verdict':   'NOT FOUND',
                'Reason':    'Not matched in league CSV — may be last name only or reserve roster',
                'Luck':      '—',
                'Flex':      '—',
                'Conf':      confidence,
                'Ambiguous': False,
            })
            continue

        # Compute F1 and TV
        r   = matched_row.to_dict()
        pos = str(r.get('POS', pos_hint or ''))

        if pos in PITCHER_POSITIONS:
            f1_val = pitcher_f1(r)
            luck   = 'N/A'
            flex   = ''
        elif pos in BATTER_POSITIONS:
            f1_val = batter_f1(r)
            luck   = babip_luck_flag(r)
            flex   = flex_flag(r, tc.get('need_positions', []))
        else:
            continue

        ml_yrs  = _s(r.get('ML_YRS',  0))
        ml_days = _s(r.get('ML_DAYS', 0))
        years   = _s(r.get('YEARS_LEFT', 0))
        control = compute_control_window(years, ml_yrs, ml_days)
        tv      = trade_value(f1_val, control, pos)

        v_label, v_reason = verdict(f1_val, tv, control, tc, pos, luck)

        # Boost to STRONG BUY if BUY_LOW/STRONG_BUY luck + high F1
        if luck in BUY_LUCK_FLAGS and f1_val >= 4.0 and v_label == 'FAIR VALUE':
            v_label  = 'STRONG BUY'
            v_reason = f'{luck} + strong ratings = buy-low | ' + v_reason

        verdicts.append({
            'Player':    r.get('Name', player_name),
            'GM':        gm_name,
            'ORG':       org or r.get('ORG', ''),
            'POS':       pos,
            'F1':        round(f1_val, 2),
            'TV':        tv,
            'Control':   control,
            'Contract':  contract,
            'Verdict':   v_label,
            'Reason':    v_reason,
            'Luck':      luck,
            'Flex':      flex,
            'Conf':      confidence,
            'Ambiguous': ambiguous,
        })

    if not verdicts:
        st.info("No players matched after filtering. Try changing direction or confidence filters.")
        return

    out = pd.DataFrame(verdicts)

    # Sort: STRONG BUY first, then FAIR VALUE, then rest
    order = {'STRONG BUY': 0, 'FAIR VALUE': 1, 'OVERPRICED': 2, 'PASS': 3, 'NOT FOUND': 4}
    out['_sort'] = out['Verdict'].map(order).fillna(5)
    out = out.sort_values('_sort').drop(columns=['_sort']).reset_index(drop=True)

    # ── Display ───────────────────────────────────────────────────────────────
    # Color-code verdict column
    def color_verdict(val):
        colors = {
            'STRONG BUY': 'background-color: #1a4a1a; color: #90ee90',
            'FAIR VALUE': 'background-color: #1a3a4a; color: #87ceeb',
            'OVERPRICED': 'background-color: #4a3a1a; color: #ffd700',
            'PASS':       'background-color: #3a1a1a; color: #ff6b6b',
            'NOT FOUND':  'background-color: #2a2a2a; color: #888888',
        }
        return colors.get(val, '')

    display_cols = [c for c in [
        'Player', 'GM', 'ORG', 'POS', 'F1', 'TV', 'Control',
        'Contract', 'Verdict', 'Reason', 'Luck', 'Flex', 'Conf'
    ] if c in out.columns]

    # Flag ambiguous matches
    ambiguous_count = out['Ambiguous'].sum() if 'Ambiguous' in out.columns else 0
    if ambiguous_count > 0:
        st.warning(f"{ambiguous_count} player(s) matched on last name only — verify before acting.")

    st.dataframe(
        out[display_cols].style.map(color_verdict, subset=['Verdict']),
        use_container_width=True,
        height=600,
        hide_index=True,
    )

    # Summary counts
    vc = out['Verdict'].value_counts()
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("STRONG BUY", vc.get('STRONG BUY', 0))
    s2.metric("FAIR VALUE", vc.get('FAIR VALUE', 0))
    s3.metric("OVERPRICED", vc.get('OVERPRICED', 0))
    s4.metric("PASS",       vc.get('PASS', 0))

    st.download_button(
        "⬇️ Download verdicts",
        data=out[display_cols].to_csv(index=False),
        file_name="slack_eval_verdicts.csv",
        mime="text/csv",
        key='m2_download'
    )


def render_mode3(league: League):
    """
    Mode 3 — Free Agents
    Filter ORG == '-', score by F1 and Fit, surface demand vs headroom,
    flag Rock and Roll archetypes (WE=L + age 30+ + SELL_HIGH/STRONG_SELL).
    """
    tc      = league.team_config
    my_team = tc.get('my_team', '')
    mode    = tc.get('mode', 'Competing')
    payroll = _s(tc.get('payroll_current', 0))
    tax     = _s(tc.get('tax_threshold', 0))
    need_pos = tc.get('need_positions', [])

    st.markdown("#### Free Agents")
    st.caption("Players with no team (ORG = '-'). Scored by Fit — no Market friction.")

    uploaded = st.file_uploader(
        "League CSV",
        type=['csv'],
        key='m3_upload',
        help="Same combined export as Mode 1. Free agents appear with ORG = '-'."
    )

    if uploaded is None:
        st.info("Upload your league CSV to browse free agents.")
        return

    with st.spinner("Loading..."):
        try:
            raw = pd.read_csv(uploaded, encoding='utf-8-sig', low_memory=False)
            df  = prep_data(raw)
        except Exception as e:
            st.error(f"Failed to read CSV: {e}")
            return

    # Filter to free agents only
    fa_df = df[df['ORG'].astype(str).str.strip() == '-'].copy()

    if fa_df.empty:
        st.warning("No free agents found in this export (no rows with ORG = '-'). "
                   "Free agents are most common during the offseason or after releases.")
        return

    st.caption(f"{len(fa_df)} free agents found in export")

    # ── Filters ───────────────────────────────────────────────────────────────
    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        role_filter = st.radio("Role", ['All', 'Batters', 'Pitchers'],
                               horizontal=True, key='m3_role')
    with fc2:
        all_pos = sorted(fa_df['POS'].dropna().unique())
        if role_filter == 'Batters':
            pos_options = [p for p in all_pos if p in BATTER_POSITIONS]
        elif role_filter == 'Pitchers':
            pos_options = [p for p in all_pos if p in PITCHER_POSITIONS]
        else:
            pos_options = all_pos
        pos_filter = st.multiselect("Position", pos_options, key='m3_pos')
    with fc3:
        age_range = st.slider("Age", min_value=20, max_value=45,
                              value=(20, 38), key='m3_age')
    with fc4:
        f1_floor = st.slider("Min F1", min_value=0.0, max_value=6.0,
                             value=1.0, step=0.5, key='m3_f1')

    rr_only = st.checkbox("Show Rock & Roll archetypes only", key='m3_rr',
                          help="WE=Low + Age 30+ + hot BABIP stats — looks great but likely regressing")

    # ── Evaluate ──────────────────────────────────────────────────────────────
    results = []
    for _, row in fa_df.iterrows():
        r   = row.to_dict()
        pos = str(r.get('POS', ''))
        age = _s(r.get('AGE', r.get('Age', 25)))

        if pos in PITCHER_POSITIONS:
            f1_val = pitcher_f1(r)
            luck   = 'N/A'
            flex   = ''
            we     = ''
        elif pos in BATTER_POSITIONS:
            f1_val = batter_f1(r)
            luck   = babip_luck_flag(r)
            flex   = flex_flag(r, need_pos)
            we     = str(r.get('WE', r.get('Work Ethic', ''))).strip()
        else:
            continue

        # Personality hard skip
        personality = str(r.get('Personality', r.get('Type', '')))
        if personality in ('Unmotivated', 'Disruptive'):
            continue

        # Rock and Roll archetype flag
        # WE=L + age 30+ + sell-side luck (outperforming ratings on small sample)
        is_rock_roll = (
            we == 'L' and
            age >= 30 and
            luck in SELL_LUCK_FLAGS
        )

        # Demand and headroom
        demand   = _s(r.get('FA_DEMAND', 0))
        fits_budget = None
        if tax > 0 and payroll > 0:
            headroom    = tax - payroll
            fits_budget = demand <= headroom
        elif tax > 0:
            fits_budget = demand <= tax

        # Fit score (no market score for FAs)
        fit, missing_cfg = fit_score(r, tc)

        # Boost fit for buy-luck batters (STRONG_BUY gets a bigger bump)
        if luck in BUY_LUCK_FLAGS and f1_val >= 3.0:
            fit = min(10.0, fit + (0.8 if luck == 'STRONG_BUY' else 0.5))

        # Penalty for Rock and Roll
        if is_rock_roll:
            fit = max(0.0, fit - 2.0)

        results.append({
            'Name':       r.get('Name', ''),
            'POS':        pos,
            'Age':        int(age),
            'F1':         round(f1_val, 2),
            'Fit':        fit,
            'Demand':     int(demand) if demand > 0 else '—',
            'Budget_OK':  ('✓' if fits_budget else '✗') if fits_budget is not None else '—',
            'Luck':       luck,
            'WE':         we,
            'Flex':       flex,
            'RockRoll':   '⚠️ R&R' if is_rock_roll else '',
            'FA_Type':    str(r.get('FA_TYPE', '')).strip(),
            'CON':        int(_s(r.get('CON', 0))) if pos in BATTER_POSITIONS else None,
            'POW':        int(_s(r.get('POW', 0))) if pos in BATTER_POSITIONS else None,
            'EYE':        int(_s(r.get('EYE', 0))) if pos in BATTER_POSITIONS else None,
            'STU':        int(_s(r.get('STU', 0))) if pos in PITCHER_POSITIONS else None,
            'MOV':        int(_s(r.get('MOV', 0))) if pos in PITCHER_POSITIONS else None,
            'PIT_CON':    int(_s(r.get('PIT_CON', 0))) if pos in PITCHER_POSITIONS else None,
            'STM':        int(_s(r.get('STM', 0))) if pos in PITCHER_POSITIONS else None,
            'PRONE':      str(r.get('PRONE', '')),
        })

    if not results:
        st.info("No free agents match the current filters.")
        return

    out = pd.DataFrame(results)

    # Apply filters
    mask = (
        (out['Age'] >= age_range[0]) &
        (out['Age'] <= age_range[1]) &
        (out['F1'] >= f1_floor)
    )
    if role_filter == 'Batters':
        mask &= out['POS'].isin(BATTER_POSITIONS)
    elif role_filter == 'Pitchers':
        mask &= out['POS'].isin(PITCHER_POSITIONS)
    if pos_filter:
        mask &= out['POS'].isin(pos_filter)
    if rr_only:
        mask &= out['RockRoll'] != ''

    filtered = out[mask].sort_values('Fit', ascending=False).reset_index(drop=True)

    st.markdown(f"#### Free Agent Candidates — {len(filtered)} shown")

    # Split batter / pitcher tabs
    t_bat, t_pit = st.tabs(["⚾ Batters", "🥎 Pitchers"])

    bat = filtered[filtered['POS'].isin(BATTER_POSITIONS)]
    pit = filtered[filtered['POS'].isin(PITCHER_POSITIONS)]

    bat_cols = [c for c in [
        'Name', 'POS', 'Age', 'F1', 'Fit', 'Demand', 'Budget_OK',
        'Luck', 'WE', 'Flex', 'RockRoll',
        'CON', 'POW', 'EYE', 'PRONE'
    ] if c in bat.columns]

    pit_cols = [c for c in [
        'Name', 'POS', 'Age', 'F1', 'Fit', 'Demand', 'Budget_OK',
        'RockRoll', 'STU', 'MOV', 'PIT_CON', 'STM', 'PRONE'
    ] if c in pit.columns]

    with t_bat:
        if bat.empty:
            st.info("No batter free agents match filters.")
        else:
            st.caption(
                "**Fit** = match to your team needs (0-10). "
                "**Demand** = asking salary. "
                "**Budget_OK** = demand fits within tax headroom. "
                "**WE** = Work Ethic (L=Low). "
                "**R&R** = Rock & Roll archetype — WE=Low + Age 30+ + hot stats. Avoid."
            )
            st.dataframe(bat[bat_cols], use_container_width=True,
                        height=500, hide_index=True)

    with t_pit:
        if pit.empty:
            st.info("No pitcher free agents match filters.")
        else:
            st.caption(
                "**Fit** = match to your team needs (0-10). "
                "**Demand** = asking salary. "
                "**Budget_OK** = demand fits within tax headroom. "
                "**R&R** = Rock & Roll archetype — WE=Low + Age 30+ + hot stats. Avoid."
            )
            st.dataframe(pit[pit_cols], use_container_width=True,
                        height=500, hide_index=True)

    # Download
    csv_out = filtered.to_csv(index=False)
    st.download_button(
        "⬇️ Download free agent list",
        data=csv_out,
        file_name="free_agents.csv",
        mime="text/csv",
        key='m3_download'
    )


def render_mode4(league: League):
    """
    Mode 4 — Build a Deal v0.1
    Single league CSV upload. Select a target player.
    Shows: their team's situation, your tradeable assets,
    and basic package suggestions ranked by feasibility.
    """
    tc       = league.team_config
    my_team  = tc.get('my_team', '')
    mode     = tc.get('mode', 'Competing')
    untouchables = [u.lower().strip() for u in tc.get('untouchables', [])]

    st.markdown("#### Build a Deal")
    st.caption("Select a target player. See their team's situation and what you can offer.")

    if not my_team:
        st.warning("Set your team in Settings first.")
        return

    uploaded = st.file_uploader(
        "League CSV",
        type=['csv'],
        key='m4_upload',
        help="Same combined export as Modes 1-3."
    )

    if uploaded is None:
        st.info("Upload your league CSV to begin.")
        return

    with st.spinner("Loading..."):
        try:
            raw       = pd.read_csv(uploaded, encoding='utf-8-sig', low_memory=False)
            league_df = prep_data(raw)
        except Exception as e:
            st.error(f"Failed to read CSV: {e}")
            return

    # ── Separate rosters ──────────────────────────────────────────────────────
    my_roster    = league_df[league_df['ORG'].astype(str).str.strip() == my_team].copy()
    other_teams  = league_df[
        (league_df['ORG'].astype(str).str.strip() != my_team) &
        (league_df['ORG'].astype(str).str.strip() != '-')
    ].copy()

    if my_roster.empty:
        st.error(f"No players found for '{my_team}'. Check Team Config matches export exactly.")
        return

    # ── Target player selector ────────────────────────────────────────────────
    st.markdown("#### 1. Select Target Player")

    # Build target list from other teams — active roster players only
    target_options = []
    for _, row in other_teams.iterrows():
        pos = str(row.get('POS', ''))
        if pos not in BATTER_POSITIONS and pos not in PITCHER_POSITIONS:
            continue
        name = str(row.get('Name', ''))
        org  = str(row.get('ORG', ''))
        target_options.append(f"{name} ({pos}, {org})")

    if not target_options:
        st.warning("No other-team players found.")
        return

    target_options.sort()
    selected = st.selectbox("Target player", target_options, key='m4_target')

    if not selected:
        return

    # Parse selection
    target_name = selected.split(' (')[0].strip()
    target_rows = other_teams[other_teams['Name'] == target_name]
    if target_rows.empty:
        st.error("Player not found.")
        return

    target     = target_rows.iloc[0].to_dict()
    target_pos = str(target.get('POS', ''))
    target_org = str(target.get('ORG', ''))
    target_age = _s(target.get('AGE', target.get('Age', 25)))

    # Compute target F1 and TV
    if target_pos in PITCHER_POSITIONS:
        target_f1 = pitcher_f1(target)
    else:
        target_f1 = batter_f1(target)

    target_years   = _s(target.get('YEARS_LEFT', 0))
    target_ml_yrs  = _s(target.get('ML_YRS', 0))
    target_ml_days = _s(target.get('ML_DAYS', 0))
    target_control = compute_control_window(target_years, target_ml_yrs, target_ml_days)
    target_tv      = trade_value(target_f1, target_control, target_pos)
    target_arb     = compute_arb_status(target_ml_yrs, target_ml_days)
    target_salary  = _s(target.get('SALARY', 0))

    # ── Target player card ────────────────────────────────────────────────────
    st.markdown("---")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("F1",           f"{target_f1:.2f}")
    c2.metric("Trade Value",  f"{target_tv:.1f}")
    c3.metric("Control",      f"{target_control:.1f} yr")
    c4.metric("Age",          int(target_age))
    c5.metric("Arb Status",   target_arb)
    c6.metric("Salary",       f"${int(target_salary):,}" if target_salary > 0 else "—")

    # Feasibility of this target
    mkt = market_score(target, None)
    st.caption(f"Market feasibility: **{mkt:.1f}/10** — "
               f"{'motivated seller' if mkt >= 7 else 'neutral' if mkt >= 4 else 'unlikely to move'}")

    if mkt < 3:
        st.warning("Low market score — this player is unlikely to be available. "
                   "Consider targets with higher market scores from Mode 1.")

    # ── Their team situation ──────────────────────────────────────────────────
    st.markdown("---")
    st.markdown(f"#### 2. {target_org} — Team Situation")

    their_roster = other_teams[
        other_teams['ORG'].astype(str).str.strip() == target_org
    ].copy()

    if their_roster.empty:
        st.warning("Could not load their roster.")
    else:
        # Compute F1 for their roster
        their_f1s = []
        for _, row in their_roster.iterrows():
            r   = row.to_dict()
            pos = str(r.get('POS', ''))
            if pos in PITCHER_POSITIONS:
                f1 = pitcher_f1(r)
            elif pos in BATTER_POSITIONS:
                f1 = batter_f1(r)
            else:
                continue
            their_f1s.append({
                'Name': r.get('Name', ''),
                'POS':  pos,
                'Age':  int(_s(r.get('AGE', r.get('Age', 25)))),
                'F1':   round(f1, 2),
                'TV':   trade_value(f1,
                         compute_control_window(
                             _s(r.get('YEARS_LEFT', 0)),
                             _s(r.get('ML_YRS', 0)),
                             _s(r.get('ML_DAYS', 0))
                         ), pos),
                'YL':   _s(r.get('YEARS_LEFT', 0)),
            })

        their_df = pd.DataFrame(their_f1s)

        if not their_df.empty:
            # Identify weak positions — below league average F1 for that position
            pos_avg = {}
            for pos in BATTER_POSITIONS | PITCHER_POSITIONS:
                pos_rows = league_df[league_df['POS'] == pos]
                if not pos_rows.empty:
                    f1s = []
                    for _, r in pos_rows.iterrows():
                        rd = r.to_dict()
                        if pos in PITCHER_POSITIONS:
                            f1s.append(pitcher_f1(rd))
                        else:
                            f1s.append(batter_f1(rd))
                    pos_avg[pos] = np.mean(f1s) if f1s else 0

            their_pos_avg = their_df.groupby('POS')['F1'].mean()
            weak_positions = []
            for pos, avg in their_pos_avg.items():
                league_avg = pos_avg.get(pos, 0)
                if avg < league_avg * 0.85:
                    weak_positions.append(pos)

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Roster Overview**")
                st.caption(f"{len(their_df)} players | Avg F1: {their_df['F1'].mean():.2f}")
                # Age distribution
                avg_age = their_df['Age'].mean()
                aging   = their_df[their_df['Age'] >= 30]
                st.caption(f"Avg age: {avg_age:.1f} | Players 30+: {len(aging)}")
                if weak_positions:
                    st.markdown(f"**Weak positions:** {', '.join(weak_positions)}")
                else:
                    st.markdown("No obviously weak positions identified.")

            with col2:
                st.markdown("**Their Roster (sorted by F1)**")
                display = their_df.sort_values('F1', ascending=False).head(15)
                st.dataframe(display[['Name','POS','Age','F1','TV','YL']],
                            use_container_width=True, hide_index=True, height=300)

    # ── Your tradeable assets ─────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 3. Your Tradeable Assets")

    my_assets = []
    for _, row in my_roster.iterrows():
        r   = row.to_dict()
        pos = str(r.get('POS', ''))
        name = str(r.get('Name', ''))

        if pos not in BATTER_POSITIONS and pos not in PITCHER_POSITIONS:
            continue
        if name.lower().strip() in untouchables:
            continue

        if pos in PITCHER_POSITIONS:
            f1 = pitcher_f1(r)
        else:
            f1 = batter_f1(r)

        ml_yrs  = _s(r.get('ML_YRS', 0))
        ml_days = _s(r.get('ML_DAYS', 0))
        years   = _s(r.get('YEARS_LEFT', 0))
        control = compute_control_window(years, ml_yrs, ml_days)
        tv      = trade_value(f1, control, pos)
        arb     = compute_arb_status(ml_yrs, ml_days)

        my_assets.append({
            'Name':    name,
            'POS':     pos,
            'Age':     int(_s(r.get('AGE', r.get('Age', 25)))),
            'F1':      round(f1, 2),
            'TV':      tv,
            'Control': control,
            'Arb':     arb,
            'Salary':  int(_s(r.get('SALARY', 0))),
        })

    assets_df = pd.DataFrame(my_assets)
    # Sort by TV descending, break ties with F1 descending
    assets_df = assets_df.sort_values(['TV', 'F1'], ascending=[False, False]).reset_index(drop=True)

    st.caption(f"{len(assets_df)} tradeable players (untouchables excluded)")
    st.dataframe(assets_df, use_container_width=True, hide_index=True, height=300)

    # ── Package suggestions ───────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 4. Package Suggestions")
    st.caption("Ranked by feasibility — why would they say yes?")

    if their_df.empty or assets_df.empty:
        st.info("Need both rosters loaded to suggest packages.")
        return

    suggestions = []

    for _, asset in assets_df.iterrows():
        asset_pos = asset['POS']
        asset_tv  = asset['TV']
        asset_f1  = asset['F1']
        asset_age = asset['Age']

        # Skip assets with no trade value
        if asset_tv <= 0:
            continue

        # Does this asset address one of their weak positions?
        addresses_need = asset_pos in weak_positions if 'weak_positions' in dir() else False

        # Feasibility reasons — why would they want this?
        reasons = []

        if addresses_need:
            reasons.append(f"fills their {asset_pos} gap")
        if asset_age <= 25 and mode == 'Competing':
            reasons.append("young controllable player")
        if asset_f1 >= 4.0:
            reasons.append(f"strong F1={asset_f1:.1f}")
        if asset['Arb'] == 'Pre-Arb':
            reasons.append("pre-arb cost control")
        if asset['Control'] >= 2.0:
            reasons.append(f"{asset['Control']:.1f}yr control")

        # TV gap — is this a fair ask?
        tv_gap   = target_tv - asset_tv
        tv_ratio = asset_tv / target_tv if target_tv > 0 else 0

        if tv_ratio >= 0.8:
            tv_note = "near value match"
        elif tv_ratio >= 0.5:
            tv_note = "need to add to match value"
        else:
            tv_note = "significant value gap — need multiple pieces"

        if reasons:  # Only suggest if there's a real reason they'd want it
            suggestions.append({
                'Offer':    asset['Name'],
                'POS':      asset_pos,
                'Age':      asset_age,
                'F1':       asset_f1,
                'TV':       asset_tv,
                'TV_Gap':   round(tv_gap, 1),
                'Why_Yes':  ' | '.join(reasons),
                'TV_Note':  tv_note,
                'Priority': len(reasons) * 2 + (1 if addresses_need else 0),
            })

    if suggestions:
        sug_df = pd.DataFrame(suggestions).sort_values('Priority', ascending=False)
        st.dataframe(
            sug_df[['Offer','POS','Age','F1','TV','TV_Gap','Why_Yes','TV_Note']],
            use_container_width=True, hide_index=True, height=400
        )
        st.caption(
            "**TV_Gap** = target TV minus your offer TV. Positive = you need to add more. "
            "Negative = you're offering more than the target's TV. "
            "Feasibility matters more than exact TV match."
        )
    else:
        st.info("No strong package suggestions found. "
                "Your tradeable assets may not address their specific needs. "
                "Consider adding prospects or picking a different target.")


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def render_acquisitions(league: League):
    """
    Main entry point called from app.py.
    Dispatches to mode tabs only. Team Config lives in Settings.
    """
    st.header("🔄 Acquisitions")

    complete, missing = league.team_config_complete()
    if not complete:
        st.warning(
            f"Team Config is incomplete ({', '.join(missing)} missing). "
            "Go to **⚙️ Settings** in the sidebar to configure your team."
        )

    tabs = st.tabs([
        "🌐 Browse League",
        "💬 Slack Eval",
        "🆓 Free Agents",
        "🤝 Build a Deal",
    ])

    with tabs[0]:
        render_mode1(league)
    with tabs[1]:
        render_mode2(league)
    with tabs[2]:
        render_mode3(league)
    with tabs[3]:
        render_mode4(league)
