import pytest
from app.caps.parser import parse_cap_basis, basis_digest
from app.config import ROOT
from app.errors import BusinessError

CONTEXT_DEVICE = {'devices': {'INV-A': {'zone': '东区', 'capacity_kw': '100'},
                              'INV-B': {'zone': '西区', 'capacity_kw': '50'}}}
HEADER = 'id,device,start,end,cap_kw,source\n'


def _basis(text):
    return parse_cap_basis(text.encode(), CONTEXT_DEVICE)


def test_sample_basis_parses():
    raw = (ROOT / 'sample_data' / 'cap_basis.csv').read_bytes()
    from app.engine import evaluate
    ctx = evaluate({'dataset': 'clean'})['context']
    basis = parse_cap_basis(raw, ctx)
    assert basis['basis_id'] == basis_digest(raw)[:16]
    assert len(basis['windows']) >= 2
    assert basis['quarantine'] == []


def test_unknown_device_quarantined():
    text = HEADER + (
        'GOOD,INV-A,2026-10-15T11:00:00+08:00,2026-10-15T11:10:00+08:00,60,台\n'
        'X1,INV-Z,2026-10-15T10:00:00+08:00,2026-10-15T10:10:00+08:00,50,台')
    basis = _basis(text)
    assert basis['quarantine'][0]['code'] == 'CAP_UNKNOWN_DEVICE'
    assert len(basis['windows']) == 1
    with pytest.raises(BusinessError) as e:
        _basis(HEADER + 'X1,INV-Z,2026-10-15T10:00:00+08:00,2026-10-15T10:10:00+08:00,50,台')
    # 唯一行被隔离时整份无有效窗口。
    assert e.value.code == 'NO_VALID_CAP'


def test_overlapping_windows_quarantined():
    text = HEADER + (
        'W1,INV-A,2026-10-15T10:00:00+08:00,2026-10-15T10:20:00+08:00,60,台\n'
        'W2,INV-A,2026-10-15T10:10:00+08:00,2026-10-15T10:30:00+08:00,55,台')
    basis = _basis(text)
    codes = {q['code'] for q in basis['quarantine']}
    assert 'CAP_OVERLAP' in codes
    assert len(basis['windows']) == 1


def test_cap_above_rating_rejected():
    text = HEADER + (
        'GOOD,INV-A,2026-10-15T11:00:00+08:00,2026-10-15T11:10:00+08:00,60,台\n'
        'W1,INV-B,2026-10-15T10:00:00+08:00,2026-10-15T10:10:00+08:00,80,台')
    basis = _basis(text)
    assert basis['quarantine'][0]['code'] == 'CAP_ABOVE_RATING'
    assert len(basis['windows']) == 1


def test_bad_time_and_positive():
    text = HEADER + (
        'GOOD,INV-A,2026-10-15T11:00:00+08:00,2026-10-15T11:10:00+08:00,60,台\n'
        'W1,INV-A,2026-10-15T10:10:00+08:00,2026-10-15T10:00:00+08:00,60,台\n'
        'W2,INV-A,2026-10-15T12:00:00+08:00,2026-10-15T12:10:00+08:00,0,台')
    basis = _basis(text)
    codes = {q['code'] for q in basis['quarantine']}
    assert 'CAP_INVALID_RANGE' in codes and 'CAP_NON_POSITIVE' in codes
    assert len(basis['windows']) == 1


def test_empty_and_bad_header():
    with pytest.raises(BusinessError) as e:
        parse_cap_basis(b'', CONTEXT_DEVICE)
    assert e.value.code == 'EMPTY_CAP_FILE'
    with pytest.raises(BusinessError) as e:
        parse_cap_basis(b'id,device\nx,INV-A', CONTEXT_DEVICE)
    assert e.value.code == 'BAD_CAP_HEADER'


def test_chinese_alias_header():
    raw = '编号,设备,开始,结束,并网点上限kW,依据来源\nW1,INV-A,2026-10-15T10:00:00+08:00,2026-10-15T10:10:00+08:00,60,调度台'.encode()
    basis = parse_cap_basis(raw, CONTEXT_DEVICE)
    assert basis['windows'][0]['cap_kw'] == '60'
