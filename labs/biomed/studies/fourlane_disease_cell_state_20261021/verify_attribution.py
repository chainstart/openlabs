"""Software checks only: exact mixtures are not biological evidence."""
from attribution import *

genes=np.array(['M_A','M_B','M_C','M_D','COL1A1','COL1A2','COL3A1','AGER'])
raw=np.array([[10,0],[0,12],[8,1],[1,8],[4,9],[2,5],[1,7],[6,0]],float)
ref=raw/raw.sum(axis=0)*1e6
coef=np.array([.3,.7]);bulk=ref@coef
p=predict((['AT2','fibroblast'],raw,ref,np.arange(4)),bulk,genes)
expected=(ref[4:7,0].sum()*.3)/(ref[4:7]@coef).sum()
assert abs(p['primary_ECM_prediction']-expected)<1e-10
assert abs(p['primary_ECM_raw_CPM_difference'])<1e-10
meta=pd.DataFrame([dict(donor_id='test',compartment='AT2',disease='IPF',age=60,n=2,population_cells=10,weight=5),dict(donor_id='test',compartment='fibroblast',disease='IPF',age=60,n=1,population_cells=20,weight=20)])
sums=np.array([[1,2,0,0,10,0,0,0],[0,0,1,2,10,0,0,0]])
t=targets(meta,sums,genes).iloc[0]
assert t.primary_ECM_observed_counts==20 and t.primary_ECM_weighted_counts==250
assert t.primary_ECM_truth==.2 and t.primary_ECM_eligible
result=dict(at=now(),status='passed',checks=['exact identifiable mixture recovers transcript-source share','raw/CPM column rescaling leaves source share invariant','inverse sampling weights applied to donor target','20-count boundary applied to actual sampled counts'],scientific_evidence=False,code_sha256=hashlib.sha256((Path(__file__).parent/'attribution.py').read_bytes()).hexdigest())
atomic(DATA/'software_verification.json',result);print(json.dumps(result))
