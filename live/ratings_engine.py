"""Core engine shared by training and live projection.
Computes as-of team ratings (opponent-adjusted YPA/YPC off&def, tempo, pass-rate, finishing),
blended: rating = w*current_season + (1-w)*preseason,  w = games/(games+K).
Projects any matchup's box-score drivers exactly as build_features_v2 does."""
import os, numpy as np, pandas as pd
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); DATA=ROOT+"/data"
K_DEFAULT=5.0

def _load():
    st=pd.read_csv(f"{DATA}/team_game_stats.csv")
    for c in ["netPassingYards","pass_att","rushingYards","rushingAttempts","points"]:
        st[c]=pd.to_numeric(st.get(c),errors="coerce")
    st["off_ypa"]=st.netPassingYards/st.pass_att; st["off_ypc"]=st.rushingYards/st.rushingAttempts
    st["plays"]=st.pass_att+st.rushingAttempts; st["prate"]=st.pass_att/st.plays
    st["off_yds"]=st.netPassingYards+st.rushingYards
    st=st.dropna(subset=["off_ypa","off_ypc","plays"])
    pre=pd.read_csv(f"{DATA}/preseason_ratings.csv")
    final=pd.read_csv(f"{DATA}/final_ratings.csv")
    return st, pre, final

ST, PRE_DF, FINAL = _load()
PRE={(r.season,r.team):dict(off_ypa=r.pre_off_ypa,def_ypa=r.pre_def_ypa,off_ypc=r.pre_off_ypc,
     def_ypc=r.pre_def_ypc,tempo=r.pre_tempo,prate=r.pre_prate) for r in PRE_DF.itertuples()}
LGP={s+1:dict(ypa=g.off_ypa.mean(),ypc=g.off_ypc.mean()) for s,g in FINAL.groupby("season")}
# prior-year finishing (pts per 100 off yds)
_seas=ST.groupby(["team","season"]).agg(oy=("off_yds","sum"),op=("points","sum")).reset_index()
_seas["py_off"]=_seas.op/_seas.oy*100
_pfin={(r.season+1,r.team):r.py_off for r in _seas.itertuples()}
# defensive finishing prior needs allowed; approximate via league mean fallback
LG_FIN=6.44

def _paired(df):
    rows=[]
    for gid,grp in df.groupby("game_id"):
        if len(grp)!=2: continue
        a,b=grp.iloc[0],grp.iloc[1]
        for me,opp in ((a,b),(b,a)):
            rows.append(dict(team=me.team,opp=opp.team,off_ypa=me.off_ypa,off_ypc=me.off_ypc,
                def_ypa=opp.off_ypa,def_ypc=opp.off_ypc,plays=me.plays,prate=me.prate,
                off_yds=me.off_yds,off_pts=me.points,def_yds=opp.off_yds,def_pts=opp.points))
    return pd.DataFrame(rows)

def _adjust(df,iters=4):
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
    fin_off={t:(idx[t].off_pts.sum()/idx[t].off_yds.sum()*100) if idx[t].off_yds.sum()>0 else np.nan for t in teams}
    fin_def={t:(idx[t].def_pts.sum()/idx[t].def_yds.sum()*100) if idx[t].def_yds.sum()>0 else np.nan for t in teams}
    gp={t:len(idx[t]) for t in teams}
    return dict(off_ypa=oa,def_ypa=da,off_ypc=oc,def_ypc=dc,tempo=tempo,prate=prate,
                fin_off=fin_off,fin_def=fin_def,gp=gp),lg

def compute_ratings(season, upto_week, K=K_DEFAULT):
    """Team ratings entering `upto_week` of `season` (uses only weeks < upto_week)."""
    cur=ST[(ST.season==season)&(ST.week<upto_week)]
    rc,_=_adjust(_paired(cur)) if len(cur)>=2 else ({},None)
    lg=LGP.get(season,dict(ypa=7.2,ypc=4.6))
    teams=set(list(rc.get("off_ypa",{}).keys())+[t for (s,t) in PRE if s==season])
    out={}
    for t in teams:
        gp=rc.get("gp",{}).get(t,0); w=gp/(gp+K)
        pri=PRE.get((season,t))
        row={"gp":gp,"w":round(w,3)}
        for key in ["off_ypa","def_ypa","off_ypc","def_ypc","tempo","prate"]:
            cv=rc.get(key,{}).get(t); pv=pri[key] if pri else None
            fb=dict(off_ypa=lg["ypa"],def_ypa=lg["ypa"],off_ypc=lg["ypc"],def_ypc=lg["ypc"],tempo=140.,prate=.5)[key]
            row[key]= fb if (cv is None and pv is None) else (pv if cv is None else (cv if pv is None else w*cv+(1-w)*pv))
        # finishing: current cumulative blended with prior-year off finishing
        for key,primap in [("fin_off",_pfin.get((season,t),LG_FIN)),("fin_def",LG_FIN)]:
            cv=rc.get(key,{}).get(t)
            row[key]= primap if (cv is None or pd.isna(cv)) else w*cv+(1-w)*primap
        out[t]=row
    return out, lg

FEATURES=["mkt_spread","proj_py_h","proj_ypa_h","proj_ry_h","proj_yrc_h","proj_py_a","proj_ypa_a",
    "proj_ry_a","proj_yrc_a","tempo_h","tempo_a","proj_total_yards","exp_plays",
    "off_ypa_h","def_ypa_h","off_ypc_h","def_ypc_h","off_ypa_a","def_ypa_a","off_ypc_a","def_ypc_a",
    "prate_h","prate_a","neutral","week","fin_off_h","fin_def_h","fin_off_a","fin_def_a"]

def project_matchup(home, away, ratings, lg, week=6, neutral=0, mkt_spread=0.0):
    rh,ra=ratings.get(home),ratings.get(away)
    if rh is None or ra is None: return None
    lgypa,lgypc=lg["ypa"],lg["ypc"]
    exp_plays=0.5*(rh["tempo"]+ra["tempo"])
    h_pa=exp_plays*rh["prate"]; h_ra=exp_plays*(1-rh["prate"]); a_pa=exp_plays*ra["prate"]; a_ra=exp_plays*(1-ra["prate"])
    def clip(v,lo,hi): return max(lo,min(hi,v))
    h_ypa=clip(rh["off_ypa"]*ra["def_ypa"]/lgypa,1,15); a_ypa=clip(ra["off_ypa"]*rh["def_ypa"]/lgypa,1,15)
    h_ypc=clip(rh["off_ypc"]*ra["def_ypc"]/lgypc,1,9); a_ypc=clip(ra["off_ypc"]*rh["def_ypc"]/lgypc,1,9)
    h_py=h_pa*h_ypa; a_py=a_pa*a_ypa; h_ry=h_ra*h_ypc; a_ry=a_ra*a_ypc
    return {"mkt_spread":mkt_spread,"proj_py_h":h_py,"proj_ypa_h":h_ypa,"proj_ry_h":h_ry,"proj_yrc_h":h_ypc,
        "proj_py_a":a_py,"proj_ypa_a":a_ypa,"proj_ry_a":a_ry,"proj_yrc_a":a_ypc,
        "tempo_h":rh["tempo"],"tempo_a":ra["tempo"],"exp_plays":exp_plays,
        "proj_total_yards":h_py+h_ry+a_py+a_ry,
        "off_ypa_h":rh["off_ypa"],"def_ypa_h":rh["def_ypa"],"off_ypc_h":rh["off_ypc"],"def_ypc_h":rh["def_ypc"],
        "off_ypa_a":ra["off_ypa"],"def_ypa_a":ra["def_ypa"],"off_ypc_a":ra["off_ypc"],"def_ypc_a":ra["def_ypc"],
        "prate_h":rh["prate"],"prate_a":ra["prate"],"neutral":neutral,"week":week,
        "fin_off_h":rh["fin_off"],"fin_def_h":rh["fin_def"],"fin_off_a":ra["fin_off"],"fin_def_a":ra["fin_def"]}
