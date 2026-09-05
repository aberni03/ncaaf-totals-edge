# NCAAF Totals Model — Rebuild & Backtest

Reproduction of the `ncaaf_datafile 2025.xlsx` model using public data
(CollegeFootballData.com API), 2015–2024, with a leak-free walk-forward backtest.

## What the original model does
Two stages:
1. **Physical projection** (`Single Game Input`): opponent-adjusted per-play efficiency
   ratings (Yards/Pass-Att & Yards/Carry, offense & defense) × pace (`TR input`) ×
   pass/run tendency → projected pass/rush attempts & yards per team.
   Efficiency formula: `YPA = OffRating × OppDefRating / league_avg`.
2. **Neural nets** (`Pts Neural Net`, trained in JMP): a 3-node tanh net maps
   {Vegas spread, Vegas total, projected drivers, tempo} → predicted total points.

Because the net takes the **Vegas total as an input**, it is a market-*anchored adjuster*,
not an independent predictor.

## Rebuild
- **Data:** CFBD games, betting lines (open+close spread & total), per-game team box stats. 2015–2024.
- **Ratings:** iterative opponent-adjusted YPA/YPC (off & def), computed **as-of each week**
  (only prior games that season), shrunk toward prior-season finals — no leakage.
- **Models:** train on seasons `< S`, predict season `S`, for S = 2018…2024.
  - `NN` — faithful tanh MLP, same inputs as the spreadsheet (incl. market total).
  - `GBM` — HistGradientBoosting on richer features (incl. market total).
  - `GBM_nomkt` — same but **blind to the betting line** (pure projection → true edge test).

## Accuracy vs actual total (9,700 FBS games)
| model | MAE | RMSE |
|---|---|---|
| **market (closing)** | **12.75** | **16.12** |
| NN (faithful) | 12.80 | 16.16 |
| GBM | 12.86 | 16.25 |
| GBM (no market) | 13.22 | 16.72 |

➡ **No model beats the market on accuracy.** The market total is the single best predictor;
the faithful NN essentially learns to echo it (MAE within 0.05).

## Betting backtest (O/U vs the line, ROI at −110, break-even = 52.38%)
Best/most consistent = the line-blind projection:

| edge ≥ | bets | win% | ROI% |
|---|---|---|---|
| 0 | 5210 | 52.5 | +0.3 |
| 3 | 2997 | 52.9 | +1.1 |
| 5 | 1855 | 53.2 | +1.5 |
| 6 | 1399 | 53.4 | +2.0 |

Win% rises monotonically as the model disagrees more with the line — the signature of *some*
real signal. **But** the per-season and significance tests say don't bet the mortgage:

**Per season (edge ≥ 4):** 2020 **58%**, 2023 55%, 2024 55%, 2019 52%, 2021 52%, 2018 51%, **2022 48%**.
Three losing seasons out of seven; the aggregate is propped up by the odd 2020 COVID season.

**Significance:** at every threshold the win rate is **not statistically distinguishable from
break-even** (binomial p ≈ 0.26–0.6 vs 52.38%). Part of the "edge" is just a mild *over* lean
(1429 overs vs 954 unders) in a decade where overs cashed by a hair (actual − line = +0.42).

## Verdict — viability
- **As a totals *predictor*: viable and faithful, but it does not beat the closing market.**
  The market is more accurate; the model's value is as a *disagreement flag*, not a truth oracle.
- **As a totals *betting* system: not demonstrated.** The historical ~52.5–53.4% is within noise
  of the −110 break-even and is inconsistent across seasons. No statistically significant edge.
- This is the expected result — CFB totals markets are efficient, and the original design's
  reliance on the Vegas total means it mostly reprices the line.

## Where a real edge would more plausibly come from (next steps)
1. Bet vs **opening** lines / shop for best number (capture closing-line value) rather than consensus.
2. Add signal the market underweights: **pace/PPA, weather (wind/precip), QB availability, travel/rest, altitude**.
3. Situational sub-models (e.g., only totals ≤ X, non-conference, specific pace mismatches) — with
   strict out-of-sample validation to avoid the season-cherry-picking trap seen above.
4. Model the *distribution* of totals (not just the mean) to size bets by true win prob, not point edge.

## Added factors (round 2) — pace, PPA, dome, altitude, rest, travel, cold-late
Added: dome, elevation, surface, a cold/late-season northern-outdoor proxy (real weather is
paywalled), rest days per team, away travel distance, and as-of PPA (explosiveness) off/def ratings.

**Adding them to the model did not help** — MAE got slightly worse (12.92 with market / 13.26
line-blind, vs market 12.75), and the large-disagreement edge stayed absent in 2021–2024.

**Testing each factor as its own O/U angle vs the closing total (2018–24) is the punchline:**

| angle | side | bets | win% | ROI% |
|---|---|---|---|---|
| dome games | over | 244 | 45.5 | −13.2 |
| fast pace (top 20%) | over | 1024 | 47.9 | −8.5 |
| both teams high PPA | over | 1030 | 48.1 | −8.3 |
| cold late-season N. outdoor | under | 566 | 48.9 | −6.6 |
| slow pace (bottom 20%) | under | 1028 | 48.9 | −6.6 |
| high altitude | over | 336 | 49.7 | −5.1 |
| long travel away | under | 315 | 52.4 | +0.0 |
| short rest away | under | 126 | 53.2 | +1.5 |

Every *intuitive* factor is a **loser** — the market doesn't just price pace/dome/altitude/PPA,
it **over-corrects** them (betting the obvious direction loses ~5–13% ROI). Only two thin,
tiny-sample situational angles (short rest / long travel for the away team → under) lean
positive, and neither is statistically significant. Net: no exploitable factor edge found.

## The exploitable angle (round 3): beat the OPENER, not the close
De-anchored model (line-blind), 2019–2025 walk-forward:
- vs **closing** total: 52.0% at |edge|≥3 — no edge (market is sharp).
- vs **opening** total: **54.3%** (edge≥3, p=.035) → **56.0%** (edge≥5, p=.005). Strengthens with
  disagreement size and is positive in 4–5 of 5 seasons. This is the real form of the
  "big-discrepancy" edge: it lives against soft openers, and you must bet early to get it.
- When the market later moves toward the model's side: 58% / +11% ROI, all 5 seasons.

**Finishing factor (yards→points):** year-over-year reliable (r=0.325), unlike the caliber effect.
Adding it nudged MAE 13.243→13.214 and improved the opener edge (54.7%/p=.016 at edge≥3). Kept.

**Line source caveat:** in CFBD, opening totals come almost entirely from **Bovada** (84% coverage;
ESPN Bet 47%, DraftKings 30%; consensus/teamrankings/numberfire have NO opens). So the opener edge
is measured against **Bovada-style early numbers**, and that's where it must be bet live.

## Files
- `src/pull_data.py` — CFBD data pull
- `src/build_features.py` — walk-forward opponent-adjusted ratings + projections
- `src/model_totals.py` — train + backtest (run: `python3 src/model_totals.py`)
- `out/backtest_preds.csv` — every game, every model's prediction (for your own slicing)
