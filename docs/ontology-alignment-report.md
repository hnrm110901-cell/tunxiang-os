# Ontology 对齐报告 — 新老项目数据模型差异分析

> 生成时间: 2026-03-27
> 老项目路径: `/Users/lichun/tunxiang/apps/api-gateway/src/models/`
> 新项目路径: `/Users/lichun/tunxiang-os/shared/ontology/src/entities.py`

---

## 1. Customer（顾客）

老项目模型: `private_domain.py` → `PrivateDomainMember`

| 字段名 | 老项目 | 新项目(补全前) | 新项目(补全后) | 优先级 | 说明 |
|--------|--------|---------------|---------------|--------|------|
| r_score | Integer | -- | Integer | P0 | RFM标准化评分，私域运营核心 |
| f_score | Integer | -- | Integer | P0 | RFM标准化评分 |
| m_score | Integer | -- | Integer | P0 | RFM标准化评分 |
| rfm_updated_at | DateTime | -- | DateTime | P0 | RFM重算时间戳 |
| store_quadrant | String(20) | -- | String(20) | P1 | 门店象限分类 |
| risk_score | Float | -- | Float | P1 | 流失风险评分 |
| channel_source | String(50) | source(已有) | -- | -- | 已覆盖(字段名不同) |
| wechat_openid | String(100) | String(128) | -- | -- | 已覆盖 |
| is_active | Boolean | is_merged(反向) | -- | -- | 语义等价 |

**未迁入字段(有意排除):**
- `store_id` — 老项目按门店存会员，新项目采用 Golden ID 架构，按 tenant_id 统一
- `consumer_id` — 新项目 Customer 本身就是 CDP 统一身份，无需额外 ID

---

## 2. Store（门店）

老项目模型: `store.py` → `Store`

| 字段名 | 老项目 | 新项目(补全前) | 新项目(补全后) | 优先级 | 说明 |
|--------|--------|---------------|---------------|--------|------|
| email | String(100) | -- | String(100) | P1 | 门店联系邮箱 |
| manager_id | UUID | -- | UUID | P0 | 店长ID，排班/审批必需 |
| is_active | Boolean | -- | Boolean | P0 | 快速过滤在营门店 |
| monthly_revenue_target | Numeric(12,2)元 | Integer(分) | -- | -- | 已覆盖，单位已转分 |

**未迁入字段(有意排除):**
- 无 — 老项目 Store 字段较少，新项目已全面超集

---

## 3. Dish（菜品）

老项目模型: `dish.py` → `Dish` + `dish_master.py` → `DishMaster`

| 字段名 | 老项目 | 新项目(补全前) | 新项目(补全后) | 优先级 | 说明 |
|--------|--------|---------------|---------------|--------|------|
| store_id | String(50) FK | -- | UUID FK | P0 | 菜品归属门店，多店菜单隔离核心 |
| season | String(20) | -- | String(20) | P2 | 季节菜品筛选 |
| requires_inventory | Boolean | -- | Boolean | P1 | 控制是否扣减库存 |
| low_stock_threshold | Integer | -- | Integer | P1 | 低库存预警阈值 |
| dish_master_id | UUID FK | -- | UUID | P0 | 集团→品牌→门店三层菜品继承链核心 |
| notes | Text | -- | Text | P2 | 菜品备注 |
| dish_metadata | JSON | -- | JSON | P2 | 灵活扩展字段 |
| price | Numeric(10,2)元 | price_fen(分) | -- | -- | 已覆盖，单位已统一为分 |

### DishCategory 补全

| 字段名 | 老项目 | 新项目(补全前) | 新项目(补全后) | 优先级 | 说明 |
|--------|--------|---------------|---------------|--------|------|
| store_id | String(50) FK | -- | UUID FK | P0 | 分类归属门店 |
| description | Text | -- | Text | P2 | 分类描述 |

### DishIngredient 补全

| 字段名 | 老项目 | 新项目(补全前) | 新项目(补全后) | 优先级 | 说明 |
|--------|--------|---------------|---------------|--------|------|
| substitute_ids | ARRAY(UUID) | -- | ARRAY(UUID) | P1 | 可替代食材列表，供应链中断时关键 |
| notes | Text | -- | Text | P2 | 配方备注 |

---

## 4. Order（订单）

老项目模型: `order.py` → `Order` + `OrderItem`

| 字段名 | 老项目 | 新项目(补全前) | 新项目(补全后) | 优先级 | 说明 |
|--------|--------|---------------|---------------|--------|------|
| customer_name | String(100) | -- | String(100) | P1 | 散客姓名，未关联CDP时记录 |
| customer_phone | String(20) | -- | String(20) | P1 | 散客手机号 |
| table_number | String(20) | 仅在metadata | String(20)顶层 | P0 | 堂食场景高频查询，同时保留metadata冗余 |
| total_amount | Numeric(10,2)元 | total_amount_fen(分) | -- | -- | 已覆盖，单位统一为分 |
| sales_channel | String(30) | sales_channel_id | -- | -- | 已升级为配置表引用 |

**未迁入字段(有意排除):**
- `consumer_id` — 新项目使用 `customer_id` FK 直接关联 Customer 表

---

## 5. Ingredient（食材/库存）

老项目模型: `inventory.py` → `InventoryItem` + `InventoryTransaction`

### Ingredient (门店库存台账)

| 字段名 | 老项目 | 新项目(补全前) | 新项目(补全后) | 优先级 | 说明 |
|--------|--------|---------------|---------------|--------|------|
| supplier_contact | String(100) | -- | String(100) | P1 | 供应商联系方式，紧急补货时需要 |

### IngredientTransaction (库存流水)

| 字段名 | 老项目 | 新项目(补全前) | 新项目(补全后) | 优先级 | 说明 |
|--------|--------|---------------|---------------|--------|------|
| store_id | String(50) FK | -- | UUID FK | P0 | 按门店查询流水必需 |
| total_cost_fen | Integer(分) | -- | Integer | P1 | 总成本=数量*单价，财务对账必需 |
| quantity_before | Float | -- | Float | P0 | 操作前库存量，对账/审计核心 |
| quantity_after | Float | -- | Float | P0 | 操作后库存量 |
| performed_by | String(100) | -- | String(100) | P1 | 操作人追溯 |
| transaction_time | DateTime | -- | DateTime | P0 | 操作时间（区别于created_at） |

---

## 6. Employee（员工）

老项目模型: `employee.py` → `Employee`

| 字段名 | 老项目 | 新项目(补全前) | 新项目(补全后) | 优先级 | 说明 |
|--------|--------|---------------|---------------|--------|------|
| health_cert_attachment | String(500) | -- | String(500) | P1 | 健康证附件，合规检查需要 |
| id_card_expiry | Date | -- | Date | P1 | 身份证到期日 |
| background_check | String(50) | -- | String(50) | P1 | 背调状态 |
| first_work_date | Date | -- | Date | P1 | 首次工作日期 |
| regular_date | Date | -- | Date | P1 | 转正日期 |
| seniority_months | Integer | -- | Integer | P1 | 司龄(月)，薪酬计算参考 |
| bank_branch | String(200) | -- | String(200) | P1 | 开户行支行，工资发放需要 |
| emergency_relation | String(20) | -- | String(20) | P2 | 紧急联系人关系 |

**未迁入字段(有意排除 — 低频/冗余):**
- `marital_status` — 非业务必需个人隐私
- `ethnicity` — 非业务必需
- `hukou_type` / `hukou_location` — 社保相关，后续按需加入
- `height_cm` / `weight_kg` — 非业务必需
- `political_status` — 非业务必需
- `accommodation` — 低频使用
- `union_member` / `union_cadre` — 低频使用
- `major` / `graduation_school` / `professional_cert` — 可放入 preferences JSON

---

## 7. 老项目独有模型（新项目暂未迁入）

| 模型 | 老项目文件 | 说明 | 建议 |
|------|-----------|------|------|
| BOMTemplate | bom.py | 版本化配方管理，支持作用域/渠道/继承 | P0 — 成本核算核心，建议作为独立实体加入 |
| BOMItem | bom.py | BOM明细行，含损耗系数/毛料用量 | P0 — 随BOMTemplate一起迁入 |
| DishMaster | dish_master.py | 集团级SKU主档 | P0 — 多品牌菜品管理核心 |
| BrandMenu | dish_master.py | 品牌层价格覆盖 | P1 — 多品牌定价体系 |
| StoreMenu | dish_master.py | 门店层价格覆盖 | P1 — 三层价格继承链 |
| PrivateDomainSignal | private_domain.py | 信号感知记录 | P2 — 私域Agent数据源 |
| PrivateDomainJourney | private_domain.py | 用户旅程记录 | P2 — 私域Agent数据源 |
| StoreQuadrantRecord | private_domain.py | 门店象限历史 | P2 — 经营分析数据源 |

---

## 8. 金额单位对齐总结

| 实体 | 老项目单位 | 新项目单位 | 状态 |
|------|-----------|-----------|------|
| Dish.price | 元 Numeric(10,2) | 分 Integer | 已统一 |
| Order.total_amount | 元 Numeric(10,2) | 分 Integer | 已统一 |
| OrderItem.unit_price | 元 Numeric(10,2) | 分 Integer | 已统一 |
| InventoryItem.unit_cost | 分 Integer | 分 Integer | 一致 |
| BOMItem.unit_cost | 分 Integer | (BOM待迁入) | -- |
| Employee.daily_wage | 分 Integer | 分 Integer | 一致 |
| Store.monthly_revenue_target | 元 Numeric(12,2) | 分 Integer | 已统一 |

**结论**: 新项目已完全统一为分(fen)存储，命名后缀 `_fen`，符合 `amount_convention.py` 公约。

---

## 9. 后续行动建议

1. **P0 — BOM 模型迁入**: 将 `BOMTemplate` + `BOMItem` 迁入 `entities.py`，这是成本核算的核心数据结构
2. **P0 — DishMaster 体系迁入**: 将集团主档 + 品牌菜单 + 门店菜单三层继承链迁入
3. **P1 — Alembic 迁移脚本**: 为本次新增字段生成数据库迁移
4. **P2 — 私域模型迁入**: Signal/Journey/Quadrant 三个辅助模型后续按需迁入
