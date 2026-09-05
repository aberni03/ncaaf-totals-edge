"""Build out/track_record.csv:
 - Historical 2020-2025: leak-free walk-forward (backtest_early.csv), graded vs opener.
 - 2026 YTD: completed games projected leak-free (ratings as-of each week) + graded vs opener.
Both use the same model + calibration and edge>=3 bet rule."""
import os, sys, json, numpy as np, pandas as pd, joblib
from datetime import datetime
from zoneinfo import ZoneInfo
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
DATA=ROOT+"/data"; OUT=ROOT+"/out"; MODELS=ROOT+"/models"; sys.path.insert(0,HERE)
ET=ZoneInfo("America/New_York")
meta=json.load(open(f"{MODELS}/meta.json")); CALIB=float(meta.get("calibration",0.8)); FEATS=meta["features"]
COLS=["season","week","date","away","home","opener","close","proj","edge","rec","tier","result",
      "clv","clv_pts","margin","proj_err","vegas_err","proj_vs_vegas","actual"]

def kick(iso):
    try: return datetime.fromisoformat(str(iso).replace("Z","+00:00")).astimezone(ET).strftime("%m/%d/%y")
    except: return None
def grade(df):
    df["abs_edge"]=df.edge.abs()
    df["rec"]=np.where(df.abs_edge>=3, np.where(df.edge>0,"OVER","UNDER"), "")
    df["tier"]=np.where(df.abs_edge>=5,"STRONG",np.where(df.abs_edge>=3,"LEAN",""))
    am=df.actual-df.opener
    df["result"]=np.where(df.rec=="","",np.where(am==0,"PUSH",
        np.where(((df.rec=="OVER")&(am>0))|((df.rec=="UNDER")&(am<0)),"WIN","LOSS")))
    mv=df.close-df.opener
    df["clv"]=np.where(df.rec=="","",np.where(np.sign(mv)==np.sign(df.edge),"+","-"))
    # cover margin: signed points the actual total beat the bet by (+ won by, - lost by)
    m=np.where(df.rec=="OVER", df.actual-df.opener, df.opener-df.actual)
    df["margin"]=pd.to_numeric(np.where(df.rec=="", np.nan, m)).round(1)
    # signed CLV in points: how much better our opener number was vs the close (+ = we beat the close)
    cp=np.where(df.rec=="OVER", df.close-df.opener, df.opener-df.close)
    df["clv_pts"]=pd.to_numeric(np.where(df.rec=="", np.nan, cp)).round(1)
    # residuals for model-building: how actual compared to projection and to Vegas close
    df["proj_err"]=(df.actual-df.proj).round(1)          # actual - model projection
    df["vegas_err"]=(df.actual-df.close).round(1)        # actual - closing total
    df["proj_vs_vegas"]=(df.proj-df.close).round(1)      # model disagreement w/ close (signed)
    return df

# ---------------- historical 2020-2025 ----------------
bt=pd.read_csv(f"{OUT}/backtest_early.csv")
fv=pd.read_csv(f"{DATA}/features_v2.csv")[["game_id","mkt_total_open"]]
gm=pd.read_csv(f"{DATA}/games.csv")[["game_id","start_date"]]
h=bt.merge(fv,on="game_id",how="left").merge(gm,on="game_id",how="left")
h=h[h.season!=2019]
h["proj"]=(h.pred+CALIB).round(1)
h["opener"]=h.mkt_total_open.where(h.mkt_total_open.notna(),h.mkt_total)
h["close"]=h.mkt_total; h["actual"]=h.total_pts
h["edge"]=(h.proj-h.opener).round(1); h["date"]=h.start_date.map(kick)
hist=grade(h)[COLS]

# ---------------- 2026 YTD (leak-free live projection) ----------------
import ratings_engine as RE
model=joblib.load(f"{MODELS}/totals.joblib")
g=pd.read_csv(f"{DATA}/games.csv"); g=g[(g.season==2026)&(g.completed==True)&(g.home_div=="fbs")&(g.away_div=="fbs")].copy()
g["actual"]=pd.to_numeric(g.home_pts,errors="coerce")+pd.to_numeric(g.away_pts,errors="coerce")
L=pd.read_csv(f"{DATA}/lines.csv"); L=L[L.season==2026]
def agg(gid):
    d=L[L.game_id==gid]
    def med(col,prov=None):
        s=d[d.provider==prov][col] if prov else d[col]
        s=s.dropna(); return float(s.median()) if len(s) else np.nan
    opener=med("over_under_open","Bovada")
    if np.isnan(opener): opener=med("over_under_open")
    close=med("over_under","consensus")
    if np.isnan(close): close=med("over_under")
    sp=med("spread","consensus")
    if np.isnan(sp): sp=med("spread")
    return opener,close,sp
rows=[]
for wk in sorted(g.week.unique()):
    R,lg=RE.compute_ratings(2026, upto_week=int(wk))
    for r in g[g.week==wk].itertuples():
        feat=RE.project_matchup(r.home,r.away,R,lg,week=int(wk),
            neutral=int(bool(r.neutral)) if not pd.isna(r.neutral) else 0, mkt_spread=0.0)
        if feat is None or pd.isna(r.actual): continue
        opener,close,sp=agg(r.game_id)
        if pd.notna(sp): feat["mkt_spread"]=sp
        proj=round(float(model.predict(np.array([[feat[c] for c in FEATS]]))[0])+CALIB,1)
        if pd.isna(opener) and pd.isna(close): continue
        op = opener if pd.notna(opener) else close
        rows.append(dict(season=2026,week=int(wk),date=kick(r.start_date),away=r.away,home=r.home,
            opener=round(op,1), close=round(close,1) if pd.notna(close) else round(op,1),
            proj=proj, edge=round(proj-op,1), actual=int(r.actual)))
ytd=grade(pd.DataFrame(rows))[COLS] if rows else pd.DataFrame(columns=COLS)

out=pd.concat([hist,ytd],ignore_index=True).sort_values(["season","week"])
out.to_csv(f"{OUT}/track_record.csv",index=False)

def summ(name,d):
    b=d[d.rec!=""]; dec=b[b.result!="PUSH"]; w=int((dec.result=="WIN").sum()); l=int((dec.result=="LOSS").sum()); p=int((b.result=="PUSH").sum())
    roi=(w*.9091-l)/(w+l)*100 if (w+l) else 0
    print(f"{name}: {len(d)} games, bets={len(b)} ({w}-{l}-{p}) win%={w/(w+l)*100 if (w+l) else 0:.1f} ROI={roi:+.1f}%")
summ("ALL", out); summ("2026 YTD", ytd)
if len(ytd): print(ytd[ytd.rec!=""][["date","away","home","opener","proj","edge","rec","result"]].to_string(index=False))
