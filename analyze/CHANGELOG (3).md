# ootp_analyze — changelog

## 2026-09-19 — adversarial review fixes (DO NOT SHIP → shippable)

An independent review found five paths producing confidently wrong numbers with no
signal to the reader. The 57-check self-test and the 5 external audits all passed
while every one of them was live: **the tests tested what the author remembered.**

### Blocking fixes

| | was | now |
|---|---|---|
| **G9 (new)** | `detect_kind` counted distinct ORGs, so a **single-team roster** — the most natural export a GM makes — was scored as a draft pool. A 28-year-old major leaguer was handed a draft-day career-WAR projection with no warning. | A pool must PROVE itself: no organisations **and** a school column. Two or more organisations is a league. Anything else is **refused**. `--kind POOL/LEAGUE` overrides. The detected kind is now printed as its own line, not buried in the provenance stamp. |
| **web path** | `app.py` never called `check_columns()`. A file containing `Name,Foo` returned **200 and a six-sheet workbook with zero players**. | `check_columns()` runs; zero players is a 400; the soft "missing tool columns" list becomes a LIMITED ANALYSIS note in the workbook. |
| **G3** | `league_report` re-implemented the ORG filter by **name-set membership**. The reference league file has 42 duplicate names; 4 unassigned arms rode in on a rostered namesake and one was counted as a potential ace. | Filters on the player's own `org`. Census went 518→510 arms, 64→62 potential aces. |
| **A115** | `eff_pitches()` promised both counts were "reported, never silently chosen" — every consumer chose A41. Three arms read RELIEVER that read STARTER under A103, silently. The conflict label was hardcoded `'YES -- 2 vs 3'` and wrong for most (Mazzola is 4v5, Fonseca 0v1). | `role_gate` and `role_gate_flat40` are both computed; `role_flips` is surfaced as a **named workbook note** ("*** A115 CHANGES THE ROLE VERDICT for John Henson, Rafael Villatoro, Dan Bond"). The label prints the real counts. A standing note records that `b_eff` is scored on the A41 count and that the sources disagree about which rule A104 fitted. |
| **SR intercept** | The whole senior-bat scale was pinned to the literal string `'Roger Renshaw'`. Absent, it fell through to the **HS intercept** applied to SR coefficients — every senior bat understated by ~11 career WAR, silently, on a single ranked board. That is every future pool. | Fails loud (rule 22) when SR bats are present and the anchor is not. |

### Also

- **G7 withdrawn.** The docstring, README and KEY sheet all asserted that A94 bars are
  computed for LEAGUE exports only. They were always computed for pools too. The claim
  is removed rather than the behaviour — the pool bars are the most useful column on the
  board — and relabelled as a *projection*, not a measurement.
- **Encoding + delimiter.** `_read_csv` hard-coded UTF-8, so any latin-1 export — OOTP is
  full of accented names — died with an unhandled `UnicodeDecodeError` (500 + traceback).
  Now falls back utf-8-sig → cp1252 → latin-1 and sniffs tab vs comma.
- **Duplicate headers** now warn instead of silently collapsing (last column wins).
- **Row cap.** A 28 MB crafted CSV held a gunicorn worker for 40+ minutes; two took the
  site down. `MAX_ROWS = 5000`, `MAX_CONTENT_LENGTH` 64 MB → 16 MB.
- **No tracebacks to the browser.** Server paths and source lines were being returned on
  any 500. Now a request id; details go to the server log.
- **Provenance.** The web path stamped `export.csv` and the temp file's mtime. It now
  carries the user's real filename, and the sheet name for multi-sheet workbooks.

### Verification
- `verify` — **63 checks pass** (was 57; tests 12–14 rewritten/added for G9, A115, SR).
- `audit.py` — **all 5 external audits pass**, including the 13-ace league count and the
  416-row ORG filter.
- Draft pool (172) and league export (1,547, ~59 s) both produce correct workbooks.
- A single-team roster is refused with an explanation.

### Still open
- `SHARE` (0.70, ESTIMATED) is bracketed in `verify` only on a single-tool probability,
  where it provably cannot matter. It moves P(#1) by **4×** across 0.0–1.0 and those
  columns are unbracketed.
- `A104_HS_CUR`, `A104_HS_GAP`, `OBP_W`, `OBP_DEN` are not wrapped in `C()`, so G5 does
  not see them.
- A115 itself is unresolved — this release makes the disagreement loud, it does not settle it.

---

## 1.1.0 — 2026-09-19 (second pass, from the first live file)

The first real upload after deployment was a **single-team roster** (Philadelphia,
41 rows). G9 refused it, correctly. The refusal exposed two defects and one trap.

| # | What was wrong | Fix |
|---|---|---|
| 1 | The G9 refusal told a **browser** user to "pass `--kind LEAGUE`" — a command-line flag with no equivalent on the page. The advice was unreachable where it was displayed. | Added an **Export kind** selector to the page (Detect automatically / Force LEAGUE / Force POOL), wired to `Frame(kind=...)`. The refusal text now names the selector first and the flag second. |
| 2 | The page said "running **57** self-tests". It had been 63 since the first pass and is now 66. | Count corrected in `app.py` (docstring + progress text) and in the `Dockerfile` comment. |
| 3 | **The trap in the obvious fix.** Forcing LEAGUE on a one-club file would have computed BASELINES and the ACE CENSUS from 41 players of a single roster and presented them as league context — means, SDs and gate counts that read as authoritative and are not. Worse than the refusal, because it looks right. | **G10.** `Frame` now counts distinct organisations once and sets `single_org`. When a LEAGUE-kind frame has fewer than two organisations, BASELINES and ACE CENSUS are written as an explanation of why they are absent, not as numbers. Every player-level sheet is unaffected. |

**G10 is deliberately not a refusal.** A single-team roster is a legitimate thing to
analyse — it is the most natural file a GM produces. What is illegitimate is league
context derived from one club. The analysis runs; the two sheets that cannot be honest
say so in the sheet the user came looking for.

Three checks added (section 15), 63 → **66**. Regression on the 1,547-row league export
is unchanged: 510 arms, 13 clearing the ace gate now, 62 on potential.

### Still open
- `SHARE` sensitivity untested where it matters (4× swing on P(#1)).
- `A104_HS_CUR`, `A104_HS_GAP`, `OBP_W`, `OBP_DEN` are not wrapped in `C()`, so G5
  cannot see them.
- A115 remains open: 68 arms counted differently, 29 role verdicts flip, 1.967 career
  WAR per disputed pitch.

---

## 1.2.0 — 2026-09-20 (G11: the board states its own bias)

Live draft, 1977. The board ranked **Alan Reames #1** while printing `P(POW55) 0.0%`
on his own row. Nothing was hidden and every number was right. **The sort was the claim.**

The default sort is `E[WAR]`, and A104 is fitted on **career WAR** — which rewards being
adequate for a long time. Its gap coefficient is **negative for college bats (JR −0.209)**:
a large current-to-potential gap *lowers* the projection. In the 1977 pool that produced:

| | POT★ | E[WAR] |
|---|---|---|
| Marty Teixeira | **5.0** | 27.5 |
| Alan Reames | **2.5** | **28.1** |

A 2.5-star projecting above a 5-star is not a bug in A104 — it is A104 answering the
question it was fitted on. But the board was silently recommending floor over ceiling,
which is the opposite of what the GM had said he wanted, and nothing on the sheet said so.

**G11.** Every board now carries **two** ranks per side, never one:

- **floor rank** — `E[WAR]` (bats: `+pos`)
- **ceiling rank** — `P(both)` for bats (A94's two bars together), `P(#2)` for arms (A112)
- **profile** — `FLOOR` / `BALANCED` / `CEILING`, set when the two percentile ranks differ
  by **≥ 0.25** (two quartiles)

Added to `BOARD`, `BATS` and `ARMS`. A104 is untouched; no coefficient changed; nothing
was removed. The tag is a description of the board, not a recommendation — which axis to
buy depends on the club, the park and what is left in the pool. The point is that the sort
can no longer make that choice without saying it did.

`BOARD`'s key-number column now leads with **P(both)** for bats, not P(POW55) alone — one
bar cleared is not the bar.

### Defect found and fixed during the same session

The first real run exposed it: on a **LEAGUE** export `E[WAR]` is deliberately `None`
(A104 is a draft-day model), so the floor sort fell back to **input order** and tagged
every player `BALANCED` — a meaningless rank printed as a real one, which is precisely
what this guard exists to prevent. A rank that cannot be computed now says
`n/a -- E[WAR] is draft-day only (A104)` and the rank cells are empty.

Six checks added (section 16), 66 → **72**.

### Still open
- `SHARE` sensitivity untested where it matters (4× swing on P(#1)).
- `A104_HS_CUR`, `A104_HS_GAP`, `OBP_W`, `OBP_DEN` not wrapped in `C()`, so G5 can't see them.
- **A94's OBP index has a hole.** V. Dones (EYE 70) indexes 52.9 → 79 wRC+; A. Proctor
  (EYE 60, CON 45, BABIP 55, POW 55) indexes 53.9 → 129 wRC+. One index point apart, 50
  wRC+ apart. The index weights EYE 0.254 against CON 0.182. Not yet fixed.
- A115 still open: 1.967 career WAR per disputed pitch.

---

## 1.2.1 — 2026-09-20 (G12: an arms-only pool must say why it cannot be scored)

Found on the first live run of 1.2.0. A pitchers-only draft export came back stamped
**"detected POOL"** with an `E[WAR]` column that was **empty on every row**, and nothing
anywhere explaining it. The G11 ranks correctly refused to invent a floor rank, but the
user was left looking at a workbook that read as a broken tool.

The cause is structural and correct: **A104 publishes coefficients but no intercepts.**
The arm intercept `a0` is derived from the **bat mean of the same pool** —

```python
bat_mean = statistics.mean(p['ewar'] for p in bats)
a0 = bat_mean * (_pooled('ARM')/_pooled('BAT')) - mean(_arm_raw(p) for p in arms)
```

— so with no batters there is no scale to place the arms on. Refusing was right.
**Doing it silently was not** (methodology rule 22).

**G12.** `score()` now writes an `ewar_blocked` explanation onto every player, and
`write_workbook` prints it in red on the KEY sheet:

> E[career WAR] NOT COMPUTED — this export contains NO BATTERS. A104 publishes no
> intercepts, and the arm intercept is derived from the bat mean of the same pool, so
> arms cannot be placed on a career-WAR scale without them. Every other column is
> unaffected. Re-export the whole pool to get E[WAR]. (G12)

Every other column — gates, arsenal, A115 conflicts, P(ace)/P(#1)/P(#2), percentiles —
is computed normally and is unaffected. Three checks added (section 17), 72 → **75**.

**Pattern worth naming:** G9, G10 and G12 are the same failure three times over — the
tool knew something the workbook didn't say. The guard is never "compute it anyway", it
is always "say what you could not do and why."

---

## 1.2.2 — 2026-09-20 (speed: 3.4× faster, zero numbers changed)

A 172-player draft pool was taking **several minutes** on the VPS. Profiled rather than
guessed:

| | seconds of a 40.7 s pool run |
|---|---|
| `simulate()` — 172 players × 20,000 sims | 30.7 |
| **`sorted()` inside `pct()`** | **7.4** |

`pct(v, q)` sorted its input on every call, and P10/P50/P90 each called it on **the same
20,000-sample list** — so every tool of every player was sorted three times. A tool with
no development gap is a point mass, and those 20,000 identical values were being sorted too.

**`pcts(v, qs)`** sorts once and returns every quantile, and short-circuits a point mass
without sorting at all. Sorting is not a random draw, so the seeded sample sequence is
untouched.

**172-player pool: 40.7 s → 12.1 s.**

**Proof that no number moved:** the old and new modules were both run over the same pool
in one process and compared player by player on `E[WAR]`, `P(POW55)`, `P(both)`, `P(#2)`
and the P50s — **172 of 172 identical, zero differences.** Three checks added (section 18)
asserting `pcts` matches `pct` on every quantile, short-circuits a point mass correctly,
and does not mutate its input. 75 → **78**.

The remaining 30 s is `simulate()` itself, which is 20,000 draws per live tool by design.
Cutting `NSIM` would be the next lever and **would** change published probabilities, so it
is not being done quietly — it needs a decision and a registry note.

Page copy updated: a league file now reads ~30 seconds rather than ~90.

---

## 1.2.3 — 2026-09-20 (G11 fix: a zero ceiling is not a rank question)

Caught on the first 1.2.1 pool run of the live 1977 draft.

**Alan Reames read `BALANCED` at board #1 with `P(both) 0.0%`.** The percentile gap
between floor rank 1 and ceiling rank 17 across 84 bats is only 0.19 — under the 0.25
threshold — so the tag said "balanced" about a player with a **literal zero** on the
ceiling bar. That is the precise case G11 was built to catch, and G11 missed it: the tag
was measuring *rank distance* when what mattered was the *value*.

**Fix:** a ceiling number of zero forces `FLOOR`, whatever the ranks say.

```python
if ceil_key(p) <= 0.0:
    p['profile'] = 'FLOOR'
```

Effect on the 1977 pool: `BALANCED 115 / CEILING 33 / FLOOR 24` → **`FLOOR 105 /
BALANCED 34 / CEILING 33`**. That is not an over-correction — **105 of 172 players in
this class have no measurable chance of clearing the quality bar for their side**, which
is the same thing the commissioner said in plain English: *"it's not deep with really
good prospects, it's deep with okay prospects."* Two checks added, 78 → **80**.

### ⚠ Known, unfixed: results depend on ROW ORDER

One seeded RNG (`SEED = 1977`) is shared across all players in file order, so the same
pool sorted differently hands each player a different slice of the stream. Observed on
the same 172-player class exported two ways: **Hopman P(#2) 28.2% vs 27.9%, Casares
P(POW55) 6.5% vs 6.6%** — inside Monte Carlo noise, but not reproducible.

Per-player seeding (`Random(SEED ^ hash(name))`) would make every number order-independent
and is the right fix. It **would** change every published probability slightly, so it is
not being done quietly — it needs a decision and a registry note, same as `NSIM`.
