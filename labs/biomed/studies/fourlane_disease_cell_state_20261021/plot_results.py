"""Export descriptive scientific figures from locked prediction records."""
from intake import *
os.environ['MPLBACKEND']='Agg';os.environ['MPLCONFIGDIR']=str(ART/'mplconfig')
import numpy as np,pandas as pd
import matplotlib.pyplot as plt
from attribution import summary

def main():
    a=pd.read_csv(ART/'confirmation_predictions.csv')
    b=pd.read_csv(ART/'confirmation_redeconv_predictions.csv')
    pred=pd.concat([a,b],ignore_index=True)
    metrics=summary(pred)['IPF_primary_ECM']
    primary=pred[pred.disease.eq('IPF')&pred.primary_ECM_eligible].copy()
    primary['error']=abs(primary.primary_ECM_prediction-primary.primary_ECM_truth)
    order=['constant','NNLS_healthy','NNLS_IPF','NNLS_pooled','ReDeconv_healthy','ReDeconv_IPF','ReDeconv_pooled']
    fig,axes=plt.subplots(1,2,figsize=(12.2,4.8),gridspec_kw={'width_ratios':[1.2,1]})
    ax=axes[0]
    rng=np.random.default_rng(20261021)
    for i,model in enumerate(order):
        vals=primary.loc[primary.model.eq(model),'error'].dropna().to_numpy()*100
        if len(vals):
            ax.scatter(vals,i+rng.uniform(-.12,.12,len(vals)),s=15,c='#64748b',alpha=.45,zorder=2)
            m=metrics['models'][model];lo,hi=np.array(m['ci95'])*100;point=m['mae']*100
            ax.plot([lo,hi],[i,i],lw=3,color='#0369a1',zorder=3);ax.plot(point,i,'o',color='#0369a1',ms=6,zorder=4)
        else:ax.text(.01,i,'unavailable / failed',va='center',transform=ax.get_yaxis_transform(),color='#991b1b')
    ax.set_yticks(range(len(order)),order);ax.invert_yaxis()
    ax.set_xlabel('Absolute ECM RNA-source-share error (percentage points)')
    ax.set_title('IPF confirmation donors; fixed references',loc='left',fontsize=11)
    ax=axes[1]
    wide=primary.pivot(index='donor_id',columns='model',values='error')
    boot=json.loads((ART/'reference_bootstrap_summary.json').read_text())
    comparisons=[('NNLS_healthy','NNLS_pooled'),('constant','NNLS_pooled')]
    for i,(x,y) in enumerate(comparisons):
        delta=(wide[x]-wide[y]).dropna().to_numpy()*100
        ax.scatter(delta,i+rng.uniform(-.1,.1,len(delta)),s=18,c='#64748b',alpha=.45)
        key=x+'_minus_'+y;m=metrics['paired_comparisons'][key]
        lo,hi=np.array(m['ci95'])*100;v=m['mean_error_reduction']*100
        ax.plot([lo,hi],[i,i],lw=3,color='#0369a1');ax.plot(v,i,'o',color='#0369a1')
        lo,hi=np.array(boot['combined_uncertainty'][key]['joint_error_reduction_q025_q975'])*100
        ax.plot([lo,hi],[i+.18,i+.18],lw=3,color='#d97706')
    ax.axvline(0,color='black',lw=.8);ax.axvline(5,color='#dc2626',ls='--',lw=1)
    ax.set_yticks([0,1],['Healthy minus pooled','Constant minus pooled']);ax.invert_yaxis()
    ax.set_xlabel('Error reduction for pooled reference (percentage points)')
    ax.set_title('Prespecified contrasts; red line = 5-point threshold',loc='left',fontsize=11)
    for ax in axes:
        ax.spines[['top','right']].set_visible(False);ax.grid(axis='x',alpha=.15)
    fig.text(.01,.01,'Dots: donors. Blue: mean and donor-bootstrap 95% interval. Orange: joint development-reference / test-donor bootstrap interval.\nRNA-source attribution in sampled pseudobulks; not tissue cell fractions or causal effects.',fontsize=9)
    fig.tight_layout(rect=[0,.11,1,1])
    for suffix in ['png','svg']:fig.savefig(ART/f'primary_attribution_results.{suffix}',dpi=180,bbox_inches='tight')
    plt.close(fig)
    atomic(ART/'figure_provenance.json',dict(at=now(),source_predictions=[str(ART/'confirmation_predictions.csv'),str(ART/'confirmation_redeconv_predictions.csv')],unit='donor',figure='primary_attribution_results.png',code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))

if __name__=='__main__':main()
