from common import *
terms={'terms_url':'https://creativecommons.org/licenses/by-nc-nd/4.0/','reuse_basis':'Current article XML identifies CC BY-NC-ND 4.0; internal noncommercial scientific analysis with attribution; no redistribution. Supersedes old report CC-BY assumption for this audit.'}
fetch('quasarr-source.xlsx','https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41467-026-68780-y/MediaObjects/41467_2026_68780_MOESM6_ESM.xlsx',terms=terms,study='10.1038/s41467-026-68780-y',accession='GSE310760:MOESM6')
for name in ('agarwal','parm'):
    links=json.loads((DATA/f'{name}-all-links.json').read_text())
    print(name,[x for x in links if 'MOESM' in x['href']],flush=True)
fetch('ENCFF631LHA_metadata.json','https://www.encodeproject.org/files/ENCFF631LHA/?format=json')
fetch('ENCSR382BVV_metadata.json','https://www.encodeproject.org/functional-characterization-experiments/ENCSR382BVV/?format=json')
fetch('tan-supplements.zip','https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13320843/supplementaryFiles',limit=64*1024**2,terms=terms,study='10.64898/2026.06.25.734173')
fetch('klein-supplements.zip','https://www.ebi.ac.uk/europepmc/webservices/rest/PMC7727316/supplementaryFiles',limit=64*1024**2,study='10.1038/s41592-020-0965-y')
