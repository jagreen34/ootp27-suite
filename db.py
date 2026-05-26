"""
OOTP 27 Suite — Persistence Layer
===================================
Multi-league SQLite storage. One League object per active league.
Extends the v26 pattern with Team Config (mode, park factors, roster
construction, service-time awareness) stored in config.json.

Directory layout:
  data/
    leagues/
      {league_slug}/
        config.json          ← display_name, my_team, team_config, created_at
        roster_current.db    ← SQLite: snapshots, snapshot_players, il_tags
        seasons/
          1975.json
"""

import os
import json
import sqlite3
import io
from datetime import date, datetime

# ── DATA ROOT ─────────────────────────────────────────────────────────────────
DATA_DIR    = os.environ.get('OOTP_DATA_DIR', os.path.join(os.path.dirname(__file__), 'data'))
LEAGUES_DIR = os.path.join(DATA_DIR, 'leagues')
os.makedirs(LEAGUES_DIR, exist_ok=True)

LAST_ROSTER_LABEL = '__last_roster__'

# ── TEAM CONFIG DEFAULTS ──────────────────────────────────────────────────────
# All keys that live under config['team_config'].
# Tools read these via league.team_config; the Settings screen writes them.
TEAM_CONFIG_DEFAULTS = {
    # Identity
    'my_team':           '',          # team name as it appears in export

    # Strategic mode — drives feasibility & fit scoring
    # Values: 'Rebuilding' | 'Competing' | 'Sustaining'
    'mode':              'Competing',

    # Contention window (years) — used in Sustaining/Competing mode
    'window_start':      None,        # int or None
    'window_end':        None,        # int or None

    # Season context — used to flag pre/post trade deadline urgency
    # Format: 'YYYY-MM-DD' or None. None = offseason planning mode.
    'current_date':      None,

    # Financial
    'payroll_current':   0,           # current committed payroll (int, dollars)
    'tax_threshold':     0,           # soft cap threshold (120% avg payroll)

    # Park factors — max HR 1.300, min .700, no more than .300 diff LH/RH
    'park_hr_l':         1.000,
    'park_hr_r':         1.000,
    'park_avg':          1.000,
    'park_2b':           1.000,
    'park_3b':           1.000,

    # Rotation philosophy (locked at 6 per registry findings)
    'rotation_size':     6,

    # Roster construction preferences
    # 'Power' | 'OBP' | 'Balanced'
    'offense_philosophy': 'Balanced',

    # No-DH flag — always True for American Circuit
    'no_dh':             True,

    # Positions where we have surplus (auto-detected, overridable)
    # List of position strings e.g. ['LF', 'RF']
    'surplus_positions': [],

    # Positions where we have need (auto-detected, overridable)
    'need_positions':    [],

    # Untouchable players — never suggest trading these away
    # List of player name strings
    'untouchables':      [],
}


# ── HELPERS ───────────────────────────────────────────────────────────────────
def _slug(name: str) -> str:
    return name.strip().replace(' ', '_')


def _s(v, d=0.0):
    """Safe float conversion."""
    try:
        import math
        if v is None: return d
        f = float(v)
        return d if math.isnan(f) else f
    except Exception:
        return d


def compute_control_window(years_left: float, ml_yrs: float, ml_days: float) -> float:
    """
    Effective years of team control — lesser of contract years remaining
    and service-time years until free agency.

    FA eligibility: 6 service years (76 days = 1 service year per AC rules).
    Returns a float rounded to 1 decimal.
    """
    service_years_accrued = ml_yrs + (ml_days / 76.0)
    fa_years_remaining    = max(0.0, 6.0 - service_years_accrued)
    return round(min(float(years_left), fa_years_remaining), 1)


def compute_arb_status(ml_yrs: float, ml_days: float) -> str:
    """
    Returns a string describing current service-time status:
      'Pre-Arb'   — fewer than 3 service years
      'Arb'       — 3-5 service years (arbitration eligible)
      'FA-Elig'   — 6+ service years
    """
    service = ml_yrs + (ml_days / 76.0)
    if service >= 6.0:
        return 'FA-Elig'
    elif service >= 3.0:
        return 'Arb'
    return 'Pre-Arb'


# ── FORMULA HELPERS (no Streamlit / pandas dependency) ───────────────────────
def _pit_con(row):
    return _s(row.get('PIT_CON', row.get('CON', 0)))


def _off_f1(row):
    """
    OOTP 27 batter F1 — OFF component only.
    Full F1 = OFF + DEF + POS_ADJ; this is the offline-safe partial.
    Used for snapshot indexing only; full reconstruction in acquisitions.py.
    """
    return (-14.168
        + _s(row.get('POW'))  * 0.1142
        + _s(row.get('BABIP',row.get('BAT_BABIP_RATING',0))) * 0.0725
        + _s(row.get('EYE'))  * 0.04
        + _s(row.get('CON'))  * 0.0379
        + _s(row.get('AVK',row.get('Ks',0))) * 0.0317
        + _s(row.get('GAP'))  * 0.0291
        + _s(row.get('SPE'))  * 0.0128)


def _sp_f1_simple(row):
    """
    Simplified SP F1 for snapshot indexing (no v-splits required).
    Full F1.1 with v-splits computed in acquisitions.py.
    """
    return (-5.932
        + _s(row.get('STU',  row.get('Stuff', 0)))    * 0.0207
        + _s(row.get('MOV',  row.get('Movement', 0))) * 0.1091
        + _s(row.get('STM',  row.get('Stamina', 0)))  * 0.0560
        + _pit_con(row)                                * 0.0053)


# ══════════════════════════════════════════════════════════════════════════════
class League:
    """
    All storage operations for one league.
    Instantiate via db.get_league() or db.create_league().
    """

    def __init__(self, slug: str):
        self.slug        = slug
        self.dir         = os.path.join(LEAGUES_DIR, slug)
        self.db_path     = os.path.join(self.dir, 'roster_current.db')
        self.config_path = os.path.join(self.dir, 'config.json')
        self.seasons_dir = os.path.join(self.dir, 'seasons')
        self._ensure_structure()
        self._init_db()

    # ── INTERNAL SETUP ────────────────────────────────────────────────────────
    def _ensure_structure(self):
        os.makedirs(self.seasons_dir, exist_ok=True)
        if not os.path.exists(self.config_path):
            self._write_config({
                'display_name': self.slug.replace('_', ' '),
                'created_at':   date.today().isoformat(),
                'notes':        '',
                'team_config':  dict(TEAM_CONFIG_DEFAULTS),
            })

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_db(self):
        with self._conn() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                label        TEXT    NOT NULL,
                season_year  INTEGER,
                phase        TEXT,
                created_at   TEXT    DEFAULT (datetime('now')),
                notes        TEXT,
                player_count INTEGER,
                csv_data     TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS snapshot_players (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
                name         TEXT,
                team         TEXT,
                pos          TEXT,
                age          REAL,
                pow          REAL, con   REAL, eye    REAL,
                gap          REAL, babip REAL, spe    REAL, war REAL,
                mov          REAL, stu   REAL, stm    REAL,
                pit_con      REAL, pit_war REAL,
                ml_yrs       REAL, ml_days REAL,
                salary       REAL, years_left REAL,
                off_f1       REAL,
                sp_f1        REAL
            );

            CREATE INDEX IF NOT EXISTS idx_sp_snapshot ON snapshot_players(snapshot_id);
            CREATE INDEX IF NOT EXISTS idx_sp_name     ON snapshot_players(name);

            CREATE TABLE IF NOT EXISTS il_tags (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                player_name TEXT NOT NULL,
                team        TEXT,
                reason      TEXT,
                date_added  TEXT DEFAULT (datetime('now')),
                active      INTEGER DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_il_team ON il_tags(team, active);
            """)

    # ── CONFIG ────────────────────────────────────────────────────────────────
    def _read_config(self) -> dict:
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _write_config(self, cfg: dict):
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)

    def get_config(self) -> dict:
        return self._read_config()

    def save_config(self, updates: dict):
        cfg = self._read_config()
        cfg.update(updates)
        self._write_config(cfg)

    @property
    def display_name(self) -> str:
        return self.get_config().get('display_name', self.slug.replace('_', ' '))

    @property
    def my_team(self) -> str:
        return self.team_config.get('my_team', '')

    # ── TEAM CONFIG ───────────────────────────────────────────────────────────
    @property
    def team_config(self) -> dict:
        """
        Returns the team config dict, merging stored values over defaults.
        Always returns a complete dict even if config.json is missing keys
        (handles upgrades where new keys were added after initial creation).
        """
        cfg  = self._read_config()
        stored = cfg.get('team_config', {})
        result = dict(TEAM_CONFIG_DEFAULTS)
        result.update(stored)
        return result

    def save_team_config(self, tc: dict):
        """
        Merge tc into the stored team_config and persist.
        Caller passes only the keys they want to update.
        """
        cfg = self._read_config()
        existing = cfg.get('team_config', {})
        existing.update(tc)
        cfg['team_config'] = existing
        self._write_config(cfg)

    def team_config_complete(self) -> tuple[bool, list[str]]:
        """
        Returns (is_complete, list_of_missing_fields).
        Used by tools to decide whether to show partial or full Fit scores.
        Required fields: my_team, mode, payroll_current, tax_threshold,
                         park_hr_l, park_hr_r, park_avg.
        """
        tc = self.team_config
        required = ['my_team', 'mode', 'payroll_current', 'tax_threshold',
                    'park_hr_l', 'park_hr_r', 'park_avg']
        missing = [k for k in required
                   if not tc.get(k) and tc.get(k) != 0]
        # my_team empty string counts as missing
        if not tc.get('my_team', '').strip():
            if 'my_team' not in missing:
                missing.append('my_team')
        return (len(missing) == 0, missing)

    def is_pre_deadline(self) -> bool | None:
        """
        Returns True if current_date is before July 31,
        False if after, None if current_date not set.
        Trade deadline = July 31.
        """
        tc = self.team_config
        cd = tc.get('current_date')
        if not cd:
            return None
        try:
            dt   = datetime.strptime(cd, '%Y-%m-%d')
            year = dt.year
            deadline = datetime(year, 7, 31)
            return dt <= deadline
        except Exception:
            return None

    # ── SNAPSHOTS ─────────────────────────────────────────────────────────────
    def save_snapshot(self, df, label: str, season_year: int = None,
                      phase: str = None, notes: str = None) -> int:
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        csv_text = buf.getvalue()

        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO snapshots (label, season_year, phase, notes, player_count, csv_data) "
                "VALUES (?,?,?,?,?,?)",
                (label, season_year, phase, notes or '', len(df), csv_text)
            )
            snap_id = cur.lastrowid

            rows = []
            for row in df.to_dict('records'):
                pos    = str(row.get('POS', ''))
                is_pit = pos in ('SP', 'RP', 'CL')
                rows.append((
                    snap_id,
                    row.get('Name', ''),
                    row.get('TM',   row.get('Team', '')),
                    pos,
                    _s(row.get('Age')),
                    _s(row.get('POW')),
                    _s(row.get('CON')),
                    _s(row.get('EYE')),
                    _s(row.get('GAP')),
                    _s(row.get('BAT_BABIP_RATING', row.get('BABIP', 0))),
                    _s(row.get('SPE')),
                    _s(row.get('BAT_WAR', row.get('WAR', 0))),
                    _s(row.get('MOV')),
                    _s(row.get('STU')),
                    _s(row.get('STM')),
                    _pit_con(row),
                    _s(row.get('PIT_WAR', 0)),
                    _s(row.get('ML_YRS',  0)),
                    _s(row.get('ML_DAYS', 0)),
                    _s(row.get('SALARY',  0)),
                    _s(row.get('YEARS_LEFT', 0)),
                    round(_off_f1(row),     3) if not is_pit else None,
                    round(_sp_f1_simple(row), 3) if is_pit    else None,
                ))

            c.executemany(
                "INSERT INTO snapshot_players "
                "(snapshot_id,name,team,pos,age,pow,con,eye,gap,babip,spe,war,"
                "mov,stu,stm,pit_con,pit_war,ml_yrs,ml_days,salary,years_left,"
                "off_f1,sp_f1) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows
            )

        return snap_id

    def save_last_roster(self, df) -> None:
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        csv_text = buf.getvalue()
        with self._conn() as c:
            c.execute("DELETE FROM snapshots WHERE label=?", (LAST_ROSTER_LABEL,))
            c.execute(
                "INSERT INTO snapshots (label, player_count, csv_data) VALUES (?,?,?)",
                (LAST_ROSTER_LABEL, len(df), csv_text)
            )

    def get_last_roster(self):
        import pandas as pd
        with self._conn() as c:
            row = c.execute(
                "SELECT csv_data FROM snapshots WHERE label=?",
                (LAST_ROSTER_LABEL,)
            ).fetchone()
        if row is None:
            return None
        return pd.read_csv(io.StringIO(row['csv_data']), encoding='utf-8', low_memory=False)

    def list_snapshots(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, label, season_year, phase, created_at, player_count, notes "
                "FROM snapshots WHERE label != ? ORDER BY id DESC",
                (LAST_ROSTER_LABEL,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_snapshot_df(self, snapshot_id: int):
        import pandas as pd
        with self._conn() as c:
            row = c.execute(
                "SELECT csv_data FROM snapshots WHERE id=?", (snapshot_id,)
            ).fetchone()
        if row is None:
            return None
        return pd.read_csv(io.StringIO(row['csv_data']), encoding='utf-8', low_memory=False)

    def delete_snapshot(self, snapshot_id: int):
        with self._conn() as c:
            c.execute("DELETE FROM snapshots WHERE id=?", (snapshot_id,))

    # ── IL TAGS ───────────────────────────────────────────────────────────────
    def get_il_tags(self, team: str = None) -> list[dict]:
        with self._conn() as c:
            if team:
                rows = c.execute(
                    "SELECT * FROM il_tags WHERE active=1 AND team=? ORDER BY date_added DESC",
                    (team,)
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM il_tags WHERE active=1 ORDER BY date_added DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    def get_il_names(self, team: str = None) -> set:
        return {r['player_name'] for r in self.get_il_tags(team)}

    def add_il_tag(self, player_name: str, team: str, reason: str = ''):
        try:
            with self._conn() as c:
                c.execute(
                    "INSERT INTO il_tags (player_name, team, reason) VALUES (?,?,?)",
                    (player_name, team, reason)
                )
        except sqlite3.IntegrityError:
            pass

    def remove_il_tag(self, player_name: str, team: str):
        with self._conn() as c:
            c.execute(
                "UPDATE il_tags SET active=0 "
                "WHERE player_name=? AND team=? AND active=1",
                (player_name, team)
            )

    # ── SEASON ARCHIVES ───────────────────────────────────────────────────────
    def save_season_archive(self, year: int, record: str = '',
                            finish: str = '', notes: str = ''):
        path = os.path.join(self.seasons_dir, f'{year}.json')
        data = {
            'year':        year,
            'record':      record,
            'finish':      finish,
            'notes':       notes,
            'archived_at': datetime.now().isoformat(timespec='seconds'),
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def list_season_archives(self) -> list[dict]:
        archives = []
        for fname in sorted(os.listdir(self.seasons_dir), reverse=True):
            if fname.endswith('.json'):
                with open(os.path.join(self.seasons_dir, fname), 'r', encoding='utf-8') as f:
                    archives.append(json.load(f))
        return archives

    def delete_season_archive(self, year: int):
        path = os.path.join(self.seasons_dir, f'{year}.json')
        if os.path.exists(path):
            os.remove(path)


# ── MODULE-LEVEL LEAGUE MANAGEMENT ───────────────────────────────────────────
def list_leagues() -> list[str]:
    names = []
    if not os.path.exists(LEAGUES_DIR):
        return names
    for entry in os.scandir(LEAGUES_DIR):
        if not entry.is_dir():
            continue
        cfg_path = os.path.join(entry.path, 'config.json')
        if os.path.exists(cfg_path):
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            names.append(cfg.get('display_name', entry.name.replace('_', ' ')))
    return sorted(names)


def create_league(display_name: str) -> 'League':
    sl     = _slug(display_name)
    league = League(sl)
    cfg    = league.get_config()
    if cfg.get('display_name') != display_name:
        cfg['display_name'] = display_name
        league._write_config(cfg)
    return league


def get_league(display_name: str) -> 'League':
    return League(_slug(display_name))


def delete_league(display_name: str):
    import shutil
    sl   = _slug(display_name)
    path = os.path.join(LEAGUES_DIR, sl)
    if os.path.exists(path):
        shutil.rmtree(path)
