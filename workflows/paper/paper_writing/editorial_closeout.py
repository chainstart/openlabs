"""Explicit editorial bridge from a replay-validated legacy ready closeout.

Old sources are mounted read-only in a private namespace for validation by the
original validators. No old record is rewritten and no whole-paper score is made.
This opt-in bridge counts one NEW independent judgment after ALL previous rounds.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from paper_writing import minor_closeout as m

FIELD = 'editorial_closeout'
PREPARATION = 'editorial_closeout_preparation'
SCHEMA = 'openlabs.editorial_closeout.v1'
SCOPE = 'validated_legacy_closeout_editorial_delta'
WRAPPERS = {'main.tex', 'main.bbl', 'author-metadata.tex'}


def retained_issues(baseline, root):
    """Only prior issue/closure text goes to the referee, never old scores."""
    meta = baseline['metadata']; gate = meta['writing_release']
    panel = m._json(m._path(meta['ara_llm_self_review']['source'], root))
    result = {'original_change_requests': panel['change_requests'],
              'original_required_changes': panel['required_changes'],
              'nonblocking_findings': gate.get('nonblocking_venue_findings', [])}
    if 'targeted_review_closeout' in gate:
        cert = m._json(m._bound(gate['targeted_review_closeout'], root))
        addendum = m._json(m._bound(cert['bindings']['addendum'], root))
        result['previous_dispositions'] = addendum['request_dispositions']
        result['previous_final_resolutions'] = cert['remaining_blocker_resolutions']
    else:
        pointer = gate['minor_revision_closeout']
        cert = m._json(m._bound({k:pointer[k] for k in ('path','sha256')}, root))
        result['previous_dispositions'] = cert['request_resolutions']
        result['previous_final_resolutions'] = cert['required_change_resolutions']
    return result


def delta(before, after):
    return [{'path': n, 'before_sha256': m._members({n: before[n]})[n] if n in before else None,
             'after_sha256': m._members({n: after[n]})[n] if n in after else None}
            for n in sorted(set(before) | set(after)) if before.get(n) != after.get(n)]


def check_scope(before, after, authorization):
    """A tripwire only: the isolated reviewer must assess every allowed hunk."""
    from urllib.parse import urlparse
    m._require(not (set(before) - set(after)), 'editorial bridge cannot remove sources')
    assets = authorization.get('template_assets', {})
    additions = set(after) - set(before)
    m._require(additions == set(assets), 'unbound new source/template asset')
    for name, row in assets.items():
        url = urlparse(row['url'])
        m._require(name == Path(name).name and Path(name).suffix in {'.sty', '.cls', '.bst'}
                   and url.scheme == 'https' and not url.username and not url.password
                   and url.hostname in {'www.combinatorics.org', 'combinatorics.org',
                                        'www.springernature.com', 'resource-cms.springernature.com'}
                   and url.path.endswith('/' + name)
                   and m._members({name: after[name]})[name] == row['sha256'],
                   'publisher asset provenance or bytes invalid')
    changes = delta(before, after)
    m._require(all(r['path'] in WRAPPERS | additions for r in changes),
               'scientific source change exceeds editorial bridge')
    return changes


def _worker(root, baseline_path):
    """Runs ONLY in the read-only historical manuscript mount namespace."""
    from paper_writing.operations import _review_workspace_fingerprints
    from paper_writing.registry import load_registry_settings
    from paper_writing.revision_policy import validate_release_revision_policy
    from paper_writing.targeted_closeout import validate_release as targeted
    baseline = m._json(baseline_path)
    meta = baseline['metadata']; pid = meta['paper_id']; gate = meta['writing_release']
    m._require(gate['status'] == 'ready' and gate['score'] >= 5
               and gate['decision'] in {'accept', 'minor_revision'}
               and gate['decision_standard'] == 'cas_zone_1_journal'
               and gate['manuscript_version'] == meta['version']
               and not gate.get('unresolved_review_blockers'), 'historical gate not ready')
    fp = _review_workspace_fingerprints(pid, meta, root)
    m._require(all(gate.get(k) == v for k, v in fp.items()), 'historical fingerprint mismatch')
    validate_release_revision_policy(pid, meta, load_registry_settings(root)['quality_gate'], root=root)
    kinds = [k for k in ('minor_revision_closeout', 'targeted_review_closeout') if k in gate]
    m._require(len(kinds) == 1 and FIELD not in gate, 'unsupported or ambiguous legacy gate')
    files = (targeted(pid, meta, root) if kinds[0] == 'targeted_review_closeout'
             else m.validate_release_minor_closeout(pid, meta, root=root))
    return {'gate': gate, 'evidence': [str(p.relative_to(root)) for p in files]}


def validate_baseline(binding, root):
    """Reconstruct exact old bytes without ever swapping the live manuscript."""
    root = Path(root).resolve(); path = m._bound(binding, root); baseline = m._json(path)
    archive = m._bound(baseline['snapshot_archive'], root, artifact=True)
    content = m._archive(archive)
    meta = baseline['metadata']; gate = meta['writing_release']
    m._require('main.pdf' in content, 'historical PDF missing')
    sources = {k: v for k, v in content.items() if k != 'main.pdf'}
    m._require(m._snapshot(sources, content['main.pdf']) == gate['manuscript_snapshot_sha256'],
               'historical snapshot does not reconstruct')
    manuscript = root / meta['manuscript_dir']
    m._require(manuscript.resolve() == manuscript and manuscript.is_relative_to(root), 'unsafe manuscript path')
    bwrap = shutil.which('bwrap'); m._require(bwrap is not None, 'read-only namespace unavailable')
    with tempfile.TemporaryDirectory(prefix='openlabs-historical-closeout-') as tmp:
        shadow = Path(tmp)/'manuscript'; shadow.mkdir()
        for name, value in content.items():
            p = shadow / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(value)
        old_registry = Path(tmp)/'registry.json'
        old_registry.write_text(json.dumps(meta))
        env = {'PATH': '/usr/bin:/bin', 'PYTHONPATH': str(Path(__file__).resolve().parents[1]),
               'PYTHONDONTWRITEBYTECODE': '1', 'LANG': 'C.UTF-8'}
        command = [bwrap, '--unshare-user', '--unshare-pid', '--unshare-net', '--die-with-parent',
                   '--ro-bind', '/', '/', '--ro-bind', str(shadow), str(manuscript),
                   '--ro-bind', str(old_registry), str(root/'registry/papers'/f'{meta["paper_id"]}.yaml'),
                   sys.executable, '-m', 'paper_writing.editorial_closeout', '_worker', str(root), str(path)]
        result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=180)
        m._require(result.returncode == 0, 'historical chain replay failed: ' + result.stderr[-3000:])
        checked = json.loads(result.stdout)
    m._require(checked['gate'] == gate, 'historical replay changed gate')
    return baseline, content, checked


def bibliography_restoration(reviewed, final, original):
    """Only undo the locator-losing style switch; reproduce the old bibliography."""
    m._require(set(reviewed) == set(final), 'bibliography closeout changed membership')
    old, new = b'\\bibliographystyle{plain}', b'\\bibliographystyle{elsarticle-num}'
    m._require(reviewed['main.tex'].count(old) == 1
               and final['main.tex'] == reviewed['main.tex'].replace(old, new)
               and final['main.bbl'] == original['main.bbl']
               and all(final[n] == v for n,v in reviewed.items() if n not in {'main.tex','main.bbl'}),
               'closeout is not an exact prior-bibliography restoration')


def inspect(paper_id, preparation, metadata, root, *, final=None):
    from paper_writing.handoff import _source_files, _verified_journal_source_archive
    from paper_writing.operations import _review_workspace_fingerprints
    from paper_writing.registry import load_registry_settings
    from paper_writing.revision_policy import revision_round_policy
    root = Path(root).resolve(); prep_path = m._bound(preparation, root); prep = m._json(prep_path)
    auth_path = m._bound(prep['authorization'], root); auth = m._json(auth_path)
    m._require(auth_path.parent == root/'registry/quality-gate-exceptions'
               and auth['actor'] == 'user' and auth['confirmed'] is True and m._text(auth['quote'])
               and auth['scope'] == SCOPE and auth['paper_id'] == paper_id
               and auth['target_version'] == metadata['version']
               and auth['target_journal'] == metadata['target_journal']
               and auth['baseline'] == prep['baseline'], 'invalid editorial authorization')
    m._timestamp(auth['recorded_at'])
    baseline, old, replay = validate_baseline(prep['baseline'], root)
    oldmeta = baseline['metadata']; oldgate = oldmeta['writing_release']
    m._require(oldmeta['paper_id'] == paper_id and oldmeta['version'] == auth['source_version'], 'baseline identity mismatch')
    m._require(metadata['ara_llm_self_review'] == oldmeta['ara_llm_self_review'], 'historical scores/review changed')
    m._require(metadata['support'] == oldmeta['support'], 'support changed; cannot use editorial bridge')
    manuscript = root/metadata['manuscript_dir']; pdf = root/metadata['latest_pdf']
    files = list(_source_files(manuscript, pdf))
    current = {str(p.relative_to(manuscript)): p.read_bytes() for p in files}
    reviewed = current
    delivery = prep
    if final is not None:
        m._require(final['kind'] == 'exact_prior_bibliography_restoration', 'unsupported final closeout')
        oldzip = m._archive(m._bound(final['reviewed_source_archive'], root))
        reviewed_pdf = m._bound(final['reviewed_pdf'], root)
        m._require(final['reviewed_source_archive']['sha256'] == prep['source_archive']['sha256']
                   and final['reviewed_pdf']['sha256'] == prep['pdf']['sha256'], 'intermediate delivery changed')
        reviewed = {**current, **oldzip}
        m._require(m._snapshot(reviewed, reviewed_pdf.read_bytes()) == prep['fingerprints']['manuscript_snapshot_sha256'], 'intermediate full snapshot changed')
        bibliography_restoration(reviewed, current, old)
        delivery = final
    changes = check_scope({k:v for k,v in old.items() if k != 'main.pdf'}, reviewed, auth)
    m._require(changes == prep['delta'], 'editorial delta changed')
    fp = _review_workspace_fingerprints(paper_id, metadata, root)
    m._require(fp == delivery['fingerprints'], 'current fingerprint changed')
    package = _verified_journal_source_archive(metadata, root, manuscript, files, None)
    m._require(package is not None and m._sha(package[0]) == delivery['source_archive']['sha256']
               and m._sha(pdf) == delivery['pdf']['sha256'], 'delivery bytes changed')
    m._bound(delivery['source_archive'], root); m._bound(delivery['pdf'], root)
    for row in prep.get('context_bindings', {}).values():m._bound(row, root)
    gate = load_registry_settings(root)['quality_gate']
    m._require(gate['minimum_score'] == 5 and gate['decision_standard'] == 'cas_zone_1_journal'
               and gate['cas_zone_1_minimum_decision'] == 'minor_revision'
               and gate.get('review_panel_size', 1) == 1, 'unsupported gate policy')
    maximum, exception = revision_round_policy(paper_id, metadata, gate, root=root)
    rounds = oldgate['revision_rounds_completed'] + 1
    m._require(rounds <= maximum, 'new judgment exceeds total authorized budget')
    return {'preparation': prep, 'delivery': delivery, 'baseline': baseline, 'old_sources': old, 'replay': replay,
            'rounds': rounds, 'maximum': maximum, 'exception': exception,
            'evidence': [prep_path, auth_path, m._bound(prep['baseline'], root)] +
                        [root/n for n in replay['evidence']]}


def validate(paper_id, certificate, metadata, root):
    from paper_writing.declarations import check_record
    from paper_writing.manuscript_style import audit_manuscript_style
    from paper_writing.support_citations import audit_manuscript_support
    root = Path(root).resolve(); path = m._bound(certificate, root); cert = m._json(path)
    m._require(cert['schema_version'] == SCHEMA and cert['paper_id'] == paper_id, 'invalid bridge certificate')
    final = cert.get('bibliography_restoration')
    checked = inspect(paper_id, cert['preparation'], metadata, root, final=final); prep = checked['preparation']; delivery = checked['delivery']
    result_path = m._bound(cert['result'], root); result = m._json(result_path)
    execution = m._json(m._bound(cert['execution'], root, artifact=True))
    snap_path = m._bound(cert['snapshot'], root, artifact=True); snap = m._json(snap_path)
    packet = snap_path.parent/'packet'
    hashes = {str(p.relative_to(packet)): m._sha(p) for p in packet.rglob('*') if p.is_file()}
    m._require(execution['paper_id'] == snap['paper_id'] == paper_id
               and execution['return_code'] == 0 and execution['fresh_ephemeral_process'] is True
               and execution['author_conversation_supplied'] is False
               and execution['isolation'] == 'ephemeral_read_only_mount_isolation'
               and execution['new_full_review'] is False
               and execution['input_hashes'] == snap['input_hashes'] == hashes
               and execution['output_sha256'] == cert['result']['sha256']
               and execution['canonical_snapshot'] == snap['canonical_snapshot'] == prep['fingerprints']['manuscript_snapshot_sha256'],
               'independent execution or frozen inputs invalid')
    m._require(json.loads((packet/'delta.json').read_text()) == prep['delta'], 'reviewed wrong delta')
    m._require(m._json(packet/'prior-issues.json') == retained_issues(checked['baseline'], root), 'prior issue text not preserved')
    for name, row in prep.get('context_bindings', {}).items():
        m._require(Path(name).name == name and (packet/name).read_bytes() == m._bound(row, root).read_bytes(), 'reviewed context mismatch')
    # Reviewers see only the current compilation source ZIP and exact changed
    # old files; private historical reviews stay hidden except the issue text.
    current_zip = m._archive(m._bound(final['reviewed_source_archive'] if final else prep['source_archive'], root))
    m._require(all((packet/'current'/n).read_bytes() == v for n,v in current_zip.items())
               and (packet/'main.pdf').read_bytes() == m._bound(final['reviewed_pdf'] if final else prep['pdf'], root).read_bytes(), 'reviewed different current sources/PDF')
    for row in prep['delta']:
        n = row['path']
        if n in checked['old_sources']:
            m._require((packet/'before'/n).read_bytes() == checked['old_sources'][n], 'reviewed different old source')
    editorial_closed = (final is not None and result['verdict'] == 'unresolved'
        and len(result['remaining_blockers']) == 1
        and 'bibliography' in result['remaining_blockers'][0].lower()
        and 'DOI' in result['remaining_blockers'][0]
        and 'locator' in result['remaining_blockers'][0].lower())
    m._require(result['scope'] == 'editorial_delta_after_validated_closeout'
               and ((result['verdict'] == 'resolved' and result['remaining_blockers'] == [] and final is None) or editorial_closed)
               and result['scientific_content_preserved'] is True
               and result['prior_judgments_preserved'] is True
               and sorted(result['changed_paths_reviewed']) == [r['path'] for r in prep['delta']]
               and m._text(result['assessment']), 'independent changes-only review unresolved')
    build_path = m._bound(cert['build'], root); build = m._json(build_path)
    m._require(build['version'] == metadata['version'] and build['canonical_standalone_pdf_text_equal'] is True
               and any(f['sha256'] == delivery['source_archive']['sha256'] for f in build['files'])
               and any(f['sha256'] == delivery['pdf']['sha256'] for f in build['files']), 'clean build mismatch')
    source = (root/metadata['manuscript_dir']/'main.tex').read_text()
    for check in (check_record(metadata, source, root=root), audit_manuscript_style(paper_id, root=root), audit_manuscript_support(paper_id, root=root)):
        m._require(check['valid'], 'deterministic gate failed: '+str(check.get('errors')))
    checked['certificate'] = cert
    checked['evidence'] += [path, result_path, build_path] + [m._bound(r, root) for r in prep.get('context_bindings', {}).values()]
    return checked


def validate_release(paper_id, metadata, root):
    gate = metadata.get('writing_release', {})
    if FIELD not in gate:return []
    checked = validate(paper_id, gate[FIELD], metadata, root)
    old = checked['baseline']['metadata']['writing_release']; prep = checked['delivery']
    m._require(gate['status'] == 'ready' and gate['score'] == old['score'] and gate['decision'] == old['decision']
               and gate['revision_rounds_completed'] == checked['rounds']
               and gate['manuscript_version'] == metadata['version']
               and gate.get('unresolved_review_blockers') == []
               and gate['source_quality_gate'] == old
               and all(gate[k] == v for k,v in prep['fingerprints'].items()), 'release changed preserved judgment or chain')
    return list(dict.fromkeys(checked['evidence']))


if __name__ == '__main__':
    m._require(sys.argv[1] == '_worker', 'internal historical validator only')
    print(json.dumps(_worker(Path(sys.argv[2]), Path(sys.argv[3]))))
