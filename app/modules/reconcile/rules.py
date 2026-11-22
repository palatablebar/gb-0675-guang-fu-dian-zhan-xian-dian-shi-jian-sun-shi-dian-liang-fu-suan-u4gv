from decimal import Decimal
from app.coerce import number
from app.caps.attribution import conservation


def reconcile(state):
    known=[r for r in state['energy_rows'] if r['loss_kwh'] is not None];unknown=[r for r in state['energy_rows'] if r['loss_kwh'] is None]
    sums={k:sum((number(r[k]) for r in known),Decimal(0)) for k in ['loss_kwh','actual_kwh','baseline_kwh']}
    union_seconds=sum(r['seconds'] for r in state['event_unions']);slice_seconds=sum(r['seconds'] for r in state['energy_rows']);c=state['counts'];explained=len(state['records'])+len(state['quarantine'])+c['blank']+c['duplicate']+c['repeated_header']
    # Decimal周期小数允许最后一位精度误差，展示前统一量化到0.0001kWh再检查。
    quant=lambda v:v.quantize(Decimal('.0001'))
    attributed=[r for r in known if r.get('dispatch_kwh') is not None]
    dispatch=sum((number(r['dispatch_kwh']) for r in attributed),Decimal(0))
    clipping=sum((number(r['clipping_kwh']) for r in attributed),Decimal(0))
    pending=sum((number(r['pending_kwh']) for r in attributed),Decimal(0))
    summary=state.get('attribution_summary',{})
    return {'input':c['input'],'accepted':len(state['records']),'quarantined':len(state['quarantine']),'row_balanced':explained==c['input'],'union_seconds':union_seconds,'slice_seconds':slice_seconds,'time_balanced':union_seconds==slice_seconds,'loss_kwh':str(quant(sums['loss_kwh'])),'actual_kwh':str(quant(sums['actual_kwh'])),'baseline_kwh':str(quant(sums['baseline_kwh'])),'energy_balanced':quant(sums['baseline_kwh'])==quant(sums['actual_kwh']+sums['loss_kwh']),'unknown_segments':len(unknown),'unknown_seconds':sum(r['seconds'] for r in unknown),
            'dispatch_kwh':str(quant(dispatch)),'clipping_kwh':str(quant(clipping)),'pending_kwh':str(quant(pending)),
            'pending_segments':summary.get('pending_segments',sum(number(r['pending_kwh'])>0 for r in attributed)),
            'attribution_balanced':conservation(state['energy_rows'])}
def apply(state):
    state['balance']=reconcile(state);state['views']['reconcile']={'title':'时间与能量四账','rows':[state['balance']],'metrics':{'可申报损失_kWh':state['balance']['dispatch_kwh'],'设备削峰_kWh':state['balance']['clipping_kwh'],'待查_kWh':state['balance']['pending_kwh'],'未定分钟':state['balance']['unknown_seconds']//60,'并集分钟':state['balance']['union_seconds']//60}}
