"""Independent correction checks, no import of patched analyses."""
from pathlib import Path
import json,hashlib,collections,argparse
import numpy as np,pandas as pd
P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-proteogenomics-20261024');A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-root-20261024');V=A/'proteogenomics-repair-v2'
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
oldidx=json.loads((P/'REVIEW_INPUT_INDEX.json').read_text())
for x in oldidx['files']:
 f=Path(x['path']);h=hashlib.sha256()
 with f.open('rb') as z:
  for b in iter(lambda:z.read(1024**2),b''):h.update(b)
 assert h.hexdigest()==x['sha256'] and f.stat().st_size==x['bytes'],str(f)
audit=json.loads((V/'code/DUPLICATE_CNA_AUDIT.json').read_text());checks=[]
for f,rec in audit.items():
 raw=pd.read_csv(f,sep='\t',comment='#',low_memory=False);genes=raw.iloc[:,0].astype(str).str.split('|').str[0];counts=collections.Counter(genes);dup=sorted(g for g,n in counts.items() if n>1);assert dup==rec['duplicate_symbols_excluded'];assert sum(counts[g] for g in dup)==rec['all_rows_in_duplicate_groups_excluded'];assert len(raw)-sum(counts[g] for g in dup)==rec['retained_genes'];vals=raw.iloc[:,1:].drop(columns=['Entrez_Gene_Id'],errors='ignore').apply(pd.to_numeric,errors='coerce');after=vals.loc[genes.map(counts)==1];assert sorted(set(after.stack().astype(float)))==rec['after_unique_finite_values'];checks.append({'file':f,'duplicate_groups':len(dup),'rows_excluded':sum(counts[g] for g in dup),'retained_unique_values':rec['after_unique_finite_values']})
old=pd.read_csv(A/'proteogenomics-analysis-v1/pair_effects.csv');new=pd.read_csv(V/'primary/pair_effects.csv');keys=['study','target','partner'];joined=old.merge(new,on=keys,suffixes=('_old','_v2'),validate='one_to_one');removed=old.merge(new[keys],on=keys,how='left',indicator=True);removed=removed[removed._merge=='left_only'][keys];removed.to_csv(V/'REMOVED_PRIMARY_MODELS_V2.csv',index=False)
maincols=[c for c in new if c.startswith(('adjusted_','without_rna_')) and not c.endswith('_q')];err=max(float(np.nanmax(abs(joined[c+'_old']-joined[c+'_v2']))) for c in maincols);assert err<1e-10
def bh(p):
 order=np.argsort(p);v=np.array([p[i]*len(p)/(j+1) for j,i in enumerate(order)]);v=np.minimum.accumulate(v[::-1])[::-1];q=np.empty(len(p));q[order]=np.minimum(v,1);return q
qerr=0.
for _,g in new.groupby(['study','same_chr']):
 for prefix in ['adjusted','without_rna','permuted']:
  for ep in ['loss','gain','asymmetry']:qerr=max(qerr,float(np.max(abs(bh(g[prefix+'_'+ep+'_p'].to_numpy())-g[prefix+'_'+ep+'_q'].to_numpy()))))
assert qerr<1e-10
short=pd.read_csv(P/'CCLE_FROZEN_SHORTLIST.csv');disc=new[(new.study=='luad_cptac_2020')&(~new.same_chr)&(new.adjusted_gain_q<.05)];assert set(zip(disc.target,disc.partner))==set(zip(short.target,short.partner));ss=short.merge(disc,on=['target','partner'],suffixes=('_frozen','_v2'));shorterr=max(float(abs(ss[c+'_frozen']-ss[c+'_v2']).max()) for c in ['adjusted_gain_beta','adjusted_gain_q']);assert shorterr<1e-12
assert (P/'CCLE_FROZEN_SHORTLIST.csv').read_bytes()==(V/'code/CCLE_FROZEN_SHORTLIST.csv').read_bytes()
native_old=pd.read_csv(A/'ccle-external-v1/group_support.csv');native_new=pd.read_csv(V/'external-qualification/group_support.csv');pd.testing.assert_frame_equal(native_old,native_new)
segold=pd.read_csv(A/'ccle-segment-external-v1/shortlist_effects.csv');segnew=pd.read_csv(V/'segment-external/shortlist_effects.csv');pd.testing.assert_frame_equal(segold,segnew,rtol=1e-10,atol=1e-12)
sensold=pd.read_csv(A/'proteogenomics-sensitivity-v1/sensitivity_effects.csv');sensnew=pd.read_csv(V/'sensitivity/sensitivity_effects.csv');sensjoin=sensold.merge(sensnew,on=keys+['mode'],suffixes=('_old','_v2'),validate='one_to_one');se=max(float(np.max(abs(sensjoin[c+'_old']-sensjoin[c+'_v2']))) for c in ['loss_beta','loss_p','gain_beta','gain_p','asymmetry_beta','asymmetry_p']);assert se<1e-10
out={'all_checks_passed':True,'old_frozen_files_unchanged':len(oldidx['files']),'old_index_sha256':hashlib.sha256((P/'REVIEW_INPUT_INDEX.json').read_bytes()).hexdigest(),'raw_duplicate_exclusion_checks':checks,'old_primary_rows':len(old),'v2_primary_rows':len(new),'removed_primary_models':removed.to_dict('records'),'retained_primary_nonpermutation_coefficient_p_se_max_error':err,'BH_independent_max_error':qerr,'frozen_nine_gain_candidates_identical':True,'frozen_candidate_effect_q_max_error':shorterr,'native_CCLE_group_support_unchanged':True,'SEG_shortlist_results_numerically_unchanged':True,'old_sensitivity_rows':len(sensold),'v2_sensitivity_rows':len(sensnew),'retained_sensitivity_coefficient_p_max_error':se,'randomized_controls':'Excluded models change subsequent RNG consumption in BRCA permutation/family-bootstrap branches. Recomputed all prescribed controls, not new experiments.','complex_v2_input':str(V/'primary/pair_effects.csv'),'no_new_confirmation':True,'no_scientific_approval':True}
args.output.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
