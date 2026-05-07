# Decimal 金额违规扫描报告

**生成日期：** 2026-05-07  
**扫描根目录：** `services/`  
**违规总数：** 25  
**扫描脚本：** `scripts/audit/scan_decimal_amount_columns.py`  
**关联差距：** `docs/gap-verification-2026-05-07.md` Part E 第 8 项  

---

## 背景

根据 CLAUDE.md §15/§17：**所有金额字段必须使用 `Integer`（单位：分/fen），不得使用 `Numeric`/`Decimal` 类型。**

本报告由 AST 扫描器自动生成，检测 `services/*/src/models/*.py` 中字段名疑似金额但仍用 `Numeric(M, N)` 的违规点。

**白名单规则（不报警）：** 字段名含 `rate` 且 scale ≤ 4 的百分比字段（如 `tax_rate Numeric(5, 4)`、`deposit_rate Numeric(5, 4)`）。

---

## tx-expense（1 处）

| 文件 | 行 | 字段名 | 类型 | 严重度 | 说明 |
|------|-----|--------|------|--------|------|
| `travel.py` | 117 | `total_mileage_km` | `Numeric(10, 2)` | **high** | 字段含 total，疑似金额，需确认是否里程数（非金额可申请豁免） |

---

## tx-finance（7 处）

| 文件 | 行 | 字段名 | 类型 | 严重度 | 说明 |
|------|-----|--------|------|--------|------|
| `cost_snapshot.py` | 56 | `raw_material_cost` | `Numeric(10, 4)` | **warning** | 成本字段，注释已标"分"但类型用 Numeric |
| `cost_snapshot.py` | 57 | `labor_cost_allocated` | `Numeric(10, 4)` | **warning** | 成本字段，注释已标"分"但类型用 Numeric |
| `cost_snapshot.py` | 59 | `total_cost` | `Numeric(10, 4)` | **warning** | 成本字段，注释已标"分"但类型用 Numeric |
| `cost_snapshot.py` | 62 | `selling_price` | `Numeric(10, 2)` | **high** | 价格字段，应改为 Integer（分） |
| `invoice.py` | 66 | `amount` | `Numeric(10, 2)` | **high** | 全电发票金额，应改为 Integer（分） |
| `invoice.py` | 67 | `tax_amount` | `Numeric(10, 2)` | **high** | 全电发票税额，应改为 Integer（分） |
| `voucher.py` | 110 | `total_amount` | `Numeric(12, 2)` | **high** | 凭证总金额，应改为 Integer（分） |

---

## tx-member（10 处）

| 文件 | 行 | 字段名 | 类型 | 严重度 | 说明 |
|------|-----|--------|------|--------|------|
| `stored_value_account.py` | 85 | `balance` | `Numeric(10, 2)` | **high** | 储值余额，应改为 Integer（分） |
| `stored_value_account.py` | 91 | `gift_balance` | `Numeric(10, 2)` | **high** | 赠送余额，应改为 Integer（分） |
| `stored_value_account.py` | 99 | `total_recharged` | `Numeric(12, 2)` | **high** | 累计充值，应改为 Integer（分） |
| `stored_value_account.py` | 105 | `total_consumed` | `Numeric(12, 2)` | **high** | 累计消费，应改为 Integer（分） |
| `stored_value_account.py` | 151 | `amount` | `Numeric(10, 2)` | **high** | 交易金额，应改为 Integer（分） |
| `stored_value_account.py` | 156 | `gift_amount` | `Numeric(10, 2)` | **high** | 赠送金额，应改为 Integer（分） |
| `stored_value_account.py` | 164 | `balance_before` | `Numeric(10, 2)` | **high** | 变更前余额，应改为 Integer（分） |
| `stored_value_account.py` | 169 | `balance_after` | `Numeric(10, 2)` | **high** | 变更后余额，应改为 Integer（分） |
| `stored_value_account.py` | 174 | `gift_balance_before` | `Numeric(10, 2)` | **high** | 变更前赠送余额，应改为 Integer（分） |
| `stored_value_account.py` | 180 | `gift_balance_after` | `Numeric(10, 2)` | **high** | 变更后赠送余额，应改为 Integer（分） |

---

## tx-trade（7 处）

| 文件 | 行 | 字段名 | 类型 | 严重度 | 说明 |
|------|-----|--------|------|--------|------|
| `banquet_contract.py` | 39 | `deposit_ratio` | `Numeric(5, 2)` | **high** | 定金比例（注释标%），应确认是否为比例字段可豁免 |
| `chef_performance_daily.py` | 22 | `dish_amount` | `Numeric(12, 2)` | **high** | 厨师绩效金额，应改为 Integer（分） |
| `discount_audit_log.py` | 43 | `original_amount` | `Numeric(12, 2)` | **high** | 原始折扣金额，Tier1 违规，待 P0-1 修复 |
| `discount_audit_log.py` | 44 | `final_amount` | `Numeric(12, 2)` | **high** | 折后金额，Tier1 违规，待 P0-1 修复 |
| `discount_audit_log.py` | 45 | `discount_amount` | `Numeric(12, 2)` | **high** | 折扣金额，Tier1 违规，待 P0-1 修复 |
| `wine_storage.py` | 61 | `storage_price` | `Numeric(12, 2)` | **high** | 存酒金额（元），Tier1 违规，待 P0-2 修复 |
| `wine_storage.py` | 92 | `price_at_trans` | `Numeric(12, 2)` | **high** | 存酒流水金额（元），Tier1 违规，待 P0-2 修复 |

---

## 严重度说明

| 严重度 | 含义 | 处理要求 |
|--------|------|----------|
| **high** | `Numeric(M, 2)` — 明显的人民币元格式 | 必须改为 `Integer`（分），无例外 |
| **warning** | `Numeric(M, N≠2)` — 疑似金额但 scale 不是 2 | 需人工核查，确认是否金额字段 |

---

## 修复路线

| 服务 | 负责 PR | 状态 |
|------|---------|------|
| tx-trade（wine_storage + discount_audit_log） | P0-2 / P0-1 | 并行修复中 |
| tx-finance（invoice + cost_snapshot） | 待排期 | baseline 中 |
| tx-member（stored_value_account） | 待排期 | baseline 中 |
| tx-expense（travel） | 待排期 | baseline 中，需确认是否金额 |
| tx-trade（banquet_contract 定金比例） | 待排期 | baseline 中，需确认豁免资格 |

---

## 后续递减方式

每个 P0 金额修复 PR（如 P0-1、P0-2）在修复业务代码后，必须同步在
`tests/tier1/test_no_decimal_amount_tier1.py` 的 `KNOWN_BASELINE` 集合中删除对应条目。
删除后 CI 守门测试才会对该条目生效（新增违规自动拒绝）。
