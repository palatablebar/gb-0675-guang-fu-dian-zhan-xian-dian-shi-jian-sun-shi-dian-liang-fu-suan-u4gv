import csv
import hashlib
import io
from app.coerce import instant, number
from app.errors import BusinessError

# 上限依据字段：每台设备在一个半开时间窗内的并网点调度功率上限(kW)。
CAP_FIELDS = ['id', 'device', 'start', 'end', 'cap_kw', 'source']
CAP_ALIASES = {'编号': 'id', '设备': 'device', '开始': 'start', '结束': 'end', '并网点上限kW': 'cap_kw', '依据来源': 'source'}


def basis_digest(raw_bytes):
    return hashlib.sha256(raw_bytes).hexdigest()


def _is_blank(cells):
    return not cells or not any(str(v).strip() for v in cells)


def parse_cap_basis(raw_bytes, context):
    """解析上限依据CSV。问题行隔离并给出稳定原因码，不静默丢弃；全无效才拒绝整份。"""
    if not raw_bytes:
        raise BusinessError('EMPTY_CAP_FILE', '上限依据为空')
    if not raw_bytes.strip(b'\xef\xbb\xbf\r\n \t'):
        raise BusinessError('BLANK_CAP_FILE', '上限依据只有空行')
    text = None
    encoding = None
    for enc in ('utf-8-sig', 'gb18030'):
        try:
            text = raw_bytes.decode(enc)
            encoding = enc
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise BusinessError('BAD_CAP_ENCODING', '上限依据编码无法识别')
    try:
        stream = csv.reader(io.StringIO(text, newline=''), strict=True)
        original = next(stream)
        header = [CAP_ALIASES.get(v.strip(), v.strip()) for v in original]
        if header != CAP_FIELDS:
            raise BusinessError('BAD_CAP_HEADER', '上限依据字段或顺序不匹配')
        windows, quarantine = [], []
        counts = {'input': 0, 'blank': 0, 'repeated_header': 0, 'rejected': 0}
        seen = {}
        for cells in stream:
            line = stream.line_num
            counts['input'] += 1
            if _is_blank(cells):
                counts['blank'] += 1
                continue
            if cells == original:
                counts['repeated_header'] += 1
                continue
            if len(cells) != len(header):
                quarantine.append({'line': line, 'id': cells[0] if cells else '',
                                   'code': 'CAP_COLUMN_COUNT', 'detail': f'需要{len(header)}列，实际{len(cells)}列',
                                   'raw': dict(zip(header, cells))})
                counts['rejected'] += 1
                continue
            row = dict(zip(header, cells))
            reason = _validate(row, context, seen, windows)
            if reason:
                quarantine.append({'line': line, 'id': row.get('id', ''), 'code': reason[0],
                                   'detail': reason[1], 'raw': row})
                counts['rejected'] += 1
                continue
            seen.setdefault(row['device'], []).append((row['_start'], row['_end']))
            windows.append({'id': row['id'].strip(), 'device': row['device'].strip(),
                            'start': row['_start'].isoformat(), 'end': row['_end'].isoformat(),
                            'cap_kw': str(row['_cap']), 'source': row.get('source', '').strip()})
    except csv.Error:
        raise BusinessError('BROKEN_CAP_CSV', '上限依据CSV引号或末行损坏')
    if not windows:
        raise BusinessError('NO_VALID_CAP', '上限依据没有任何有效窗口')
    windows.sort(key=lambda w: (w['device'], w['start'], w['end'], w['id']))
    return {'basis_id': basis_digest(raw_bytes)[:16], 'sha256': basis_digest(raw_bytes),
            'encoding': encoding, 'windows': windows, 'quarantine': quarantine, 'counts': counts}


def _validate(row, context, seen, accepted):
    rid = row.get('id', '').strip()
    if not rid:
        return ('CAP_MISSING_ID', '上限窗口编号不能为空')
    device = row.get('device', '').strip()
    if device not in context.get('devices', {}):
        return ('CAP_UNKNOWN_DEVICE', '上限设备不在设备台账中')
    try:
        start, end = instant(row['start']), instant(row['end'])
    except BusinessError as exc:
        return (exc.code, exc.message)
    if not start < end:
        return ('CAP_INVALID_RANGE', '上限窗口开始须早于结束')
    try:
        cap = number(row['cap_kw'])
    except BusinessError as exc:
        return (exc.code, exc.message)
    if cap <= 0:
        return ('CAP_NON_POSITIVE', '并网点上限须为正数')
    capacity = number(context['devices'][device]['capacity_kw'])
    if cap > capacity:
        return ('CAP_ABOVE_RATING', '并网点上限不能高于设备交流额定容量')
    # 同设备时间窗重叠会让“采用上限”不唯一，必须显式隔离，禁止任意挑一条。
    for prev_start, prev_end in seen.get(device, []):
        if start < prev_end and prev_start < end:
            return ('CAP_OVERLAP', '同设备上限时间窗重叠')
    row['_start'], row['_end'], row['_cap'] = start, end, cap
    return None
