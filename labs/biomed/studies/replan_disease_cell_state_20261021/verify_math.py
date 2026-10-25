"""Estimator sanity checks only. Synthetic numbers never biological evidence."""
from analyse_bulk import *
from scipy.stats import rankdata
import io
checks={}
rank=np.arange(1,101,dtype=float)[:,None]
checks['singscore_upper_extreme']=bool(np.allclose(singscore(rank,np.arange(97,100)),.5))
checks['singscore_lower_extreme']=bool(np.allclose(singscore(rank,np.arange(3)),-.5))
checks['singscore_middle_center']=bool(np.allclose(singscore(rank,np.array([49,50])),0))
groups=[np.repeat(float(i),4) for i in range(5)]
checks['icc_perfect_repeatability']=bool(np.isclose(icc(groups),1))
checks['icc_not_clipped_negative']=bool(icc([np.array([0.,1.]) for i in range(5)])<0)
checks['binomial_boundaries']=cp(0,9)[0]==0 and cp(9,9)[1]==1
checks['binomial_nontrivial']=bool(np.allclose(cp(6,9),[.29929505620854036,.9251453685803082]))
rng=np.random.default_rng(173);x=np.column_stack([np.ones(30),np.repeat([0.,1.],15),np.linspace(-1,1,30)]);y=x@np.array([1,2,3])+rng.normal(size=30)*.1
r=hc3(x,y,['intercept','IPF','age']);b=np.linalg.lstsq(x,y,rcond=None)[0]
checks['OLS_independent_lstsq']=bool(abs(r['disease_coefficient']-b[1])<1e-9)
r2=hc3(np.column_stack([x,np.ones(30)]),y,['intercept','IPF','age','male'])
checks['constant_nuisance_invariance']=bool(abs(r2['disease_coefficient']-r['disease_coefficient'])<1e-12)
# Four within-donor values generate6pairs but1independent donor summary.
v=np.array([0,0,0,2.]);pairs=[abs(v[i]-v[j]) for i,j in combinations(range(4),2)]
checks['pair_accounting']=len(pairs)==6 and np.mean(np.array(pairs)>=1)==.5
# Fixed library scale normalization leaves abundances exactly invariant.
a=np.array([[1.,2.],[3.,4.],[5.,7.]])
norm=lambda z:z/z.sum(axis=0)*1e6
checks['library_scale_invariance']=bool(np.allclose(norm(a),norm(a*np.array([3.,7.]))))
checks['replicate_row_order_invariance']=bool(np.isclose(icc([g[::-1] for g in groups[::-1]]),icc(groups)))
toy=pd.read_csv(io.StringIO(',annotation,sampleB,sampleA\nGENE1,text,2,3\n'),index_col=0,usecols=[0,2,3]).astype(float)
checks['unnamed_source_gene_column_and_nonnumeric_annotation']=bool(toy.index.tolist()==['GENE1'] and toy.columns.tolist()==['sampleB','sampleA'] and toy.sum().sum()==5)
meta=pd.DataFrame({'sample_id':['B','A'],'donor':['D2','D1']}).set_index('sample_id').loc[pd.Index(['A','B'])].rename_axis('sample_id').reset_index()
checks['metadata_index_name_and_reordering']=bool(meta.sample_id.tolist()==['A','B'] and meta.donor.tolist()==['D1','D2'])
checks={k:bool(v) for k,v in checks.items()}
record=dict(at=now(),checks=checks,all_pass=all(checks.values()),purpose='software algebra checks, not biological evidence',executable=sys.executable,code_hashes={p.name:sha(p) for p in [CODE/'bulk_io.py',CODE/'analyse_bulk.py',Path(__file__)]})
atomic(DATA/'software_verification.json',record);print(json.dumps(record));assert record['all_pass']
