from copy import deepcopy
import hashlib
import pytest
from paper_writing import editorial_closeout as e


def test_no_implicit_release_exception(tmp_path):
    assert e.validate_release('paper', {}, tmp_path) == []


def test_only_wrappers_are_eligible():
    old = {'main.tex': b'old wrapper', 'proof.tex': b'unchanged proof'}
    new = {**old, 'main.tex': b'new wrapper'}
    assert [r['path'] for r in e.check_scope(old, new, {})] == ['main.tex']
    with pytest.raises(ValueError, match='scientific source'):
        e.check_scope(old, {**new, 'proof.tex': b'changed'}, {})


def test_removals_and_new_science_fail():
    with pytest.raises(ValueError, match='remove sources'):
        e.check_scope({'main.tex': b'old', 'proof.tex': b'p'}, {'main.tex': b'new'}, {})
    with pytest.raises(ValueError, match='unbound new'):
        e.check_scope({'main.tex': b'old'}, {'main.tex': b'new', 'proof.tex': b'p'}, {})


def template():
    old = {'main.tex': b'old'}
    new = {'main.tex': b'new', 'e-jc.sty': b'official bytes'}
    auth = {'template_assets': {'e-jc.sty': {
        'url': 'https://www.combinatorics.org/files/e-jc.sty',
        'sha256': hashlib.sha256(new['e-jc.sty']).hexdigest()}}}
    return old, new, auth


def test_exact_electronic_template_eligible_for_independent_review():
    old, new, auth = template()
    rows = e.check_scope(old, new, auth)
    assert [r['path'] for r in rows] == ['e-jc.sty', 'main.tex']
    assert rows[0]['before_sha256'] is None


@pytest.mark.parametrize('url', [
    'https://www.combinatorics.org.attacker.test/files/e-jc.sty',
    'http://www.combinatorics.org/files/e-jc.sty',
    'https://www.combinatorics.org/files/another.sty',
    'https://user:password@www.combinatorics.org/files/e-jc.sty',
])
def test_wrong_asset_provenance_fails(url):
    old, new, auth = template(); auth['template_assets']['e-jc.sty']['url'] = url
    with pytest.raises(ValueError, match='provenance'):
        e.check_scope(old, new, auth)


def test_changed_template_and_unused_authorization_fail():
    old, new, auth = template()
    with pytest.raises(ValueError, match='provenance'):
        e.check_scope(old, {**new, 'e-jc.sty': b'altered'}, auth)
    with pytest.raises(ValueError, match='unbound new'):
        e.check_scope(old, {'main.tex': b'new'}, auth)


def test_release_preserves_all_prior_rounds_and_judgments(monkeypatch, tmp_path):
    old = {'score': 5, 'decision': 'minor_revision', 'revision_rounds_completed': 5}
    prep = {'fingerprints': {'manuscript_snapshot_sha256': 'snapshot'}}
    checked = {'baseline': {'metadata': {'writing_release': old}}, 'preparation': prep, 'delivery': prep,
               'rounds': 6, 'evidence': []}
    monkeypatch.setattr(e, 'validate', lambda *a: checked)
    gate = {'status': 'ready', 'score': 5, 'decision': 'minor_revision',
            'revision_rounds_completed': 6, 'manuscript_version': '1.0.7',
            'unresolved_review_blockers': [], 'source_quality_gate': old,
            'manuscript_snapshot_sha256': 'snapshot', e.FIELD: {}}
    meta = {'version': '1.0.7', 'writing_release': gate}
    assert e.validate_release('p', meta, tmp_path) == []
    for field, value in [('score', 6), ('decision', 'accept'), ('revision_rounds_completed', 5),
                         ('manuscript_version', '1.0.6'), ('status', 'draft'),
                         ('unresolved_review_blockers', ['still open']),
                         ('source_quality_gate', {}), ('manuscript_snapshot_sha256', 'other')]:
        bad = deepcopy(meta); bad['writing_release'][field] = value
        with pytest.raises(ValueError, match='preserved judgment'):
            e.validate_release('p', bad, tmp_path)


def test_missing_historical_archive_fails_closed(tmp_path):
    with pytest.raises(ValueError):
        e.validate_baseline({'path': '../escape', 'sha256': '0'*64}, tmp_path)


def test_exact_bibliography_restoration_only():
    reviewed = {'main.tex': b'body\\bibliographystyle{plain}', 'main.bbl': b'lost locators', 'proof.tex': b'proof'}
    original = {'main.bbl': b'all original DOI/arXiv locators'}
    final = {**reviewed, 'main.tex': b'body\\bibliographystyle{elsarticle-num}', 'main.bbl': original['main.bbl']}
    e.bibliography_restoration(reviewed, final, original)
    for key, value in [('main.tex', b'changed science\\bibliographystyle{elsarticle-num}'),
                       ('main.bbl', b'partial restoration'), ('proof.tex', b'changed proof')]:
        with pytest.raises(ValueError, match='exact prior-bibliography'):
            e.bibliography_restoration(reviewed, {**final, key:value}, original)


def test_router_does_not_fall_back_on_invalid_opt_in(monkeypatch, tmp_path):
    from paper_writing import registry, review_delta
    monkeypatch.setattr(registry, 'load_paper_metadata', lambda *a: {e.PREPARATION: {'bad': True}})
    monkeypatch.setattr(e, 'inspect', lambda *a: (_ for _ in ()).throw(ValueError('invalid historical chain')))
    result = review_delta.route_review('p', root=tmp_path)
    assert result == {'route': 'blocked', 'reason': 'invalid historical chain'}
