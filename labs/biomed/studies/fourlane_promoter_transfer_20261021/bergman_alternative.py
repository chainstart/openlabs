from common import *
import xml.etree.ElementTree as ET,re
p=fetch('bergman-efetch.xml','https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=9262863&retmode=xml',study='10.1038/s41586-022-04877-w')
if p:
    try:
        root=ET.parse(p).getroot();links=[dict(el.attrib) for el in root.iter() if el.tag in ('media','ext-link')];write(DATA/'bergman-links.json',links);print(links[:20],flush=True)
    except Exception as e:print('xml parse error',str(e),flush=True)
p=fetch('bergman-nature.html','https://www.nature.com/articles/s41586-022-04877-w',study='10.1038/s41586-022-04877-w')
if p:
    links=re.findall(r'https[^"\s<>]+MOESM[^"\s<>]+',p.read_text())
    write(DATA/'bergman-nature-links.json',links);print(links,flush=True)
