"""Pull transfer portal + coaching data -> per-team-season features:
  data/portal.csv  : net portal talent (incoming minus outgoing)
  data/coaches.csv : new head-coach flag + tenure
"""
import os, time, requests, numpy as np, pandas as pd
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); DATA=ROOT+"/data"
KEY=open(ROOT+"/.cfbd_key").read().strip(); H={"Authorization":f"Bearer {KEY}"}; B="https://api.collegefootballdata.com"
def get(p,**q):
    for a in range(4):
        r=requests.get(B+p,params=q,headers=H,timeout=90)
        if r.status_code==200: return r.json()
        time.sleep(2)
    return []

# ---------- transfer portal ----------
def star_wt(s): return {2:0.75,3:0.83,4:0.93,5:0.99}.get(int(s),0.80) if s else np.nan
prows=[]
for yr in range(2015,2027):
    d=get("/player/portal",year=yr)
    for x in d:
        wt = x.get("rating") if x.get("rating") is not None else star_wt(x.get("stars"))
        st = x.get("stars") or 0
        prows.append(dict(season=yr,origin=x.get("origin"),destination=x.get("destination"),
                          wt=wt,stars=st,blue=1 if st>=4 else 0))
    print("portal",yr,"rows",len(d))
P=pd.DataFrame(prows)
teams=sorted(set(P.origin.dropna())|set(P.destination.dropna()))
rows=[]
for yr in range(2015,2027):
    py=P[P.season==yr]
    for t in teams:
        inc=py[py.destination==t]; out=py[py.origin==t]
        rows.append(dict(season=yr,team=t,
            portal_in_ct=len(inc),portal_out_ct=len(out),portal_net_ct=len(inc)-len(out),
            portal_in_wt=inc.wt.sum(),portal_out_wt=out.wt.sum(),
            portal_net_wt=round(inc.wt.sum()-out.wt.sum(),2),
            portal_in_blue=int(inc.blue.sum()),portal_out_blue=int(out.blue.sum()),
            portal_net_blue=int(inc.blue.sum()-out.blue.sum())))
pd.DataFrame(rows).to_csv(DATA+"/portal.csv",index=False)
print("saved portal.csv")

# ---------- coaches ----------
coach_of={}
for yr in range(2012,2027):
    for c in get("/coaches",year=yr):
        name=f'{c.get("firstName")} {c.get("lastName")}'
        for s in c.get("seasons",[]):
            if s.get("year")==yr and s.get("school"):
                coach_of[(yr,s["school"])]=name
crows=[]
allteams=sorted({t for (y,t) in coach_of})
for yr in range(2015,2027):
    for t in allteams:
        cur=coach_of.get((yr,t)); prev=coach_of.get((yr-1,t))
        new_hc=1 if (cur and prev and cur!=prev) else (1 if (cur and prev is None) else 0)
        # tenure: consecutive prior years with same coach
        ten=0
        if cur:
            y=yr-1
            while coach_of.get((y,t))==cur and y>=2012: ten+=1; y-=1
        crows.append(dict(season=yr,team=t,new_hc=new_hc,hc_tenure=ten))
pd.DataFrame(crows).to_csv(DATA+"/coaches.csv",index=False)
print("saved coaches.csv; new-HC counts by yr:",
      pd.DataFrame(crows).groupby("season").new_hc.sum().to_dict())
