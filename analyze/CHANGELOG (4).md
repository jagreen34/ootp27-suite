# ootp_analyze — changelog

## 1.7.0 — 2026-09-22 — three rounds of adversarial audit, and two GM corrections

**284 checks** (was 96 at the start of the day). **1.4.0, 1.5.0 and 1.6.0 were each
reviewed before deploy and none of them shipped.** Everything below is what the reviews
and the GM found.

### The two that mattered most came from the GM, not the audit

> **"POS is the engine's defined position. A player can have a LF pos and play 1b, LF, RF, etc."**

1.5.0 had replaced the acquisition gate with `POS` and called it *"the position he
actually plays."* It is a **designation**. The fielding block is no help either — it is a
season total summed across every position a man appeared at (per-ORG non-pitcher IP ÷ 9 ÷
games = 8.03, exactly the nine slots; `TC == PO+A+E` for 100% of rows). There is no
per-position line anywhere in 257 columns and **53% of fielders are provably
multi-position. The split is not recoverable from this export**, and the KEY sheet now
says so instead of implying otherwise.

> **"for fielding we should only use IFR, OFR etc"**

A putout-rate override (`PO×9/IP` separates first base cleanly — median 9.99 against 2.39
for the next position) was built and then **removed**. Fielding is the ratings. The tool
now reads no fielding counting stat anywhere, and a self-test enforces it against
`__code__.co_consts` rather than against memory.

> **"if you see sp rp cl that means you are looking at role not position for pitchers"**

`SP`/`RP`/`CL` are **roles**. `pos_runs_600` now **refuses** one outright (G18) instead of
returning the `.get` default of 0.0, which read on the sheet as "an average position."
ROSTER's column is renamed `priced at` → `slot` and documented as position-for-bats,
role-for-arms.

**None of these was a coding error. Each was correct code implementing a wrong idea — the
class no mutation score can see.**

### G16 — the acquisition gate was pricing the lineup card, and the first fix was one-sheet

`lands` answers *where a glove can be bought to play*. It was keying the positional runs.
396 of 860 bats land somewhere other than their listed position; 169 differ by more than
4 runs/season. D. Tislow, listed at shortstop with 453 PA, was priced at first base —
**13.94 runs, ~11 career WAR**.

1.5.0 fixed it on ROSTER and left `pos runs/season` and `pos career WAR` on the gate, so
the BATS sheet carried three columns labelled "pos" on one row disagreeing by 13.94 runs.
All three now derive from one key, `priced_at`, in one place. **Live file: 0 of 860 rows
disagree, down from 169.**

### The ceiling rank was input order — twice

818 of 860 bats have P(both) = 0.0%. Ranking them produced one tie block resolved by
**alphabetical input order** — ranks 43 through 860. That is G17's own failure mode
shipped as the fix for a different one. Fixed on the league branch; the **pool** branch
kept it, on the sheet a draft pick is made from (68 of 84 bats, ranks 17–84). Both
branches now leave the zero block unranked and tagged `NO CEILING — clears the bar in 0 of
20,000 simulations`. The rank is also side-qualified (`BAT 12` / `ARM 41`) on ROSTER *and*
BOARD — unqualified, a catcher and a reliever both read "rank 1," affecting 49% of ranked
rows on the pool board.

### The error bar: a fit withdrawn, a table published

`WRC_NOISE_K = 291` dropped the largest band (350–450, n=100) from its own fit, and
`k = SD·√PA` came out **308 / 265 / 278 / 210** — not constant, so the model was
misspecified. Withdrawn. `WRC_NOISE_SD` is now a measured step table (28.3 / 19.5 / 16.2 /
10.5 wRC+), pinned to literals, bounded above by the total dispersion it was extracted
from. At 125 PA the bar is **17.8 runs against a 16.64-run positional spread** — that is
the finding, and it is why the column exists.

### Found by the tool's own new coverage

The generated per-column sweep (every column, every sheet, both export kinds) immediately
found that **GATED BATS and GATED ARMS have shipped a probability column with
`number_format = 'General'` since 1.0** — G2, on two sheets no test had ever opened.

### The tests, three rounds running

| | 1.4.0 | 1.5.0 | 1.6.0 | 1.7.0 |
|---|---|---|---|---|
| checks | 117 | 141 | 189 | **284** |
| independent mutation catch rate | 5 of 7 shipped | 36% | 48% | **~90% projected** |

Each round the reviewer found assertions of mine that **could not fail**: `'lands' in
('lands',)`; `bat_runs_600(130) == bat_runs_600(130)`; `X or Y or True`; a width check
reading `iter_rows(values_only=True)`, which **pads every row** so `len(r) == len(headers)`
always; a percent check asserting `0 ≤ v ≤ 100`, which **a fraction also satisfies** —
inside the check written to stop exactly that.

Structural answers, not patches: the width guard and the heading resolver moved to module
level so `verify()` drives the shipped code instead of a copy; fixtures now span the
branches they claim to test (the live-ceiling path was never executed, which is why an
inverted rank shipped clean; the fixture arm had `p_ace == p_no2 == 100%`, which is why
ranking arms on the wrong bar was invisible); a POOL frame is driven end to end through
the BOARD; and **`MIN_CHECKS` fails the build if the suite ever shrinks** — a generated
section that stops generating otherwise prints a smaller number and the word PASSED.

> The 2026-09-19 conclusion, earned three more times: **the tests tested what the author
> remembered.** The memory was just one review newer each time.

## 1.5.0 — 2026-09-22 — what the adversarial review found in 1.4.0

**141 checks** (was 117). **12 of 12 decision-grade mutations now caught; 5 of 7 shipped clean before.**

1.4.0 was reviewed before deploy by two independent passes — one hostile code review, one
re-derivation of the statistics from scratch. Both found real defects. 1.4.0 was never
deployed. Everything below is what changed.

### G16 (new) — the acquisition gate was pricing the lineup card. 45% of the league.

`lands` is where a glove **clears A108's gate** — an acquisition question. It was also
driving the positional runs column on ROSTER, which is a **lineup card**.

| | |
|---|---|
| rostered bats whose landing spot ≠ position played | **279 of 619 (45.1%)** |
| of those, swinging more than 4 runs/season | **120** |
| everyday players (>350 PA) repriced | **67** |

D. Tislow plays shortstop with **453 plate appearances** and was priced at first base,
−10.87, because his range is 55 against A108's bar of 65 — a **13.94-run error, ~11 career
WAR**, on a man his club plays at short every day. The gate is right about acquisition and
irrelevant to what the club is already getting.

**This is G6 with the names changed, and G6 was already written.** On a LEAGUE export the
runs columns now use the position actually played; `lands` keeps its own column and its
acquisition meaning. A pool has no playing-time record, so `lands` still governs there.

### The "(NO pos)" column contained a position term

1.4.0 computed `bat_runs_600(wrc) × PT_RATIO[landing]`. The same bat read **39.69 at first
base and 33.34 at catcher** — a 6.35-run spread driven entirely by the position the column
claimed not to contain, in the one column built so the position could be read separately.
The KEY sheet stated the opposite in as many words.

Both reviewers found this independently. The playing-time scaling was also where the units
went soft: **A74 publishes runs per 600 PA, and A114's ratio is PA relative to FIRST BASE,
not to 600.** They agree only because a first baseman's projected full season happens to
land near 600 PA — correct to ~2%, by coincidence, and it would break silently the moment
A114's partial-season ratios are refit (A114 §5 flags them as unhardened).

**Everything on the sheet is now per 600 PA**, which is A74's own denominator. `PT_RATIO`
survives only where A114 actually requires it — the conversion to career WAR (G8), untouched.

### `± 1 SE` (new column) — the error bar, measured on the AC

wRC+ dispersion of rostered bats by playing-time band, excess over the ≥450 PA band:

| PA band | total SD | implied noise SD | in runs |
|---|---|---|---|
| 100–150 | 38.5 | 28.3 | **17.7** |
| 150–250 | 32.7 | 19.5 | **12.3** |
| 250–350 | 30.8 | 16.2 | **10.1** |

**The entire positional spread, catcher to first base, is 16.64 runs.** Below ~250 PA one
standard error is most of it. The decomposition is confounded — band means climb 76 → 122,
so better players simply play more — which makes these an **upper** bound; the number is
published as an error bar and never used to change the score. This is Rule 12 in the bat
column's own units.

*Calibration (Rule 29, outcome on prediction, 211 regulars ≥300 PA): regressing realized WAR
on predicted wins gives **slope 1.147, r = 0.826, residual SD 0.99 WAR**, intercept +2.26
(replacement level). The scale is right and mildly conservative, which is the correct
direction for an offense-only predictor of total WAR.*

### G17 (new) — the column the rank is built on must exist

1.4.0 made WAR the rank of a single flat list and **nothing checked that WAR was in the
file**. Absent, every player sorts to the bottom on a `None` and the `#` column numbers the
**input order** while looking exactly like a ranking. A LEAGUE export with no `WAR` is now
refused; `WAR` without `WAR_1` is a named warning (every pitcher would read blank and sort
to the bottom).

### The blanks now say which refusal they are

Three different reasons — G14 (under 100 PA), G15 (fill value), G7 (draft pool) — arrived as
one undifferentiated empty cell. A `bat score note` column names each. On the live file:
**266 G14, 233 G15.**

`bat_runs` also no longer matches the fill value with `int()`, which truncated the whole
interval **[100, 101)** and silently discarded real measurements at 100.4 and 100.9; and a
non-finite wRC+ no longer raises `ValueError` mid-build (CLI traceback, web 500).

### G7 — the bat score was running on draft pools against a major-league mean

Nothing gated it on `fr.kind`. A 19-year-old amateur at wRC+ 145 priced at **+19.72 runs**
against `WRC_MEAN = 110.8`, the AC's full-time **major leaguer** mean. That is the error G7
exists for. Refused, by name.

### Ceiling rank is no longer thrown away with the floor rank

The 2026-09-20 fix correctly refused to fake a floor rank on a league export — and discarded
the **ceiling** rank too, which `p_both`/`p_no2` make perfectly computable. Three advertised
columns were dead on the only export kind that produces them. The ceiling is now published
and the profile says which rank you are looking at.

### Sheet hygiene — two things review found correct *by luck*

- Percent columns were assigned to hand-counted letters (`'W'`, `'X'`, `'Y'`…) that had to be
  re-counted every time a column was inserted. They are now located **by heading**, and a
  missing heading is a hard failure — a probability shipped as a raw fraction is G2, and G2
  has cost us once already.
- Nothing checked that a row emitted as many cells as its header list. A row one cell short
  does not raise; openpyxl leaves the tail blank and **every value after the gap sits under
  the wrong heading**. The player grids are now width-checked.

### The 1.4.0 self-tests did not test the 1.4.0 code

This is the finding that matters most, because it is the one that would have let everything
above ship again. Review mutation-tested the suite:

| mutation | 1.4.0 suite | 1.5.0 suite |
|---|---|---|
| invert the rostered flag | **ships** | caught |
| rank the FA pool above the rostered one | **ships** | caught |
| swap the bat and pos cells on ROSTER | **ships** | caught |
| shift a percent-format column | **ships** | caught |
| price off the gate instead of the position played | **ships** | caught |
| put PT_RATIO back in the bat column | — | caught |
| drop the G14 / G15 / G7 refusals | 2 of 3 | caught |
| drop the WAR requirement, let a non-finite through | — | caught |

Every check in sections 20–22 had **re-implemented the logic inside the test** — pasting a
copy of the sort lambda and sorting a literal list, rather than calling the production path.
Two were literal tautologies (`'lands' in ('lands',)`). They now drive a real frame through
`build()` and `write_workbook()` and read the cells back out of the written file.

> The 2026-09-19 review's conclusion, earned a second time: **the tests tested what the
> author remembered.**

### Correction to the 1.4.0 write-up

The 1.4.0 notes and the project finding cited *"T. Davis (1B, **174** wRC+) → +47.2 bat
runs."* Davis is **186**; 174 is R. Turner, a different row. The tool was right and the prose
was wrong. Corrected in the project doc.

## 1.4.0 — 2026-09-22 — the bat, priced without the position

**117 checks** (was 96).

### The ask
> "show the score without the position adjustment"

The ROSTER sheet carried `pos runs/season (A74×A114)` — the penalty — with nothing to
apply it to. A first baseman's bat and a shortstop's bat could not be compared.

### `bat runs/season (NO pos)` — new column on ROSTER and BATS

A74 did not invent its positional adjustment. It **derived** it from the mean wRC+ of
full-time players at each position (37,650 player-seasons, league mean 110.8):

| pos | mean wRC+ | A74 adj |
|---|---|---|
| C | 101.6 | +5.77 |
| SS | 105.9 | +3.07 |
| 3B | 106.8 | +2.51 |
| CF | 108.3 | +1.56 |
| 2B | 108.9 | +1.19 |
| RF | 112.1 | −0.82 |
| LF | 114.8 | −2.52 |
| 1B | 128.1 | −10.87 |

That is a straight line through the origin. Its slope reads back off A74's own table by
least squares: **0.6280 runs per wRC+ point per 600 PA**, reproducing all eight published
adjustments to within 0.011 runs (worst: CF, 1.570 vs 1.56). This is not a new model — it
is A74 read in the other direction.

```
bat runs/season (NO pos) = (wRC+ − 110.8) × 0.6280 × PT_RATIO[position]
total runs/season        = bat runs + pos runs
```

Both halves are scaled by the **position's** playing time (A114), not the individual's, so
the two columns are directly addable and an injured player is not priced as a part-timer
for life.

**⚠ This is NOT engine WAR minus A74.** A114 §1 records that the engine's WAR already
carries "whatever positional credit the engine applies." A74 measures a different thing —
the bat a club will *tolerate* at the spot. Subtracting one from the other mixes two
systems and yields a number with no referent. The bat score is built from wRC+ alone and
never touches the WAR column; a self-test asserts it.

### ROSTER is one flat ranked list

Through 1.3.1 the sheet was **grouped** — C, SS, 2B … 1B, then arms — so comparing a first
baseman with a shortstop meant scrolling past six position blocks. It is now a single order
ranked on the engine's own WAR, the only scale in the file that prices bats and arms in the
same currency. `lands` survives as a column, so the old grouping is one Excel click away.

### G14 (new) — the bat score is blank under 100 PA, never zero

wRC+ is a rate. A man with 23 PA and a 180 wRC+ prices out at +44 runs/season and tops the
sheet. A114's positional means are taken on 326–388 PA. A zero would read as an average
bat — a stronger claim than "not enough plate appearances to say."

### G15 (new) — wRC+ 100 is a FILL VALUE

**Caught on the live 1,547-row AC file before shipping.** 753 of 1,547 rows carry wRC+
**exactly 100**. That is not a distribution — the next most common value appears 8 times.
OOTP writes 100 where it has none to publish. Split by organisation the tell is decisive:

| | n bats | read exactly 100 | |
|---|---|---|---|
| ORG assigned | 649 | 174 (26.8%) | **every one has PA ≤ 65** |
| ORG `-` | 247 | 240 (**97.2%**) | PA up to 414 |

For rostered players G14's plate-appearance floor already removes them. For the unassigned
pool it does not, because **their PA is real and only the rate is fake**. J. Keller (201 PA)
and M. Teixeira (414 PA) both priced out at exactly league average, which looked entirely
plausible on the sheet.

G15 also **sorts** ROSTER: rostered players first, the FA / unassigned pool below them, WAR
ordering within each, and a new `pool` column saying which. A flat WAR sort had put two free
agents at #2 and #3 on WAR earned at another level. Same family as G3.

*The silent-failure family again: a placeholder read as a measurement. The number was not
missing and not obviously wrong — it was plausible, and it was everywhere.*

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

---

## 1.3.0 — 2026-09-22 (⛔ glove gates corrected · ROSTER sheet · G13)

### ⛔ THE GLOVE GATES WERE THE PARQUET VALUES, CITING THE REVERSAL THAT OVERTURNED THEM

`GATE_SS = 60` and `GATE_2B = 55`, with the source string
`"THE_RULES_pocket rule 5 / A108 REVERSAL"`.

| source | SS | 2B | CF | dated |
|---|---|---|---|---|
| `THE_RULES_pocket.md` rule 5 | 60 | 55 | 65 | **2026-08-26** |
| **A108 REVERSAL** (AC innings-weighted means 67.1 / 60.7 / 65.0) | **65** | **60** | 65 | **2026-08-28** |
| `A84_ingame_filter_recipes.md` v3, derived independently | **65** | **60** | 65 | 2026-08-28 |

**The pocket card predates A108 by two days and was never updated.** A108's entire finding
is that **SS 60 / 2B 55 are the PARQUET positional means applied to AC players** — and the
tool carried that exact pair while naming A108 as its authority. A108 verified its values
across two exports eight days apart with all three methods agreeing; A84 v3 reproduced them
the same day.

**Cost, measured on the 1,547-row league file:** **88 of 620 position players (14%) landed
at the wrong position.**

| move | n |
|---|---|
| SS → 2B | 41 |
| **2B → 1B** | **37** |
| 2B → 3B | 10 |

`lands` drives the A74 position credit, so each of the 37 was being paid **+1.19 runs/season
(2B)** instead of **−10.87 (1B)** — a 12-run error per player. On Philadelphia, **R. Turner
(174 wRC+, the club's best bat) read 2B and is a 3B**; D. Snyder read 2B and is a 1B.

**Corrected to SS 65 / 2B 60. CF 65 was right in every source and is unchanged.**

**The self-test caught the change and refused to build** — two checks in section 4 encoded
`IF RNG 60 -> SS` and `IF RNG 55 -> 2B`, the parquet values. They now pin A108's numbers and
test **both sides** of each boundary, including the R. Turner case (`IF RNG 55 + IF ARM 70
= 125 -> 3B, not 2B`). That is rule 22 working: a constant could not move without a human
deciding it should.

**⚠ `THE_RULES_pocket.md` rule 5 is stale and still says SS 60 · 2B 55.** It needs a
reversal banner pointing at A108. Not done here — it is a registry doc, not tool code.

### NEW — the ROSTER sheet (league files only)

Current value and future value on one row, grouped by where the glove actually plays:
`lands · Name · ORG · POS · Age · OVR* · POT* · PA/IP · wRC+ / FIP- · WAR ·
pos runs/season (A74×A114) · key tool now · P50 · P90 · ceiling % · ceiling rank · gate`

Sorted C · SS · 2B · 3B · CF · RF · LF · 1B · SP · rp, then by WAR.

It deliberately **does not invent a combined score.** A104's E[WAR] is a draft-day model and
is not computed for established players (G12); there is no measured way to add "what he is"
to "what he might become". The two sit side by side and the GM weighs them.

### G13 — every tool and every potential column is checked

`check_columns()` validated `Name/POS/Age` and warned on four glove columns. It said nothing
about the **ten tool/potential pairs that drive every probability**. A missing potential
column is not an error anywhere in `build()`:

```python
pot[key] = max(c, p if p is not None else c)   # no potential column -> pot = cur
```

so the tool silently never develops and its upside reads as zero, while the workbook looks
complete. Every pair is now checked and any absentee is **named** in the notes, distinguishing
a missing tool ("scores 0, every probability using it is wrong") from a missing potential
("FROZEN at current, upside reads as zero").

**Known and expected:** OOTP publishes **no BABIP potential** — the export's potential block
is HT/CON/GAP/POW/EYE/K. BABIP is frozen by the data, not by choice. It carries 0.085 of the
A94 OBP index. Stated on the KEY sheet rather than discovered.

80 → **96 checks.**

---

## 1.3.1 — 2026-09-22 (the landing spot is auditable on its own row)

`ROSTER` now carries the **pure tools** that produced `lands`, beside it:

`IF RNG · IF ARM · OF RNG · OF ARM · TDP · C ABI`

**Why these and not the position ratings:** A113 — the `1B/2B/3B/SS/LF/CF/RF` columns in
the export are a **playing-time record**, not ability, and a player can carry no position
rating at all at a spot he is perfectly able to play. These six exist for every fielder
regardless of where he has happened to appear, and they are what the gates actually read.

Effect: every landing spot can be checked without leaving the row. R. Turner reads
**3B** and the row shows **IF RNG 55 / IF ARM 70 = 125**, over the 120 bar — the A108
correction visible in place. Neyland reads SS on IF RNG 70; Paige on 65, exactly at the
gate.

Arms get blanks in these columns rather than zeros, so a sort on IF RNG does not bury the
pitchers among genuinely rangeless fielders.
