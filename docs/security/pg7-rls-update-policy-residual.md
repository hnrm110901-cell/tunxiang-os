# PG.7 RLS UPDATE/ALL Policy WITH CHECK — 历史违规清单

> **状态**: Lint 工具 ast 重写后已**自带 baseline**，CI 可直接接入；运行时 policy 已由 v399/v400/v401/v402 修补
> **更新日期**: 2026-05-05
> **触发命令**:
> - `python3 scripts/check_rls_with_check.py` — 默认模式（baseline-excused，新违规才 fail，CI 用）
> - `python3 scripts/check_rls_with_check.py --strict` — 全量模式（28 处全报，未来 drain 进度参考）

## 背景

`CREATE POLICY ... FOR UPDATE USING (...)` 仅有 `USING` 子句而无 `WITH CHECK` 时存在跨租户逃逸面：
应用层若能写入 `tenant_id` 列（业务漏洞 / 注入），UPDATE 通过 USING 校验后行就被改属另一租户，原租户视野永远丢失该行。详见 `v399_points_update_policy_with_check.py` 头部注释。

## 修补 PR 链（合并后运行时 policy 全合规）

| PR | 修补范围 | 表数 |
|----|---------|------|
| v395 (in main) | delivery_dispatches | 1 |
| v399 (in main) | card_types / member_cards / points_log | 3 |
| #187 (v400) | patrol×5 / payment×3 / subsidy×2 / users×2 / employee_role_assignments | 13 |
| #189 (v401) | purchase_invoices / purchase_match_records (v067 helper 域) | 2 |
| #192 (v402) | dispatch_rules / ontology_snapshots / api×4 / dish_allergens / receiving_orders / stocktake_sessions / patrol_logs / crew×4 | 14 |
| **合计** | | **33** |

## 字面 SQL 违规清单（28 处，14 文件 — 已 baseline）

按 CLAUDE.md §18 "已应用迁移禁止修改"，原 migration 文件的 USING-only 字面 SQL **保留不动**；运行时 policy 由上方 PR 链 DROP+CREATE 替换。lint 把这 14 个 file 加 baseline，CI 不会 fail。

| 文件 | 表 / Policy | 形态 |
|------|-----|------|
| v020_dispatch_rules.py | dispatch_rules | NULLIF+UUID |
| v052_allergen_management.py | dish_allergens | 3-clause AND |
| v053_supply_chain_mobile.py | receiving_orders / stocktake_sessions | 3-clause AND |
| v055_patrol_logs.py | patrol_logs | 3-clause AND |
| v065_patrol_inspection.py | patrol_issues | NULLIF+UUID |
| v067_three_way_match.py | helper `{table}_update`（动态） | NULLIF+UUID |
| v068_ontology_snapshots.py | ontology_snapshots / `onto_snap_update` | NULLIF+UUID |
| v069_open_api_platform.py | api_applications / api_access_tokens / api_request_logs / api_webhooks | NULLIF+UUID |
| v072_mfa_auth.py | users | NULLIF+UUID |
| v073_rbac_roles.py | user_roles | NULLIF+UUID |
| v076_role_permission_levels.py | employee_role_assignments | NULLIF+UUID |
| v151_crew_schedule_tables.py | crew_schedules / crew_checkin_records / crew_shift_swaps / crew_shift_summaries | text-cast |
| v284_payment_nexus.py | payment_channel_configs / payment_sagas / payment_idempotency | 3-clause AND |
| v386_subsidy_programs.py | tenant_subsidies / subsidy_bills | simple `::uuid` cast |

## CI 接入

`scripts/check_rls_with_check.py` 默认模式跑通（0 new violations）。可直接接入 `.github/workflows/migration-ci.yml`：

```yaml
- name: Assert UPDATE/ALL policies include WITH CHECK [PG.7]
  run: python3 scripts/check_rls_with_check.py
```

**新 migration** 若添加 `FOR UPDATE/ALL ... USING (...)` 而无 `WITH CHECK`，lint fail。
**baseline 文件**若被新增违规（理论上不会，因为不能改已应用 migration），会被自动豁免 — 但 14 个文件已 frozen，不会变。

## drain 路线（将来某天）

未来若做 migration squash（合并历史 migrations 到一个起点），把这 14 个 file 的字面 SQL 一并改成 USING+WITH CHECK，然后从 baseline 移除。

## helper 形态的盲点

v067_three_way_match.py:41 是动态 `f"CREATE POLICY {table}_update ON {table} FOR UPDATE USING ({_SAFE_CONDITION})"` helper。lint 看见的是字符串模板（占位符 `{}`），FOR UPDATE 命中即报警。helper 本身漏了 WITH CHECK，所以所有调用此 helper 的表（v067 内部的 purchase_invoices / purchase_match_records）都受影响 — 已被 v401 (PR #189) 在运行时修补。
