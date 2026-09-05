"""CFB Totals Edge — dashboard.  Run:  streamlit run live/app.py"""
import os, sys, json, subprocess
import pandas as pd, numpy as np
import streamlit as st
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); OUT=ROOT+"/out"; sys.path.insert(0,HERE)
st.set_page_config(page_title="CFB Totals Edge", page_icon="🏈", layout="wide", initial_sidebar_state="collapsed")

# On Streamlit Cloud the API keys come from st.secrets. Materialize them to the key files +
# env vars so the refresh subprocesses (which read .cfbd_key/.odds_key) work unchanged. Locally
# (no secrets file) this silently no-ops and the existing local key files are used.
try:
    for _k,_f in [("CFBD_KEY",".cfbd_key"),("ODDS_KEY",".odds_key")]:
        if _k in st.secrets:
            _v=str(st.secrets[_k]).strip()
            open(os.path.join(ROOT,_f),"w").write(_v); os.environ[_k]=_v
except Exception:
    pass

CSS="""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@600;700&display=swap');
:root{--bg:#070b16;--card:#111a2e;--card2:#0c1424;--line:#1e2c47;--txt:#eef3fc;--mut:#7e8db0;
--grn:#19e59b;--red:#ff4d73;--amb:#ffc24b;--cyan:#38d6ff;--vio:#8b7bff;}
*{font-family:'Inter',sans-serif;}
.stApp{background:radial-gradient(1200px 500px at 15% -10%,#132449 0%,#070b16 55%) fixed;}
#MainMenu,footer,header{visibility:hidden;}
.block-container{padding-top:1rem;padding-bottom:3rem;max-width:1180px;}
.mono{font-family:'JetBrains Mono',monospace;font-variant-numeric:tabular-nums;}
.hero{background:linear-gradient(110deg,#16224a 0%,#0e1730 60%);border:1px solid var(--line);
  border-radius:20px;padding:20px 26px;margin-bottom:16px;position:relative;overflow:hidden;}
.hero:before{content:'';position:absolute;right:-40px;top:-40px;width:220px;height:220px;
  background:radial-gradient(circle,rgba(25,229,155,.22),transparent 70%);}
.hero h1{font-size:31px;font-weight:900;color:#fff;margin:0;letter-spacing:-.7px;}
.hero h1 .ac{background:linear-gradient(90deg,var(--grn),var(--cyan));-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.hero .sub{color:var(--mut);font-size:13px;margin-top:5px;} .hero .sub b{color:var(--grn);}
.bank{background:linear-gradient(120deg,#122murky,#0b1424);background:linear-gradient(120deg,#122748,#0b1424);border:1px solid #24365d;border-radius:18px;padding:16px 24px;margin:2px 0 16px;display:grid;grid-template-columns:minmax(240px,auto) 1fr;gap:26px;align-items:center;position:relative;overflow:hidden;}
.bank:before{content:'';position:absolute;left:-30px;top:-40px;width:180px;height:180px;background:radial-gradient(circle,rgba(25,229,155,.14),transparent 70%);}
.bank .sub{color:var(--mut);font-size:12px;letter-spacing:.4px;} .bank .sub b{font-weight:800;}
.bank .bal{font-size:36px;font-weight:900;color:#fff;line-height:1.05;margin:2px 0;} .bank .bal.g{color:var(--grn);} .bank .bal.r{color:var(--red);}
.bank .chips{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap;}
.bank .chip{background:#0e1830;border:1px solid #23345a;border-radius:20px;padding:5px 12px;font-size:12px;color:#c7d2ea;font-weight:800;}
.bank .streak.hot{color:var(--amb);} .bank .streak.cold{color:var(--cyan);}
.bank.compact{padding:12px 22px;grid-template-columns:minmax(180px,auto) 1fr;gap:20px;margin:2px 0 14px;}
.bank.compact:before{display:none;} .bank.compact .bal{font-size:26px;}
.kpi{background:linear-gradient(160deg,var(--card),var(--card2));border:1px solid var(--line);border-radius:16px;padding:15px 18px;}
.kpi .n{font-size:26px;font-weight:900;color:var(--txt);line-height:1;} .kpi .n.g{color:var(--grn);} .kpi .n.r{color:var(--red);}
.kpi .l{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:1px;margin-top:6px;font-weight:600;}
.daybar{display:flex;align-items:center;gap:10px;margin:22px 0 10px;}
.daybar span{color:#cdd7ee;font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:1.5px;}
.daybar .ln{flex:1;height:1px;background:linear-gradient(90deg,var(--line),transparent);}
.game{display:grid;grid-template-columns:64px 1fr 210px 118px 104px;gap:14px;align-items:center;
  background:linear-gradient(180deg,var(--card),var(--card2));border:1px solid var(--line);
  border-left:4px solid #23324f;border-radius:14px;padding:13px 18px;margin-bottom:9px;transition:.15s;}
.game:hover{transform:translateY(-1px);box-shadow:0 6px 22px rgba(0,0,0,.35);}
.game.ov{border-left-color:var(--grn);} .game.un{border-left-color:var(--grn);}
/* clickable game bubble (click anywhere on the card to open the projection) */
details.gc{margin-bottom:9px;}
details.gc>summary{list-style:none;cursor:pointer;outline:none;}
details.gc>summary::-webkit-details-marker{display:none;}
details.gc>summary::marker{content:"";}
details.gc>summary .game{margin-bottom:0;}
details.gc[open]>summary .game{border-color:#3a4d7a;box-shadow:0 8px 26px rgba(0,0,0,.45);border-bottom-left-radius:0;border-bottom-right-radius:0;}
details.gc .dpan{margin:0 0 0;border-radius:0 0 14px 14px;border-top:0;}
.kick{color:var(--mut);font-size:12px;font-weight:700;text-align:center;line-height:1.35;} .kick .nd{color:var(--vio);font-size:10px;}
.match .a{color:#c7d2ea;font-weight:600;font-size:15px;} .match .at{color:var(--mut);margin:0 4px;}
.match .h{color:#fff;font-weight:800;font-size:15px;} .match .meta{color:var(--mut);font-size:11px;margin-top:3px;}
.mv{display:flex;align-items:center;justify-content:center;gap:8px;}
.mv .step{text-align:center;} .mv .step .k{font-size:9px;color:var(--mut);text-transform:uppercase;letter-spacing:.5px;font-weight:700;}
.mv .step .v{font-size:14px;font-weight:700;color:#b9c6e3;} .mv .step .v.proj{font-size:19px;font-weight:900;color:#fff;}
.mv .ar{color:var(--mut);font-size:13px;font-weight:800;} .mv .ar.up{color:var(--grn);} .mv .ar.dn{color:var(--red);}
.sp{text-align:center;} .sp .k{font-size:9px;color:var(--mut);text-transform:uppercase;letter-spacing:.5px;font-weight:700;} .sp .v{font-size:15px;font-weight:700;color:#b9c6e3;}
.sig{text-align:center;}
.badge{display:inline-flex;align-items:center;gap:5px;padding:6px 12px;border-radius:22px;font-size:12px;font-weight:900;letter-spacing:.4px;}
.badge.o{background:linear-gradient(90deg,var(--grn),#12b985);color:#042317;box-shadow:0 0 18px rgba(25,229,155,.25);}
.badge.u{background:linear-gradient(90deg,var(--grn),#12b985);color:#042317;box-shadow:0 0 18px rgba(25,229,155,.25);}
.badge.lean{background:transparent;border:1.5px solid;} .badge.lean.o{color:var(--grn);border-color:var(--grn);} .badge.lean.u{color:var(--grn);border-color:var(--grn);}
.badge.none{background:#141d33;color:#5b688a;font-weight:700;}
.badge.aplus{background:linear-gradient(90deg,var(--grn),var(--cyan));color:#042317;box-shadow:0 0 22px rgba(56,214,255,.38);}
.badge.avoid{background:#2a3040;color:#8b93a7;} .badge.caution{background:transparent;border:1.5px solid var(--amb);color:var(--amb);}
.mvc{font-size:10px;font-weight:800;margin-top:5px;letter-spacing:.3px;text-align:center;}
.mvc.up{color:var(--grn);} .mvc.dn{color:var(--red);} .mvc.flat{color:var(--mut);}
.game.aplus{border-left-color:var(--cyan);} .game.avoid{border-left-color:#39415a;opacity:.82;}
.eplus{color:var(--grn);font-weight:800;} .eminus{color:var(--red);font-weight:800;}
/* results table */
.trow{display:grid;grid-template-columns:66px 1fr 150px 60px 72px 62px 54px 40px;gap:10px;align-items:center;
  background:linear-gradient(180deg,var(--card),var(--card2));border:1px solid var(--line);border-radius:10px;padding:9px 16px;margin-bottom:6px;font-size:13px;}
.trow .dt{color:var(--mut);font-size:12px;} .trow .mt .h{color:#fff;font-weight:700;} .trow .mt .a{color:#c7d2ea;} .trow .mt .at{color:var(--mut);}
.trow .ln{color:#b9c6e3;text-align:center;} .trow .ln .k{color:var(--mut);font-size:9px;text-transform:uppercase;}
.pillsm{padding:3px 9px;border-radius:14px;font-size:11px;font-weight:800;text-align:center;}
.pillsm.o{background:rgba(25,229,155,.16);color:var(--grn);} .pillsm.u{background:rgba(25,229,155,.16);color:var(--grn);}
.res{font-weight:900;text-align:center;} .res.WIN{color:var(--grn);} .res.LOSS{color:var(--red);} .res.PUSH{color:var(--amb);}
.clvp{text-align:center;font-weight:800;} .clvp.p{color:var(--grn);} .clvp.m{color:var(--mut);}
.thead{display:grid;grid-template-columns:66px 1fr 150px 60px 72px 62px 54px 40px;gap:10px;padding:0 16px 6px;color:var(--mut);font-size:10px;text-transform:uppercase;letter-spacing:.6px;font-weight:700;}
.legend{color:var(--mut);font-size:12px;margin-top:16px;line-height:1.7;border-top:1px solid var(--line);padding-top:12px;} .legend b{color:#c7d2ea;}
div[data-testid="stSelectbox"] label,div[data-testid="stSlider"] label{color:var(--mut)!important;font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:.5px;}
.stButton button{background:linear-gradient(90deg,var(--grn),#12b985);color:#042317;border:0;border-radius:10px;font-weight:800;}
div[role="radiogroup"]{gap:6px;} div[role="radiogroup"] label{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:6px 16px;color:var(--mut);font-weight:700;}
/* detail panel */
.dpan{background:linear-gradient(160deg,#152banchor,#0c1424);background:linear-gradient(160deg,#13203b,#0c1424);border:1px solid #2a3a5c;border-radius:16px;padding:18px 22px;margin-bottom:14px;}
.dhead{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:6px;}
.dhead .t{font-size:19px;font-weight:900;color:#fff;} .dhead .t .at{color:var(--mut);font-weight:600;margin:0 6px;}
.dhead .r{color:var(--mut);font-size:13px;}
.dsum{display:flex;gap:18px;flex-wrap:wrap;margin:10px 0 16px;}
.dsum .b{background:#0e1830;border:1px solid var(--line);border-radius:12px;padding:8px 16px;min-width:96px;}
.dsum .b .k{font-size:10px;color:var(--mut);text-transform:uppercase;letter-spacing:.6px;font-weight:700;}
.dsum .b .v{font-size:20px;font-weight:900;color:#fff;} .dsum .b .v.g{color:var(--grn);} .dsum .b .v.r{color:var(--red);}
.tcards{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
.tc{background:#0e1830;border:1px solid var(--line);border-radius:12px;padding:14px 16px;}
.tc h4{margin:0 0 10px;color:#fff;font-size:15px;font-weight:800;} .tc h4 .mix{float:right;font-size:11px;color:var(--vio);font-weight:700;}
.stat{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #182238;font-size:13px;}
.stat:last-child{border:0;} .stat .k{color:var(--mut);} .stat .v{color:#dbe4f7;font-weight:700;}
/* ===== MOBILE ONLY (<=680px) — desktop layout is untouched ===== */
@media (max-width:680px){
  .block-container{padding-left:.7rem;padding-right:.7rem;}
  .hero h1{font-size:24px;} .hero{padding:16px 18px;}
  .game{grid-template-columns:1fr auto;grid-template-areas:"match sig" "mv mv" "kick sp";gap:8px 10px;padding:12px 14px;}
  .game .kick{grid-area:kick;text-align:left;}
  .game .match{grid-area:match;}
  .game .mv{grid-area:mv;justify-content:flex-start;gap:12px;}
  .game .mv .step .v.proj{font-size:17px;}
  .game .sp{grid-area:sp;text-align:right;}
  .game .sig{grid-area:sig;justify-self:end;align-self:start;}
  .tcards{grid-template-columns:1fr;}
  .bank,.bank.compact{grid-template-columns:1fr;gap:12px;}
  .bank .rgt{order:2;}
  .thead,.trow{grid-template-columns:50px 1fr 42px 56px 52px;gap:6px;font-size:11px;padding-left:10px;padding-right:10px;}
  .thead>div:nth-child(3),.thead>div:nth-child(7),.thead>div:nth-child(8),
  .trow>*:nth-child(3),.trow>*:nth-child(7),.trow>*:nth-child(8){display:none;}
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

@st.cache_data(ttl=60)
def load():
    s=pd.read_csv(f"{OUT}/slate.csv") if os.path.exists(f"{OUT}/slate.csv") else None
    m=json.load(open(f"{OUT}/slate_meta.json")) if os.path.exists(f"{OUT}/slate_meta.json") else {}
    tr=pd.read_csv(f"{OUT}/track_record.csv") if os.path.exists(f"{OUT}/track_record.csv") else None
    return s,m,tr
slate,meta,track=load()

c1,c2=st.columns([3.3,1])
with c1:
    st.markdown('<div class="hero"><h1>🏈 CFB Totals <span class="ac">Edge</span></h1>'
      f'<div class="sub">De-anchored model · edge vs the <b>opener</b> (bet early for CLV) · '
      f'updated {meta.get("generated","—") if meta else "—"} · odds credits left: <b>{meta.get("requests_remaining","—")}</b></div></div>',
      unsafe_allow_html=True)
def run_job(script, label, args=None):
    with st.spinner(f"{label}…"):
        r=subprocess.run([sys.executable, f"{HERE}/{script}"]+(args or []), cwd=ROOT, capture_output=True, text=True)
    if r.returncode==0:
        st.cache_data.clear(); st.session_state["_msg"]=("ok",f"✅ {label} complete."); st.rerun()
    else:
        st.session_state["_msg"]=("err",f"⚠️ {label} failed:\n{(r.stderr or r.stdout)[-600:]}")

with c2:
    st.markdown("<div style='height:8px'></div>",unsafe_allow_html=True)
    if st.button("🔄  Refresh odds", use_container_width=True,
                 help="Re-pull live lines & re-project with current ratings (1 odds credit). Use Sun–Tue as openers post."):
        run_job("project_slate.py","Refreshing live odds")
    if st.button("🔃  Update week results", use_container_width=True,
                 help="Pull the latest box scores so team ratings update (preseason→live blend), then re-project."):
        run_job("weekly_update.py","Pulling new results + reprojecting")

if st.session_state.get("_msg"):
    kind,txt=st.session_state.pop("_msg")
    (st.success if kind=="ok" else st.error)(txt)

nav=st.radio("nav",["📋 This Week's Board","📈 Track Record"],horizontal=True,label_visibility="collapsed")

def fnum(x): return "—" if (x is None or (isinstance(x,float) and np.isnan(x))) else f"{x:.1f}"
def sp(x):
    if x is None or (isinstance(x,float) and np.isnan(x)): return "—"
    return f"+{x:.1f}" if x>0 else f"{x:.1f}"
def kpis(items):
    for col,(l,n,cl) in zip(st.columns(len(items)),items):
        col.markdown(f'<div class="kpi"><div class="n {cl}">{n}</div><div class="l">{l}</div></div>',unsafe_allow_html=True)

def sparkline(vals, w=560, h=96, color="#19e59b", base=None):
    if len(vals)<2: return ""
    mn,mx=min(vals),max(vals);
    if base is not None: mn=min(mn,base); mx=max(mx,base)
    rng=(mx-mn) or 1; n=len(vals)
    def xy(i,v): return (i/(n-1)*w, h-6-((v-mn)/rng)*(h-12))
    pts=" ".join(f"{x:.1f},{y:.1f}" for i,(x,v) in enumerate(zip(range(n),vals)) for x,y in [xy(i,v)])
    area=f"0,{h} "+pts+f" {w},{h}"
    ex,ey=xy(n-1,vals[-1])
    baseline=""
    if base is not None:
        _,by=xy(0,base); baseline=f'<line x1="0" y1="{by:.1f}" x2="{w}" y2="{by:.1f}" stroke="#33415f" stroke-width="1" stroke-dasharray="4 4"/>'
    return (f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" style="width:100%;height:{h}px">'
      f'<defs><linearGradient id="bkg" x1="0" y1="0" x2="0" y2="1">'
      f'<stop offset="0" stop-color="{color}" stop-opacity="0.30"/><stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>'
      f'{baseline}<polygon points="{area}" fill="url(#bkg)"/>'
      f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linejoin="round"/>'
      f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="3.5" fill="{color}"/></svg>')

BK_DEFAULTS={"bk_basis":"All bets (≥3)","bk_unit":100,"bk_start":10000,"bk_scope":"All history (2020→)","bk_side":"Both","bk_clv":"All CLV"}
def _read_bk(): return tuple(st.session_state.get(k,v) for k,v in BK_DEFAULTS.items())

def bankroll_settings():
    for k,v in BK_DEFAULTS.items(): st.session_state.setdefault(k,v)
    with st.popover("💰 Bankroll settings"):
        st.selectbox("Stake on",["Strong bets (≥5)","All bets (≥3)"],key="bk_basis")
        cA,cB=st.columns(2)
        cA.number_input("$ per bet (flat)",min_value=10,max_value=100000,step=10,key="bk_unit")
        cB.number_input("Starting bankroll $",min_value=0,max_value=10000000,step=500,key="bk_start")
        st.selectbox("Span",["All history (2020→)","2026 season only"],key="bk_scope")
        cC,cD=st.columns(2)
        with cC: st.selectbox("Side",["Both","Overs only","Unders only"],key="bk_side")
        with cD: st.selectbox("CLV",["All CLV","CLV+ (market agreed)","CLV− (market faded)"],key="bk_clv")

def _bk_compute(track):
    basis,unit,start,scope,side,clv=_read_bk()
    b=track[track.rec.isin(["OVER","UNDER"])].copy()
    if basis.startswith("Strong"): b=b[b.tier=="STRONG"]
    if scope.startswith("2026"): b=b[b.season==2026]
    if side=="Overs only": b=b[b.rec=="OVER"]
    elif side=="Unders only": b=b[b.rec=="UNDER"]
    if "agreed" in clv: b=b[b.clv_pts>0]          # positive CLV = close moved toward the model
    elif "faded" in clv: b=b[b.clv_pts<0]
    b["_dt"]=pd.to_datetime(b.date,format="%m/%d/%y",errors="coerce")
    b=b.sort_values(["season","_dt","week"])
    if len(b)==0: return None
    pnl=b.result.map({"WIN":0.9091,"LOSS":-1.0,"PUSH":0.0}).fillna(0)*unit
    curve=(start+pnl.cumsum()).tolist(); bal=curve[-1]; net=bal-start
    dec=b[b.result!="PUSH"]; w=int((dec.result=="WIN").sum()); l=int((dec.result=="LOSS").sum()); p=int((b.result=="PUSH").sum())
    roi=net/(len(dec)*unit)*100 if len(dec) else 0
    winp=w/(w+l)*100 if (w+l) else 0
    seq=list(dec.result)[::-1]; r0=seq[0] if seq else None; stk=0
    for x in seq:
        if x==r0: stk+=1
        else: break
    streak=f'🔥 W{stk}' if r0=="WIN" else (f'🧊 L{stk}' if r0=="LOSS" else "—")
    l10=list(dec.result)[-10:]
    return dict(basis=basis,unit=unit,start=start,curve=curve,bal=bal,net=net,roi=roi,winp=winp,
                w=w,l=l,p=p,streak=streak,scls="hot" if r0=="WIN" else "cold",
                l10w=l10.count("WIN"),l10n=len(l10),nbets=len(dec))

def bankroll_card(track, compact=False):
    if track is None or len(track)==0: return
    d=_bk_compute(track)
    if d is None:
        if not compact: st.markdown('<div class="bank"><div class="lft"><div class="sub">MODEL BANKROLL</div><div class="bal">—</div><div class="sub">no bets in this span yet</div></div><div class="rgt"></div></div>',unsafe_allow_html=True)
        return
    net=d["net"]; color="#19e59b" if net>=0 else "#ff4d73"; gcls="g" if net>=0 else "r"
    netstr=f'<b style="color:{color}">{"+" if net>=0 else "−"}${abs(net):,.0f}</b>'
    if compact:
        st.markdown(f'''<div class="bank compact"><div class="lft">
          <div class="sub">MODEL BANKROLL · {d["basis"].split(" ")[0].lower()}</div>
          <div class="bal {gcls}">${d["bal"]:,.0f}</div>
          <div class="sub">net {netstr} · {d["winp"]:.0f}% win · {d["roi"]:+.1f}% · {d["nbets"]} bets</div></div>
          <div class="rgt">{sparkline(d["curve"],h=62,color=color,base=d["start"])}</div></div>''',unsafe_allow_html=True)
    else:
        st.markdown(f'''<div class="bank"><div class="lft">
          <div class="sub">MODEL BANKROLL · {d["basis"].split(" ")[0].lower()} plays · ${d["unit"]:,}/bet</div>
          <div class="bal {gcls}">${d["bal"]:,.0f}</div>
          <div class="sub">net {netstr} · {d["winp"]:.1f}% win · ROI {d["roi"]:+.1f}% · {d["nbets"]} bets</div>
          <div class="chips"><span class="chip">{d["w"]}-{d["l"]}-{d["p"]}</span>
            <span class="chip streak {d["scls"]}">{d["streak"]}</span>
            <span class="chip">last 10 · {d["l10w"]}-{d["l10n"]-d["l10w"]}</span></div></div>
          <div class="rgt">{sparkline(d["curve"],color=color,base=d["start"])}</div></div>''',unsafe_allow_html=True)

@st.cache_data(ttl=600)
def ratings_for(season, week):
    import ratings_engine as RE
    R,lg=RE.compute_ratings(int(season), int(week)); return R,lg

def detail_html(r, season, week):
    import ratings_engine as RE
    R,lg=ratings_for(season, week)
    rh,ra=R.get(r.home),R.get(r.away)
    if rh is None or ra is None:
        return '<div class="dpan" style="color:#7e8db0">Detailed ratings unavailable for this matchup.</div>'
    feat=RE.project_matchup(r.home,r.away,R,lg,week=int(week),neutral=int(bool(r.neutral)) if pd.notna(r.neutral) else 0,
                            mkt_spread=float(r.mkt_spread) if pd.notna(r.mkt_spread) else 0.0)
    hy=feat["proj_py_h"]+feat["proj_ry_h"]; ay=feat["proj_py_a"]+feat["proj_ry_a"]
    hfin=(feat["fin_off_h"]+feat["fin_def_a"])/2; afin=(feat["fin_off_a"]+feat["fin_def_h"])/2
    rhp=hy*hfin/100; rap=ay*afin/100; sc=r.proj_total/max(rhp+rap,1e-6); hpp,app_=rhp*sc,rap*sc
    edge=r.edge if pd.notna(r.edge) else None
    ecls="g" if (edge or 0)>0 else "r"
    return (f'''<div class="dpan">
      <div class="dsum">
        <div class="b"><div class="k">Market total</div><div class="v">{"—" if pd.isna(r.mkt_total) else r.mkt_total}</div></div>
        <div class="b"><div class="k">Opener</div><div class="v">{"—" if pd.isna(r.open_total) else r.open_total}</div></div>
        <div class="b"><div class="k">Projection</div><div class="v">{r.proj_total}</div></div>
        <div class="b"><div class="k">Edge</div><div class="v {ecls}">{("+" if (edge or 0)>0 else "")+str(edge) if edge is not None else "—"}</div></div>
        <div class="b"><div class="k">Market spread</div><div class="v">{sp(r.mkt_spread)}</div></div>
        <div class="b"><div class="k">Proj score</div><div class="v" style="font-size:15px">{r.away.split()[-1]} {app_:.0f} – {hpp:.0f} {r.home.split()[-1]}</div></div>
      </div>
      <div class="tcards">{team_card(r.away,ra,feat,"a")}{team_card(r.home,rh,feat,"h")}</div>
      <div style="color:#7e8db0;font-size:12px;margin-top:12px;">Opponent-adjusted ratings, as-of all games played to date
        (live mix shown per team). YPA/YPC = yards/attempt vs a league-average opponent; finishing = points per 100 yards.</div></div>''')

def team_card(name, rt, feat, side):
    py=feat[f"proj_py_{side}"]; ry=feat[f"proj_ry_{side}"]
    ypa=feat[f"proj_ypa_{side}"]; yrc=feat[f"proj_yrc_{side}"]
    mix=int(round(rt.get("w",0)*100))
    def row(k,v): return f'<div class="stat"><span class="k">{k}</span><span class="v">{v}</span></div>'
    return (f'<div class="tc"><h4>{name}<span class="mix">{mix}% live</span></h4>'
      + row("Off YPA (rating)", f'{rt["off_ypa"]:.2f}') + row("Def YPA allowed", f'{rt["def_ypa"]:.2f}')
      + row("Off YPC (rating)", f'{rt["off_ypc"]:.2f}') + row("Def YPC allowed", f'{rt["def_ypc"]:.2f}')
      + row("Tempo (plays/g)", f'{rt["tempo"]:.1f}') + row("Pass rate", f'{rt["prate"]*100:.0f}%')
      + row("Finishing (pts/100y off)", f'{rt["fin_off"]:.2f}') + row("Finishing allowed (def)", f'{rt["fin_def"]:.2f}')
      + row("Proj pass yds", f'{py:.0f} @ {ypa:.1f}/att') + row("Proj rush yds", f'{ry:.0f} @ {yrc:.1f}/att')
      + '</div>')

def play_call(edge, side, open_t, now_t):
    """LIVE board recommendation, adjusted for market movement since the opener.
    Returns (call, move) where move = points the market moved TOWARD the model (+) or against (-).
    Backtested: STRONG or confirmed-LEAN + market moving toward = ~60-65%; moved 2+ against = ~45% (avoid).
    NOTE: applied to the live board ONLY — the Track Record stays pure edge-based."""
    if edge is None or (isinstance(edge,float) and pd.isna(edge)): return "NONE", None
    ae=abs(edge); tier = "STRONG" if ae>=5 else ("LEAN" if ae>=3 else "NONE")
    move=None
    if open_t is not None and now_t is not None and pd.notna(open_t) and pd.notna(now_t):
        move=(now_t-open_t) if side=="OVER" else (open_t-now_t)   # + = toward model's side
    if tier=="NONE": return "NONE", move                          # edge<3: not a play, movement irrelevant
    if move is not None and move<=-2: return "AVOID", move        # a PLAY the market moved 2+ against -> skip
    if tier=="STRONG" and move is not None and move>=1: return "APLUS", move
    if tier=="LEAN"  and move is not None and move>=2: return "APLUS", move   # confirmed lean -> upgrade to a play
    if tier=="STRONG": return "STRONG", move
    if tier=="LEAN":   return "LEAN", move
    return "NONE", move

# ============================= BOARD =============================
def render_board():
    bankroll_card(track, compact=True)
    if slate is None or len(slate)==0:
        st.warning("No slate yet — run:  python3 live/project_slate.py"); return
    weeks=sorted(slate.week.dropna().unique()); cur=meta.get("current_week", weeks[0] if weeks else 1)
    f1,f2,f3=st.columns([1,1.6,1.3])
    with f1: wk=st.selectbox("Week",weeks,index=weeks.index(cur) if cur in weeks else 0)
    with f2: show=st.selectbox("Filter",["Leans + bets (edge ≥ 3)","Bets: STRONG (edge ≥ 5)","All games"])
    with f3: side_f=st.selectbox("Side",["Both","Overs only","Unders only"])
    wkraw=slate[slate.week==wk].copy()
    played=int(wkraw.actual_total.notna().sum())
    wkall=wkraw[wkraw.actual_total.isna()].copy()   # board = UPCOMING games only; completed -> Track Record
    wkall["move"]=np.where(wkall.side=="OVER", wkall.mkt_total-wkall.open_total, wkall.open_total-wkall.mkt_total)  # + toward model
    view=wkall.copy()
    if show.startswith("Bets"): view=view[view.abs_edge>=5]
    elif show.startswith("Leans"): view=view[view.abs_edge>=3]
    if side_f=="Overs only": view=view[view.side=="OVER"]
    elif side_f=="Unders only": view=view[view.side=="UNDER"]
    confirmed=int(((wkall.abs_edge>=3)&(wkall.move>=1)).sum())
    kpis([("Upcoming",str(len(wkall)),""),("Strong ★",str(int((wkall.abs_edge>=5).sum())),"g"),
          ("Leans",str(int(((wkall.abs_edge>=3)&(wkall.abs_edge<5)).sum())),""),
          ("Market ✓",str(confirmed),"g")])
    if played:
        st.markdown(f'<div class="legend" style="border:0;margin:6px 0 0;padding:0;">✓ {played} game(s) this week already '
                    f'played — results moved to the <b>Track Record</b> tab.</div>',unsafe_allow_html=True)
    st.markdown("<div style='height:8px'></div>",unsafe_allow_html=True)
    def arrow(o,c):
        if o is None or c is None or pd.isna(o) or pd.isna(c) or c==o: return '<span class="ar">→</span>'
        return '<span class="ar up">↗</span>' if c>o else '<span class="ar dn">↘</span>'
    def row(r):
        edge=r.edge if pd.notna(r.edge) else None
        move=getattr(r,"move",None); move=None if (move is not None and isinstance(move,float) and pd.isna(move)) else move
        und=(r.side=="UNDER"); oc="u" if und else "o"
        cls="ov" if (edge is not None and edge>0) else ("un" if edge is not None else "")
        strong=edge is not None and abs(edge)>=5
        lean=edge is not None and 3<=abs(edge)<5
        confirmed=move is not None and move>=1        # market has moved 1+ pt toward the model
        star=" ★" if strong else ""; chk=" ✓" if confirmed else ""
        if edge is None: badge='<span class="badge none">NO LINE</span>'
        elif strong: badge=f'<span class="badge {oc}">{r.side}{star}{chk}</span>'
        elif lean: badge=f'<span class="badge lean {oc}">{r.side}{chk}</span>'
        else: badge=f'<span class="badge none">{r.side}</span>'
        if move is not None:
            if move>=0.5: mvchip=f'<div class="mvc up">mkt ✓ +{move:.1f}</div>'
            elif move<=-0.5: mvchip=f'<div class="mvc dn">mkt ⚠ {move:.1f}</div>'
            else: mvchip='<div class="mvc flat">mkt →</div>'
        else: mvchip=''
        edtxt=f'<span class="eplus">{"+" if (edge or 0)>0 else ""}{edge:.1f}</span>' if edge is not None else ""
        mv=(f'<div class="mv"><div class="step"><div class="k">Open</div><div class="v mono">{fnum(r.open_total)}</div></div>{arrow(r.open_total,r.mkt_total)}'
            f'<div class="step"><div class="k">Now</div><div class="v mono">{fnum(r.mkt_total)}</div></div><span class="ar">·</span>'
            f'<div class="step"><div class="k">Proj {edtxt}</div><div class="v proj mono">{fnum(r.proj_total)}</div></div></div>')
        nd='<div class="nd">◇ NEUTRAL</div>' if r.neutral else ''
        return (f'<div class="game {cls}"><div class="kick">{"" if pd.isna(r.time) else r.time}{nd}</div>'
          f'<div class="match"><div><span class="a">{r.away}</span><span class="at">@</span><span class="h">{r.home}</span></div>'
          f'<div class="meta">{int(r.n_books) if pd.notna(r.n_books) else ""} books</div></div>'
          f'{mv}<div class="sp"><div class="k">Spread</div><div class="v mono">{sp(r.mkt_spread)}</div></div><div class="sig">{badge}{mvchip}</div></div>')
    if len(view)==0: st.info("No games match these filters.")
    else:
        rwk=meta.get("ratings_week", wk)
        for day in view.day.dropna().unique():
            st.markdown(f'<div class="daybar"><span>{day}</span><div class="ln"></div></div>',unsafe_allow_html=True)
            for r in view[view.day==day].itertuples():
                dh=detail_html(r, meta.get("season",2026), rwk)
                st.markdown(f'<details class="gc"><summary>{row(r)}</summary>{dh}</details>',unsafe_allow_html=True)
    st.markdown('<div class="legend"><b>Open → Now → Proj</b>: opener → current line vs model projection. '
      '<b>★</b> = strong play (edge ≥ 5). <b>✓</b> = market agrees (line has moved 1+ pt toward the model since the opener). '
      '<b>mkt ✓ / ⚠</b> chip = points the line moved toward (✓) or against (⚠) the model. '
      'Bet the ★ plays early into the opener; a ✓ is added confirmation, and a red ⚠ chip is a caution. Not betting advice.</div>',unsafe_allow_html=True)

# ============================= TRACK RECORD =============================
def render_track():
    if track is None or len(track)==0:
        st.warning("No track record yet — run:  python3 live/build_track_record.py"); return
    bankroll_settings()
    bankroll_card(track, compact=False)
    seasons=["All"]+[str(s) for s in sorted(track.season.unique())]
    def_season=str(int(track.season.max())) if len(track) else "All"   # default to current season
    g1,g2,g3=st.columns(3)
    with g1: seas=st.selectbox("Season",seasons,index=seasons.index(def_season) if def_season in seasons else 0)
    with g2: tier=st.selectbox("Bets",["All bets (≥3)","Strong only (≥5)","Leans only (3–5)"])
    with g3: res=st.selectbox("Result",["All","Wins","Losses"])
    h1,h2,h3=st.columns(3)
    with h1: side_f=st.selectbox("Side",["Both","Overs only","Unders only"])
    with h2: clv_f=st.selectbox("CLV",["All CLV","CLV+ (market agreed)","CLV− (market faded)"])
    with h3:
        st.markdown("<div style='height:26px'></div>",unsafe_allow_html=True)
        if st.button("↻ Rebuild", use_container_width=True, help="Re-pull latest results + regrade the whole history."):
            run_job("build_track_record.py","Rebuilding track record")
    d=track.copy()
    if seas!="All": d=d[d.season==int(seas)]
    bets=d[d.rec.isin(["OVER","UNDER"])].copy()       # actual bets only (a play was recommended, edge>=3)
    if tier.startswith("Strong"): bets=bets[bets.tier=="STRONG"]
    elif tier.startswith("Leans"): bets=bets[bets.tier=="LEAN"]
    if side_f=="Overs only": bets=bets[bets.rec=="OVER"]
    elif side_f=="Unders only": bets=bets[bets.rec=="UNDER"]
    if "agreed" in clv_f: bets=bets[bets.clv_pts>0]
    elif "faded" in clv_f: bets=bets[bets.clv_pts<0]
    dec=bets[bets.result!="PUSH"]; w=int((dec.result=="WIN").sum()); l=int((dec.result=="LOSS").sum()); p=int((bets.result=="PUSH").sum())
    winp=w/(w+l)*100 if (w+l) else 0; roi=(w*0.9091-l)/(w+l)*100 if (w+l) else 0; units=w*0.9091-l
    clvp=(bets.clv=="+").mean()*100 if len(bets) else 0
    avgm=dec.margin.mean() if len(dec) else 0
    avgclv=bets.clv_pts.mean() if ("clv_pts" in bets and len(bets)) else 0
    mae_m=bets.proj_err.abs().mean() if ("proj_err" in bets and len(bets)) else 0
    mae_v=bets.vegas_err.abs().mean() if ("vegas_err" in bets and len(bets)) else 0
    kpis([("Record",f"{w}-{l}-{p}",""),("Win %",f"{winp:.1f}%","g" if winp>=52.38 else "r"),
          ("ROI @ -110",f"{roi:+.1f}%","g" if roi>=0 else "r"),
          ("Avg margin",f"{avgm:+.1f}","g" if avgm>=0 else "r"),
          ("Avg CLV",f"{avgclv:+.1f}","g" if avgclv>=0 else "r")])
    st.markdown(f'<div class="legend" style="border:0;margin:8px 0 0;padding:0;">On these bets — '
      f'model MAE <b>{mae_m:.1f}</b> vs Vegas-close MAE <b>{mae_v:.1f}</b> '
      f'({"model sharper" if mae_m<mae_v else "market sharper"}) · {clvp:.0f}% beat the closing number</div>',unsafe_allow_html=True)
    st.markdown("<div style='height:10px'></div>",unsafe_allow_html=True)
    if res=="Wins": bets=bets[bets.result=="WIN"]
    elif res=="Losses": bets=bets[bets.result=="LOSS"]
    bets["_dt"]=pd.to_datetime(bets.date,format="%m/%d/%y",errors="coerce")
    bets=bets.sort_values(["season","_dt","week"],ascending=[False,False,False])   # most recent first
    st.markdown('<div class="thead"><div>Date</div><div>Matchup</div><div>Open · Close · Proj</div><div>Edge</div><div>Bet</div><div>Result</div><div>By</div><div>CLV</div></div>',unsafe_allow_html=True)
    N=250; shown=bets.head(N)
    html=[]
    for r in shown.itertuples():
        oc="u" if r.rec=="UNDER" else "o"
        star=" ★" if r.tier=="STRONG" else ""
        ln=f'<span class="k">O</span> {fnum(r.opener)} · <span class="k">C</span> {fnum(r.close)} · <b>{fnum(r.proj)}</b>'
        ecls="eplus" if r.edge>0 else "eminus"
        cp=r.clv_pts if ("clv_pts" in shown.columns and pd.notna(r.clv_pts)) else None
        clv=(f'<span class="clvp {"p" if cp>0 else "m"}">{"+" if cp>0 else ""}{cp:.1f}</span>' if cp is not None else '<span class="clvp m">—</span>')
        mg=r.margin if ("margin" in shown.columns and pd.notna(r.margin)) else None
        mgcls="eplus" if (mg or 0)>0 else "eminus"
        mghtml=f'<div class="ln mono {mgcls}">{"+" if (mg or 0)>0 else ""}{mg:.1f}</div>' if mg is not None else '<div class="ln">—</div>'
        html.append(f'<div class="trow"><div class="dt">{r.date if isinstance(r.date,str) else ""}</div>'
          f'<div class="mt"><span class="a">{r.away}</span> <span class="at">@</span> <span class="h">{r.home}</span> '
          f'<span class="dt">· final {int(r.actual)}</span></div>'
          f'<div class="ln mono">{ln}</div><div class="ln mono {ecls}">{"+" if r.edge>0 else ""}{r.edge:.1f}</div>'
          f'<div><span class="pillsm {oc}">{r.rec}{star}</span></div>'
          f'<div class="res {r.result}">{r.result}</div>{mghtml}{clv}</div>')
    st.markdown("".join(html),unsafe_allow_html=True)
    if len(bets)>N: st.caption(f"Showing {N} of {len(bets)} bets (KPIs reflect all). Narrow the filters to see more.")
    st.markdown('<div class="legend"><b>Leak-free walk-forward</b> 2019–2025: each game projected using only prior data, '
      'graded vs the <b>opener</b> at edge ≥ 3. <b>CLV ✓</b> = the closing line moved toward our side (value captured). '
      'Break-even at -110 is 52.4%. Past results, not a guarantee.</div>',unsafe_allow_html=True)

render_board() if nav.startswith("📋") else render_track()
