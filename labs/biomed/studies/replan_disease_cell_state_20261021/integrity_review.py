from common import *
import subprocess

records=[json.loads(line) for line in (ART/'manifest.jsonl').read_text().splitlines()]
verified=[];failures=[]
for record in records:
 if record.get('status')!='complete':
  failures.append({k:record[k] for k in ['name','url','attempt','error','bytes'] if k in record});continue
 p=Path(record['path']);assert p.is_relative_to(ART)
 assert p.exists() and p.stat().st_size==record['bytes'] and sha(p)==record['sha256'],str(p)
 verified.append(dict(path=str(p.relative_to(ART)),bytes=p.stat().st_size,sha256=record['sha256']))
oldrefs=json.loads((DATA/'assessment.json').read_text())['old_evidence']
for p,h in oldrefs.items():assert sha(p)==h,(p,'old evidence modified')
all_oldrefs=json.loads((DATA/'old_evidence_references.json').read_text())
for ref in all_oldrefs:assert sha(ref['path'])==ref['sha256'],(ref['path'],'old referenced evidence modified')
oldzip=json.loads((DATA/'C3_supplement_inventory_audit.json').read_text())
assert sha(oldzip['path'])==oldzip['sha256']
plan=json.loads((DATA/'plan_frozen_v1.json').read_text())
assert sha(DATA/'plan_frozen_v1.json')==json.loads((DATA/'plan_frozen_v1.sha256.json').read_text())['sha256']
assert sha(ART/'plan_frozen_v1.json')==sha(DATA/'plan_frozen_v1.json')
for acc,ref in plan['sample_tables'].items():assert sha(ref['path'])==ref['sha256']
source=json.loads((DATA/'annotation_readonly_reference.json').read_text());assert sha(source['path'])==source['sha256']
env=json.loads((ART/'environment_actual.json').read_text())
assert sys.executable==env['executable']
for p,h in env['lock_hashes'].items():assert sha(p)==h,(p,'shared lock changed')
cg=Path('/proc/self/cgroup').read_text();assert 'openlabs-workers.slice' in cg and 'openlabs-biomed-replan6h-disease-cell-state-20261021.service' in cg
properties=subprocess.check_output(['systemctl','--user','show','openlabs-biomed-replan6h-disease-cell-state-20261021.service','-p','MemoryCurrent','-p','MemoryPeak','-p','CPUUsageNSec','-p','CPUQuotaPerSecUSec','-p','MemoryHigh','-p','MemoryMax','-p','MemorySwapMax','-p','TasksMax'],text=True)
sizes={str(root):sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) for root in [ART,DATA,CODE]}
assert sum(sizes.values())<12*1024**3
transfer=json.loads((ART/'transfer_bytes.json').read_text())['bytes'];assert transfer<6*1024**3
summary=dict(at=now(),payloads_verified=verified,all_complete_payloads_match=True,failed_intake_attempts=failures,manifest_bytes=sum(r.get('bytes',0) for r in records),accounted_transfer_bytes=transfer,transfer_difference_explanation='Range feasibility probe and early byte-account reconciliation are separately recorded; failed response bytes counted where received',old_frozen_report_hashes_unchanged=oldrefs,old_annotation_unchanged=source['sha256'],plan_hash=sha(DATA/'plan_frozen_v1.json'),sample_tables_unchanged=True,cgroup=cg,resource_properties=properties,scratch_bytes=sizes,code_hashes={p.name:sha(p) for p in CODE.glob('*.py')},old_confirmation_opened=False,all_checks_pass=True)
summary['environment_locks_unchanged']=True
summary['reproduce_doc_sha256']=sha(CODE/'REPRODUCE.md')
summary['all_referenced_old_files_unchanged']=True
summary['source_probe_bytes']=json.loads((DATA/'original_source_probe.json').read_text())['bytes']
assert summary['accounted_transfer_bytes']==summary['manifest_bytes']+summary['source_probe_bytes']
summary['byte_accounting_exactly_reconciled']=True
atomic(ART/'integrity_review.json',summary)
print(json.dumps({k:v for k,v in summary.items() if k not in ['payloads_verified','old_frozen_report_hashes_unchanged','code_hashes','failed_intake_attempts']}))
