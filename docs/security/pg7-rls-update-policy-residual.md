# PG.7 RLS UPDATE/ALL Policy WITH CHECK — 历史违规清单

> **状态**: Lint 工具落地 (`scripts/check_rls_with_check.py`)；CI 接入待 founder 决策（直接修 vs baseline 模式）
> **生成日期**: 2026-05-05
> **触发命令**: `python3 scripts/check_rls_with_check.py`

## 背景

`CREATE POLICY ... FOR UPDATE USING (...)` 仅有 `USING` 子句而无 `WITH CHECK` 时存在跨租户逃逸面：
应用层若能写入 `tenant_id` 列（业务漏洞 / 注入），UPDATE 通过 USING 校验后行
就被改属另一租户，原租户视野永远丢失该行。详见 `v399_points_update_policy_with_check.py`
头部注释。

v399 修补 3 表（积分系统），v400 修补 13 表（patrol / payment / subsidy / users / 等）。

## 余下 15 处历史违规（v399/v400 范围之外）

| 文件 | 表 | 行号 |
|------|-----|------|
| v020_dispatch_rules.py | dispatch_rules | 101 |
| v052_allergen_management.py | dish_allergens | 106 |
| v053_supply_chain_mobile.py | receiving_orders | 79 |
| v053_supply_chain_mobile.py | stocktake_sessions | 164 |
| v055_patrol_logs.py | patrol_logs | 69 |
| v067_three_way_match.py | helper（动态 `{table}`，需检查调用面） | 43 |
| v068_ontology_snapshots.py | ontology_snapshots | 72 |
| v069_open_api_platform.py | api_applications | 64 |
| v069_open_api_platform.py | api_access_tokens | 111 |
| v069_open_api_platform.py | api_request_logs | 161 |
| v069_open_api_platform.py | api_webhooks | 211 |
| v151_crew_schedule_tables.py | crew_schedules | 65 |
| v151_crew_schedule_tables.py | crew_checkin_records | 114 |
| v151_crew_schedule_tables.py | crew_shift_swaps | 165 |
| v151_crew_schedule_tables.py | crew_shift_summaries | 219 |

## 修补路径选项

按 CLAUDE.md §18 "已应用迁移禁止修改"，需新增 v401（或更高版本）DROP+CREATE
重建 UPDATE policy。

- **路径 A — 全量补一刀**: 一个 v401 migration 一次性 DROP+CREATE 这 15 个 policy。优点：一次到位；缺点：单 migration 规模大，回滚粒度粗。
- **路径 B — 按服务分批**: v401 dispatch+supply、v402 patrol+ontology、v403 api+crew。优点：原子化、回滚精细；缺点：3 个 PR。
- **路径 C — 接入 CI baseline 模式**: 把这 15 处加白名单，新违规 fail。这只防退化，不修历史。

## CI 接入说明

`scripts/check_rls_with_check.py` 当前**未**接入 `.github/workflows/migration-ci.yml`，
原因：直接接入会让 main 立即 fail。需 founder 选定上述路径之一。

接入草稿（待选）：
```yaml
- name: Assert UPDATE/ALL policies include WITH CHECK [PG.7]
  run: python3 scripts/check_rls_with_check.py
```

## helper 形态的盲点

v067_three_way_match.py:43 是动态 `f"CREATE POLICY {table}_update ON {table} FOR UPDATE USING ({_SAFE_CONDITION})"`
helper。lint 看见的是字符串模板，不是运行时 SQL。helper 本身漏了 `WITH CHECK`，
所以**所有调用此 helper 的表都受影响**——但 lint 工具仅在定义点报一次。修补 helper
即可一并修补所有使用方；调用面追溯需结合 `grep three_way_match` 的导入分析。
