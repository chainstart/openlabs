"""Independent production follow-up, preserving the unsuccessful first addendum.

This opt-in is not an author-side pass. It allows only two exact elsarticle
typography repairs and completion of previously omitted build/package evidence.
Both independent executions remain bound and consume separate review rounds.
"""
from pathlib import Path
import re
from paper_writing import minor_closeout as m

KIND = 'independent_elsarticle_production_followup'


def typography_delta(before, after):
    m._require(set(before) == set(after), 'follow-up source membership changed')
    required = {'main.tex', 'references.bib', 'main.bbl'}
    m._require(required <= set(before), 'follow-up sources incomplete')
    old, new = b'Appendix~\\ref{app:', b'\\ref{app:'
    m._require(before['main.tex'].count(old) == 5
               and after['main.tex'] == before['main.tex'].replace(old, new),
               'follow-up exceeds five appendix-prefix corrections')
    old, new = b'note          = {Preprint, version', b'note          = {, Preprint, version'
    m._require(before['references.bib'].count(old) == 4
               and after['references.bib'] == before['references.bib'].replace(old, new),
               'follow-up exceeds four bibliography separators')
    compact = lambda value: re.sub(rb'\s+', b'', value)
    old = compact(before['main.bbl'])
    m._require(old.count(b'e-printsPreprint') == 4
               and compact(after['main.bbl']) == old.replace(b'e-printsPreprint', b'e-prints,Preprint'),
               'regenerated bibliography changed more than separators/wrapping')
    m._require(all(after[n] == v for n,v in before.items() if n not in required),
               'unrelated source changed in production follow-up')


def inspect_authorization(paper_id, final, prep, metadata, root):
    path = m._bound(final['authorization'], root); auth = m._json(path)
    original = m._json(m._bound(final['prior_preparation'], root))
    m._require({k:v for k,v in prep.items() if k != 'production_followup'} == original,
               'follow-up changed original preparation')
    m._require(path.parent == Path(root)/'registry/quality-gate-exceptions'
               and auth.get('actor') == 'user' and auth.get('confirmed') is True
               and m._text(auth.get('quote')) and auth.get('scope') == KIND
               and auth.get('paper_id') == paper_id
               and auth.get('target_version') == metadata['version']
               and auth.get('target_journal') == metadata['target_journal']
               and auth.get('prior_preparation') == final['prior_preparation']
               and auth.get('additional_independent_reviews') == 1,
               'explicit production-follow-up authorization missing')
    m._timestamp(auth['recorded_at'])
    return auth, path


def validate(paper_id, final, primary, root):
    """Validate the new judgment and the actual ZIP/build/PDF inputs it saw."""
    from paper_writing.editorial_closeout import delta
    result_path = m._bound(final['result'], root); result = m._json(result_path)
    snap_path = m._bound(final['snapshot'], root, artifact=True); snap = m._json(snap_path)
    execution = m._json(m._bound(final['execution'], root, artifact=True))
    packet = snap_path.parent/'packet'
    hashes = {str(p.relative_to(packet)):m._sha(p) for p in packet.rglob('*') if p.is_file()}
    m._require(execution['paper_id'] == snap['paper_id'] == paper_id
               and execution['return_code'] == 0 and execution['fresh_ephemeral_process'] is True
               and execution['author_conversation_supplied'] is False
               and execution['new_full_review'] is False
               and execution['isolation'] == 'ephemeral_read_only_mount_isolation'
               and execution['input_hashes'] == snap['input_hashes'] == hashes
               and execution['output_sha256'] == final['result']['sha256']
               and execution['canonical_snapshot'] == snap['canonical_snapshot']
                   == final['fingerprints']['manuscript_snapshot_sha256'],
               'production follow-up execution/input binding invalid')
    m._require(m._json(packet/'prior-result.json') == primary
               and primary['scientific_content_preserved'] is True
               and primary['prior_judgments_preserved'] is True
               and primary['verdict'] in {'unresolved','escalate'},
               'follow-up does not preserve the prior unsuccessful judgment')
    prior = m._archive(m._bound(final['reviewed_source_archive'], root))
    current = m._archive(m._bound(final['source_archive'], root))
    typography_delta(prior, current)
    changes = delta(prior, current)
    m._require(m._json(packet/'delta.json') == changes
               and all((packet/'current'/n).read_bytes() == v for n,v in current.items())
               and all((packet/'before'/r['path']).read_bytes() == prior[r['path']] for r in changes)
               and (packet/'source.zip').read_bytes() == m._bound(final['source_archive'],root).read_bytes()
               and (packet/'main.pdf').read_bytes() == m._bound(final['pdf'],root).read_bytes(),
               'follow-up omitted or changed source ZIP/PDF/delta evidence')
    build_path = m._bound(final['build'], root); build = m._json(build_path)
    verification_path = m._bound(final['package_verification'], root); verification = m._json(verification_path)
    m._require(m._json(packet/'package-build-result.json') == build
               and m._json(packet/'package-verification.json') == verification
               and verification['source_archive_sha256'] == final['source_archive']['sha256']
               and verification['canonical_pdf_sha256'] == final['pdf']['sha256']
               and verification['standalone_pdf_sha256'] == m._sha(packet/'standalone.pdf')
               and verification['source_members'] == m._members(current)
               and verification['canonical_standalone_pdf_text_equal'] is True
               and verification['standalone_build_log_sha256'] == m._sha(packet/'standalone-build.log'),
               'follow-up build evidence incomplete')
    # Recheck the two actual PDF texts, not only the stored boolean.
    import subprocess
    texts = [subprocess.check_output(['pdftotext','-layout',str(packet/n),'-'],timeout=30)
             for n in ('main.pdf','standalone.pdf')]
    m._require(texts[0] == texts[1] and b'Appendix Appendix' not in texts[0]
               and b'e-printsPreprint' not in texts[0], 'standalone PDF text or typography differs')
    dispositions = result.get('issue_dispositions', [])
    m._require(result.get('scope') == KIND and result.get('verdict') == 'resolved'
               and result.get('scientific_content_preserved') is True
               and result.get('prior_judgments_preserved') is True
               and result.get('source_archive_verified') is True
               and result.get('standalone_build_verified') is True
               and result.get('remaining_blockers') == []
               and sorted(result.get('changed_paths_reviewed',[])) == [r['path'] for r in changes]
               and [r.get('index') for r in dispositions] == list(range(len(primary['remaining_blockers'])))
               and all(r.get('status') == 'closed' and m._text(r.get('evidence')) for r in dispositions)
               and m._text(result.get('assessment')) and m._text(result.get('visual_assessment')),
               'independent production follow-up unresolved')
    return [result_path,build_path,verification_path]
