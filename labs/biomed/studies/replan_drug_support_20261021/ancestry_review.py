"""Post-confirmation donor/parent audit; original endpoints and selection unchanged."""
from common import *
from pair_math import selected
from evaluate import weighted_pair_mean
import numpy as np
import pandas as pd
import hashlib

def main():
    p=ART/'intake/depmap22q2-sample-info.csv'
    m=json.loads((ART/'intake/depmap22q2-article.json').read_text())
    f=next(f for f in m['files'] if f['id']==35020903)
    assert hashlib.md5(p.read_bytes()).hexdigest()==f['computed_md5']
    s=pd.read_csv(p); parent={x:x for x in s.DepMap_ID}
    def root(x):
        parent.setdefault(x,x)
        while parent[x]!=x:
            parent[x]=parent[parent[x]];x=parent[x]
        return x
    def union(a,b):parent[root(a)]=root(b)
    for _,g in s.dropna(subset=['patient_id']).groupby('patient_id'):
        for x in g.DepMap_ID:union(g.DepMap_ID.iloc[0],x)
    for row in s.dropna(subset=['parent_depmap_id']).itertuples():union(row.DepMap_ID,row.parent_depmap_id)
    target=pd.read_csv(ART/'sealed/external-target.csv.gz');ids=sorted(target.depmap_id.unique());q=s.set_index('DepMap_ID').loc[ids].copy()
    q['ancestry_group']=[root(x) for x in ids];groups=sorted(q.ancestry_group.unique());q.to_csv(DATA/'donor-parent-linkage-audit.csv')
    frozen=json.loads((ART/'models-frozen.json').read_text());boot=np.load(ART/'bootstrap-results.npz');B=1000;D=len(frozen['scores'])
    rng=np.random.default_rng(20261021);gw=rng.multinomial(len(groups),np.full(len(groups),1/len(groups)),size=B).astype(float)
    values=np.zeros((B,D,2))
    for di,e in enumerate(frozen['scores']):
        z=np.load(e['path'],allow_pickle=False);i=z['i'];j=z['j'];n=len(z['models'])
        y=target[target.structure_key==e['structure_key']].set_index('depmap_id').loc[z['models']].target_auc.to_numpy()
        a=z['raw_direction'];b=y[i]-y[j];error=np.where((a==0)|(b==0),.5,((a>0)!=(b>0)).astype(float))
        W=gw[:,[groups.index(root(c)) for c in z['models']]]
        for k,name in enumerate(['gap_raw','hgb_full']):
            ix=selected(z['scores'][:,frozen['methods'].index(name)],z['tie'],.5)
            values[:,di,k]=weighted_pair_mean(W,i[ix],j[ix],error[ix],n)
    dw=boot['drug_weights'];est=np.einsum('bd,bdm->bm',dw,values)/dw.sum(axis=1)[:,None];delta=est[:,0]-est[:,1]
    out={'at':now(),'timing':'post-confirmation supplementary ancestry sensitivity','metadata_title':m['title'],'source':'https://api.figshare.com/v2/articles/19700056','file_id':35020903,'license':m['license'],'sha256':sha256_file(p),'official_md5_verified':True,'model_ids':len(ids),'patient_ids':int(q.patient_id.nunique()),'missing_patient_ids':int(q.patient_id.isna().sum()),'donor_parent_components':len(groups),'multi_model_components':q.groupby('ancestry_group').apply(lambda x:list(x.index),include_groups=False).loc[lambda x:x.map(len)>1].to_dict(),'bootstrap_draws':B,'chemical_by_ancestry_benefit_ci95':np.quantile(delta,[.025,.975]).tolist(),'primary_unchanged':True,'limitation':'Metadata ancestry does not establish biological replication or independent laboratory; target plate IDs remain unavailable. Same-component pair weights use the same multiplicity squared as the declared crossed resampling scheme.','code_sha256':sha256_file(__file__)}
    write(ART/'ancestry-review.json',out);write(DATA/'ancestry-review.json',out);print(json.dumps(out,indent=2))
if __name__=='__main__':main()
