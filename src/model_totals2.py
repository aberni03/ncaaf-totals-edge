"""Re-run totals backtest WITH added factors, and test each factor as a standalone angle."""
import os, warnings, numpy as np, pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingRegressor
warnings.filterwarnings("ignore")
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA=os.path.join(ROOT,"data"); OUT=os.path.join(ROOT,"out")

df=pd.read_csv(DATA+"/features2.csv")
for c,lo,hi in [("proj_ypa_h",1,15),("proj_ypa_a",1,15),("proj_yrc_h",1,9),("proj_yrc_a",1,9)]:
    df[c]=df[c].clip(lo,hi)
df=df.dropna(subset=["mkt_total","total_pts"]).copy()
df=df[df.fbs_both==True].copy()
df["neutral"]=df["neutral"].fillna(False).astype(int)
df["mkt_spread"]=df["mkt_spread"].fillna(0)

BASE=["mkt_spread","proj_py_h","proj_ypa_h","proj_ry_h","proj_yrc_h","proj_py_a","proj_ypa_a",
      "proj_ry_a","proj_yrc_a","tempo_h","tempo_a","proj_total_yards","exp_plays",
      "off_ypa_h","def_ypa_h","off_ypc_h","def_ypc_h","off_ypa_a","def_ypa_a","off_ypc_a","def_ypc_a",
      "prate_h","prate_a","neutral","week"]
FACTORS=["dome","elevation","grass","cold_late","rest_h","rest_a","rest_diff","travel_a",
         "ppa_off_h","ppa_def_h","ppa_off_a","ppa_def_a","ppa_env"]
NOMKT=BASE+FACTORS                 # line-blind, WITH factors
WITHMKT=["mkt_total"]+NOMKT        # WITH market + factors

def fit_gbm(Xtr,ytr,Xte):
    m=HistGradientBoostingRegressor(max_iter=400,learning_rate=0.03,max_depth=3,
        l2_regularization=1.0,min_samples_leaf=40,random_state=0)
    m.fit(Xtr,ytr); return m.predict(Xte)

rows=[]
for S in [2018,2019,2020,2021,2022,2023,2024]:
    tr=df[df.season<S]; te=df[df.season==S]
    if len(tr)<500 or len(te)==0: continue
    ytr=tr.total_pts.values
    o=te[["game_id","season","week","home","away","total_pts","mkt_total"]].copy()
    o["pred_fac_nomkt"]=fit_gbm(tr[NOMKT].values,ytr,te[NOMKT].values)
    o["pred_fac_mkt"]=fit_gbm(tr[WITHMKT].values,ytr,te[WITHMKT].values)
    rows.append(o)
res=pd.concat(rows,ignore_index=True)
res.to_csv(OUT+"/backtest_preds_factors.csv",index=False)

def bt(d,pred,thr,hi=None,recent=False):
    d=d.copy()
    if recent: d=d[d.season>=2021]
    d["edge"]=d[pred]-d.mkt_total; m=d.edge.abs()>=thr
    if hi is not None: m&=d.edge.abs()<hi
    b=d[m].copy(); b["side"]=np.where(b.edge>0,"over","under")
    amL=b.total_pts-b.mkt_total
    win=((b.side=="over")&(amL>0))|((b.side=="under")&(amL<0)); push=amL==0
    ndec=len(b)-int(push.sum()); nwin=int(win.sum())
    wp=nwin/ndec*100 if ndec else 0; roi=(nwin*.9091-(ndec-nwin))/ndec*100 if ndec else 0
    p=stats.binomtest(nwin,ndec,0.5238,alternative="greater").pvalue if ndec else 1
    return len(b),wp,roi,p

# accuracy
print("=== MAE vs actual ===")
for c in ["mkt_total","pred_fac_mkt","pred_fac_nomkt"]:
    print(f"  {c:<16}{np.mean(np.abs(res[c]-res.total_pts)):.2f}")

print("\n=== FACTOR MODEL (line-blind) large-disagreement, ALL seasons ===")
print(f"{'edge>=':>7}{'bets':>6}{'win%':>7}{'ROI%':>7}{'p':>7}")
for thr in [4,6,8,10,12]:
    n,wp,roi,p=bt(res,"pred_fac_nomkt",thr); print(f"{thr:>7}{n:>6}{wp:>7.1f}{roi:>7.1f}{p:>7.3f}")
print("\n=== same, RECENT (2021-24) ===")
for thr in [4,6,8,10]:
    n,wp,roi,p=bt(res,"pred_fac_nomkt",thr,recent=True); print(f"{thr:>7}{n:>6}{wp:>7.1f}{roi:>7.1f}{p:>7.3f}")

# ---- standalone factor angles: does the factor alone beat the closing total? ----
print("\n================ STANDALONE FACTOR ANGLES (O/U vs closing line) ================")
d=df[df.season>=2018].copy()
d["res"]=d.total_pts-d.mkt_total   # >0 => over cashed
def angle(name,mask,side):
    b=d[eval(mask)]; r=b.res
    if side=="over": win=(r>0).sum();
    else: win=(r<0).sum()
    ndec=(r!=0).sum(); wp=win/ndec*100 if ndec else 0
    roi=(win*.9091-(ndec-win))/ndec*100 if ndec else 0
    p=stats.binomtest(int(win),int(ndec),0.5238,alternative="greater").pvalue if ndec else 1
    print(f"  {name:<34}{side:>6} bets={int(ndec):>5} win%={wp:>5.1f} ROI%={roi:>+6.1f} p={p:.3f}")
angle("dome games","d.dome==1",'over')
angle("cold late-season northern outdoor",'d.cold_late==1','under')
angle("high altitude (elev>=1200m)",'d.elevation>=1200','over')
angle("both teams high PPA (env top 20%)",'d.ppa_env>=d.ppa_env.quantile(.8)','over')
angle("both low PPA (env bottom 20%)",'d.ppa_env<=d.ppa_env.quantile(.2)','under')
angle("short rest away (rest_a<=5)",'d.rest_a<=5','under')
angle("long travel away (>1500mi)",'d.travel_a>1500','under')
angle("fast pace (exp_plays top 20%)",'d.exp_plays>=d.exp_plays.quantile(.8)','over')
angle("slow pace (exp_plays bottom 20%)",'d.exp_plays<=d.exp_plays.quantile(.2)','under')
print("\n(break-even = 52.38%;  p = one-sided vs break-even)")
print("saved out/backtest_preds_factors.csv")
