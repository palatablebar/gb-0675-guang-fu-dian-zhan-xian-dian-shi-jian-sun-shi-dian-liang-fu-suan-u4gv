# 光伏电站限电事件与损失电量复算

给新能源场站运营分析员使用。仅用有效对照逆变器和相同辐照区间拟合基线；重叠限电事件先求并集再积分。每个缺额段再按**并网点调度上限**与**逆变器交流额定容量**拆成可申报损失、设备削峰与待查片段，同一缺额只归因一次。

九个业务模块：遥测采信、设备映射、事件切片、基线拟合、损失核算、上限依据、损失归责、能量对账、运行归档。

```sh
docker compose up --build -d
docker compose exec -T app pytest -q
```

访问 http://localhost:18244 。启动直接载入现场脏批。切换干净样例和旧编码样例可对照核验。完整对照批INV-A重叠事件取并集后30分钟，基线100kW、实际60kW，损失20kWh；无合格对照或遥测冲突必须保持未定，不能填0。

各模块页面对应 `/<模块英文名>`，各模块执行入口为 `POST /api/<模块英文名>`，不传参即可独立演示。完整运行 `POST /api/runs` 支持 `dataset`（dirty/clean/legacy）、`csv_text` 与 `overrides` 参数。批次历史 `GET /api/runs`，详情 `GET /api/runs/{run_id}`。

同输入与规则版本生成相同批号，只保留一条批次。复核入口 `POST /api/runs/{run_id}/review` 提交当前 `revision`，陈旧提交409。归档包只有一个下载入口 `GET /api/export/{run_id}`，含证据和运行摘要。原始隔离在页面同屏显示。

SQLite使用命名卷，容器重启后保留历史。要重建演示可在Compose中改用新的卷名称，保留旧卷。

源码在 `app/`，样例在 `sample_data/`，测试在 `tests/`；定义见 `docs/DATA-DICTIONARY.md`，模块和边界测试对应关系见 `docs/DEPTH.md`。输入上限2MB，属于离线复核工具。

采信页支持上传或粘贴CSV。完整源字节与参数随批次持久化，跨页通过run_id读取同一结果。`POST /api/runs/{run_id}/rerun` 读取该批不可变输入快照重新计算，规则未变时批号不变。切换另一示例则创建或复用另一批次。

## 可归责限电损失与上限依据

午间并网点给出功率上限，逆变器同时受交流额定容量约束。归责页（`/attribution`）逐段展示三类互斥电量，顶部与页面同时显示**可申报损失、设备削峰、待查片段**：

- 可申报损失：调度并网点上限把可达基线压低的部分，可按差额申报；
- 设备削峰：应发潜力超出逆变器交流额定容量的固有部分，不向调度申报；
- 待查片段：实际功率低于采用上限（或依据与遥测矛盾），无法证明由限电导致，阻止封存。

上限依据在 `/caps` 页以 CSV（`id,device,start,end,cap_kw,source`）管理，问题窗口隔离不静默丢弃。接口：上传 `POST /api/cap-bases`、列表 `GET /api/cap-bases`、原始凭据 `GET /api/cap-bases/{basis_id}/raw`、切换 `POST /api/runs/{run_id}/cap-basis`、审计 `GET /api/runs/{run_id}/cap-audit`。

切换依据只重算设备窗口发生变化的受牵连切片，其余时段保持不变；切换在单数据库事务内完成，中途中断整体回滚到旧版。已上传依据的原始字节只增不删，归档包 `GET /api/export/{run_id}` 另存 `cap_basis_original.csv` 与逐段归责明细。同一依据重复提交幂等：不新增审计、不产生新版本、不误删任何原始凭据。
