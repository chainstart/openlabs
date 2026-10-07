"""Ignored build products require exact Git-frozen, two-copy artifact bindings."""
import hashlib
import json
from pathlib import Path
import subprocess

import pytest
from paper_writing.handoff import _release_artifact_bindings, HandoffError
from paper_writing.support import write_support_artifact_manifest


def git(root, *args):
    subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)


def make_setup(tmp_path, pid):
    root = tmp_path / 'openlabs-data'; root.mkdir()
    manuscript = root / 'papers' / pid / 'manuscript'; manuscript.mkdir(parents=True)
    pdf = manuscript / 'main.pdf'; pdf.write_bytes(b'%PDF exact test bytes')
    source = manuscript / 'main.tex'; source.write_text('scientific source')
    (root / '.gitignore').write_text('*.pdf\n*.bbl\n')
    git(root, 'init', '-q')
    manifest = write_support_artifact_manifest(root, [pdf], f'papers/{pid}/production/release-artifacts.json')
    meta = {'manuscript_dir': str(manuscript.relative_to(root)), 'submission_package': {
        'artifact_manifest': {'path': str(manifest.relative_to(root)),
                              'sha256': hashlib.sha256(manifest.read_bytes()).hexdigest()}}}
    git(root, 'add', '.gitignore', str(source.relative_to(root)), str(manifest.relative_to(root)))
    git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'Freeze manifest')
    return root, pid, meta, manifest, pdf, source


@pytest.fixture
def setup(tmp_path):
    return make_setup(tmp_path, '20260908-math-graph-artifact-test')


@pytest.mark.parametrize('pid,name,content,accepted', [
    ('20260608mathgraph0006', 'main.lpg', b'\\def \\@myextralastpage {15}\n\\endinput \n', True),
    ('20260908-math-graph-artifact-test', 'main.lpg', b'\\def \\@myextralastpage {15}\n\\endinput \n', False),
    ('20260608mathgraph0006', 'nested/main.lpg', b'\\def \\@myextralastpage {15}\n\\endinput \n', False),
    ('20260608mathgraph0006', 'other.lpg', b'\\def \\@myextralastpage {15}\n\\endinput \n', False),
    ('20260608mathgraph0006', 'main.lpg', b'\\def \\@myextralastpage {16}\n\\endinput \n', False),
    ('20260608mathgraph0006', 'main.lpg', b'', False),
])
def test_exact_p006_legacy_pagination_only(tmp_path, pid, name, content, accepted):
    root, pid, meta, manifest, pdf, source = make_setup(tmp_path, pid)
    marker = pdf.parent / name
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_bytes(content)
    with (root / '.gitignore').open('a') as f:
        f.write('*.lpg\n')
    write_support_artifact_manifest(root, [pdf, marker], manifest)
    meta['submission_package']['artifact_manifest']['sha256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    git(root, 'add', '.gitignore', str(manifest.relative_to(root)))
    git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'Bind legacy adjunct')
    files = [pdf, source, marker]
    if not accepted:
        with pytest.raises(HandoffError, match='Only canonical'):
            _release_artifact_bindings(pid, meta, root, files)
        return
    assert str(marker.relative_to(root)) in _release_artifact_bindings(pid, meta, root, files)[1]
    git(root, 'add', '-f', str(marker.relative_to(root)))
    with pytest.raises(HandoffError, match='Tracked manuscript'):
        _release_artifact_bindings(pid, meta, root, files)
    git(root, 'reset', '--', str(marker.relative_to(root)))
    marker.write_bytes(content.replace(b'{15}', b'{16}'))
    with pytest.raises(HandoffError, match='Only canonical'):
        _release_artifact_bindings(pid, meta, root, files)


def test_exact_ignored_artifact_passes_and_original_is_required(setup):
    root, pid, meta, manifest, pdf, source = setup
    result = _release_artifact_bindings(pid, meta, root, [pdf, source])
    assert result == (manifest, {str(pdf.relative_to(root))})
    row = json.loads(manifest.read_text())['files'][0]
    from urllib.parse import urlparse, unquote
    original = Path(unquote(urlparse(row['artifact_uri']).path))
    original.write_bytes(b'%PDF changed original')
    with pytest.raises(HandoffError, match='SHA-256'):
        _release_artifact_bindings(pid, meta, root, [pdf, source])


def test_changed_cache_fails_even_same_size(setup):
    root, pid, meta, manifest, pdf, source = setup
    pdf.write_bytes(b'x' * pdf.stat().st_size)
    with pytest.raises(HandoffError, match='SHA-256'):
        _release_artifact_bindings(pid, meta, root, [pdf, source])


def test_modified_manifest_cannot_rebind_uncommitted_bytes(setup):
    root, pid, meta, manifest, pdf, source = setup
    manifest.write_text(manifest.read_text() + '\n')
    meta['submission_package']['artifact_manifest']['sha256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    git(root, 'update-index', '--assume-unchanged', str(manifest.relative_to(root)))
    with pytest.raises(HandoffError, match='Git HEAD'):
        _release_artifact_bindings(pid, meta, root, [pdf, source])


def test_scientific_sources_cannot_use_generated_artifact_exemption(setup):
    root, pid, meta, manifest, pdf, source = setup
    write_support_artifact_manifest(root, [source], manifest)
    meta['submission_package']['artifact_manifest']['sha256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    git(root, 'add', str(manifest.relative_to(root)))
    git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'Invalid source binding')
    with pytest.raises(HandoffError, match='Only canonical'):
        _release_artifact_bindings(pid, meta, root, [pdf, source])


def test_already_tracked_pdf_remains_git_frozen(setup):
    root, pid, meta, manifest, pdf, source = setup
    git(root, 'add', '-f', str(pdf.relative_to(root)))
    with pytest.raises(HandoffError, match='Tracked manuscript'):
        _release_artifact_bindings(pid, meta, root, [pdf, source])


@pytest.mark.parametrize('name,content,accepted', [
    ('main.idx', b'', True),
    ('main.idx', b'\\indexentry{scientific content}{1}', False),
    ('other.idx', b'', False),
    ('main.aux', b'', False),
    ('nested/main.idx', b'', False),
])
def test_only_empty_root_index_marker_can_be_bound(setup, name, content, accepted):
    root, pid, meta, manifest, pdf, source = setup
    marker = pdf.parent / name
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_bytes(content)
    with (root / '.gitignore').open('a') as f:
        f.write('*.idx\n*.aux\n')
    write_support_artifact_manifest(root, [pdf, marker], manifest)
    meta['submission_package']['artifact_manifest']['sha256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    git(root, 'add', '.gitignore', str(manifest.relative_to(root)))
    git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'Bind exact marker')
    files = [pdf, source, marker]
    if not accepted:
        with pytest.raises(HandoffError, match='Only canonical'):
            _release_artifact_bindings(pid, meta, root, files)
        return
    assert _release_artifact_bindings(pid, meta, root, files) == (manifest, {
        str(pdf.relative_to(root)), str(marker.relative_to(root))})
    # Mutation after binding cannot turn the empty marker into hidden content.
    marker.write_bytes(b'x')
    with pytest.raises(HandoffError, match='Only canonical'):
        _release_artifact_bindings(pid, meta, root, files)
