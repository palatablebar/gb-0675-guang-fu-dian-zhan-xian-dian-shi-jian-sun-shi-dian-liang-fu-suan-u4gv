from importlib import import_module
from copy import deepcopy
import json, time, base64
from app.config import ROOT, MODULES, MAX_BYTES
from app.errors import BusinessError
from app.manifest import digest, make_manifest
from app.caps.attribution import attribute_all, summarize, conservation

# 归责相关模块在流水线中的序号（1-based，与MODULES对齐）。
CAP_INDEX = MODULES.index('caps') + 1
ATTRIBUTION_INDEX = MODULES.index('attribution') + 1


def evaluate(payload=None, until=len(MODULES), snapshot=None, cap_basis=None):
    payload=payload or {}
    dataset=payload.get('dataset','dirty')
    if dataset not in {'dirty','clean','legacy'}: raise BusinessError('BAD_DATASET','样例名称无效')
    if not isinstance(payload.get('overrides',{}),dict): raise BusinessError('BAD_CONTEXT','参数须为对象')
    raw=(base64.b64decode(snapshot['bytes_b64'],validate=True) if snapshot is not None else (str(payload['csv_text']).encode() if 'csv_text' in payload else (ROOT/'sample_data'/f'{dataset}.csv').read_bytes()))
    if len(raw)>MAX_BYTES: raise BusinessError('TOO_LARGE','文件超过2MB',413)
    context=deepcopy(snapshot['context']) if snapshot is not None else json.loads((ROOT/'sample_data/context.json').read_text())
    context.update(deepcopy(payload.get('overrides',{})))
    start=time.perf_counter()
    state={'raw_bytes':raw,'context':context,'records':[],'quarantine':[], 'counts':{},'views':{},'source':dataset}
    if cap_basis is not None:
        state['cap_basis']=cap_basis
    for index,key in enumerate(MODULES,1):
        if index>until: break
        import_module(f'app.modules.{key}.rules').apply(state)
    state['input_snapshot']={'bytes_b64':base64.b64encode(raw).decode(),'context':deepcopy(context)}
    state.pop('raw_bytes',None)
    state['manifest']=make_manifest(digest(raw,context),dataset,time.perf_counter()-start)
    return state


def _segment_key(row):
    return (row['device'], row['start'], row['end'], row.get('sample_id', ''))


def affected_keys(old_basis, new_basis):
    """上限依据变化时，找出采用上限发生改变的(设备,窗口)，进而定位受牵连切片。"""
    def index_windows(basis):
        out = {}
        for w in (basis or {}).get('windows', []):
            out.setdefault(w['device'], []).append((w['start'], w['end'], str(w['cap_kw']), w['id']))
        return out
    old, new = index_windows(old_basis), index_windows(new_basis)
    devices = set(old) | set(new)
    changed_devices = {d for d in devices if old.get(d) != new.get(d)}
    return changed_devices


def reapply(old_result, new_basis):
    """仅重算受上限依据牵连的归责时段，上游（采信/切片/基线/损失积分）结果原样保留。

    返回 (新state, 受牵连切片数)。新依据须与旧结果同一上下文解析。
    """
    state = deepcopy(old_result)
    old_basis = state.get('cap_basis')
    changed_devices = affected_keys(old_basis, new_basis)
    rows = state['energy_rows']
    # 先按新依据整体重算归责字段，再标记哪些切片的设备受牵连；未受牵连设备结果保持不变。
    recalculated = attribute_all(rows, state['context'], new_basis)
    affected = 0
    merged = []
    recal_by_key = {_segment_key(r): r for r in recalculated}
    for row in rows:
        new_row = recal_by_key[_segment_key(row)]
        if row['device'] in changed_devices:
            affected += 1
            merged.append(new_row)
        else:
            # 未受牵连：保留原归责结果，确保“仅重算受牵连时段”。
            merged.append(row)
    state['energy_rows'] = merged
    state['cap_basis'] = new_basis
    summary = summarize(merged)
    summary['conservation_ok'] = conservation(merged)
    summary['cap_basis_id'] = new_basis['basis_id']
    state['attribution_summary'] = summary
    # 重建受影响模块的视图与下游对账/归档，保证页面与导出一致。
    import_module('app.modules.caps.rules').apply(state)
    import_module('app.modules.attribution.rules').apply_view(state)
    import_module('app.modules.reconcile.rules').apply(state)
    import_module('app.modules.archive.rules').apply(state)
    return state, affected
