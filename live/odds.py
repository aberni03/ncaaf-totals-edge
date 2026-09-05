"""Odds ingestion + team-name resolution + opener snapshot logging.
Primary: The Odds API (real-time, incl. Bovada). Resolves book team names -> CFBD names.
Logs every poll to out/odds_snapshots.csv so we can track opener (first-seen) vs current (CLV)."""
import os, re, json, unicodedata, datetime as dt
import requests, pandas as pd
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); DATA=ROOT+"/data"; OUT=ROOT+"/out"
ODDS_KEY=open(f"{ROOT}/.odds_key").read().strip()
CFBD_KEY=open(f"{ROOT}/.cfbd_key").read().strip()
TEAMS=pd.read_csv(f"{DATA}/teams_fbs.csv")

def _norm(s):
    s=unicodedata.normalize("NFKD",str(s)).encode("ascii","ignore").decode()
    s=s.lower().replace("&","and"); s=re.sub(r"[^a-z0-9 ]","",s); return re.sub(r"\s+"," ",s).strip()

# manual aliases (book name fragment -> CFBD school)
ALIAS={"miami florida":"Miami","miami hurricanes":"Miami","miami ohio":"Miami (OH)",
    "miami redhawks":"Miami (OH)","southern miss":"Southern Mississippi","hawaii":"Hawai'i",
    "san jose state":"San José State","louisiana lafayette":"Louisiana","ul monroe":"Louisiana Monroe",
    "louisiana monroe":"Louisiana Monroe","texas san antonio":"UTSA","texas el paso":"UTEP",
    "massachusetts":"UMass","connecticut":"UConn","nc state":"NC State","app state":"App State",
    "appalachian state":"App State","florida international":"Florida International",
    "middle tennessee":"Middle Tennessee","san diego state":"San Diego State"}
_CFBD_NORM={_norm(t):t for t in TEAMS.team}

def resolve(book_name):
    n=_norm(book_name)
    if n in ALIAS: return ALIAS[n]
    if n in _CFBD_NORM: return _CFBD_NORM[n]
    # drop trailing mascot words progressively
    words=n.split()
    for k in range(len(words)-1,0,-1):
        cand=" ".join(words[:k])
        if cand in ALIAS: return ALIAS[cand]
        if cand in _CFBD_NORM: return _CFBD_NORM[cand]
    # last resort: unique startswith match
    hits=[full for norm,full in _CFBD_NORM.items() if n.startswith(norm) or norm.startswith(n)]
    return hits[0] if len(hits)==1 else None

def _median(xs):
    xs=sorted(x for x in xs if x is not None)
    if not xs: return None
    m=len(xs)//2; return xs[m] if len(xs)%2 else (xs[m-1]+xs[m])/2

def fetch_odds_api(markets="totals,spreads"):
    r=requests.get("https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds",
        params={"apiKey":ODDS_KEY,"regions":"us","markets":markets,"oddsFormat":"american"},timeout=30)
    r.raise_for_status()
    rem=r.headers.get("x-requests-remaining")
    rows=[]
    for g in r.json():
        home=resolve(g["home_team"]); away=resolve(g["away_team"])
        if not home or not away: continue
        totals={}; spreads={}
        for bk in g.get("bookmakers",[]):
            for mk in bk.get("markets",[]):
                if mk["key"]=="totals":
                    pt=next((o["point"] for o in mk["outcomes"] if o["name"]=="Over"),None)
                    if pt is not None: totals[bk["key"]]=pt
                elif mk["key"]=="spreads":
                    pt=next((o["point"] for o in mk["outcomes"] if resolve(o["name"])==home),None)
                    if pt is not None: spreads[bk["key"]]=pt
        rows.append(dict(home=home,away=away,commence=g["commence_time"],
            book_total_bovada=totals.get("bovada"),
            book_total_consensus=_median(list(totals.values())),
            book_spread_consensus=_median(list(spreads.values())),
            n_books=len(totals)))
    df=pd.DataFrame(rows)
    return df, rem

def log_snapshot(df):
    """Append current totals with timestamp; return opener (first-seen) per game."""
    ts=dt.datetime.utcnow().isoformat()
    path=f"{OUT}/odds_snapshots.csv"
    snap=df.assign(ts=ts)[["ts","home","away","commence","book_total_bovada","book_total_consensus"]]
    if os.path.exists(path):
        old=pd.read_csv(path); allsnap=pd.concat([old,snap],ignore_index=True)
    else:
        allsnap=snap
    allsnap.to_csv(path,index=False)
    # opener = earliest snapshot per (home,away); current = latest
    allsnap["ts"]=pd.to_datetime(allsnap.ts)
    opener=allsnap.sort_values("ts").groupby(["home","away"]).first().reset_index()
    return opener[["home","away","book_total_bovada","book_total_consensus"]].rename(
        columns={"book_total_bovada":"open_bovada","book_total_consensus":"open_consensus"})

def fetch_ap_top25(season):
    """Latest AP Top 25 as {school: rank}. Auto-current: takes the most recent week's poll."""
    try:
        r=requests.get("https://api.collegefootballdata.com/rankings",params={"year":season},
            headers={"Authorization":f"Bearer {CFBD_KEY}"},timeout=30)
        d=r.json(); aps=[(x["week"],p) for x in d for p in x.get("polls",[]) if p.get("poll")=="AP Top 25"]
        if not aps: return {}
        lw=max(w for w,_ in aps); poll=next(p for w,p in aps if w==lw)
        return {t["school"]:t["rank"] for t in poll.get("ranks",[])}
    except Exception:
        return {}

def fetch_media(season):
    """{(home,away): tv_outlet} for the season (prefers TV over streaming)."""
    try:
        r=requests.get("https://api.collegefootballdata.com/games/media",
            params={"year":season,"seasonType":"regular"},headers={"Authorization":f"Bearer {CFBD_KEY}"},timeout=60)
        out={}
        for g in r.json():
            k=(g.get("homeTeam"),g.get("awayTeam")); ou=g.get("outlet")
            if not ou: continue
            if k not in out or g.get("mediaType")=="tv": out[k]=ou
        return out
    except Exception:
        return {}

def fetch_cfbd_lines(season, week):
    """Fallback / historical: CFBD lines incl. Bovada open."""
    r=requests.get("https://api.collegefootballdata.com/lines",
        params={"year":season,"week":week,"seasonType":"regular"},
        headers={"Authorization":f"Bearer {CFBD_KEY}"},timeout=60)
    rows=[]
    for g in r.json():
        bov=next((l for l in g.get("lines",[]) if l["provider"]=="Bovada"),None)
        cons=next((l for l in g.get("lines",[]) if l["provider"]=="consensus"),None)
        ou=[l.get("overUnder") for l in g.get("lines",[]) if l.get("overUnder")]
        rows.append(dict(home=g["homeTeam"],away=g["awayTeam"],
            open_bovada=(bov or {}).get("overUnderOpen"),
            close_consensus=(cons or {}).get("overUnder") or _median(ou),
            book_total_consensus=_median(ou)))
    return pd.DataFrame(rows)

if __name__=="__main__":
    df,rem=fetch_odds_api()
    print(f"fetched {len(df)} games (resolved); requests remaining: {rem}")
    print(df.head(8).to_string())
    # report unresolved
    r=requests.get("https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds",
        params={"apiKey":ODDS_KEY,"regions":"us","markets":"totals"},timeout=30).json()
    unresolved=[(g["home_team"],g["away_team"]) for g in r if not resolve(g["home_team"]) or not resolve(g["away_team"])]
    print(f"\nunresolved games: {len(unresolved)}")
    for h,a in unresolved[:15]: print("  ",a,"@",h,"| home->",resolve(h),"away->",resolve(a))
