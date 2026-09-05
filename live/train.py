"""Train and freeze the de-anchored totals GBM (with finishing) on all completed data.
Saves models/totals.joblib + models/meta.json. Uses the SAME feature columns the live
engine produces (ratings_engine.FEATURES)."""
import os, json, warnings, numpy as np, pandas as pd, joblib
from sklearn.ensemble import HistGradientBoostingRegressor
warnings.filterwarnings("ignore")
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); DATA=ROOT+"/data"; MODELS=ROOT+"/models"
os.makedirs(MODELS,exist_ok=True)
import sys; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from ratings_engine import FEATURES

# training table = features_v2 (has proj drivers as-of, leak-free) + finishing merged
f=pd.read_csv(f"{DATA}/features_v2.csv")
# finishing per (game_id, team), as-of (mirror finishing_model.py)
s=pd.read_csv(f"{DATA}/team_game_stats.csv")
for c in ['netPassingYards','rushingYards','points']: s[c]=pd.to_numeric(s[c],errors='coerce')
s['off_yds']=s.netPassingYards+s.rushingYards; s=s.dropna(subset=['off_yds','points'])
pair=[]
for gid,grp in s.groupby('game_id'):
    if len(grp)!=2: continue
    a,b=grp.iloc[0],grp.iloc[1]
    for me,opp in ((a,b),(b,a)):
        pair.append(dict(game_id=gid,season=me.season,week=me.week,team=me.team,
            off_yds=me.off_yds,off_pts=me.points,def_yds=opp.off_yds,def_pts=opp.points))
tg=pd.DataFrame(pair).sort_values(['team','season','week'])
for pre in ['off','def']:
    g=tg.groupby(['team','season'])
    tg[f'{pre}_cy']=g[f'{pre}_yds'].cumsum()-tg[f'{pre}_yds']
    tg[f'{pre}_cp']=g[f'{pre}_pts'].cumsum()-tg[f'{pre}_pts']
    tg[f'{pre}_n']=g.cumcount()
seas=tg.groupby(['team','season']).agg(oy=('off_yds','sum'),op=('off_pts','sum'),
     dy=('def_yds','sum'),dp=('def_pts','sum')).reset_index()
seas['py_off']=seas.op/seas.oy*100; seas['py_def']=seas.dp/seas.dy*100
prior=seas.copy(); prior['season']=prior.season+1
tg=tg.merge(prior[['team','season','py_off','py_def']],on=['team','season'],how='left')
K=5.0
def blend(cp,cy,n,pri,lg=6.44):
    cur=(cp/cy*100) if cy and cy>0 else np.nan; pri=pri if not pd.isna(pri) else lg
    if pd.isna(cur): return pri
    w=n/(n+K); return w*cur+(1-w)*pri
tg['fin_off']=[blend(r.off_cp,r.off_cy,r.off_n,r.py_off) for r in tg.itertuples()]
tg['fin_def']=[blend(r.def_cp,r.def_cy,r.def_n,r.py_def) for r in tg.itertuples()]
fin=tg[['game_id','team','fin_off','fin_def']]
f=f.merge(fin.rename(columns={'team':'home','fin_off':'fin_off_h','fin_def':'fin_def_h'}),on=['game_id','home'],how='left')
f=f.merge(fin.rename(columns={'team':'away','fin_off':'fin_off_a','fin_def':'fin_def_a'}),on=['game_id','away'],how='left')
for c,lo,hi in [("proj_ypa_h",1,15),("proj_ypa_a",1,15),("proj_yrc_h",1,9),("proj_yrc_a",1,9)]:
    f[c]=f[c].clip(lo,hi)
f=f.dropna(subset=['total_pts']); f=f[f.fbs_both==True].copy()
f['neutral']=f.neutral.fillna(False).astype(int); f['mkt_spread']=f.mkt_spread.fillna(0)
for c in ['fin_off_h','fin_def_h','fin_off_a','fin_def_a']: f[c]=f[c].fillna(6.44)

X=f[FEATURES].values; y=f.total_pts.values
model=HistGradientBoostingRegressor(max_iter=400,learning_rate=0.03,max_depth=3,
    l2_regularization=1.0,min_samples_leaf=40,random_state=0).fit(X,y)
joblib.dump(model, f"{MODELS}/totals.joblib")

# --- spread model (home margin), de-anchored: drop mkt_spread so proj is independent ---
gm=pd.read_csv(f"{DATA}/games.csv")[["game_id","home_pts","away_pts"]]
f=f.merge(gm,on="game_id",how="left")
f["home_margin"]=pd.to_numeric(f.home_pts,errors="coerce")-pd.to_numeric(f.away_pts,errors="coerce")
fs=f.dropna(subset=["home_margin"])
SPREAD_FEATS=[c for c in FEATURES if c!="mkt_spread"]
sp=HistGradientBoostingRegressor(max_iter=400,learning_rate=0.03,max_depth=3,
    l2_regularization=1.0,min_samples_leaf=40,random_state=0).fit(fs[SPREAD_FEATS].values,fs.home_margin.values)
joblib.dump(sp, f"{MODELS}/spread.joblib")

json.dump({"features":FEATURES,"spread_features":SPREAD_FEATS,"n_train":len(f),
           "trained_through_season":int(f.season.max()),"K":K}, open(f"{MODELS}/meta.json","w"), indent=2)
print(f"trained on {len(f)} games (through {int(f.season.max())}); saved totals + spread models")
print("totals in-sample MAE:", round(np.mean(np.abs(model.predict(X)-y)),3))
print("spread in-sample MAE:", round(np.mean(np.abs(sp.predict(fs[SPREAD_FEATS].values)-fs.home_margin.values)),3))
