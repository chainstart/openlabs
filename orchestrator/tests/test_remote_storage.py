from pathlib import Path
from types import SimpleNamespace
import importlib.util,json
import pytest

TOOLS=Path(__file__).resolve().parents[2]/'tools/remote-compute'
@pytest.fixture
def storage():
 spec=importlib.util.spec_from_file_location('remote_storage_test',TOOLS/'storage.py')
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
@pytest.fixture
def pool(tmp_path):
 result=[]
 for i,free in [(1,100),(2,200),(3,300)]:
  mount=tmp_path/('ssd'+str(i));root=mount/'openlabs-worker';(root/'jobs').mkdir(parents=True)
  result.append({'id':'ssd'+str(i),'mount':str(mount),'root':str(root),'free':free,'online':True})
 return result

def check(entry):
 if not entry['online']:raise ValueError('SSD offline')
def usage(path):
 i=int(Path(path).parent.name[3:]);return SimpleNamespace(total=1000,free=i*100)

def test_auto_uses_most_free_mounted_ssd(storage,pool):
 path,entry=storage.locate_job('a'*32,entries=pool,checker=check,usage=usage)
 assert entry['id']=='ssd3' and path==Path(pool[2]['root'])/'jobs'/('a'*32)

def test_explicit_volume_overrides_free_space(storage,pool):
 _,entry=storage.locate_job('a'*32,'ssd1',entries=pool,checker=check,usage=usage)
 assert entry['id']=='ssd1'

def test_existing_job_does_not_move_to_freer_disk(storage,pool):
 path=Path(pool[0]['root'])/'jobs'/('a'*32);path.mkdir()
 chosen,entry=storage.locate_job('a'*32,entries=pool,checker=check,usage=usage)
 assert chosen==path and entry['id']=='ssd1'
 with pytest.raises(ValueError,match='differs'):storage.locate_job('a'*32,'ssd2',entries=pool,checker=check,usage=usage)

def test_new_job_skips_offline_disks(storage,pool):
 pool[2]['online']=False
 _,entry=storage.locate_job('a'*32,entries=pool,checker=check,usage=usage)
 assert entry['id']=='ssd2'
 with pytest.raises(ValueError,match='offline'):storage.locate_job('b'*32,'ssd3',entries=pool,checker=check,usage=usage)

def test_index_prevents_reexecution_elsewhere_when_original_disk_offline(storage,pool,tmp_path):
 index=tmp_path/'placements'
 original,entry=storage.locate_job('a'*32,'ssd1',entries=pool,checker=check,usage=usage,index_dir=index)
 assert json.loads((index/('a'*32+'.json')).read_text())['volume']=='ssd1'
 pool[0]['online']=False
 with pytest.raises(ValueError,match='offline'):storage.locate_job('a'*32,entries=pool,checker=check,usage=usage,index_dir=index)
 assert not original.exists() and not (Path(pool[2]['root'])/'jobs'/('a'*32)).exists()

def test_all_offline_refuses_system_disk_fallback(storage,pool):
 for entry in pool:entry['online']=False
 with pytest.raises(ValueError,match='system-disk fallback is forbidden'):
  storage.locate_job('a'*32,entries=pool,checker=check,usage=usage)

def test_duplicate_identity_across_disks_is_not_silently_selected(storage,pool):
 for entry in pool[:2]:(Path(entry['root'])/'jobs'/('a'*32)).mkdir()
 with pytest.raises(ValueError,match='more than one SSD'):
  storage.locate_job('a'*32,entries=pool,checker=check,usage=usage)

def test_unknown_explicit_volume_is_rejected(storage,pool):
 with pytest.raises(ValueError,match='unknown'):
  storage.locate_job('a'*32,'ssd9',entries=pool,checker=check,usage=usage)

def test_real_unmounted_directory_is_rejected(storage,pool):
 with pytest.raises(ValueError,match='not mounted independently'):storage.check(pool[0])

def test_system_device_is_rejected_even_if_marked_mounted(storage,pool,monkeypatch):
 monkeypatch.setattr(Path,'is_mount',lambda path:True)
 monkeypatch.setattr(Path,'stat',lambda path,*args,**kwargs:SimpleNamespace(st_dev=42))
 with pytest.raises(ValueError,match='not mounted independently'):storage.check(pool[0])

def test_inventory_exposes_offline_status_without_claiming_capacity(storage,pool):
 pool[1]['online']=False;items=storage.inventory(pool,checker=check,usage=usage)
 assert items[0]['available'] and items[0]['free_bytes']==100
 assert not items[1]['available'] and 'free_bytes' not in items[1]
