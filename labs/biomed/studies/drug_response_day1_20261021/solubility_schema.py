"""Schema-only feasibility audit; never print response labels."""
import json,zipfile,xml.etree.ElementTree as ET
import pandas as pd
from audit import OUT,save
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
def workbook(p):
    result=[]
    with zipfile.ZipFile(p) as z:
        strings=[''.join(e.itertext()) for e in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',NS)] if 'xl/sharedStrings.xml' in z.namelist() else []
        wb=ET.fromstring(z.read('xl/workbook.xml'))
        names=[e.attrib['name'] for e in wb.findall('m:sheets/m:sheet',NS)]
        for n in [n for n in z.namelist() if n.startswith('xl/worksheets/sheet') and n.endswith('.xml')]:
            rows=[]
            with z.open(n) as f:
                count=0
                for _,e in ET.iterparse(f,events=['end']):
                    if e.tag.endswith('}row'):
                        if count<3:
                            row=[]
                            for c in e:
                                v=c.find('m:v',NS); val=None if v is None else v.text
                                if c.attrib.get('t')=='s':val=strings[int(val)]
                                if c.attrib.get('t')=='inlineStr':val=''.join(c.itertext())
                                row.append([c.attrib.get('r'),val])
                            rows.append(row)
                        count+=1;e.clear()
            result.append(dict(member=n,rows=count,header_rows=rows[:1]))
        return dict(sheet_names=names,sheets=result)
def main():
    result={'workbook':workbook(OUT/'ulrich-dataset/dataset.xlsx')}
    for key,file in [('ochem-unseen','OChemUnseen.tab'),('ochem-curated','OChemCurated.tab')]:
        d=pd.read_csv(OUT/key/file,sep='\t');result[key]=dict(rows=len(d),columns=list(d.columns),null_counts={k:int(v) for k,v in d.isna().sum().items()})
    save(OUT/'solubility-schema.json',result);print(json.dumps(result,indent=2))
if __name__=='__main__':main()
