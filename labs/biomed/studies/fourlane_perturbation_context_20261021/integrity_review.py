"""Streaming payload and derived-row verification after experiment completion."""
import hashlib
import json
from pathlib import Path
import sys
import pandas as pd
import numpy as np
from scipy.sparse import load_npz
from intake import ART, DATA, atomic, now, status

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while chunk:=f.read(1024**2):h.update(chunk)
    return h.hexdigest()

def run():
    marker=json.loads((DATA/'screen_confirmation_opened.json').read_text())
    if marker['status']!='evaluated once':raise RuntimeError('screen confirmation not complete; do not imply completed evidence')
    status('final_integrity_review',['bulk and screen confirmations evaluated once'],['streaming hash/row verification','scientific report and disposition'])
    verified=[];errors=[];etags=set();versions=set()
    for folder in [ART/'manifests',*ART.glob('h5chunks*')]:
        for p in folder.glob('*.json'):
            try:
                m=json.loads(p.read_text())
                if 'sha256' not in m:continue
                payload=Path(m['artifact_uri'].removeprefix('file://')) if 'artifact_uri' in m else p.with_suffix('.bin')
                if not payload.resolve().is_relative_to(ART.resolve()):raise ValueError('payload leaves lane staging root')
                if payload.stat().st_size!=m['bytes']:raise ValueError('size mismatch')
                actual=sha(payload)
                if actual!=m['sha256']:raise ValueError('payload hash mismatch')
                verified.append({'manifest':str(p),'manifest_sha256':sha(p),'payload':str(payload),'bytes':m['bytes'],'sha256':actual})
                if 'GWCD4i.pseudobulk_merged.h5ad' in m.get('source_url',''):
                    headers={k.lower():v for k,v in m.get('response_headers',{}).items()}
                    if headers.get('etag'):etags.add(headers['etag'])
                    if headers.get('x-amz-version-id'):versions.add(headers['x-amz-version-id'])
            except Exception as e:errors.append({'path':str(p),'error':repr(e)})
    obs=pd.read_csv(ART/'pseudobulk_obs.csv',index_col=0);row_counts={};cell_counts={}
    for label,table in [('development_controls','development_controls.csv'),('screen_development','screen_development_rows.csv'),('screen_confirmation_controls','screen_confirmation_controls.csv'),('screen_confirmation','screen_confirmation_rows.csv')]:
        selected=pd.read_csv(DATA/table,index_col=0)
        if not selected.index.is_unique:raise ValueError('duplicate selected sample')
        positions=obs.index.get_indexer(selected.index)
        if (positions<0).any():raise ValueError('unknown sample index')
        row_counts[label]=0;cell_counts[label]=float(selected.n_cells.sum())
        for sid,pos in zip(selected.index,positions):
            path=ART/'extracted'/label/f'{pos}.npz'
            try:
                m=json.loads(path.with_suffix('.json').read_text());x=load_npz(path)
                if sha(path)!=m['sha256']:raise ValueError('row hash mismatch')
                if m['sample_id']!=sid or m['row_index']!=int(pos):raise ValueError('row/sample identity mismatch')
                if x.shape!=(1,18129) or not np.isfinite(x.data).all() or (x.data<0).any():raise ValueError('invalid sparse row')
                if not np.isclose(float(x.sum()),obs.iloc[pos].total_counts):raise ValueError('row sum differs from original metadata')
                verified.append({'derived_row':str(path),'sample_id':sid,'sha256':m['sha256'],'bytes':path.stat().st_size})
                row_counts[label]+=1
            except Exception as e:errors.append({'path':str(path),'error':repr(e)})
    if len(etags)!=1 or len(versions)!=1:errors.append({'source_versions':sorted(versions),'source_etags':sorted(etags),'error':'remote object versions not unique'})
    events=[json.loads(x) for x in (ART/'transfer-ledger.jsonl').read_text().splitlines()]
    charged=sum(x.get('bytes',0) for x in events)
    actual_reported=sum(x.get('bytes',0) for x in events if x.get('status') in ['success','failed'])
    files=[p for p in ART.rglob('*') if p.is_file()]
    scratch=sum(p.stat().st_size for p in files)
    partials=[{'path':str(p),'bytes':p.stat().st_size} for p in files if p.suffix in ['.part','.tmp']]
    if charged>6*1024**3:errors.append({'error':'download budget exceeded','charged_bytes':charged})
    if scratch>12*1024**3:errors.append({'error':'scratch budget exceeded','scratch_bytes':scratch})
    index=ART/'evidence_hash_index.json';atomic(index,verified)
    summary={'at_utc':now(),'valid':not errors,'errors':errors,'verified_records':len(verified),'row_counts':row_counts,'cell_counts_not_independent_sample_sizes':cell_counts,'source_object_etags':sorted(etags),'source_object_versions':sorted(versions),'full_remote_object_downloaded':False,'full_remote_object_sha256_claimed':False,'reported_received_bytes':actual_reported,'charged_download_bytes_including_conservative_bounds':charged,'scratch_bytes':scratch,'retained_incomplete_transport_files':partials,'hash_index':{'path':str(index),'sha256':sha(index)},'scope':'byte integrity and sample identity checks, not an assertion of scientific validity or a second confirmation'}
    atomic(DATA/'artifact_integrity_review.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k!='retained_incomplete_transport_files'},indent=2))
    if errors:raise RuntimeError('evidence integrity review failed')

if __name__=='__main__':run()
