from common import *
import xml.etree.ElementTree as ET,re
repo='yj-tan/ExP-MPRA';tree=json.loads((ART/'payload/ExP-MPRA_tree.json').read_text());commit=tree['sha']
for x in tree['tree']:
    path=x['path']
    if path.startswith('annotations/') and not path.endswith('.gz') or path.startswith('code/01-dictionary_building/fasta/') or path in ('code/04-Expression/fit_expression_models.R','code/README.md'):
        fetch('tan_'+Path(path).name,f'https://raw.githubusercontent.com/{repo}/{commit}/{path}',study='10.64898/2026.06.25.734173',accession=commit)
for name in ('tan','klein'):
    p=ART/'payload'/f'{name}.xml'
    if p.exists():
        root=ET.parse(p).getroot();out=[]
        for el in root.iter():
            if el.tag in ('p','title'):
                s=' '.join(el.itertext())
                if re.search(r'GSE|github|zenodo|orientation|reverse|[Ll]ibrary|[Dd]ata availability|[Ss]equences were|[Ss]equence length',s):out.append(s)
        (ART/f'{name}-methods-extract.txt').write_text('\n\n'.join(out))
        links=[dict(el.attrib) for el in root.iter() if el.tag in ('ext-link','supplementary-material','media')]
        write(DATA/f'{name}-links.json',links)
for acc in ('GSE301246','GSE334082'):
    fetch(acc+'_inventory.html',f'https://ftp.ncbi.nlm.nih.gov/geo/series/{acc[:-3]}nnn/{acc}/suppl/',accession=acc)
status('new_library_metadata',['PARM/Tan official inventories and author sequences obtained','Klein fulltext retrieved'],['exact reverse-complement audits','design metadata and precision gate'])
