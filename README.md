# 🏈 CFB Totals Edge

A de-anchored college-football **totals model** + live **Streamlit dashboard**.

- **Board** — every upcoming FBS game with the opener → current line → model projection, edge vs the opener, OVER/UNDER signals (★ = STRONG, edge ≥ 5), and click any card for a full team-stats / projection breakdown.
- **Track Record** — leak-free walk-forward grading (2020→present) vs the opener: record, ROI, CLV, cover margin.
- **Bankroll** — live equity curve, streak, and form for the model's plays.

The edge is **closing-line value**: the model beats soft *openers* (not the sharp close), so plays are graded and bet against the opening number. Bet ≥ 5-point disagreements early.

## Run locally
```bash
pip install -r requirements.txt
# put your keys in ./.cfbd_key and ./.odds_key  (one line each)
streamlit run live/app.py
```

## Deploy (Streamlit Community Cloud)
1. Push this repo to GitHub.
2. On [share.streamlit.io](https://share.streamlit.io) → **New app** → pick the repo, branch `main`, main file `live/app.py`.
3. In **Advanced settings → Secrets**, add:
   ```toml
   CFBD_KEY = "your_collegefootballdata_key"
   ODDS_KEY = "your_theoddsapi_key"
   ```
4. Deploy. Use **🔃 Update week results** + **🔄 Refresh odds** to pull live data.

Data comes from [CollegeFootballData](https://collegefootballdata.com) (games, box scores, opening lines) and [The Odds API](https://the-odds-api.com) (live lines). Not betting advice.
