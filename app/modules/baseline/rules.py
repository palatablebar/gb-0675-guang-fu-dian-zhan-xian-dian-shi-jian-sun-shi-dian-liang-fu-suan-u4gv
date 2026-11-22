from decimal import Decimal
from app.coerce import number,instant

def estimate(segment,records,context):
    base={**segment,'baseline_kw':None,'potential_kw':None,'reference_ids':[]}
    if segment['actual_kw'] is None:return {**base,'code':'TARGET_GAP'}
    if segment['status']!='健康':return {**base,'code':'TARGET_FAULT'}
    target=context['devices'][segment['device']];width=number(context['irradiance_bin']);target_bin=number(segment['irradiance'])//width
    references=[]
    for row in records:
        if row['kind']!='TELEMETRY' or row['device']==segment['device']:continue
        device=context['devices'][row['device']]
        if not device['reference'] or device['zone']!=segment['zone'] or row['status']!='健康' or row['at']!=segment['sample_at']:continue
        if number(row['irradiance'])//width!=target_bin:continue
        if any(e['kind']=='EVENT' and e['device']==row['device'] and instant(e['start'])<=instant(row['at'])<instant(e['end']) for e in records):continue
        capacity=number(device['capacity_kw'])
        if capacity<=0:continue
        references.append((number(row['power_kw'])/capacity,row['id']))
    if len(references)<context['min_references']:return {**base,'reference_ids':[x[1] for x in references],'code':'NO_REFERENCE'}
    ratios=sorted(x[0] for x in references);mid=len(ratios)//2;ratio=ratios[mid] if len(ratios)%2 else (ratios[mid-1]+ratios[mid])/2
    rated=number(target['capacity_kw'])
    # potential_kw：对照逆变器归一化得到的应发潜力，未被本机交流额定容量截断；
    # baseline_kw：叠加设备交流额定容量后的可达基线，保持原口径用于损失积分。
    potential=ratio*rated
    baseline=min(rated,potential)
    return {**base,'baseline_kw':str(baseline),'potential_kw':str(potential),'reference_ids':sorted(x[1] for x in references),'code':'ESTIMATED'}

def apply(state):
    estimates=[estimate(s,state['records'],state['context']) for s in state['segments']];state['estimates']=estimates
    state['views']['baseline']={'title':'对照基线','rows':estimates,'metrics':{'可估计':sum(r['code']=='ESTIMATED' for r in estimates),'未定':sum(r['code']!='ESTIMATED' for r in estimates),'对照下限':state['context']['min_references']}}
