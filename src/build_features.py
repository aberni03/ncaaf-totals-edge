"""Build a leak-free, walk-forward feature table for totals modeling.

Reproduces the spreadsheet's logic with public data:
  - opponent-adjusted per-play efficiency ratings (YPA off/def, YPC off/def)
  - tempo (plays/game) and pass rate
  - Stage-1 projected box-score drivers (proj PY/YPA/RY/YRA per team) a la 'Single Game Input'
All team ratings entering a given (season, week) use ONLY games from earlier weeks
that season, blended with the prior season's final rating (shrinkage by games played).
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# ---------------- load ----------------
games = pd.read_csv(os.path.join(DATA, "games.csv"))
lines = pd.read_csv(os.path.join(DATA, "lines.csv"))
stats = pd.read_csv(os.path.join(DATA, "team_game_stats.csv"))

# FBS vs FBS regular+post games with final scores
games = games[games.completed == True].copy()
games["home_pts"] = pd.to_numeric(games["home_pts"], errors="coerce")
games["away_pts"] = pd.to_numeric(games["away_pts"], errors="coerce")
games = games.dropna(subset=["home_pts", "away_pts"])
games["total_pts"] = games.home_pts + games.away_pts
games["fbs_both"] = (games.home_div == "fbs") & (games.away_div == "fbs")

# ---------------- market line (consensus close) ----------------
def consensus(df, col):
    # prefer 'consensus' provider, else median across books
    d = df.dropna(subset=[col])
    if len(d) == 0:
        return np.nan
    c = d[d.provider == "consensus"]
    if len(c):
        return c[col].median()
    return d[col].median()

mk = []
for gid, grp in lines.groupby("game_id"):
    mk.append(dict(
        game_id=gid,
        mkt_total=consensus(grp, "over_under"),
        mkt_total_open=consensus(grp, "over_under_open"),
        mkt_spread=consensus(grp, "spread"),          # home-negative
        mkt_spread_open=consensus(grp, "spread_open"),
    ))
mk = pd.DataFrame(mk)
games = games.merge(mk, on="game_id", how="left")

# ---------------- per-team-game efficiency ----------------
s = stats.copy()
for c in ["netPassingYards","pass_att","rushingYards","rushingAttempts","points","turnovers"]:
    s[c] = pd.to_numeric(s.get(c), errors="coerce")
s["off_pass_y"] = s.netPassingYards
s["off_rush_y"] = s.rushingYards
s["off_pa"] = s.pass_att
s["off_ra"] = s.rushingAttempts
s["off_ypa"] = s.off_pass_y / s.off_pa
s["off_ypc"] = s.off_rush_y / s.off_ra
s["plays"] = s.off_pa + s.off_ra
s = s.dropna(subset=["off_ypa","off_ypc","plays"])

# pair opponents within a game to get 'allowed' (defense faced)
pieces = []
for gid, grp in s.groupby("game_id"):
    if len(grp) != 2:
        continue
    a, b = grp.iloc[0].copy(), grp.iloc[1].copy()
    for me, opp in ((a, b), (b, a)):
        pieces.append(dict(
            game_id=gid, season=me.season, week=me.week, team=me.team,
            off_ypa=me.off_ypa, off_ypc=me.off_ypc,
            def_ypa=opp.off_ypa, def_ypc=opp.off_ypc,   # allowed
            off_pa=me.off_pa, off_ra=me.off_ra, plays=me.plays,
            pass_rate=me.off_pa / me.plays if me.plays else np.nan,
            points=me.points,
        ))
tg = pd.DataFrame(pieces)

# ---------------- opponent-adjusted ratings (as-of, walk-forward) ----------------
def adjust(df, iters=4):
    """Iterative opponent adjustment centered on league means.
    Returns per-team dict of adjusted off/def ypa & ypc, plus tempo & pass_rate."""
    if len(df) == 0:
        return {}, {}
    lg = dict(ypa=df.off_ypa.mean(), ypc=df.off_ypc.mean())
    teams = df.team.unique()
    off_ypa = {t: df.loc[df.team==t,"off_ypa"].mean() for t in teams}
    def_ypa = {t: df.loc[df.team==t,"def_ypa"].mean() for t in teams}
    off_ypc = {t: df.loc[df.team==t,"off_ypc"].mean() for t in teams}
    def_ypc = {t: df.loc[df.team==t,"def_ypc"].mean() for t in teams}
    g = df.groupby("team")
    idx = {t: g.get_group(t) for t in teams}
    for _ in range(iters):
        no, nd, no2, nd2 = {}, {}, {}, {}
        for t in teams:
            d = idx[t]
            # opponent-adjust: subtract opponent's (rating - league mean)
            no[t] = (d.off_ypa - (d["opp"].map(def_ypa).fillna(lg["ypa"]) - lg["ypa"])).mean()
            nd[t] = (d.def_ypa - (d["opp"].map(off_ypa).fillna(lg["ypa"]) - lg["ypa"])).mean()
            no2[t] = (d.off_ypc - (d["opp"].map(def_ypc).fillna(lg["ypc"]) - lg["ypc"])).mean()
            nd2[t] = (d.def_ypc - (d["opp"].map(off_ypc).fillna(lg["ypc"]) - lg["ypc"])).mean()
        off_ypa, def_ypa, off_ypc, def_ypc = no, nd, no2, nd2
    tempo = {t: idx[t].plays.mean() for t in teams}
    prate = {t: idx[t].pass_rate.mean() for t in teams}
    gp = {t: len(idx[t]) for t in teams}
    return (dict(off_ypa=off_ypa, def_ypa=def_ypa, off_ypc=off_ypc, def_ypc=def_ypc,
                 tempo=tempo, prate=prate, gp=gp), lg)

# need opponent column on tg
opp_map = {}
for gid, grp in tg.groupby("game_id"):
    if len(grp) == 2:
        a, b = grp.team.tolist()
        opp_map[(gid, a)] = b
        opp_map[(gid, b)] = a
tg["opp"] = [opp_map.get((r.game_id, r.team)) for r in tg.itertuples()]

# prior-season FINAL ratings for shrinkage
final_ratings = {}   # season -> ratings dict
for season, grp in tg.groupby("season"):
    r, lg = adjust(grp)
    final_ratings[season] = (r, lg)

SHRINK_K = 4.0  # games at which current-season weight = 0.5

def blended_ratings(season, week):
    """Ratings entering (season, week): current-season games with week<week,
    shrunk toward prior-season final ratings."""
    cur = tg[(tg.season == season) & (tg.week < week)]
    r_cur, lg_cur = adjust(cur)
    prior = final_ratings.get(season - 1, ({}, None))
    r_pri, lg_pri = prior
    lg = lg_cur if r_cur else (lg_pri if r_pri else dict(ypa=7.2, ypc=4.6))
    teams = set(list(r_cur.get("off_ypa", {}).keys()) + list(r_pri.get("off_ypa", {}).keys()))
    out = {}
    for t in teams:
        gp = r_cur.get("gp", {}).get(t, 0)
        w = gp / (gp + SHRINK_K)              # weight on current season
        row = {}
        for key in ["off_ypa","def_ypa","off_ypc","def_ypc","tempo","prate"]:
            cv = r_cur.get(key, {}).get(t)
            pv = r_pri.get(key, {}).get(t)
            if cv is None and pv is None:
                # league fallback
                fallback = dict(off_ypa=lg["ypa"], def_ypa=lg["ypa"], off_ypc=lg["ypc"],
                                def_ypc=lg["ypc"], tempo=140.0, prate=0.5)[key]
                row[key] = fallback
            elif cv is None:
                row[key] = pv
            elif pv is None:
                row[key] = cv
            else:
                row[key] = w * cv + (1 - w) * pv
        out[t] = row
    return out, lg

# ---------------- assemble game features ----------------
LG_YPA_DEFAULT, LG_YPC_DEFAULT = 7.2, 4.6
rows = []
for (season, week), grp in games.groupby(["season", "week"]):
    R, lg = blended_ratings(season, week)
    lgypa = lg.get("ypa", LG_YPA_DEFAULT); lgypc = lg.get("ypc", LG_YPC_DEFAULT)
    for gme in grp.itertuples():
        h, a = gme.home, gme.away
        rh, ra = R.get(h), R.get(a)
        if rh is None or ra is None:
            continue
        # Stage-1 projections (spreadsheet 'Single Game Input' logic)
        exp_plays = 0.5 * (rh["tempo"] + ra["tempo"])   # both teams ~equal plays/game
        # per-team play splits from their own pass rate
        h_pa = exp_plays * rh["prate"]; h_ra = exp_plays * (1 - rh["prate"])
        a_pa = exp_plays * ra["prate"]; a_ra = exp_plays * (1 - ra["prate"])
        # efficiency = off_rating * opp_def_rating / league (spreadsheet formula)
        h_ypa = rh["off_ypa"] * ra["def_ypa"] / lgypa
        a_ypa = ra["off_ypa"] * rh["def_ypa"] / lgypa
        h_ypc = rh["off_ypc"] * ra["def_ypc"] / lgypc
        a_ypc = ra["off_ypc"] * rh["def_ypc"] / lgypc
        h_py = h_pa * h_ypa; a_py = a_pa * a_ypa
        h_ry = h_ra * h_ypc; a_ry = a_ra * a_ypc
        proj_total_yards = h_py + h_ry + a_py + a_ry
        rows.append(dict(
            game_id=gme.game_id, season=season, week=week, season_type=gme.season_type,
            home=h, away=a, neutral=gme.neutral, fbs_both=gme.fbs_both,
            total_pts=gme.total_pts, home_pts=gme.home_pts, away_pts=gme.away_pts,
            mkt_total=gme.mkt_total, mkt_total_open=gme.mkt_total_open,
            mkt_spread=gme.mkt_spread,
            # projected drivers (faithful-NN inputs)
            proj_py_h=h_py, proj_ypa_h=h_ypa, proj_ry_h=h_ry, proj_yrc_h=h_ypc,
            proj_py_a=a_py, proj_ypa_a=a_ypa, proj_ry_a=a_ry, proj_yrc_a=a_ypc,
            tempo_h=rh["tempo"], tempo_a=ra["tempo"], exp_plays=exp_plays,
            proj_total_yards=proj_total_yards,
            # raw adjusted ratings (extra features for GBM)
            off_ypa_h=rh["off_ypa"], def_ypa_h=rh["def_ypa"], off_ypc_h=rh["off_ypc"], def_ypc_h=rh["def_ypc"],
            off_ypa_a=ra["off_ypa"], def_ypa_a=ra["def_ypa"], off_ypc_a=ra["off_ypc"], def_ypc_a=ra["def_ypc"],
            prate_h=rh["prate"], prate_a=ra["prate"],
        ))
feat = pd.DataFrame(rows)
feat.to_csv(os.path.join(DATA, "features.csv"), index=False)
print("features.csv", feat.shape)
print("with market total:", feat.mkt_total.notna().sum())
print("seasons:", sorted(feat.season.unique()))
