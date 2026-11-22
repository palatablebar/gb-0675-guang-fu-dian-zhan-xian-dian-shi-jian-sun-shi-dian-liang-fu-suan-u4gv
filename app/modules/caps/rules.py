from app.caps.parser import parse_cap_basis
from app.config import ROOT

DEFAULT_CAP_FILE = 'cap_basis.csv'


def load_default_basis(context):
    """读取随仓样例上限依据，作为页面初始与无窗口回退口径。"""
    raw = (ROOT / 'sample_data' / DEFAULT_CAP_FILE).read_bytes()
    return raw, parse_cap_basis(raw, context)


def ensure_default_basis(path, context):
    """惰性登记样例上限依据，保证不依赖lifespan的入口也能切换/下载凭据。

    幂等：已存在同sha256依据时不重复插入、不改动任何凭据。
    """
    from app import store
    raw, basis = load_default_basis(context)
    store.upsert_cap_basis(path, basis, raw, '午间并网点调度上限（样例）')
    return basis


def apply(state):
    """把当前上限依据挂到状态上，供归责模块使用。

    引擎/重算入口负责把已解析依据放入 state['cap_basis']；
    独立演示（POST /api/caps）或缺少显式依据时，回落到仓内样例。
    原始字节不进入可序列化state，凭据由cap_bases表单独留档。
    """
    context = state['context']
    if state.get('cap_basis') is None:
        _, basis = load_default_basis(context)
        state['cap_basis'] = basis
    basis = state['cap_basis']
    state['views']['caps'] = {
        'title': '并网点上限依据',
        'rows': basis['windows'],
        'quarantine': basis.get('quarantine', []),
        'metrics': {
            '依据编号': basis['basis_id'],
            '有效窗口': len(basis['windows']),
            '隔离窗口': len(basis.get('quarantine', [])),
        },
    }
