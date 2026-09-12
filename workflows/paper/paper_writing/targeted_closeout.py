"""Hash-bound targeted addendum followed by author-side editorial closeout.

Not a replacement full review, score generator, or scientific waiver. The
independent addendum must itself establish scientific readiness. Only remaining
text-only requests can be closed by the separately recorded author-side action.
"""
from pathlib import Path
from paper_writing import minor_closeout as m

FIELD = 'targeted_review_closeout'
SCHEMA = 'openlabs.targeted_review_closeout.v1'


def _support_digests(path, version):
    """Bounded-memory comparison of complete payloads, including large archives.

    This never treats archive CRCs or a manifest as proof of member equality.
    Every uncompressed member is streamed through SHA-256; path checks remain
    identical to the small-archive reader. No payload is dropped or truncated.
    """
    import hashlib
    import zipfile
    from pathlib import PurePosixPath
    result = {}
    with zipfile.ZipFile(path) as archive:
        m._require(len(archive.infolist()) <= 10000, 'too many support members')
        for item in archive.infolist():
            name = item.filename
            p = PurePosixPath(name)
            m._require(not p.is_absolute() and '..' not in p.parts and '\\' not in name
                       and (item.external_attr >> 16) & 0o170000 != 0o120000,
                       'unsafe archive member')
            if item.is_dir():
                continue
            key = next(iter(m._support_members({name: b''}, version)))
            m._require(key not in result, 'duplicate normalized support member')
            digest = hashlib.sha256()
            size = 0
            with archive.open(item) as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
            m._require(size == item.file_size, 'support member size mismatch')
            result[key] = digest.hexdigest()
    return result


def _documentary_support_path(name):
    # CLAIMS.yaml is declarative claim-to-evidence mapping, not executable code.
    # It is accepted only through the exact independently reviewed delta below.
    return Path(name).suffix in {'.md', '.svg'} or Path(name).name == 'CLAIMS.yaml'


def _authorized_module_docstring_delta(row, authorization, assessment, packet):
    """Exact opt-in documentation edit, not permission to change executable AST.

    The isolated referee must also assess docstring use at runtime. Byte equality
    outside the leading string prevents an AST-equivalent code rewrite slipping
    through. Authorization is already paper/version bound by validate().
    """
    import ast
    import hashlib
    if (row not in authorization.get('support_docstring_only_changes', [])
            or row['path'] not in assessment.get('support_docstring_only_reviewed', [])
            or not row['path'].startswith('support/') or not row['path'].endswith('.py')):
        return False
    relative = Path(row['path'])
    if '..' in relative.parts or relative.is_absolute():return False
    values = [(Path(packet)/'before'/relative).read_bytes(), (Path(packet)/relative).read_bytes()]
    if [hashlib.sha256(v).hexdigest() for v in values] != [row['before_sha256'], row['after_sha256']]:return False
    stripped=[]
    for value in values:
        try:
            tree=ast.parse(value)
            node=tree.body[0]
            if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):return False
            lines=value.splitlines(keepends=True)
            start=sum(map(len,lines[:node.lineno-1]))+node.col_offset
            end=sum(map(len,lines[:node.end_lineno-1]))+node.end_col_offset
            stripped.append(value[:start]+b'"""DOCSTRING"""'+value[end:])
            # Only the conventional argparse help description may consume it.
            # The independently supplied assessment still decides semantic scope.
            parents={child:parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
            for n in ast.walk(tree):
                if isinstance(n,ast.Attribute) and n.attr=='__doc__':return False
                if not (isinstance(n,ast.Name) and n.id=='__doc__'):continue
                kw=parents.get(n);call=parents.get(kw)
                if not (isinstance(kw,ast.keyword) and kw.arg=='description'
                        and isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute)
                        and isinstance(call.func.value,ast.Name) and call.func.value.id=='argparse'
                        and call.func.attr=='ArgumentParser'):return False
        except (SyntaxError,IndexError,UnicodeError):return False
    return stripped[0]==stripped[1]


def _cumulative_manuscript_delta(before, after, authorization, provenance, assessment):
    """Permit new publisher template assets only when byte-bound and reviewed.

    This is exclusive to an explicitly authorized targeted addendum. It does not
    make a global-template change eligible for ordinary automatic delta reuse.
    Removed files and new scientific sources remain forbidden.
    """
    from urllib.parse import urlparse
    additions = sorted(set(after) - set(before))
    m._require(not (set(before) - set(after)), 'removed manuscript input')
    if not additions:
        return m._deltas(before, after, 'manuscript')
    assets = authorization.get('template_asset_sha256', {})
    m._require(set(assets) == set(additions)
               and provenance.get('files') == assets
               and sorted(assessment.get('template_assets_reviewed', [])) == additions,
               'new template files lack exact authorization/provenance/review')
    url = urlparse(provenance.get('url', ''))
    m._require(url.scheme == 'https' and url.hostname is not None
               and (url.hostname == 'springernature.com'
                    or url.hostname.endswith('.springernature.com')
                    or url.hostname.endswith('.springernature.io')),
               'unverified publisher template provenance')
    import hashlib
    for name in additions:
        m._require(Path(name).name == name and Path(name).suffix in {'.cls', '.bst', '.sty'}
                   and hashlib.sha256(after[name]).hexdigest() == assets[name],
                   'new manuscript file exceeds publisher template boundary')
    result = m._deltas(before, {n: after[n] for n in before}, 'manuscript')
    result += [{'path': 'manuscript/' + n, 'before_sha256': None,
                'after_sha256': assets[n]} for n in additions]
    return sorted(result, key=lambda row: row['path'])


def _integrity_rebinding_from_archives(name, old_path, new_path, old_version, new_version):
    """Read only the verifier and sibling manifest, then use the strict checker."""
    import zipfile
    if Path(name).name != 'verify_support_bundle.py':
        return False
    needed = {name, str(Path(name).parent / 'evidence_bundle_manifest.json')}
    def selected(path, version):
        found = {}
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                if item.is_dir():
                    continue
                key = next(iter(m._support_members({item.filename: b''}, version)))
                if key not in needed:
                    continue
                m._require(key not in found and item.file_size <= 2 * 1024 * 1024,
                           'oversized or duplicate integrity metadata')
                found[key] = archive.read(item)
        return found
    before, after = selected(old_path, old_version), selected(new_path, new_version)
    return name in before and name in after and m._integrity_verifier_rebinding(
        name, before[name], after[name], before, after, old_version, new_version)


def _validate_code_first_repackaging(old, new, packet, authorization, assessment,
                                    old_archive_sha256, new_archive_sha256):
    """Explicitly authorized inventory revision, independently assessed, not reuse.

    Keep the full old evidence hash-bound. Scientific construction modules and
    retained entry points cannot change. Only a new orchestration entry point and
    compact summary may be added. Missing-input judgments belong to the isolated
    reviewer, not to filename heuristics or the author-side closeout.
    """
    import hashlib
    packet = Path(packet)
    inventory_path = packet / 'support-repackaging.json'
    inventory = m._json(inventory_path)
    sha = m._sha(inventory_path)
    changes = [{'path': n, 'before_sha256': old.get(n), 'after_sha256': new.get(n)}
               for n in sorted(set(old) | set(new)) if old.get(n) != new.get(n)]
    m._require(authorization.get('actor') == 'user' and authorization.get('confirmed') is True
               and m._text(authorization.get('quote'))
               and authorization.get('scope') == 'code_first_repackaging_targeted_review'
               and authorization.get('inventory_sha256') == sha,
               'explicit exact-inventory repackaging authorization required')
    m._require(inventory == {'before': old, 'after': new, 'changes': changes,
                'baseline_archive_sha256': old_archive_sha256,
                'current_archive_sha256': new_archive_sha256},
               'support repackaging inventory differs from complete archives')
    m._require(assessment.get('inventory_sha256') == sha
               and all(assessment.get(k) is True for k in
                       ('ready', 'unchanged_scientific_code', 'no_required_input_lost',
                        'documentation_matches_manuscript'))
               and sorted(assessment.get('changed_paths_reviewed', [])) == [r['path'] for r in changes]
               and m._text(assessment.get('reason')),
               'independent support repackaging assessment incomplete or blocking')
    for name, digest in old.items():
        path = Path(name)
        if path.parent.name == 'src' or path.name in {'requirements.txt', 'LICENSE', 'LICENSE.txt'}:
            m._require(new.get(name) == digest, 'scientific source/dependency/license lost or changed: ' + name)
        if name in new and path.suffix == '.py':
            m._require(new[name] == digest, 'retained scientific entry point changed: ' + name)
    for name in set(new) - set(old):
        m._require(name in {'support-materials/public-support-v{version}/reproduce.py',
                           'support-materials/public-support-v{version}/reference-summary.json'},
                   'new support input exceeds code-first orchestration scope: ' + name)
    # The referee must receive the exact complete CURRENT public file set, not
    # just a coordinator-generated list or a prose claim that code was retained.
    actual = {str(p.relative_to(packet/'current-support')): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (packet/'current-support').rglob('*') if p.is_file()}
    m._require(actual == new, 'reviewer did not receive the exact complete current public package')


def validate(paper_id, certificate, metadata, root):
    from paper_writing.handoff import _source_files, _verified_journal_source_archive
    from paper_writing.operations import _review_workspace_fingerprints
    from paper_writing.registry import load_registry_settings
    from paper_writing.review import validate_review_panel_files, reviewer_role_for_domain
    from paper_writing.revision_policy import revision_round_policy
    from paper_writing.support import verify_support_archive, resolve_support_sources, _record_version
    from paper_writing.zenodo import _verify_archive_sources
    from paper_writing.manuscript_style import audit_manuscript_style, manuscript_style_blockers
    from paper_writing.support_citations import audit_manuscript_support, support_audit_blockers

    root = Path(root).resolve()
    path = m._path(certificate, root)
    cert = m._json(path)
    m._require(cert['schema_version'] == SCHEMA and cert['paper_id'] == paper_id,
               'invalid targeted closeout identity')
    evidence = [path]
    def bound(row, artifact=False):
        p = m._bound(row, root, artifact=artifact)
        if not artifact:
            evidence.append(p)
        return p
    bindings = cert['bindings']
    for row in bindings.values():
        bound(row)
    for row in cert['artifact_bindings'].values():
        bound(row, True)
    auth = m._json(bound(bindings['authorization']))
    m._require(auth['actor'] == 'user' and auth['confirmed'] is True
               and auth['paper_id'] == paper_id and m._text(auth['quote'])
               and auth['scope'] == 'targeted_addendum_then_text_only_closeout'
               and auth['target_version'] == metadata['version'] == cert['target']['version'],
               'explicit version-scoped targeted closeout authorization required')
    m._timestamp(auth['recorded_at'])
    baseline = m._json(bound(bindings['baseline_review']))
    panel_path = bound(bindings['baseline_panel'])
    panel = m._json(panel_path)
    errors = validate_review_panel_files(panel, review_path=panel_path, repo_root=root,
        expected_role=reviewer_role_for_domain(metadata['domain']), expected_paper_id=paper_id)
    m._require(not errors, 'invalid original review: ' + '; '.join(errors))
    records = panel['review_metadata']['review_panel']['reviewer_records']
    m._require(len(records) == 1 and records[0]['sha256'] == bindings['baseline_review']['sha256']
               == auth['source_review_sha256'], 'baseline review mismatch')
    applied_record = m._json(bound(bindings['baseline_apply']))
    # Historical final-gate.json records store the same gate at the root.
    # Bind the original record, never manufacture a replacement application.
    applied = applied_record.get('quality_gate', applied_record)
    m._require(applied['score'] == baseline['scores']['overall'] >= 5
               and applied['decision'] == baseline['recommendations']['cas_zone_1_journal']['decision']
               and applied['manuscript_snapshot_sha256'] == baseline['review_metadata']['manuscript_snapshot_sha256_before'],
               'original applied judgment mismatch')
    addendum = m._json(bound(bindings['addendum']))
    execution = m._json(bound(cert['artifact_bindings']['execution'], True))
    snapshot = m._json(bound(cert['artifact_bindings']['snapshot'], True))
    m._require(execution['paper_id'] == snapshot['paper_id'] == paper_id
               and execution['return_code'] == 0 and execution['fresh_ephemeral_process'] is True
               and execution['author_conversation_supplied'] is False
               and execution['prior_review_intentionally_included'] is True
               and execution['new_full_review'] is False
               and execution['isolation'] == 'ephemeral_read_only_mount_isolation'
               and execution['output_sha256'] == bindings['addendum']['sha256']
               and execution['input_hashes'] == snapshot['input_hashes']
               and execution['canonical_snapshot'] == snapshot['canonical_snapshot'],
               'targeted reviewer execution is not bound to its inputs/output')
    packet = bound(cert['artifact_bindings']['snapshot'], True).parent / 'packet'
    actual_inputs = {str(p.relative_to(packet)): m._sha(p) for p in packet.rglob('*') if p.is_file()}
    m._require(actual_inputs == snapshot['input_hashes'], 'targeted packet changed')
    m._require(m._sha(packet / 'baseline-review.json') == bindings['baseline_review']['sha256'],
               'targeted reviewer saw a different baseline')
    m._require(addendum['scope'] == 'targeted_addendum_not_full_review'
               and addendum['original_scores_unchanged'] is True
               and addendum['scientific_ready'] is True
               and addendum['cas_zone_1_decision'] in {'minor_revision', 'accept'},
               'independent scientific readiness/CAS threshold not met')
    dispositions = addendum['request_dispositions']
    # Some isolated reviewers label the complete original list 1..N. Retain
    # their raw judgment unchanged and bind the explicit indexing convention.
    index_base = cert.get('request_index_base', 0)
    m._require(type(index_base) is int and index_base in {0, 1}, 'invalid request index base')
    m._require(sorted(r['index'] - index_base for r in dispositions) == list(range(len(baseline['change_requests'])))
               and all(r['status'] in {'open', 'closed'} and m._text(r['reason']) for r in dispositions),
               'missing or duplicate original request dispositions')
    open_requests = [r['index'] - index_base for r in dispositions if r['status'] == 'open']
    m._require(all(baseline['change_requests'][i].get('text_only') is True for i in open_requests),
               'author-side closeout cannot resolve scientific requests')
    m._require(cert['closed_text_request_indices'] == open_requests,
               'final closeout must cover exactly the open text requests')
    rows = cert['remaining_blocker_resolutions']
    m._require([r['blocker'] for r in rows] == addendum['remaining_blockers']
               and all(r['classification'] in {'text_only_closed', 'nonblocking_venue_only'}
                       and m._text(r['reason']) for r in rows), 'unclassified addendum blocker')
    for row in rows:
        if row['classification'] == 'nonblocking_venue_only':
            m._require('four-leading-journal' in row['blocker'] and 'not a proof defect' in row['blocker']
                       and 'not' in row['blocker'] and 'blocker' in row['blocker'],
                       'venue limitation must be explicitly self-qualified by reviewer')
        else:
            m._require(any(word in row['blocker'].lower() for word in ('whitespace', 'wrapping', 'bibliography')),
                       'not an editorial blocker')
    # Reconstruct the exact reviewed intermediate snapshot, then allow only the
    # explicitly hash-bound final editorial delta. No hidden source change fits.
    manuscript = root / metadata['manuscript_dir']
    pdf = root / metadata['latest_pdf']
    sources = {str(p.relative_to(manuscript)): p.read_bytes() for p in _source_files(manuscript, pdf)}
    verified_zip = _verified_journal_source_archive(metadata, root, manuscript,
        list(_source_files(manuscript, pdf)), None)
    m._require(verified_zip is not None, 'missing verified clean source archive')
    intermediate = m._archive(bound(bindings['reviewed_source_archive']))
    final_zip = m._archive(verified_zip[0])
    m._require(set(intermediate) == set(final_zip)
               and all(sources.get(n) == v for n, v in final_zip.items()),
               'journal source archive membership or bytes differ')
    extras = [{'path': n, 'sha256': m._members({n: v})[n], 'in_review_packet': False}
              for n, v in sources.items() if n not in final_zip]
    reviewed = {**intermediate, **{r['path']: sources[r['path']] for r in extras}}
    m._require(m._snapshot(reviewed, bound(bindings['reviewed_pdf']).read_bytes())
               == snapshot['canonical_snapshot'], 'reviewed full snapshot does not reconstruct')
    final_delta = m._deltas(reviewed, sources, 'manuscript')
    m._require(final_delta == cert['final_editorial_delta'], 'unreviewed final delta')
    m._require(all(row['path'] in auth['final_editorial_files'] for row in final_delta)
               and auth['final_editorial_files'] == cert['final_editorial_files'],
               'final delta exceeds authorized editorial files')
    # The preceding addendum must cover every intermediate canonical difference
    # from the full review. Unchanged snapshot-only ancillary files are not
    # represented as independently reviewed packet content.
    original_zip = m._archive(bound(cert['artifact_bindings']['baseline_source_archive'], True))
    original_pdf = bound(cert['artifact_bindings']['baseline_pdf'], True).read_bytes()
    old_complete = {**original_zip, **{row['path']: sources[row['path']] for row in extras}}
    m._require(m._snapshot(old_complete, original_pdf) == applied['manuscript_snapshot_sha256'],
               'full-review snapshot does not reconstruct')
    import json
    delta = json.loads((packet / 'delta.json').read_text())
    template_provenance = (m._json(bound(bindings['template_provenance']))
                           if 'template_provenance' in bindings else {})
    m._require(_cumulative_manuscript_delta(old_complete, reviewed, auth,
                                           template_provenance, addendum) ==
               [r for r in delta if r['path'].startswith('manuscript/')],
               'targeted packet omitted an intermediate manuscript change')
    # The supporting archive may change only metadata or the exact documentary
    # rows independently inspected in this addendum. Every other byte is fixed.
    support_path = bound(bindings['support_archive'])
    support = verify_support_archive(support_path)
    _verify_archive_sources(support, resolve_support_sources(metadata, repo_root=root), root)
    m._require(support['paper_id'] == paper_id and support['paper_version'] == _record_version(metadata)
               and m._sha(support_path) == metadata['support']['publication']['package_sha256'],
               'current supporting package mismatch')
    old_support_path = bound(cert['artifact_bindings']['baseline_support_archive'], True)
    m._require(m._sha(old_support_path) == applied['support_package_sha256'],
               'support baseline differs from original applied judgment')
    old_version = verify_support_archive(old_support_path)['paper_version']
    old_support = _support_digests(old_support_path, old_version)
    new_support = _support_digests(support_path, support['paper_version'])
    documented = [r for r in delta if r['path'].startswith('support/')]
    if 'support_repackaging_authorization' in bindings:
        repack_auth = m._json(bound(bindings['support_repackaging_authorization']))
        m._require(repack_auth.get('paper_id') == paper_id
                   and repack_auth.get('target_version') == metadata['version']
                   and not documented, 'invalid or mixed repackaging review identity')
        m._timestamp(repack_auth['recorded_at'])
        _validate_code_first_repackaging(old_support, new_support, packet, repack_auth,
            addendum.get('support_repackaging', {}), m._sha(old_support_path), m._sha(support_path))
        from paper_writing.support_upload_policy import validate_upload_packages
        validate_upload_packages([support_path], repo_root=root)
    else:
        m._require(set(old_support) == set(new_support), 'support membership changed')
        used = []
        for name in sorted(old_support):
            before, after = old_support[name], new_support[name]
            if before == after:
                continue
            if Path(name).name in m._SUPPORT_METADATA:
                continue
            matching = [r for r in documented if name == r['path'][8:]
                        or name.endswith('/' + r['path'][8:])]
            m._require(len(matching) == 1, 'unreviewed supporting science/code change: ' + name)
            row = matching[0]
            integrity_only = (row['path'] in addendum.get('support_integrity_rebinding_reviewed', [])
                              and _integrity_rebinding_from_archives(name, old_support_path,
                                  support_path, old_version, support['paper_version']))
            docstring_only = _authorized_module_docstring_delta(row, auth, addendum, packet)
            m._require((_documentary_support_path(name) or integrity_only or docstring_only)
                       and row['before_sha256'] == before
                       and row['after_sha256'] == after, 'support delta differs')
            used.append(row)
        m._require(sorted(r['path'] for r in used) == sorted(r['path'] for r in documented),
                   'reviewed support changes missing')
    target = cert['target']
    m._require(target['fingerprints'] == _review_workspace_fingerprints(paper_id, metadata, root)
               and target['source_archive_sha256'] == m._sha(verified_zip[0])
               and target['pdf_sha256'] == m._sha(pdf), 'final fingerprint changed')
    settings = load_registry_settings(root).get('quality_gate', {})
    m._require(settings.get('minimum_score', 5) == 5
               and settings.get('decision_standard') == 'cas_zone_1_journal'
               and settings.get('cas_zone_1_minimum_decision') == 'minor_revision', 'threshold changed')
    maximum, exception = revision_round_policy(paper_id, metadata, settings, root=root)
    total = applied['revision_rounds'] + 1
    m._require(cert['full_review_rounds'] == applied['revision_rounds']
               and cert['targeted_review_rounds'] == 1 and total <= maximum,
               'targeted judgment exceeds authorized total budget')
    m._timestamp(cert['closed_at'])
    m._require(cert['closed_by'] == 'Codex author-side editorial inspection'
               and cert['new_full_review'] is False and cert['new_lean_executions'] == 0
               and cert['new_scientific_experiments'] == 0, 'incorrect closeout provenance')
    build = m._json(bound(bindings['clean_build']))
    m._require(build['version'] == metadata['version'] and build['standalone_build'] is True
               and build['canonical_standalone_pdf_text_equal'] is True
               and any(r['sha256'] == target['pdf_sha256'] for r in build['files'])
               and any(r['sha256'] == target['source_archive_sha256'] for r in build['files']),
               'clean build is not bound to final delivery')
    blockers = manuscript_style_blockers(audit_manuscript_style(paper_id, root=root, require_ai_declaration=True))
    blockers += support_audit_blockers(audit_manuscript_support(paper_id, root=root))
    m._require(not blockers, 'deterministic gates failed: ' + '; '.join(blockers))
    # Prior ZIP/PDF bytes are replay-checked above but are cache artifacts, not
    # routine Git source. Their SHA bindings live in the committed certificate.
    evidence = [p for p in evidence if p.suffix != '.zip'
                and p != root / bindings['reviewed_pdf']['path']]
    return {'certificate': cert, 'evidence_paths': list(dict.fromkeys(evidence)),
            'score': baseline['scores']['overall'], 'decision': addendum['cas_zone_1_decision'],
            'rounds': total, 'maximum': maximum, 'exception': exception}


def validate_release(paper_id, metadata, root):
    pointer = metadata.get('writing_release', {}).get(FIELD)
    if pointer is None:
        return []
    root = Path(root).resolve()
    m._bound(pointer, root)
    checked = validate(paper_id, pointer['path'], metadata, root)
    cert = checked['certificate']
    release = metadata['writing_release']
    m._require(release['status'] == 'ready' and release['score'] == checked['score']
               and release['decision'] == checked['decision']
               and release['revision_rounds_completed'] == checked['rounds']
               and release['manuscript_version'] == cert['target']['version']
               and release.get('unresolved_review_blockers', []) == [], 'release changed judgment')
    m._require(all(release[k] == v for k, v in cert['target']['fingerprints'].items()),
               'release lost final fingerprint binding')
    return checked['evidence_paths']
