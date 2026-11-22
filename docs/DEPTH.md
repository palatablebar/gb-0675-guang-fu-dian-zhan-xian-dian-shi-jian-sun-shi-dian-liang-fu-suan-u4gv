# 深度登记 光伏电站限电事件与损失电量复算

规模：中型。使用者：新能源场站运营分析员。核心规则：仅用有效对照逆变器和相同辐照区间拟合基线；重叠限电事件先求并集再积分。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 遥测采信 | 执行并复核遥测采信 | `POST /api/intake` | `app/modules/intake/rules.py` | `tests/test_intake.py` |
| M2 设备映射 | 执行并复核设备映射 | `POST /api/devices` | `app/modules/devices/rules.py` | `tests/test_devices.py` |
| M3 事件切片 | 执行并复核事件切片 | `POST /api/slicing` | `app/modules/slicing/rules.py` | `tests/test_slicing.py` |
| M4 基线拟合 | 执行并复核基线拟合 | `POST /api/baseline` | `app/modules/baseline/rules.py` | `tests/test_baseline.py` |
| M5 损失核算 | 执行并复核损失核算 | `POST /api/loss` | `app/modules/loss/rules.py` | `tests/test_loss.py` |
| M6 上限依据 | 上传/隔离/切换并网点上限 | `POST /api/caps`、`POST /api/cap-bases`、`POST /api/runs/{id}/cap-basis` | `app/modules/caps/rules.py`、`app/caps/parser.py` | `tests/test_caps.py`、`tests/test_cap_reapply.py` |
| M7 损失归责 | 区分调度/设备/待查并核验守恒 | `POST /api/attribution` | `app/modules/attribution/rules.py`、`app/caps/attribution.py` | `tests/test_attribution.py`、`tests/test_cap_reapply.py` |
| M8 能量对账 | 执行并复核能量对账 | `POST /api/reconcile` | `app/modules/reconcile/rules.py` | `tests/test_reconcile.py` |
| M9 运行归档 | 执行并复核运行归档 | `POST /api/archive` | `app/modules/archive/rules.py` | `tests/test_archive.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | 旧编码中文状态 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_legacy_source` |
| TRAP-02 | BOM表头 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_bom_source` |
| TRAP-04 | 分段表头 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_segment_header` |
| TRAP-05 | 缺列记录 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_bad_column` |
| TRAP-18 | 空态 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_three_empty_types` |
| TRAP-07 | 遥测哨兵 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/devices/rules.py` | `tests/test_devices.py::test_sentinel_real` |
| TRAP-14 | 设备时刻冲突 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/devices/rules.py` | `tests/test_devices.py::test_conflict_both_isolated` |
| TRAP-15 | 功率单位 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/devices/rules.py` | `tests/test_devices.py::test_megawatt_conversion` |
| TRAP-06 | 全角千分位 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/devices/rules.py` | `tests/test_devices.py::test_fullwidth_number` |
| TRAP-11 | UTC归一 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/devices/rules.py` | `tests/test_devices.py::test_time_equivalence` |
| TRAP-23 | 限电区间并集 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/slicing/rules.py` | `tests/test_slicing.py::test_overlapping_real` |
| TRAP-31 | 设备固有削峰被算作调度限电 | 实际低于基线即全额申报 | 用应发潜力与交流额定容量拆出设备削峰，不并入可申报损失 | `app/caps/attribution.py` | `tests/test_attribution.py::test_device_clipping_isolated_from_dispatch` |
| TRAP-32 | 同一缺额重复归因 | 调度、设备、待查口径重叠加总 | 三段互斥并逐段守恒校验，dispatch+pending=原损失 | `app/caps/attribution.py` | `tests/test_attribution.py::test_three_way_conservation_no_double_count` |
| TRAP-33 | 实际未达上限仍申报 | 把低于采用上限的缺额也算限电 | 列入待查片段，阻止封存 | `app/caps/attribution.py` | `tests/test_attribution.py::test_pending_when_actual_below_binding_cap` |
| TRAP-34 | 上限依据切换全量重算 | 改动一条窗口导致所有时段重算 | 仅重算设备窗口变化的受牵连切片 | `app/engine.py::reapply` | `tests/test_cap_reapply.py::test_reapply_only_recomputes_affected_segments` |
| TRAP-35 | 切换中断污染旧版/删除凭据 | 非事务写入、覆盖原始字节 | 单事务回滚+依据只增不删+同依据幂等 | `app/store.py::reapply_basis` | `tests/test_cap_reapply.py::test_rollback_restores_old_version_on_failure` |
| TRAP-36 | 同设备上限时间窗重叠 | 任意挑一条窗口，采用上限不唯一 | 显式隔离并给稳定原因码 | `app/caps/parser.py` | `tests/test_caps.py::test_overlapping_windows_quarantined` |

## 对账规则

原始逻辑输入=采纳行+隔离行+空行+重复表头+同值重复。业务计算按 DATA-DICTIONARY.md 分别核验，不能把上级与下级重复加总。所有隔离保留编号、原值、原始行号和稳定原因码。

## 已知不覆盖

数据来自仓内样例或用户粘贴文件，不连接外部业务生产系统。平台不执行实际资金划转或行政审批。
