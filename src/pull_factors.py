"""Pull extra factor data: venues, teams(home location), game->venue map, and PPA per game."""
import os, time, requests
import pandas as pd
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA=os.path.join(ROOT,"data")
KEY=open(os.path.join(ROOT,".cfbd_key")).read().strip()
H={"Authorization":f"Bearer {KEY}"}; B="https://api.collegefootballdata.com"
SEASONS=list(range(2015,2025))
def get(path,**p):
    for a in range(5):
        r=requests.get(B+path,params=p,headers=H,timeout=90)
        if r.status_code==200: return r.json()
        if r.status_code==429: time.sleep(3*(a+1)); continue
        print("WARN",path,p,r.status_code,r.text[:80]); time.sleep(1)
    return []

# venues
v=get("/venues")
pd.DataFrame([dict(venue_id=x["id"],name=x.get("name"),dome=x.get("dome"),
    elevation=x.get("elevation"),grass=x.get("grass"),lat=x.get("latitude"),
    lon=x.get("longitude"),state=x.get("state")) for x in v]).to_csv(DATA+"/venues.csv",index=False)
print("venues",len(v))

# teams (home location)
trows=[]
for yr in SEASONS:
    d=get("/teams/fbs",year=yr)
    for t in d:
        loc=t.get("location") or {}
        trows.append(dict(season=yr,team=t.get("school"),venue_id=loc.get("venueId"),
            home_lat=loc.get("latitude"),home_lon=loc.get("longitude"),home_elev=loc.get("elevation")))
pd.DataFrame(trows).drop_duplicates(["season","team"]).to_csv(DATA+"/teams_loc.csv",index=False)
print("teams_loc",len(trows))

# game -> venue map (+ startDate) via /games
grows=[]
for yr in SEASONS:
    for st in ("regular","postseason"):
        for g in get("/games",year=yr,seasonType=st,division="fbs"):
            grows.append(dict(game_id=g["id"],venue_id=g.get("venueId"),start_date=g.get("startDate")))
pd.DataFrame(grows).to_csv(DATA+"/game_venue.csv",index=False)
print("game_venue",len(grows))

# PPA per game (offense/defense predicted points added per play)
prows=[]
for yr in SEASONS:
    for st in ("regular","postseason"):
        weeks=range(1,17) if st=="regular" else [1]
        for wk in weeks:
            for x in get("/ppa/games",year=yr,week=wk,seasonType=st):
                off=x.get("offense") or {}; dfn=x.get("defense") or {}
                prows.append(dict(game_id=x["gameId"],season=yr,week=wk,team=x["team"],
                    ppa_off=off.get("overall"),ppa_off_pass=off.get("passing"),ppa_off_rush=off.get("rushing"),
                    ppa_def=dfn.get("overall"),ppa_def_pass=dfn.get("passing"),ppa_def_rush=dfn.get("rushing")))
    print("ppa",yr,"cum",len(prows))
pd.DataFrame(prows).to_csv(DATA+"/ppa_games.csv",index=False)
print("ppa_games",len(prows)); print("DONE")
