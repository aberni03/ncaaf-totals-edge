"""Pull ONLY 2025 and append to existing CSVs (games, lines, team_game_stats, ppa_games, game_venue)."""
import os, time, requests, pandas as pd
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); DATA=ROOT+"/data"
KEY=open(ROOT+"/.cfbd_key").read().strip(); H={"Authorization":f"Bearer {KEY}"}
B="https://api.collegefootballdata.com"; YR=2025
def get(path,**p):
    for a in range(5):
        r=requests.get(B+path,params=p,headers=H,timeout=90)
        if r.status_code==200: return r.json()
        if r.status_code==429: time.sleep(3*(a+1)); continue
        print("WARN",path,p,r.status_code); time.sleep(1)
    return []
def app(name,rows):
    new=pd.DataFrame(rows); old=pd.read_csv(DATA+f"/{name}.csv")
    old=old[old.get("season",YR)!=YR] if "season" in old.columns else old
    out=pd.concat([old,new],ignore_index=True)
    out.to_csv(DATA+f"/{name}.csv",index=False); print(name,"->",out.shape,"(+%d)"%len(new))

# games
gr=[]
for st in ("regular","postseason"):
    for g in get("/games",year=YR,seasonType=st,division="fbs"):
        gr.append(dict(game_id=g["id"],season=g["season"],week=g["week"],season_type=st,
            start_date=g.get("startDate"),home=g["homeTeam"],away=g["awayTeam"],
            home_conf=g.get("homeConference"),away_conf=g.get("awayConference"),
            home_div=g.get("homeClassification"),away_div=g.get("awayClassification"),
            home_pts=g.get("homePoints"),away_pts=g.get("awayPoints"),
            neutral=g.get("neutralSite"),completed=g.get("completed")))
app("games",gr)
# lines
lr=[]
for st in ("regular","postseason"):
    for g in get("/lines",year=YR,seasonType=st):
        for ln in g.get("lines",[]):
            lr.append(dict(game_id=g["id"],season=g["season"],week=g["week"],season_type=st,
                home=g["homeTeam"],away=g["awayTeam"],provider=ln.get("provider"),
                spread=ln.get("spread"),spread_open=ln.get("spreadOpen"),
                over_under=ln.get("overUnder"),over_under_open=ln.get("overUnderOpen"),
                home_ml=ln.get("homeMoneyline"),away_ml=ln.get("awayMoneyline")))
app("lines",lr)
# team game stats
def parse(sl):
    o={}
    for s in sl:
        c,v=s["category"],s["stat"]
        if c=="completionAttempts":
            try: comp,att=str(v).split("-"); o["pass_att"]=float(att); o["completions"]=float(comp)
            except: pass
        elif c in ["totalYards","netPassingYards","yardsPerPass","rushingYards","rushingAttempts",
                   "yardsPerRushAttempt","turnovers","possessionTime","firstDowns"]:
            try: o[c]=float(v)
            except: o[c]=None
    return o
sr=[]
for st in ("regular","postseason"):
    weeks=range(1,17) if st=="regular" else [1]
    for wk in weeks:
        for g in get("/games/teams",year=YR,week=wk,seasonType=st):
            for t in g.get("teams",[]):
                rec=dict(game_id=g["id"],season=YR,week=wk,season_type=st,team=t["team"],
                    home_away=t.get("homeAway"),points=t.get("points")); rec.update(parse(t.get("stats",[])))
                sr.append(rec)
app("team_game_stats",sr)
# ppa
pr=[]
for st in ("regular","postseason"):
    weeks=range(1,17) if st=="regular" else [1]
    for wk in weeks:
        for x in get("/ppa/games",year=YR,week=wk,seasonType=st):
            off=x.get("offense") or {}; dfn=x.get("defense") or {}
            pr.append(dict(game_id=x["gameId"],season=YR,week=wk,team=x["team"],
                ppa_off=off.get("overall"),ppa_off_pass=off.get("passing"),ppa_off_rush=off.get("rushing"),
                ppa_def=dfn.get("overall"),ppa_def_pass=dfn.get("passing"),ppa_def_rush=dfn.get("rushing")))
app("ppa_games",pr)
# game_venue (no season col; dedup on game_id)
vr=[]
for st in ("regular","postseason"):
    for g in get("/games",year=YR,seasonType=st,division="fbs"):
        vr.append(dict(game_id=g["id"],venue_id=g.get("venueId"),start_date=g.get("startDate")))
gvold=pd.read_csv(DATA+"/game_venue.csv"); ids={r["game_id"] for r in vr}
gvout=pd.concat([gvold[~gvold.game_id.isin(ids)],pd.DataFrame(vr)],ignore_index=True)
gvout.to_csv(DATA+"/game_venue.csv",index=False); print("game_venue ->",gvout.shape)
print("DONE")
