from contextlib import asynccontextmanager
from importlib import import_module
from fastapi import FastAPI, Request, Body
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from app.config import ROOT, META, MODULES, DB_PATH, MAX_BYTES
from app.errors import BusinessError
from app.engine import evaluate, reapply
from app import store
from app.archive import serialize
from app.caps.parser import parse_cap_basis
from app.modules.caps.rules import load_default_basis, ensure_default_basis


@asynccontextmanager
async def lifespan(app):
    state = evaluate()
    store.save(DB_PATH, state)
    # 预置样例上限依据：原始字节随表保存，作为可下载凭据与初始依据。
    raw, basis = load_default_basis(state['context'])
    store.upsert_cap_basis(DB_PATH, basis, raw, '午间并网点调度上限（样例）')
    store.reapply_basis(DB_PATH, state['manifest']['run_id'], basis['basis_id'],
                        lambda old, parsed: reapply(old, parsed))
    yield


app = FastAPI(title=META['title'], lifespan=lifespan)
app.mount('/static', StaticFiles(directory=str(ROOT / 'app/static')), name='static')


@app.exception_handler(BusinessError)
async def business_error(request: Request, error: BusinessError):
    return JSONResponse({'code': error.code, 'detail': error.message}, status_code=error.status)


@app.get('/')
def home():
    return RedirectResponse('/' + MODULES[0], status_code=303)


@app.get('/healthz')
def health():
    return {'status': 'ok', 'project': META['short']}


@app.post('/api/runs')
def create(payload: dict = Body(default={})):
    return store.save(DB_PATH, evaluate(payload))


@app.post('/api/runs/{run_id}/rerun')
def rerun(run_id: str):
    previous = store.get(DB_PATH, run_id)
    if 'input_snapshot' not in previous:
        raise BusinessError('INPUT_SNAPSHOT_MISSING', '旧批缺少源快照，请重新导入')
    # 重跑沿用该批当前已应用的上限依据；无则回落到样例依据。
    cap_basis = previous.get('cap_basis')
    result = evaluate({'dataset': previous['source']},
                      snapshot=previous['input_snapshot'], cap_basis=cap_basis)
    saved = store.save(DB_PATH, result)
    new_id = saved['manifest']['run_id']
    if cap_basis is not None:
        basis_id = cap_basis['basis_id']
        already = store.applied_basis_of(DB_PATH, new_id)
        # 仅当依据已在库登记且与当前应用值不同才切换；样例依据由evaluate自动应用。
        if already != basis_id:
            try:
                store.get_cap_basis(DB_PATH, basis_id)
            except BusinessError:
                pass
            else:
                # 幂等：同依据不写审计、不改动凭据。
                store.reapply_basis(DB_PATH, new_id, basis_id,
                                    lambda old, parsed: reapply(old, parsed))
    return store.get(DB_PATH, new_id)


@app.get('/api/runs')
def runs():
    return store.history(DB_PATH)


@app.get('/api/runs/{run_id}')
def run(run_id: str):
    return store.get(DB_PATH, run_id)


@app.post('/api/runs/{run_id}/review')
def review(run_id: str, payload: dict = Body(...)):
    revision = payload.get('revision')
    if not isinstance(revision, int) or revision < 1:
        raise BusinessError('BAD_REVISION', '版本号须为正整数')
    return store.review(DB_PATH, run_id, revision)


# ---- 上限依据：上传凭据、切换重算、原始凭据下载、审计 ----

@app.post('/api/cap-bases')
def upload_cap_basis(payload: dict = Body(...)):
    csv_text = payload.get('csv_text')
    label = str(payload.get('label') or '页面导入上限依据')
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise BusinessError('EMPTY_CAP_FILE', '请提供非空上限依据CSV')
    raw = csv_text.encode()
    if len(raw) > MAX_BYTES:
        raise BusinessError('TOO_LARGE', '文件超过2MB', 413)
    # 用一个已存在批次的上下文（设备台账）校验设备有效性。
    probe = evaluate()
    basis = parse_cap_basis(raw, probe['context'])
    record = store.upsert_cap_basis(DB_PATH, basis, raw, label)
    return {'basis_id': basis['basis_id'], 'sha256': basis['sha256'],
            'windows': basis['windows'], 'quarantine': basis['quarantine'],
            'counts': basis['counts'], 'label': record['label'],
            'created_at': record['created_at']}


@app.get('/api/cap-bases')
def cap_bases():
    probe = evaluate()
    ensure_default_basis(DB_PATH, probe['context'])
    return {'bases': store.list_cap_bases(DB_PATH)}


@app.get('/api/cap-bases/{basis_id}/raw')
def cap_basis_raw(basis_id: str):
    raw, label = store.get_cap_raw(DB_PATH, basis_id)
    return Response(raw, media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{basis_id}.csv"'})


@app.post('/api/runs/{run_id}/cap-basis')
def apply_cap_basis(run_id: str, payload: dict = Body(...)):
    basis_id = payload.get('basis_id')
    if not isinstance(basis_id, str) or not basis_id:
        raise BusinessError('BAD_BASIS', '缺少上限依据编号')
    target = store.get(DB_PATH, run_id)
    # 惰性确保样例默认依据已登记（兼容未触发lifespan的入口）。
    if target.get('cap_basis') and basis_id == target['cap_basis']['basis_id']:
        ensure_default_basis(DB_PATH, target['context'])

    def rebuild(old, parsed):
        return reapply(old, parsed)

    outcome = store.reapply_basis(DB_PATH, run_id, basis_id, rebuild)
    return {**outcome, 'result': store.get(DB_PATH, run_id)}


@app.get('/api/runs/{run_id}/cap-audit')
def cap_audit(run_id: str):
    store.get(DB_PATH, run_id)
    return {'audit': store.cap_audit(DB_PATH, run_id),
            'applied_basis': store.applied_basis_of(DB_PATH, run_id)}


@app.get('/api/export/{run_id}')
def export(run_id: str):
    result = store.get(DB_PATH, run_id)
    cap_raw = None
    cap = result.get('cap_basis')
    if cap:
        try:
            cap_raw, _ = store.get_cap_raw(DB_PATH, cap['basis_id'])
        except BusinessError:
            # 兼容未触发lifespan的入口：惰性补登样例依据后再取原始字节。
            ensure_default_basis(DB_PATH, result['context'])
            try:
                cap_raw, _ = store.get_cap_raw(DB_PATH, cap['basis_id'])
            except BusinessError:
                cap_raw = None
    return Response(serialize(result, cap_raw), media_type='application/zip',
                    headers={'Content-Disposition': f'attachment; filename="{run_id}.zip"'})


for key in MODULES:
    app.include_router(import_module(f'app.modules.{key}.handler').router)
