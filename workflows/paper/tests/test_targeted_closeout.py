from copy import deepcopy
import pytest
from paper_writing import targeted_closeout as t


def test_absent_closeout_is_noop(tmp_path):
    assert t.validate_release('p', {}, tmp_path) == []


def test_streamed_support_hashes_all_bytes(tmp_path):
    import hashlib
    import zipfile
    data = b'x' * (3 * 1024 * 1024) + b'end'
    path = tmp_path / 'support.zip'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('p-support-v0.1.0/support-materials/public-support-v0.1.0/data.bin', data)
    assert t._support_digests(path, '0.1.0') == {
        'support-materials/public-support-v{version}/data.bin': hashlib.sha256(data).hexdigest()}


@pytest.mark.parametrize('name', ['/absolute', '../escape', 'p-support-v0.1.0/../escape', 'bad-root/data'])
def test_streamed_support_rejects_unsafe_paths(tmp_path, name):
    import zipfile
    path = tmp_path / 'support.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr(name, b'x')
    with pytest.raises(ValueError):
        t._support_digests(path, '0.1.0')


def test_only_exact_claim_map_yaml_is_documentary():
    assert t._documentary_support_path('support/CLAIMS.yaml')
    assert not t._documentary_support_path('support/config.yaml')
    assert not t._documentary_support_path('support/check.py')


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
