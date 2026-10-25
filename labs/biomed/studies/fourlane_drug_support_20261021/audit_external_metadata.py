"""Reproducible BeatAML feasibility, never parse normalized_viability."""
from common import *
import pandas as pd

cols=['dbgap_subject_id','dbgap_dnaseq_sample','dbgap_rnaseq_sample','inhibitor','run_index','inhibitor_panel','plate_num','replicate','well_concentration','time_of_read','passed_qc']
d=pd.read_csv(ART/'intake/beataml-raw.txt',sep='\t',usecols=cols,dtype=str)
sig=['dbgap_subject_id','dbgap_dnaseq_sample','dbgap_rnaseq_sample','inhibitor']
g=d.fillna({'dbgap_dnaseq_sample':'MISSING','dbgap_rnaseq_sample':'MISSING'}).groupby(sig+['run_index','inhibitor_panel','time_of_read']).replicate.nunique().reset_index(name='nrep')
three=g[g.nrep>=3]
valid=d.dropna(subset=sig)
r=valid.groupby(sig+['run_index','time_of_read']).replicate.nunique().reset_index(name='nrep')
units=r.groupby(sig).agg(runs=('run_index','nunique'),maxrep=('nrep','max')).reset_index()
candidate=units[(units.runs>1)&(units.maxrep>=3)]
joined=r.merge(candidate[sig],on=sig)
eligible=[]
for key,group in joined.groupby(sig):
    ok=any(a.run_index!=b.run_index and a.nrep>=2 and b.nrep>=3 and a.time_of_read==b.time_of_read for a in group.itertuples() for b in group.itertuples())
    if ok:eligible.append(dict(zip(sig,key)))
e=pd.DataFrame(eligible)
out={'at':now(),'raw_rows':len(d),'donors':d.dbgap_subject_id.nunique(),'drug_names':d.inhibitor.nunique(),'viability_values_parsed':False,'at_least_three_repeats':{'groups':len(three),'donors':three.dbgap_subject_id.nunique(),'drug_names':three.inhibitor.nunique()},'complete_sequencing_id_pair_signatures':len(units),'missing_specimen_signature_rows':len(d)-len(valid),'crossrun_with_target_three_repeats':{'pairs':len(candidate),'donors':candidate.dbgap_subject_id.nunique(),'drug_names':candidate.inhibitor.nunique()},'source_two_target_three_same_readtime':{'pairs':len(e),'donors':e.dbgap_subject_id.nunique() if len(e) else 0,'drug_names':e.inhibitor.nunique() if len(e) else 0},'disposition':'Not sufficient for donor-generalizable independent cross-run validation: eligible source/target-repeat metadata occurs in one donor. No effect experiment, no clinical claim. Missing sequencing IDs not silently merged; official drug-family workbook lacks exact structure identity.','raw_sha256':hashlib.sha256((ART/'intake/beataml-raw.txt').read_bytes()).hexdigest()}
assert out['source_two_target_three_same_readtime']=={'pairs':10,'donors':1,'drug_names':10}
write(DATA/'beataml-feasibility-reproducible.json',out);print(json.dumps(out,indent=2))
