from copy import deepcopy
import pytest
from paper_writing import targeted_closeout as t


def test_absent_closeout_is_noop(tmp_path):
    assert t.validate_release('p', {}, tmp_path) == []


@pytest.mark.parametrize('field,value', [
    (None, None), ('score', 9), ('decision', 'accept'),
    ('revision_rounds_completed', 4), ('manuscript_version', '1.0.5'),
    ('unresolved_review_blockers', ['proof gap']), ('status', 'blocked'),
    ('manuscript_snapshot_sha256', 'different'),
])
def test_release_keeps_targeted_judgment_and_fingerprint(monkeypatch, tmp_path, field, value):
    fingerprints = {'manuscript_snapshot_sha256': 'final'}
    cert = {'target': {'version': '1.0.6', 'fingerprints': fingerprints}}
    checked = {'certificate': cert, 'score': 5, 'decision': 'minor_revision',
               'rounds': 5, 'evidence_paths': [tmp_path/'certificate.json']}
    monkeypatch.setattr(t.m, '_bound', lambda *a, **kw: tmp_path/'certificate.json')
    monkeypatch.setattr(t, 'validate', lambda *a, **kw: checked)
    metadata = {'writing_release': {
        'status': 'ready', 'score': 5, 'decision': 'minor_revision',
        'revision_rounds_completed': 5, 'manuscript_version': '1.0.6',
        'unresolved_review_blockers': [], **fingerprints,
        t.FIELD: {'path': 'certificate.json', 'sha256': 'bound'},
    }}
    metadata = deepcopy(metadata)
    if field:
        metadata['writing_release'][field] = value
        with pytest.raises(ValueError):
            t.validate_release('p', metadata, tmp_path)
    else:
        assert t.validate_release('p', metadata, tmp_path) == checked['evidence_paths']
