from copy import deepcopy
import pytest
from paper_writing import targeted_closeout as t


def test_absent_closeout_is_noop(tmp_path):
    assert t.validate_release('p', {}, tmp_path) == []


@pytest.mark.parametrize('mutation', ['none','help_only','code','outside_comment','runtime_doc','unauthorized','unreviewed','wrong_hash'])
def test_docstring_exception_is_exact_and_independently_reviewed(tmp_path, mutation):
    import hashlib
    name='support/code.py';old=b'"""old documentation"""\nx=1\n';new=b'"""correct documentation"""\nx=1\n'
    if mutation=='code':new=new.replace(b'x=1',b'x=2')
    if mutation=='outside_comment':new+=b'# unrelated\n'
    if mutation=='runtime_doc':old+=b'print(__doc__)\n';new+=b'print(__doc__)\n'
    if mutation=='help_only':old+=b'parser=argparse.ArgumentParser(description=__doc__)\n';new+=b'parser=argparse.ArgumentParser(description=__doc__)\n'
    for path,value in [(tmp_path/'before'/name,old),(tmp_path/name,new)]:
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
    row={'path':name,'before_sha256':hashlib.sha256(old).hexdigest(),'after_sha256':hashlib.sha256(new).hexdigest()}
    auth={'support_docstring_only_changes':[row]};assessment={'support_docstring_only_reviewed':[name]}
    if mutation=='unauthorized':auth={}
    if mutation=='unreviewed':assessment={}
    if mutation=='wrong_hash':row['after_sha256']='0'*64
    assert t._authorized_module_docstring_delta(row,auth,assessment,tmp_path) is (mutation in {'none','help_only'})


def template_fixture():
    import hashlib
    before = {'main.tex': b'old'}
    after = {'main.tex': b'new', 'sn-jnl.cls': b'publisher class'}
    assets = {'sn-jnl.cls': hashlib.sha256(after['sn-jnl.cls']).hexdigest()}
    return before, after, {'template_asset_sha256': assets}, {
        'url': 'https://cms-resources.apps.public.k8s.springernature.io/template',
        'files': dict(assets)}, {'template_assets_reviewed': ['sn-jnl.cls']}


def test_exact_publisher_asset_in_targeted_addendum():
    rows = t._cumulative_manuscript_delta(*template_fixture())
    assert [r['path'] for r in rows] == ['manuscript/main.tex', 'manuscript/sn-jnl.cls']
    assert rows[1]['before_sha256'] is None


@pytest.mark.parametrize('mutation', ['hash', 'missing_authorization', 'missing_review',
    'duplicate_review', 'wrong_publisher', 'removed_source', 'new_science', 'changed_asset'])
def test_template_addendum_fails_closed(mutation):
    before, after, auth, provenance, assessment = template_fixture()
    if mutation == 'hash': auth['template_asset_sha256']['sn-jnl.cls'] = '0' * 64
    if mutation == 'missing_authorization': auth.clear()
    if mutation == 'missing_review': assessment.clear()
    if mutation == 'duplicate_review': assessment['template_assets_reviewed'] *= 2
    if mutation == 'wrong_publisher': provenance['url'] = 'https://evil.test/template'
    if mutation == 'removed_source': after.pop('main.tex')
    if mutation == 'new_science': after['new-proof.tex'] = b'new science'
    if mutation == 'changed_asset': after['sn-jnl.cls'] += b'tampered'
    with pytest.raises(ValueError):
        t._cumulative_manuscript_delta(before, after, auth, provenance, assessment)


@pytest.mark.parametrize('tamper', [False, True])
def test_integrity_archive_rebinding_is_not_code_permission(tmp_path, tamper):
    import hashlib, zipfile
    paths=[]
    for v in ['0.2.18', '0.2.19']:
        manifest=('version '+v).encode()
        script=('EXPECTED_BUNDLE_MANIFEST_SHA256 = "'+hashlib.sha256(manifest).hexdigest()+'"\nVERSION="'+v+'"\nassert check()\n').encode()
        if tamper and v == '0.2.19': script=script.replace(b'assert check()', b'assert True')
        p=tmp_path/(v+'.zip');paths.append(p)
        with zipfile.ZipFile(p,'w') as z:
            base='p-support-v'+v+'/support-materials/public-support-v'+v+'/'
            z.writestr(base+'evidence_bundle_manifest.json',manifest)
            z.writestr(base+'verify_support_bundle.py',script)
    assert t._integrity_rebinding_from_archives(
        'support-materials/public-support-v{version}/verify_support_bundle.py',
        *paths, '0.2.18', '0.2.19') is (not tamper)


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
    assert not t._documentary_support_path('support/proofs.tex')


def tex_prose_fixture(tmp_path, *, old_paragraph=None, new_paragraph=None, context='',
                      heading=r'\section{Packing}\label{sec:packing}'):
    import difflib, hashlib, zipfile
    old_paragraph = old_paragraph or 'The rooted construction repeats a one vertex cost at separated centers.'
    new_paragraph = new_paragraph or ('The rooted construction deletes one path neighbor at an endpoint center\n'
                                      'and two at an internal center.')
    body = ('\\begin{document}\n' + context + heading + '\n' + old_paragraph + '\n\n'
            '\\begin{theorem}\nThe cost is $c_i=1$ at an endpoint and $c_i=2$ internally.\n'
            '\\end{theorem}\n\\begin{proof}\nDelete the stated neighbors.\n\\end{proof}\n'
            '\\end{document}\n')
    old_main = ('\\documentclass{article}\n' + body).encode()
    old_support = ('\\documentclass[11pt]{article}\n' + body).encode()
    new_main = old_main.replace(old_paragraph.encode(), new_paragraph.encode())
    new_support = old_support.replace(old_paragraph.encode(), new_paragraph.encode())
    support_name = 'support/evidence/public-support-v2.1.0/proofs.tex'
    main_name = 'manuscript/main.tex'
    digest = lambda value: hashlib.sha256(value).hexdigest()
    entry = {'path': support_name, 'before_sha256': digest(old_support), 'after_sha256': digest(new_support),
             'manuscript_path': main_name, 'manuscript_before_sha256': digest(old_main),
             'manuscript_after_sha256': digest(new_main), 'before_paragraph': old_paragraph,
             'after_paragraph': new_paragraph}
    assessment = {key: value for key, value in entry.items() if key not in {'before_paragraph', 'after_paragraph'}}
    assessment.update(both_diffs_reviewed=True, scientific_content_unchanged=True,
                      reason='Both preview paragraphs now state the endpoint and internal costs already in the unchanged theorem.')
    delta = []
    for area, name, old, new in [('manuscript', main_name, old_main, new_main),
                                ('support', support_name, old_support, new_support)]:
        for prefix, value in [('before/', old), ('', new)]:
            path = tmp_path / (prefix + name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        diff = ''.join(difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True),
                       fromfile='before/' + name, tofile=name, n=12)).encode()
        (tmp_path / (area + '-tex-prose.diff')).write_bytes(diff)
        assessment[area + '_diff_sha256'] = digest(diff)
        delta.append({'path': name, 'before_sha256': digest(old), 'after_sha256': digest(new)})
    archives = []
    for name, value in [('old.zip', old_support), ('new.zip', new_support)]:
        path = tmp_path / name
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('p-support-v2.1.0/' + support_name[8:], value)
            archive.writestr('p-support-v2.1.0/evidence/public-support-v2.1.0/code.py', b'unchanged science')
            archive.writestr('p-support-v2.1.0/evidence/public-support-v2.1.0/README.md', b'unchanged documentation')
        archives.append(path)
    before = {'main.tex': old_main, 'references.tex': b'unchanged bibliography'}
    reviewed = {**before, 'main.tex': new_main}
    return dict(authorization={'support_tex_prose_only_changes': [entry]},
                assessment={'support_tex_prose_only_reviewed': [assessment]}, packet=tmp_path,
                before=before, reviewed=reviewed, final=dict(reviewed), delta=delta,
                old_archive=archives[0], new_archive=archives[1], old_version='2.1.0', new_version='2.1.0',
                old_inventory=t._support_digests(archives[0], '2.1.0'),
                new_inventory=t._support_digests(archives[1], '2.1.0'))


def test_exact_mirrored_tex_prose_requires_actual_archives_and_independent_diffs(tmp_path):
    bundle = tex_prose_fixture(tmp_path)
    assert t._validated_support_tex_prose_changes(**bundle) == {
        'evidence/public-support-v{version}/proofs.tex': bundle['delta'][1]}
    # The opt-in does not turn TeX into general supporting documentation.
    assert not t._documentary_support_path('evidence/public-support-v2.1.0/proofs.tex')


@pytest.mark.parametrize('mutation', [
    'no_authorization', 'no_assessment', 'duplicate_authorization', 'duplicate_assessment',
    'negative_assessment', 'uninspected_diff', 'no_reason', 'wrong_support_hash', 'wrong_main_hash',
    'assessment_hash', 'missing_source', 'packet_tamper', 'missing_diff', 'invented_diff',
    'wrong_diff_hash', 'extra_delta', 'omitted_delta', 'support_path_traversal',
    'wrong_manuscript_path', 'postreview_main', 'postreview_other_file', 'template_change',
    'main_baseline_tamper', 'support_archive_tamper', 'duplicate_archive_member',
    'archive_suffix_impostor', 'paragraph_mirror',
])
def test_mirrored_tex_prose_fails_closed_on_binding_and_review_tampering(tmp_path, mutation):
    import zipfile
    bundle = tex_prose_fixture(tmp_path)
    auth = bundle['authorization']['support_tex_prose_only_changes']
    inspected = bundle['assessment']['support_tex_prose_only_reviewed']
    support = auth[0]['path']
    if mutation == 'no_authorization': bundle['authorization'].clear()
    if mutation == 'no_assessment': bundle['assessment'].clear()
    if mutation == 'duplicate_authorization': auth.append(dict(auth[0]))
    if mutation == 'duplicate_assessment': inspected.append(dict(inspected[0]))
    if mutation == 'negative_assessment': inspected[0]['scientific_content_unchanged'] = False
    if mutation == 'uninspected_diff': inspected[0]['both_diffs_reviewed'] = False
    if mutation == 'no_reason': inspected[0]['reason'] = ''
    if mutation in {'wrong_support_hash', 'wrong_main_hash'}:
        field = 'before_sha256' if mutation == 'wrong_support_hash' else 'manuscript_before_sha256'
        auth[0][field] = inspected[0][field] = '0' * 64
    if mutation == 'assessment_hash': inspected[0]['after_sha256'] = '0' * 64
    if mutation == 'missing_source': (tmp_path / ('before/' + support)).unlink()
    if mutation == 'packet_tamper': (tmp_path / support).write_text('packet differs from actual support ZIP')
    if mutation == 'missing_diff': (tmp_path / 'support-tex-prose.diff').unlink()
    if mutation == 'invented_diff': (tmp_path / 'manuscript-tex-prose.diff').write_text('approved')
    if mutation == 'wrong_diff_hash': inspected[0]['support_diff_sha256'] = '0' * 64
    if mutation == 'extra_delta': bundle['delta'].append({'path': 'support/README.md'})
    if mutation == 'omitted_delta': bundle['delta'].pop()
    if mutation == 'support_path_traversal': auth[0]['path'] = inspected[0]['path'] = 'support/../proofs.tex'
    if mutation == 'wrong_manuscript_path': auth[0]['manuscript_path'] = inspected[0]['manuscript_path'] = 'manuscript/other.tex'
    if mutation == 'postreview_main': bundle['final']['main.tex'] += b'after review'
    if mutation == 'postreview_other_file': bundle['final']['references.tex'] += b'after review'
    if mutation == 'template_change':
        bundle['reviewed']['template.cls'] = bundle['final']['template.cls'] = b'new class'
    if mutation == 'main_baseline_tamper': bundle['before']['main.tex'] += b'baseline changed'
    if mutation in {'support_archive_tamper', 'duplicate_archive_member', 'archive_suffix_impostor'}:
        path = bundle['new_archive']
        value = (tmp_path / support).read_bytes()
        with zipfile.ZipFile(path, 'w') as archive:
            name = 'p-support-v2.1.0/' + support[8:]
            if mutation == 'archive_suffix_impostor': name = 'p-support-v2.1.0/impostor/' + support[8:]
            archive.writestr(name, value + (b'tampered' if mutation == 'support_archive_tamper' else b''))
            if mutation == 'duplicate_archive_member':
                archive.writestr('other-support-v2.1.0/' + support[8:], value)
    if mutation == 'paragraph_mirror': auth[0]['after_paragraph'] += ' Different wording.'
    with pytest.raises(ValueError):
        t._validated_support_tex_prose_changes(**bundle)


@pytest.mark.parametrize('paragraph', [
    'The cost is $2$.', r'The cost is \(2\).', r'The cost is \two.',
    'The cost is {two}.', 'The cost is two% hidden', 'The cost is ^^32.',
    'The cost is two & more.', 'The cost is two\tmore.', 'The cost is two\n\nMore prose.',
    'The cost is two\x00.', 'The cost is twó.',
])
def test_tex_prose_cannot_introduce_math_commands_or_control_syntax(tmp_path, paragraph):
    bundle = tex_prose_fixture(tmp_path, new_paragraph=paragraph)
    with pytest.raises(ValueError):
        t._validated_support_tex_prose_changes(**bundle)


@pytest.mark.parametrize('context', [
    '\\begin{proof}\n', '\\begin{customtheorem}\n', '\\begin{remark}\n',
    '\\begin{frontmatter}\n', '\\begin {proof}\n', '\\begin % hidden\n {proof}\n',
    '\\begin{proof}\n% \\end{proof}\n', r'\begin{proof}' + '\n' + r'\\% \end{proof}' + '\n',
    '{\n', '\\somecommand{\n', '$\n', '$$\n', '\\[\n', '\\(\n',
    '\\begingroup\n', '\\bgroup\n', '\\everypar{macro}\n',
    '\\catcode`X=0\n', '\\csname begin\\endcsname{proof}\n',
    '\\verb|dynamic syntax|\n', '\\scantokens{dynamic}\n', '^^5cbegin{proof}\n',
    '\\proof\n', '\\capture\n', '\\long\\def\\capture#1\\STOP{#1}\n\\capture\n',
    '\\end{document}\n\\begin{document}\n', '\\endinput\n', '\\stop\n',
    '\\begin{verbatim}\n\\end{verbatim}\n', '\\begin{lstlisting}\n\\end{lstlisting}\n',
    '\r', '\x00',
])
def test_mirrored_plain_paragraph_cannot_hide_inside_scientific_or_dynamic_tex(tmp_path, context):
    bundle = tex_prose_fixture(tmp_path, context=context)
    with pytest.raises(ValueError):
        t._validated_support_tex_prose_changes(**bundle)


def test_tex_context_handles_real_comments_and_escaped_percent():
    assert t._tex_document_body('\\begin{document}\n% \\begin{proof}\n')
    assert t._tex_document_body('\\begin{document}\n\\% ordinary percent\n')
    assert not t._tex_document_body('\\begin{document}\n\\begin{proof}\n\\\\% \\end{proof}\n')
    assert not t._tex_document_body('\\long\\def\\capture#1\\STOP{#1}\n\\begin{document}\n\\capture\n')
    assert not t._tex_document_body('\\newcommand{\\section}{capture}\n\\begin{document}\n')
    assert not t._tex_document_body('\\let\\section\\proof\n\\begin{document}\n')


@pytest.mark.parametrize('mutation', ['extra_hunk', 'protected_theorem', 'label', 'duplicate_paragraph', 'partial_paragraph'])
def test_exact_prose_replacement_rejects_other_source_edits_even_if_reviewer_approves(tmp_path, mutation):
    import difflib, hashlib
    bundle = tex_prose_fixture(tmp_path)
    old, new = bundle['before']['main.tex'], bundle['reviewed']['main.tex']
    if mutation == 'extra_hunk': new += b'Unrelated prose.\n'
    if mutation == 'protected_theorem': new = new.replace(b'$c_i=2$', b'$c_i=3$')
    if mutation == 'label': new = new.replace(b'sec:packing', b'sec:other')
    if mutation == 'duplicate_paragraph':
        paragraph = bundle['authorization']['support_tex_prose_only_changes'][0]['before_paragraph'].encode()
        old += paragraph
    if mutation == 'partial_paragraph': old = old.replace(b'The rooted', b'Additional text. The rooted')
    bundle['before']['main.tex'], bundle['reviewed']['main.tex'], bundle['final']['main.tex'] = old, new, new
    for prefix, value in [('before/', old), ('', new)]:
        (tmp_path / (prefix + 'manuscript/main.tex')).write_bytes(value)
    digest = lambda value: hashlib.sha256(value).hexdigest()
    entry = bundle['authorization']['support_tex_prose_only_changes'][0]
    inspected = bundle['assessment']['support_tex_prose_only_reviewed'][0]
    entry['manuscript_before_sha256'] = inspected['manuscript_before_sha256'] = digest(old)
    entry['manuscript_after_sha256'] = inspected['manuscript_after_sha256'] = digest(new)
    bundle['delta'][0].update(before_sha256=digest(old), after_sha256=digest(new))
    diff = ''.join(difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True),
                  fromfile='before/manuscript/main.tex', tofile='manuscript/main.tex', n=12)).encode()
    (tmp_path / 'manuscript-tex-prose.diff').write_bytes(diff)
    inspected['manuscript_diff_sha256'] = digest(diff)
    with pytest.raises(ValueError):
        t._validated_support_tex_prose_changes(**bundle)


@pytest.mark.parametrize('mutation', ['proof', 'math', 'label', 'extra_hunk', 'different_wrapping'])
def test_support_tex_cannot_hide_other_changes_behind_approved_full_hashes(tmp_path, mutation):
    import difflib, hashlib, zipfile
    bundle = tex_prose_fixture(tmp_path)
    entry = bundle['authorization']['support_tex_prose_only_changes'][0]
    inspected = bundle['assessment']['support_tex_prose_only_reviewed'][0]
    name = entry['path']
    old = (tmp_path / ('before/' + name)).read_bytes()
    new = (tmp_path / name).read_bytes()
    if mutation == 'proof': new = new.replace(b'Delete the stated neighbors.', b'Use an unstated assumption.')
    if mutation == 'math': new = new.replace(b'$c_i=2$', b'$c_i=3$')
    if mutation == 'label': new = new.replace(b'sec:packing', b'sec:other')
    if mutation == 'extra_hunk': new += b'Unrelated supporting claim.\n'
    if mutation == 'different_wrapping': new = new.replace(b'center\nand two', b'center and\ntwo')
    archive_path = bundle['new_archive']
    with zipfile.ZipFile(archive_path) as archive:
        members = {item.filename: archive.read(item) for item in archive.infolist()}
    members['p-support-v2.1.0/' + name[8:]] = new
    with zipfile.ZipFile(archive_path, 'w') as archive:
        for member, value in members.items(): archive.writestr(member, value)
    bundle['new_inventory'] = t._support_digests(archive_path, '2.1.0')
    (tmp_path / name).write_bytes(new)
    digest = lambda value: hashlib.sha256(value).hexdigest()
    entry['after_sha256'] = inspected['after_sha256'] = bundle['delta'][1]['after_sha256'] = digest(new)
    diff = ''.join(difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True),
                  fromfile='before/' + name, tofile=name, n=12)).encode()
    (tmp_path / 'support-tex-prose.diff').write_bytes(diff)
    inspected['support_diff_sha256'] = digest(diff)
    with pytest.raises(ValueError):
        t._validated_support_tex_prose_changes(**bundle)


@pytest.mark.parametrize('mutation', ['science', 'documentation', 'added', 'removed'])
def test_complete_support_inventory_stays_fixed_during_tex_prose_closeout(tmp_path, mutation):
    import zipfile
    bundle = tex_prose_fixture(tmp_path)
    path = bundle['new_archive']
    with zipfile.ZipFile(path) as archive:
        members = {item.filename: archive.read(item) for item in archive.infolist()}
    base = 'p-support-v2.1.0/evidence/public-support-v2.1.0/'
    if mutation == 'science': members[base + 'code.py'] += b'changed science'
    if mutation == 'documentation': members[base + 'README.md'] += b'unreviewed statement'
    if mutation == 'added': members[base + 'extra.tex'] = b'new proof'
    if mutation == 'removed': del members[base + 'code.py']
    with zipfile.ZipFile(path, 'w') as archive:
        for name, value in members.items(): archive.writestr(name, value)
    bundle['new_inventory'] = t._support_digests(path, '2.1.0')
    with pytest.raises(ValueError, match='other supporting inputs'):
        t._validated_support_tex_prose_changes(**bundle)


def repackaging_fixture(tmp_path):
    import hashlib, json
    base = 'support-materials/public-support-v{version}/'
    digest = lambda value: hashlib.sha256(value).hexdigest()
    old = {base+'src/science.py': digest(b'science'), base+'requirements.txt': digest(b'deps'),
           base+'certificates/result.json.gz': digest(b'generated')}
    payloads = {base+'src/science.py': b'science', base+'requirements.txt': b'deps',
                base+'reproduce.py': b'orchestration'}
    new = {n:digest(v) for n,v in payloads.items()}
    for n,v in payloads.items():
        p=tmp_path/'current-support'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(v)
    changes=[{'path':n,'before_sha256':old.get(n),'after_sha256':new.get(n)}
             for n in sorted(set(old)|set(new)) if old.get(n)!=new.get(n)]
    inventory={'before':old,'after':new,'changes':changes,'baseline_archive_sha256':'old','current_archive_sha256':'new'}
    path=tmp_path/'support-repackaging.json';path.write_text(json.dumps(inventory))
    sha=t.m._sha(path)
    auth={'actor':'user','confirmed':True,'quote':'Code-first packaging and targeted review approved',
          'scope':'code_first_repackaging_targeted_review','inventory_sha256':sha}
    assessment={'inventory_sha256':sha,'ready':True,'unchanged_scientific_code':True,
                'no_required_input_lost':True,'documentation_matches_manuscript':True,
                'changed_paths_reviewed':[r['path'] for r in changes],'reason':'Independent trace and exact inventory inspected'}
    return old,new,auth,assessment


def test_exact_independently_reviewed_repackaging(tmp_path):
    old,new,auth,assessment=repackaging_fixture(tmp_path)
    t._validate_code_first_repackaging(old,new,tmp_path,auth,assessment,'old','new')


@pytest.mark.parametrize('mutation', ['no_authorization','wrong_inventory','missing_path',
    'duplicate_path','input_lost','science_changed','source_not_shown','archive_changed'])
def test_repackaging_fails_closed(tmp_path,mutation):
    old,new,auth,assessment=repackaging_fixture(tmp_path)
    if mutation=='no_authorization':auth['confirmed']=False
    if mutation=='wrong_inventory':assessment['inventory_sha256']='other'
    if mutation=='missing_path':assessment['changed_paths_reviewed'].pop()
    if mutation=='duplicate_path':assessment['changed_paths_reviewed'].append(assessment['changed_paths_reviewed'][0])
    if mutation=='input_lost':assessment['no_required_input_lost']=False
    if mutation=='science_changed':new['support-materials/public-support-v{version}/src/science.py']='tampered'
    if mutation=='source_not_shown':(tmp_path/'current-support/support-materials/public-support-v{version}/reproduce.py').unlink()
    with pytest.raises(ValueError):
        t._validate_code_first_repackaging(old,new,tmp_path,auth,assessment,'old','bad' if mutation=='archive_changed' else 'new')


@pytest.mark.parametrize('mutation', ['modified_science','removed_science','new_science','changed_dependencies'])
def test_reviewer_approval_cannot_waive_scientific_source_boundary(tmp_path, mutation):
    import json
    old,new,auth,assessment=repackaging_fixture(tmp_path)
    base='support-materials/public-support-v{version}/'
    if mutation=='modified_science':new[base+'src/science.py']='different'
    if mutation=='removed_science':new.pop(base+'src/science.py')
    if mutation=='new_science':new[base+'src/new.py']='new'
    if mutation=='changed_dependencies':new[base+'requirements.txt']='other dependency'
    changes=[{'path':n,'before_sha256':old.get(n),'after_sha256':new.get(n)}
             for n in sorted(set(old)|set(new)) if old.get(n)!=new.get(n)]
    path=tmp_path/'support-repackaging.json'
    path.write_text(json.dumps({'before':old,'after':new,'changes':changes,
                               'baseline_archive_sha256':'old','current_archive_sha256':'new'}))
    auth['inventory_sha256']=assessment['inventory_sha256']=t.m._sha(path)
    assessment['changed_paths_reviewed']=[r['path'] for r in changes]
    with pytest.raises(ValueError,match='scientific source|new support input'):
        t._validate_code_first_repackaging(old,new,tmp_path,auth,assessment,'old','new')


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


def derived_fixture(tmp_path, monkeypatch):
    import hashlib
    import json
    import zipfile
    sha = lambda value: hashlib.sha256(value).hexdigest()
    before = {'main.tex': b'other document', 'earlier.tex': b'fixed document',
              'included.tex': b'unchanged science', 'figures/plot.pdf': b'unchanged figure',
              'references.bib': b'note={v5 (October 2022)}',
              'earlier.bbl': b'v5\n (October 2022).', 'earlier.pdf': b'%PDF-baseline'}
    after = dict(before, **{'main.tex': b'independently reviewed change',
                           'references.bib': b'note={v5 (29 September 2022)}',
                           'earlier.bbl': b'v5 (29\n September 2022).', 'earlier.pdf': b'%PDF-reviewed'})
    texts = {b'%PDF-baseline': 'science\nOctober 2022\n',
             b'%PDF-reviewed': 'science\n29 September 2022\n'}
    monkeypatch.setattr(t, '_pdf_text', lambda value: texts[value])
    def bind(name, value):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return {'path': name, 'sha256': sha(value)}
    def archive(name, sources):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, 'w') as z:
            for n, value in sources.items():
                z.writestr(n, value)
        return {'path': name, 'sha256': t.m._sha(path)}
    proof = {'schema_version': 'openlabs.derived_document_date_build.v1',
             'complete_snapshots': {stage: archive(stage + '-full.zip', sources)
                                    for stage, sources in [('baseline', before), ('reviewed', after)]},
             'builds': []}
    for stage in ['baseline', 'reviewed', 'standalone']:
        sources = before if stage == 'baseline' else after
        build = {'stage': stage, 'input_archive': archive(stage + '/inputs.zip', t._clean_build_inputs(sources))}
        for key, value in {
            'pdf': sources['earlier.pdf'], 'text': texts[sources['earlier.pdf']].encode(),
            'recorder': ('PWD /build/' + stage + '\nINPUT earlier.tex\nINPUT included.tex\n'
                         'INPUT figures/plot.pdf\nINPUT earlier.bbl\nINPUT earlier.aux\n'
                         'INPUT /usr/share/texlive/article.cls\n').encode(),
            'log': b'Output written on earlier.pdf (1 page, 123 bytes).\n',
            'bibliography_log': b'Database file #1: references.bib\n', 'bbl': sources['earlier.bbl'],
        }.items():
            build[key] = bind(stage + '/' + key, value)
        proof['builds'].append(build)
    changes = [{'path': 'manuscript/' + n, 'before_sha256': sha(before[n]), 'after_sha256': sha(after[n])}
               for n in ['earlier.bbl', 'references.bib']]
    update = {'path': 'manuscript/earlier.pdf', 'source': 'manuscript/earlier.tex',
              'before_sha256': sha(before['earlier.pdf']), 'after_sha256': sha(after['earlier.pdf']),
              'source_sha256': sha(before['earlier.tex']), 'input_changes': changes,
              'date_correction': {'before': 'October 2022', 'after': '29 September 2022'},
              'evidence_sha256': ''}
    auth = {'derived_document_updates': [update]}
    assessment = {'derived_document_updates_reviewed': [
        {'update': deepcopy(update), 'evidence_sha256': '', 'ready': True,
         'reason': 'Inspected complete snapshots, the only date change, source dependencies and real builds.'}]}
    def seal():
        digest = bind('derived-document-proof.json', (json.dumps(proof) + '\n').encode())['sha256']
        update['evidence_sha256'] = digest
        assessment['derived_document_updates_reviewed'][0]['update'] = deepcopy(update)
        assessment['derived_document_updates_reviewed'][0]['evidence_sha256'] = digest
    seal()
    return before, after, auth, assessment, proof, bind, archive, seal, texts


def test_derived_date_update_requires_real_bound_inputs(tmp_path, monkeypatch):
    before, after, auth, assessment, *_ = derived_fixture(tmp_path, monkeypatch)
    row = t._derived_document_delta(before, after, auth, assessment, tmp_path)
    assert row == {k: auth['derived_document_updates'][0][k]
                   for k in ('path', 'before_sha256', 'after_sha256')}
    # The ordinary minor protocol and the post-addendum final delta stay strict.
    with pytest.raises(ValueError, match='non-text'):
        t.m._deltas(before, after, 'manuscript')
    final = dict(after, **{'earlier.pdf': b'%PDF-further-change'})
    with pytest.raises(ValueError, match='non-text'):
        t.m._deltas(after, final, 'manuscript')


def test_empty_assessment_preflight_checks_machine_evidence_but_stays_blocked(tmp_path, monkeypatch):
    before, after, auth, _, _, _, _, _, texts = derived_fixture(tmp_path, monkeypatch)
    extracted = []
    def extract(value):
        extracted.append(value)
        return texts[value]
    monkeypatch.setattr(t, '_pdf_text', extract)
    with pytest.raises(ValueError, match='independent derived-document assessment missing'):
        t._derived_document_delta(before, after, auth, {}, tmp_path)
    assert len(extracted) == 6  # Three real build PDFs plus each canonical counterpart.
    after['references.bib'] += b' extra content'
    with pytest.raises(ValueError, match='derived input hash differs'):
        t._derived_document_delta(before, after, auth, {}, tmp_path)


@pytest.mark.parametrize('mutation', [
    'missing_authorization', 'duplicate_output', 'missing_review', 'review_blocks', 'review_wrong_hash',
    'wrong_output_hash', 'changed_tex', 'changed_included_tex', 'changed_figure', 'new_output',
    'wrong_date', 'bib_science', 'bbl_science', 'proof_tamper', 'proof_symlink', 'input_tamper', 'false_text',
    'missing_build', 'same_directory', 'unbound_input', 'wrong_bibliography', 'build_error',
    'unreviewed_snapshot', 'extra_pdf_text', 'recorder_traversal',
])
def test_derived_date_update_fails_closed(tmp_path, monkeypatch, mutation):
    before, after, auth, assessment, proof, bind, archive, seal, texts = derived_fixture(tmp_path, monkeypatch)
    update = auth['derived_document_updates'][0]
    if mutation == 'missing_authorization': auth.clear()
    if mutation == 'duplicate_output': auth['derived_document_updates'] *= 2
    if mutation == 'missing_review': assessment.clear()
    if mutation == 'review_blocks': assessment['derived_document_updates_reviewed'][0]['ready'] = False
    if mutation == 'review_wrong_hash': assessment['derived_document_updates_reviewed'][0]['evidence_sha256'] = '0' * 64
    if mutation == 'wrong_output_hash': update['after_sha256'] = '0' * 64
    if mutation == 'changed_tex': after['earlier.tex'] = b'different science'
    if mutation in {'changed_included_tex', 'changed_figure'}:
        name = 'included.tex' if mutation == 'changed_included_tex' else 'figures/plot.pdf'
        after[name] = b'different scientific input'
        proof['complete_snapshots']['reviewed'] = archive('reviewed-full.zip', after)
        for build in proof['builds'][1:]:
            build['input_archive'] = archive(build['stage'] + '/inputs.zip', t._clean_build_inputs(after))
        seal()
    if mutation == 'new_output': before.pop('earlier.pdf')
    if mutation == 'wrong_date': update['date_correction']['after'] = '30 September 2022'
    if mutation in {'bib_science', 'bbl_science'}:
        import hashlib
        n = 'references.bib' if mutation == 'bib_science' else 'earlier.bbl'
        after[n] += b' changed theorem'
        next(r for r in update['input_changes'] if r['path'] == 'manuscript/' + n)['after_sha256'] = hashlib.sha256(after[n]).hexdigest()
    if mutation == 'proof_tamper': (tmp_path / 'derived-document-proof.json').write_text('{}')
    if mutation == 'proof_symlink':
        path = tmp_path / 'derived-document-proof.json'
        moved = tmp_path / 'moved-proof.json'
        path.rename(moved)
        path.symlink_to(moved)
    if mutation == 'input_tamper': (tmp_path / 'reviewed/inputs.zip').write_bytes(b'changed')
    if mutation == 'false_text':
        proof['builds'][1]['text'] = bind('reviewed/text', b'author asserted different text')
        seal()
    if mutation == 'missing_build': proof['builds'].pop(); seal()
    if mutation == 'same_directory':
        proof['builds'][2]['recorder'] = proof['builds'][1]['recorder']; seal()
    if mutation == 'unbound_input':
        p = tmp_path / 'reviewed/recorder'
        proof['builds'][1]['recorder'] = bind('reviewed/recorder', p.read_bytes() + b'INPUT /private/unreviewed.tex\n')
        seal()
    if mutation == 'recorder_traversal':
        p = tmp_path / 'reviewed/recorder'
        proof['builds'][1]['recorder'] = bind('reviewed/recorder', p.read_bytes() + b'INPUT /usr/share/texlive/../../../private/unreviewed.tex\n')
        seal()
    if mutation == 'wrong_bibliography':
        proof['builds'][1]['bibliography_log'] = bind('reviewed/bibliography_log', b'Database file #1: hidden.bib\n')
        seal()
    if mutation == 'build_error':
        proof['builds'][1]['log'] = bind('reviewed/log', b'! Compilation failed\n'); seal()
    if mutation == 'unreviewed_snapshot':
        proof['complete_snapshots']['baseline'] = proof['complete_snapshots']['reviewed']; seal()
    if mutation == 'extra_pdf_text':
        texts[b'%PDF-reviewed'] += 'new numerical result'
        for build in proof['builds'][1:]:
            build['text'] = bind(build['stage'] + '/text', texts[b'%PDF-reviewed'].encode())
        seal()
    with pytest.raises(ValueError):
        t._derived_document_delta(before, after, auth, assessment, tmp_path)


@pytest.mark.parametrize('mutation', ['none', 'current_pdf_overlay', 'omitted_ancillary', 'wrong_clean_byte', 'wrong_main'])
def test_complete_snapshot_replay_uses_its_own_ancillary_bytes(mutation):
    old = {'main.tex': b'old main', 'earlier.pdf': b'old ancillary'}
    clean = {'main.tex': b'old main'}
    pdf = b'old main PDF'
    expected = t.m._snapshot(old, pdf)
    complete = dict(old)
    if mutation == 'current_pdf_overlay': complete['earlier.pdf'] = b'new ancillary'
    if mutation == 'omitted_ancillary': complete.pop('earlier.pdf')
    if mutation == 'wrong_clean_byte': clean['main.tex'] = b'new main'
    if mutation == 'wrong_main': pdf = b'new main PDF'
    if mutation == 'none':
        assert t._complete_snapshot_replay(complete, clean, pdf, expected, old) == old
    else:
        with pytest.raises(ValueError):
            t._complete_snapshot_replay(complete, clean, pdf, expected, old)


def test_pdf_text_is_extracted_from_actual_pdf_bytes():
    # A complete one-page PDF exercises the external extractor without requiring
    # a TeX build or treating an author-supplied .txt as the PDF's content.
    stream = b'BT /F1 12 Tf 72 720 Td (October 2022) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
               b'/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    pdf = b'%PDF-1.4\n'
    offsets = [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += str(number).encode() + b' 0 obj\n' + value + b'\nendobj\n'
    start = len(pdf)
    pdf += b'xref\n0 6\n0000000000 65535 f \n'
    pdf += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    pdf += b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n' + str(start).encode() + b'\n%%EOF\n'
    assert t._pdf_text(pdf).strip() == 'October 2022'
    with pytest.raises(ValueError, match='invalid or oversized'):
        t._pdf_text(b'October 2022')
