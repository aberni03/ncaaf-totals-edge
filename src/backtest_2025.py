"""Backtest the core SOS-adjusted YPP model specifically on the 2025 season.
Train on 2015-2024, predict 2025. Focus on higher model-vs-market discrepancies."""
import os, warnings, numpy as np, pandas as pd
from scipy import stats
from sklearn.preprocessing import StandardScaler
from sklearn.neural_network import MLPRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
warnings.filterwarnings("ignore")
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); DATA=ROOT+"/data"; OUT=ROOT+"/out"

df=pd.read_csv(DATA+"/features.csv")
for c,lo,hi in [("proj_ypa_h",1,15),("proj_ypa_a",1,15),("proj_yrc_h",1,9),("proj_yrc_a",1,9)]:
    df[c]=df[c].clip(lo,hi)
df=df.dropna(subset=["mkt_total","total_pts"]).copy()
df=df[df.fbs_both==True].copy()
df["neutral"]=df["neutral"].fillna(False).astype(int)
df["mkt_spread"]=df["mkt_spread"].fillna(0)

NN=["mkt_spread","mkt_total","proj_py_h","proj_ypa_h","proj_ry_h","proj_yrc_h",
    "proj_py_a","proj_ypa_a","proj_ry_a","proj_yrc_a","tempo_h","tempo_a"]
GBM=NN+["proj_total_yards","exp_plays","off_ypa_h","def_ypa_h","off_ypc_h","def_ypc_h",
        "off_ypa_a","def_ypa_a","off_ypc_a","def_ypc_a","prate_h","prate_a","neutral","week"]
NOMKT=[c for c in GBM if c!="mkt_total"]

tr=df[df.season<2025]; te=df[df.season==2025].copy()
print(f"train {len(tr)}  test(2025) {len(te)}")
ytr=tr.total_pts.values

# faithful NN (market-anchored)
sc=StandardScaler().fit(tr[NN]);
pr=[]
for s in (0,1,2,3,5):
    m=MLPRegressor(hidden_layer_sizes=(6,),activation="tanh",solver="lbfgs",alpha=1.0,max_iter=2000,random_state=s)
    m.fit(sc.transform(tr[NN]),ytr); pr.append(m.predict(sc.transform(te[NN])))
te["pred_nn"]=np.mean(pr,axis=0)
# GBM with market
g=HistGradientBoostingRegressor(max_iter=400,learning_rate=0.03,max_depth=3,l2_regularization=1.0,min_samples_leaf=40,random_state=0)
g.fit(tr[GBM],ytr); te["pred_gbm"]=g.predict(te[GBM])
# line-blind projection (pure SOS-YPP model)
g2=HistGradientBoostingRegressor(max_iter=400,learning_rate=0.03,max_depth=3,l2_regularization=1.0,min_samples_leaf=40,random_state=0)
g2.fit(tr[NOMKT],ytr); te["pred_nomkt"]=g2.predict(te[NOMKT])
te["pred_market"]=te.mkt_total
te.to_csv(OUT+"/preds_2025.csv",index=False)

print("\n=== 2025 accuracy (MAE vs actual total) ===")
for c in ["pred_market","pred_nn","pred_gbm","pred_nomkt"]:
    print(f"  {c:<12}{np.mean(np.abs(te[c]-te.total_pts)):.2f}")

def table(pred):
    print(f"\n=== 2025 betting: {pred}  (break-even 52.38%) ===")
    print(f"{'edge>=':>7}{'bets':>6}{'win%':>7}{'ROI%':>7}{'p':>7}")
    d=te.copy(); d["edge"]=d[pred]-d.mkt_total
    for thr in [0,2,3,4,6,8,10]:
        b=d[d.edge.abs()>=thr].copy(); b["side"]=np.where(b.edge>0,"over","under")
        amL=b.total_pts-b.mkt_total
        win=((b.side=="over")&(amL>0))|((b.side=="under")&(amL<0)); push=amL==0
        ndec=len(b)-int(push.sum()); nwin=int(win.sum())
        if ndec==0: continue
        wp=nwin/ndec*100; roi=(nwin*.9091-(ndec-nwin))/ndec*100
        p=stats.binomtest(nwin,ndec,0.5238,alternative="greater").pvalue
        print(f"{thr:>7}{len(b):>6}{wp:>7.1f}{roi:>7.1f}{p:>7.3f}")

for c in ["pred_nn","pred_gbm","pred_nomkt"]:
    table(c)
print("\nsaved out/preds_2025.csv")
