"""Test the opponent-CALIBER interaction hypothesis:
Do teams under/over-perform their SOS-adjusted per-play efficiency specifically vs elite
opponents, beyond the linear opponent adjustment? Is any per-team effect repeatable?"""
import os, warnings, numpy as np, pandas as pd
from scipy import stats
warnings.filterwarnings("ignore")
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); DATA=ROOT+"/data"
stats_df=pd.read_csv(DATA+"/team_game_stats.csv")

s=stats_df.copy()
for c in ["netPassingYards","pass_att","rushingYards","rushingAttempts","points"]:
    s[c]=pd.to_numeric(s.get(c),errors="coerce")
s["off_ypa"]=s.netPassingYards/s.pass_att
s["off_ypc"]=s.rushingYards/s.rushingAttempts
s=s.dropna(subset=["off_ypa","off_ypc"])
# pair opponents
pieces=[]
for gid,grp in s.groupby("game_id"):
    if len(grp)!=2: continue
    a,b=grp.iloc[0],grp.iloc[1]
    for me,opp in ((a,b),(b,a)):
        pieces.append(dict(season=me.season,week=me.week,team=me.team,opp=opp.team,
            off_ypa=me.off_ypa,off_ypc=me.off_ypc,def_ypa=opp.off_ypa,def_ypc=opp.off_ypc,points=me.points))
tg=pd.DataFrame(pieces)

def adjust(df,iters=5):
    lg=dict(ypa=df.off_ypa.mean(),ypc=df.off_ypc.mean())
    teams=df.team.unique()
    oa={t:df.loc[df.team==t,"off_ypa"].mean() for t in teams}
    da={t:df.loc[df.team==t,"def_ypa"].mean() for t in teams}
    oc={t:df.loc[df.team==t,"off_ypc"].mean() for t in teams}
    dc={t:df.loc[df.team==t,"def_ypc"].mean() for t in teams}
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
    return oa,da,oc,dc,lg

# full-season ratings per season; compute per-game residual vs multiplicative SOS expectation
allres=[]
for season,grp in tg.groupby("season"):
    oa,da,oc,dc,lg=adjust(grp)
    # overall team quality (net efficiency), rank -> caliber
    q={t:(oa.get(t,lg["ypa"])-da.get(t,lg["ypa"]))+(oc.get(t,lg["ypc"])-dc.get(t,lg["ypc"])) for t in grp.team.unique()}
    qrank=pd.Series(q).rank(ascending=False)  # 1 = best team
    g=grp.copy()
    g["exp_ypa"]=g.team.map(oa)*g.opp.map(da)/lg["ypa"]
    g["exp_ypc"]=g.team.map(oc)*g.opp.map(dc)/lg["ypc"]
    g["res_ypa"]=g.off_ypa-g.exp_ypa
    g["res_ypc"]=g.off_ypc-g.exp_ypc
    # normalize residual to % of expected (so 20% worse is comparable across teams)
    g["res_ypa_pct"]=g.res_ypa/g.exp_ypa
    g["opp_qrank"]=g.opp.map(qrank)
    g["opp_top25"]=(g.opp_qrank<=25).astype(int)
    g["team_qrank"]=g.team.map(qrank)
    allres.append(g)
R=pd.concat(allres,ignore_index=True)
R=R[R.week>=3]  # ratings need a little data to be meaningful

print("========== (1) LEAGUE-WIDE: residual efficiency by OPPONENT caliber ==========")
print("(residual = actual YPA - SOS-expected YPA; negative = worse than SOS predicts)")
bins=[(1,10,'opp top 1-10'),(11,25,'opp 11-25'),(26,50,'opp 26-50'),(51,80,'opp 51-80'),(81,999,'opp 81+')]
print(f"{'opp caliber':<16}{'n':>7}{'mean res YPA':>13}{'res as % exp':>14}")
for lo,hi,lab in bins:
    b=R[(R.opp_qrank>=lo)&(R.opp_qrank<=hi)]
    print(f"{lab:<16}{len(b):>7}{b.res_ypa.mean():>13.3f}{b.res_ypa_pct.mean()*100:>13.1f}%")

print("\n========== (2) Is there a TEAM-SPECIFIC 'step-down vs elite' trait? ==========")
# per team-season: avg residual% vs top25 minus vs rest
rows=[]
for (season,team),g in R.groupby(["season","team"]):
    vE=g[g.opp_top25==1].res_ypa_pct; vR=g[g.opp_top25==0].res_ypa_pct
    if len(vE)>=2 and len(vR)>=2:
        rows.append(dict(season=season,team=team,stepdown=vE.mean()-vR.mean(),n_elite=len(vE)))
sd=pd.DataFrame(rows)
print(f"team-seasons with >=2 elite games: {len(sd)}")
print(f"league mean step-down (elite - rest), % of expected: {sd.stepdown.mean()*100:.1f}%")
# year-over-year reliability: does a team's stepdown in season t predict t+1?
j=sd.merge(sd,on="team",suffixes=("_t","_t1"))
j=j[j.season_t1==j.season_t+1]
if len(j)>10:
    r,p=stats.pearsonr(j.stepdown_t,j.stepdown_t1)
    print(f"year-over-year reliability of team step-down: r={r:.3f} (p={p:.3f}, n={len(j)})")
    print("  -> r near 0 = NOT a repeatable trait (noise); r>0.3 = real & usable")
# also split-half within-season stability check via correlation of elite-game residuals
print(f"std of team step-down across team-seasons: {sd.stepdown.std()*100:.1f}%  "
      f"(noise band if games few)")

print("\n========== (3) does opp-caliber residual predict TEAM TOTAL points miss? ==========")
# aggregate to game total: sum both teams' residual points proxy
print("corr(opp_top25, res_ypa_pct):",round(R.opp_top25.corr(R.res_ypa_pct),3))
print("mean res% vs top-10 opp:",round(R[R.opp_qrank<=10].res_ypa_pct.mean()*100,1),
      "%   vs rest:",round(R[R.opp_qrank>25].res_ypa_pct.mean()*100,1),"%")
R.to_csv(ROOT+"/out/caliber_residuals.csv",index=False)
print("saved out/caliber_residuals.csv")
