"""Build walk-forward PRESEASON rating projections for each team-season.
Target: my opponent-adjusted final ratings (off/def YPA & YPC, tempo, pass-rate).
Features (all known before Week 1): prior-yr & 2-yr ratings, returning production,
recruiting (current + trailing), prior-yr SP+.  Model trained only on seasons < N.
Also writes final_ratings.csv (used as in-season target + carryover)."""
import os, warnings, numpy as np, pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
warnings.filterwarnings("ignore")
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); DATA=ROOT+"/data"

st=pd.read_csv(DATA+"/team_game_stats.csv")
for c in ["netPassingYards","pass_att","rushingYards","rushingAttempts"]:
    st[c]=pd.to_numeric(st.get(c),errors="coerce")
st["off_ypa"]=st.netPassingYards/st.pass_att
st["off_ypc"]=st.rushingYards/st.rushingAttempts
st["plays"]=st.pass_att+st.rushingAttempts
st["prate"]=st.pass_att/st.plays
st=st.dropna(subset=["off_ypa","off_ypc","plays"])
pieces=[]
for gid,grp in st.groupby("game_id"):
    if len(grp)!=2: continue
    a,b=grp.iloc[0],grp.iloc[1]
    for me,opp in ((a,b),(b,a)):
        pieces.append(dict(season=me.season,team=me.team,opp=opp.team,off_ypa=me.off_ypa,
            off_ypc=me.off_ypc,def_ypa=opp.off_ypa,def_ypc=opp.off_ypc,plays=me.plays,prate=me.prate))
tg=pd.DataFrame(pieces)
# exclude the CURRENT incomplete season from final-rating targets — it's the preseason target,
# not a completed season. (Otherwise a partial season shifts CUR and drops not-yet-played teams.)
_cf=pd.read_csv(DATA+"/games.csv").groupby("season").completed.mean()
_incomplete=set(_cf[_cf<0.9].index)
tg=tg[~tg.season.isin(_incomplete)]

def adjust(df,iters=5):
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
    return oa,da,oc,dc,tempo,prate,lg

# final ratings per season
frows=[]; LG={}
for season,grp in tg.groupby("season"):
    oa,da,oc,dc,tempo,prate,lg=adjust(grp); LG[season]=lg
    for t in grp.team.unique():
        frows.append(dict(season=season,team=t,off_ypa=oa[t],def_ypa=da[t],off_ypc=oc[t],
            def_ypc=dc[t],tempo=tempo[t],prate=prate[t]))
final=pd.DataFrame(frows)
final.to_csv(DATA+"/final_ratings.csv",index=False); print("final_ratings",final.shape)

# add placeholder rows for the CURRENT (incomplete) season so we can project its preseason ratings
CUR=int(final.season.max())+1  # e.g. 2026
cur_teams=set(pd.read_csv(DATA+"/recruiting.csv").query("season==@CUR").team) | \
          set(pd.read_csv(DATA+"/returning.csv").query("season==@CUR").team)
if cur_teams:
    ph=pd.DataFrame([dict(season=CUR,team=t,**{c:np.nan for c in
        ["off_ypa","def_ypa","off_ypc","def_ypc","tempo","prate"]}) for t in cur_teams])
    final=pd.concat([final,ph],ignore_index=True)
    print(f"added {len(ph)} placeholder rows for current season {CUR}")

# offseason feature tables
ret=pd.read_csv(DATA+"/returning.csv"); rec=pd.read_csv(DATA+"/recruiting.csv"); sp=pd.read_csv(DATA+"/sp.csv")
rec["rec_points"]=pd.to_numeric(rec.rec_points,errors="coerce")
rec=rec.sort_values(["team","season"])
rec["rec_pts_3yr"]=rec.groupby("team").rec_points.transform(lambda s:s.rolling(3,min_periods=1).mean())

TARGETS=["off_ypa","def_ypa","off_ypc","def_ypc","tempo","prate"]
# assemble training frame: for each team-season N, features from N-1/N-2 + preseason-known N
f=final.copy()
prev=final.copy(); prev["season"]=prev.season+1
f=f.merge(prev[["season","team"]+TARGETS].rename(columns={c:"p1_"+c for c in TARGETS}),on=["season","team"],how="left")
prev2=final.copy(); prev2["season"]=prev2.season+2
f=f.merge(prev2[["season","team"]+TARGETS].rename(columns={c:"p2_"+c for c in TARGETS}),on=["season","team"],how="left")
f=f.merge(ret,on=["season","team"],how="left")
f=f.merge(rec[["season","team","rec_points","rec_pts_3yr"]],on=["season","team"],how="left")
spp=sp.copy(); spp["season"]=spp.season+1  # prior-year SP+
f=f.merge(spp.rename(columns={"sp_rating":"p1_sp","sp_off":"p1_sp_off","sp_def":"p1_sp_def"}),
          on=["season","team"],how="left")
# v2: transfer portal net talent + coaching change (known preseason)
portal=pd.read_csv(DATA+"/portal.csv"); coaches=pd.read_csv(DATA+"/coaches.csv")
f=f.merge(portal[["season","team","portal_net_wt","portal_net_ct","portal_net_blue","portal_in_wt"]],on=["season","team"],how="left")
f=f.merge(coaches[["season","team","new_hc","hc_tenure"]],on=["season","team"],how="left")
for c in ["portal_net_wt","portal_net_ct","portal_net_blue","portal_in_wt","new_hc"]:
    f[c]=f[c].fillna(0)
f["hc_tenure"]=f["hc_tenure"].fillna(3)

FEATS_BASE=["p1_off_ypa","p1_def_ypa","p1_off_ypc","p1_def_ypc","p1_tempo","p1_prate",
       "p2_off_ypa","p2_def_ypa","p2_off_ypc","p2_def_ypc",
       "ret_ppa","ret_pass_ppa","ret_rush_ppa","rec_points","rec_pts_3yr","p1_sp","p1_sp_off","p1_sp_def"]
FEATS_V2=FEATS_BASE+["portal_net_wt","portal_net_ct","portal_net_blue","portal_in_wt","new_hc","hc_tenure"]
for c in FEATS_V2:
    f[c]=pd.to_numeric(f[c],errors="coerce")

def project(feats):
    fillvals={c:f[c].median() for c in feats}
    def prep(df):
        X=df[feats].copy()
        for c in feats: X[c]=X[c].fillna(fillvals[c])
        return X
    rows=[]
    for N in range(2016,CUR+1):
        tr=f[(f.season<N)&(f.p1_off_ypa.notna())&(f.off_ypa.notna())]
        te=f[f.season==N]
        if len(tr)<200 or len(te)==0: continue
        sc=StandardScaler().fit(prep(tr)); Xtr2,Xte2=sc.transform(prep(tr)),sc.transform(prep(te))
        out=te[["season","team"]].copy()
        for tgt in TARGETS:
            out["pre_"+tgt]=Ridge(alpha=5.0).fit(Xtr2,tr[tgt].values).predict(Xte2)
        rows.append(out)
    return pd.concat(rows,ignore_index=True)

pre_base=project(FEATS_BASE)
pre_v2=project(FEATS_V2)
# FINDING: portal + coaching features add ~0 lift to per-play efficiency projection (see below).
# Keep the parsimonious BASE model as production; v2 kept only for the documented comparison.
pre=pre_base
pre.to_csv(DATA+"/preseason_ratings.csv",index=False)
print("preseason_ratings (BASE — production)",pre.shape,"seasons",sorted(pre.season.unique()))

# lift: v2 vs base projection MAE to actual final rating (completed seasons only)
def mae_to_final(p):
    c=p.merge(final,on=["season","team"])
    return {t:(c["pre_"+t]-c[t]).abs().mean() for t in TARGETS}
mb,mv=mae_to_final(pre_base),mae_to_final(pre_v2)
print("\n=== v2 (portal+coaching) vs base preseason projection — MAE to actual final rating ===")
for t in TARGETS:
    print(f"  {t:<9} base={mb[t]:.3f}  v2={mv[t]:.3f}  lift={100*(1-mv[t]/mb[t]):+.1f}%")
