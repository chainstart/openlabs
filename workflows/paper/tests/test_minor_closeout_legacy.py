"""Legacy native packets retain original validation and complete snapshot checks."""
import json
import shutil

import pytest

from paper_writing import minor_closeout as m
from test_minor_closeout import bundle, prepare, write, PID


@pytest.fixture
def legacy(bundle):
    b = bundle
    run = 'staging/legacy-native/' + PID
    art = b['root'].parent / 'openlabs-artifacts' / run
    packet = art / 'packet'
    packet.mkdir(parents=True)
    sources = m._archive(b['source_path'])
    manifest = {}
    # main.tex is deliberately snapshot-only in this fixture, exercising recovery.
    extras = {}
    for name, value in sources.items():
        if name == 'main.tex':
            p = art / 'recovery' / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(value)
            extras[name] = {'path': str(p.relative_to(b['root'].parent / 'openlabs-artifacts')), 'sha256': m._sha(p)}
        else:
            p = packet / 'manuscript' / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(value)
            manifest['manuscript/' + name] = m._sha(p)
    shutil.copyfile(b['pdf'], packet / 'manuscript.pdf')
    shutil.copyfile(b['support_path'], packet / 'original-support.zip')
    manifest['manuscript.pdf'] = m._sha(b['pdf'])
    manifest['original-support.zip'] = m._sha(b['support_path'])
    snap = json.loads((b['art'] / 'packet/input-binding.json').read_text())
    snap['support_archive'] = 'original-support.zip'
    write(art / 'snapshot.json', snap)
    write(packet / 'input-binding.json', snap)
    write(art / 'packet-manifest.json', manifest)
    write(art / 'panel-validation-original/summary.json', {
        'paper_id': PID, 'native_review_sha256': m._sha(b['raw_path']),
        'review_unchanged': True, 'all_steps_passed': True,
        'steps': [{'exit_code': 0} for _ in range(4)]})
    shutil.copyfile(b['review_dir'] / 'apply-cli.json', art / 'panel-validation-original/3.stdout.txt')
    write(b['review_dir'] / 'snapshot-reconstruction.json', {
        'schema_version': 'ara.paper_writing.legacy_snapshot_reconstruction.v1',
        'paper_id': PID, 'reconstructed_at': '2020-01-01T00:00:00+00:00',
        'provenance': 'Offline reconstructed test; ancillary files are not reviewer inputs.',
        'snapshot_only_sources': extras})
    b['run'], b['art'] = run, art
    return b


def test_legacy_packet_preserves_actual_rounds_and_snapshot(legacy):
    cert = prepare(legacy)
    assert cert['revision_rounds_completed'] == 12
    assert cert['snapshot_only_sources'][0]['in_review_packet'] is False
    assert 'postvalidation.json' not in cert['source']
    assert cert['new_independent_review'] is False


@pytest.mark.parametrize('attack', ['recovered_byte', 'pdf', 'manifest', 'apply', 'validation', 'recovery_overlap'])
def test_legacy_rejects_tampering(legacy, attack):
    b = legacy
    if attack == 'recovered_byte':
        (b['art'] / 'recovery/main.tex').write_text('changed')
    elif attack == 'pdf':
        (b['art'] / 'packet/manuscript.pdf').write_bytes(b'changed')
    elif attack == 'manifest':
        write(b['art'] / 'packet-manifest.json', {})
    elif attack == 'apply':
        p = b['review_dir'] / 'apply-cli.json'
        value = json.loads(p.read_text()); value['quality_gate']['revision_rounds'] = 1; write(p, value)
    elif attack == 'validation':
        p = b['art'] / 'panel-validation-original/summary.json'
        value = json.loads(p.read_text()); value['steps'][0]['exit_code'] = 1; write(p, value)
    else:
        p = b['review_dir'] / 'snapshot-reconstruction.json'
        value = json.loads(p.read_text()); value['snapshot_only_sources']['main.pdf'] = value['snapshot_only_sources']['main.tex']; write(p, value)
    with pytest.raises(ValueError):
        prepare(b)
