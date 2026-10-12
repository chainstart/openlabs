"""Proportional reporting without relaxing scientific or release requirements."""
import copy
import json
import zipfile
from pathlib import Path
import pytest
from paper_writing import formal_checks as f, review_flow as flow
from paper_writing.review_launcher import LaunchError
from test_formal_checks import run_fixture, fixture_workspace, mock_http, ROLE, simulated_runner


def test_whitespace_quote_equivalence_still_binds_raw_source(tmp_path, monkeypatch):
    m,b,d=run_fixture(tmp_path,monkeypatch)
    q=d['report']['references'][0]['evidence'][0]
    q['quote']='for every real x,\n\t x squared is nonnegative'
    assert f.report_blockers(d['report'],d['inventory'],d['sources'])==[]
    source=next(s for s in d['sources'] if s['id']==q['source_id'])
    assert source['text_sha256']==f.sha(source['text'].encode())
    for wrong in ['For every real x, x squared is nonnegative',
                  'for every real x, x squared is negative',
                  'for every real x, x-squared is nonnegative']:
        q['quote']=wrong
        assert any('Quoted evidence is absent' in x for x in f.report_blockers(d['report'],d['inventory'],d['sources']))
    q['quote']='1234567890'+' '*1000
    assert any('insufficient quotation' in x for x in f.report_blockers(d['report'],d['inventory'],d['sources']))


def test_internal_locator_only_whitespace_is_equivalent(tmp_path,monkeypatch):
    _,_,d=run_fixture(tmp_path,monkeypatch)
    p=next(p for p in d['report']['passages'] if p['prerequisites'])
    t=p['prerequisites'][0];t.update(kind='internal_derivation',reference_keys=[],evidence=[],
                                    original_locator='For real\n\t $x$, $x^2\\ge0$')
    assert f.report_blockers(d['report'],d['inventory'],d['sources'])==[]
    t['original_locator']='For real $x$, $x^2\\le0$'
    assert any('Internal derivation locator' in x for x in f.report_blockers(d['report'],d['inventory'],d['sources']))


def test_parent_aggregation_suppressed_not_distinct_checks(tmp_path,monkeypatch):
    _,_,d=run_fixture(tmp_path,monkeypatch)
    p=next(p for p in d['report']['passages'] if p['prerequisites'])
    p['status']='gap';p['prerequisites'][0]['status']='gap';p['formulas'][0]['status']='error'
    raw=[];blockers=f.report_blockers(d['report'],d['inventory'],d['sources'],findings=raw)
    summary=f.issue_summary(raw)
    assert len(blockers)==3 and len(raw)==3
    assert len(summary['root_causes'])==2
    assert len(summary['by_category']['scientific'])==2
    assert d['report']['passages'][d['report']['passages'].index(p)]['status']=='gap'


def test_actual_pdf_missing_or_hash_changed_is_preparation_not_science(tmp_path,monkeypatch):
    m=fixture_workspace(tmp_path)
    supp=tmp_path/'papers/p/manuscript/Additionalfile1.pdf'
    m['latest_supplementary_pdf']=str(supp.relative_to(tmp_path))
    assert f.artifact_inventory(m,tmp_path)['blockers']
    supp.write_bytes(b'%PDF-1.4\nactual fixture\n%%EOF')
    inventory=f.artifact_inventory(m,tmp_path)
    assert not inventory['blockers']
    assert {r['id'] for r in inventory['records']}=={'main_pdf','supplement_pdf'}
    assert all(r['scientific_correctness_established'] is False for r in inventory['records'])
    m['submission_package']={'source_archive':'papers/p/source.zip','source_archive_sha256':'0'*64}
    assert f.artifact_inventory(m,tmp_path)['blockers']


def test_historical_zip_presence_does_not_establish_current_source_identity(tmp_path):
    m=fixture_workspace(tmp_path);m['version']='2'
    archive=tmp_path/'papers/p/source.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('main.tex','genuine historical source')
    m['submission_package']={'version':'1','source_archive':str(archive.relative_to(tmp_path)),
                             'source_archive_sha256':f.sha(archive.read_bytes())}
    a=f.artifact_inventory(m,tmp_path)
    record=next(r for r in a['records'] if r['id']=='journal_source_archive')
    assert record['status']=='present' and record['current_version_identity'] is False
    assert record['current_source_correspondence_requires_official_handoff'] is True
    archive.write_bytes(b'not the registered ZIP')
    assert f.artifact_inventory(m,tmp_path)['blockers']


def test_artifact_claim_requires_actual_configured_binding(tmp_path,monkeypatch):
    m,_,d=run_fixture(tmp_path,monkeypatch)
    p=next(p for p in d['report']['passages'] if p['prerequisites'])
    t=p['prerequisites'][0];t.update(kind='artifact_preparation',reference_keys=[],evidence=[],original_locator='main_pdf')
    artifacts=f.artifact_inventory(m,tmp_path)
    assert f.report_blockers(d['report'],d['inventory'],d['sources'],artifacts=artifacts)==[]
    t['original_locator']='all experimental results reproduced'
    assert f.report_blockers(d['report'],d['inventory'],d['sources'],artifacts=artifacts)


def test_routing_fails_before_any_model_for_missing_selector_or_binding(tmp_path,monkeypatch):
    m=fixture_workspace(tmp_path);p=tmp_path/'papers/p/evidence.json';p.write_text('{"observations":1}')
    m['formal_check']['local_evidence']=[{'path':str(p.relative_to(tmp_path)),'sha256':f.sha(p.read_bytes()),
        'kind':'execution_record','passage_patterns':['No actual paragraph','For real']}]
    docs,bib=f.current_inputs(m,tmp_path);inv=f.inventory(docs,bib)
    assert any('selector' in x for x in f.local_route_preflight(m,inv,tmp_path))
    m['formal_check']['local_evidence'][0]['passage_patterns']=['For real']
    assert f.local_route_preflight(m,inv,tmp_path)==[]
    p.write_text('changed actual evidence')
    assert any('hash' in x for x in f.local_route_preflight(m,inv,tmp_path))
    run=tmp_path/'run';run.mkdir();mock_http(monkeypatch)
    def forbidden(**kwargs):raise AssertionError('Do not spend a model call on broken declared routing')
    binding=f.run_checks({'metadata':m},tmp_path,run,ROLE,1,forbidden)
    assert binding['valid'] is False
    assert binding['issue_summary']['by_category']['source_routing']
    assert binding['issue_summary']['by_category']['scientific']==[]


def test_mixed_model_gap_and_protocol_failure_preserves_science(tmp_path,monkeypatch):
    m=fixture_workspace(tmp_path);mock_http(monkeypatch)
    run=tmp_path/'run';run.mkdir()
    def runner(**kw):
        output,receipt=simulated_runner(**kw)
        if output['passages']:
            output['passages'][0]['status']='gap'
            output['passages'][-1]['passage_id']='invented ID'
        return output,receipt
    b=f.run_checks({'metadata':m},tmp_path,run,ROLE,1,runner)
    cats=b['issue_summary']['by_category']
    assert cats['scientific'] and cats['technical'] and not b['valid']
    merged=flow.merge({'decision':'send_to_review'}, {}, formal_blockers=b['blockers'],formal_summary=b['issue_summary'])
    assert merged['scientific_blockers'] and merged['technical_blockers']


def test_service_failure_retains_real_failure_and_cannot_pass(tmp_path,monkeypatch):
    m=fixture_workspace(tmp_path);mock_http(monkeypatch);run=tmp_path/'run';run.mkdir()
    calls=[]
    def down(**kwargs):
        calls.append(kwargs['role_name'])
        raise LaunchError('actual fixture service capacity failure')
    b=f.run_checks({'metadata':m},tmp_path,run,ROLE,1,down)
    assert len(calls)==2 and b['valid'] is False
    assert b['issue_summary']['by_category']['technical']
    assert not b['issue_summary']['by_category']['scientific']
    actual=json.loads((tmp_path/b['path']).read_text())
    assert actual['receipts']==[] and actual['report']=={'references':[],'passages':[]}
    assert any('capacity failure' in x for x in actual['blockers'])


def test_pure_protocol_does_not_consume_future_round_old_records_unchanged(tmp_path):
    base=tmp_path/'reviews/unified/p';base.mkdir(parents=True)
    old={'target_journal':'J','stage_reached':'decision','round_for_target':1}
    tech=old|{'consumes_scientific_round':False,'round_for_target':1}
    mixed=old|{'consumes_scientific_round':True,'round_for_target':2}
    for i,record in enumerate([old,tech,mixed]):
        p=base/str(i);p.mkdir();(p/'decision.json').write_text(json.dumps(record))
    assert len(flow.completed_rounds(tmp_path,'p','J'))==3
    assert len(flow.scientific_rounds(tmp_path,'p','J'))==2
    assert json.loads((base/'0/decision.json').read_text())==old
    summary={'by_category':{'scientific':[],'technical':['wrong quote'],'source_routing':[],'preparation':[]}}
    merged=flow.merge({'decision':'send_to_review'}, {},formal_blockers=['wrong quote'],formal_summary=summary)
    assert merged['outcome']=='formal_check_blocked' and merged['scientific_blockers']==[]
    assert merged['technical_blockers']==['wrong quote']


@pytest.mark.parametrize('scientific', [False,True])
def test_official_pipeline_counts_mixed_but_not_pure_technical(tmp_path,monkeypatch,scientific):
    config={'process':flow.PROCESS,'roles':{'editor':ROLE,'referee_b':ROLE},
            'referee_roles':['referee_b'],'timeout_seconds':1,'max_rounds_per_target':15,
            'rejection_clearance_required':True}
    monkeypatch.setattr(flow,'review_config',lambda root:config)
    monkeypatch.setattr(flow,'preflight',lambda *args:{'metadata':{'paper_id':'p','version':'1','target_journal':'J'},
        'target':'J','blockers':[],'fingerprints':{},'expanded':'ordinary statement','bibliography':''})
    monkeypatch.setattr(flow,'prior_decisions',lambda *args:[])
    summary={'by_category':{'scientific':['genuine unresolved hypothesis'] if scientific else [],
                          'technical':['quote mismatch'],'source_routing':[],'preparation':[]}}
    monkeypatch.setattr(f,'run_checks',lambda *args:{'valid':False,'blockers':['actual raw negative'],
                                                   'issue_summary':summary})
    calls=[]
    def role(**kw):
        calls.append(kw['role_name'])
        if kw['role_name']=='editor':return {'decision':'send_to_review','desk_reject_category':'none'},{}
        if kw['role_name']=='decision_letter':return {'letter':'actual fixture decision'},{}
        raise AssertionError('A blocked formal check must never start the referee')
    monkeypatch.setattr(flow,'run_role',role)
    record=flow.run_review('p',root=tmp_path,apply=False)
    assert record['stage_reached']=='decision' and record['merged']['outcome']=='formal_check_blocked'
    assert record['consumes_scientific_round'] is scientific
    assert record['round_for_target']==int(scientific)
    assert calls==['editor','decision_letter']
    assert len(flow.scientific_rounds(tmp_path,'p','J'))==int(scientific)
