"""Build the full-season slate: every FBS-vs-FBS game, by week, with projected total & spread,
market total & spread (from live odds where posted), edge, kickoff (ET), and CLV opener tracking.
Writes out/slate.csv (all weeks) for the dashboard."""
import os, sys, json, warnings, numpy as np, pandas as pd, joblib
from datetime import datetime
from zoneinfo import ZoneInfo
warnings.filterwarnings("ignore")
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); sys.path.insert(0,HERE)
import ratings_engine as RE
import odds as ODDS
DATA=ROOT+"/data"; OUT=ROOT+"/out"; MODELS=ROOT+"/models"
ET=ZoneInfo("America/New_York")

def current_week(season):
    # current bettable week = earliest week that still has UPCOMING (unplayed) games
    g=pd.read_csv(f"{DATA}/games.csv"); g=g[(g.season==season)&(g.season_type=="regular")]
    up=g[g.completed!=True]
    if len(up): return int(up.week.min())
    return int(g.week.max()) if len(g) else 1

def ratings_week(season):
    # as-of week for RATINGS = include ALL games completed to date (so last night's results count).
    g=pd.read_csv(f"{DATA}/games.csv"); done=g[(g.season==season)&(g.completed==True)]
    return int(done.week.max())+1 if len(done) else 1

def _fmt_kick(iso):
    if not iso or pd.isna(iso): return (None,None,None)
    try:
        d=datetime.fromisoformat(str(iso).replace("Z","+00:00")).astimezone(ET)
        return (d.strftime("%a %m/%d"), d.strftime("%-I:%M %p"), d.isoformat())
    except Exception: return (None,None,None)

def build_slate(season=2026, fetch_live=True):
    meta=json.load(open(f"{MODELS}/meta.json")); FEATS=meta["features"]
    CALIB=float(meta.get("calibration",0.8))   # +0.8 removes small OOS low-bias (see RESULTS.md)
    model=joblib.load(f"{MODELS}/totals.joblib")
    wk=current_week(season)                       # display/default week (earliest upcoming)
    rwk=ratings_week(season)                       # ratings snapshot = all games completed to date
    ratings,lg=RE.compute_ratings(season, upto_week=rwk)

    sched=pd.read_csv(f"{DATA}/games.csv"); sched=sched[(sched.season==season)&(sched.season_type=="regular")].copy()
    sched=sched[(sched.home_div=="fbs")&(sched.away_div=="fbs")]

    # live odds -> dict by (home,away)
    OD={}; rem="n/a"
    if fetch_live:
        try:
            odf,rem=ODDS.fetch_odds_api()
            opener=ODDS.log_snapshot(odf); odf=odf.merge(opener,on=["home","away"],how="left")
            for r in odf.itertuples():
                OD[(r.home,r.away)]=dict(cur_total=getattr(r,"book_total_consensus",None),
                    open_total=getattr(r,"open_bovada",None) if pd.notna(getattr(r,"open_bovada",np.nan)) else getattr(r,"open_consensus",None),
                    cur_spread=getattr(r,"book_spread_consensus",None), n_books=getattr(r,"n_books",None))
        except Exception as e:
            print("odds fetch failed:",e)

    # DURABLE openers from CFBD (Bovada recorded opener) — survives reboots, re-pulled every refresh
    OPEN={}
    if fetch_live:
        for w in range(wk, wk+4):
            try:
                for r in ODDS.fetch_cfbd_lines(season, w).itertuples():
                    ob=getattr(r,"open_bovada",None)
                    if ob is not None and pd.notna(ob): OPEN[(r.home,r.away)]=float(ob)
            except Exception: pass

    rows=[]
    for g in sched.itertuples():
        feat=RE.project_matchup(g.home,g.away,ratings,lg,week=int(g.week),
            neutral=int(bool(g.neutral)) if not pd.isna(g.neutral) else 0,
            mkt_spread=float(OD.get((g.home,g.away),{}).get("cur_spread") or 0))
        if feat is None: continue
        X=np.array([[feat[c] for c in FEATS]]); model_total=float(model.predict(X)[0])+CALIB
        od=OD.get((g.home,g.away),{})
        cfbd_open=OPEN.get((g.home,g.away))
        mtot=od.get("cur_total")
        mopen=cfbd_open if (cfbd_open is not None and pd.notna(cfbd_open)) else od.get("open_total")  # durable CFBD opener first
        mspread=od.get("cur_spread")
        ref = mopen if (mopen is not None and pd.notna(mopen)) else mtot
        edge = round(model_total-ref,1) if (ref is not None and pd.notna(ref)) else None
        day,tm,ck=_fmt_kick(g.start_date)
        actual = int(g.home_pts+g.away_pts) if (g.completed==True and pd.notna(g.home_pts)) else None
        rows.append(dict(week=int(g.week),day=day,time=tm,kick=ck,home=g.home,away=g.away,
            neutral=int(bool(g.neutral)) if not pd.isna(g.neutral) else 0,
            proj_total=round(model_total,1), mkt_total=round(mtot,1) if (mtot is not None and pd.notna(mtot)) else None,
            open_total=round(mopen,1) if (mopen is not None and pd.notna(mopen)) else None,
            edge=edge, side=("OVER" if (edge or 0)>0 else "UNDER") if edge is not None else None,
            mkt_spread=round(mspread,1) if (mspread is not None and pd.notna(mspread)) else None,
            actual_total=actual,
            n_books=od.get("n_books"), w_current=round(np.mean([ratings.get(g.home,{}).get("w",0),ratings.get(g.away,{}).get("w",0)]),2)))
    slate=pd.DataFrame(rows)
    if len(slate):
        slate["edge"]=pd.to_numeric(slate.edge,errors="coerce")
        slate["abs_edge"]=slate.edge.abs()
        slate["signal"]=np.where(slate.abs_edge>=5,"STRONG",np.where(slate.abs_edge>=3,"LEAN","-"))
        slate.loc[slate.edge.isna(),"signal"]="-"
        slate=slate.sort_values(["week","kick","abs_edge"],ascending=[True,True,False])
    slate.to_csv(f"{OUT}/slate.csv",index=False)
    json.dump(dict(season=season,current_week=wk,ratings_week=rwk,requests_remaining=str(rem),
        generated=datetime.now(ET).strftime("%Y-%m-%d %-I:%M %p ET"),n=len(slate)),open(f"{OUT}/slate_meta.json","w"))
    return slate

if __name__=="__main__":
    s=build_slate(fetch_live=("--nolive" not in sys.argv))
    m=json.load(open(f"{OUT}/slate_meta.json")); print(m)
    cur=s[s.week==m["current_week"]]
    print(f"\n=== Week {m['current_week']} ({len(cur)} games) ===")
    print(cur[["day","time","away","home","open_total","mkt_total","proj_total","edge","side","mkt_spread","signal"]].head(30).to_string(index=False))
