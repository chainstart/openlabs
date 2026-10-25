from common import *

m=json.loads((ART/'intake/prism-9393293-v4.json').read_text())
targets=['secondary-screen-dose-response-curve-parameters.csv','secondary-screen-logfold-change.csv','secondary-screen-mfi.csv']
plan={'created_at':now(),'purpose':'Metadata feasibility and source/redo paired-curve assembly, not model evaluation; keep target labels sealed until freeze','files':[{k:x[k] for k in ['id','name','size','download_url']} for x in m['files'] if x['name'] in targets],'max_file_bytes':256*1024**2,'max_total_download_bytes':6*1024**3,'scratch_max_bytes':12*1024**3,'processing':'Read CSV in cell-row chunks or selected columns; no matrix >500 MiB in memory, no whole atlas. Preserve original payload; source and MTS010 are technical screening runs, not independent laboratories. 20Q2 is a later reprocessing/expansion, not a new external experiment.','memory_estimate_mib':1800,'threads':2,'http_concurrency':1}
if not (DATA/'prism-intake-plan.json').exists():write(DATA/'prism-intake-plan.json',plan)
for x in m['files']:
    if x['name'] in targets:
        assert x['size']<=plan['max_file_bytes']
        fetch('prism19-'+x['name'],x['download_url'],limit=256*1024**2,provenance={'provider':'Broad DepMap','release':'PRISM Repurposing 19Q4 v4','doi':m.get('doi'),'file_id':x['id'],'expected_bytes':x['size'],'expected_md5':x.get('computed_md5'),'terms_url':m['license']['url'],'reuse_basis':'CC BY 4.0, official file collection; internal analysis with attribution','upstream_study_ids':['10.1038/s43018-019-0018-6','HTS002','MTS005','MTS006','MTS010'],'sample_unit':'cell model / exact compound / screening run / detection plate replicate; pooled assays not independent cell measurements'})
