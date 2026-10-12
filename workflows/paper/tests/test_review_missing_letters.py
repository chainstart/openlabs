"""Actual-user scoped missing originals do not excuse bad evidence or science."""
import copy
import hashlib
import json

import pytest

from paper_writing import review_flow as flow
from paper_writing.review_launcher import _validate_against_schema


def mock_formal_stage(monkeypatch):
    # Isolate rejection-history tests; actual formal coverage has its own suite.
    monkeypatch.setattr(flow.formal_checks, 'run_checks', lambda *a: {'valid': True, 'blockers': []})
    monkeypatch.setattr(flow.formal_checks, 'validate_binding', lambda *a: [])
    monkeypatch.setattr(flow.formal_checks, 'packet', lambda *a: 'Isolated formal fixture')


def setup_policy(tmp_path, monkeypatch, missing=True):
    monkeypatch.delenv('ARA_PAPER_MANAGE_API_URL', raising=False)
    decisions = [{'journal': 'J', 'manuscript_number': '1', 'rejected_at': '2026-01-01'}]
    identity = hashlib.sha256(json.dumps(['J', '1'], ensure_ascii=False).encode()).hexdigest()[:20]
    ids = [identity] if missing else []
    summary = 'Missing originals alone do not block normal review; available letters and science remain binding.'
    grant = {'mode': 'available_originals_only', 'paper_ids': ['p'], 'authorization': summary,
             'decision_scope': [{'paper_id': 'p', 'missing_decision_ids': ids}]}
    receipt = tmp_path / 'authorization.json'
    receipt.write_text(json.dumps({'schema': 'openlabs.actual_author_instruction.v1',
        'source': 'actual user message in this session', 'user_text': 'Continue normal review despite missing letters.',
        'missing_original_letters': grant}))
    policy = {'paper_id': 'p', 'mode': 'available_originals_only', 'missing_decision_ids': ids,
              'authorization': {'path': 'authorization.json', 'sha256': flow._sha256(receipt.read_bytes()),
                  'json_pointer': '/missing_original_letters', 'summary': summary}}
    return {'paper_id': 'p', 'journal_rejections': decisions,
            'missing_rejection_letter_policy': policy}, identity


def addressed(identity, judgment='not_assessable', answered=False):
    return {'decision_id': identity, 'journal': 'J', 'judgment': judgment,
            'answered': answered, 'concern': 'Original unavailable; concern cannot be determined.',
            'evidence': 'Actual scoped policy; no original text has been recovered.'}


def test_missing_letter_default_blocks_but_scoped_unknown_can_proceed(tmp_path, monkeypatch):
    meta, identity = setup_policy(tmp_path, monkeypatch)
    policy = flow.rejection_history_policy(meta, tmp_path, 'p')
    decisions = flow.prior_decisions('p', meta, tmp_path)
    ed = {'prior_rejections_addressed': [addressed(identity)]}
    assert flow.rejection_clearance_blockers(ed, decisions)
    assert flow.rejection_clearance_blockers(ed, decisions, policy) == []
    assert decisions[0]['letter_available'] is False and decisions[0]['letter_text'] == ''


@pytest.mark.parametrize('judgment,answered', [('resolved', True), ('compatible', False),
                                             ('unverifiable', False), ('not_assessable', True)])
def test_authorization_never_fabricates_recovery_or_compatibility(tmp_path, monkeypatch, judgment, answered):
    meta, identity = setup_policy(tmp_path, monkeypatch)
    ed = {'prior_rejections_addressed': [addressed(identity, judgment, answered)]}
    assert flow.rejection_clearance_blockers(ed, flow.prior_decisions('p', meta, tmp_path),
                                            flow.rejection_history_policy(meta, tmp_path))


@pytest.mark.parametrize('damage', ['digest', 'missing', 'wrong_decision', 'empty_text', 'symlink'])
def test_corrupt_registered_letter_binding_is_not_an_authorized_absence(tmp_path, monkeypatch, damage):
    meta, _ = setup_policy(tmp_path, monkeypatch)
    path = tmp_path / 'letter.txt'; path.write_text('Real editor: Lemma 2 is unproved.')
    b = {'journal': 'J', 'manuscript_number': '1', 'path': 'letter.txt',
         'sha256': flow._sha256(path.read_bytes()), 'kind': 'verbatim_decision_letter'}
    meta['journal_rejection_letters'] = [b]
    if damage == 'digest':
        b['sha256'] = '0' * 64
    elif damage == 'missing':
        path.unlink()
    elif damage == 'wrong_decision':
        b['journal'] = 'Other journal'
    elif damage == 'empty_text':
        path.write_text(' '); b['sha256'] = flow._sha256(path.read_bytes())
    else:
        other = tmp_path / 'original.txt'; path.rename(other); path.symlink_to(other)
    with pytest.raises(ValueError):
        flow.prior_decisions('p', meta, tmp_path)


def test_available_unresolved_letter_and_scientific_gap_still_block(tmp_path, monkeypatch):
    meta, identity = setup_policy(tmp_path, monkeypatch)
    path = tmp_path / 'letter.json'; path.write_text(json.dumps({'body': 'Proof of Lemma 2 absent.'}))
    meta['journal_rejections'][0]['source'] = 'letter.json'
    decisions = flow.prior_decisions('p', meta, tmp_path)
    policy = flow.rejection_history_policy(meta, tmp_path)
    ed = {'decision': 'send_to_review', 'prior_rejections_addressed': [addressed(identity, 'unresolved')]}
    blockers = flow.rejection_clearance_blockers(ed, decisions, policy)
    assert blockers and flow.merge(ed, {}, blockers)['outcome'] == 'rejection_history_blocked'
    ed['prior_rejections_addressed'] = [addressed(identity, 'compatible')]
    assert flow.rejection_clearance_blockers(ed, decisions, policy) == []
    ref = {'recommendation': 'accept', 'scientific_blockers': ['Current proof gap'],
           'required_changes': [], 'previous_items': []}
    assert flow.merge(ed, {'referee_b': ref})['outcome'] == 'revision_required'


@pytest.mark.parametrize('damage', ['paper', 'scope', 'receipt_sha', 'summary', 'pointer', 'grant_mode'])
def test_exact_user_receipt_and_decision_scope_are_required(tmp_path, monkeypatch, damage):
    meta, _ = setup_policy(tmp_path, monkeypatch)
    p = meta['missing_rejection_letter_policy']; a = p['authorization']
    if damage == 'paper':
        meta['paper_id'] = 'unrelated'
    elif damage == 'scope':
        p['missing_decision_ids'] = []
    elif damage == 'receipt_sha':
        a['sha256'] = '0' * 64
    elif damage == 'summary':
        a['summary'] = 'Waive science too.'
    elif damage == 'pointer':
        a['json_pointer'] = '/nonexistent'
    else:
        r = tmp_path / a['path']; obj = json.loads(r.read_text())
        obj['missing_original_letters']['mode'] = 'waive_all'; r.write_text(json.dumps(obj))
        a['sha256'] = flow._sha256(r.read_bytes())
    with pytest.raises(ValueError):
        flow.rejection_history_policy(meta, tmp_path)


def test_empty_missing_scope_is_valid_but_cannot_waive_a_new_missing_decision(tmp_path, monkeypatch):
    meta, identity = setup_policy(tmp_path, monkeypatch, missing=False)
    policy = flow.rejection_history_policy(meta, tmp_path)
    assert policy['missing_decision_ids'] == []
    assert flow.rejection_clearance_blockers({'prior_rejections_addressed': [addressed(identity)]},
                                            flow.prior_decisions('p', meta, tmp_path), policy)


def test_mandatory_formal_policy_and_scoped_history_are_hash_bound(tmp_path, monkeypatch):
    meta, _ = setup_policy(tmp_path, monkeypatch)
    config = {'process': flow.PROCESS, 'roles': {}, 'referee_roles': ['referee_b'],
              'rejection_clearance_required': True}
    expected = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    assert flow.review_policy_sha256(config) != expected
    assert flow.review_policy_sha256(config) == hashlib.sha256(json.dumps(dict(config,
        formal_check=flow.formal_checks.policy(),
        stage_order='editor_scientific_referee_core_verification_decision'), sort_keys=True).encode()).hexdigest()
    assert flow.rejection_history_policy({}, tmp_path, 'other') is None
    policy = flow.rejection_history_policy(meta, tmp_path)
    assert flow.review_policy_sha256(config, policy) != expected
    changed = copy.deepcopy(policy); changed['authorization']['sha256'] = '0' * 64
    assert flow.review_policy_sha256(config, changed) != flow.review_policy_sha256(config, policy)


def test_original_recovered_after_unknown_screen_requires_fresh_assessment(tmp_path, monkeypatch):
    meta, _ = setup_policy(tmp_path, monkeypatch)
    policy = flow.rejection_history_policy(meta, tmp_path)
    bound = flow.prior_decisions('p', meta, tmp_path)
    record = {'paper_id': 'p', 'prior_decisions': bound, 'missing_rejection_letter_policy': policy}
    assert flow.rejection_context_blockers(record, meta, tmp_path) == []
    (tmp_path / 'letter.json').write_text(json.dumps({'body': 'Actually unresolved scientific concern.'}))
    meta['journal_rejections'][0]['source'] = 'letter.json'
    assert flow.rejection_context_blockers(record, meta, tmp_path)


def test_ready_release_rechecks_exact_scoped_policy_and_authorization(tmp_path, monkeypatch):
    mock_formal_stage(monkeypatch)
    meta, identity = setup_policy(tmp_path, monkeypatch)
    meta['target_journal'] = 'K'
    config = {'process': flow.PROCESS, 'roles': {}, 'referee_roles': ['referee_b'],
              'rejection_clearance_required': True}
    monkeypatch.setattr(flow, 'review_config', lambda root: config)
    policy = flow.rejection_history_policy(meta, tmp_path)
    record = {'paper_id': 'p', 'merged': {'outcome': 'ready'}, 'target_journal': 'K',
        'editor_screen': {'decision': 'send_to_review', 'prior_rejections_addressed': [addressed(identity)]},
        'referee_reports': {'referee_b': {'recommendation': 'accept', 'scientific_blockers': [], 'required_changes': [], 'previous_items': [], 'formal_check_assessment': {'coverage_complete': True, 'omissions_or_errors': []}}}, 'prior_decisions': flow.prior_decisions('p', meta, tmp_path),
        'fingerprints': {'manuscript_snapshot_sha256': 'a' * 64},
        'missing_rejection_letter_policy': policy, 'review_policy_sha256': flow.review_policy_sha256(config, policy)}
    p = tmp_path / 'decision.json'; p.write_text(json.dumps(record))
    meta['writing_release'] = {'review_process': flow.PROCESS, 'decision_record': 'decision.json',
                              'decision_record_sha256': flow._sha256(p.read_bytes())}
    assert flow.validate_unified_release('p', meta, tmp_path, 'a' * 64) == []
    strict = copy.deepcopy(meta); strict.pop('missing_rejection_letter_policy')
    assert flow.validate_unified_release('p', strict, tmp_path, 'a' * 64)
    (tmp_path / 'authorization.json').write_text('Changed instruction')
    assert flow.validate_unified_release('p', meta, tmp_path, 'a' * 64)


def test_new_portal_decision_invalidates_old_scoped_release(tmp_path, monkeypatch):
    meta, _ = setup_policy(tmp_path, monkeypatch)
    bound = flow.prior_decisions('p', meta, tmp_path)
    record = {'paper_id': 'p', 'prior_decisions': bound,
              'missing_rejection_letter_policy': flow.rejection_history_policy(meta, tmp_path)}
    extra = dict(bound[0], decision_id='f' * 20, journal='New journal')
    monkeypatch.setattr(flow, 'prior_decisions', lambda *args: bound + [extra])
    assert 'Current rejection decision scope changed after review' in flow.rejection_context_blockers(record, meta, tmp_path)


def test_apply_never_reuses_strict_decision_for_new_scoped_policy(tmp_path, monkeypatch):
    meta, _ = setup_policy(tmp_path, monkeypatch)
    config = {'process': flow.PROCESS, 'roles': {}, 'referee_roles': ['referee_b'],
              'rejection_clearance_required': True}
    monkeypatch.setattr(flow, 'review_config', lambda root: config)
    monkeypatch.setattr(flow, 'load_paper_metadata', lambda *args: meta)
    written = []
    monkeypatch.setattr(flow, 'write_paper_metadata', lambda *args: written.append(args))
    path = tmp_path / 'strict.json'; path.write_text(json.dumps({'review_policy_sha256': flow.review_policy_sha256(config)}))
    with pytest.raises(ValueError, match='Review policy changed'):
        flow.apply_decision('p', root=tmp_path, decision_path=path, digest=flow._sha256(path.read_bytes()))
    assert written == []


def test_apply_current_scoped_ready_preserves_unknown_letter_and_binding(tmp_path, monkeypatch):
    from paper_writing import operations

    mock_formal_stage(monkeypatch)
    meta, identity = setup_policy(tmp_path, monkeypatch)
    config = {'process': flow.PROCESS, 'roles': {}, 'referee_roles': ['referee_b'],
              'rejection_clearance_required': True, 'max_rounds_per_target': 15}
    monkeypatch.setattr(flow, 'review_config', lambda root: config)
    monkeypatch.setattr(flow, 'load_paper_metadata', lambda *args: meta)
    fingerprints = {'manuscript_snapshot_sha256': 'a' * 64}
    monkeypatch.setattr(operations, '_review_workspace_fingerprints', lambda *args: fingerprints)
    written = []
    monkeypatch.setattr(flow, 'write_paper_metadata', lambda *args: written.append(copy.deepcopy(args[1])))
    policy = flow.rejection_history_policy(meta, tmp_path)
    editor = {'decision': 'send_to_review', 'prior_rejections_addressed': [addressed(identity)]}
    referee = {'recommendation': 'minor_revision', 'scientific_blockers': [], 'required_changes': [],
               'previous_items': [], 'scores': {'overall': 6}, 'formal_check_assessment': {'coverage_complete': True, 'omissions_or_errors': []}}
    record = {'paper_id': 'p', 'target_journal': 'K', 'manuscript_version': '1.0',
              'finished_at': '2026-01-01T00:00:00Z', 'round_for_target': 1,
              'review_policy_sha256': flow.review_policy_sha256(config, policy),
              'missing_rejection_letter_policy': policy, 'prior_decisions': flow.prior_decisions('p', meta, tmp_path),
              'editor_screen': editor, 'referee_reports': {'referee_b': referee},
              'merged': flow.merge(editor, {'referee_b': referee}), 'fingerprints': fingerprints}
    path = tmp_path / 'decision.json'; path.write_text(json.dumps(record))
    digest = flow._sha256(path.read_bytes())
    release = flow.apply_decision('p', root=tmp_path, decision_path=path, digest=digest)
    assert release['status'] == 'ready' and release['decision_record_sha256'] == digest
    assert written[0]['missing_rejection_letter_policy'] == policy
    assert json.loads(path.read_text())['editor_screen']['prior_rejections_addressed'][0]['judgment'] == 'not_assessable'
    assert json.loads(path.read_text())['prior_decisions'][0]['letter_available'] is False


@pytest.mark.parametrize('old_science_resolved', [True, False])
def test_both_fresh_roles_receive_complete_available_letters_policy_and_previous_items(tmp_path, monkeypatch,
                                                                                      old_science_resolved):
    mock_formal_stage(monkeypatch)
    meta, identity = setup_policy(tmp_path, monkeypatch)
    meta.update(version='1.0', target_journal='K')
    (tmp_path / 'present.json').write_text(json.dumps({'body': 'Authentic original: contribution too narrow.'}))
    meta['journal_rejections'].append({'journal': 'K', 'manuscript_number': '2',
                                      'source': 'present.json', 'rejected_at': '2026-01-02'})
    config = {'process': flow.PROCESS, 'roles': {'editor': {'provider': 'openai-codex'},
              'referee_b': {'provider': 'openai-codex'}}, 'referee_roles': ['referee_b'],
              'rejection_clearance_required': True, 'timeout_seconds': 1, 'max_rounds_per_target': 15}
    monkeypatch.setattr(flow, 'review_config', lambda root: config)
    pre = {'metadata': meta, 'expanded': 'Current source', 'bibliography': '', 'target': 'K',
           'fingerprints': {}, 'blockers': []}
    monkeypatch.setattr(flow, 'preflight', lambda *args: pre)
    old = tmp_path / 'reviews/unified/p/20260101T000000Z'; old.mkdir(parents=True)
    missing = 'Original rejection letter unavailable: J 1'
    science = 'Proof of current Lemma 2 missing'
    (old / 'manuscript-expanded.tex').write_text('Old source')
    (old / 'decision.json').write_text(json.dumps({'stage_reached': 'decision', 'target_journal': 'K',
        'letter': 'Earlier requests', 'merged': {'scientific_blockers': [missing, science], 'required_changes': []}}))
    response = tmp_path / 'response.md'; response.write_text('User instruction changes missing-original requirement; proof supplied.')
    calls = []
    def role(**kw):
        name = kw['role_name']; calls.append(name)
        if name in ('editor', 'referee_b'):
            packet = kw['user_prompt']
            assert identity in packet and 'available_originals_only' in packet
            assert 'Authentic original: contribution too narrow.' in packet
            assert 'not_assessable' in packet and 'unknown' in packet
        if name == 'editor':
            rows = flow.prior_decisions('p', meta, tmp_path)
            reports = [addressed(identity)] + [{'decision_id': r['decision_id'], 'journal': 'K',
                'concern': 'Narrow contribution', 'answered': False, 'judgment': 'compatible',
                'evidence': 'Current stronger result and matched target comparison Section 1.'}
                for r in rows if r['decision_id'] != identity]
            result = {'decision': 'send_to_review', 'prior_rejections_addressed': reports}
            assert 'not_assessable' in kw['schema']['properties']['prior_rejections_addressed']['items']['properties']['judgment']['enum']
            return result, {}
        if name == 'decision_letter':
            return {'letter': 'Internal simulated decision, not external acceptance'}, {}
        assert missing in kw['user_prompt'] and science in kw['user_prompt']
        previous = [{'item': missing, 'resolved': True, 'evidence': 'No longer required by explicit scoped policy; letter remains unknown.'},
                    {'item': science, 'resolved': old_science_resolved, 'evidence': 'Independent current proof assessment.'}]
        _validate_against_schema(previous, kw['schema']['properties']['previous_items'])
        return {'recommendation': 'minor_revision', 'scientific_blockers': [], 'required_changes': [],
                'previous_items': previous, 'scores': {'overall': 6}, 'formal_check_assessment': {'coverage_complete': True, 'omissions_or_errors': []}}, {}
    monkeypatch.setattr(flow, 'run_role', role)
    result = flow.run_review('p', root=tmp_path, response_letter=response, apply=False)
    assert calls == ['editor', 'referee_b', 'decision_letter']
    assert result['merged']['outcome'] == ('ready' if old_science_resolved else 'revision_required')
    assert result['previous_required_items'] == [missing, science]
    assert json.loads((old / 'decision.json').read_text())['merged']['scientific_blockers'] == [missing, science]
    assert result['missing_rejection_letter_policy'] == flow.rejection_history_policy(meta, tmp_path)


def test_scoped_next_round_keeps_exact_unresolved_prerequisites_for_fresh_assessment(tmp_path, monkeypatch):
    old = tmp_path / 'old'; old.mkdir()
    (old / 'manuscript-expanded.tex').write_text('Old source')
    missing = 'Previous rejection not overcome or compatible: ' + 'a' * 20
    proof = '[evidence] Missing uniform proof (Theorem 2)'
    record = {'_path': old / 'decision.json', 'stage_reached': 'decision', 'letter': 'Actual previous letter',
              'merged': {'scientific_blockers': [], 'required_changes': [],
                         'unresolved_previous_items': [{'item': missing, 'resolved': False},
                                                       {'item': proof, 'resolved': False}]}}
    monkeypatch.setattr(flow, 'completed_rounds', lambda *args: [record])
    # Default callers retain their existing packet shape and fingerprint.
    assert flow._previous_round(tmp_path, 'p', 'J', 'Current source', 'Response')['items'] == []
    previous = flow._previous_round(tmp_path, 'p', 'J', 'Current source', 'Response', {'mode': 'available_originals_only'})
    assert previous['items'] == [missing, proof]
    schema = flow.referee_schema_for_previous(previous)
    assert schema['properties']['previous_items']['items']['properties']['item']['enum'] == [missing, proof]
    assert record['merged']['unresolved_previous_items'][0]['resolved'] is False


def test_scoped_resolution_distinguishes_unknown_letter_from_superseded_requirement():
    packet = flow._history_policy_packet({'history_policy': {'mode': 'available_originals_only'}})
    assert 'prior requirement' in packet and 'overcome or compatible' in packet
    assert 'historical assessment remains not_assessable and answered=false' in packet
    assert 'Do not remove combined scientific or available-letter concerns' in packet
    editor = {'decision': 'send_to_review'}
    report = {'recommendation': 'minor_revision', 'scientific_blockers': [], 'required_changes': [],
              'previous_items': [{'item': 'Unknown original prerequisite', 'resolved': False,
                                  'evidence': 'Independent referee has not closed the prerequisite.'}]}
    assert flow.merge(editor, {'referee_b': report})['outcome'] == 'revision_required'
    report['previous_items'][0].update(resolved=True, evidence='Independent referee finds the prerequisite no longer applicable; original remains unknown.')
    assert flow.merge(editor, {'referee_b': report})['unresolved_previous_items'] == []
