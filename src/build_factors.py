"""Augment features.csv with extra factors -> features2.csv
Adds: rest days (each team), travel distance (away), dome, elevation, grass,
cold-late-season proxy, and as-of PPA (explosiveness) ratings for both teams.
All time-varying inputs use only prior information (no leakage)."""
import os, numpy as np, pandas as pd
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA=os.path.join(ROOT,"data")

feat=pd.read_csv(DATA+"/features.csv")
games=pd.read_csv(DATA+"/games.csv")
gv=pd.read_csv(DATA+"/game_venue.csv")
ven=pd.read_csv(DATA+"/venues.csv")
loc=pd.read_csv(DATA+"/teams_loc.csv")
ppa=pd.read_csv(DATA+"/ppa_games.csv")

# ---- game date + venue geo ----
gv["start_date"]=pd.to_datetime(gv["start_date"],utc=True,errors="coerce")
feat=feat.merge(gv,on="game_id",how="left")
feat=feat.merge(ven[["venue_id","dome","elevation","grass","lat","lon"]],on="venue_id",how="left")
feat["dome"]=feat["dome"].fillna(False).astype(int)
feat["grass"]=feat["grass"].fillna(True).astype(int)
feat["elevation"]=pd.to_numeric(feat["elevation"],errors="coerce").fillna(200.0)
feat["month"]=feat["start_date"].dt.month
feat["cold_late"]=(((feat["month"]>=11)|(feat["month"]<=1)) & (feat["dome"]==0) & (feat["lat"]>=40)).astype(int)

# ---- rest days per team ----
g=games[["game_id","season","home","away","start_date"]].copy()
g["start_date"]=pd.to_datetime(g["start_date"],utc=True,errors="coerce")
long=pd.concat([
    g.rename(columns={"home":"team"})[["game_id","season","team","start_date"]],
    g.rename(columns={"away":"team"})[["game_id","season","team","start_date"]],
],ignore_index=True).dropna(subset=["start_date"])
long=long.sort_values(["team","season","start_date"])
long["prev"]=long.groupby(["team","season"])["start_date"].shift(1)
long["rest"]=(long["start_date"]-long["prev"]).dt.days
long["rest"]=long["rest"].clip(3,21).fillna(7)   # season opener -> 7
rest=long.set_index(["game_id","team"])["rest"].to_dict()
feat["rest_h"]=[rest.get((gid,t),7) for gid,t in zip(feat.game_id,feat.home)]
feat["rest_a"]=[rest.get((gid,t),7) for gid,t in zip(feat.game_id,feat.away)]
feat["rest_diff"]=feat["rest_h"]-feat["rest_a"]

# ---- travel distance (away team home -> venue) ----
loc_last=loc.sort_values("season").drop_duplicates("team",keep="last").set_index("team")
def haversine(lat1,lon1,lat2,lon2):
    if any(pd.isna([lat1,lon1,lat2,lon2])): return np.nan
    R=3959.0; import math
    p1,p2=math.radians(lat1),math.radians(lat2)
    dp=math.radians(lat2-lat1); dl=math.radians(lon2-lon1)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(a))
def team_home(t):
    if t in loc_last.index:
        r=loc_last.loc[t]; return r.home_lat,r.home_lon
    return (np.nan,np.nan)
tr=[]
for r in feat.itertuples():
    alat,alon=team_home(r.away); d=haversine(alat,alon,r.lat,r.lon)
    tr.append(d if not pd.isna(d) else 800.0)   # median-ish fallback
feat["travel_a"]=tr

# ---- as-of PPA ratings (season-to-date, shrunk to prior-season final) ----
for c in ["ppa_off","ppa_def","ppa_off_pass","ppa_off_rush","ppa_def_pass","ppa_def_rush"]:
    ppa[c]=pd.to_numeric(ppa[c],errors="coerce")
ppa=ppa.dropna(subset=["ppa_off","ppa_def"])
prior_final={}
for season,grp in ppa.groupby("season"):
    prior_final[season]={t:grp[grp.team==t][["ppa_off","ppa_def"]].mean().to_dict()
                         for t in grp.team.unique()}
K=3.0
PCOLS=["ppa_off","ppa_def"]
def asof_ppa(season,week):
    cur=ppa[(ppa.season==season)&(ppa.week<week)]
    curm={t:cur[cur.team==t][PCOLS].mean().to_dict() for t in cur.team.unique()}
    curn=cur.groupby("team").size().to_dict()
    pri=prior_final.get(season-1,{})
    teams=set(list(curm.keys())+list(pri.keys()))
    out={}
    for t in teams:
        n=curn.get(t,0); w=n/(n+K)
        row={}
        for c in PCOLS:
            cv=curm.get(t,{}).get(c); pv=pri.get(t,{}).get(c)
            if cv is None and pv is None: row[c]=0.0
            elif cv is None: row[c]=pv
            elif pv is None: row[c]=cv
            else: row[c]=w*cv+(1-w)*pv
        out[t]=row
    return out
po_h,pd_h,po_a,pd_a=[],[],[],[]
for (season,week),grp in feat.groupby(["season","week"]):
    R=asof_ppa(season,week)
    for r in grp.itertuples():
        rh=R.get(r.home,{"ppa_off":0.0,"ppa_def":0.0}); ra=R.get(r.away,{"ppa_off":0.0,"ppa_def":0.0})
        po_h.append((r.Index,rh["ppa_off"])); pd_h.append((r.Index,rh["ppa_def"]))
        po_a.append((r.Index,ra["ppa_off"])); pd_a.append((r.Index,ra["ppa_def"]))
for name,lst in [("ppa_off_h",po_h),("ppa_def_h",pd_h),("ppa_off_a",po_a),("ppa_def_a",pd_a)]:
    s=pd.Series(dict(lst)); feat[name]=feat.index.map(s)
# combined expected scoring environment from PPA
feat["ppa_env"]=feat.ppa_off_h+feat.ppa_off_a-feat.ppa_def_h-feat.ppa_def_a

feat.to_csv(DATA+"/features2.csv",index=False)
print("features2.csv",feat.shape)
print("new cols sample:")
print(feat[["dome","elevation","cold_late","rest_h","rest_a","travel_a","ppa_off_h","ppa_def_a","ppa_env"]].describe().round(2).to_string())
