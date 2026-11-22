from app.modules.reconcile.rules import reconcile
from copy import deepcopy

def test_input_rows_real(sample):
    assert sample['balance']['input']==40;assert sample['balance']['accepted']==32;assert sample['balance']['quarantined']==5;assert sample['balance']['row_balanced']
def test_clean_energy_real(clean):
    # 原INV-A/INV-B损失不变(26.6667)；新增南区设备抬高实际与基准电量，能量仍守恒。
    assert clean['balance']['loss_kwh']=='26.6667';assert clean['balance']['actual_kwh']=='93.3333';assert clean['balance']['energy_balanced']
    # 设备削峰来自应发潜力超额定部分，独立于原损失口径，不混入可申报损失。
    assert clean['balance']['dispatch_kwh']=='26.6667';assert clean['balance']['clipping_kwh']=='2.6667';assert clean['balance']['pending_kwh']=='0.0000'
def test_unknown_time_real(sample):
    assert sample['balance']['unknown_seconds']==1200;assert sample['balance']['unknown_segments']==2
def test_union_time_conservation(clean):
    # 新增南区两台目标机后并集总时长：INV-A 1800 + INV-B 1200 + INV-C/INV-D 各1200。
    assert clean['balance']['union_seconds']==clean['balance']['slice_seconds']==5400
def test_time_tamper(clean):
    s=deepcopy(clean);s['energy_rows'][0]['seconds']+=1;assert reconcile(s)['time_balanced'] is False
def test_energy_tamper(clean):
    s=deepcopy(clean);s['energy_rows'][0]['loss_kwh']='999';assert reconcile(s)['energy_balanced'] is False
def test_record_tamper(sample):
    s=deepcopy(sample);s['records'].pop();assert reconcile(s)['row_balanced'] is False
