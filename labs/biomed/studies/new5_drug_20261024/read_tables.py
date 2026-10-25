import zipfile,xml.etree.ElementTree as E,re
M={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
def xlsx_rows(path,sheet='sheet1.xml'):
 with zipfile.ZipFile(path) as z:
  ss=[''.join(x.itertext()) for x in E.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',M)] if 'xl/sharedStrings.xml' in z.namelist() else []
  with z.open('xl/worksheets/'+sheet) as f:
   for event,row in E.iterparse(f,events=['end']):
    if row.tag!='{'+M['m']+'}row':continue
    vals={}
    for c in row.findall('m:c',M):
     ref=c.attrib['r'];col=re.match('[A-Z]+',ref)[0];i=0
     for a in col:i=i*26+ord(a)-64
     v=c.find('m:v',M);v=v.text if v is not None else ''
     if c.attrib.get('t')=='s':v=ss[int(v)] if v else ''
     elif c.attrib.get('t')=='inlineStr':v=''.join(c.find('m:is',M).itertext())
     vals[i-1]=v
    yield [vals.get(i,'') for i in range(max(vals,default=-1)+1)]
    row.clear()
T='urn:oasis:names:tc:opendocument:xmlns:table:1.0';O='urn:oasis:names:tc:opendocument:xmlns:office:1.0';X='urn:oasis:names:tc:opendocument:xmlns:text:1.0'
def ods_rows(path):
 with zipfile.ZipFile(path) as z,z.open('content.xml') as f:
  for event,row in E.iterparse(f,events=['end']):
   if row.tag!='{'+T+'}table-row':continue
   vals=[]
   for c in row:
    if c.tag not in ['{'+T+'}table-cell','{'+T+'}covered-table-cell']:continue
    repeat=int(c.attrib.get('{'+T+'}number-columns-repeated','1'));v=c.attrib.get('{'+O+'}value')
    if v is None:v='\n'.join(''.join(n.itertext()) for n in c.findall('{'+X+'}p'))
    if repeat>256:
     if str(v).strip():raise ValueError('unexpected large nonempty repeat')
     continue
    vals.extend([v]*repeat)
   if any(str(v).strip() for v in vals):yield vals
   row.clear()
