import os, json, hashlib, datetime, pathlib, sys
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[k]='2'
ROOT=pathlib.Path('/home/biostar/work/projects/openlabs/openlabs')
ART=ROOT.parent/'openlabs-artifacts/artifact-stage/biomed/replan-three-sixhour-20261021/promoter_transfer'
DATA=ROOT.parent/'openlabs-data/workspaces/biology/projects/biomed-replan-promoter-transfer-20261021'
OLD=ROOT.parent/'openlabs-artifacts/artifact-stage/biomed/four-lanes-20261021/promoter_transfer'
OD=ROOT.parent/'openlabs-data/workspaces/biology/projects/biomed-fourlane-promoter-transfer-20261021'
DEADLINE=datetime.datetime.fromisoformat('2026-10-21T19:51:45.199167+00:00')
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def write(p,obj):
    p=pathlib.Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_name(p.name+'.tmp'); t.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n'); t.replace(p)
def status(phase,question,done,remaining,command,failures=None):
    s=dict(updated_at_utc=now(),status='running',phase=phase,research_question=question,completed=done,remaining=remaining,actual_command=command,failures=failures or [],paper_candidate=False,deadline_utc=DEADLINE.isoformat(),evidence_paths=[str(DATA),str(ART)])
    for d in (ART,DATA): write(d/'research_status.json',s)
def guard_check():
    c=pathlib.Path('/proc/self/cgroup').read_text()
    assert 'openlabs-workers.slice' in c and 'openlabs-biomed-replan6h-promoter-transfer-20261021.service' in c,c
    assert datetime.datetime.now(datetime.timezone.utc)<DEADLINE
    return c
if __name__=='__main__':
    c=guard_check()
    status('assessment','跨报告设计来源测量能否预示响应校准失效？候选尚待数据和文献门槛。',['资源与截止核验','读取技能、证据契约及上一轮报告'],['失败审计','近期原始文献','候选数据与独立性','冻结后实验'], 'guard --task-type cpu -- python common.py')
    write(DATA/'environment.json',dict(time=now(),interpreter=sys.executable,python=sys.version,cgroup=c,lock=str(ROOT/'labs/biomed/uv.lock'),lock_sha256=sha(ROOT/'labs/biomed/uv.lock'),threads=2))
