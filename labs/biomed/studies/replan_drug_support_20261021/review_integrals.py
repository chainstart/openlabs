"""Independent raw-control normalization and scalar integration review.

No model tuning, target selection, or replacement of frozen result files.
"""
from common import *
from metadata import OLD_ART, OLD_DATA
import csv
import math
import statistics
import numpy as np
import pandas as pd

def integral(x,y,lo,hi,clip=True):
    # Direct line-segment antiderivative, independent of np.interp/trapezoid.
    assert min(x)<=lo+1e-10 and max(x)>=hi-1e-10 and hi>lo
    total=0.
    if clip:y=[min(1.,max(0.,v)) for v in y]
    for xa,xb,ya,yb in zip(x[:-1],x[1:],y[:-1],y[1:]):
        left=max(xa,lo);right=min(xb,hi)
        if right<=left:continue
        slope=(yb-ya)/(xb-xa)
        total+=ya*(right-left)+.5*slope*((right-xa)**2-(left-xa)**2)
    return total/(hi-lo)

def source_normalization():
    p=OLD_ART/'intake/prism19-secondary-screen-mfi.csv'
    assert sha256_file(p)==json.loads(p.with_name(p.name+'.manifest.json').read_text())['sha256']
    t=pd.read_csv(OLD_ART/'intake/prism19-secondary-screen-replicate-treatment-info.csv')
    ex=pd.read_csv(OLD_ART/'selected-well-metadata.csv')
    keys=set(pd.read_csv(DATA/'external-eligible-identifiers.csv').structure_key)
    ex=ex[ex.structure_key.isin(keys)&(ex.screen_id==ex.source_screen)]
    plates=set(ex.detection_plate)
    ctrl=t[t.detection_plate.isin(plates)&t.perturbation_type.isin(['vehicle_control','positive_control'])]
    cols=set(ex.column_name)|set(ctrl.column_name)
    raw=pd.read_csv(p,index_col=0,usecols=lambda c:c=='Unnamed: 0' or c in cols)
    previous=pd.read_pickle(OLD_ART/'normalized-selected-mfi.pkl').reindex(raw.index)
    maxdiff=0.;compared=0;mask_differences=0;plate_results=[]
    for plate,g in ctrl.groupby('detection_plate'):
        negcols=g[g.perturbation_type=='vehicle_control'].column_name.tolist()
        poscols=g[g.perturbation_type=='positive_control'].column_name.tolist()
        neg=raw[negcols].to_numpy();pos=raw[poscols].to_numpy()
        expcols=ex[ex.detection_plate==plate].column_name.tolist()
        values=raw[expcols].to_numpy();expected=np.full_like(values,np.nan)
        passing=0
        for row in range(len(raw)):
            nv=[float(v) for v in neg[row] if math.isfinite(v) and v>0]
            pv=[float(v) for v in pos[row] if math.isfinite(v) and v>0]
            if len(nv)<3 or len(pv)<3:continue
            nl=[math.log2(v) for v in nv];pl=[math.log2(v) for v in pv]
            nm=statistics.median(nl);pm=statistics.median(pl)
            ns=1.4826*statistics.median([abs(v-nm) for v in nl])
            ps=1.4826*statistics.median([abs(v-pm) for v in pl])
            denom=math.sqrt(ns*ns+ps*ps)
            if not denom:continue
            ssmd=(nm-pm)/denom
            if not math.isfinite(ssmd) or ssmd<2:continue
            passing+=1;median=statistics.median(nv)
            for column,v in enumerate(values[row]):
                if math.isfinite(v) and v>0:expected[row,column]=v/median
        prior=previous[expcols].to_numpy()
        mask_differences+=int(np.sum(np.isfinite(expected)!=np.isfinite(prior)))
        ok=np.isfinite(expected)&np.isfinite(prior)
        if ok.any():maxdiff=max(maxdiff,float(np.max(abs(expected[ok]-prior[ok]))))
        compared+=int(ok.sum())
        plate_results.append({'detection_plate':plate,'passing_rows':passing,'source_columns':len(expcols)})
    assert mask_differences==0 and maxdiff<1e-12
    result={'raw_payload_sha256':sha256_file(p),'detection_plates':len(plates),'source_columns':len(set(ex.column_name)),
            'cell_rows':len(raw),'finite_values_compared':compared,'finite_mask_mismatches':mask_differences,'maximum_absolute_error':maxdiff,'plate_details':plate_results}
    write(ART/'raw-normalization-review.json',result)
    print('Independent raw normalization passed',compared,'values',flush=True)
    return result

def target_and_source_integrals():
    metadata=pd.read_csv(DATA/'metadata-qualified-pairs.csv');metadata=metadata[metadata.source_eligible]
    mapping={(r.cell_line,r.drug):(r.structure_key,r.depmap_id) for r in metadata.itertuples()}
    drugset={d for _,d in mapping}
    # Independently parse the official CSV using the standard library.
    values={};nrows=0;retained=0
    with (ART/'intake/CTRP_replicates.csv').open(newline='') as f:
        for row in csv.DictReader(f):
            nrows+=1
            if row['drug'] not in drugset:continue
            identity=mapping.get((row['cell_line'],row['drug']))
            if identity is None:continue
            x=float(row['dose']);y=float(row['response'])
            if not (math.isfinite(x) and math.isfinite(y)):continue
            values.setdefault(identity,{}).setdefault(x,[]).append(y);retained+=1
    targets=pd.read_csv(ART/'sealed/external-target.csv.gz').set_index(['structure_key','depmap_id'])
    maximum=0.;max_unclipped=0.;target_count=0
    for key,r in targets.iterrows():
        d=values[key];xs=sorted(d);ys=[statistics.median(d[x]) for x in xs]
        result=integral(xs,ys,r.common_lo,r.common_hi)
        unconstrained=integral(xs,ys,r.common_lo,r.common_hi,clip=False)
        maximum=max(maximum,abs(result-r.target_auc));max_unclipped=max(max_unclipped,abs(unconstrained-r.target_unclipped_auc));target_count+=1
    assert maximum<1e-12 and max_unclipped<1e-12
    del values
    source=pd.read_csv(ART/'external-source-features.csv.gz').set_index(['structure_key','depmap_id'])
    curves=json.loads((ART/'external-source-curves.json').read_text())
    max_mean=max_sd=max_rep=0.
    for r in curves:
        f=source.loc[(r['structure_key'],r['depmap_id'])]
        x=[math.log10(v) for v in r['source_doses']]
        aucs=[]
        for rep,values in r['source_replicates'].items():
            a=integral(x,values,f.common_lo,f.common_hi)
            aucs.append(a);max_rep=max(max_rep,abs(a-f['rep'+rep+'_auc']))
        max_mean=max(max_mean,abs(statistics.fmean(aucs)-f.raw_auc))
        max_sd=max(max_sd,abs(statistics.stdev(aucs)-f.rep_sd))
    assert max(max_mean,max_sd,max_rep)<1e-12
    result={'ctpr_full_rows_read':nrows,'selected_finite_measurements':retained,'target_pairs_reviewed':target_count,
            'target_bounded_auc_max_error':maximum,'target_unclipped_auc_max_error':max_unclipped,
            'source_pairs_reviewed':len(curves),'source_repeat_auc_max_error':max_rep,'source_mean_auc_max_error':max_mean,'source_sd_max_error':max_sd,
            'implementation':'Python csv + statistics.median/stdev + direct analytic line-segment integration; independent of original pandas groupby/np.interp/np.trapezoid',
            'new_confirmation':False}
    write(ART/'independent-integral-review.json',result)
    print(json.dumps(result,indent=2),flush=True)
    return result

def main():
    assert (ART/'confirmation-results.json').exists()
    started=now();normalization=source_normalization();integration=target_and_source_integrals()
    write(ART/'raw-data-review-complete.json',{'started_utc':started,'finished_utc':now(),'code_sha256':sha256_file(__file__),'all_passed':True,'normalization_file':'raw-normalization-review.json','integration_file':'independent-integral-review.json','same_research_agent_independent_implementation':True,'not_independent_laboratory_or_human_review':True})

if __name__=='__main__':main()
