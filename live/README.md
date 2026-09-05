# CFB Totals Edge — live dashboard

Action Network-style dashboard for the de-anchored NCAAF totals model.

## Launch
```bash
cd /Users/ABIII/ncaaf-totals-model
streamlit run live/app.py
# opens at http://localhost:8501 (or the port shown)
```

## Weekly workflow
1. **Refresh data** (once new results are in, ~Sunday):
   ```bash
   python3 src/pull_2025.py            # <- edit YR, or use the 2026 pull pattern; pulls new games/lines/stats
   python3 src/build_preseason.py      # refresh ratings (preseason auto-extends to current season)
   python3 src/build_features_v2.py 5  # rebuild leak-free features (~6 min)
   python3 live/train.py               # retrain + freeze totals & spread models
   ```
2. **Project the slate + pull live odds:**
   ```bash
   python3 live/project_slate.py       # 1 Odds API request; writes out/slate.csv
   ```
   or click **🔄 Refresh live odds** in the dashboard.
3. Open the dashboard, pick the **Week**, read the board.

## Reading the board
- **Total**: `Mkt` = current market total; big number = model projection; ▲/▼ = edge vs the **opener**.
- **STRONG** = model disagrees with the number by ≥5 pts; **LEAN** = ≥3.
- Edge is measured vs the **opening** total on purpose — the backtested edge is a
  closing-line-value effect: you must bet **early** (soft openers, e.g. Bovada) to capture it.
- Spread projection is secondary (this is a totals-first model); treat it as a rough read.

## Odds API budget
Free tier = 500 requests/month. Each slate refresh = 1 request. Don't auto-poll aggressively;
a few refreshes per day (Sun–Tue when openers post) is plenty. Remaining count shows in the header.

## Files
- `live/ratings_engine.py` — as-of ratings + matchup projection (shared by train & live)
- `live/train.py` — trains/freezes `models/totals.joblib` + `models/spread.joblib`
- `live/odds.py` — Odds API fetch, team-name resolver, opener snapshot logging, CFBD fallback
- `live/project_slate.py` — full-season slate w/ proj total+spread, market join, edge, CLV
- `live/app.py` — Streamlit dashboard
- `out/slate.csv` — the projected slate (all weeks); `out/odds_snapshots.csv` — opener tracking log
