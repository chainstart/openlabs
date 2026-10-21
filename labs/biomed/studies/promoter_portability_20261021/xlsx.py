import zipfile,xml.etree.ElementTree as E
N={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
def sheets(p):
 z=zipfile.ZipFile(p);strings=[]
 if 'xl/sharedStrings.xml' in z.namelist():
  root=E.fromstring(z.read('xl/sharedStrings.xml'));strings=[''.join(x.itertext()) for x in root]
 wb=E.fromstring(z.read('xl/workbook.xml'));rels=E.fromstring(z.read('xl/_rels/workbook.xml.rels'));targets={x.attrib['Id']:x.attrib['Target'] for x in rels}
 out={}
 for s in wb.find('s:sheets',N):
  rid=s.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'];t=targets[rid];t=t.lstrip('/') if t.startswith('/') else 'xl/'+t
  root=E.fromstring(z.read(t));rows=[]
  for r in root.findall('.//s:sheetData/s:row',N):
   row={}
   for c in r:
    v=c.find('s:v',N);v=v.text if v is not None else ''.join(c.find('s:is',N).itertext()) if c.find('s:is',N) is not None else ''
    if c.attrib.get('t')=='s':v=strings[int(v)]
    row[c.attrib['r']]=v
   rows.append(row)
  out[s.attrib['name']]=rows
 return out
