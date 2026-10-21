import json
from common import *
plan=json.loads((PROJECT/'plan.json').read_text())
projectid=PROJECT.name
def rec(name):return dict(path=name,sha256=sha(PROJECT/name))
atomic(PROJECT/'project.json',dict(schema_version='openlabs.project.v1',project_id=projectid,
 domain='biology',lab_id='biomed',status='active',objective=plan['research_question'],
 protocol=dict(id='biomed-public-data-pilot',primary_skill='biomed-research-loop'),
 workstreams=[dict(workstream_id='orientation-transfer',state_path='research_state.json',startup='paused',
 agent_role='researcher',session_mode='fresh',objective=plan['research_question'],resources=dict(cpu_threads=2,memory_mib=1536,scratch_mib=3072))]))
atomic(PROJECT/'research_state.json',dict(schema_version='openlabs.biomed_pilot_state.v1',project_id=projectid,
 workstream_id='orientation-transfer',status='running',paper_candidate=False,
 research_question=plan['research_question'],independent_unit='molecule',
 next_experiment='Complete guarded intake, fixed eight-policy training/validation, freeze selection and evaluate WTC11 confirmation once.',
 plan=rec('plan.json'),environment=rec('environment.json'),datasets=[],
 evidence=[rec(x) for x in ['candidate-screen.json','identity-audit.json','split-audit.json','software-check.json']],
 claims=[dict(status='hypothesis',text=plan['hypothesis'])]))
print('local project/state initialized; factory startup stays paused')
