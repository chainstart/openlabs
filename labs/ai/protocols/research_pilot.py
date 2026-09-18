"""Validate configuration and hash-bound evidence for exploratory AI pilots.

This protocol validates an envelope, never scores scientific novelty or grants
publication readiness. Pilot claims cannot be promoted to verified here.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path


def file_record(root,record,errors,label):
    if not isinstance(record,dict):
        errors.append(label+': file record required');return
    raw=record.get('path')
    if not isinstance(raw,str) or not raw or Path(raw).is_absolute():
        errors.append(label+': relative path required');return
    p=(root/raw).resolve()
    if not p.is_relative_to(root) or not p.is_file():
        errors.append(label+': missing file or path escape');return
    actual=hashlib.sha256(p.read_bytes()).hexdigest()
    if actual!=record.get('sha256'):errors.append(label+': SHA-256 mismatch')


def validate(project_path,workstream_path,mode):
    project_path=project_path.resolve();workstream_path=workstream_path.resolve();root=project_path.parent
    project=json.loads(project_path.read_text());state=json.loads(workstream_path.read_text());errors=[]
    if project.get('schema_version')!='openlabs.project.v1' or project.get('domain')!='ai':errors.append('AI project required')
    if project.get('protocol')!={'id':'ai-research-pilot','primary_skill':'ai-research-loop'}:errors.append('Incorrect protocol binding')
    declared={(root/w.get('state_path','')).resolve():w.get('workstream_id') for w in project.get('workstreams',[]) if isinstance(w,dict)}
    if workstream_path not in declared or declared.get(workstream_path)!=state.get('workstream_id'):errors.append('Undeclared workstream or identity mismatch')
    if state.get('project_id')!=project.get('project_id'):errors.append('Project identity mismatch')
    if state.get('schema_version')!='openlabs.ai_research_pilot_state.v1':errors.append('Unknown AI pilot state schema')
    if state.get('stage')!='exploratory_pilot':errors.append('This protocol admits exploratory pilots only')
    if state.get('status') not in {'configured','running','completed','failed','needs_replan'}:errors.append('Invalid state status')
    for field in ['research_question','independent_unit','next_experiment']:
        if not isinstance(state.get(field),str) or not state[field].strip():errors.append(field+' required')
    if state.get('paper_candidate') is not False:errors.append('Exploratory pilot cannot be a paper candidate')
    for field in ['plan','environment']:
        file_record(root,state.get(field),errors,field)
    plan_record=state.get('plan',{})
    if not any(e.startswith('plan:') for e in errors):
        plan=json.loads((root/plan_record['path']).read_text())
        if plan.get('stage')!='exploratory_pilot':errors.append('Plan is not exploratory')
        if not plan.get('primary_outcomes') or not plan.get('stop_conditions'):errors.append('Plan outcomes and stopping rules required')
        if not plan.get('confirmatory_holdout'):errors.append('Holdout boundary required')
    evidence=state.get('evidence',[])
    if not isinstance(evidence,list):errors.append('Evidence must be a list');evidence=[]
    for i,record in enumerate(evidence):file_record(root,record,errors,f'evidence[{i}]')
    if state.get('status')=='completed' and not evidence:errors.append('Completed pilot requires evidence')
    claims=state.get('claims',[])
    if not isinstance(claims,list):errors.append('Claims must be a list');claims=[]
    for claim in claims:
        if not isinstance(claim,dict) or claim.get('status') not in {'hypothesis','provisional','refuted'}:
            errors.append('Pilot claims must remain hypothesis/provisional/refuted')
        elif claim.get('status')!='hypothesis' and not evidence:
            errors.append('Observed pilot claim requires hash-bound evidence')
    return errors


def main():
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--workstream',type=Path,required=True)
    p.add_argument('--mode',choices=['discovery','commit'],required=True);a=p.parse_args()
    try:errors=validate(a.project,a.workstream,a.mode)
    except (OSError,ValueError,TypeError,KeyError) as e:errors=[str(e)]
    print(json.dumps({'valid':not errors,'errors':errors}));return bool(errors)


if __name__=='__main__':raise SystemExit(main())
