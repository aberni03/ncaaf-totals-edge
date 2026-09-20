"""ONE-COMMAND weekly refresh. Pulls the current season's latest results (box scores),
then re-projects the slate with live odds. Team ratings update automatically because the
live engine recomputes as-of ratings from the fresh box scores (preseason -> live blend).

Usage:  python3 live/weekly_update.py [SEASON]      (SEASON defaults to 2026)

NOTE: the frozen GBM does NOT need retraining during the season — only the team ratings/
features update as games come in. Retrain (live/train.py) only in the OFFSEASON to add a
completed year to the training set.

TIME BUDGET (why this file is structured in steps): the dashboard runs this as a subprocess
and kills it at 240s. Every network pull is bounded (2 attempts x 25s, never past PULL_BUDGET
seconds total) and every step is independent — a slow or failing provider skips that step and
leaves its data untouched instead of stranding the whole refresh.

ORDER MATTERS: pulls -> BOARD -> regrade. The board is what the page shows and is the lighter
job (~142MB vs ~271MB peak); the regrade only feeds the Track Record tab. Running the board
first means a slow, skipped or OOM-killed regrade can never cost you a fresh board.

The heavy path really belongs off this container: .github/workflows/refresh.yml runs the same
update on a GitHub runner (7GB, full CPU) and COMMITS the result, which also survives the
container restarts that otherwise reset its ephemeral disk back to the repo.
"""
import os, sys, time, json, subprocess, datetime as dt, requests, pandas as pd
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); DATA=ROOT+"/data"; OUT=ROOT+"/out"; HERE=os.path.dirname(os.path.abspath(__file__))

# Single-thread the children. numpy/sklearn size their thread pools from the HOST core count,
# but the dashboard container gets a fraction of one CPU — oversubscribing there turns a 5s
# job into minutes of contention. Predictions are deterministic either way.
CHILD_ENV={**os.environ,"OMP_NUM_THREADS":"1","OPENBLAS_NUM_THREADS":"1","MKL_NUM_THREADS":"1",
           "NUMEXPR_NUM_THREADS":"1","VECLIB_MAXIMUM_THREADS":"1"}
KEY=open(f"{ROOT}/.cfbd_key").read().strip(); H={"Authorization":f"Bearer {KEY}"}; B="https://api.collegefootballdata.com"
YR=int(sys.argv[1]) if len(sys.argv)>1 else 2026

T0=time.time()
# The dashboard kills this subprocess at 240s. We budget BELOW that so the job always exits
# on its own with a message naming the slow step, instead of being killed mid-flight.
TOTAL_BUDGET=float(os.environ.get("REFRESH_TOTAL_BUDGET","200"))  # whole job
PULL_BUDGET=float(os.environ.get("REFRESH_PULL_BUDGET","100"))   # seconds for ALL CFBD pulls
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
# Both get a hard timeout — project_slate does its own network I/O, and requests' timeout is
# per-socket-read, so a trickling response would otherwise hang with no upper bound.
def run_stage(n, label, script, budget):
    t=time.time(); print(f"[{n}/5] {label}…", flush=True)
    if budget < 5:
        print(f"      ⏱ skipped — out of time budget", flush=True); return None
    try:
        r=subprocess.run([sys.executable, f"{HERE}/{script}"], cwd=ROOT, capture_output=True, text=True,
                         timeout=budget, env=CHILD_ENV)
    except subprocess.TimeoutExpired as e:
        got=(e.stdout.decode(errors="ignore") if isinstance(e.stdout,bytes) else (e.stdout or "")).strip()
        print(f"      ⏱ TIMED OUT after {budget:.0f}s — {script} is the slow step", flush=True)
        if got: print("        last output: "+" | ".join(got.splitlines()[-2:]), flush=True)
        return "timeout"
    print(f"      {'✓' if r.returncode==0 else '⚠ FAILED'} ({time.time()-t:.1f}s)", flush=True)
    if r.returncode!=0: print((r.stderr or r.stdout or "")[-400:], flush=True)
    return r.returncode

def _remaining(): return TOTAL_BUDGET-(time.time()-T0)

# Release the parent's pandas objects before spawning children — on a ~1GB container the
# parent + child are alive at the same time, and that concurrent peak is what gets us killed.
import gc
for _v in [v for v in list(globals()) if v.startswith(("gr","lrows","new","ts","L","gg"))]:
    globals().pop(_v,None)
gc.collect()

# ---- BOARD FIRST -----------------------------------------------------------------------------
# The board is what the page shows; the regrade only feeds the Track Record tab. Rebuilding the
# board first means a slow or killed regrade can no longer cost you a fresh board. project_slate
# is also the lighter of the two (~142MB vs ~271MB peak).
r_board=run_stage(4,"re-projecting board","project_slate.py",min(140,_remaining()-40))

# ---- REGRADE LAST, and only when something new has actually finished --------------------------
# Grading only reads COMPLETED games, and snapshots for completed games are frozen at kickoff and
# never change — so if the finals and their lines are unchanged, a regrade is guaranteed to
# reproduce the same file. Fingerprint those inputs and skip when identical (repeat clicks were
# each paying for a full 4,581-row regrade).
def _fingerprint():
    try:
        g=pd.read_csv(f"{DATA}/games.csv",usecols=["season","week","completed","home_div","away_div"])
        d=g[(g.season==YR)&(g.completed==True)&(g.home_div=="fbs")&(g.away_div=="fbs")]
        L=pd.read_csv(f"{DATA}/lines.csv",usecols=["season"])
        return dict(done=int(len(d)), maxwk=int(d.week.max()) if len(d) else 0,
                    lines=int((L.season==YR).sum()))
    except Exception:
        return None

STATE=f"{OUT}/.refresh_state.json"
fp=_fingerprint(); prev=None
try: prev=json.load(open(STATE)).get("regrade")
except Exception: pass

if fp is not None and fp==prev and os.path.exists(f"{OUT}/track_record.csv"):
    print(f"[5/5] regrading track record… ⏭ skipped — no new finals since the last regrade "
          f"({fp['done']} completed games, week {fp['maxwk']})", flush=True)
    r_grade=0
else:
    r_grade=run_stage(5,"regrading track record (completed games -> Track Record)","build_track_record.py",min(60,_remaining()))
    if r_grade==0 and fp is not None:
        try: json.dump({"regrade":fp}, open(STATE,"w"))
        except Exception: pass

print(f"\ntotal {time.time()-T0:.1f}s", flush=True)
if r_board!=0:
    raise SystemExit(f"board rebuild did not complete ({r_board}) — see output above")   # the only true failure for the UI
notes=[]
if quota_msg: notes.append(quota_msg)
if r_grade!=0: notes.append("Track Record not regraded (board is current)")
print(("⚠ board updated, but: "+"; ".join(notes)) if notes else
      "✅ done. Board re-projected and the Track Record is current.")
