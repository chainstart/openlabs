from common import *
guard_check()
index=json.loads((OD/'artifact-hash-index.json').read_text()); checks={}
for rel,rec in index.items():
    p=OLD/rel
    if p.exists() and p.is_file() and '.part' not in p.name:
        checks[rel]={'sha256':sha(p),'expected':rec['sha256']}
        assert checks[rel]['sha256']==rec['sha256'],rel
write(DATA/'reuse-hash-audit.json',checks)
old=[{'path':str(OD/n),'sha256':sha(OD/n)} for n in ('c3-plan.frozen.json','complete-trial-ledger.json','candidate-ledger.json','c3-trial-ledger.json','RESULTS.json','FINAL_REPORT.md')]
write(DATA/'assessment.json',dict(time=now(),historical_evidence=old,old_raw_experiments_resynced=False,read_only_reuse=True,assessment='原方向跨体系同一性未建立；六设计方向只有2位点；旧267位点类别校准已有测试暴露，最强类别基线优势不确定且用了目标质量特征。不能继续作新确认。',exposure_policy='All prior Agarwal/QUASARR/Tan500P outcomes are development only. Other archived panels require provenance and exposure audit before eligibility.',historical_budget=dict(candidates=3,configurations=8),new_budget=dict(candidates=3,configurations=12),paper_candidate=False))
write(DATA/'replan.json',dict(time=now(),stage='candidate_feasibility_not_frozen',deadline_utc=DEADLINE.isoformat(),candidates=[dict(id='R1',question='来源连续响应性与重复误差能否预测跨研究响应校准失败？',gate='Bergman/Tan continuous endpoints, exact sequences, source-only features, new independent unexposed panel required'),dict(id='R2',question='源重复精度能否区分跨报告位置失配和随机测量误差，超过identity/affine及活性对照？',gate='Klein multi-design or new panel: explicit sequence, matched endpoints, independent loci, heldout experimental design; within-study scope explicit'),dict(id='R3',question='局部启动子突变的背景依赖是否超过重复精度可解释范围？',gate='PARM/Tan mutagenesis with genuine replicate/background structure and novelty beyond published saturation analysis')],selection='Prefer real compatible measurements and an unexposed experimental panel; reject if nearest work already directly answers or precision inadequate.',new_max_configurations=12,paper_candidate=False))
write(DATA/'complete-trial-ledger.json',dict(time=now(),historical_ledger={'path':str(OD/'complete-trial-ledger.json'),'sha256':sha(OD/'complete-trial-ledger.json')},history_budget={'candidates':3,'configurations':8},current_budget={'candidates_max':3,'configurations_max':12},current_trials=[]))
print('verified completed old artifacts',len(checks))
