"""Rebuild feature table using PRESEASON projection as the Week-1 prior, with current-season
as-of ratings taking over as games accrue:  rating = w*current + (1-w)*preseason,  w=gp/(gp+K).
K controls how fast current data overtakes the preseason estimate (default 5)."""
import os, sys, warnings, numpy as np, pandas as pd
warnings.filterwarnings("ignore")
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); DATA=ROOT+"/data"
K=float(sys.argv[1]) if len(sys.argv)>1 else 5.0

games=pd.read_csv(DATA+"/games.csv")
lines=pd.read_csv(DATA+"/lines.csv")
stats=pd.read_csv(DATA+"/team_game_stats.csv")
pre=pd.read_csv(DATA+"/preseason_ratings.csv")
final=pd.read_csv(DATA+"/final_ratings.csv")

games=games[games.completed==True].copy()
games["home_pts"]=pd.to_numeric(games.home_pts,errors="coerce"); games["away_pts"]=pd.to_numeric(games.away_pts,errors="coerce")
games=games.dropna(subset=["home_pts","away_pts"])
games["total_pts"]=games.home_pts+games.away_pts
games["fbs_both"]=(games.home_div=="fbs")&(games.away_div=="fbs")

def consensus(df,col):
    d=df.dropna(subset=[col])
    if len(d)==0: return np.nan
    c=d[d.provider=="consensus"]
    return c[col].median() if len(c) else d[col].median()
mk=[]
for gid,grp in lines.groupby("game_id"):
    mk.append(dict(game_id=gid,mkt_total=consensus(grp,"over_under"),
        mkt_total_open=consensus(grp,"over_under_open"),mkt_spread=consensus(grp,"spread")))
games=games.merge(pd.DataFrame(mk),on="game_id",how="left")

# per-team-game efficiency + opponent
s=stats.copy()
for c in ["netPassingYards","pass_att","rushingYards","rushingAttempts"]:
    s[c]=pd.to_numeric(s.get(c),errors="coerce")
s["off_ypa"]=s.netPassingYards/s.pass_att; s["off_ypc"]=s.rushingYards/s.rushingAttempts
s["plays"]=s.pass_att+s.rushingAttempts; s["prate"]=s.pass_att/s.plays
s=s.dropna(subset=["off_ypa","off_ypc","plays"])
tgp=[]
for gid,grp in s.groupby("game_id"):
    if len(grp)!=2: continue
    a,b=grp.iloc[0],grp.iloc[1]
    for me,opp in ((a,b),(b,a)):
        tgp.append(dict(game_id=gid,season=me.season,week=me.week,team=me.team,opp=opp.team,
            off_ypa=me.off_ypa,off_ypc=me.off_ypc,def_ypa=opp.off_ypa,def_ypc=opp.off_ypc,
            plays=me.plays,prate=me.prate))
tg=pd.DataFrame(tgp)

# preseason prior dict
PRE={}
for r in pre.itertuples():
    PRE[(r.season,r.team)]=dict(off_ypa=r.pre_off_ypa,def_ypa=r.pre_def_ypa,off_ypc=r.pre_off_ypc,
        def_ypc=r.pre_def_ypc,tempo=r.pre_tempo,prate=r.pre_prate)
# stable league normalizer = prior-season final means
LGP={}
for season,grp in final.groupby("season"):
    LGP[season+1]=dict(ypa=grp.off_ypa.mean(),ypc=grp.off_ypc.mean())

def adjust(df,iters=4):
    if len(df)==0: return {},dict(ypa=7.2,ypc=4.6)
    lg=dict(ypa=df.off_ypa.mean(),ypc=df.off_ypc.mean())
    teams=df.team.unique()
    oa={t:df.loc[df.team==t,"off_ypa"].mean() for t in teams}; da={t:df.loc[df.team==t,"def_ypa"].mean() for t in teams}
    oc={t:df.loc[df.team==t,"off_ypc"].mean() for t in teams}; dc={t:df.loc[df.team==t,"def_ypc"].mean() for t in teams}
    idx={t:df[df.team==t] for t in teams}
    for _ in range(iters):
        no,nd,no2,nd2={},{},{},{}
        for t in teams:
            d=idx[t]
            no[t]=(d.off_ypa-(d.opp.map(da).fillna(lg["ypa"])-lg["ypa"])).mean()
            nd[t]=(d.def_ypa-(d.opp.map(oa).fillna(lg["ypa"])-lg["ypa"])).mean()
            no2[t]=(d.off_ypc-(d.opp.map(dc).fillna(lg["ypc"])-lg["ypc"])).mean()
            nd2[t]=(d.def_ypc-(d.opp.map(oc).fillna(lg["ypc"])-lg["ypc"])).mean()
        oa,da,oc,dc=no,nd,no2,nd2
    tempo={t:idx[t].plays.mean() for t in teams}; prate={t:idx[t].prate.mean() for t in teams}
    gp={t:len(idx[t]) for t in teams}
    return dict(off_ypa=oa,def_ypa=da,off_ypc=oc,def_ypc=dc,tempo=tempo,prate=prate,gp=gp),lg

def ratings_asof(season,week):
    cur=tg[(tg.season==season)&(tg.week<week)]
    rc,_=adjust(cur)
    teams=set(list(rc.get("off_ypa",{}).keys())+[t for (sea,t) in PRE if sea==season])
    lg=LGP.get(season,dict(ypa=7.2,ypc=4.6))
    out={}
    for t in teams:
        gp=rc.get("gp",{}).get(t,0); w=gp/(gp+K)
        pri=PRE.get((season,t))
        row={}
        for key in ["off_ypa","def_ypa","off_ypc","def_ypc","tempo","prate"]:
            cv=rc.get(key,{}).get(t); pv=pri[key] if pri else None
            if cv is None and pv is None:
                row[key]=dict(off_ypa=lg["ypa"],def_ypa=lg["ypa"],off_ypc=lg["ypc"],def_ypc=lg["ypc"],tempo=140.,prate=.5)[key]
            elif cv is None: row[key]=pv
            elif pv is None: row[key]=cv
            else: row[key]=w*cv+(1-w)*pv
        row["w"]=w
        out[t]=row
    return out,lg

rows=[]
for (season,week),grp in games.groupby(["season","week"]):
    if season<2017: continue
    R,lg=ratings_asof(season,week); lgypa,lgypc=lg["ypa"],lg["ypc"]
    for gme in grp.itertuples():
        rh,ra=R.get(gme.home),R.get(gme.away)
        if rh is None or ra is None: continue
        exp_plays=0.5*(rh["tempo"]+ra["tempo"])
        h_pa=exp_plays*rh["prate"]; h_ra=exp_plays*(1-rh["prate"]); a_pa=exp_plays*ra["prate"]; a_ra=exp_plays*(1-ra["prate"])
        h_ypa=rh["off_ypa"]*ra["def_ypa"]/lgypa; a_ypa=ra["off_ypa"]*rh["def_ypa"]/lgypa
        h_ypc=rh["off_ypc"]*ra["def_ypc"]/lgypc; a_ypc=ra["off_ypc"]*rh["def_ypc"]/lgypc
        h_py=h_pa*h_ypa; a_py=a_pa*a_ypa; h_ry=h_ra*h_ypc; a_ry=a_ra*a_ypc
        rows.append(dict(game_id=gme.game_id,season=season,week=week,home=gme.home,away=gme.away,
            neutral=gme.neutral,fbs_both=gme.fbs_both,total_pts=gme.total_pts,
            mkt_total=gme.mkt_total,mkt_total_open=gme.mkt_total_open,mkt_spread=gme.mkt_spread,
            proj_py_h=h_py,proj_ypa_h=h_ypa,proj_ry_h=h_ry,proj_yrc_h=h_ypc,
            proj_py_a=a_py,proj_ypa_a=a_ypa,proj_ry_a=a_ry,proj_yrc_a=a_ypc,
            tempo_h=rh["tempo"],tempo_a=ra["tempo"],exp_plays=exp_plays,
            proj_total_yards=h_py+h_ry+a_py+a_ry,
            off_ypa_h=rh["off_ypa"],def_ypa_h=rh["def_ypa"],off_ypc_h=rh["off_ypc"],def_ypc_h=rh["def_ypc"],
            off_ypa_a=ra["off_ypa"],def_ypa_a=ra["def_ypa"],off_ypc_a=ra["off_ypc"],def_ypc_a=ra["def_ypc"],
            prate_h=rh["prate"],prate_a=ra["prate"],pre_w_h=rh["w"],pre_w_a=ra["w"]))
feat=pd.DataFrame(rows)
feat.to_csv(DATA+"/features_v2.csv",index=False)
print("features_v2.csv",feat.shape,"K=",K)
print("2025 fbs w/mkt:",int(((feat.season==2025)&feat.mkt_total.notna()&(feat.fbs_both==True)).sum()))
