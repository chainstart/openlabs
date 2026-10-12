"""User-scoped correctness gate without an all-prose evidence replay."""
import json

from paper_writing import formal_checks as f, review_flow as flow
from test_formal_checks import fixture_workspace, mock_http, ROLE, simulated_runner


def test_named_statements_proofs_displays_retained_preamble_and_prose_excluded():
    text = r'''\newtheorem{claim}{Claim}
\newcommand{\unused}{\[a=b\]}
\begin{document}

Funding was absent. Sample processing used a fixed seed. Let $x$ be a label.

\begin{claim}
A real square is nonnegative.

For real $x$, $x^2\ge0$.
\end{claim}

\begin{proof}
The two factors have the same sign.

Consequently the product is nonnegative.
\end{proof}

The defining equation is \[y=x^2.\]

\end{document}'''
    inv = f.verification_inventory([{'id': 'main', 'text': text}], r'\bibitem{a}Work A.')
    joined = '\n'.join(p['text'] for p in inv['passages'])
    assert 'A real square' in joined and 'two factors' in joined and 'Consequently' in joined
    assert 'y=x^2' in joined and 'unused' not in joined and 'Funding' not in joined
    assert inv['scope']['core_passage_count'] < inv['scope']['full_passage_count']
    assert all(formula['text'] != '$x$' for p in inv['passages'] for formula in p['formulas'])
    assert [r['key'] for r in inv['references']] == ['a']


def test_supplement_theorem_cannot_be_hidden_by_prose_only_main():
    inv = f.verification_inventory([{'id': 'main', 'text': 'Ordinary prose.'},
        {'id': 'supplement', 'text': r'\begin{lemma}A necessary result.\end{lemma}'}], '')
    assert len(inv['passages']) == 1 and inv['passages'][0]['document'] == 'supplement'


def test_metadata_only_gate_does_not_fetch_original_or_replay_records(tmp_path, monkeypatch):
    m = fixture_workspace(tmp_path)
    m['formal_check']['local_evidence'] = [{'path': 'papers/p/missing-replay.json',
        'sha256': '0'*64, 'kind': 'execution_record', 'passage_patterns': ['Old selector']}]
    mock_http(monkeypatch)
    run = tmp_path/'review'; run.mkdir()
    binding = f.run_checks({'metadata': m}, tmp_path, run, ROLE, 1, simulated_runner)
    assert binding['valid'] and f.validate_binding(binding, m, tmp_path, ROLE) == []
    result = json.loads((tmp_path/binding['path']).read_text())
    assert all(s['kind'] == 'bibliographic_metadata' for s in result['sources'])
    assert result['artifact_inventory'] == {}
    assert result['inventory']['scope']['name'] == 'all_references_and_core_mathematics'


def test_metadata_reference_evidence_does_not_require_literal_quote(tmp_path, monkeypatch):
    m = fixture_workspace(tmp_path); mock_http(monkeypatch)
    run = tmp_path/'review'; run.mkdir()
    binding = f.run_checks({'metadata':m}, tmp_path, run, ROLE, 1, simulated_runner)
    result = json.loads((tmp_path/binding['path']).read_text())
    result['report']['references'][0]['evidence'][0]['quote'] = ''
    assert not f.report_blockers(result['report'], result['inventory'], result['sources'])
    result['report']['references'][0]['evidence'][0]['source_id'] = 'invented'
    assert f.report_blockers(result['report'], result['inventory'], result['sources'])


def test_formal_failure_cannot_hide_completed_scientific_objection():
    report = {'recommendation':'major_revision', 'scientific_blockers':['Main proof has a counterexample'],
        'required_changes':[{'change':'Fix proof', 'type':'evidence', 'location':'Theorem 1'}],
        'previous_items':[{'item':'Old proof gap', 'resolved':False, 'evidence':'Still missing'}]}
    merged = flow.merge({'decision':'send_to_review'}, {'referee_b':report},
        formal_blockers=['Malformed ID'], formal_summary={'by_category':{'scientific':[], 'technical':['Malformed ID']}})
    assert 'Main proof has a counterexample' in merged['scientific_blockers']
    assert merged['required_changes'] and merged['unresolved_previous_items']


def test_scientific_rejection_does_not_spend_more_formal_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(flow,'review_config',lambda root:{'process':flow.PROCESS,
        'roles':{'editor':ROLE,'referee_b':ROLE},'referee_roles':['referee_b'],
        'timeout_seconds':1,'max_rounds_per_target':15,'rejection_clearance_required':True})
    monkeypatch.setattr(flow,'preflight',lambda *args:{'metadata':{'paper_id':'p','version':'1','target_journal':'J'},
        'target':'J','blockers':[],'fingerprints':{},'expanded':'Main result','bibliography':''})
    calls=[]
    def role(**kw):
        calls.append(kw['role_name'])
        if kw['role_name']=='editor': return {'decision':'send_to_review'},{}
        if kw['role_name']=='decision_letter': return {'letter':'Actual fixture letter'},{}
        return {'recommendation':'reject','scientific_blockers':['Core result already known'],
            'required_changes':[],'previous_items':[],
            'formal_check_assessment':{'coverage_complete':True,'omissions_or_errors':[]}},{}
    monkeypatch.setattr(flow,'run_role',role)
    monkeypatch.setattr(f,'run_checks',lambda *args: (_ for _ in ()).throw(AssertionError('No formal calls after scientific rejection')))
    record=flow.run_review('p',root=tmp_path,apply=False)
    assert calls==['editor','referee_b','decision_letter']
    assert record['merged']['outcome']=='revision_required' and 'formal_check' not in record
