import secrets
from sqlalchemy import select
from fastapi import HTTPException
from .models import Consignment,VaseSample,Clock,Experiment,ExperimentPair,ExperimentSlot
from .common import lock,pack,add,audit
def slot_of(s,exp_id,sample_id):
    return s.scalar(select(ExperimentSlot).join(ExperimentPair,ExperimentPair.id==ExperimentSlot.pair_id).where(ExperimentPair.experiment_id==exp_id,ExperimentSlot.sample_id==sample_id))
def create(s,d,u):
    cons=lock(s,Consignment,d.consignment_id);clock=lock(s,Clock,1)
    taken=select(ExperimentSlot.sample_id)
    pool=s.scalars(select(VaseSample).where(VaseSample.consignment_id==cons.id,VaseSample.prediction.isnot(None),VaseSample.observed_days.is_(None),VaseSample.id.notin_(taken))).all()
    pool=sorted(pool,key=lambda x:(x.prediction['vase_days'],x.id))
    need=2*(d.primary_pairs+d.backup_pairs)
    if len(pool)<need:raise HTTPException(409,'同批可配留样不足：需'+str(need)+'枝已估级且未封存实测，现仅'+str(len(pool))+'枝，整场退回')
    exp=add(s,Experiment(code=d.code,consignment_id=cons.id,primary_pairs=d.primary_pairs,created_at=clock.now))
    for i in range(d.primary_pairs+d.backup_pairs):
        a,b=pool[2*i],pool[2*i+1]
        pair=ExperimentPair(experiment_id=exp['id'],seq=i+1,role='primary' if i<d.primary_pairs else 'backup',status='active' if i<d.primary_pairs else 'standby',activated_at=clock.now if i<d.primary_pairs else None);s.add(pair);s.flush()
        if secrets.randbelow(2):a,b=b,a
        s.add(ExperimentSlot(pair_id=pair.id,sample_id=a.id,arm='treatment',locked_estimate=a.prediction['vase_days']))
        s.add(ExperimentSlot(pair_id=pair.id,sample_id=b.id,arm='control',locked_estimate=b.prediction['vase_days']))
    audit(s,u,'开测保鲜液对比 '+d.code+' 正选'+str(d.primary_pairs)+'对 候补'+str(d.backup_pairs)+'对，配对/签/估值已锁定')
    return exp
def damage(s,id,d,u):
    exp=lock(s,Experiment,id);clock=lock(s,Clock,1)
    if exp.state!='running':raise HTTPException(409,'试验已定稿，破损与定稿以先办成的为准')
    slot=slot_of(s,exp.id,d.sample_id)
    if not slot:raise HTTPException(404,'该留样不在本场试验中')
    if slot.damaged_at:return pack(exp)
    slot.damaged_at=clock.now
    pair=s.get(ExperimentPair,slot.pair_id);code=s.get(VaseSample,slot.sample_id).code
    note='登记破损 '+code
    if pair.status=='active':
        pair.status='void';note+='，第'+str(pair.seq)+'对整对作废'
        nxt=s.scalar(select(ExperimentPair).where(ExperimentPair.experiment_id==exp.id,ExperimentPair.status=='standby').order_by(ExperimentPair.seq).limit(1))
        if nxt:nxt.status='active';nxt.activated_at=clock.now;note+='，按原顺序启用候补第'+str(nxt.seq)+'对'
        else:note+='，候补已用尽'
    elif pair.status=='standby':pair.status='void';note+='，候补第'+str(pair.seq)+'对作废跳过'
    else:note+='，所在对已作废，仅留记录'
    audit(s,u,note);return pack(exp)
def measure(s,id,d,u):
    exp=lock(s,Experiment,id)
    slot=slot_of(s,exp.id,d.sample_id)
    if not slot:raise HTTPException(404,'该留样不在本场试验中')
    pair=s.get(ExperimentPair,slot.pair_id)
    if pair.status=='standby' or (pair.status=='void' and pair.role=='backup' and pair.activated_at is None):
        raise HTTPException(409,'候补对启用前不登记实测')
    if slot.actual_days is not None:
        if slot.actual_days==d.actual_days:return pack(exp)
        raise HTTPException(409,'该枝实测已登记，不能覆盖')
    slot.actual_days=d.actual_days
    code=s.get(VaseSample,slot.sample_id).code
    audit(s,u,'登记实测 '+code+' '+str(d.actual_days)+'天'+('（作废对晚报照存）' if pair.status=='void' else ''))
    return pack(exp)
def finalize(s,id,u):
    exp=lock(s,Experiment,id);clock=lock(s,Clock,1)
    if exp.state!='running':raise HTTPException(409,'只能定稿一次')
    pairs=s.scalars(select(ExperimentPair).where(ExperimentPair.experiment_id==exp.id,ExperimentPair.status=='active').order_by(ExperimentPair.seq)).all()
    if len(pairs)<exp.primary_pairs:raise HTTPException(409,'正选未补齐且候补已用尽，不能定稿')
    detail=[];diffs=[]
    for p in pairs:
        slots=s.scalars(select(ExperimentSlot).where(ExperimentSlot.pair_id==p.id)).all()
        t=next(x for x in slots if x.arm=='treatment');c=next(x for x in slots if x.arm=='control')
        if t.actual_days is None or c.actual_days is None:raise HTTPException(409,'第'+str(p.seq)+'对实测未到齐，不能定稿')
        diff=round((t.actual_days-c.actual_days)-(t.locked_estimate-c.locked_estimate),3)
        diffs.append(diff);detail.append({'seq':p.seq,'treatment_sample_id':t.sample_id,'control_sample_id':c.sample_id,'actual_gap':round(t.actual_days-c.actual_days,3),'estimate_gap':round(t.locked_estimate-c.locked_estimate,3),'adjusted_days':diff})
    exp.conclusion_days=round(sum(diffs)/len(diffs),2);exp.conclusion={'pairs':detail,'pair_count':len(diffs)}
    exp.state='finalized';exp.finalized_at=clock.now
    audit(s,u,'定稿保鲜液对比 '+exp.code+'，平均每对多撑 '+str(exp.conclusion_days)+' 天')
    return pack(exp)
