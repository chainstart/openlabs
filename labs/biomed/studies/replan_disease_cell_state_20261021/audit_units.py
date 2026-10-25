from common import *
import pandas as pd,itertools
frames={acc:pd.read_csv(DATA/f'{acc}_samples_frozen.csv',dtype={'subject':str}) for acc in ['GSE184316','GSE199949','GSE150910']}
rows=[]
for acc,m in frames.items():
 assert m.sample_id.is_unique
 assert m.groupby('donor_id').diagnosis.nunique().max()==1
 for d,g in m.groupby('donor_id'):
  assert g.age.dropna().nunique()<=1
  rows.append(dict(study_id=acc,donor_id=d,n_regions=len(g),diagnosis=g.diagnosis.iloc[0],age_known=bool(g.age.notna().all()),eligible_adult=bool(g.eligible_adult.all()),sex_conflict=bool(g.sex_conflict.any() or g.sex.nunique()!=1)))
allunits=pd.DataFrame(rows);allunits.to_csv(DATA/'donor_units_frozen.csv',index=False)
a=pd.read_csv(DATA/'GSE124685_metadata.csv',dtype=str);a['subject']=a.title.str.split('.').str[0]
b=frames['GSE184316'];overlap=sorted(set(a.subject)&set(b.subject))
comparisons=[]
for x,y in itertools.combinations(frames,2):
 comparisons.append(dict(study_a=x,study_b=y,shared_GSM=sorted(set(frames[x].sample_id)&set(frames[y].sample_id)),study_names_differ=True,limitations='Different accession or namespace is not proof of biological independence'))
atomic(DATA/'split_and_independence_audit.json',dict(at=now(),independent_unit='lung_donor',split_strategy='study_held_out',group_columns=['study_id','donor_id'],table_hashes={acc:sha(DATA/f'{acc}_samples_frozen.csv') for acc in frames},donor_table_sha256=sha(DATA/'donor_units_frozen.csv'),crossstudy_metadata=comparisons,excluded_pseudoreplication_pair=dict(studies=['GSE124685','GSE184316'],matching_donor_labels=overlap,matching_IPF_labels=sorted(set(a.loc[a['disease state'].eq('IPF'),'subject'])&set(b.loc[b.diagnosis.eq('IPF'),'subject'])),decision='Not independent; GSE124685 excluded from confirmation regardless of gene expression similarity'),external_confirmation_evidence=dict(development='GSE184316original regional lung study, Leuven tissue collection/Yale profiling;10IPF overlap with originalLeuven2019study',confirmation='PMC9896241Methods explicitly UniversityofChicagoIRB andGift ofHope donor lungs;distinct central/peripheral experiments and authors',conclusion='Institution and original-study provenance support cohort separation for frozen new paired test; no genotype proof available',context='GSE150910multi-centre includesLTRC/UCSF/Pittsburgh/Vanderbilt; upstream overlap with oldlung studies not fully resolvable; used onlycontext'),protocol_status='adapted_observational_audit; genericthreewaytrain-validation-testvalidatornotapplicable',paper_candidate=False))
# Cohort confounding summary uses metadata only, never scores.
summary={}
for acc,m in frames.items():
 m=m[m.eligible_primary];d=m.groupby('donor_id').first();entry=dict(age_by_diagnosis=d.groupby('diagnosis').age.agg(['count','mean','min','max']).to_dict(),sex_by_diagnosis=pd.crosstab(d.diagnosis,d.sex).to_dict())
 for col in ['sample type','institution','batch','plate','ever_smoked']:
  if col in d:entry[col+'_by_diagnosis']=pd.crosstab(d.diagnosis,d[col]).to_dict()
 if acc=='GSE150910':
  entry['batch_perfect_diagnosis_separation']=bool(d.groupby('batch').diagnosis.nunique().max()==1)
 summary[acc]=entry
atomic(DATA/'confounding_metadata_audit.json',dict(at=now(),cohorts=summary,note='Metadata audit only. Within-donor primary cancels fixed donor age/sex, but anatomy/region selection and platform remain. Large-cohort disease effects do not isolate batch or control indication.'))
print(allunits.groupby(['study_id','diagnosis']).size().to_dict());print('overlap rejected',overlap)
