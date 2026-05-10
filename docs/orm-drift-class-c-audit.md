# ORM↔Migration Drift — Class C Audit

> 2026-05-10。承接 PR #357 起点 18 张 drift / PR #361 / #362 / #363 chain rescue revive 后剩余 7 张全部 Class C（ORM-only 无 migration 痕迹）。本 doc 记录 7 张 audit 结果与处置决策。

## 调研方法

每张表执行三步并行 grep：
1. **ORM 类外部引用** — `grep -rn "class XxxX\|XxxX(" services/`
2. **表名 raw SQL** — `grep -rn "FROM <table>\|INSERT INTO <table>\|UPDATE <table>" services/`
3. **API 路由** — `grep -rn "<table_name>" services/*/api/*.py`

任一维度 ≥ 1 命中 → LIVE，必须 revive；三维度全 0 → DEAD，删 ORM 类。

## 7 张 audit 矩阵

| # | 表 | ORM 文件 | 外部引用 | raw SQL CRUD | API endpoint | 判定 | 处置 |
|---|---|---|---|---|---|---|---|
| 1 | `banquet_menu_templates_v2` | `tx-trade/src/models/banquet_quote.py:15` | **0**（同名 LIVE 类在 banquet.py:170 用 `banquet_menu_templates` 无 _v2，已被 v332 建表） | 0 | 0 | 💀 **DEAD** | 删 banquet_quote.py BanquetMenuTemplate 类 |
| 2 | `brand_groups` | `tx-member/src/models/group_config.py:18` | group_member_service / group_routes / group_member_routes / group_analytics 多处 import | 4+ raw SQL（`SELECT FROM brand_groups WHERE id=:group_id`） | group_routes / group_member_routes API | 🟢 **LIVE** | v410 revive |
| 3 | `cook_time_baselines` | `tx-trade/src/models/cook_time_baseline.py:21` | cook_time_stats.py | `从 cook_time_baselines 表查询单条基准数据` raw SQL | — | 🟢 **LIVE** | v410 revive |
| 4 | `daily_plans` | `tx-agent/src/models/daily_plan.py:10` | **0**（同名 dict key `daily_plans` 在 revenue_schedule_service.py 是 Python 字典字段名，不是数据库表；同名 `DailyPlannerAgent` 是不同类） | 0 | 0 | 💀 **DEAD** | 删整文件 daily_plan.py |
| 5 | `delivery_auto_accept_rules` | `tx-trade/src/models/delivery_auto_accept_rule.py:17` | DeliveryAutoAcceptRuleRepository (delivery_order_repo.py:494) | ORM CRUD（`select(DeliveryAutoAcceptRule)`、`db.add(rule)`） | takeaway_routes / delivery_panel_router | 🟢 **LIVE** | v410 revive |
| 6 | `kds_tasks` | `tx-trade/src/models/kds_task.py:35` | KDSTask 多处 import | **9+ raw SQL CRUD 跨 5 文件**：kitchen_monitor_routes (4×FROM) / kds_banquet_routes (2×INSERT) / kds_by_session_routes (1×UPDATE) / cook_time_stats (2×FROM) / store_health_routes (1×FROM) | KDS 主流程 + cook_time hot path | 🟢 **LIVE** ⚠️ | v410 revive — Tier 影响（已有"kds_tasks 表不存在时优雅降级"补丁证明 runtime 已 broken） |
| 7 | `stored_value_account_transactions` | `tx-member/src/models/stored_value_account.py:130` | **0**（连 tx-member/__init__.py 都不 collect stored_value_account 模块） | 0 | 0 | 💀 **DEAD** | 删 StoredValueAccountTransaction 类（ORM file 头部 CREATE TABLE 注释作 TODO，从未实施 — 真实 stored_value 流水由 stored_value.py 负责） |

## 关键发现

### banquet_menu_templates_v2 — fork 残留
两个同名 ORM 类 `BanquetMenuTemplate`：
- `services/tx-trade/src/models/banquet.py:170`：`__tablename__ = "banquet_menu_templates"` — **LIVE**，被 services/__init__.py 导出 + banquet_template_service.py heavy use + v332_banquet_quotes 已建表
- `services/tx-trade/src/models/banquet_quote.py:15`：`__tablename__ = "banquet_menu_templates_v2"` — **DEAD**，0 import / 0 raw SQL，同 file 中 BanquetQuote / BanquetQuoteItem 是 LIVE（已被 v332 建表）

PR #357 drift 检测捕获的是 v2 版本 — fork/重写 残留，需移除。

### kds_tasks — 已知 broken 但被 graceful degradation 掩盖
`services/tx-trade/tests/test_shift_report.py` 含专门测试：
```python
async def test_graceful_degradation_when_kds_tasks_missing():
    """kds_tasks 表不存在时 get_shift_summary 返回空报表，不抛异常"""
```
这证明该 ORM↔migration drift 已在 production 触发过且**被掩盖处理**——9+ raw SQL CRUD 全部潜在断点。v410 revive 后该 graceful degradation 可移除（独立 PR，不在 v410 scope）。

### daily_plans — 误判风险已排除
revenue_schedule_service.py 中 `daily_plans: List[Dict[str, Any]]` 是 Python 字典 key，与 ORM 类 `DailyPlan` 同字面量但语义无关。`DailyPlannerAgent` 是 Agent OS 类，与 DailyPlan ORM 无任何关联。tx-agent 的 __init__.py 不 export DailyPlan。**纯死代码**。

### stored_value_account_transactions — TODO 性质留痕
ORM file 头部注释（lines 35-52）记录该表的 schema SQL，**但从未做成 alembic migration**。开发者把 schema 写在 docstring 里就放着了，class 实例化 0 处。pure documented-but-never-implemented 模式。

## 处置计划

### PR-α 本 PR（drift 7 → 4）
- 删 3 个 dead ORM 类
- ratchet drift baseline 7 → 4
- 写本 audit doc 留痕

### PR-β 后续（drift 4 → 0 终态）
4 张 LIVE 表统一 revive：`v410_class_c_live_revive`
- brand_groups (tx-member 域)
- cook_time_baselines / delivery_auto_accept_rules / kds_tasks (tx-trade 域)
- 沿用 v407/v408/v409 helper 模板（_apply_rls + Class F2 修）
- 列对齐验证：每张表 ORM 列 ↔ 现行 raw SQL INSERT/UPDATE 子集 ↔ 新 SQL DDL 三方一致

### 后续清理（可选独立 PR）
- 移除 `test_graceful_degradation_when_kds_tasks_missing` 等掩盖性测试（v410 落地后表必存在）
- 移除相关 ORM file 头部 TODO 性质 schema 注释（已部分清理）

## 引用

- PR #357 drift 检测器引入（baseline 18）
- PR #361 / #362 / #363 chain rescue revive 模板系列
- shared/db-migrations/tests/test_orm_migration_drift_tier1.py 当前 baseline 检测点
- CLAUDE.md §17 Tier 1 路径（kds_tasks 影响 cook_time hot path）
