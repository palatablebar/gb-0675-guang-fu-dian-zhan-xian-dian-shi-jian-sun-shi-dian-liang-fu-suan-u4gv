import io, json, zipfile
from app.errors import BusinessError


def serialize(result, cap_raw=None):
    if not result.get('manifest') or not result.get('views'):
        raise BusinessError('INCOMPLETE_RUN', '批次尚未完成')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps(
            {**result['manifest'], 'revision': result.get('revision', 1),
             'status': result.get('status', '待复核'),
             'applied_cap_basis': (result.get('cap_basis') or {}).get('basis_id')},
            ensure_ascii=False, indent=2))
        archive.writestr('evidence.json', json.dumps(
            {'counts': result['counts'], 'views': result['views'],
             'quarantine': result['quarantine'],
             'attribution_summary': result.get('attribution_summary'),
             'cap_basis': result.get('cap_basis')},
            ensure_ascii=False, indent=2))
        archive.writestr('attribution_rows.json', json.dumps(
            result.get('energy_rows', []), ensure_ascii=False, indent=2))
        # 上限依据原始凭据单独留档，复核可逐段追溯采用的是哪条窗口。
        cap = result.get('cap_basis')
        if cap:
            archive.writestr('cap_basis.json', json.dumps(cap, ensure_ascii=False, indent=2))
        if cap_raw is not None:
            archive.writestr('cap_basis_original.csv', cap_raw)
    return buffer.getvalue()
