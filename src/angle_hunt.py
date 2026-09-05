"""Hunt for exploitable conditions on the de-anchored model's disagreements with the total.
All bets require |model - close| >= EDGE (default 3). Reports win% / ROI / p vs 52.38% and
per-season consistency (to avoid single-season flukes)."""
import numpy as np, pandas as pd
from scipy import stats
m=pd.read_csv('out/angle_frame.csv')
EDGE=3.0

def grade(d, line_col='mkt_total'):
    d=d.copy(); d['e']=d.pred-d[line_col]
    b=d[d.e.abs()>=EDGE].copy(); b['side']=np.where(b.e>0,'over','under')
    amL=b.total_pts-b[line_col]
    b['win']=((b.side=='over')&(amL>0))|((b.side=='under')&(amL<0)); b['push']=amL==0
    return b

def report(name,b):
    ndec=int((~b.push).sum()); nwin=int(b.win.sum())
    if ndec<20: print(f"  {name:<30} n={ndec:<4} (too small)"); return
    wp=nwin/ndec*100; roi=(nwin*.9091-(ndec-nwin))/ndec*100
    p=stats.binomtest(nwin,ndec,0.5238,alternative='greater').pvalue
    # per-season win% for consistency
    seas=b[~b.push].groupby('season').win.mean()*100
    cons="".join('+' if v>=52.38 else '-' for _,v in seas.items())
    print(f"  {name:<30} n={ndec:<4} win%={wp:>5.1f} ROI%={roi:>+5.1f} p={p:.3f}  seasons[{cons}]")

B=grade(m)  # base: all disagreements vs close
print(f"=== BASELINE: all disagreements (|edge|>={EDGE}) vs CLOSE ===")
report("all", B)

print("\n=== by EDGE DIRECTION ===")
report("model OVER", B[B.side=='over']); report("model UNDER", B[B.side=='under'])

print("\n=== by TOTAL LEVEL (closing total) ===")
for lab,q in [("total<=45","B.mkt_total<=45"),("45-52","(B.mkt_total>45)&(B.mkt_total<=52)"),
              ("52-59","(B.mkt_total>52)&(B.mkt_total<=59)"),("59+","B.mkt_total>59")]:
    report(lab, B[eval(q)])

print("\n=== by TIER (market sharpness) ===")
for t in ['P5-P5','G5-G5','mixed']: report(t, B[B.tier==t])

print("\n=== by SPREAD SIZE (blowout scripts) ===")
report("close (|spread|<=7)", B[B.mkt_spread.abs()<=7])
report("mid (7-17)", B[(B.mkt_spread.abs()>7)&(B.mkt_spread.abs()<=17)])
report("blowout (|spread|>17)", B[B.mkt_spread.abs()>17])

print("\n=== by WEEK WINDOW ===")
report("wk2-4", B[(B.week>=2)&(B.week<=4)]); report("wk5-9", B[(B.week>=5)&(B.week<=9)])
report("wk10+", B[B.week>=10]); report("wk1", B[B.week==1])

print("\n=== INTERACTIONS (direction x condition) ===")
report("UNDER & total>=59", B[(B.side=='under')&(B.mkt_total>=59)])
report("UNDER & G5", B[(B.side=='under')&(B.tier=='G5-G5')])
report("OVER & total<=45", B[(B.side=='over')&(B.mkt_total<=45)])
report("UNDER & blowout", B[(B.side=='under')&(B.mkt_spread.abs()>17)])
report("OVER & close game", B[(B.side=='over')&(B.mkt_spread.abs()<=7)])

# ---------- vs OPENING total (softer number / CLV) ----------
print(f"\n=== vs OPENING total (does model beat the opener?) ===")
mo=m.dropna(subset=['mkt_total_open'])
BO=grade(mo,'mkt_total_open')
report("all vs OPEN", BO)
# line moved toward model side since open?
mo2=mo.copy(); mo2['move']=mo2.mkt_total-mo2.mkt_total_open
mo2['model_side']=np.sign(mo2.pred-mo2.mkt_total_open)
mo2['confirmed']=np.sign(mo2.move)==mo2.model_side  # market moved toward model
BC=grade(mo2[mo2.confirmed],'mkt_total_open'); report("vs OPEN, market CONFIRMED", BC)
BD=grade(mo2[~mo2.confirmed],'mkt_total_open'); report("vs OPEN, market FADED", BD)
print(f"\n(EDGE threshold={EDGE}; 'seasons[+/-]' shows each yr 2019..2025 above/below break-even)")
print("(NOTE: many angles tested -> treat single low-p hits with skepticism / demand a mechanism)")
