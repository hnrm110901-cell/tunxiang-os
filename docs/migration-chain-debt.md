# Migration Chain Debt 跟踪

> **✅ 2026-05-09 (B') — 全部 3 处历史断链修复完毕。** `KNOWN_BROKEN_PARENTS` /
> `KNOWN_BROKEN_CHILDREN` 排空。`scripts/check_alembic_chain.py` scope-guard
> 机制保留为防御性兜底，但白名单内已无条目。
>
> 由 PI.1（2026-05-04）建立。`migration-ci.yml` 修了 regex bug 后暴露 3 个 main 既存断链。
> 暂以 `KNOWN_BROKEN` 白名单允许 CI 通过，必须在 v400 之前清零。
>
> **PJ.5（2026-05-04 同日）更新**：CodeRabbit 指出 PI.1 白名单作用域过宽 ——
> 新 PR 只要把 `down_revision` 写成白名单内的 rev 就 silent pass。修复：
> 把检查抽到 `scripts/check_alembic_chain.py`，拆成两组：
>
>  - `KNOWN_BROKEN_PARENTS`：被引用但无文件声明的孤儿父 rev 名（下方 3 项）。
>  - `KNOWN_BROKEN_CHILDREN`：现存的、已经引用孤儿父的 child rev ID
>    （`v310` / `v311` / `v388`）—— 仅这三个 rev 可以 pass。
>
> Scope guard：若新 migration 的 `down_revision ∈ KNOWN_BROKEN_PARENTS` 且自身
> ∉ `KNOWN_BROKEN_CHILDREN`，CI fail。下游链 chain off 真 declared rev（如
> v311 / v389_vn_market）时按正常 chain 处理，不级联豁免。

## 背景

旧 `migration-ci.yml` 的断链检测正则 `^revision = ` 漏掉了 alembic 1.13+ 的 `revision: str = ` 类型注解写法（68/493 个文件），导致**所有**指向新版 revision 的 `down_revision` 都被误报，掩盖了真实断链。

PI.1 修了正则后真实暴露的 3 个断链如下：

## 断链清单

### 1. `v310_mv_performance_indexes`（被 v311 引用）— ✅ 已修复 (B', 2026-05-09)

- 文件：`shared/db-migrations/versions/v310_mv_performance_indexes.py`
- 实际 `revision = "v310"`（短形式）
- 引用方：`v311_rls_retrofit_26_tables.py` 的 `down_revision = "v310_mv_performance_indexes"`
- 同 v310 命名空间还有 `v310_challenges.py`（`revision = "v310_challenges"`）— **revision 撞短前缀**
- ~~修复方向：把 `v310_mv_performance_indexes.py` 的 `revision` 改为 `"v310_mv_performance_indexes"`~~
- **B' 实际修复**：把 `v311_rls_retrofit_26_tables.py` 的 `down_revision` 从 filename stem
  `"v310_mv_performance_indexes"` 改为真 revision ID `"v310"`（1 字符订正，不动 v310 自身 revision，
  避开 v310/v310_challenges 撞前缀风险，也无需 alembic_version 数据修复）。
- 风险：~~若已 apply 过 v310（写入 alembic_version），DB 端需手工~~（已规避）

### 2. `v387_pdpa_compliance`（被 v388 引用）— ✅ 已修复 (B', 2026-05-09)

- 文件：`shared/db-migrations/versions/v387_pdpa_compliance.py`
- 实际 `revision: str = "v387"`
- 引用方：`v388_id_market.py` 的 `down_revision = "v387_pdpa_compliance"`
- ~~修复方向：同 (1)，把文件 revision 改为 `"v387_pdpa_compliance"`~~
- **B' 实际修复**：v388_id_market.py 与 v388_fill_rls_26_tables.py **重复声明 `revision="v388"`**（alembic 拒绝加载）。
  把 v388_id_market.py revision 重命名为唯一 ID `"v388_id_market"`，down_revision 由 filename stem
  `"v387_pdpa_compliance"` 订正为真 revision ID `"v387"`。同步把 v388_fill_rls_26_tables.py 的
  down_revision 从 `"v387"` 改为 `"v388_id_market"`。链路：
  `v387 → v388_id_market → v388 (fill_rls) → v389_vn_market`。
- 风险：~~同 (1)~~（已规避，v389_vn_market 的 down_revision = "v388" 仍然有效，指向 fill_rls）

### 3. `v301_refund_requests`（被 v310_mv_performance_indexes 引用，文件不存在）— ✅ 已修复 (B', 2026-05-09)

- 引用方：`v310_mv_performance_indexes.py` 的 `down_revision = "v301_refund_requests"`
- v301 命名空间存在的文件：
  - `v301_group_ops_material.py`（`revision = "v301_group_ops_material"`）
  - `v301_table_analytics_views.py`（`revision = "v151b"` — **本身就异常**）
- ~~修复方向需考古：v310_mv_performance_indexes 的真实上游是哪个 v300 系列？需 founder/原作者确认。~~
- **B' 实际修复**：考古 PR #128 (fd94028e) 引入 v310 时，仓库无任何文件声明 `revision="v301_refund_requests"`
  （PR 作者拍脑袋取名，对应文件未提交）。当时 active heads 含 v304 / v330_reputation_alerts /
  v383_chain_consolidation 等。选 `v304` 作为真前置：(a) 是真 revision ID（不是 filename stem），
  (b) 与 mv 索引语义无依赖冲突，(c) 不跨太大 v3xx 段。v398 merge migration 后续把 v310 + 其他
  b-suffix head 一同合到主链，不影响。

## 处置方案

1. ~~**本次（PI.1）：** 加 `KNOWN_BROKEN` 白名单，CI 报 warning 不 block；让 PR #144 等 SECURITY 修复可合入。~~ ✅ 历史
2. ~~**下个 sprint：** 单独 PR 逐项修复~~ ✅ 已在 B' (2026-05-09) 一次性完成
3. ~~**目标：** v400 migration 落库前清零白名单。~~ ✅ v406 已落库，B' 同 PR 内清零

### B' 后状态（2026-05-09）

- `KNOWN_BROKEN_PARENTS = frozenset()` — 排空
- `KNOWN_BROKEN_CHILDREN = frozenset()` — 排空
- `scripts/check_alembic_chain.py` scope-guard 机制保留作为防御性兜底
- `shared/db-migrations/tests/test_chain_integrity_tier1.py` 新增 4 项静态扫描测试覆盖
  无 dup revision、无 dangling、单 head、单 root
- 解锁能力：CI 真 PG 反测 fixture（B'→A 串行的 A 任务）、生产新机房 `alembic upgrade head`、
  本地 dev DB 完整初始化

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
