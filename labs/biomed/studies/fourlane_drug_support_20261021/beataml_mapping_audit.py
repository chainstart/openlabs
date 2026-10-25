"""Read small official XLSX metadata with stdlib, without optional dependencies."""
from common import *
import zipfile
import xml.etree.ElementTree as ET
import re

NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
out={}
for filename in ['beataml_waves1to4_sample_mapping.xlsx','beataml_drug_families.xlsx']:
    result={}
    with zipfile.ZipFile(ART/'intake'/('beataml-'+filename)) as z:
        assert sum(i.file_size for i in z.infolist())<64*1024**2
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            strings=[''.join(n.itertext()) for n in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',NS)]
        for file in sorted(z.namelist()):
            if re.fullmatch(r'xl/worksheets/sheet\d+.xml',file):
                rows=[]
                for r in ET.fromstring(z.read(file)).findall('.//m:sheetData/m:row',NS):
                    row={}
                    for c in r.findall('m:c',NS):
                        value=c.find('m:v',NS)
                        if value is not None:
                            text=value.text or '';text=strings[int(text)] if c.attrib.get('t')=='s' else text
                        else:text=''.join(c.find('m:is',NS).itertext()) if c.find('m:is',NS) is not None else ''
                        row[re.sub(r'\d','',c.attrib['r'])]=text
                    rows.append(row)
                header=rows[0];result[file]={'data_rows':len(rows)-1,'header_by_column':header,'nonempty_counts':{name:sum(bool(r.get(k)) for r in rows[1:]) for k,name in header.items()},'no_assay_normalized_viability_values_read':True,'binding_annotations_not_used_as_response_endpoints':True}
    out[filename]=result
write(DATA/'beataml-official-mapping-schema.json',out)
write(DATA/'beataml-mapping-parser-note.json',{'at':now(),'failed_attempt':'pandas.ExcelFile required openpyxl, not installed in locked environment','resolution':'stdlib ZIP/XML reader with64MiB expanded ceiling; no installation, raw inputs unchanged','scientific_result':'metadata availability only'})
print(json.dumps(out,indent=2))
