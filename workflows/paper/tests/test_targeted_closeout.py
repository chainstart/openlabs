from copy import deepcopy
import pytest
from paper_writing import targeted_closeout as t


def test_absent_closeout_is_noop(tmp_path):
    assert t.validate_release('p', {}, tmp_path) == []


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
