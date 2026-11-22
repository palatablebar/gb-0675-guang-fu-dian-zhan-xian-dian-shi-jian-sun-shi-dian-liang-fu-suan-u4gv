from decimal import Decimal
from app.caps.attribution import attribute_segment, attribute_all, summarize, conservation, load_windows
from app.caps.parser import parse_cap_basis
from app.config import ROOT


def _windows(clean):
    raw = (ROOT / 'sample_data' / 'cap_basis.csv').read_bytes()
    return parse_cap_basis(raw, clean['context'])


def test_dispatch_claimable_not_device(clean):
    # INV-A：基线100、调度上限60、实际60，缺额全部可向调度申报，设备削峰为0。
    basis = _windows(clean)
    rows = attribute_all(clean['energy_rows'], clean['context'], basis)
    inv_a = [r for r in rows if r['device'] == 'INV-A']
    assert sum(Decimal(r['dispatch_kwh']) for r in inv_a).quantize(Decimal('.0001')) == Decimal('20.0000')
    assert sum(Decimal(r['clipping_kwh']) for r in inv_a) == Decimal('0')
    assert all(r['attribution_code'] == 'GRID_CAP' for r in inv_a)


def test_device_clipping_isolated_from_dispatch(clean):
    # INV-C：应发潜力105 > 额定100，且无调度窗口；5kW属设备固有削峰，不可申报。
    basis = _windows(clean)
    rows = attribute_all(clean['energy_rows'], clean['context'], basis)
    inv_c = [r for r in rows if r['device'] == 'INV-C']
    assert all(r['grid_cap_kw'] is None for r in inv_c)
    assert all(r['attribution_code'] == 'DEVICE_CLIPPING' for r in inv_c)
    assert sum(Decimal(r['clipping_kwh']) for r in inv_c).quantize(Decimal('.0001')) == Decimal('1.6667')
    assert sum(Decimal(r['dispatch_kwh']) for r in inv_c) == Decimal('0')


def test_three_way_conservation_no_double_count(clean):
    basis = _windows(clean)
    rows = attribute_all(clean['energy_rows'], clean['context'], basis)
    assert conservation(rows) is True
    q = Decimal('.0001')
    for r in rows:
        parts = Decimal(r['dispatch_kwh']) + Decimal(r['clipping_kwh']) + Decimal(r['pending_kwh'])
        potential = Decimal(r['potential_kw'])
        total = max(Decimal(0), potential - Decimal(r['actual_kw'])) * Decimal(r['seconds']) / 3600
        # 周期小数在第四位量化后必须严格相等（同一缺额只归一次）。
        assert parts.quantize(q) == total.quantize(q)
        # 调度+待查必须等于原损失口径，设备削峰不得重复计入。
        assert Decimal(r['dispatch_kwh']) + Decimal(r['pending_kwh']) == Decimal(r['loss_kwh'])


def test_pending_when_actual_below_binding_cap(clean):
    # 实际低于采用上限：缺额无法证明是限电，列入待查，不申报。
    basis = _windows(clean)
    seg = dict(clean['estimates'][0], actual_kw='40')  # INV-A 上限60，实际40
    out = attribute_segment(seg, clean['context'], load_windows(basis))
    assert out['attribution_code'] == 'PENDING'
    assert Decimal(out['pending_kwh']) > 0
    q = Decimal('.0001')
    # 调度缺额仍是 100->60 的部分，待查是 60->40，二者不重叠。
    assert Decimal(out['dispatch_kwh']).quantize(q) == ((Decimal('100') - Decimal('60')) * Decimal(seg['seconds']) / 3600).quantize(q)
    assert Decimal(out['pending_kwh']).quantize(q) == ((Decimal('60') - Decimal('40')) * Decimal(seg['seconds']) / 3600).quantize(q)


def test_contradiction_actual_above_cap_goes_pending(clean):
    # 实际功率高于调度上限：依据与遥测矛盾，整段不得申报，转待查。
    from app.modules.loss.rules import integrate
    seg = dict(clean['estimates'][0], actual_kw='60')
    integrated = integrate(seg)
    # 构造一个比实际更低的调度上限 50。
    tight = {'windows': [{'device': 'INV-A', 'start': '2026-10-15T02:00:00+00:00',
                          'end': '2026-10-15T02:30:00+00:00', 'cap_kw': '50', 'id': 'TIGHT'}]}
    out = attribute_segment(seg, clean['context'], load_windows(tight))
    assert out['attribution_code'] == 'PENDING'
    assert Decimal(out['dispatch_kwh']) == Decimal('0')
    assert Decimal(out['pending_kwh']) == Decimal(integrated['loss_kwh'])


def test_no_baseline_segment_stays_unknown(sample):
    # 缺测/无对照片段：归责三字段保持None，不填0。
    basis = _windows(sample)
    rows = attribute_all(sample['energy_rows'], sample['context'], basis)
    unknown = [r for r in rows if r['baseline_kw'] is None]
    assert unknown and all(r['dispatch_kwh'] is None and r['attribution_code'] == 'NO_BASELINE' for r in unknown)


def test_summary_totals_quantized(clean):
    basis = _windows(clean)
    rows = attribute_all(clean['energy_rows'], clean['context'], basis)
    summary = summarize(rows)
    assert summary['dispatch_kwh'] == '26.6667'
    assert summary['clipping_kwh'] == '2.6667'
    assert summary['pending_kwh'] == '0.0000'
    assert summary['unknown_segments'] == 0
