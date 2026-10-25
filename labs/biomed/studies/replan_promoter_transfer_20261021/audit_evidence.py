"""Read-only provenance/resource audit and lane-local evidence records."""
from common import *
import csv,collections,shutil,math
guard_check()
freeze=json.loads((DATA/'freeze.json').read_text())
checks={}
for p,h in freeze['code_sha256'].items():assert sha(p)==h
assert sha(freeze['plan_path'])==freeze['plan_sha256']
assert sha(DATA/'split-audit.json')==freeze['split_audit_sha256']
for ds,parts in freeze['partitions']['summary'].items():
    for sp,m in parts.items():assert sha(m['path'])==m['sha256']
train=json.loads((DATA/'training-completed.json').read_text())
opened=json.loads((ART/'test-opened.json').read_text())
saved=json.loads((DATA/'test-predictions-saved.json').read_text())
assert freeze['time']<train['time']<opened['time']<saved['time']
assert sha(DATA/'training-completed.json')==opened['training_record_sha256']
for p,h in train['models'].items():assert sha(ART/'models'/p)==h
for p,h in saved['files'].items():assert sha(ART/'predictions'/p)==h
with (DATA/'samples.csv').open() as f:rows=list(csv.DictReader(f))
groups=collections.defaultdict(set)
for r in rows:groups[r['group']].add(r['split'])
assert all(len(s)==1 for s in groups.values())
checks.update(frozen_code_unchanged=True,frozen_plan_unchanged=True,all_partition_hashes_match=True,model_hashes_match=True,
    saved_confirmation_predictions_unchanged=True,chronology_valid=True,group_overlap=0,total_rows=len(rows),global_groups=len(groups),
    timestamps=dict(freeze=freeze['time'],training_finished=train['time'],test_opened=opened['time'],predictions_saved=saved['time']))
lock=ROOT/'labs/biomed/uv.lock';env=json.loads((DATA/'environment.json').read_text());assert sha(lock)==env['lock_sha256']
shutil.copyfile(lock,DATA/'environment.lock')
checks['lock_snapshot_sha256']=sha(DATA/'environment.lock')
manifests=[];body=0
for p in (ART/'manifests').glob('*.json'):
    m=json.loads(p.read_text());body+=m.get('actual_bytes',m.get('bytes',0))
    if m.get('sha256'):
        q=ART/'payload'/p.name.removesuffix('.ranges.json').removesuffix('.json')
        if q.exists():assert sha(q)==m['sha256']
    manifests.append(dict(path=str(p),sha256=sha(p),status=m.get('status'),actual_bytes_recorded=m.get('actual_bytes',m.get('bytes',0))))
old_audit=json.loads((DATA/'reuse-hash-audit.json').read_text())
# Original manifests remain untouched; this current attribution overrides preliminary Bose labels.
intakes=[]
for filename,doi,accession,unit in [
 ('GSE142696_9MPRA.ActivityRatios.IndividualReps.tsv.gz','10.1038/s41592-020-0965-y','GSE142696','HepG2 genomic locus; three separate culture/day replicates'),
 ('GSE142696_9MPRA.ActivityRatios.tsv.gz','10.1038/s41592-020-0965-y','GSE142696','same upstream experiment, published source estimator'),
 ('GSE279057_kyono_library_counts.txt.gz','10.1016/j.xhgg.2026.100606','GSE279057','genomic locus/signal; pooled four-vector library, three electroporations, one DNA input'),
 ('GSE279057_kyono_library_barcode_pairing.txt.gz','10.1016/j.xhgg.2026.100606','GSE279057','barcode mapping, not independent samples'),
 ('GSE279057_kyono_library_annotations.txt.gz','10.1016/j.xhgg.2026.100606','GSE279057','fragment designs, not independent biological replicates')]:
    p=ART/'payload'/filename;mp=ART/'manifests'/(filename+('.ranges.json' if accession=='GSE279057' else '.json'))
    m=json.loads(mp.read_text())
    intakes.append(dict(provider='NCBI GEO',release_accession=accession,source_url=m['source_url'],final_url=m.get('final_url',m['source_url']),
       retrieval_timestamp=m.get('completed_at_utc',m.get('time')),sample_unit=unit,citation_doi=doi,upstream_study_ids=[accession,doi],
       terms_url='https://www.ncbi.nlm.nih.gov/home/about/policies/',reuse_basis='Official public GEO files, attributed private computational research; no claim that public access alone grants unrestricted redistribution.',
       staging_root=str(ART),file_uri=p.as_uri(),size_bytes=p.stat().st_size,sha256=sha(p),original_manifest=str(mp),original_manifest_sha256=sha(mp)))
write(DATA/'verified-intakes.json',dict(time=now(),intakes=intakes,correction='GSE279057 attribution is Tovar2026; earlier Bose2025 refers to reused same library/experiment, never another independent replication.'))
cg=pathlib.Path('/sys/fs/cgroup'+pathlib.Path('/proc/self/cgroup').read_text().strip().split('::',1)[1])
resources={k:(cg/k).read_text().strip() for k in ['memory.current','memory.peak','memory.high','memory.max','memory.swap.max','memory.events','cpu.max','cpu.stat','pids.max','pids.current'] if (cg/k).exists()}
files=[p for p in ART.rglob('*') if p.is_file()]
scratch=sum(p.stat().st_size for p in files)
assert scratch<12*1024**3 and body<6*1024**3
res=dict(time=now(),cgroup=str(cg),resources=resources,artifact_bytes=scratch,manifest_body_bytes_recorded=body,
    download_accounting='Manifest sum can include extracted members (not network), and interrupted retries have separate prefix records. Conservative additional allowance10MiB covers recorded interrupted prefixes/in-flight uncertainty; not a byte-exact transport ledger.',
    conservative_network_budget_bound_bytes=body+10*1024**2,download_limit_bytes=6*1024**3,scratch_limit_bytes=12*1024**3,
    HTTP_concurrency_caveat='Early interrupted-downloader/metadata handoff not provably <=2 aggregate HTTP requests. Subsequently enforced cross-process filesystem semaphore2. See operation-errors.json; no claim of perfect historical compliance.',GPU_used=False,packages_installed=False,subagents_started=False,original_raw_experiments_resynced=False)
write(DATA/'resource-and-download-audit.json',res)
write(DATA/'boundary-and-hash-review.json',dict(time=now(),checks=checks,manifests=manifests,formal_protocol_validator_passed=False,
    contract_scope='Applied prospective plan, exact lock, public intake, grouped samples/split audit, all baseline metrics, trials, hashes. Custom paired-assay risk endpoint and three-directory lane layout are not the standard confined project protocol; do not report a validator pass.'))
print('checks',checks,'resources',resources,'bytes',scratch,body)
