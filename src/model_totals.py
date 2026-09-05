"""Train + walk-forward backtest of totals models.

Models compared:
  MARKET   : predict = closing market total (benchmark)
  NN       : faithful rebuild of the spreadsheet's neural net
             (tanh MLP; inputs = market spread/total + projected box drivers + tempo)
  GBM      : modern gradient-boosted trees on a richer feature set (incl. market total)
  GBM_nomkt: GBM WITHOUT the market total (pure independent projection -> shows raw edge)

Walk-forward: to predict season S, train only on seasons < S.
Backtest bets FBS-vs-FBS games with a market total; grades O/U vs the closing line,
ROI at standard -110 juice.
"""
import os, warnings
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.neural_network import MLPRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "out")

df = pd.read_csv(os.path.join(DATA, "features.csv"))

# clip degenerate early-season projected efficiencies to sane bounds
for c, lo, hi in [("proj_ypa_h",1,15),("proj_ypa_a",1,15),("proj_yrc_h",1,9),("proj_yrc_a",1,9)]:
    df[c] = df[c].clip(lo, hi)
# recompute projected yards from clipped efficiency for consistency
df["proj_py_h"] = (df.proj_py_h.clip(-50,900)).clip(lower=20)
df["proj_py_a"] = (df.proj_py_a.clip(-50,900)).clip(lower=20)

df = df.dropna(subset=["mkt_total", "total_pts"]).copy()
df = df[df.fbs_both == True].copy()
df["neutral"] = df["neutral"].fillna(False).astype(int)

NN_FEATS = ["mkt_spread","mkt_total","proj_py_h","proj_ypa_h","proj_ry_h","proj_yrc_h",
            "proj_py_a","proj_ypa_a","proj_ry_a","proj_yrc_a","tempo_h","tempo_a"]
GBM_FEATS = NN_FEATS + ["proj_total_yards","exp_plays","off_ypa_h","def_ypa_h","off_ypc_h",
                        "def_ypc_h","off_ypa_a","def_ypa_a","off_ypc_a","def_ypc_a",
                        "prate_h","prate_a","neutral","week"]
GBM_NOMKT = [c for c in GBM_FEATS if c not in ("mkt_total",)]
TARGET = "mkt_spread"  # placeholder to ensure column exists
df["mkt_spread"] = df["mkt_spread"].fillna(0)

TEST_SEASONS = [2018, 2019, 2020, 2021, 2022, 2023, 2024]

def fit_nn(Xtr, ytr, Xte, seeds=(0,1,2,3,5)):
    """Faithful tanh MLP, averaged over seeds for stability."""
    sc = StandardScaler().fit(Xtr)
    Xtr2, Xte2 = sc.transform(Xtr), sc.transform(Xte)
    preds = []
    for s in seeds:
        m = MLPRegressor(hidden_layer_sizes=(6,), activation="tanh", solver="lbfgs",
                         alpha=1.0, max_iter=2000, random_state=s)
        m.fit(Xtr2, ytr)
        preds.append(m.predict(Xte2))
    return np.mean(preds, axis=0)

def fit_gbm(Xtr, ytr, Xte):
    m = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.03, max_depth=3,
                                      l2_regularization=1.0, min_samples_leaf=40,
                                      random_state=0)
    m.fit(Xtr, ytr)
    return m.predict(Xte)

rows = []
for S in TEST_SEASONS:
    tr = df[df.season < S]
    te = df[df.season == S]
    if len(tr) < 500 or len(te) == 0:
        continue
    ytr = tr.total_pts.values
    out = te[["game_id","season","week","home","away","total_pts","mkt_total"]].copy()
    out["pred_market"] = te.mkt_total.values
    out["pred_nn"]  = fit_nn(tr[NN_FEATS].values, ytr, te[NN_FEATS].values)
    out["pred_gbm"] = fit_gbm(tr[GBM_FEATS].values, ytr, te[GBM_FEATS].values)
    out["pred_gbm_nomkt"] = fit_gbm(tr[GBM_NOMKT].values, ytr, te[GBM_NOMKT].values)
    rows.append(out)
    print(f"season {S}: train {len(tr)} test {len(te)}")

res = pd.concat(rows, ignore_index=True)
res.to_csv(os.path.join(OUT, "backtest_preds.csv"), index=False)

# ---------------- evaluation ----------------
def mae(a, b): return float(np.mean(np.abs(a - b)))

print("\n================ ACCURACY (vs actual total) ================")
print(f"{'model':<14}{'MAE':>8}{'RMSE':>9}")
for col in ["pred_market","pred_nn","pred_gbm","pred_gbm_nomkt"]:
    e = res[col] - res.total_pts
    print(f"{col:<14}{mae(res[col],res.total_pts):>8.2f}{np.sqrt((e**2).mean()):>9.2f}")

def backtest(pred_col, thresholds=(0,1,2,3,4,5,6)):
    print(f"\n================ BETTING BACKTEST: {pred_col} ================")
    print(f"{'edge>=':>7}{'bets':>7}{'win%':>8}{'push':>6}{'ROI%':>8}{'units':>8}")
    r = res.copy()
    r["edge"] = r[pred_col] - r.mkt_total
    for thr in thresholds:
        b = r[r.edge.abs() >= thr].copy()
        if len(b) == 0:
            continue
        b["side"] = np.where(b.edge > 0, "over", "under")
        act_minus_line = b.total_pts - b.mkt_total
        win = ((b.side=="over")&(act_minus_line>0)) | ((b.side=="under")&(act_minus_line<0))
        push = act_minus_line == 0
        n = len(b); npush = int(push.sum()); ndec = n - npush
        nwin = int(win.sum())
        winpct = nwin/ndec if ndec else 0
        units = nwin*0.9091 - (ndec-nwin)*1.0
        roi = units/ndec*100 if ndec else 0
        print(f"{thr:>7}{n:>7}{winpct*100:>8.1f}{npush:>6}{roi:>8.2f}{units:>8.1f}")

for col in ["pred_nn","pred_gbm","pred_gbm_nomkt"]:
    backtest(col)

# break-even at -110 is 52.38%
print("\n(break-even win rate at -110 juice = 52.38%)")
print("\nsaved out/backtest_preds.csv")
