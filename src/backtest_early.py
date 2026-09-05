"""Backtest the DE-ANCHORED (line-blind) totals model with preseason priors,
focused on early weeks and Week 1. Train on seasons < S, predict S."""
import os, warnings, numpy as np, pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingRegressor
warnings.filterwarnings("ignore")
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); DATA=ROOT+"/data"; OUT=ROOT+"/out"

df=pd.read_csv(DATA+"/features_v2.csv")
for c,lo,hi in [("proj_ypa_h",1,15),("proj_ypa_a",1,15),("proj_yrc_h",1,9),("proj_yrc_a",1,9)]:
    df[c]=df[c].clip(lo,hi)
df=df.dropna(subset=["mkt_total","total_pts"]).copy()
df=df[df.fbs_both==True].copy()
df["neutral"]=df["neutral"].fillna(False).astype(int)
df["mkt_spread"]=df["mkt_spread"].fillna(0)

FEATS=["mkt_spread","proj_py_h","proj_ypa_h","proj_ry_h","proj_yrc_h","proj_py_a","proj_ypa_a",
       "proj_ry_a","proj_yrc_a","tempo_h","tempo_a","proj_total_yards","exp_plays",
       "off_ypa_h","def_ypa_h","off_ypc_h","def_ypc_h","off_ypa_a","def_ypa_a","off_ypc_a","def_ypc_a",
       "prate_h","prate_a","neutral","week"]   # NO mkt_total -> de-anchored

def fit(Xtr,ytr,Xte):
    m=HistGradientBoostingRegressor(max_iter=400,learning_rate=0.03,max_depth=3,
        l2_regularization=1.0,min_samples_leaf=40,random_state=0)
    m.fit(Xtr,ytr); return m.predict(Xte)

rows=[]
for S in range(2019,2026):
    tr=df[df.season<S]; te=df[df.season==S]
    if len(tr)<500 or len(te)==0: continue
    o=te[["game_id","season","week","home","away","total_pts","mkt_total"]].copy()
    o["pred"]=fit(tr[FEATS].values,tr.total_pts.values,te[FEATS].values)
    rows.append(o)
res=pd.concat(rows,ignore_index=True)
res["ae_model"]=(res.pred-res.total_pts).abs(); res["ae_mkt"]=(res.mkt_total-res.total_pts).abs()
res.to_csv(OUT+"/backtest_early.csv",index=False)

def wb(w): return "wk1" if w==1 else ("wk2" if w==2 else ("wk3" if w==3 else ("wk4-6" if w<=6 else "wk7+")))
res["wb"]=res.week.map(wb)

print("=== accuracy by week (de-anchored model w/ preseason priors, 2019-2025) ===")
print(f"{'week':<8}{'games':>7}{'model MAE':>11}{'market MAE':>12}{'gap':>7}")
for k in ["wk1","wk2","wk3","wk4-6","wk7+"]:
    b=res[res.wb==k]
    print(f"{k:<8}{len(b):>7}{b.ae_model.mean():>11.2f}{b.ae_mkt.mean():>12.2f}{b.ae_model.mean()-b.ae_mkt.mean():>+7.2f}")

def bet(d,thr):
    d=d.copy(); d["edge"]=d.pred-d.mkt_total
    b=d[d.edge.abs()>=thr].copy(); b["side"]=np.where(b.edge>0,"over","under")
    amL=b.total_pts-b.mkt_total
    win=((b.side=="over")&(amL>0))|((b.side=="under")&(amL<0)); push=amL==0
    ndec=len(b)-int(push.sum()); nwin=int(win.sum())
    if ndec==0: return None
    wp=nwin/ndec*100; roi=(nwin*.9091-(ndec-nwin))/ndec*100
    p=stats.binomtest(nwin,ndec,0.5238,alternative="greater").pvalue
    return len(b),wp,roi,p

print("\n=== EARLY-WEEK betting (wk1-3 combined), by disagreement threshold ===")
early=res[res.week<=3]
print(f"{'edge>=':>7}{'bets':>6}{'win%':>7}{'ROI%':>7}{'p':>7}")
for thr in [0,2,3,4,6]:
    r=bet(early,thr)
    if r: print(f"{thr:>7}{r[0]:>6}{r[1]:>7.1f}{r[2]:>7.1f}{r[3]:>7.3f}")

print("\n=== WEEK 1 ONLY, all test seasons (2019-2025) ===")
w1=res[res.week==1]
print(f"{'edge>=':>7}{'bets':>6}{'win%':>7}{'ROI%':>7}{'p':>7}")
for thr in [0,2,3,4]:
    r=bet(w1,thr)
    if r: print(f"{thr:>7}{r[0]:>6}{r[1]:>7.1f}{r[2]:>7.1f}{r[3]:>7.3f}")

print("\n=== WEEK 1 by season (edge>=0, all games) ===")
for S in sorted(w1.season.unique()):
    b=w1[w1.season==S].copy(); b["edge"]=b.pred-b.mkt_total; b["side"]=np.where(b.edge>0,"over","under")
    amL=b.total_pts-b.mkt_total; win=((b.side=="over")&(amL>0))|((b.side=="under")&(amL<0)); push=amL==0
    ndec=len(b)-int(push.sum()); nwin=int(win.sum()); wp=nwin/ndec*100 if ndec else 0
    print(f"  {int(S)}: {nwin}/{ndec} = {wp:.1f}%   model MAE {b.ae_model.mean():.2f} vs mkt {b.ae_mkt.mean():.2f}")
print("\nsaved out/backtest_early.csv")
