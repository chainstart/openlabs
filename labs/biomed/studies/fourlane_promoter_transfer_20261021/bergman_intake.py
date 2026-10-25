from common import *
mp=ART/'manifests/parm-v2-range-counts.json'
if mp.exists():
    d=json.loads(mp.read_text());p=ART/'payload/parm-v2-range-counts.txt.gz.part'
    d.update(status='stopped_incomplete_metadata_only',stop_reason='Scope decision: raw table contains reference coordinates and counts, not exact insert sequences; additional count bytes do not resolve the original identity gate. The alternative same-coordinate panel must not be relabeled exact inserts.',partial_payload=str(p),partial_bytes=p.stat().st_size,partial_sha256=sha(p));write(mp,d)
repo='broadinstitute/ExP-model-fit'
p=fetch('bergman_repo.json','https://api.github.com/repos/'+repo)
if p:
    branch=json.loads(p.read_text())['default_branch']
    q=fetch('bergman_tree.json',f'https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1')
    if q:
        data=json.loads(q.read_text());print('commit',data.get('sha'));print([(x['path'],x.get('size')) for x in data.get('tree',[])],flush=True)
        for x in data.get('tree',[]):
            if x['path'].lower().endswith('readme.md'):
                fetch('bergman_README.md',f'https://raw.githubusercontent.com/{repo}/{data["sha"]}/{x["path"]}')
fetch('bergman-bioc.json','https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/PMC9262863/unicode')
fetch('bergman-supplements.zip','https://www.ebi.ac.uk/europepmc/webservices/rest/PMC9262863/supplementaryFiles',limit=64*1024**2)
status('alternative_design_gate',['C1 exact DNA intersections completed','C2 six-design orientation data have only two independent paired loci'],['C3 scalar promoter responsiveness: exact identity, endpoint semantics and novelty feasibility'],evidence_paths=[str(DATA/'exact-library-audit.json')])
