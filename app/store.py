import sqlite3
import json
from pathlib import Path
from app.errors import BusinessError

SCHEMA_CAP = """
CREATE TABLE IF NOT EXISTS cap_bases (
  basis_id TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL,
  label TEXT NOT NULL,
  raw_b64 TEXT NOT NULL,
  parsed TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_caps (
  run_id TEXT PRIMARY KEY,
  basis_id TEXT,
  basis_label TEXT,
  FOREIGN KEY(run_id) REFERENCES runs(id)
);
CREATE TABLE IF NOT EXISTS cap_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  from_basis TEXT,
  to_basis TEXT,
  basis_label TEXT,
  affected_segments INTEGER NOT NULL,
  action TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _b64(raw):
    import base64
    return base64.b64encode(raw).decode()


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, result TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT '待复核')")
    con.executescript(SCHEMA_CAP)
    _ensure_column(con, 'runs', 'applied_basis', 'TEXT')
    return con


def _ensure_column(con, table, column, decl):
    cols = {r['name'] for r in con.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def save(path, result):
    run_id = result['manifest']['run_id']
    with connect(path) as con:
        con.execute('INSERT OR IGNORE INTO runs(id,digest,result) VALUES(?,?,?)',
                    (run_id, result['manifest']['sha256'], json.dumps(result, ensure_ascii=False)))
    return get(path, run_id)


def get(path, run_id):
    with connect(path) as con:
        row = con.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
    if not row:
        raise BusinessError('NOT_FOUND', '批次不存在', 404)
    result = json.loads(row['result'])
    result.update(revision=row['revision'], status=row['status'])
    result['applied_basis'] = row['applied_basis']
    return result


def history(path):
    with connect(path) as con:
        return [dict(r) for r in con.execute('SELECT id,revision,status FROM runs ORDER BY rowid DESC LIMIT 100')]


def review(path, run_id, revision):
    with connect(path) as con:
        cur = con.execute('UPDATE runs SET revision=revision+1,status=? WHERE id=? AND revision=?',
                          ('已复核', run_id, revision))
        if cur.rowcount != 1:
            if not con.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone():
                raise BusinessError('NOT_FOUND', '批次不存在', 404)
            raise BusinessError('STALE_VERSION', '复核版本已更新，请刷新', 409)
    return get(path, run_id)


# ---- 上限依据持久化（原始字节永不覆盖、永不删除）----

def upsert_cap_basis(path, basis, raw_bytes, label):
    with connect(path) as con:
        con.execute(
            'INSERT OR IGNORE INTO cap_bases(basis_id,sha256,label,raw_b64,parsed,created_at) VALUES(?,?,?,?,?,?)',
            (basis['basis_id'], basis['sha256'], label, _b64(raw_bytes),
             json.dumps(basis, ensure_ascii=False), _now()))
        row = con.execute('SELECT basis_id,label,parsed,created_at FROM cap_bases WHERE basis_id=?',
                          (basis['basis_id'],)).fetchone()
    return dict(row)


def list_cap_bases(path):
    with connect(path) as con:
        rows = con.execute('SELECT basis_id,sha256,label,created_at FROM cap_bases ORDER BY rowid DESC').fetchall()
    out = []
    for r in rows:
        d = dict(r)
        parsed = get_cap_basis(path, d['basis_id'])
        d['windows'] = parsed['windows']
        d['counts'] = parsed['counts']
        d['quarantine'] = parsed['quarantine']
        out.append(d)
    return out


def get_cap_basis(path, basis_id):
    with connect(path) as con:
        row = con.execute('SELECT * FROM cap_bases WHERE basis_id=?', (basis_id,)).fetchone()
    if not row:
        raise BusinessError('BASIS_NOT_FOUND', '上限依据不存在', 404)
    return json.loads(row['parsed'])


def get_cap_raw(path, basis_id):
    import base64
    with connect(path) as con:
        row = con.execute('SELECT raw_b64,label FROM cap_bases WHERE basis_id=?', (basis_id,)).fetchone()
    if not row:
        raise BusinessError('BASIS_NOT_FOUND', '上限依据不存在', 404)
    return base64.b64decode(row['raw_b64']), row['label']


def applied_basis_of(path, run_id):
    with connect(path) as con:
        row = con.execute('SELECT applied_basis FROM runs WHERE id=?', (run_id,)).fetchone()
    if not row:
        raise BusinessError('NOT_FOUND', '批次不存在', 404)
    return row['applied_basis']


def cap_audit(path, run_id):
    with connect(path) as con:
        rows = con.execute('SELECT * FROM cap_audit WHERE run_id=? ORDER BY id DESC', (run_id,)).fetchall()
    return [dict(r) for r in rows]


def reapply_basis(path, run_id, new_basis_id, rebuild_result, now_provider=_now):
    """在单个事务内切换上限依据并重算。任何异常整体回滚，旧版结果与原凭据保留。

    rebuild_result(old_result, parsed_basis) -> (new_result_json, affected_count)
    同依据重试不产生新版本、不写审计、不改动任何原始凭据（幂等）。
    """
    con = connect(path)
    try:
        con.execute('BEGIN IMMEDIATE')
        run = con.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if not run:
            raise BusinessError('NOT_FOUND', '批次不存在', 404)
        cap = con.execute('SELECT * FROM cap_bases WHERE basis_id=?', (new_basis_id,)).fetchone()
        if not cap:
            raise BusinessError('BASIS_NOT_FOUND', '上限依据不存在', 404)
        old_basis_id = run['applied_basis']
        if old_basis_id == new_basis_id:
            con.commit()  # 同依据重试：无新增、无删除
            return {'changed': False, 'run_id': run_id, 'basis_id': new_basis_id,
                    'affected_segments': 0, 'revision': run['revision']}
        old_result = json.loads(run['result'])
        parsed_basis = json.loads(cap['parsed'])
        new_result, affected = rebuild_result(old_result, parsed_basis)
        con.execute('UPDATE runs SET result=?, applied_basis=? WHERE id=?',
                    (json.dumps(new_result, ensure_ascii=False), new_basis_id, run_id))
        con.execute('INSERT INTO cap_audit(run_id,from_basis,to_basis,basis_label,affected_segments,action,created_at)'
                    ' VALUES(?,?,?,?,?,?,?)',
                    (run_id, old_basis_id, new_basis_id, cap['label'], affected,
                     'SWITCH' if old_basis_id else 'APPLY', now_provider()))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return {'changed': True, 'run_id': run_id, 'basis_id': new_basis_id,
            'affected_segments': affected, 'revision': get(path, run_id)['revision']}
