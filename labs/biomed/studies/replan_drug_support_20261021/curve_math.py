"""Established bounded 3PL and non-extrapolating empirical integration."""
import numpy as np
from scipy.special import expit
from scipy.optimize import least_squares

GX,GW=np.polynomial.legendre.leggauss(64)

def logistic(logdose, params):
    bottom, logec50, slope=params
    return bottom+(1-bottom)*expit(-np.log(10)*slope*(np.asarray(logdose)-logec50))

def fitted_auc(params,lo,hi):
    x=(GX+1)*.5*(hi-lo)+lo
    return float(np.dot(GW,logistic(x,params))*.5)

def empirical_auc(dose,response,lo,hi,clip=True):
    dose=np.asarray(dose,dtype=float);response=np.asarray(response,dtype=float)
    x=np.log10(dose)
    if len(x)<2 or not np.all(np.isfinite(response)) or not np.all(np.diff(x)>0):
        raise ValueError('Invalid empirical curve')
    tol=1e-9
    if lo<x[0]-tol or hi>x[-1]+tol or not hi>lo:
        raise ValueError('Empirical curve extrapolation prohibited')
    y=np.clip(response,0,1) if clip else response
    xx=np.r_[lo,x[(x>lo)&(x<hi)],hi]
    return float(np.trapezoid(np.interp(xx,x,y),xx)/(hi-lo))

def fit_curve(dose,replicates,lo,hi):
    x=np.tile(np.log10(dose),len(replicates));y=np.asarray(replicates).ravel()
    init=[np.clip(np.min(y),0,1),np.median(x),1]
    res=least_squares(lambda p:logistic(x,p)-y,init,bounds=([0,-6,0],[1,6,4]),max_nfev=300)
    if not res.success or not np.all(np.isfinite(res.x)):
        return {'success':False,'reason':str(res.message),'nfev':res.nfev}
    pred=logistic(x,res.x)
    return {'success':True,'bottom':float(res.x[0]),'logec50':float(res.x[1]),'slope':float(res.x[2]),'auc':fitted_auc(res.x,lo,hi),'rmse':float(np.sqrt(np.mean((pred-y)**2))),'nfev':res.nfev,'boundary':bool(np.any(res.active_mask))}

def self_check():
    from scipy.integrate import quad
    for p in [[0,-2,1],[.4,1,4],[1,0,0],[.2,-6,4],[.8,6,.01]]:
        expected=quad(lambda x:logistic(x,p),-4,1,epsabs=1e-10)[0]/5
        assert abs(fitted_auc(p,-4,1)-expected)<1e-6
    doses=10.**np.arange(-4,2)
    assert abs(empirical_auc(doses,np.full(6,.3),-3.2,.8)-.3)<1e-12
    try:empirical_auc(doses,np.ones(6),-5,1)
    except ValueError:pass
    else:raise AssertionError('extrapolation accepted')
    p=[.2,-1,1.2];ys=logistic(np.log10(doses),p)
    fit=fit_curve(doses,[ys,ys],-4,1)
    assert fit['success'] and fit['rmse']<1e-6
    return {'gauss_vs_quad':True,'constant_empirical_auc':True,'extrapolation_rejected':True,'exact_3pl_recovery':True}
