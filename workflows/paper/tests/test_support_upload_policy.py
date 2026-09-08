from pathlib import Path
import pytest
from paper_writing.support_upload_policy import validate_upload_sources
from paper_writing.support import SupportPackageError

def put(root, name, size=1):
    path=root/name; path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('wb') as stream: stream.truncate(size)
    return path

def test_code_and_small_reference_allowed(tmp_path):
    paths=[put(tmp_path,n) for n in ['src/main.py','requirements.txt','README.md','reference-result.json']]
    assert validate_upload_sources(paths,repo_root=tmp_path)['files']==4

@pytest.mark.parametrize('name',['certificates/n17.json.gz','data.npz','cache/a.json','checkpoints/model.bin','nested.zip','old.TAR'])
def test_generated_and_nested_payload_rejected_even_small(tmp_path,name):
    with pytest.raises(SupportPackageError,match='Code-first'):
        validate_upload_sources([put(tmp_path,name)],repo_root=tmp_path)

def test_renamed_large_payload_rejected(tmp_path):
    with pytest.raises(SupportPackageError,match='file exceeds'):
        validate_upload_sources([put(tmp_path,'innocent.json',10*1024*1024+1)],repo_root=tmp_path)

def test_split_payload_total_rejected(tmp_path):
    paths=[put(tmp_path,f'p{i}.json',9*1024*1024) for i in range(6)]
    with pytest.raises(SupportPackageError,match='source total'):
        validate_upload_sources(paths,repo_root=tmp_path)

@pytest.mark.parametrize('value',[0,-1,True,'500'])
def test_invalid_limits_fail_closed(tmp_path,value):
    with pytest.raises(SupportPackageError,match='positive integers'):
        validate_upload_sources([],repo_root=tmp_path,settings={'support_publication':{'package_policy':{'max_file_bytes':value}}})

def test_configured_count_limit(tmp_path):
    with pytest.raises(SupportPackageError,match='file count'):
        validate_upload_sources([put(tmp_path,'a.py'),put(tmp_path,'b.py')],repo_root=tmp_path,
            settings={'support_publication':{'package_policy':{'max_files':1}}})

def test_zip_compression_does_not_hide_large_members(tmp_path):
    import zipfile
    from paper_writing.support_upload_policy import validate_upload_packages
    path=tmp_path/'support.zip'
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('support/large.json',b'0'*(10*1024*1024+1))
    assert path.stat().st_size<100000
    with pytest.raises(SupportPackageError,match='file exceeds'):
        validate_upload_packages([path],repo_root=tmp_path)

def test_zip_nested_payload_rejected(tmp_path):
    import zipfile
    from paper_writing.support_upload_policy import validate_upload_packages
    path=tmp_path/'support.zip'
    with zipfile.ZipFile(path,'w') as z:z.writestr('support/certificate.json.gz',b'compressed')
    with pytest.raises(SupportPackageError,match='nested archive'):
        validate_upload_packages([path],repo_root=tmp_path)

def test_prepare_blocks_before_git_or_network(tmp_path, monkeypatch):
    import paper_writing.zenodo as zenodo
    path = put(tmp_path, 'certificate.json.gz')
    monkeypatch.setattr(zenodo, 'find_paper_record', lambda *a, **k: {})
    monkeypatch.setattr(zenodo, 'resolve_support_sources', lambda *a, **k: [path])
    monkeypatch.setattr(zenodo, 'load_config', lambda *a, **k: {})
    def forbidden(*a, **k):
        pytest.fail('Rejected payload reached Git or networking')
    monkeypatch.setattr(zenodo, 'validate_git_frozen_paths', forbidden)
    monkeypatch.setattr(zenodo, 'ZenodoClient', forbidden)
    with pytest.raises(SupportPackageError, match='Code-first'):
        zenodo.prepare_zenodo_release('paper', environment='sandbox', token='unused', repo_root=tmp_path)
