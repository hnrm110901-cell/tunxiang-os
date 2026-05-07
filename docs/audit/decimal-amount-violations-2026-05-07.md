# Decimal 金额违规扫描报告

**扫描根目录：** `services`  
**违规总数：** 27  

## tx-expense (1 处)

| 文件 | 行 | 字段名 | 类型 | 严重度 |
|------|-----|--------|------|--------|
| `travel.py` | 117 | `total_mileage_km` | `Numeric(10, 2)` | **high** |

## tx-finance (8 处)

| 文件 | 行 | 字段名 | 类型 | 严重度 |
|------|-----|--------|------|--------|
| `cost_snapshot.py` | 56 | `raw_material_cost` | `Numeric(10, 4)` | **warning** |
| `cost_snapshot.py` | 57 | `labor_cost_allocated` | `Numeric(10, 4)` | **warning** |
| `cost_snapshot.py` | 58 | `overhead_allocated` | `Numeric(10, 4)` | **warning** |
| `cost_snapshot.py` | 59 | `total_cost` | `Numeric(10, 4)` | **warning** |
| `cost_snapshot.py` | 62 | `selling_price` | `Numeric(10, 2)` | **high** |
| `invoice.py` | 66 | `amount` | `Numeric(10, 2)` | **high** |
| `invoice.py` | 67 | `tax_amount` | `Numeric(10, 2)` | **high** |
| `voucher.py` | 110 | `total_amount` | `Numeric(12, 2)` | **high** |

## tx-member (10 处)

| 文件 | 行 | 字段名 | 类型 | 严重度 |
|------|-----|--------|------|--------|
| `stored_value_account.py` | 85 | `balance` | `Numeric(10, 2)` | **high** |
| `stored_value_account.py` | 91 | `gift_balance` | `Numeric(10, 2)` | **high** |
| `stored_value_account.py` | 99 | `total_recharged` | `Numeric(12, 2)` | **high** |
| `stored_value_account.py` | 105 | `total_consumed` | `Numeric(12, 2)` | **high** |
| `stored_value_account.py` | 151 | `amount` | `Numeric(10, 2)` | **high** |
| `stored_value_account.py` | 156 | `gift_amount` | `Numeric(10, 2)` | **high** |
| `stored_value_account.py` | 164 | `balance_before` | `Numeric(10, 2)` | **high** |
| `stored_value_account.py` | 169 | `balance_after` | `Numeric(10, 2)` | **high** |
| `stored_value_account.py` | 174 | `gift_balance_before` | `Numeric(10, 2)` | **high** |
| `stored_value_account.py` | 180 | `gift_balance_after` | `Numeric(10, 2)` | **high** |

## tx-trade (8 处)

| 文件 | 行 | 字段名 | 类型 | 严重度 |
|------|-----|--------|------|--------|
| `banquet_ai.py` | 90 | `food_cost_rate` | `Numeric(5, 2)` | **high** |
| `banquet_contract.py` | 39 | `deposit_ratio` | `Numeric(5, 2)` | **high** |
| `chef_performance_daily.py` | 22 | `dish_amount` | `Numeric(12, 2)` | **high** |
| `discount_audit_log.py` | 43 | `original_amount` | `Numeric(12, 2)` | **high** |
| `discount_audit_log.py` | 44 | `final_amount` | `Numeric(12, 2)` | **high** |
| `discount_audit_log.py` | 45 | `discount_amount` | `Numeric(12, 2)` | **high** |
| `wine_storage.py` | 61 | `storage_price` | `Numeric(12, 2)` | **high** |
| `wine_storage.py` | 92 | `price_at_trans` | `Numeric(12, 2)` | **high** |

---

## 规范说明

根据 CLAUDE.md §15/§17：**金额字段必须使用 `Integer`（单位：分），不得使用 `Numeric`/`Decimal` 类型。**

- `high`：`Numeric(M, 2)` — 明显的人民币元/角格式，必须修为 `Integer`
- `warning`：`Numeric(M, N≠2)` — 疑似金额但 scale 异常，需人工核查

**白名单（不报警）：** 字段名含 `rate` 且 scale ≤ 4 的百分比字段（如 `tax_rate Numeric(5,4)`）。
