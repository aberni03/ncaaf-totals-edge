"""Pull offseason/preseason-known data: returning production, recruiting, SP+ ratings."""
import os, time, requests, pandas as pd
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); DATA=ROOT+"/data"
KEY=open(ROOT+"/.cfbd_key").read().strip(); H={"Authorization":f"Bearer {KEY}"}
B="https://api.collegefootballdata.com"; SEASONS=list(range(2013,2026))
def get(path,**p):
    for a in range(5):
        r=requests.get(B+path,params=p,headers=H,timeout=90)
        if r.status_code==200: return r.json()
        if r.status_code==429: time.sleep(3*(a+1)); continue
        print("WARN",path,p,r.status_code); time.sleep(1)
    return []

ret=[]
for yr in SEASONS:
    for x in get("/player/returning",year=yr):
        ret.append(dict(season=yr,team=x["team"],ret_ppa=x.get("percentPPA"),
            ret_pass_ppa=x.get("percentPassingPPA"),ret_rush_ppa=x.get("percentRushingPPA"),
            ret_rec_ppa=x.get("percentReceivingPPA"),usage=x.get("usage")))
pd.DataFrame(ret).to_csv(DATA+"/returning.csv",index=False); print("returning",len(ret))

rec=[]
for yr in SEASONS:
    for x in get("/recruiting/teams",year=yr):
        rec.append(dict(season=yr,team=x["team"],rec_rank=x.get("rank"),rec_points=x.get("points")))
pd.DataFrame(rec).to_csv(DATA+"/recruiting.csv",index=False); print("recruiting",len(rec))

sp=[]
for yr in SEASONS:
    for x in get("/ratings/sp",year=yr):
        if x.get("team")=="nationalAverages": continue
        sp.append(dict(season=yr,team=x["team"],sp_rating=x.get("rating"),
            sp_off=(x.get("offense") or {}).get("rating"),sp_def=(x.get("defense") or {}).get("rating")))
pd.DataFrame(sp).to_csv(DATA+"/sp.csv",index=False); print("sp",len(sp))
print("DONE")
