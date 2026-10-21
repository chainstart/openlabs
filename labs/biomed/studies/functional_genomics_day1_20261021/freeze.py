"""Outcome-blind identity matching and prospective protocol freeze."""
import csv,collections,json,sys
from common import *
sys.path.insert(0,str(CODE.parents[1]))
from tools.split_audit import audit

assert not (PROJECT/'plan.json').exists(), 'Never overwrite a frozen plan'
cells={'HepG2':'ENCFF774DYO','K562':'ENCFF631LHA','WTC11':'ENCFF971UBA'}
tables={}
for cell,f in cells.items():
    bygene=collections.defaultdict(dict)
    for r in csv.DictReader((ART/'design'/f'{f}.csv').open()):
        name=r['name']
        if not name.startswith('ENSG'):continue
        gene=name.split('_')[0]
        orient='antisense' if ('Reversed' in name or name.endswith('_R')) else 'sense'
        key=(r['chrom'],int(r['start']),int(r['end']))
        if orient in bygene[gene]: raise ValueError('Duplicate gene orientation '+gene)
        bygene[gene][orient]=dict(name=name,coordinate=key,strand=r['strand'])
    tables[cell]=bygene
common=set.intersection(*(set(x) for x in tables.values()))
samples=[];excluded=collections.Counter();seen=set()
for gene in sorted(common):
    rec=[tables[c][gene] for c in cells]
    if any(set(r)!= {'sense','antisense'} for r in rec):
        excluded['missing_orientation']+=1;continue
    coords={r[o]['coordinate'] for r in rec for o in ['sense','antisense']}
    if len(coords)!=1:excluded['coordinate_mismatch']+=1;continue
    chrom,start,end=next(iter(coords))
    if chrom not in ['chr'+str(i) for i in range(1,23)]:excluded['not_autosomal']+=1;continue
    if end-start!=200:excluded['not_200nt']+=1;continue
    strands={r['sense']['strand'] for r in rec}
    if len(strands)!=1 or any(r['sense']['strand']==r['antisense']['strand'] for r in rec):
        excluded['strand_conflict']+=1;continue
    locus=f'{chrom}:{start}-{end}'
    if locus in seen:excluded['duplicate_coordinate']+=1;continue
    seen.add(locus)
    chromosome=int(chrom[3:])
    split='train' if chromosome<=16 else 'validation' if chromosome<=18 else 'test'
    row=dict(sample_id=gene,split=split,molecule_id=locus,locus_id=locus,chrom=chrom,start=start,end=end,
             block_id=f'{chrom}:{start//1000000}',native_strand=next(iter(strands)))
    for cell in cells:
        for o in ['sense','antisense']:row[f'{cell}_{o}_name']=tables[cell][gene][o]['name']
    samples.append(row)
assert len(samples)>=2000,'Insufficient paired loci: stop before outcomes'
assert len({s['block_id'] for s in samples if s['split']=='test'})>=50,'Insufficient confirmation blocks'
with (PROJECT/'samples.csv').open('w') as f:
    w=csv.DictWriter(f,fieldnames=list(samples[0]));w.writeheader();w.writerows(samples)
report=audit(PROJECT/'samples.csv',independent_unit='molecule',group_columns=['molecule_id','block_id','chrom'],strategy='group',project_root=PROJECT)
assert report['valid']
atomic(PROJECT/'split-audit.json',report)
atomic(PROJECT/'identity-audit.json',dict(identifiers_only=True,labels_compared=False,shared_gene_ids=len(common),
      eligible_exact_paired_autosomal_loci=len(samples),exclusions=dict(excluded),
      counts=dict(collections.Counter(x['split'] for x in samples)),
      note='Molecule compatibility label means genomic DNA locus, not a chemical scaffold. Same coordinates and native strand required in all three experiments. Native direction is defined by original non-Reversed/F gene-labelled design, not an activity score. Exact sequence identity inferred from source study fixed 200nt reference promoter design; no raw oligo resequencing performed. No cell-type or study disjointness is claimed.'))
models=['zero','median','activity_ridge','activity_hgb','identity_delta','delta_ridge','full_ridge','full_hgb']
plan=dict(schema_version='openlabs.functional_genomics_plan.v1',stage='exploratory_pilot',frozen_at_utc=now(),
 research_question='Can promoter-specific sense-minus-antisense activity differences learned from HepG2→K562 predict WTC11 differences at unseen genomic loci beyond source overall activity, assay precision and shared sense preference?',
 hypothesis='Measured source orientation differences provide a portable promoter-specific component, beyond overall activity and universal sense bias.',
 scope='A narrow lentiMPRA replication/extension, not a new algorithm, endogenous mechanism, disease claim, or proof of sequence-intrinsic causality.',
 independent_unit='molecule',unit_description='Paired genomic 200nt promoter locus; uncertainty clusters 1Mb genomic blocks conditional on these three cell contexts and original study.',
 primary_outcomes=['WTC11 test-locus MSE improvement of validation-selected orientation model over validation-selected strongest activity-only model',
                   'Relative MSE reduction >=0.10 and paired block-bootstrap 95% interval lower bound of absolute MSE improvement >0 are both required for positive pilot support'],
 secondary_outcomes=['MAE, Pearson and Spearman signed differences; sign concordance',
                     'Residual correlation after train-only activity regression; per-chromosome errors',
                     'Source-only reliable subset: abs(mean sense-minus-antisense)>=0.5 log2 and all three source contrasts share a sign',
                     'Replicate difference reproducibility; two-level genomic-block/target-culture bootstrap sensitivity',
                     'Performance against uncalibrated identity_delta; a learned-method claim additionally needs improvement over identity, and is not the primary aim'],
 baselines=models,model_specifications={
   'zero':'orientation invariance: delta=0',
   'median':'K562 train median sense-minus-antisense, captures shared sense preference',
   'activity_ridge':'StandardScaler fit train + Ridge(alpha=1) using source mean, mean squared, source contrast SD, log1p(min source barcode count)',
   'activity_hgb':'Same four source features; HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=7,max_depth=3,min_samples_leaf=20,l2_regularization=10,learning_rate=.05,early_stopping=False,random_state=20261021)',
   'identity_delta':'source mean signed contrast unchanged',
   'delta_ridge':'train-scaled source contrast + Ridge(alpha=1)',
   'full_ridge':'four activity features plus source contrast and contrast*source mean + same ridge',
   'full_hgb':'same six features and same HGB settings'},
 model_selection='Fit all eight only on K562 train labels. Select min validation MSE separately among zero/median/activity_ridge/activity_hgb and among identity_delta/delta_ridge/full_ridge/full_hgb. Freeze both names and coefficients/models, no refitting after validation. WTC11 labels never used for model choice or rescaling.',
 split_strategy='group',group_columns=['molecule_id','block_id','chrom'],
 split_description='chr1–16 training, chr17–18 validation (K562 only); chr19–22 test (WTC11 only). HepG2 source measurements of all loci explicitly available. Measured-source transfer, not sequence-only inductive prediction.',
 leakage_controls=['All fitted transformations use K562 train rows only. No WTC11 numeric outcome opened before once-only confirmation marker.',
                   'One row per exact genomic coordinate; paired orientations/cultures merged per locus; no adjacent or chromosome overlap across partitions.',
                   'Target BEDs were processed for first four columns and strand only; outcome fields not inspected. All joint-library files excluded from research because one orientation only.',
                   'The two manually inspected source-BED preview rows are chr1:10410-10610 nonpromoter and outside eligible promoter analysis.',
                   'Use only finite source and K562 values and >=10 barcodes in every orientation and replicate for train/validation. Test applies same fixed source and WTC11 quality rule once, does not use K562 test outcomes.',
                   'No target-label imputation. Primary result conditional on QC-passing loci and one held-out cell context.'],
 confirmatory_holdout='WTC11 numeric replicate outcomes, chr19–22 only, single evaluation; other WTC11 outcomes are not read analytically.',
 uncertainty='2000 paired 1Mb block bootstrap replicates, seed20261021; additionally resample three target cultures globally inside each bootstrap to preserve culture-wide dependence. Report intervals separately. Do not infer across-cell or across-laboratory uncertainty from locus counts.',
 multiplicity='One primary selected-model comparison. All other comparisons descriptive; no subgroup discovery or significance-based selection. Seeds are computational repeats, not biological experiments.',
 exclusions='Identity metadata and fixed QC only; no outcome-based trimming, no sign-based target selection.',
 stop_conditions=['<2000 exact paired shared promoter loci or <50 confirmation blocks before outcomes',
                  '<200 train or <100 validation or <200 test QC-passing loci',
                  'terms/access/resource failure; deadline2026-10-22T00:10Z',
                  'No reliable primary improvement means no support; no adaptive test reuse. Strong overlap with prior work or lack of external laboratory validation means no paper promotion even after positive transfer.'],
 max_trials=8,seeds=[20261021],resource_budget=dict(cpu_threads=2,memory_mib=2048,scratch_mib=3072,download_mib=1024,per_file_mib=128,http_concurrency=2),
 source_study='DOI:10.1038/s41586-024-08430-9; ENCSR022GQD,ENCSR382BVV,ENCSR244FWB',
 closest_work=['10.1101/gr.270751.120 already establishes cross-cell MPRA strand asymmetry and sequence prediction.',
               '10.1038/s41586-024-08430-9 already shows promoter orientation/activity correlations across cells. Only incremental individual-contrast transfer beyond activity/mean bias remains to quantify.',
               '10.1038/s41467-026-68780-y dual potential/reciprocity is distinct assay biology; do not claim to establish it.'],
 paper_candidate=False)
atomic(PROJECT/'plan.json',plan)
atomic(PROJECT/'freeze-hashes.json',{n:sha(PROJECT/n) for n in ['plan.json','samples.csv','split-audit.json','identity-audit.json','environment.json','environment.uv.lock']})
(PROJECT/'CHECKPOINT.md').write_text('# 冻结检查点\n\n身份坐标审计和方案已冻结，未比较目标数值。\n8个固定配置，HepG2作实测来源，K562训练/验证，WTC11 chr19–22一次确认。\n主问题仅为启动子个体方向差在控制总体活性、技术精度、共同正义链偏好后是否仍可迁移。\n2021/2025文献已覆盖一般方向保守性；即使主检验阳性也不是新机制或新算法。\n')
status('plan_frozen',plan['research_question'],'freeze.py completed',[PROJECT/'plan.json',PROJECT/'freeze-hashes.json',PROJECT/'split-audit.json'])
print(report['counts'],dict(excluded),sha(PROJECT/'plan.json'))
