from app.caps.attribution import attribute_all, summarize, conservation


def apply(state):
    """在损失积分结果上叠加可归责拆分，并产出三类汇总。"""
    basis = state.get('cap_basis')
    rows = attribute_all(state['energy_rows'], state['context'], basis)
    state['energy_rows'] = rows
    summary = summarize(rows)
    summary['conservation_ok'] = conservation(rows)
    basis_id = basis['basis_id'] if basis else ''
    summary['cap_basis_id'] = basis_id
    state['attribution_summary'] = summary
    apply_view(state)


def apply_view(state):
    """依据已更新的energy_rows重建归责视图（增量重算后调用）。"""
    rows = state['energy_rows']
    summary = state['attribution_summary']
    basis_id = summary.get('cap_basis_id', '')
    state['views']['attribution'] = {
        'title': '限电损失归责',
        'rows': [{k: v for k, v in r.items()
                  if k not in ('sample_at', 'zone', 'irradiance', 'status')} for r in rows],
        'metrics': {
            '可申报损失_kWh': summary['dispatch_kwh'],
            '设备削峰_kWh': summary['clipping_kwh'],
            '待查片段_kWh': summary['pending_kwh'],
            '待查片段数': summary['pending_segments'],
            '未定片段': summary['unknown_segments'],
            '拆分守恒': '通过' if summary['conservation_ok'] else '失败',
            '上限依据': basis_id,
        },
    }
