"""Preserve initial failed outputs, then repair only the sample-ID CSV header."""
from common import *
import shutil,csv
assert not (DATA/'confirmation_open.json').exists()
assert not (DATA/'sample_id_header_repair.json').exists()
archive=ART/'failed_output_sample_id_header';archive.mkdir(exist_ok=False)
changes=[]
for acc in ['GSE184316','GSE150910']:
 p=ART/f'{acc}_scores.csv';before=p.read_bytes();header,tail=before.split(b'\n',1)
 assert header.startswith(b'index,') and b'sample_id' not in header
 after=b'sample_id,'+header[len(b'index,'):]+b'\n'+tail
 for path in [p,ART/f'{acc}_score_record.json',ART/f'{acc}_donor_scores.csv']:
  if path.exists():shutil.copy2(path,archive/path.name)
 p.write_bytes(after)
 assert p.read_bytes().split(b'\n',1)[1]==tail
 rec=json.loads((ART/f'{acc}_score_record.json').read_text())
 rec.update(header_repair_at=now(),original_score_sha256=rec['score_sha256'],score_sha256=sha(p),header_repair_script_sha256=sha(Path(__file__)),numeric_rows_byte_identical=True,initial_output_preserved=str(archive/p.name))
 atomic(ART/f'{acc}_score_record.json',rec)
 changes.append(dict(accession=acc,before_sha256=sha(archive/p.name),after_sha256=sha(p),numeric_rows_byte_identical=True,model_rerun=False))
atomic(DATA/'sample_id_header_repair.json',dict(at=now(),cause='Pandas loc with unnamed Index removes original sample index name; reset_index emitted index',changes=changes,confirmation_opened=False,scientific_configuration_changed=False,bulk_io_fixed_by_explicit_rename_axis=True))
print(json.dumps(changes))
