"""Prespecified development-donor resampling after fixed confirmation scoring."""
from attribution import *

def main():
    assert (ART/'confirmation_predictions.csv').exists()
    out=ART/'reference_bootstrap_metrics.csv'
    assert not out.exists(),'Refuse overwrite'
    train=load('development');test=load('confirmation')
    donors=train[0][['donor_id','disease']].drop_duplicates()
    rng=np.random.default_rng(SEED+1);rows=[];combined=[]
    for b in range(100):
        sampled=[]
        for _,g in donors.groupby('disease'):
            sampled.extend(rng.choice(g.donor_id.to_numpy(),len(g),replace=True).tolist())
        pred=run_predictions(train,test,bootstrap_donors=sampled)
        p=pred[(pred.disease=='IPF')&pred.primary_ECM_eligible].copy()
        p['error']=abs(p.primary_ECM_prediction-p.primary_ECM_truth)
        means=p.groupby('model').error.mean().to_dict()
        for model,mae in means.items():rows.append(dict(draw=b,model=model,mae=mae,sampled_donors=';'.join(sampled)))
        w=p.pivot(index='donor_id',columns='model',values='error')
        for a,c in [('NNLS_healthy','NNLS_pooled'),('constant','NNLS_pooled')]:
            delta=(w[a]-w[c]).dropna().to_numpy()
            if len(delta):
                # Two thousand donor-bootstrap draws overall, twenty per reference draw.
                vals=delta[rng.integers(len(delta),size=(20,len(delta)))].mean(axis=1)
                combined.extend(dict(reference_draw=b,contrast=a+'_minus_'+c,error_reduction=float(v)) for v in vals)
        if b%10==0:
            atomic(ART/'reference_bootstrap_progress.json',dict(at=now(),draws_done=b+1,draws_total=100,paper_candidate=False))
            print('reference draws',b+1,flush=True)
    df=pd.DataFrame(rows);df.to_csv(out,index=False)
    c=pd.DataFrame(combined);c.to_csv(ART/'joint_reference_test_bootstrap.csv',index=False)
    report=dict(at=now(),draws=100,independent_units='development donors resampled within disease; confirmation IPF donors independently resampled',metrics={},combined_uncertainty={},model_selection_uncertainty='No model selected on confirmation; compare all frozen configurations, report reference-induced ranking instability')
    for m,g in df.groupby('model'):report['metrics'][m]=dict(reference_mae_q025_q975=g.mae.quantile([.025,.975]).tolist(),reference_mae_min_max=[float(g.mae.min()),float(g.mae.max())])
    for name,g in c.groupby('contrast'):report['combined_uncertainty'][name]=dict(joint_error_reduction_q025_q975=g.error_reduction.quantile([.025,.975]).tolist(),draws=len(g))
    wide=df.pivot(index='draw',columns='model',values='mae')
    report['best_model_counts']=wide.idxmin(axis=1).value_counts().to_dict()
    atomic(ART/'reference_bootstrap_summary.json',report);print(json.dumps(report,indent=2))

if __name__=='__main__':main()
