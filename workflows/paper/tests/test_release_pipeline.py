"""Release pipeline support on the paper side: delivery issues, release status, delta-only review."""

from __future__ import annotations

import json
import subprocess

import pytest

from paper_writing import release_pipeline as rp
from paper_writing import review_flow as flow
from test_review_flow import FORMAL_STYLE_PROBLEMS, FORMAL_SUPPORT_PROBLEMS, MANUSCRIPT, _delta_fixture


def _stub_audits(monkeypatch, style_errors, support_errors, abstract=()):
    from paper_writing import editorial_rewrite, manuscript_style, registry, support_citations

    monkeypatch.setattr(registry, 'load_registry_settings', lambda *args, **kwargs: {})
    monkeypatch.setattr(manuscript_style, 'audit_manuscript_style', lambda *args, **kwargs: {
        'errors': style_errors,
        'blacklist_findings': [{'code': 'STYLE-INTERNAL-AUDIT', 'message': 'internal vocabulary'}]})
    monkeypatch.setattr(support_citations, 'audit_manuscript_support',
                        lambda *args, **kwargs: {'errors': support_errors})
    monkeypatch.setattr(editorial_rewrite, 'abstract_findings', lambda *args: list(abstract))


def test_delivery_issues_carry_codes_and_the_unchanged_blocker_text(tmp_path, monkeypatch):
    manuscript = tmp_path / 'papers/p/manuscript'
    manuscript.mkdir(parents=True)
    (manuscript / 'main.tex').write_text('x')
    (manuscript / 'leftover.tex').write_text('not read by the build')
    _stub_audits(monkeypatch, FORMAL_STYLE_PROBLEMS, FORMAL_SUPPORT_PROBLEMS, ['abstract has 300 words'])
    record = {'build_inputs': ['main.tex']}
    items = flow.delivery_issues('p', {'paper_id': 'p'}, tmp_path, record, notes=[])
    assert [i['text'] for i in items] == flow.delivery_blockers('p', {'paper_id': 'p'}, tmp_path, record)
    codes = {i['code'] for i in items}
    assert {'STYLE-UNRESOLVED-MARKER', 'SUPPORT-DOI-MISSING', 'ABSTRACT-VENUE-FORMAT',
            'UNUSED-SOURCE-FILES'} <= codes
    assert next(i for i in items if i['code'] == 'UNUSED-SOURCE-FILES')['files'] == ['leftover.tex']
    assert 'STYLE-INTERNAL-AUDIT' not in codes  # a note, never a blocker


def _git_repo(root):
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    for key, value in (('user.name', 'Test'), ('user.email', 'test@example.invalid')):
        subprocess.run(['git', '-C', str(root), 'config', key, value], check=True)


def _status_fixture(tmp_path, monkeypatch, *, publication, release=None, settings=None,
                    style=(), support=()):
    _git_repo(tmp_path)
    (tmp_path / 'registry/papers').mkdir(parents=True)
    (tmp_path / 'registry/papers/p.yaml').write_text('paper_id: p\n')
    (tmp_path / 'papers/p/manuscript').mkdir(parents=True)
    (tmp_path / 'papers/p/manuscript/main.tex').write_text('x')
    (tmp_path / 'other.txt').write_text('unrelated')
    subprocess.run(['git', '-C', str(tmp_path), 'add', '-A'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), 'commit', '-qm', 'base'], check=True)
    metadata = {'paper_id': 'p', 'version': '1.2.0', 'title': 'T',
                'manuscript_dir': 'papers/p/manuscript', 'support': {'publication': publication},
                'writing_release': release or {'status': 'ready', 'review_process': 'unified_v1'}}
    monkeypatch.setattr(rp, 'load_paper_metadata', lambda *args, **kwargs: metadata)
    monkeypatch.setattr(rp, 'load_registry_settings', lambda *args, **kwargs: settings or {
        'support_publication': {'default_mode': 'zenodo_only', 'zenodo_environment': 'production',
                                'standing_production_release_authorization': True}})
    monkeypatch.setattr(rp, '_review_status', lambda *args: {'ready': True, 'current': True, 'problems': []})
    issues = [{'source': 'manuscript_style', 'code': c, 'location': '', 'message': c, 'text': c} for c in style]
    issues += [{'source': 'support_citations', 'code': c, 'location': '', 'message': c, 'text': c} for c in support]
    monkeypatch.setattr(flow, 'delivery_issues', lambda *args, **kwargs: list(issues))
    return metadata


def test_release_status_classifies_remedies_and_reads_the_standing_authorization(tmp_path, monkeypatch):
    _status_fixture(tmp_path, monkeypatch, publication={'status': 'planned'},
                    style=['STYLE-UNRESOLVED-MARKER'], support=['SUPPORT-RECEIPT-DOI', 'SUPPORT-BIB-DOI'])
    status = rp.release_status('p', root=tmp_path)
    remedies = {i['code']: i['remedy'] for i in status['issues']}
    assert remedies == {'STYLE-UNRESOLVED-MARKER': 'writer', 'SUPPORT-RECEIPT-DOI': 'zenodo_prepare',
                        'SUPPORT-BIB-DOI': 'writer'}
    support = status['support']
    assert support['prepare_needed'] and not support['release_needed']
    assert support['standing_production_release_authorization'] is True
    assert status['git']['clean'] and status['delivered'] is False
    assert 'retained-sources' in status['writer_scope'] and 'papers/p/' in status['writer_scope']


def test_release_status_lists_only_paper_paths_and_their_changes(tmp_path, monkeypatch):
    _status_fixture(tmp_path, monkeypatch, publication={'status': 'draft', 'environment': 'production'})
    (tmp_path / 'papers/p/manuscript/main.tex').write_text('changed')
    (tmp_path / 'other.txt').write_text('unrelated change')
    status = rp.release_status('p', root=tmp_path)
    assert status['commit_paths'] == ['registry/papers/p.yaml', 'papers/p', 'reviews/unified/p',
                                      'reviews/formal-check/p']
    assert status['git']['dirty'] == [' M papers/p/manuscript/main.tex']
    # A draft package that is not registered must be prepared again.
    assert status['support']['release_needed'] and status['support']['prepare_needed']


def test_published_support_problems_need_a_human_and_not_required_needs_nothing(tmp_path, monkeypatch):
    metadata = _status_fixture(tmp_path, monkeypatch, publication={'status': 'published'},
                               support=['SUPPORT-PACKAGE-VERSION'])
    status = rp.release_status('p', root=tmp_path)
    assert status['issues'][0]['remedy'] == 'human'
    assert not status['support']['prepare_needed'] and not status['support']['release_needed']
    metadata['support']['publication'] = {'mode': 'not_required', 'not_required_reason': 'no data'}
    assert rp.release_status('p', root=tmp_path)['support']['required'] is False
    metadata['delivery'] = {'package_id': 'pkg', 'version': '1.2.0'}
    assert rp.release_status('p', root=tmp_path)['delivered'] is True


def test_delta_only_reports_a_full_review_without_starting_a_model(tmp_path, monkeypatch):
    calls = _delta_fixture(tmp_path, monkeypatch, MANUSCRIPT.replace('120 counties', '118 counties'))
    record = flow.run_review('p', root=tmp_path, apply=True, delta_only=True)
    assert calls == []
    assert record['merged']['outcome'] == 'full_review_required'
    assert any('numbers changed' in r for r in record['merged']['full_review_reasons'])
    assert record['stage_reached'] == 'delta_check' and record['consumes_scientific_round'] is False
    # The refusal is kept but is not a scientific round and does not hide the ready basis.
    assert len(flow.scientific_rounds(tmp_path, 'p', 'J')) == 1


def test_delta_only_runs_the_delta_review_for_a_citation_change(tmp_path, monkeypatch):
    doi = r'Data are available at \url{https://doi.org/10.5281/zenodo.17000001}.'
    calls = _delta_fixture(tmp_path, monkeypatch, MANUSCRIPT.replace(
        'The estimator follows a standard design.', 'The estimator follows a standard design. ' + doi))
    monkeypatch.setattr(flow.formal_checks, 'run_checks', lambda *args: {'valid': True, 'blockers': []})
    record = flow.run_review('p', root=tmp_path, apply=False, delta_only=True)
    assert calls == [] and record['review_mode'] == 'delta'
    assert record['merged']['outcome'] == 'ready' and record['consumes_scientific_round'] is False


@pytest.mark.parametrize('replacement,eligible', [
    (r'\url{https://doi.org/10.5281/zenodo.17000001}', True),
    ('doi:10.5281/zenodo.17000001', False),  # bare DOI digits count as new numbers
])
def test_doi_wording_decides_whether_the_delta_rule_applies(replacement, eligible):
    new = MANUSCRIPT.replace('The estimator follows a standard design.',
                             'The estimator follows a standard design. Code: ' + replacement + '.')
    assert flow.substantive_delta(MANUSCRIPT, new)['substantive_unchanged'] is eligible


def test_release_status_cli_prints_one_json_object(tmp_path, monkeypatch, capsys):
    from paper_writing.__main__ import main

    monkeypatch.setattr(rp, 'release_status', lambda paper_id, root: {'paper_id': paper_id, 'issues': []})
    assert main(['program', 'release-status', '--paper-id', 'p', '--root', str(tmp_path), '--json']) == 0
    assert json.loads(capsys.readouterr().out) == {'paper_id': 'p', 'issues': []}
