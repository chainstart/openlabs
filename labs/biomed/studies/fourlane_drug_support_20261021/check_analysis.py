"""Software checks only: constructed arrays never used as research evidence."""
from evaluate import cluster_bootstrap,pair_error
from common import *
from curve_math import self_check
import numpy as np
import pandas as pd

df=pd.DataFrame({'structure_key':['a','a','b','b'],'depmap_id':['x','y','x','y']})
x=np.array([[1.,3.],[1.,3.],[1.,3.],[1.,3.]])
bs=cluster_bootstrap(df,x,nboot=40)
assert np.allclose(bs,x[0])
x=np.array([[0.,3.],[2.,5.],[4.,7.],[6.,9.]])
bs=cluster_bootstrap(df,x,nboot=40)
assert np.allclose(bs[:,1]-bs[:,0],3.)
assert np.allclose(pair_error(np.array([-1,1,0,1]),np.array([1,1,1,0])),[1,0,.5,.5])
# Reproduce the first pigeonhole draw by explicit repeated-row enumeration.
rng=np.random.default_rng(20261021);wd=rng.multinomial(2,[.5,.5]);wc=rng.multinomial(2,[.5,.5])
manual=np.average(np.average(x.reshape(2,2,2),axis=1,weights=wc),axis=0,weights=wd)
assert np.allclose(bs[0],manual)
checks={**self_check(),'constant_bootstrap':True,'paired_contrast_invariance':True,'bootstrap_explicit_enumeration':True,'ranking_ties_and_reversal':True,'synthetic_software_check_only':True,'at':now()}
write(ART/'analysis-software-checks.json',checks)
print(checks)
