"""Bounded official supplement intake for methods/batch metadata only."""
from common import *
import zipfile

p=fetch('https://www.ebi.ac.uk/europepmc/webservices/rest/PMC9896241/supplementaryFiles','PMC9896241_supplementary.zip',cap=16*1024**2,timeout=180,metadata=dict(provider='Europe PMC',accession='PMC9896241',citation='10.1136/bmjresp-2022-001391',release='Current official supplementary archive',independent_unit='methods document; not additional biological observations',upstream_study_ids=['GSE199949'],terms_url='https://creativecommons.org/licenses/by-nc/4.0/',reuse_basis='Article CC BY-NC4.0; internal attributed methods audit; no redistribution'))
record=dict(at=now(),purpose='Resolve two-library-batch allocation if methods specify it; post-result provenance review only',new_configuration=False)
if p and zipfile.is_zipfile(p):
 with zipfile.ZipFile(p) as z:
  infos=z.infolist();record['inventory']=[{'name':x.filename,'bytes':x.file_size} for x in infos]
  names=[x.filename for x in infos if x.filename.endswith('supp001.pdf')]
  if len(names)==1:
   info=z.getinfo(names[0]);assert info.file_size<10*1024**2
   dest=ART/'methods_supplement.pdf';dest.write_bytes(z.read(names[0]))
   record.update(pdf_path=str(dest),pdf_sha256=sha(dest),archive_sha256=sha(p),expression_supplements_opened=False)
  else:record['status']='No unique methodsPDF in archive'
else:record['status']='Official archive unavailable or not ZIP'
atomic(DATA/'batch_supplement_intake.json',record);print(json.dumps(record))
