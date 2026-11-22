from decimal import Decimal
from app.coerce import instant, number

# 归责原因码：
# GRID_CAP        调度并网点上限低于基线，缺额可向调度申报
# DEVICE_CLIPPING 设备交流额定容量比调度上限更紧，属于设备固有削峰
# PENDING         实际功率低于采用上限，无法证明是限电，列入待查
# NO_BASELINE     基线未定（缺测/故障/无合格对照），整段保持未定，不填0
Q4 = Decimal('.0001')


def load_windows(basis):
    """把上限依据按设备分组并转成UTC时间，便于半开区间命中。"""
    grouped = {}
    if not basis:
        return grouped
    for w in basis.get('windows', []):
        grouped.setdefault(w['device'], []).append(
            {'start': instant(w['start']), 'end': instant(w['end']),
             'cap_kw': number(w['cap_kw']), 'id': w['id'], 'source': w.get('source', '')})
    for rows in grouped.values():
        rows.sort(key=lambda r: (r['start'], r['end']))
    return grouped


def grid_cap_for(device, sample_at, windows):
    """命中覆盖采样时刻的半开时间窗 [start,end)；无调度窗口时返回None。"""
    at = instant(sample_at)
    for w in windows.get(device, ()):
        if w['start'] <= at < w['end']:
            return w
    return None


def attribute_segment(estimate, context, windows):
    """对单个损失估算段做可归责拆分。返回新增的归责字段，不修改入参。

    口径（potential为未被本机额定截断的应发潜力，baseline已被额定容量截断）：
      设备削峰 = (potential − min(potential, 额定))⁺        —— 设备交流额定容量固有约束
      调度缺额 = (min(potential, 额定) − min(调度上限, 额定))⁺ —— 并网点调度约束
      待查     = (采用上限 − 实际)⁺                          —— 实际未达采用上限
    三者之和恒等于 (potential − 实际)⁺；其中后两者之和等于原损失 (baseline − 实际)⁺。
    """
    base = {'grid_cap_kw': None, 'binding_cap_kw': None, 'cap_basis_id': '',
            'dispatch_kwh': None, 'clipping_kwh': None, 'pending_kwh': None,
            'attribution_code': 'NO_BASELINE', 'cap_reason': '基线未定，整段待查'}
    if estimate.get('baseline_kw') is None or estimate.get('actual_kw') is None:
        return base
    hours = Decimal(estimate['seconds']) / Decimal(3600)
    baseline = number(estimate['baseline_kw'])
    actual = number(estimate['actual_kw'])
    potential = number(estimate['potential_kw']) if estimate.get('potential_kw') is not None else baseline
    capacity = number(context['devices'][estimate['device']]['capacity_kw'])
    win = grid_cap_for(estimate['device'], estimate['sample_at'], windows)
    if win is None:
        # 没有调度并网点上限：唯一硬约束是设备交流额定容量。
        grid_cap = capacity
        base['cap_reason'] = '无调度窗口，采用设备交流额定容量'
    else:
        grid_cap = win['cap_kw']
        base['grid_cap_kw'] = str(grid_cap)
        base['cap_basis_id'] = win['id']
        base['cap_reason'] = f"调度窗口 {win['id']}" + (f"（{win['source']}）" if win['source'] else '')
    binding = min(grid_cap, capacity)
    base['binding_cap_kw'] = str(binding)

    rated_potential = min(potential, capacity)
    # 设备削峰：应发潜力超出本机交流额定容量的部分，与调度窗口无关，物理上独立。
    clipping = max(Decimal(0), potential - rated_potential) * hours
    if actual > binding:
        # 实际功率高于采用上限：调度依据与遥测自相矛盾，无法证明任何调度影响，
        # 原损失整段转入待查，不得申报；设备削峰仍按物理口径保留。
        dispatch = Decimal(0)
        pending = max(Decimal(0), rated_potential - actual) * hours
        base['cap_reason'] = base['cap_reason'] + '；实际超出采用上限，依据矛盾，整段待查'
        code = 'PENDING'
    else:
        dispatch = max(Decimal(0), rated_potential - binding) * hours
        pending = max(Decimal(0), binding - actual) * hours
        if pending > 0:
            code = 'PENDING'
        elif dispatch > 0:
            code = 'GRID_CAP'
        elif clipping > 0:
            code = 'DEVICE_CLIPPING'
        else:
            code = 'NO_LOSS'
    base['clipping_kwh'] = str(clipping)
    base['dispatch_kwh'] = str(dispatch)
    base['pending_kwh'] = str(pending)
    base['attribution_code'] = code
    return base


def attribute_all(estimates, context, basis):
    windows = load_windows(basis)
    rows = []
    for estimate in estimates:
        rows.append({**estimate, **attribute_segment(estimate, context, windows)})
    return rows


def summarize(energy_rows):
    """汇总三类分量与待查时长；未定段不并入任何确定分量。"""
    known = [r for r in energy_rows if r.get('dispatch_kwh') is not None]
    unknown = [r for r in energy_rows if r.get('dispatch_kwh') is None]
    totals = {k: sum((number(r[k]) for r in known), Decimal(0))
              for k in ('dispatch_kwh', 'clipping_kwh', 'pending_kwh', 'loss_kwh')}
    return {
        'dispatch_kwh': str(totals['dispatch_kwh'].quantize(Q4)),
        'clipping_kwh': str(totals['clipping_kwh'].quantize(Q4)),
        'pending_kwh': str(totals['pending_kwh'].quantize(Q4)),
        'loss_kwh': str(totals['loss_kwh'].quantize(Q4)),
        'known_segments': len(known),
        'unknown_segments': len(unknown),
        'pending_segments': sum(number(r['pending_kwh']) > 0 for r in known),
        'unknown_seconds': sum(r['seconds'] for r in unknown),
    }


def conservation(energy_rows):
    """逐段校验拆分守恒，防止同一缺额被重复归因：
    1) 调度+设备削峰+待查 == (potential−实际)⁺×时长（全缺额只归一次）
    2) 调度+待查 == 原损失 loss_kwh（设备削峰来自potential超出额定的部分，不混入原损失）
    周期小数按全局0.0001kWh精度量化后比较。
    """
    for r in energy_rows:
        if r.get('dispatch_kwh') is None:
            continue
        parts = number(r['dispatch_kwh']) + number(r['clipping_kwh']) + number(r['pending_kwh'])
        potential = number(r['potential_kw']) if r.get('potential_kw') is not None else number(r['baseline_kw'])
        hours = Decimal(r['seconds']) / Decimal(3600)
        total_gap = max(Decimal(0), potential - number(r['actual_kw'])) * hours
        if parts.quantize(Q4) != total_gap.quantize(Q4):
            return False
        if (number(r['dispatch_kwh']) + number(r['pending_kwh'])).quantize(Q4) != number(r['loss_kwh']).quantize(Q4):
            return False
    return True
