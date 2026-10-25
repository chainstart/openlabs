"""Source provenance and bounded real-input preprocessing reconstruction."""
from common import *
import pandas as pd
import numpy as np
from rdkit import Chem

official=json.loads((ART/'intake/prism-9393293-v4.json').read_text())
files={str(x['id']):x for x in official['files']};checks=[]
for manifest in (ART/'intake').glob('prism19-*.manifest.json'):
    m=json.loads(manifest.read_text());prov=m['provenance'];file=files[str(prov['file_id'])]
    p=manifest.with_name(manifest.name.removesuffix('.manifest.json'));h=hashlib.md5();sha=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024**2),b''):h.update(b);sha.update(b)
    check={'file':p.name,'file_id':file['id'],'bytes':p.stat().st_size,'official_bytes':file['size'],'official_md5':file.get('computed_md5'),'actual_md5':h.hexdigest(),'sha256':sha.hexdigest()}
    check['matches']=check['bytes']==file['size'] and h.hexdigest()==file.get('computed_md5') and sha.hexdigest()==m['sha256'];checks.append(check)
assert all(x['matches'] for x in checks)
identity=pd.read_csv(DATA/'compound-identity.csv').dropna(subset=['structure_key'])
for row in identity.itertuples(index=False):
    canonical={Chem.MolToSmiles(Chem.MolFromSmiles(s.strip()),isomericSmiles=True) for s in row.smiles.split(',') if s.strip()}
    assert canonical=={row.canonical_smiles}
    assert hashlib.sha256(row.canonical_smiles.encode()).hexdigest()[:24]==row.structure_key
cells=pd.read_csv(DATA/'cell-identity.csv');assert not cells.depmap_id.duplicated().any()
# Audit real raw normalization for 6 original detection plates, all499 matrix rows.
tm=pd.read_csv(DATA/'treatment-metadata.csv');ex=pd.read_csv(ART/'selected-well-metadata.csv')
plates=sorted(ex.detection_plate.unique());chosen=plates[::max(1,len(plates)//6)][:6]
selected=ex[ex.detection_plate.isin(chosen)]
controls=tm[tm.detection_plate.isin(chosen)&tm.perturbation_type.isin(['vehicle_control','positive_control'])]
cols=set(selected.column_name)|set(controls.column_name)
mfi=pd.read_csv(ART/'intake/prism19-secondary-screen-mfi.csv',index_col=0,usecols=lambda x:x=='Unnamed: 0' or x in cols)
old=pd.read_pickle(ART/'normalized-selected-mfi.pkl');errs=[];mask_equal=[]
for plate in chosen:
    c=controls[controls.detection_plate==plate]
    neg=mfi[c[c.perturbation_type=='vehicle_control'].column_name].to_numpy();pos=mfi[c[c.perturbation_type=='positive_control'].column_name].to_numpy()
    with np.errstate(divide='ignore',invalid='ignore'):
        ln=np.log2(np.where(neg>0,neg,np.nan));lp=np.log2(np.where(pos>0,pos,np.nan))
    mn=np.nanmedian(ln,axis=1);mp=np.nanmedian(lp,axis=1)
    sn=np.nanmedian(abs(ln-mn[:,None]),axis=1)*1.4826;sp=np.nanmedian(abs(lp-mp[:,None]),axis=1)*1.4826
    with np.errstate(divide='ignore',invalid='ignore'):score=(mn-mp)/np.sqrt(sn*sn+sp*sp)
    valid=np.isfinite(score)&(score>=2)&(np.isfinite(ln).sum(axis=1)>=3)&(np.isfinite(lp).sum(axis=1)>=3)
    ec=selected[selected.detection_plate==plate].column_name
    values=mfi[ec].to_numpy();values=np.where(values>0,values,np.nan)
    new=values/np.nanmedian(np.where(neg>0,neg,np.nan),axis=1)[:,None];new[~valid]=np.nan
    ref=old.loc[mfi.index,ec].to_numpy();mask_equal.append(bool(np.array_equal(np.isnan(new),np.isnan(ref))))
    errs.append(float(np.nanmax(abs(new-ref))))
assert all(mask_equal) and max(errs)<1e-12
report={'at':now(),'official_payload_checksum_checks':checks,'exact_structure_rows_reconstructed':len(identity),'cell_model_unique':True,'raw_normalization_reconstruction':{'detection_plates':chosen,'all_rows_per_plate':len(mfi),'missing_masks_match':all(mask_equal),'maximum_absolute_difference':max(errs)},'review_scope':'Same agent separate implementation on verified raw payload; not independent laboratory review'}
write(ART/'final-input-audit.json',report);write(DATA/'final-input-audit.json',report)
print(json.dumps({'input_files':len(checks),'all_official_checksums_match':True,'normalization_error':max(errs),'identity_rows':len(identity)},indent=2))
