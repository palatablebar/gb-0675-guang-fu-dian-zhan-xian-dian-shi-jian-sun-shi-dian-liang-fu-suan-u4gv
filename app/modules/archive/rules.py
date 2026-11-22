import hashlib,json

def archive_decision(state):
    b=state['balance']
    # 封存要求：行/时间/能量/归责守恒全部通过，且无隔离、无未定、无待查片段。
    ready=(b['row_balanced'] and b['time_balanced'] and b['energy_balanced']
           and b.get('attribution_balanced',False) and not b['unknown_segments']
           and not b.get('pending_segments',0) and not state['quarantine'])
    return {'status':'可归档' if ready else '待复核','seal':hashlib.sha256(json.dumps(state['energy_rows'],sort_keys=True).encode()).hexdigest(),'segments':len(state['energy_rows']),'unknown':b['unknown_segments'],'pending':b.get('pending_segments',0)}
def apply(state):
    state['archive']=archive_decision(state);state['views']['archive']={'title':'运行凭证','rows':state['event_unions'],'metrics':{'切片':state['archive']['segments'],'未定':state['archive']['unknown'],'待查':state['archive']['pending'],'状态':state['archive']['status']}}
