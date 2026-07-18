"""Deployment fit — F2 RETRAIN (flat-12 pitch grades + HRA movement).
Per-realization full-sample Ridge, raw coefficients keyed by feature name,
+ OOF residual SD. Pitcher: 12 flat grade VALs (free coefs), movement=HRA
(MOV dropped), presence _HAS dropped (deferred R2b). Batter: unchanged."""
import numpy as np, pandas as pd, json, warnings
warnings.filterwarnings('ignore')
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.metrics import r2_score

UP='/mnt/user-data/uploads'
dp=pd.read_parquet(f'{UP}/draft_pool_full__1_.parquet')
cs=pd.read_parquet(f'{UP}/player_cross_section_full__5_.parquet',
   columns=['ID','seed','AGE','ORG','POS','ROLE','BAT_WAR','PIT_WAR','PA','IP'])
PITCHER_POS={'SP','RP','CL'}

dp=dp.sort_values(['ID','seed','AGE'])
feat=dp.groupby(['ID','seed'],as_index=False).first()
BAT_AM=['AM_PA','AM_AVG','AM_OBP','AM_SLG','AM_ISO','AM_wOBA','AM_wRAA','AM_BB_PCT','AM_K_PCT']
PIT_AM=['AM_IP','AM_BF','AM_PIT_HR','AM_PIT_ERA']
for c in BAT_AM+PIT_AM:
    if c in feat.columns:
        feat[f'HSC_{c}']=feat['HSC_MULT'].astype(float)*pd.to_numeric(feat[c],errors='coerce').fillna(0)

# ── 12 enumerated pitch grades, fail-loud parse, '-'->0 ───────────────
PG12=['PIT_FB_GR','PIT_CH','PIT_SI','PIT_SL','PIT_CB','PIT_SP','PIT_CT','PIT_FO','PIT_CC','PIT_SC','PIT_KC','PIT_KN']
def gparse(v):
    t=str(v).strip()
    if t in ('-','','nan','None'): return 0.0
    try: return float(int(t))
    except ValueError: raise ValueError(f'fail-loud: bad grade {v!r}')
for col in PG12:
    feat[f'{col}_VAL']=feat[col].map(gparse)   # flat value, free coef; NO _HAS (deferred R2b)

feat['POW_EYE']=pd.to_numeric(feat['POW'],errors='coerce').fillna(0)*pd.to_numeric(feat['EYE'],errors='coerce').fillna(0)
feat['CON_GAP']=pd.to_numeric(feat['CON'],errors='coerce').fillna(0)*pd.to_numeric(feat['GAP'],errors='coerce').fillna(0)
for p in ['SS','CF','C','2B','3B','RF','LF','1B']:
    feat[f'POS_{p}']=(feat['POS'].astype(str).str.strip()==p).astype(float)
feat['is_pit']=feat['POS'].astype(str).str.strip().isin(PITCHER_POS)

cs['ORG']=cs['ORG'].astype(str).str.strip()
mat=cs[(cs.ORG!='-')&(cs.AGE.between(23,27))].copy()
bat_out=(mat[mat.PA>=1].groupby(['ID','seed'])
    .apply(lambda g:pd.Series({'bat_war':g.BAT_WAR.mean(),'elig_bat':(g.PA>=100).any()})).reset_index())
pit_out=(mat[mat.IP>=1].groupby(['ID','seed'])
    .apply(lambda g:pd.Series({'pit_war':g.PIT_WAR.mean(),'elig_pit':(g.IP>=20).any()})).reset_index())

def build(is_pit,feats,tgt,out,elig):
    sub=feat[feat.is_pit==is_pit].merge(out,on=['ID','seed'],how='inner')
    sub=sub[sub[elig]==True].copy()
    for c in feats:
        if c in sub.columns: sub[c]=pd.to_numeric(sub[c],errors='coerce').fillna(0)
    return sub.dropna(subset=[tgt])

# PITCHER: HRA movement (no MOV); 12 flat VAL (no HAS); rest identical to deploy
PIT_FEATS=(['STU','HRA','PIT_CON','PBABIP','STM','AGE','velo_mid','RISK_ORD','COMP_ORD','HSC_MULT','SLOT_ORD']
    +[f'{c}_VAL' for c in PG12]+['PIT_COUNT']+[f'HSC_{c}' for c in PIT_AM])
BAT_FEATS=(['CON','GAP','POW','EYE','SPE','AGE','POW_EYE','CON_GAP']
    +[f'POS_{p}' for p in ['SS','CF','C','2B','3B','RF','LF','1B']]
    +['WE_ORD','IQ_ORD','AD_ORD','LEA_ORD','LOY_ORD','FIN_ORD','RISK_ORD','COMP_ORD','HSC_MULT']
    +[f'HSC_{c}' for c in BAT_AM])

def deploy_fit(df,feats,tgt,alpha,label):
    feats=[f for f in feats if f in df.columns]
    X=df[feats].values; y=df[tgt].values; g=df['ID'].values
    pipe=make_pipeline(StandardScaler(),Ridge(alpha=alpha))
    oof=cross_val_predict(pipe,X,y,groups=g,cv=GroupKFold(5))
    r2=r2_score(y,oof); resid_sd=float(np.std(y-oof))
    sc=StandardScaler().fit(X); rg=Ridge(alpha=alpha).fit(sc.transform(X),y)
    raw=rg.coef_/sc.scale_
    raw_int=float(rg.intercept_-np.sum(rg.coef_*sc.mean_/sc.scale_))
    chk=np.allclose(X@raw+raw_int, rg.predict(sc.transform(X)),atol=1e-6)
    assert np.all(np.isfinite(raw)) and chk, f'{label}: raw coef check failed'
    print(f'{label}: per-realization CV R2={r2:.4f}  resid_sd={resid_sd:.3f}  N={len(df)}  raw-coef check={chk}')
    return {'features':feats,'raw_coef':{f:float(c) for f,c in zip(feats,raw)},
            'intercept':raw_int,'cv_r2':float(r2),'resid_sd':resid_sd,'alpha':alpha,'n':int(len(df))}

pit=deploy_fit(build(True,PIT_FEATS,'pit_war',pit_out,'elig_pit'),PIT_FEATS,'pit_war',10,'PITCHER(flat12+HRA)')
bat=deploy_fit(build(False,BAT_FEATS,'bat_war',bat_out,'elig_bat'),BAT_FEATS,'bat_war',100,'BATTER(unchanged)')
json.dump({'pitcher':pit,'batter':bat,'lineage':'per-realization (K-T, interim); F2 RETRAIN flat12+HRA',
           'source':'fit_f2_deploy.py'}, open('/home/claude/f2_deploy_NEW.json','w'),indent=2)
print('\nPITCHER raw coef — 12 grade VALs (off-model arms should be +):')
for c in PG12:
    k=f'{c}_VAL'; print(f'  {k:16s} {pit["raw_coef"][k]:+.5f}')
print('  --- movement/other top ---')
for k,v in sorted(pit['raw_coef'].items(),key=lambda x:-abs(x[1])):
    if not k.endswith('_VAL'): print(f'  {k:16s} {v:+.5f}')
