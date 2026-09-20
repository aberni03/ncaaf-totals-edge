"""ONE-COMMAND weekly refresh. Pulls the current season's latest results (box scores),
then re-projects the slate with live odds. Team ratings update automatically because the
live engine recomputes as-of ratings from the fresh box scores (preseason -> live blend).

Usage:  python3 live/weekly_update.py [SEASON]      (SEASON defaults to 2026)

NOTE: the frozen GBM does NOT need retraining during the season — only the team ratings/
features update as games come in. Retrain (live/train.py) only in the OFFSEASON to add a
completed year to the training set.

TIME BUDGET (why this file is structured in steps): the dashboard runs this as a subprocess
and kills it at 300s. Every network pull is therefore bounded (2 attempts x 25s, never past
PULL_BUDGET seconds total) and every step is independent — a slow or failing provider skips
that step and leaves its data untouched instead of stranding the whole refresh. The board
rebuild ALWAYS runs last, so the visible board matches whatever data actually landed.
"""
import os, sys, time, subprocess, datetime as dt, requests, pandas as pd
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); DATA=ROOT+"/data"; HERE=os.path.dirname(os.path.abspath(__file__))
KEY=open(f"{ROOT}/.cfbd_key").read().strip(); H={"Authorization":f"Bearer {KEY}"}; B="https://api.collegefootballdata.com"
YR=int(sys.argv[1]) if len(sys.argv)>1 else 2026

T0=time.time()
PULL_BUDGET=float(os.environ.get("REFRESH_PULL_BUDGET","120"))   # seconds for ALL CFBD pulls
ATTEMPT_TIMEOUT=25                                               # per HTTP attempt (was 90)
ATTEMPTS=2                                                       # (was 4 -> worst case 366s > the 300s cap)
def _left(): return PULL_BUDGET-(time.time()-T0)

class Deadline(Exception):
    """Out of pull budget — skip this step, keep existing data, still rebuild the board."""

def get(p,**q):
    """Bounded CFBD fetch. Raises Deadline (skip step), SystemExit (quota/auth) or RuntimeError."""
    for a in range(ATTEMPTS):
        if _left() <= 5: raise Deadline(f"no pull budget left for {p}")
        try:
            r=requests.get(B+p,params=q,headers=H,timeout=min(ATTEMPT_TIMEOUT,max(5,_left())))
        except requests.RequestException as e:
            if a==ATTEMPTS-1: raise RuntimeError(f"{type(e).__name__} on {p}")
            time.sleep(1); continue
        if r.status_code==200: return r.json()
        if r.status_code==429:   # quota exhausted — retrying won't help, bail fast instead of buffering
            raise SystemExit("CFBD monthly call quota exceeded — results/stats/lines can't update until the monthly reset. Live odds (board totals) still work.")
        if r.status_code in (401,403):
            raise SystemExit(f"CFBD auth failed ({r.status_code}) — check the CFBD key.")
        if a==ATTEMPTS-1: raise RuntimeError(f"CFBD {r.status_code} on {p}")
        time.sleep(1)
    return []

def step(n, label, fn):
    """Run one pull step in isolation. Returns True if it wrote data."""
    t=time.time(); print(f"[{n}/5] {label}…", flush=True)
    try:
        msg=fn(); print(f"      ✓ {msg}  ({time.time()-t:.1f}s, {_left():.0f}s budget left)", flush=True); return True
    except Deadline as e:
        print(f"      ⏱ skipped — {e}. Existing data kept.", flush=True); return False
    except SystemExit: raise                       # quota/auth: stop pulling, still rebuild below
    except Exception as e:
        print(f"      ⚠ failed — {type(e).__name__}: {e}. Existing data kept.", flush=True); return False

# postseason endpoints return nothing until bowl season; skip the 2 wasted calls the rest of the year
SEASON_TYPES=("regular","postseason") if dt.date.today().month in (11,12,1) else ("regular",)

# ---------------------------------------------------------------- 1. games (schedule + results)
def pull_games():
    gr=[]
    for st in SEASON_TYPES:
        for g in get("/games",year=YR,seasonType=st,division="fbs"):
            gr.append(dict(game_id=g["id"],season=g["season"],week=g["week"],season_type=st,start_date=g.get("startDate"),
                home=g["homeTeam"],away=g["awayTeam"],home_conf=g.get("homeConference"),away_conf=g.get("awayConference"),
                home_div=g.get("homeClassification"),away_div=g.get("awayClassification"),
                home_pts=g.get("homePoints"),away_pts=g.get("awayPoints"),neutral=g.get("neutralSite"),completed=g.get("completed")))
    gg=pd.read_csv(f"{DATA}/games.csv"); have=int((gg.season==YR).sum())
    # SAFETY: a truncated/partial response must never wipe the stored season
    if len(gr) < max(1, 0.8*have):
        raise RuntimeError(f"partial response ({len(gr)} rows vs {have} stored) — refusing to overwrite games.csv")
    pd.concat([gg[gg.season!=YR],pd.DataFrame(gr)],ignore_index=True).to_csv(f"{DATA}/games.csv",index=False)
    done=[x for x in gr if x["completed"]]
    return f"{len(gr)} games, {len(done)} completed"

# ---------------------------------------------------------------- 2. box scores (drives ratings)
def parse(sl):
    o={}
    for s in sl:
        c,v=s["category"],s["stat"]
        if c=="completionAttempts":
            try: comp,att=str(v).split("-"); o["pass_att"]=float(att); o["completions"]=float(comp)
            except: pass
        elif c in ["totalYards","netPassingYards","yardsPerPass","rushingYards","rushingAttempts","yardsPerRushAttempt","turnovers","possessionTime","firstDowns"]:
            try: o[c]=float(v)
            except: o[c]=None
    return o

def latest_done_week():
    """Latest completed week from the stored file (works even if the games pull was skipped)."""
    g=pd.read_csv(f"{DATA}/games.csv"); d=g[(g.season==YR)&(g.completed==True)]
    return int(d.week.max()) if len(d) else 0

def pull_box_scores(cw):
    # only refresh a small window (latest completed week ± 1) instead of all 16 weeks
    lo=max(1,cw-1); hi=min(16,cw+1); weeks=list(range(lo,hi+1))
    jobs=[("regular",w) for w in weeks]+([("postseason",1)] if cw>=15 else [])
    sr=[]
    for st,wk in jobs:
        for g in get("/games/teams",year=YR,week=wk,seasonType=st):
            for t in g.get("teams",[]):
                rec=dict(game_id=g["id"],season=YR,week=wk,season_type=st,team=t["team"],home_away=t.get("homeAway"),points=t.get("points")); rec.update(parse(t.get("stats",[])))
                sr.append(rec)
    new=pd.DataFrame(sr)
    ts=pd.read_csv(f"{DATA}/team_game_stats.csv")
    if len(new):   # replace ONLY the weeks we just pulled; keep every earlier week intact (ratings need full history)
        key=lambda d:d.season.astype(str)+"|"+d.season_type.astype(str)+"|"+d.week.astype(str)
        ts=ts[~key(ts).isin(set(key(new)))]
    if not len(new): return f"no new rows for weeks {weeks} — existing box scores kept"
    pd.concat([ts,new],ignore_index=True).to_csv(f"{DATA}/team_game_stats.csv",index=False)
    return f"{len(sr)} team-game rows (weeks {weeks}); {len(jobs)} calls instead of 17"

# ---------------------------------------------------------------- 3. betting lines
def pull_lines():
    lrows=[]
    for st in SEASON_TYPES:
        for g in get("/lines",year=YR,seasonType=st):
            for ln in g.get("lines",[]):
                lrows.append(dict(game_id=g["id"],season=g["season"],week=g["week"],season_type=st,
                    home=g["homeTeam"],away=g["awayTeam"],provider=ln.get("provider"),
                    spread=ln.get("spread"),spread_open=ln.get("spreadOpen"),
                    over_under=ln.get("overUnder"),over_under_open=ln.get("overUnderOpen"),
                    home_ml=ln.get("homeMoneyline"),away_ml=ln.get("awayMoneyline")))
    L=pd.read_csv(f"{DATA}/lines.csv"); have=int((L.season==YR).sum())
    # SAFETY: same guard — never trade a full stored season for a partial response
    if len(lrows) < max(1, 0.8*have):
        raise RuntimeError(f"partial response ({len(lrows)} rows vs {have} stored) — refusing to overwrite lines.csv")
    pd.concat([L[L.season!=YR],pd.DataFrame(lrows)],ignore_index=True).to_csv(f"{DATA}/lines.csv",index=False)
    return f"{len(lrows)} line rows"

# ---------------------------------------------------------------- run
quota_msg=None
try:
    step(1,f"pulling {YR} games",pull_games)
    cw=latest_done_week(); print(f"      latest week done = {cw}", flush=True)
    step(2,f"pulling {YR} box scores (recent weeks only — saves CFBD calls)",lambda: pull_box_scores(cw))
    step(3,f"pulling {YR} betting lines",pull_lines)
except SystemExit as e:          # quota/auth — stop pulling, but still rebuild from what we have
    quota_msg=str(e); print(f"      ⚠ {quota_msg}", flush=True)

# The board rebuild ALWAYS runs: whatever data landed above, the displayed board matches it.
print("[4/5] regrading track record (completed games -> Track Record)…", flush=True)
t=time.time(); r4=subprocess.run([sys.executable, f"{HERE}/build_track_record.py"], cwd=ROOT, capture_output=True, text=True)
print(f"      {'✓' if r4.returncode==0 else '⚠ FAILED'} ({time.time()-t:.1f}s)", flush=True)
if r4.returncode!=0: print((r4.stderr or r4.stdout or "")[-400:], flush=True)

print("[5/5] re-projecting board…", flush=True)
t=time.time(); r5=subprocess.run([sys.executable, f"{HERE}/project_slate.py"], cwd=ROOT, capture_output=True, text=True)
print(f"      {'✓' if r5.returncode==0 else '⚠ FAILED'} ({time.time()-t:.1f}s)", flush=True)
if r5.returncode!=0: print((r5.stderr or r5.stdout or "")[-400:], flush=True)

print(f"\ntotal {time.time()-T0:.1f}s", flush=True)
if r5.returncode!=0:
    raise SystemExit("board rebuild failed — see output above")   # the only true failure for the UI
if quota_msg:
    print(f"⚠ finished, but data pulls were skipped: {quota_msg}")
else:
    print("✅ done. Completed games are in the Track Record; the board is re-projected.")
