"""Plots from frozen results; no additional model selection or fitting."""
from common import *
os.environ['MPLCONFIGDIR']=str(ART/'mpl-cache')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

def save(fig,name):
    fig.savefig(ART/(name+'.png'),dpi=180,bbox_inches='tight')
    fig.savefig(ART/(name+'.svg'),bbox_inches='tight')
    plt.close(fig)

def main():
    r=json.loads((ART/'confirmation-results.json').read_text())
    labels={'hgb_full':'Full reliability HGB (primary)','gap_raw':'Source raw response gap','gap_fit':'Source fitted response gap',
            'additive_mean':'Training mean effects','repeat_agreement':'Source repeat agreement','standardized_gap':'Standardized response gap',
            'nrfe_curve':'Curve NRFE (adapted)','isotonic_gap':'Gap-only isotonic','ridge_full':'Full reliability ridge',
            'hgb_gap':'Gap-only HGB','hgb_dose':'Dose-only HGB'}
    order=['hgb_full','gap_raw','isotonic_gap','hgb_gap','ridge_full','gap_fit','standardized_gap','repeat_agreement','nrfe_curve','hgb_dose','additive_mean']
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none'})
    fig,ax=plt.subplots(figsize=(8.5,5.4))
    for k,name in enumerate(order):
        m=r['all_baselines'][name];p=100*m['error_at_50pct'];lo,hi=np.array(m['two_way_ci95'])*100
        ax.errorbar(p,k,xerr=[[p-lo],[hi-p]],fmt='o',color='#007c91' if name=='hgb_full' else '#333333',capsize=3)
    ax.set_yticks(range(len(order)),[labels[x] for x in order]);ax.invert_yaxis()
    ax.set_xlabel('Observed CTRP ranking error (%) at fixed 50% coverage')
    ax.set_title('50 compounds, 444 cell models; chemical x cell bootstrap 95% intervals',fontsize=11)
    ax.grid(axis='x',alpha=.2);fig.tight_layout();save(fig,'all-baseline-errors')

    fig,ax=plt.subplots(figsize=(7.7,2.7))
    p=r['primary'];value=100*p['benefit'];lo,hi=np.array(p['two_way_ci95'])*100
    ax.errorbar(value,0,xerr=[[value-lo],[hi-value]],fmt='o',color='#007c91',capsize=5)
    ax.axvline(0,color='#777777',ls=':');ax.axvline(2,color='#b45124',ls='--',label='Preregistered material benefit: 2 pp')
    ax.set_xlim(-1,2.6);ax.set_ylim(-.6,.6);ax.set_yticks([])
    ax.set_xlabel('Error reduction vs source raw gap (percentage points; positive favors full model)')
    ax.set_title(f'Primary benefit {value:.2f} pp; 95% interval [{lo:.2f}, {hi:.2f}]')
    ax.legend(loc='upper right',frameon=False,fontsize=9);fig.tight_layout();save(fig,'primary-benefit')

    fig,ax=plt.subplots(figsize=(7.5,4.5))
    for name in ['hgb_full','gap_raw','isotonic_gap','repeat_agreement','nrfe_curve']:
        m=r['all_baselines'][name];ys=[100*m['error_at_25pct'],100*m['error_at_50pct'],100*m['error_at_75pct'],100*m['all_pair_error']]
        ax.plot([25,50,75,100],ys,'o-',label=labels[name],lw=2 if name=='hgb_full' else 1)
    ax.axvline(50,color='#999999',lw=.7,ls=':')
    ax.set_xlabel('Retained comparison coverage (%)');ax.set_ylabel('Drug-macro observed ranking error (%)')
    ax.set_title('Prespecified coverage sensitivity (points only)');ax.legend(frameon=False,fontsize=8)
    ax.grid(alpha=.2);fig.tight_layout();save(fig,'coverage-sensitivity')

    bins=pd.read_csv(ART/'calibration-fixed-bins.csv');fig,ax=plt.subplots(figsize=(5.5,5))
    ax.plot([0,1],[0,1],':',color='#888888',label='Perfect calibration')
    for name,color in [('hgb_full','#007c91'),('isotonic_gap','#555555')]:
        g=bins[bins.method==name].sort_values('bin')
        ax.plot(g.predicted,g.observed,'o-',color=color,label=labels[name])
    ax.set_xlim(0,1);ax.set_ylim(0,1);ax.set_aspect('equal')
    ax.set_xlabel('Predicted disagreement (PRISM-trained)');ax.set_ylabel('Observed CTRP disagreement')
    ax.set_title('Five fixed risk bins; equal-drug descriptive means',fontsize=10)
    ax.legend(frameon=False,fontsize=8);fig.tight_layout();save(fig,'calibration-transfer')
    write(ART/'figure-provenance.json',{'at':now(),'code_sha256':sha256_file(__file__),'inputs':{f:sha256_file(ART/f) for f in ['confirmation-results.json','calibration-fixed-bins.csv']},'figures':['all-baseline-errors','primary-benefit','coverage-sensitivity','calibration-transfer'],'new_model_fits':False})

if __name__=='__main__':main()
