"""Pull CFBD data: games (finals), betting lines, per-game team box stats.
Saves tidy CSVs to data/. Idempotent-ish: re-run overwrites."""
import os, sys, time, json
import requests
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
KEY = open(os.path.join(ROOT, ".cfbd_key")).read().strip()
H = {"Authorization": f"Bearer {KEY}"}
B = "https://api.collegefootballdata.com"
SEASONS = list(range(2015, 2025))  # 2015-2024

def get(path, **params):
    for attempt in range(5):
        r = requests.get(f"{B}{path}", params=params, headers=H, timeout=90)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(3 * (attempt + 1)); continue
        print(f"  WARN {path} {params} -> {r.status_code} {r.text[:120]}")
        time.sleep(1)
    return []

# ---------- 1) Games (final scores) ----------
def pull_games():
    rows = []
    for yr in SEASONS:
        for st in ("regular", "postseason"):
            d = get("/games", year=yr, seasonType=st, division="fbs")
            for g in d:
                rows.append(dict(
                    game_id=g["id"], season=g["season"], week=g["week"],
                    season_type=st, start_date=g.get("startDate"),
                    home=g["homeTeam"], away=g["awayTeam"],
                    home_conf=g.get("homeConference"), away_conf=g.get("awayConference"),
                    home_div=g.get("homeClassification"), away_div=g.get("awayClassification"),
                    home_pts=g.get("homePoints"), away_pts=g.get("awayPoints"),
                    neutral=g.get("neutralSite"), completed=g.get("completed"),
                ))
        print(f"games {yr}: cumulative {len(rows)}")
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(DATA, "games.csv"), index=False)
    print("saved games.csv", df.shape)
    return df

# ---------- 2) Betting lines ----------
def pull_lines():
    rows = []
    for yr in SEASONS:
        for st in ("regular", "postseason"):
            d = get("/lines", year=yr, seasonType=st)
            for g in d:
                for ln in g.get("lines", []):
                    rows.append(dict(
                        game_id=g["id"], season=g["season"], week=g["week"],
                        season_type=st, home=g["homeTeam"], away=g["awayTeam"],
                        provider=ln.get("provider"),
                        spread=ln.get("spread"), spread_open=ln.get("spreadOpen"),
                        over_under=ln.get("overUnder"), over_under_open=ln.get("overUnderOpen"),
                        home_ml=ln.get("homeMoneyline"), away_ml=ln.get("awayMoneyline"),
                    ))
        print(f"lines {yr}: cumulative {len(rows)}")
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(DATA, "lines.csv"), index=False)
    print("saved lines.csv", df.shape)
    return df

# ---------- 3) Per-game team box stats ----------
STAT_KEYS = ["totalYards","netPassingYards","completionAttempts","yardsPerPass",
             "rushingYards","rushingAttempts","yardsPerRushAttempt","turnovers",
             "possessionTime","firstDowns"]

def parse_stats(statlist):
    out = {}
    for s in statlist:
        c = s["category"]; v = s["stat"]
        if c == "completionAttempts":
            # "24-38" -> completions, attempts
            try:
                comp, att = str(v).split("-"); out["pass_att"] = float(att); out["completions"] = float(comp)
            except Exception:
                pass
        elif c in STAT_KEYS:
            try: out[c] = float(v)
            except Exception: out[c] = None
    return out

def pull_team_game_stats():
    rows = []
    for yr in SEASONS:
        for st in ("regular", "postseason"):
            weeks = range(1, 17) if st == "regular" else [1]
            for wk in weeks:
                d = get("/games/teams", year=yr, week=wk, seasonType=st)
                for g in d:
                    tms = g.get("teams", [])
                    for t in tms:
                        rec = dict(game_id=g["id"], season=yr, week=wk, season_type=st,
                                   team=t["team"], home_away=t.get("homeAway"),
                                   points=t.get("points"))
                        rec.update(parse_stats(t.get("stats", [])))
                        rows.append(rec)
            print(f"teamstats {yr} {st}: cumulative {len(rows)}")
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(DATA, "team_game_stats.csv"), index=False)
    print("saved team_game_stats.csv", df.shape)
    return df

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all","games"): pull_games()
    if which in ("all","lines"): pull_lines()
    if which in ("all","stats"): pull_team_game_stats()
    print("DONE")
