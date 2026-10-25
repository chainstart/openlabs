"""Publication-style diagnostic plot from saved results; no fitting or selection."""
import json
import os
import sys
from intake import ART
os.environ.setdefault('MPLCONFIGDIR',str(ART/'mplconfig'))
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

for prefix in sys.argv[1:]:
    scores=pd.read_csv(ART/(prefix+'_donor_metrics.csv'),index_col=0)
    result=json.loads((ART/(prefix+'_results.json')).read_text())
    gain=(scores.M2_linear-scores.M5_shrunk_potency_ratio)/scores.M2_linear*100
    primary=result['primary_M5_vs_M2']['relative_gain']
    fig,ax=plt.subplots(figsize=(7,4.5))
    ys=np.arange(len(gain))
    ax.scatter(gain.to_numpy(),ys,color='#295f8c',s=38,label='Individual held donor')
    mean=primary['estimate']*100;lo,hi=np.array(primary['donor_t95'])*100
    ax.errorbar(mean,len(gain)+.7,xerr=np.array([[mean-lo],[hi-mean]]),fmt='D',color='#913326',capsize=4,label='Donor mean and t 95% CI')
    ax.axvline(0,color='black',lw=.8);ax.axvline(5,color='grey',linestyle='--',lw=.8,label='Prespecified 5% gain')
    ax.set_yticks(list(ys)+[len(gain)+.7],list(gain.index)+['Mean'])
    ax.invert_yaxis();ax.set_xlabel('Relative MSE reduction: M5 vs M2 (%)\nPositive values favor target-RNA calibration')
    ax.set_title(prefix.replace('_',' ').title()+f' | {len(gain)} independent donors')
    ax.spines[['top','right']].set_visible(False)
    ax.legend(fontsize=8,loc='best');fig.tight_layout()
    fig.savefig(ART/(prefix+'_donor_gain.png'),dpi=180)
    fig.savefig(ART/(prefix+'_donor_gain.pdf'))
    plt.close(fig)
