import hashlib
import importlib.util
import json
from pathlib import Path

SPEC=importlib.util.spec_from_file_location('ai_pilot_protocol',Path(__file__).parents[1]/'protocols/research_pilot.py')
MODULE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(MODULE)


def fixture(tmp_path):
    def write(name,obj):
        p=tmp_path/name;p.write_text(json.dumps(obj));return {'path':name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    plan=write('plan.json',{'stage':'exploratory_pilot','primary_outcomes':['error'],
                          'stop_conditions':['invalid oracle'],'confirmatory_holdout':'unseen tasks, not yet run'})
    env=write('env.json',{'python':'/usr/bin/python3'})
    project={'schema_version':'openlabs.project.v1','project_id':'p','domain':'ai',
             'protocol':{'id':'ai-research-pilot','primary_skill':'ai-research-loop'},
             'workstreams':[{'workstream_id':'w','state_path':'state.json'}]}
    state={'schema_version':'openlabs.ai_research_pilot_state.v1','project_id':'p','workstream_id':'w',
           'stage':'exploratory_pilot','status':'configured','paper_candidate':False,'research_question':'q',
           'independent_unit':'task','next_experiment':'bounded pilot','plan':plan,'environment':env,'claims':[],'evidence':[]}
    write('project.json',project);write('state.json',state)
    return tmp_path/'project.json',tmp_path/'state.json',state


def test_valid_envelope_and_tampered_plan(tmp_path):
    project,state,_=fixture(tmp_path)
    assert MODULE.validate(project,state,'discovery')==[]
    (tmp_path/'plan.json').write_text('{}')
    assert 'plan: SHA-256 mismatch' in MODULE.validate(project,state,'commit')


def test_no_pilot_promotion_or_empty_completion(tmp_path):
    project,path,state=fixture(tmp_path)
    state.update(status='completed',paper_candidate=True,claims=[{'status':'verified'}]);path.write_text(json.dumps(state))
    errors=MODULE.validate(project,path,'commit')
    assert 'Completed pilot requires evidence' in errors
    assert 'Exploratory pilot cannot be a paper candidate' in errors
    assert 'Pilot claims must remain hypothesis/provisional/refuted' in errors


def test_evidence_cannot_escape_project(tmp_path):
    project,path,state=fixture(tmp_path)
    state['evidence']=[{'path':'../outside.json','sha256':'0'*64}];path.write_text(json.dumps(state))
    assert any('path escape' in e for e in MODULE.validate(project,path,'commit'))


def test_workstream_identity_is_bound(tmp_path):
    project,path,state=fixture(tmp_path);state['workstream_id']='other';path.write_text(json.dumps(state))
    assert any('identity' in e for e in MODULE.validate(project,path,'discovery'))
