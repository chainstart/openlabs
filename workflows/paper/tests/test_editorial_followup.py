import pytest
import hashlib
import json
from paper_writing import editorial_followup as f


def pair():
    before={'main.tex':b'Appendix~\\ref{app:a}\n'*5,
            'references.bib':b'note          = {Preprint, version 2}\n'*4,
            'main.bbl':b'arXiv e-printsPreprint, version 2\n'*4,
            'figure.pdf':b'unchanged'}
    after={**before,'main.tex':before['main.tex'].replace(b'Appendix~',b''),
           'references.bib':before['references.bib'].replace(b'{Preprint',b'{, Preprint'),
           'main.bbl':before['main.bbl'].replace(b'e-printsPreprint',b'e-prints,\n Preprint')}
    return before,after


def test_exact_typography_and_wrapping_only():
    f.typography_delta(*pair())


@pytest.mark.parametrize('mutation',['science','citation','version','figure','new_file','removed_file','wrong_count','uncorrected'])
def test_typography_does_not_allow_unrelated_change(mutation):
    before,after=pair()
    if mutation=='science':after['main.tex']+=b'new result'
    if mutation=='citation':after['references.bib']+=b'doi={changed}'
    if mutation=='version':after['main.bbl']=after['main.bbl'].replace(b'version 2',b'version 3')
    if mutation=='figure':after['figure.pdf']=b'new figure'
    if mutation=='new_file':after['proof.tex']=b'new proof'
    if mutation=='removed_file':after.pop('figure.pdf')
    if mutation=='wrong_count':before['main.tex']+=b'Appendix~\\ref{app:b}'
    if mutation=='uncorrected':after['main.bbl']=before['main.bbl']
    with pytest.raises(ValueError):f.typography_delta(before,after)


@pytest.mark.parametrize('mutation',['none','unconfirmed','wrong_paper','wrong_version','extra_review','changed_prior'])
def test_followup_requires_exact_user_and_prior_preparation(tmp_path,mutation):
    def save(path,obj):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(obj))
        return {'path':str(path.relative_to(tmp_path)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    prior=save(tmp_path/'prior.json',{'delta':['unchanged prior']})
    auth={'actor':'user','confirmed':True,'quote':'Approved one follow-up','scope':f.KIND,
          'recorded_at':'2026-09-12T00:00:00+00:00','paper_id':'p','target_version':'0.2.22',
          'target_journal':'PDU','prior_preparation':prior,'additional_independent_reviews':1}
    if mutation=='unconfirmed':auth['confirmed']=False
    if mutation=='wrong_paper':auth['paper_id']='other'
    if mutation=='wrong_version':auth['target_version']='0.2.21'
    if mutation=='extra_review':auth['additional_independent_reviews']=2
    pointer=save(tmp_path/'registry/quality-gate-exceptions/a.json',auth)
    final={'authorization':pointer,'prior_preparation':prior}
    prep={'delta':['unchanged prior'],'production_followup':final}
    if mutation=='changed_prior':prep['delta']=['changed prior']
    meta={'version':'0.2.22','target_journal':'PDU'}
    if mutation=='none':assert f.inspect_authorization('p',final,prep,meta,tmp_path)[0]==auth
    else:
        with pytest.raises(ValueError):f.inspect_authorization('p',final,prep,meta,tmp_path)
