"""Read bounded publisher xlsx tables without adding shared dependencies."""
import zipfile,xml.etree.ElementTree as ET,re
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
def sheets(path):
    with zipfile.ZipFile(path) as z:
        root=ET.fromstring(z.read('xl/workbook.xml'))
        return [x.attrib['name'] for x in root.findall('m:sheets/m:sheet',NS)]
def rows(path,index=0):
    with zipfile.ZipFile(path) as z:
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            strings=[''.join(e.itertext()) for e in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',NS)]
        root=ET.fromstring(z.read(f'xl/worksheets/sheet{index+1}.xml'))
        for row in root.findall('.//m:row',NS):
            out=[]
            for c in row.findall('m:c',NS):
                col=0
                for a in re.match('[A-Z]+',c.attrib['r'])[0]:col=col*26+ord(a)-64
                while len(out)<col:out.append('')
                v=c.find('m:v',NS)
                val=v.text if v is not None else ''
                if c.attrib.get('t')=='s':val=strings[int(val)]
                elif c.attrib.get('t')=='inlineStr':val=''.join(c.find('m:is',NS).itertext())
                out[col-1]=val
            yield out
