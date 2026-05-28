"""Deployment fit: per-realization full-sample Ridge, raw coefficients keyed by
feature name (apply directly to raw feature values), + OOF residual SD."""
import numpy as np, pandas as pd, json
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.pipeline import make_pipeline

UP='/mnt/user-data/uploads'
dp=pd.read_parquet(f'{UP}/draft_pool_full.parquet')
cs=pd.read_parquet(f'{UP}/player_cross_section_full.parquet',
   columns=['ID','seed','AGE','ORG','POS','ROLE','BAT_WAR','PIT_WAR','PA','IP'])
PITCHER_POS={'SP','RP','CL'}

dp=dp.sort_values(['ID','seed','AGE'])
feat=dp.groupby(['ID','seed'],as_index=False).first()
BAT_AM=['AM_PA','AM_AVG','AM_OBP','AM_SLG','AM_ISO','AM_wOBA','AM_wRAA','AM_BB_PCT','AM_K_PCT']
PIT_AM=['AM_IP','AM_BF','AM_PIT_HR','AM_PIT_ERA']
for c in BAT_AM+PIT_AM:
    if c in feat.columns:
        feat[f'HSC_{c}']=feat['HSC_MULT'].astype(float)*pd.to_numeric(feat[c],errors='coerce').fillna(0)
PG=['PIT_FB_GR','PIT_CH','PIT_SI','PIT_SL']
for col in PG:
    feat[f'{col}_VAL']=pd.to_numeric(feat[col],errors='coerce').fillna(0)
    feat[f'{col}_HAS']=(feat[f'{col}_VAL']>0).astype(float)
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

PIT_FEATS=(['STU','MOV','PIT_CON','PBABIP','HRA','STM','AGE','velo_mid','RISK_ORD','COMP_ORD','HSC_MULT','SLOT_ORD']
    +[f'{c}_VAL' for c in PG]+[f'{c}_HAS' for c in PG]+['PIT_COUNT']+[f'HSC_{c}' for c in PIT_AM])
BAT_FEATS=(['CON','GAP','POW','EYE','SPE','AGE','POW_EYE','CON_GAP']
    +[f'POS_{p}' for p in ['SS','CF','C','2B','3B','RF','LF','1B']]
    +['WE_ORD','IQ_ORD','AD_ORD','LEA_ORD','LOY_ORD','FIN_ORD','RISK_ORD','COMP_ORD','HSC_MULT']
    +[f'HSC_{c}' for c in BAT_AM])

def deploy_fit(df,feats,tgt,alpha,label):
    feats=[f for f in feats if f in df.columns]
    X=df[feats].values; y=df[tgt].values; g=df['ID'].values
    pipe=make_pipeline(StandardScaler(),Ridge(alpha=alpha))
    oof=cross_val_predict(pipe,X,y,groups=g,cv=GroupKFold(5))
    from sklearn.metrics import r2_score
    r2=r2_score(y,oof); resid_sd=float(np.std(y-oof))
    sc=StandardScaler().fit(X); rg=Ridge(alpha=alpha).fit(sc.transform(X),y)
    raw=rg.coef_/sc.scale_
    raw_int=float(rg.intercept_-np.sum(rg.coef_*sc.mean_/sc.scale_))
    # verify raw coefficients reproduce pipeline predictions
    chk=np.allclose(X@raw+raw_int, rg.predict(sc.transform(X)),atol=1e-6)
    assert np.all(np.isfinite(raw)) and chk, f'{label}: raw coef check failed'
    print(f'{label}: per-realization CV R2={r2:.3f}  resid_sd={resid_sd:.3f}  N={len(df)}  raw-coef check={chk}')
    return {'features':feats,'raw_coef':{f:float(c) for f,c in zip(feats,raw)},
            'intercept':raw_int,'cv_r2':float(r2),'resid_sd':resid_sd,'alpha':alpha,'n':int(len(df))}

pit=deploy_fit(build(True,PIT_FEATS,'pit_war',pit_out,'elig_pit'),PIT_FEATS,'pit_war',10,'PITCHER')
bat=deploy_fit(build(False,BAT_FEATS,'bat_war',bat_out,'elig_bat'),BAT_FEATS,'bat_war',100,'BATTER')
json.dump({'pitcher':pit,'batter':bat,'lineage':'per-realization (K-T, interim)','source':'fit_f2_deploy.py'},
          open('/home/claude/f2_deploy.json','w'),indent=2)
print('saved /home/claude/f2_deploy.json')
print('\nPITCHER raw coef (sorted):')
for k,v in sorted(pit['raw_coef'].items(),key=lambda x:-abs(x[1]))[:12]: print(f'  {k:16s} {v:+.4f}')
print('BATTER raw coef (sorted):')
for k,v in sorted(bat['raw_coef'].items(),key=lambda x:-abs(x[1]))[:12]: print(f'  {k:16s} {v:+.4f}')
