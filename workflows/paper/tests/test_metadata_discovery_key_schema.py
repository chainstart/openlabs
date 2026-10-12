"""Behavioral regressions for optional discovery and work-specific evidence IDs."""
import copy
import json
import httpx
import pytest
from paper_writing import formal_checks as f
from paper_writing.review_launcher import LaunchError


def collect(root, references, declarations=(), handler=None):
    requests=[]
    def transport(request):
        requests.append(str(request.url))
        if handler is not None:
            return handler(request)
        if request.url.host=='api.crossref.org':
            doi=httpx.URL(request.url).path.removeprefix('/works/')
            return httpx.Response(200,json={'message':{'DOI':doi,'title':['Actual work'],
                'author':[{'family':'Author'}]}})
        raise AssertionError('Unexpected optional download: '+str(request.url))
    inv=f.inventory([{'id':'main','text':'Context.'}],references)
    m={'paper_id':'p','formal_check':{'sources':list(declarations)}}
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        sources,errors=f.collect_sources(inv,m,root,root/'evidence',client)
    return inv,sources,errors,requests


@pytest.mark.parametrize('url',['https://publisher.example/paper.pdf',
    'https://publisher.example/paper', 'https://publisher.example/paper.pdf?download=1'])
def test_identified_metadata_skips_implicit_printed_download(tmp_path,url):
    bib=r'\bibitem{a}Author. Actual work. DOI:10.1234/a. '+url
    inv,sources,errors,requests=collect(tmp_path,bib)
    assert errors==[] and len(requests)==1
    assert requests[0].startswith('https://api.crossref.org/works/')
    assert inv['references'][0]['text'].endswith(url)  # Printed link unchanged.
    assert sources[0]['reference_keys']==['a']


def test_catalog_for_unidentified_work_still_discovered(tmp_path):
    def handler(request):
        assert request.url.path=='/catalog'
        return httpx.Response(200,text='Author. Identified catalog title. 2020.',headers={'content-type':'text/plain'})
    inv,sources,errors,requests=collect(tmp_path,
        r'\bibitem{a}Catalog work. https://publisher.example/paper.pdf https://publisher.example/catalog',handler=handler)
    assert requests==['https://publisher.example/catalog'] and errors==[]
    assert sources[0]['kind']=='publisher_catalog'
    assert 'paper.pdf' in inv['references'][0]['text']


def test_missing_metadata_pdf_alone_is_honest_gap_not_download(tmp_path):
    _,sources,errors,requests=collect(tmp_path,r'\bibitem{a}Unknown work. https://publisher.example/paper.pdf')
    assert requests==[] and sources==[]
    assert errors and 'no queryable authoritative bibliographic evidence' in errors[0]


def test_metadata_other_key_does_not_hide_catalog_fallback(tmp_path):
    def handler(request):
        if request.url.host=='api.crossref.org':
            return httpx.Response(200,json={'message':{'DOI':'10.1234/a','title':['Work A'],'author':[{'family':'Author'}]}})
        assert request.url.path=='/catalog-b'
        return httpx.Response(200,text='Work B author title year',headers={'content-type':'text/plain'})
    _,sources,errors,requests=collect(tmp_path,r'\bibitem{a}Work A DOI:10.1234/a. https://publisher.example/a.pdf'
        r'\bibitem{b}Work B https://publisher.example/catalog-b',handler=handler)
    assert errors==[] and len(requests)==2
    assert {tuple(s['reference_keys']) for s in sources}=={('a',),('b',)}


def test_catalog_resolves_doi_provider_outage_but_attempts_remain(tmp_path):
    def handler(request):
        if request.url.host in ['api.crossref.org','api.datacite.org']:
            return httpx.Response(503)
        return httpx.Response(200,text='Author. Exact fallback title. DOI 10.1234/a.',headers={'content-type':'text/plain'})
    _,sources,errors,requests=collect(tmp_path,r'\bibitem{a}Work DOI:10.1234/a. https://publisher.example/catalog',handler=handler)
    assert len(requests)==3 and errors==[]
    assert sources[0]['kind']=='publisher_catalog'
    attempts=json.loads((tmp_path/'evidence/retrieval-failures.json').read_text())
    assert len(attempts)==1 and 'lookup unresolved' in attempts[0]


def test_explicit_primary_source_not_silently_disabled_by_metadata(tmp_path,monkeypatch):
    def handler(request):
        if request.url.host=='api.crossref.org':
            return httpx.Response(200,json={'message':{'DOI':'10.1234/a','title':['Work A'],'author':[{'family':'Author'}]}})
        assert request.url.path=='/original.pdf'
        return httpx.Response(200,content=b'%PDF- fixture original',headers={'content-type':'application/pdf'})
    original=f._text_document
    monkeypatch.setattr(f,'_text_document',lambda body,ct,*args: 'Explicit original text' if body.startswith(b'%PDF-') else original(body,ct,*args))
    _,sources,errors,requests=collect(tmp_path,r'\bibitem{a}Work DOI:10.1234/a. https://publisher.example/original.pdf',
        [{'reference_keys':['a'],'url':'https://publisher.example/original.pdf','kind':'primary_text'}],handler)
    assert errors==[] and len(requests)==2
    assert {s['kind'] for s in sources}=={'primary_text','bibliographic_metadata'}


def reference_row(key,status='verified',evidence=()):
    row={k:'Actual check' for k in f.REFERENCE_SCHEMA['properties'] if k not in ['key','status','evidence']}
    return dict(row,key=key,status=status,evidence=list(evidence))


def evidence(sid):return {'source_id':sid,'locator':'message.title','quote':''}


@pytest.mark.parametrize('status',f.STATUSES)
def test_each_key_only_accepts_its_bound_source_and_keeps_status_neutral(status):
    inv={'references':[{'key':'hochster'},{'key':'other'}],'passages':[]}
    sources=[{'id':'S-H','reference_keys':['hochster']},{'id':'S-O','reference_keys':['other']}]
    schema=f.batch_schema('references',inv['references'],inv,sources)
    output={'references':[reference_row('hochster',status,[evidence('S-H')]),reference_row('other',status,[evidence('S-O')])],'passages':[]}
    f._validate_against_schema(output,schema)
    wrong=copy.deepcopy(output);wrong['references'][0]['evidence'][0]['source_id']='S-O'
    with pytest.raises(LaunchError,match='alternative'):f._validate_against_schema(wrong,schema)
    empty=copy.deepcopy(output);empty['references'][0]['evidence']=[]
    f._validate_against_schema(empty,schema)


def test_shared_catalog_key_binding_and_source_free_gaps_are_representable():
    inv={'references':[{'key':'a'},{'key':'b'},{'key':'missing'}],'passages':[]}
    sources=[{'id':'S-shared','reference_keys':['a','b']},{'id':'S-private-a','reference_keys':['a']}]
    schema=f.batch_schema('references',inv['references'],inv,sources)
    output={'references':[reference_row('a','verified',[evidence('S-private-a')]),
        reference_row('b','error',[evidence('S-shared')]),reference_row('missing','gap')],'passages':[]}
    f._validate_against_schema(output,schema)
    output['references'][2]['evidence']=[evidence('S-shared')]
    with pytest.raises(LaunchError,match='alternative'):f._validate_against_schema(output,schema)


def test_reference_alternatives_remain_strict_objects_and_complete_batches():
    inv={'references':[{'key':'a'}],'passages':[]}
    schema=f.batch_schema('references',inv['references'],inv,[{'id':'S1','reference_keys':['a']}])
    row=reference_row('a','unchecked');row['invented_field']='not allowed'
    with pytest.raises(LaunchError):f._validate_against_schema({'references':[row],'passages':[]},schema)
    with pytest.raises(LaunchError):f._validate_against_schema({'references':[],'passages':[]},schema)
    assert all(branch['additionalProperties'] is False for branch in schema['properties']['references']['items']['anyOf'])
