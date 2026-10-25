"""Streaming stdlib XLSX reader adapted from promoter_portability_20261021/xlsx.py.
New code clears XML rows; no old entrypoint imported or executed.
"""
import zipfile,xml.etree.ElementTree as E
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
def colnum(s):
    n=0
    for c in s:
        if c.isalpha():n=n*26+ord(c)-64
    return n-1
class Workbook:
    def __init__(self,p):
        self.z=zipfile.ZipFile(p);self.strings=[]
        if 'xl/sharedStrings.xml' in self.z.namelist():
            with self.z.open('xl/sharedStrings.xml') as f:
                for _,el in E.iterparse(f,events=('end',)):
                    if el.tag==f'{{{NS}}}si':
                        self.strings.append(''.join(el.itertext()));el.clear()
        wb=E.fromstring(self.z.read('xl/workbook.xml'));rels=E.fromstring(self.z.read('xl/_rels/workbook.xml.rels'))
        targets={x.attrib['Id']:x.attrib['Target'] for x in rels};self.sheets={}
        for s in wb.find(f'{{{NS}}}sheets'):
            t=targets[s.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
            self.sheets[s.attrib['name']]=t.lstrip('/') if t.startswith('/') else 'xl/'+t
    def rows(self,sheet):
        with self.z.open(self.sheets[sheet]) as f:
            for _,el in E.iterparse(f,events=('end',)):
                if el.tag==f'{{{NS}}}row':
                    row={}
                    for c in el:
                        v=c.find(f'{{{NS}}}v')
                        v=v.text if v is not None else ''.join(c.itertext())
                        if c.attrib.get('t')=='s':v=self.strings[int(v)]
                        row[colnum(c.attrib['r'])]=v
                    out=[row.get(i,'') for i in range(max(row,default=-1)+1)]
                    el.clear();yield out
    def close(self):self.z.close()
