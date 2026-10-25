from common import *
import zipfile,xml.etree.ElementTree as ET
for name,url in [('agarwal-tables.zip','https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41586-024-08430-9/MediaObjects/41586_2024_8430_MOESM5_ESM.zip'),('parm-synthetic.xlsx','https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41586-025-10093-z/MediaObjects/41586_2025_10093_MOESM3_ESM.xlsx')]:
    fetch(name,url,limit=256*1024**2,terms={'terms_url':'https://creativecommons.org/licenses/by/4.0/','reuse_basis':'Article supplementary scientific data, internal attributed analysis'},study=name.split('-')[0])
for name in ('agarwal-tables.zip','tan-supplements.zip','klein-supplements.zip'):
    p=ART/'payload'/name
    if p.exists():
        with zipfile.ZipFile(p) as z:
            inv=[dict(name=x.filename,size=x.file_size,compressed=x.compress_size) for x in z.infolist()]
            write(DATA/(name+'-inventory.json'),inv);print(name,inv,flush=True)
root=ET.parse(ART/'payload/bergman.xml').getroot()
for el in root.iter('ext-link'):
    href=el.attrib.get('{http://www.w3.org/1999/xlink}href','')
    if 'github' in href:print('bergman_repo',href,flush=True)
status('new_library_sequence_audit',['Tan exact RC-pair enumeration completed','PARM official Range responses validated; schemas lack insert sequences','new library supplementary payloads obtained'],['full exact-sequence cross-library comparison','three-design scientific gate decisions'],evidence_paths=[str(DATA/'tan-exact-orientation-audit.json'),str(DATA/'exposure-log.json')])
