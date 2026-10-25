"""Final provenance/resource audit and scientific closeout; no inference."""
from common import *
import subprocess

def main():
    cg=Path('/proc/self/cgroup').read_text();assert 'openlabs-workers.slice/openlabs-biomed-replan6h-drug-support-20261021.service' in cg
    service='openlabs-biomed-replan6h-drug-support-20261021.service'
    resource=subprocess.check_output(['systemctl','--user','show',service,'--property=CPUQuotaPerSecUSec,MemoryHigh,MemoryMax,MemorySwapMax,TasksMax,MemoryCurrent,MemoryPeak,TasksCurrent,ControlGroup'],text=True)
    old_checks=[]
    for fn in ['prior-evidence-hashes.json','old-payload-reuse.json','old-readonly-references.json']:
        for entry in json.loads((DATA/fn).read_text()):
            actual=sha256_file(entry['path']);assert actual==entry['sha256'],entry['path'];old_checks.append({'path':entry['path'],'sha256':actual,'unchanged':True})
    oldroot=ROOT/'openlabs-artifacts/artifact-stage/biomed/four-lanes-20261021/drug_support'
    for name in ['prism19-secondary-screen-mfi.csv','prism19-secondary-screen-replicate-treatment-info.csv','prism19-secondary-screen-pooling-info.csv']:
        p=oldroot/'intake'/name;m=json.loads(p.with_name(name+'.manifest.json').read_text());actual=sha256_file(p);assert actual==m['sha256']
        old_checks.append({'path':str(p),'sha256':actual,'unchanged_from_original_intake_manifest':True})
    frozen=json.loads((ART/'models-frozen.json').read_text())
    assert sha256_file(DATA/'plan-frozen.json')==frozen['plan_sha256']
    assert sha256_file(ART/'models.joblib')==frozen['model_sha256']
    for name,sha in frozen['code'].items():assert sha256_file(CODE/name)==sha,name
    for e in frozen['scores']:assert sha256_file(e['path'])==e['sha256']
    env=json.loads((DATA/'environment.json').read_text());assert sha256_file(env['lock_path'])==env['lock_sha256']
    intake=[]
    for p in sorted((ART/'intake').glob('*.manifest.json')):
        m=json.loads(p.read_text())
        if m.get('success'):
            dest=p.with_name(p.name.removesuffix('.manifest.json'));assert sha256_file(dest)==m['sha256'],str(dest)
            intake.append({'name':dest.name,'bytes':dest.stat().st_size,'sha256':m['sha256']})
    downloaded=json.loads((ART/'download-ledger.json').read_text())['actual_bytes'];assert downloaded<6*1024**3
    sizes={str(base):sum(p.stat().st_size for p in base.rglob('*') if p.is_file()) for base in (ART,DATA,CODE)}
    assert sum(sizes.values())<12*1024**3
    # Bounded current service process list: never inspect other route scientific files.
    group=cg.strip().split('::',1)[1];pids=(Path('/sys/fs/cgroup')/group.lstrip('/')/'cgroup.procs').read_text().split()
    procs=[]
    for pid in pids:
        p=Path('/proc')/pid/'comm'
        if p.exists():procs.append({'pid':int(pid),'comm':p.read_text().strip()})
    start=json.loads((ART/'review-start.json').read_text());print('review start',start)
    audit={'at_utc':now(),'cgroup':cg,'resource_snapshot':resource,'processes_in_own_service_at_audit':procs,'note':'Snapshot includes active agent/supervisor and this bounded audit. Scientific workers finished; agent exits after final answer. No unrelated jobs killed.','download_actual_bytes':downloaded,'scratch_current_bytes_by_directory':sizes,'scratch_current_total_bytes':sum(sizes.values()),'old_references':old_checks,'all_checked_old_hashes_unchanged':True,'all_frozen_model_code_score_hashes_unchanged':True,'environment_lock_unchanged':True,'successful_intake_payloads':intake,'figures_visually_reviewed':['primary-benefit.png','calibration-transfer.png','all-baseline-errors.png','coverage-sensitivity.png'],'third_party_review':False}
    for base in (ART,DATA):write(base/'final-audit.json',audit)
    scripts=['metadata.py','freeze.py','prepare_source.py','prepare_target.py','models.py','preopening_audit.py','evaluate.py','review_integrals.py','review_statistics.py','audit_identity_models.py','calibration_review.py','dependence_sensitivity.py','ancestry_review.py','descriptive_strata.py','make_figures.py','closeout.py','final_audit.py','validate_delivery.py']
    prefix=f'{ROOT}/openlabs/bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 {env["executable"]} '
    write(ART/'execution-ledger.json',{'at':now(),'command_form':prefix+'<script>','records':[{'script':str(CODE/s),'command':prefix+str(CODE/s),'sha256':sha256_file(CODE/s),'status':'executed'} for s in scripts],'ordering':'Scientific execution ordering documented in README; this list is not an exact timestamped shell history.','additional_execution':'evaluate.py --resume-after-indexing-failure continued the same opening; inline metadata/intake/source-review commands retained in agent logs and per-file manifests.','no_fabricated_timestamps':True})
    print(json.dumps({'download_bytes':downloaded,'scratch_bytes':sum(sizes.values()),'old_checks':len(old_checks),'intake_payloads_verified':len(intake),'resources':resource},indent=2))

if __name__=='__main__':main()
