"""ONE-COMMAND weekly refresh. Pulls the current season's latest results (box scores),
then re-projects the slate with live odds. Team ratings update automatically because the
live engine recomputes as-of ratings from the fresh box scores (preseason -> live blend).

Usage:  python3 live/weekly_update.py [SEASON]      (SEASON defaults to 2026)

NOTE: the frozen GBM does NOT need retraining during the season — only the team ratings/
features update as games come in. Retrain (live/train.py) only in the OFFSEASON to add a
completed year to the training set.
"""
import os, sys, time, subprocess, requests, pandas as pd
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); DATA=ROOT+"/data"; HERE=os.path.dirname(os.path.abspath(__file__))
KEY=open(f"{ROOT}/.cfbd_key").read().strip(); H={"Authorization":f"Bearer {KEY}"}; B="https://api.collegefootballdata.com"
YR=int(sys.argv[1]) if len(sys.argv)>1 else 2026

def get(p,**q):
    for a in range(4):
        r=requests.get(B+p,params=q,headers=H,timeout=90)
        if r.status_code==200: return r.json()
        time.sleep(2)
    return []

print(f"[1/3] pulling {YR} games…")
gr=[]
for st in ("regular","postseason"):
    for g in get("/games",year=YR,seasonType=st,division="fbs"):
        gr.append(dict(game_id=g["id"],season=g["season"],week=g["week"],season_type=st,start_date=g.get("startDate"),
            home=g["homeTeam"],away=g["awayTeam"],home_conf=g.get("homeConference"),away_conf=g.get("awayConference"),
            home_div=g.get("homeClassification"),away_div=g.get("awayClassification"),
            home_pts=g.get("homePoints"),away_pts=g.get("awayPoints"),neutral=g.get("neutralSite"),completed=g.get("completed")))
gg=pd.read_csv(f"{DATA}/games.csv"); gg=gg[gg.season!=YR]
pd.concat([gg,pd.DataFrame(gr)],ignore_index=True).to_csv(f"{DATA}/games.csv",index=False)
done=[x for x in gr if x["completed"]]; cw=max([x["week"] for x in done],default=0)
print(f"      {len(done)} completed; latest week done = {cw}")

print(f"[2/3] pulling {YR} box scores…")
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
sr=[]
for st in ("regular","postseason"):
    for wk in (range(1,17) if st=="regular" else [1]):
        for g in get("/games/teams",year=YR,week=wk,seasonType=st):
            for t in g.get("teams",[]):
                rec=dict(game_id=g["id"],season=YR,week=wk,season_type=st,team=t["team"],home_away=t.get("homeAway"),points=t.get("points")); rec.update(parse(t.get("stats",[])))
                sr.append(rec)
ts=pd.read_csv(f"{DATA}/team_game_stats.csv"); ts=ts[ts.season!=YR]
pd.concat([ts,pd.DataFrame(sr)],ignore_index=True).to_csv(f"{DATA}/team_game_stats.csv",index=False)
print(f"      {len(sr)} team-game rows refreshed")

print(f"[3/5] pulling {YR} betting lines…")
lrows=[]
for st in ("regular","postseason"):
    for g in get("/lines",year=YR,seasonType=st):
        for ln in g.get("lines",[]):
            lrows.append(dict(game_id=g["id"],season=g["season"],week=g["week"],season_type=st,
                home=g["homeTeam"],away=g["awayTeam"],provider=ln.get("provider"),
                spread=ln.get("spread"),spread_open=ln.get("spreadOpen"),
                over_under=ln.get("overUnder"),over_under_open=ln.get("overUnderOpen"),
                home_ml=ln.get("homeMoneyline"),away_ml=ln.get("awayMoneyline")))
L=pd.read_csv(f"{DATA}/lines.csv"); L=L[L.season!=YR]
pd.concat([L,pd.DataFrame(lrows)],ignore_index=True).to_csv(f"{DATA}/lines.csv",index=False)
print(f"      {len(lrows)} line rows")

print("[4/5] regrading track record (completed games -> Track Record)…")
subprocess.run([sys.executable, f"{HERE}/build_track_record.py"], cwd=ROOT, capture_output=True)

print("[5/5] re-projecting board (upcoming games only)…")
subprocess.run([sys.executable, f"{HERE}/project_slate.py"], cwd=ROOT)
print("\n✅ done. Completed games are now in the Track Record; the board shows only upcoming games.")
