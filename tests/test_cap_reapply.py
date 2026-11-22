import io
import zipfile
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from app import main, store
from app.engine import evaluate, reapply
from app.caps.parser import parse_cap_basis
from app.modules.caps.rules import ensure_default_basis


def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB_PATH', str(tmp_path / 'test.sqlite'))
    c = TestClient(main.app)
    # 非lifespan客户端：显式登记样例默认依据（生产环境由lifespan预热）。
    probe = evaluate({'dataset': 'clean'})
    ensure_default_basis(main.DB_PATH, probe['context'])
    return c


def _basis(clean_state, csv_text):
    return parse_cap_basis(csv_text.encode(), clean_state['context'])


def test_reapply_only_recomputes_affected_segments(tmp_path):
    # 直接调用纯重算：只改 INV-A 依据时，INV-B/C/D 的归责结果必须保持不变。
    clean = evaluate({'dataset': 'clean'})
    old_dispatch = {(r['device'], r['start']): r['dispatch_kwh'] for r in clean['energy_rows']}
    # 新依据保留INV-B原窗口、仅调整INV-A，确保只有INV-A被牵连。
    new_csv = ('id,device,start,end,cap_kw,source\n'
               'CAP-A2,INV-A,2026-10-15T10:00:00+08:00,2026-10-15T10:30:00+08:00,80,二次指令\n'
               'CAP-B-AM,INV-B,2026-10-15T10:00:00+08:00,2026-10-15T10:20:00+08:00,30,台')
    new_basis = _basis(clean, new_csv)
    new_state, affected = reapply(clean, new_basis)
    inv_a_count = sum(1 for r in clean['energy_rows'] if r['device'] == 'INV-A')
    assert affected == inv_a_count == 3
    # 未受牵连设备逐字段保持。
    for r in new_state['energy_rows']:
        if r['device'] != 'INV-A':
            assert r['dispatch_kwh'] == old_dispatch[(r['device'], r['start'])]
    # 受牵连设备按新上限重算（上限60->80，可申报损失下降）。
    inv_a = sum(Decimal(r['dispatch_kwh']) for r in new_state['energy_rows'] if r['device'] == 'INV-A')
    assert inv_a.quantize(Decimal('.0001')) == Decimal('10.0000')


def test_switch_is_transactional_and_audited(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={'dataset': 'clean'}).json()
    rid = run['manifest']['run_id']
    new_csv = ('id,device,start,end,cap_kw,source\n'
               'CAP-A2,INV-A,2026-10-15T10:00:00+08:00,2026-10-15T10:30:00+08:00,80,二次指令')
    up = c.post('/api/cap-bases', json={'csv_text': new_csv, 'label': '二次修正'}).json()
    before = c.get(f'/api/runs/{rid}').json()['attribution_summary']['dispatch_kwh']
    res = c.post(f'/api/runs/{rid}/cap-basis', json={'basis_id': up['basis_id']})
    assert res.status_code == 200
    assert res.json()['changed'] is True
    after = c.get(f'/api/runs/{rid}').json()['attribution_summary']['dispatch_kwh']
    assert after != before
    audit = c.get(f'/api/runs/{rid}/cap-audit').json()
    assert audit['applied_basis'] == up['basis_id']
    assert audit['audit'][0]['to_basis'] == up['basis_id']
    assert audit['audit'][0]['affected_segments'] >= 1


def test_same_basis_retry_is_idempotent(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={'dataset': 'clean'}).json()
    rid = run['manifest']['run_id']
    default_id = run['cap_basis']['basis_id']
    # 首次应用默认依据（产生一次APPLY审计）。
    first_apply = c.post(f'/api/runs/{rid}/cap-basis', json={'basis_id': default_id}).json()
    assert first_apply['changed'] is True
    audit_count = len(c.get(f'/api/runs/{rid}/cap-audit').json()['audit'])
    # 同依据连续重试：不新增审计、不产生新版本、不改动凭据。
    first = c.post(f'/api/runs/{rid}/cap-basis', json={'basis_id': default_id}).json()
    second = c.post(f'/api/runs/{rid}/cap-basis', json={'basis_id': default_id}).json()
    assert first['changed'] is False and second['changed'] is False
    audit = c.get(f'/api/runs/{rid}/cap-audit').json()['audit']
    assert len(audit) == audit_count
    bases = c.get('/api/cap-bases').json()['bases']
    assert any(b['basis_id'] == default_id for b in bases)


def test_rollback_restores_old_version_on_failure(tmp_path, monkeypatch):
    from app.modules.caps.rules import ensure_default_basis
    c = client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={'dataset': 'clean'}).json()
    rid = run['manifest']['run_id']
    old = c.get(f'/api/runs/{rid}').json()
    ensure_default_basis(main.DB_PATH, old['context'])
    # 让重算函数抛错，模拟切换中途中断。
    def boom(old_result, parsed):
        raise RuntimeError('simulated interruption')
    with pytest.raises(RuntimeError):
        store.reapply_basis(main.DB_PATH, rid, old['cap_basis']['basis_id'], boom)
    recovered = c.get(f'/api/runs/{rid}').json()
    # 旧版结果完整保留。
    assert recovered['attribution_summary']['dispatch_kwh'] == old['attribution_summary']['dispatch_kwh']
    assert recovered['cap_basis']['basis_id'] == old['cap_basis']['basis_id']


def test_raw_credentials_never_deleted_and_exported(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={'dataset': 'clean'}).json()
    rid = run['manifest']['run_id']
    csv_text = ('id,device,start,end,cap_kw,source\n'
                'CAP-A2,INV-A,2026-10-15T10:00:00+08:00,2026-10-15T10:30:00+08:00,80,二次指令')
    up = c.post('/api/cap-bases', json={'csv_text': csv_text}).json()
    # 切换到新依据后，新旧两份原始凭据都仍可下载。
    raw_new = c.get(f"/api/cap-bases/{up['basis_id']}/raw")
    assert raw_new.status_code == 200 and 'CAP-A2' in raw_new.text
    default_id = run['cap_basis']['basis_id']
    raw_old = c.get(f'/api/cap-bases/{default_id}/raw')
    assert raw_old.status_code == 200 and 'CAP-A-AM' in raw_old.text
    c.post(f'/api/runs/{rid}/cap-basis', json={'basis_id': up['basis_id']})
    z = zipfile.ZipFile(io.BytesIO(c.get(f'/api/export/{rid}').content))
    names = z.namelist()
    assert 'cap_basis_original.csv' in names and 'attribution_rows.json' in names
    assert 'CAP-A2' in z.read('cap_basis_original.csv').decode()


def test_default_basis_export_contains_raw_csv(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    rid = c.post('/api/runs', json={'dataset': 'clean'}).json()['manifest']['run_id']
    z = zipfile.ZipFile(io.BytesIO(c.get(f'/api/export/{rid}').content))
    assert 'cap_basis_original.csv' in z.namelist()
    assert 'CAP-A-AM' in z.read('cap_basis_original.csv').decode()


def test_pages_show_three_categories(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    rid = c.post('/api/runs', json={'dataset': 'clean'}).json()['manifest']['run_id']
    html = c.get(f'/attribution?run_id={rid}').text
    assert '可申报损失' in html and '设备削峰' in html and '待查片段' in html
    caps_html = c.get(f'/caps?run_id={rid}').text
    assert '并网点调度上限依据' in caps_html
