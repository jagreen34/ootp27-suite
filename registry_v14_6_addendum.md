## v14.6 Addendum — Draft Board: Delivery Discount, Scouting Surfacing, Glove WAR (May 29, 2026)

Session built three additive layers onto the deployed Draft module (`draft.py`,
served at ootptools.com/27/) and surfaced one real correction to a defensive
assumption. Nothing in this addendum changed the F2 scorer or any locked formula —
all three layers are **display/annotation only and never reorder the BPA rank.**
Source modules: `acquisitions.py` (helpers), `draft.py` (UI). Three smoke suites
green; integration tested through `prep_draft_pool` → `build_board`.

---

### A16 — Delivery-Discount View on the Draft Board (Deployed)

**What.** A second WAR view beside Career WAR. **Career WAR** = F2 on CURRENT
ratings (the conservative floor — what the prospect IS). **Disc WAR** = the same
F2 re-scored on EXPECTED-MATURE ratings:

```
expected = current + (potential − current) × delivery_factor × age_mult
```

then F2 on those discounted ratings. **Growth-bet = Disc − Career** is the
surfaced signal: the projected upside that survives the haircut (▲/▲▲ glyphs scale
with the gap, colorblind-safe). Large for toolsy teens, ≈0 for finished college
bats. Additive — Career WAR remains the primary BPA rank; Disc never reorders.

**Factors (registry-locked production-discount means, applied here).** Batter CON
.48 / GAP .48 / POW .45 / EYE .28; pitcher CON .43 / STU .53 / MOV .40. EYE is the
outlier (OOTP 27 under-delivers projected eye discipline, 28% vs 40–53%). Only
these seven ratings are discounted. **SPE/STM** (no potential column / no growth
claim), pitch grades, AGE, amateur, personality, HSC, and **all fielding** stay at
current — outside the locked study.

**Age multiplier (`delivery_age_mult`).** Expresses the registry's
"younger-draftees-deliver-2–3×" finding as a shared multiplier on the locked
factors: 1.0 at ref_age 19, slope 0.15/yr, clamped 0.50–1.50 (≈2.4× end-to-end
span, honoring "2–3×"). Calibrated on the ONLY age-stratified data in the registry
(pitcher CON, 57%@17 → 22%@21) and **generalized across all seven ratings** — this
generalization is an assumption, flagged for revisit at the AC re-fit. Effective
factor = base × age_mult, capped at 1.0; discounted rating clamped to [current,
potential].

**No double-count on AGE.** AGE is identical in both feature vectors (real AGE kept
in Career and Disc), so the strong negative AGE coefficient CANCELS in the
Disc − Career gap. The age multiplier modulates only credited growth (a different
channel than the level effect AGE captures). Complementary, not redundant.

**Caveat.** Factors are population means with ±5–10pt individual SD — a calibration
anchor for expectations, not a per-prospect guarantee.

**Fail-loud.** When the pool carries no potential columns, Disc shows Career
unchanged and Growth-bet shows `—`, with a visible warning — never a silent
Disc==Career masquerading as a real haircut.

---

### A17 — Scouting Columns Surfaced on the Draft Board (Deployed)

Display-only fields that were already in the prepped data (or in the export) but
not shown. **None feed the F2 scorer.**

- **B/T** — bats / throws (`B`,`T`). Degrades to `—` if absent from export.
- **STM** — stamina, pitchers. Always present (it is a pitcher F2 input).
- **#P** — usable pitch count = `cnt_eff_pitches` (grade ≥ 30, the registry
  usable-pitch boundary). Surfaced on the Pitch Grades tab alongside Velo/Top.
  Read pitch VALUES, not the count: low-grade pitches are phantom depth.
- **Def** — position-appropriate fielding line (range·arm·error; catchers
  ability·arm·framing), scored at LISTED position.
- **Inspect card** — full arsenal (pitchers) or full fielding block (batters) on
  demand via selectbox.

**Export dependency (load-bearing).** Handedness (`B`/`T`) and the fielding block
(`IF_RNG`/`OF_RNG`/`C_ABI`…) are NOT model inputs and only appear if present in the
OOTP export. The column audit reports them as non-blocking; the board shows `—`
plus a note naming the missing field, never a silent `0` that reads like a real
20-grade rating. STM is guaranteed (model input).

---

### A18 — Glove WAR + Best-Fit Position on the Draft Board (Deployed)

**Closes the draft board's defensive blind spot.** F2 sees batter defense ONLY
through a flat position dummy → a 75-range SS and a 40-range SS scored identically.
This layer surfaces the glove using the deployed, sim-validated per-position ZR
models (A12 / `ZR_MODELS` → `def_war`). **Additive; never reorders the BPA rank.**

- **Glove (column).** `def_war(listed_pos)` = DEF_WAR vs an AVERAGE glove there
  (ZR is centered, so 0 ≈ average; ◆ asset / ◇ liability / · ≈avg). Because ZR is a
  deviation-from-average and the F2 position dummy already credits the average
  fielder, Glove WAR (the deviation) is **de-double-counted by construction** —
  which is also why it stays a side column rather than folding into the rank.
- **Fit (column).** Best-fit position. `✓` when listed = best fit; else `→POS`
  with the WAR left on the table at the listed spot.

**Best-fit logic (`best_fit_position`).** Since the bat is identical at every
position, it cancels — best fit = argmax of `def_war(pos) + pos_adj_fixed(pos)`
over ENGINE-ELIGIBLE positions (ratings ≥ floor, `POS_SKILL_REQUIREMENTS`; the only
real discontinuity — "the game won't roster him there"). Per A12, defensive value
is a **soft tax, not a hard wall** (premium positions punish a bad glove only ~1.2×
harder; smooth slope; no quality cliff), so the layer scores continuously and never
gates on quality.

**Relocation guards (added after the build surfaced spurious moves).** The
per-position ZR models are fit independently and observed ZR is a season ROLLUP
(see A19), so cross-position magnitudes are imperfectly calibrated at the extremes
— the first run wanted to move a 75-range SS to 2B for a +0.12 noise gain. Two
guards:
  1. **Defensive-spectrum guard** (`_DEF_SPECTRUM` hardest→easiest): won't move a
     player DOWN the spectrum on a sub-margin gain (`_BESTFIT_RELOCATE_MARGIN` 0.40
     WAR); UP the spectrum needs only to win outright.
  2. **Liability override** (`_LISTED_LIABILITY_ZR` −0.30): if the listed-position
     glove is a negative (genuinely miscast), free him to relocate on ANY positive
     gain — this is what moves a 45-range "SS" to 3B while keeping the 75-range SS
     at short.
Never relocates a non-catcher TO catcher (C requires C_ABI; weak model — below).

**Catcher caveat (CERA reconfirmed dead).** The C ZR model is near-useless
(R²=0.037) because the engine barely varies catcher ZR (SD 2.84) — not a
measurement gap, the engine genuinely flattens catcher defense. **CERA is NOT a
substitute (A8: debunked — CERA reflects the staff/defense around the catcher,
absorbed by pitcher PBABIP, not catcher skill).** Catcher Glove WAR is
small-by-construction and flagged low-confidence; evaluate the bat + framing/arm
tools directly.

**Note.** This substantially delivers the previously-queued "ZR-feasible best-fit
position ranking" task for the draft side (the My Team ZR-flex model, ported).

---

### A19 — Defensive Ratings: Range DECLINES (correction to "fixed"); Per-Position ZR Validation Open

**Correction to a prior verbal claim.** Earlier framing called defensive range
"fixed." That is wrong as stated and is corrected here. What the OOTP 26 study
established was that range does not **develop upward** — draft-day range ≈ prime
range (r ~0.96–0.99), and the DEF READY label is "essentially permanent" *on the
upside*. It said **nothing about decline.** The aging work (3C-6) is WAR-by-age and
offensive ratings only; **range decline with age was never measured.**

**Standing finding (qualitative, unquantified).** Range almost certainly DECLINES
with age — it tracks foot-speed, and the engine clearly decays athletic/offensive
ratings (batter peak 25–27, decline from 32, K-T ~15% steeper). No reason range is
exempt. So the accurate statement is: **range is locked going UP (won't develop),
but NOT locked going DOWN (declines, magnitude unknown).**

**Consequences.**
- The "value the glove at the draft" logic SURVIVES and is arguably strengthened —
  you still cannot manufacture range later, so draft-day range is a depreciating
  asset best acquired young at full value.
- But Glove WAR (A18) is a **present-tense** number — the glove at draft age, which
  for a young prospect is also prime. It is NOT a career-long guarantee at the
  position. A glove-first SS drifts down the spectrum (SS → 2B/3B → corner) with
  age, same as real baseball. The defensive "floor" under an aging bat erodes —
  do not treat a premium-position glove as a durable floor for OLDER draftees.

**OPEN — per-position ZR validation (parked).** Concern: exported ZR is a SEASON
ROLLUP across every position a player logged, so per-position ZR coefficients
(`ZR_MODELS`) are trained on contaminated targets. Eligibility flags do NOT
identify single-position players (most SS show eligible at 2B). The clean fix needs
a **games-by-position count** to filter to genuine single-position seasons; that
field is visible on the player card but **unconfirmed as exportable**. Decision
tree (parked, not run this session):
  - If games-by-position **exports** → filter to single-position players by actual
    games (ignore eligibility), re-fit per-position ZR, compare to current
    coefficients. Script-level task.
  - If it **does not export** → the contamination is unfixable by filtering; the
    justified method is a **targeted position-LOCK experiment** at the up-the-middle
    spots only (SS/2B/CF/3B — where contamination bites; corners/1B trivial,
    catcher hopeless), one or two locked single-position seasons, to produce clean
    training data. NOT the large multi-position multi-season sweep.
Until validated, the current ZR models are **kept as-is and NOT baked into the
rank** — they already reconstruct real players closely (e.g. a 73–75 IF_RNG SS →
predicted +16–20 ZR → 2.5–3.5 WAR, matching observation). Baking defense into the
F2 rank (an F2 refit with a de-double-counted defensive term) is gated on this
validation AND a range-decline curve, and is explicitly NOT recommended for the
draft board regardless (the Glove/Fit columns are designed to keep the growth/
defense BETS visible — collapsing them into one number hides the decision, same
rationale as keeping Disc separate). The all-in WAR belongs in My Team / lineup
construction, where total value is the right question and the full OFF+DEF+POS_ADJ
reconstruction (R²=0.738) already does it.

**Related open follow-up.** A "best-bat-anywhere vs best-value-with-fit" roster
simulation (does loading the best bats regardless of position out-WAR a positional-
fit roster?) was raised and parked — needs roster-level sim runs, lower priority,
sits behind the ZR validation.
