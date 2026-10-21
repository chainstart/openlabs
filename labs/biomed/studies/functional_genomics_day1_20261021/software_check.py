"""Small oracle checks before real confirmation; no scientific labels used."""
import numpy as np,pandas as pd
from common import *
from run import source_features,bootstrap,metrics

s=np.array([[[3.,1.],[4.,2.],[2.,0.]],[[1.,2.],[2.,3.],[0.,1.]]])
f=source_features(s,np.full(s.shape,20.))
assert np.allclose(f['delta'][:,0],[2.,-1.])
assert np.allclose(f['activity'][:,0],[2.,1.5])
assert f['reliable'].all()
assert metrics(np.array([1.,-1.]),np.array([1.,-1.]))['mse']==0
n=120;y=np.tile(np.array([1.,2.,3.]),(n,1));blocks=pd.Series(['b'+str(i//2) for i in range(n)])
same,draws=bootstrap(blocks,y,np.full(n,2.),np.full(n,2.),reps=20)
assert same['mse_improvement']==0 and np.all(draws==0)
gain,draws=bootstrap(blocks,y,np.zeros(n),np.full(n,2.),reps=20)
assert gain['mse_improvement']==4 and gain['block_95ci']==[4.,4.]
assert np.all(draws[0]==4.)
atomic(PROJECT/'software-check.json',dict(time_utc=now(),valid=True,
 checks=['sense-minus-antisense arithmetic and source means','fixed source-only reliable mask','zero-error metric oracle',
         'identical-policy paired intervals exactly zero','constant known MSE improvement exactly 4 under block resampling'],
 scientific_labels_used=False,code_sha256=sha(CODE/'run.py')))
print('five synthetic oracle checks passed; no research outcomes used')
