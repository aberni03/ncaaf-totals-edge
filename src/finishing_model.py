"""Add as-of 'finishing' (points per 100 yards, off & def) to the de-anchored model and
re-backtest. Compares MAE and the opener-edge with vs without finishing."""
import warnings, numpy as np, pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingRegressor
warnings.filterwarnings("ignore")
DATA="data"; K=5.0

# ---- as-of finishing per (game_id, team) ----
s=pd.read_csv(f"{DATA}/team_game_stats.csv")
for c in ['netPassingYards','rushingYards','points']: s[c]=pd.to_numeric(s[c],errors='coerce')
s['off_yds']=s.netPassingYards+s.rushingYards
s=s.dropna(subset=['off_yds','points'])
pair=[]
for gid,grp in s.groupby('game_id'):
    if len(grp)!=2: continue
    a,b=grp.iloc[0],grp.iloc[1]
    for me,opp in ((a,b),(b,a)):
        pair.append(dict(game_id=gid,season=me.season,week=me.week,team=me.team,
            off_yds=me.off_yds,off_pts=me.points,def_yds=opp.off_yds,def_pts=opp.points))
tg=pd.DataFrame(pair).sort_values(['team','season','week'])
# cumulative BEFORE current game (no leakage)
for pre in ['off','def']:
    g=tg.groupby(['team','season'])
    tg[f'{pre}_cy']=g[f'{pre}_yds'].cumsum()-tg[f'{pre}_yds']
    tg[f'{pre}_cp']=g[f'{pre}_pts'].cumsum()-tg[f'{pre}_pts']
    tg[f'{pre}_n']=g.cumcount()
# prior-year finishing (season total)
seas=tg.groupby(['team','season']).agg(oy=('off_yds','sum'),op=('off_pts','sum'),
     dy=('def_yds','sum'),dp=('def_pts','sum')).reset_index()
seas['py_off']=seas.op/seas.oy*100; seas['py_def']=seas.dp/seas.dy*100
prior=seas.copy(); prior['season']=prior.season+1
tg=tg.merge(prior[['team','season','py_off','py_def']],on=['team','season'],how='left')
LG_off=6.44; LG_def=6.44
def blend(cp,cy,n,pri,lg):
    cur=(cp/cy*100) if cy and cy>0 else np.nan
    pri=pri if not pd.isna(pri) else lg
    if pd.isna(cur): return pri
    w=n/(n+K); return w*cur+(1-w)*pri
tg['fin_off']=[blend(r.off_cp,r.off_cy,r.off_n,r.py_off,LG_off) for r in tg.itertuples()]
tg['fin_def']=[blend(r.def_cp,r.def_cy,r.def_n,r.py_def,LG_def) for r in tg.itertuples()]
fin=tg[['game_id','team','fin_off','fin_def']]

# ---- merge to features_v2 ----
f=pd.read_csv(f"{DATA}/features_v2.csv")
f=f.merge(fin.rename(columns={'team':'home','fin_off':'fin_off_h','fin_def':'fin_def_h'}),on=['game_id','home'],how='left')
f=f.merge(fin.rename(columns={'team':'away','fin_off':'fin_off_a','fin_def':'fin_def_a'}),on=['game_id','away'],how='left')
for c,lo,hi in [("proj_ypa_h",1,15),("proj_ypa_a",1,15),("proj_yrc_h",1,9),("proj_yrc_a",1,9)]:
    f[c]=f[c].clip(lo,hi)
f=f.dropna(subset=['mkt_total','total_pts']); f=f[f.fbs_both==True].copy()
f['neutral']=f.neutral.fillna(False).astype(int); f['mkt_spread']=f.mkt_spread.fillna(0)
for c in ['fin_off_h','fin_def_h','fin_off_a','fin_def_a']: f[c]=f[c].fillna(6.44)

BASE=["mkt_spread","proj_py_h","proj_ypa_h","proj_ry_h","proj_yrc_h","proj_py_a","proj_ypa_a",
      "proj_ry_a","proj_yrc_a","tempo_h","tempo_a","proj_total_yards","exp_plays",
      "off_ypa_h","def_ypa_h","off_ypc_h","def_ypc_h","off_ypa_a","def_ypa_a","off_ypc_a","def_ypc_a",
      "prate_h","prate_a","neutral","week"]
FIN=BASE+["fin_off_h","fin_def_h","fin_off_a","fin_def_a"]
def run(FEATS):
    rows=[]
    for S in range(2019,2026):
        tr=f[f.season<S]; te=f[f.season==S]
        if len(tr)<500 or len(te)==0: continue
        m=HistGradientBoostingRegressor(max_iter=400,learning_rate=0.03,max_depth=3,
            l2_regularization=1.0,min_samples_leaf=40,random_state=0).fit(tr[FEATS].values,tr.total_pts.values)
        o=te[['game_id','season','week','total_pts','mkt_total','mkt_total_open']].copy()
        o['pred']=m.predict(te[FEATS].values); rows.append(o)
    return pd.concat(rows,ignore_index=True)

def opener_edge(res,edge=3):
    d=res.dropna(subset=['mkt_total_open']).copy(); d['e']=d.pred-d.mkt_total_open
    b=d[d.e.abs()>=edge].copy(); b['side']=np.where(b.e>0,'over','under'); amL=b.total_pts-b.mkt_total_open
    win=((b.side=='over')&(amL>0))|((b.side=='under')&(amL<0)); push=amL==0
    ndec=int((~push).sum()); nwin=int(win.sum()); wp=nwin/ndec*100
    roi=(nwin*.9091-(ndec-nwin))/ndec*100; p=stats.binomtest(nwin,ndec,0.5238,alternative='greater').pvalue
    return ndec,wp,roi,p

for name,FEATS in [("BASE (no finishing)",BASE),("+ FINISHING",FIN)]:
    res=run(FEATS); mae=np.mean(np.abs(res.pred-res.total_pts))
    print(f"\n### {name}:  MAE={mae:.3f}")
    print(f"  {'opener edge>=':>14}{'bets':>6}{'win%':>7}{'ROI%':>7}{'p':>8}")
    for e in [3,4,5]:
        n,wp,roi,p=opener_edge(res,e); print(f"  {e:>14}{n:>6}{wp:>7.1f}{roi:>7.1f}{p:>8.4f}")
