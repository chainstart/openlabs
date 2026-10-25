from pathlib import Path
import shutil,json,hashlib,subprocess,sys,datetime
P=Path('/home/biostar/work/projects/openlabs/openlabs-data/workspaces/biology/projects/biomed-new5-proteogenomics-20261024')
A=Path('/home/biostar/work/projects/openlabs/openlabs-artifacts/artifact-stage/biomed/new5-root-20261024')
V=A/'proteogenomics-repair-v2';V.mkdir(exist_ok=False);C=V/'code';C.mkdir()
assert 'openlabs-workers.slice' in Path('/proc/self/cgroup').read_text()
reg={'registered_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reason':'Independent review found mean collapse of duplicate discrete-CNA symbols can create nonexistent categories.','rule':'For exact data_cna.txt only, exclude EVERY row in EVERY duplicate symbol group before analysis, regardless of values or outcomes. Continuous RNA/protein/CNA retain existing per-symbol arithmetic mean; no source-unit equivalence assumed.','new_confirmation':False,'model_selection_or_tuning':False,'frozen_candidate_list':'original nine gain candidates, unchanged','phases':['primary','sensitivity','native_CCLE_qualification','SEG','complex_from_corrected_primary'],'old_frozen_index_sha256':hashlib.sha256((P/'REVIEW_INPUT_INDEX.json').read_bytes()).hexdigest()}
(V/'CORRECTION_REGISTRATION_V2.json').write_text(json.dumps(reg,indent=2)+'\n')
for n in ['analyze.py','sensitivity.py','external_ccle.py','segment_external.py','complex_followup.py','ANALYSIS_REGISTRATION.json','CCLE_FROZEN_SHORTLIST.csv','CELL_LINE_EXTERNAL_REGISTRATION.json','SEGMENT_EXTERNAL_REGISTRATION.json','COMPLEX_FOLLOWUP_PLAN.json']:shutil.copy2(P/n,C/n)
helper='''from pathlib import Path
import json,hashlib
def collapse_discrete_safe(x,n,source):
 if n != 'data_cna.txt':return x.groupby(level=0,sort=True).mean()
 mask=x.index.duplicated(keep=False);symbols=sorted(set(x.index[mask]));y=x.loc[~mask].sort_index()
 log=Path(__file__).parent/'DUPLICATE_CNA_AUDIT.json';a=json.loads(log.read_text()) if log.exists() else {};a[str(source)]={'duplicate_symbols_excluded':symbols,'duplicate_groups_excluded':len(symbols),'all_rows_in_duplicate_groups_excluded':int(mask.sum()),'extra_duplicate_rows':int(x.index.duplicated().sum()),'retained_genes':len(y),'before_unique_finite_values':sorted(set(x.stack().astype(float))),'after_unique_finite_values':sorted(set(y.stack().astype(float))),'source_sha256':hashlib.sha256(Path(source).read_bytes()).hexdigest(),'rule':'all duplicate-symbol groups excluded independent of outcomes'};log.write_text(json.dumps(a,indent=2)+'\\n');assert y.index.is_unique
 return y
'''
(C/'cna_loader_v2.py').write_text(helper)
for n in ['analyze.py','sensitivity.py','external_ccle.py','segment_external.py']:
 s=(C/n).read_text();s='from cna_loader_v2 import collapse_discrete_safe\n'+s
 if n=='analyze.py':
  s=s.replace('dup=int(x.index.duplicated().sum());x=x.groupby(level=0,sort=True).mean()',"dup=int(x.index.duplicated(keep=False).sum()) if n=='data_cna.txt' else int(x.index.duplicated().sum());x=collapse_discrete_safe(x,n,fp(study,n))")
  s=s.replace("'cna_duplicate_rows_collapsed':dc","'cna_all_duplicate_group_rows_excluded':dc")
 elif n=='external_ccle.py':s=s.replace('return x.groupby(level=0).mean()','return collapse_discrete_safe(x,n,file(n))')
 elif n=='sensitivity.py':s=s.replace('return d.groupby(level=0).mean()','return collapse_discrete_safe(d,n,path(s,n))')
 else:s=s.replace('return d.groupby(level=0).mean()','return collapse_discrete_safe(d,n,file(n))')
 (C/n).write_text(s)
s=(C/'complex_followup.py').read_text();s=s.replace("A/'proteogenomics-analysis-v1/pair_effects.csv'", "Path(sys.argv[3])/'pair_effects.csv'");(C/'complex_followup.py').write_text(s)
jobs=[('analyze.py',[str(A/'proteogenomics'),str(V/'primary')]),('sensitivity.py',[str(A/'proteogenomics'),str(V/'primary'),str(V/'sensitivity')]),('external_ccle.py',[str(A),str(V/'external-qualification')]),('segment_external.py',[str(A),str(V/'segment-external')]),('complex_followup.py',[str(A),str(V/'complex'),str(V/'primary')])]
records=[]
for n,args in jobs:
 cmd=[sys.executable,str(C/n),*args];print('START '+n,flush=True);r=subprocess.run(cmd,capture_output=True,text=True);(V/(n+'.log')).write_text(r.stdout+r.stderr);records.append({'argv':cmd,'exit_code':r.returncode});(V/'EXECUTION.json').write_text(json.dumps(records,indent=2)+'\n');assert r.returncode==0,r.stderr;print('DONE '+n,flush=True)
print('ALL DONE',flush=True)
