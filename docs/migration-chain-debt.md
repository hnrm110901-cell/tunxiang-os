# Migration Chain Debt 跟踪

> 由 PI.1（2026-05-04）建立。`migration-ci.yml` 修了 regex bug 后暴露 3 个 main 既存断链。
> 暂以 `KNOWN_BROKEN` 白名单允许 CI 通过，必须在 v400 之前清零。

## 背景

旧 `migration-ci.yml` 的断链检测正则 `^revision = ` 漏掉了 alembic 1.13+ 的 `revision: str = ` 类型注解写法（68/493 个文件），导致**所有**指向新版 revision 的 `down_revision` 都被误报，掩盖了真实断链。

PI.1 修了正则后真实暴露的 3 个断链如下：

## 断链清单

### 1. `v310_mv_performance_indexes`（被 v311 引用）

- 文件：`shared/db-migrations/versions/v310_mv_performance_indexes.py`
- 实际 `revision = "v310"`（短形式）
- 引用方：`v311_rls_retrofit_26_tables.py` 的 `down_revision = "v310_mv_performance_indexes"`
- 同 v310 命名空间还有 `v310_challenges.py`（`revision = "v310_challenges"`）— **revision 撞短前缀**
- 修复方向：把 `v310_mv_performance_indexes.py` 的 `revision` 改为 `"v310_mv_performance_indexes"`
- 风险：若已 apply 过 v310（写入 alembic_version），DB 端需手工 `UPDATE alembic_version SET version_num='v310_mv_performance_indexes' WHERE version_num='v310';`

### 2. `v387_pdpa_compliance`（被 v388 引用）

- 文件：`shared/db-migrations/versions/v387_pdpa_compliance.py`
- 实际 `revision: str = "v387"`
- 引用方：`v388_id_market.py` 的 `down_revision = "v387_pdpa_compliance"`
- 修复方向：同 (1)，把文件 revision 改为 `"v387_pdpa_compliance"`
- 风险：同 (1)

### 3. `v301_refund_requests`（被 v310_mv_performance_indexes 引用，文件不存在）

- 引用方：`v310_mv_performance_indexes.py` 的 `down_revision = "v301_refund_requests"`
- v301 命名空间存在的文件：
  - `v301_group_ops_material.py`（`revision = "v301_group_ops_material"`）
  - `v301_table_analytics_views.py`（`revision = "v151b"` — **本身就异常**）
- 修复方向需考古：v310_mv_performance_indexes 的真实上游是哪个 v300 系列？需 founder/原作者确认。

## 处置方案

1. **本次（PI.1）：** 加 `KNOWN_BROKEN` 白名单，CI 报 warning 不 block；让 PR #144 等 SECURITY 修复可合入。
2. **下个 sprint：** 单独 PR 逐项修复，按 (1) → (2) → (3) 顺序：
   - (1)/(2) 改 revision 字符串 + 准备 alembic_version 数据修复脚本
   - (3) 与原作者对接确定上游 → 改 down_revision
3. **目标：** v400 migration 落库前清零白名单。

---

## PG.1.1 / PI.2：alembic multiple heads（2026-05-04 新增登记）

### 当前状态

仓库 `shared/db-migrations/versions/` 当前同时存在 **75 个 alembic head**（leaf revision，未被任何其他 down_revision 引用）。

### 即时修补（PG.1.1，v397）

v395（RLS WITH CHECK 安全修补）与 v392/v393（业务推进）从 v391 分叉后，未合并；本次 PR 用 `v397_merge_v393_v396_heads.py` 合并这两个**当前活跃链**头部，使 `v397` 成为 v391 之后的唯一活跃 head。

### 残留债务（PI.2，待立项）

剩余 73 个历史 head 集中在 v047 / v150b / v206-v297 等旧时代分支，绝大多数是迭代/灰度残留：

- v047 分叉到 {v048, v049, v050, v054}（4 head）
- v206 / v207 / v208 / v235 等带后缀字母的并行分支
- v264-v297 的 b/c/d 后缀变体

这些 head 在生产 DB 的 `alembic_version` 表中实际只有一条主干指针在用，其他全是"代码里残留、DB 不感知"的孤立 leaf。如果将来某个 PR 不慎把 down_revision 指到这些孤儿，就会引入新分叉。

### 为什么本次不修

- 工程量大（73 个 head × 平均 2 文件需改 = 150+ 文件）
- 多数旧 head 的语义需考古（找原作者 / 看 PR 历史）
- 误改可能导致 alembic_version 数据修复脚本爆雷

### 下一步

- 立 PI.2 sprint：分批把 73 head 用 merge migration 合并；每批不超过 5 head，灰度验证
- 立 CI 增强：检测**新增**孤立 head（比对 PR 前后 head 集合差），允许保留历史白名单
- 目标 v420 落库前 head ≤ 5（业务/安全/灰度三个稳定子链可接受）
