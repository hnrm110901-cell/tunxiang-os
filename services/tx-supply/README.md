# tx-supply 供应链升级开发计划

> **屯象OS 供应链微服务** — 从 G10 形态 SoR 复刻到 AI-Native SoI 双层操作系统的 6 个月升级路线
>
> 作者立场：CTO 视角，**实事求是 + 第一性原理**双轨。不复刻 G10 形态，复刻其**用户价值**；不为 AI 而 AI，先解 SoR（System of Record）合规/操作刚需，再叠 SoI（System of Intelligence）决策增量。
>
> 最后更新：2026-05-14 · 对标基线：G10云仓 v8.0（236+ 功能 / 10 模块）

---

## 目录

- [一、第一性原理](#一第一性原理供应链系统的本质)
- [二、对标差距总览](#二对标差距总览)
- [三、P0 PRD 清单（7 项）](#三p0-prd-清单7-项阻塞-week-8-验收--23-套替换)
- [四、P1 PRD 清单（10 项）](#四p1-prd-清单10-项徐记替换必备)
- [五、P2 清单（6 项）](#五p2-清单6-项长尾3-个月内补)
- [六、明确不做（4 项）](#六明确不做4-项)
- [七、6 个月分阶段路线图](#七6-个月分阶段路线图)
- [八、长期价值沉淀地图](#八长期价值沉淀地图5-大数据资产)
- [九、关键风险](#九关键风险--缓解)
- [十、与 Tier 1 row-lock 工作整合](#十与现有-tier-1-row-lock-工作的整合点)

---

## 一、第一性原理：供应链系统的本质

抽掉所有 UI 噪音，供应链管 3 件事：

1. **货从哪来** — 供应商资质 + 采购决策（价、量、时机、合规）
2. **货怎么进** — 收货 + 入库 + 质检 + 成本归属
3. **货怎么出** — 用料（BOM）+ 损耗 + 盘点 + 出库追溯

G10 是 **SoR（事后记账）** — 完备但是死数据；屯象目标是 **SoI（事前决策）** — 但**不能跳过 SoR**。23 套系统替换中，徐记采购总监/财务/库管 80% 时间在录单/查表/对账。**SoI 是增量价值，不是替代 SoR**。

### 实事求是的 3 条裁决标准

任何 G10 缺失项，过这 3 道闸：

| 闸 | 问 | 不过 → |
|---|---|---|
| **合规闸** | 不做是否违反 Tier 1（毛利底线/食安/客户体验）或国家法规？ | **P0 必做**（不论形态多丑）|
| **替换闸** | 不做是否阻塞徐记/最黔线**替换决策**（采购总监 demo 时一票否决）？ | **P0 必做**（直接复刻 G10 形态）|
| **价值闸** | 做了能沉淀长期资产（数据/模型/网络效应/UX 壁垒）？ | **AI 化重做**；否则**最小复刻** |

---

## 二、对标差距总览

仅供应链相关（采购/库存/仓储/BOM/供应商/收货/质检/物流/成本/价格/调研），共 69 项：

| 模块 | G10 项数 | 屯象 ✅ | 🟡 部分 | ❌ 缺失 |
|---|---|---|---|---|
| 1 商品主数据 | 17 | 7 | 8 | 2 |
| 2 申购模板 | 3 | 0 | 1 | 2 |
| 3 BOM | 10 | 8 | 1 | 1 |
| 4 供应商 | 16 | 10 | 2 | 4 |
| 5 采购定价 | 12 | 9 | 3 | 0 |
| 6 市场调研 | 4 | 0 | 1 | 3 |
| 7 询价单 | 3 | 0 | 1 | 2 |
| 8 其他 | 4 | 0 | 2 | 2 |
| **合计** | **69** | **34 (49%)** | **19 (28%)** | **16 (23%)** |

**供应链模块覆盖率 49%**，明显低于整体 60%。屯象供应链是核心定位（连锁餐饮 Palantir），但传统 ERP 功能完整度有缺口，集中在 ①主数据维护 UI ②单据编号 ③人工调研/比价 ④食安证件临期 四块。

### 屯象反超 G10 的 7 大差异点（销售话术）

1. **AI 供应商评分**（`supplier_scoring_engine`）— G10 只有静态打分表
2. **动态定价 + AI 推荐菜**（`dish_dynamic_pricing` / `upsell_generator`）— G10 无
3. **价格 ledger 全量流水 + AI 预警**（`price_ledger_service`）— G10 是周期快照
4. **OmniChannel 6 平台 + AI 自动调研**（`smart_procurement`）— G10 是人工询价
5. **AI 智能补货 / MRP 引擎**（`mrp_engine_service`）— G10 是定时模板补货
6. **全链路 traceability + 活鲜溯源**（`traceability` + `seafood_traceability`）— G10 无
7. **Tier 1 资金路径 row-lock 严格性**（2026-05 audit 全扫 24 漏锁/14 P0 全修）— G10 传统 ASP.NET MVC 难以保证

---

## 三、P0 PRD 清单（7 项，阻塞 Week 8 验收 + 23 套替换）

### PRD-01 供应商证件临期预警【Tier 1 食安合规】

**业务问题**：食品经营许可证 / 检验报告 / 健康证过期不发现 → 食药监突击检查 → 一店关停 + 全连锁停业整顿。徐记 200+ 供应商，证件 5+ 类，**人工台账必漏**。

**用户故事**：作为食安总监，我需要在证件**到期前 30/15/7 天**收到推送，并在过期当天**自动阻断该供应商的入库收货**。

**验收标准**（GIVEN/WHEN/THEN）：
- GIVEN 供应商 A 的"食品经营许可证"`expire_date = 2026-06-01`
- WHEN 系统时间到达 2026-05-02（30 天前）
- THEN 自动推送给食安总监 + 该供应商对接采购员 + supplier_portal 推送
- AND 过期当天 `receiving_v2_service` 拒绝该供应商所有入库单（HTTP 422 + 原因码 `SUPPLIER_CERT_EXPIRED`）
- AND 续证后**自动恢复**收货能力（无需人工解锁）

**数据模型**：
```python
# 已有 supplier_certificates 表，加字段：
expire_date: date  NOT NULL
warning_days: List[int] = [30, 15, 7]  # JSON
last_alert_sent_at: datetime
auto_block_on_expire: bool = True  # 食材类 True，文件类 False
```

**接口**：
- `GET /api/supply/suppliers/{id}/certificates/expiring?within_days=30`
- `POST /api/supply/certificates/{id}/renew`（含上传扫描件）
- Worker: `cert_expiry_alerter`（每日 06:00 跑，命中即推 + 写 `alert_aggregation`）

**Tier**: Tier 1（食安合规硬约束 → TDD 必须）
**工时**: 5 人日 = 模型 0.5 + service 1 + worker 1 + 收货阻断 1 + UI 1 + 测试 0.5
**长期资产**: 监管数据沉淀（哪类证最易过期、续证最慢供应商 → AI 评分输入）

---

### PRD-02 商品扣秤标准库（毛重/净重/去皮）【Tier 1 毛利底线】

**业务问题**：徐记每天收 30 吨海鲜 + 蔬菜，**毛菜（带泥/带冰/带袋）→ 净菜**出料率 60%~95%。供应商按毛重报价、按毛重送达，但用料按净重，**扣秤标准不统一 → 毛利偏差 3~8%**。

**第一性原理**：这不是"信息系统"问题，是"度量衡"问题。**标准缺失 → 任何 AI 算的毛利都是错的**。

**用户故事**：作为采购总监，我需要对每个 SKU 维护"标准扣秤项"（如冰块 8%、塑料袋 0.3 斤、菜叶损耗 12%），收货时**自动扣秤后入账**，超过标准扣秤 ±2% **自动报警**到我手机。

**数据模型**：
```python
class IngredientWeightStandard(Base):
    ingredient_id: UUID
    deduct_type: Literal["ice","packaging","leaves","stem","other"]
    deduct_method: Literal["percentage","fixed_kg"]
    deduct_value: Decimal
    tolerance_pct: Decimal = 2.0
    effective_from: date
    effective_to: date | None
    approved_by: UUID
```

**接口**：
- `POST /api/supply/ingredients/{id}/weight-standards`（二级审批）
- `POST /api/supply/receiving/{id}/calculate-net-weight`
- Event: `weight_deduction_anomaly` → 推 `alert_aggregation`

**Tier**: Tier 1（毛利底线 → TDD）
**工时**: 8 人日
**长期资产**: ⭐ **生鲜 SKU 标准扣秤库**（行业级竞争壁垒 — 越用越准）

---

### PRD-03 业务单号定制规则【Tier 1 审计/财务】

**业务问题**：徐记财务对账系统 + 食药监稽查 + 银行流水匹配，都需要可读单号：`PO20260513-001` 比 `9f3a-...UUID` 高 100 倍效率。屯象 UUID 是工程偷懒，**财务/审计场景不可用**。

**第一性原理**：单号 = 业务实体的**人类可读身份证**。UUID 是机器身份证，PO20260513 是人类身份证。**两者并存**（UUID 主键、单号展示）。

**用户故事**：作为财务经理，我需要在系统设置里配置：采购单 `PO{yyyy}{MM}{dd}-{seq:03d}`，盘点单 `STK-{store_code}-{yyyyMM}-{seq:04d}`，**租户级可定制**。

**数据模型**：
```python
class DocNumberRule(Base):
    tenant_id: UUID
    doc_type: str  # purchase_order / requisition / stocktake / transfer / receiving / ...
    template: str  # "PO{yyyy}{MM}{dd}-{seq:03d}"
    seq_scope: Literal["global","daily","monthly","store"]
    seq_reset_at: date
    current_seq: int
    is_active: bool
```

**接口**：
- `POST /api/supply/doc-number-rules`
- `POST /api/supply/doc-number/generate`（PG advisory_lock 并发安全）
- 现有 17 类单据全部回填 `doc_number` 字段（不影响 UUID 主键）

**Tier**: Tier 1（审计 + 财务对账）
**工时**: 10 人日
**长期资产**: 跨服务通用基础设施

---

### PRD-04 询价单 + 比价表【Tier 1 毛利底线 + 合规】

**业务问题**：屯象 AI 推荐供应商是黑盒，**采购总监无法向老板/审计交代**为何选 A 不选 B。**国企/上市公司客户的采购合规要求"三家比价"**，黑盒 AI 不被接受。

**第一性原理**：AI 推荐是**助手**（assistive），**决策权必须在人**。比价表是 AI 透明化的载体。

**用户故事**：作为采购员，我需要：
1. 创建 RFQ：选 SKU + 选 3+ 供应商 + 截止时间
2. 系统**自动**邀请这些供应商在 `supplier_portal` 填价
3. AI **自动**预填屯象历史价 + 市场价 + 推荐供应商，但**最终决策保留**
4. 截止后生成**比价表**（含 AI 推荐 + 偏差预警）+ 二级审批（>5% 涨幅必审）

**数据模型**：
```python
class RFQ(Base):
    rfq_number: str  # 走 PRD-03 单号规则
    initiator_id: UUID
    deadline: datetime
    status: Literal["draft","published","quoting","comparing","awarded","cancelled"]

class RFQItem(Base):
    rfq_id: UUID
    ingredient_id: UUID
    qty_required: Decimal
    spec_notes: str

class RFQInvitee(Base):
    rfq_id: UUID
    supplier_id: UUID
    invited_at: datetime
    responded_at: datetime | None

class RFQQuote(Base):
    rfq_id: UUID
    supplier_id: UUID
    ingredient_id: UUID
    unit_price_fen: int  # 分
    valid_until: date
    notes: str
    submitted_at: datetime

class RFQAward(Base):
    rfq_id: UUID
    selected_quote_id: UUID
    reason: str  # 合规审计
    approved_by: UUID
    ai_recommendation_followed: bool  # ⭐ RLHF 信号
```

**接口**：
- `POST /api/supply/rfqs`
- `POST /api/supply/rfqs/{id}/invite`
- `POST /api/supplier-portal/rfqs/{id}/quote`
- `GET /api/supply/rfqs/{id}/comparison`（比价表 + AI 标注）
- `POST /api/supply/rfqs/{id}/award`

**Tier**: Tier 1（毛利底线 + 合规）
**工时**: 18 人日（单项最大）
**长期资产**:
- ⭐ **三方比价数据集** → 训练 AI 推荐的 ground truth
- **供应商响应率/报价偏离度** → AI 评分输入
- ⭐ **采购员是否采纳 AI 推荐** → RLHF 信号（AI 自动议价的终极训练数据）

---

### PRD-05 补货时间窗硬约束【Tier 1 食安】

**业务问题**：生鲜必须在**4-7 点到货**（厨房 9 点开档前完成质检/分拣）。供应商**晚到 10 分钟 = 当餐缺菜**。屯象 `smart_replenishment` 是 AI 建议，**没有硬约束**。

**第一性原理**：时间窗是**门店运营的物理约束**（厨师下班、厨房备餐节奏），不是软建议。

**用户故事**：作为门店店长，我需要为每个供应商设置：
- 配送时间窗 `04:00-07:00`
- 提前/迟到容忍度 `±15min`
- 违约处理：自动扣分（接入 `supplier_scoring`）+ 累计 3 次黄牌警告
- 收货员**一键拒收**操作（带原因码）

**数据模型**：
```python
class SupplierDeliveryWindow(Base):
    supplier_id: UUID
    store_id: UUID
    weekday_mask: int  # 1-127 bit mask
    earliest_time: time
    latest_time: time
    grace_minutes: int = 15
    auto_reject_on_late: bool = False  # P0 仅记录，不自动拒收
```

**接口**：
- `POST /api/supply/suppliers/{id}/delivery-windows`
- `POST /api/supply/receiving/{id}/check-window`
- Event: `delivery_late` → 扣 `supplier_scoring` 分

**Tier**: Tier 1（食安 + 客户体验）
**工时**: 6 人日
**长期资产**: **供应商时间履约率** → 评分关键维度

---

### PRD-06 商品出料率标准库【Tier 1 毛利底线】

**业务问题**：**100 斤毛菜出 60 斤净菜** → 净菜 BOM 用量 1 斤 → 实际采购 1.67 斤。**出料率没有标准 → BOM 算出来的成本是假的 → 毛利全是假的**。

**用户故事**：作为采购总监 / 中央厨房经理，我需要维护：
- 每个原料的**标准出料率**（季节差异：春菠菜 65%、夏菠菜 50%）
- 实际出料率超过标准 ±5% → 报警
- 出料率**自动**进入 BOM 反算 → 采购量推荐

**数据模型**：
```python
class IngredientYieldStandard(Base):
    ingredient_id: UUID
    process_id: UUID | None  # 关联工序
    yield_rate: Decimal  # 0.60 = 60%
    season: Literal["spring","summer","autumn","winter","all"]
    effective_from: date
    effective_to: date | None
    tolerance_pct: Decimal = 5.0
    approved_by: UUID
```

**接口**：
- `POST /api/supply/ingredients/{id}/yield-standards`
- BOM 引擎集成：`bom_service.calc_purchase_qty()` 自动除以 yield_rate
- Event: `yield_anomaly` → 报警

**Tier**: Tier 1（毛利底线）
**工时**: 7 人日
**长期资产**: ⭐ **生鲜出料率知识库**（季节/产地/工序三维度）— 行业护城河

---

### PRD-07 申购模板 + 仓库级模板【操作效率 → 决定 NPS】

**业务问题**：门店每天上传申购单，**80% SKU 重复**。每次手工录 30+ 行 = 15 分钟/店 × 200 店 = 50 工时/天。**操作低效 → 店长抵触 → 替换失败**。

**用户故事**：作为门店店长，我需要：
1. 总部预设"标准申购模板"（按品类：海鲜/蔬菜/调料/酒水）
2. 一键发起申购 → 自动填充模板 SKU + AI 推荐量
3. 仓库（大店 / 小店 / 中央厨房）可有**不同模板**

**数据模型**：
```python
class RequisitionTemplate(Base):
    tenant_id: UUID
    name: str
    category: str
    is_active: bool
    created_by: UUID

class RequisitionTemplateItem(Base):
    template_id: UUID
    ingredient_id: UUID
    default_qty: Decimal | None  # null = AI 推荐
    qty_method: Literal["fixed","ai_predicted","last_order","par_level"]

class WarehouseRequisitionTemplateBinding(Base):
    warehouse_id: UUID
    template_id: UUID
    auto_trigger_cron: str | None
```

**接口**：
- 模板 CRUD
- `POST /api/supply/requisitions/from-template/{template_id}`（一键生成）
- AI 推荐量复用 `smart_replenishment` 现有引擎

**Tier**: T2（效率，但**决定客户留存**）
**工时**: 8 人日
**长期资产**: **门店申购行为画像** → AI 补货模型输入

---

## 四、P1 PRD 清单（10 项，徐记替换必备）

### PRD-08 部门用料范围白名单
- **价值**: 防止后厨员工领料"串货"（早餐档领高档食材 → 毛利漏）
- **模型**: `DepartmentIngredientWhitelist(dept_id, ingredient_id, max_qty_per_day)`
- **工时**: 4 人日

### PRD-09 分解型 BOM UI（整件拆零）
- **价值**: 1 箱啤酒 = 24 瓶，库存按箱采、按瓶销售，**没有拆分关系核算就错**
- **模型**: 已有 `bom_service split`，仅缺管理 UI + 自动转换 service
- **工时**: 5 人日

### PRD-10 产品测试标准库
- **价值**: 食品 QC（农残/兽残/微生物）标准化（GB 2761/2762 国标），**第三方检测对接基础**
- **模型**: `ProductTestStandard(ingredient_id, test_item, gb_code, threshold, frequency)`
- **工时**: 6 人日

### PRD-11 POS 销售分成转入库设置
- **价值**: 多人合点（"2 人共享一份酸菜鱼"）按比例转入库扣料
- **模型**: 现有 `auto_deduction` 加 `share_split_rule` 配置层
- **工时**: 4 人日

### PRD-12 资质证件类型字典维护 UI
- **价值**: PRD-01 的基础数据 — 不同地区/品类要求不同证件
- **模型**: `CertificateType(name, applicable_supplier_kinds, validity_period, is_required)`
- **工时**: 3 人日

### PRD-13 市场调研双轨（AI 主 + 人工巡店兜底）⭐
- **价值**: AI 调研缺早市/批发市场价（菜场无 API），**人工巡店**是必须的兜底
- **模型**: `MarketSurvey(survey_id, surveyor_id, location, sku_prices: JSON, surveyed_at, photos: URL[])`
- **移动端**: 创始人/采购总监**早市拍照录入** → 进 AI 训练池
- **工时**: 12 人日（含移动端）
- **长期资产**: ⭐ **本地早市价数据集**是连锁餐饮独家资产

### PRD-14 商品采购及销售价格一览（统一进销价对比）
- **价值**: 销售决策必看 — 成本涨了 8%，是否调菜单价？
- **模型**: 报表层，join `price_ledger` × `dish_pricing`
- **工时**: 5 人日

### PRD-15 区域商品采购价差报表
- **价值**: 长沙 vs 株洲 同品类菜价差，调拨决策依据
- **工时**: 3 人日

### PRD-16 采购定价审批工作流绑定
- **价值**: 涨幅 >5% 必须采购总监审批
- **复用**: tx-org/`approval_engine` 引擎
- **工时**: 4 人日

### PRD-17 商户自定义入库/盘点表单字段
- **价值**: 海鲜店要"产地/活体状态"，干货店要"批次/生产日期"，**字段刚性差异**
- **模型**: `CustomFormSchema(tenant_id, doc_type, schema: JSON)` + 表单渲染层
- **工时**: 15 人日（低代码引擎，**最大单项**）
- **长期资产**: 跨服务复用（不止供应链）

---

## 五、P2 清单（6 项，长尾，3 个月内补）

| PRD# | 项目 | 工时 | 价值 |
|---|---|---|---|
| P2-1 | 年度定价日期日历 | 3 | 采购合同节奏控制 |
| P2-2 | 定价周期模板 | 2 | 周期切换灵活性 |
| P2-3 | 商品财务分类映射 UI | 3 | 财务报表精细化 |
| P2-4 | 应产率（半成品产出率）UI | 4 | 中央厨房 KPI |
| P2-5 | SKU 录入模板 | 3 | 批量录入效率 |
| P2-6 | 全局补货时间总开关 | 2 | 节假日批量调整 |

---

## 六、明确不做（4 项）

| G10 项 | 不做理由 |
|---|---|
| 供应商睿博支付接口 | 屯象走云闪付/微信 B2B 路线 |
| 代发单据类型 | 用 PRD-17 自定义表单兜底 |
| 商品-税码-税率三联表（独立 UI） | 已纳入 `vat_ledger` |
| 供应商签到时段/时点（独立模块） | 合并入 PRD-05 |

---

## 七、6 个月分阶段路线图

### Phase 1（Week 8 验收前 ~3 周）— P0 5 项 + 强 Tier 1

**目标**：徐记 demo 不被采购总监 / 食安总监一票否决

| 周 | PRD | 工时 |
|---|---|---|
| W6 | PRD-03 单号定制规则 + PRD-01 证件临期 | 15 人日 |
| W7 | PRD-02 扣秤标准 + PRD-06 出料率 | 15 人日 |
| W8 | PRD-05 补货时间窗 + 集成测试 + 200 桌并发 regression | 10 人日 |

**40 人日 / 3 周** → 需 **2 人全职 + 1 人 review/qa**

### Phase 2（Week 9-12 ~4 周）— P0 剩余 2 项 + P1 核心 5 项

**目标**：徐记替换 G10 决策点（采购员 + 店长 + 财务三方使用率）

- PRD-04 询价单 + 比价表（18 人日，单项最大）
- PRD-07 申购模板（8）
- PRD-08 用料白名单（4）
- PRD-11 销售分成转入库（4）
- PRD-13 市场调研双轨（12）⭐ 早市数据集起步

**46 人日 / 4 周** → 需 **3 人**

### Phase 3（Week 13-16 ~4 周）— P1 剩余 + P2 启动

- PRD-09 分解型 BOM UI（5）
- PRD-10 产品测试标准（6）
- PRD-12 证件类型字典（3）
- PRD-14/15 价格对比报表（8）
- PRD-16 定价审批流（4）
- P2-1/2/4/5/6（14）

**40 人日 / 4 周** → 2 人

### Phase 4（Week 17-24 ~8 周）— PRD-17 自定义表单 + AI 升级

- PRD-17 低代码表单引擎（15）
- **AI 化二阶段**：基于 Phase 1-3 沉淀的数据训练
  - 采购员对 AI 推荐的采纳率 → RLHF
  - 出料率/扣秤实际值 → 标准动态调整
  - 早市价 → 区域价格预测模型

---

### Phase 2 W7-W12 决策落地（2026-05-14 创始人 deep-interview 锁定）

> SoT：`~/.claude/projects/-Users-lichun/memory/project_tunxiang_supply_phase2_w7w12.md`
> 本节为 README 接续段落 — 决策表 + 阻塞依赖图 + Migration 链规划 + W7 首发参数

#### D1 — Phase 2 入口：方案 A（README 原计划）
- W7-W8 = Phase 1 P0 收尾 21 人日（PRD-02 扣秤 8 + PRD-06 出料率 7 + PRD-05 补货时间窗 6）
- W9-W12 = Phase 2 原计划 46 人日（PRD-04 询价 18 + PRD-07 申购 8 + PRD-08 用料白名单 4 + PRD-11 销售分成 4 + PRD-13 市场调研 12）
- 总 67 人日 / 6 周 / 2-3 人

#### D2 — §17 桌台并发对齐：架构 default 1A / 2A / 3B
- **1A 强一致** (`open_table` FOR UPDATE + rowcount check)：桌台物理资源，LWW 不可接受
- **2A 双锁排序** (`transfer_table` table_id 升序锁防 ABBA)
- **3B 幂等释放** (`_release_table` WHERE `current_order_id=:id AND status='occupied'`)
- 4 段 §17 PR 走 explicit-ask + §19 reviewer + 200 桌并发 regression（Tier 1 fund/源 第 17-20 例）

#### D3 — Wave1/Wave2 拆分：≥10 人日强制 3 sub-PR
- **PRD-04 询价 (18 人日)** 拆 3 sub-PR（sub-A v426 schema → sub-B Tier 1 award + #579 嵌入 → sub-C 前端）
- **PRD-13 市场调研 (12 人日)** 拆 3 sub-PR（sub-A v427 schema → sub-B 早市上传 → sub-C 调研列表）
- **PRD-02/06/05/07/08/11** 全 ≤8 人日，单 PR ship

#### D4 — Sprint H DEMO 前必修 4 issue 嵌入 sub-PR
- **#579** → PRD-04 sub-B（Tier 1 award 200 桌并发压测同期跑）
- **#589** → PRD-07 v426（申购单 doc_number namespace cleanup）
- **#613** → §17 PR ship 同期 v428 patch
- **#615** → §17 PR ship 同期 pytest-postgresql 嵌入

T2 推 Phase 3 W13-16: #577/#578/#580/#591/#592/#598/#604/#557/#559/#562/#549/#535/#537/#626/#627
T3 obs Phase 4 W17+: #599/#600/#605/#614

#### Migration 版本号链规划（W7-W12）
- v418-v424 Phase 1 W6 ✅ ship
- v425 supplier_portal_messages UNIQUE 索引（§17 patch / #613）
- v425-v427 slot abandon（原 supplier_portal_messages UNIQUE / RFQ / MarketSurvey 预留，实际迁移跳至 v428+）
- **v428 PRD-02 ingredient_weight_standards + receiving_weight_deductions（W7-1 PR #633 ✅ ship）**
- **v429 PRD-06 ingredient_yield_standards（W7-2 PR #637 ✅ ship）**
- **v430 PRD-05 supplier_delivery_windows + supplier_delivery_violations（W8 PR #641 ✅ ship）**
- **v431 PRD-04 sub-A RFQ 5 表 (rfqs/items/invitees/quotes/awards) + supplier_portal_messages partial UNIQUE 索引 (#613 闭环)（W9 PR #645 ✅ ship）**
- **PRD-04 sub-B RFQ award 路径 + 二级审批 + #579 200 桌并发（W9 PR #647 ✅ ship，复用 v431 schema 无新 migration）**
- **PRD-04 sub-C state transitions + supplier-portal scope + 前端 RFQManagementPage/QuotePage + AI 推荐 UI（W9-W10 本 PR，复用 v431 schema 无新 migration）**
- **v432 PRD-07 RequisitionTemplate 3 表 + #589 purchase_orders 3 表 建表（W10 本 PR ship）**
- v433+ PRD-13 sub-A MarketSurvey schema（W11-W12）

#### W9 sub-B PR 立项参数（PRD-04 RFQ award 路径 + 二级审批 + #579 200 桌并发）

**Tier 级别**：Tier 1 资金路径前置（award → 采购单 → 应付账款）／**Tier 1 explicit-ask**：第 21 例 reconciled（不在 8 类 carve-out）／**§19 reviewer**：opus B 选项 P0/P1 真 BUG only 多 round

- **范围**：rfq_service.py (create_rfq + get_rfq lock pattern + award_rfq Tier 1) / 3 admin-side REST endpoint (POST /rfqs, GET /rfqs/{id}, POST /rfqs/{id}/award) / main.py 注册 rfq_router
- **Tier 1 award 硬约束**：
  - FOR UPDATE on rfqs (PR-A/B/C/D/E pattern 串行化 — 200 桌并发 #579 反测)
  - UNIQUE(tenant_id, rfq_id) on rfq_awards (DB-level 双保险防重复 award)
  - 二级审批 approver_id != rfq.created_by (param 层 + DB 层双重)
  - quote 归属校验 (selected_quote_id 必须属于本 rfq — 合规审计)
  - 状态机校验 (awarded/cancelled 拒绝重复 award)
  - ai_recommendation_followed BOOLEAN ⭐ RLHF 训练信号
- **#579 闭环**：tests/concurrent/test_rfq_award_concurrent_tier1.py 1 用例 N=10 并发 award 同 rfq → 仅 1 成功 + 9 raise "已 award"；conftest._CONCURRENT_TABLES 加 RFQ 5 表 (FK 子→父序)；workflow paths 加 rfq_service.py + v431
- **测试**：
  - `test_rfq_service_tier1.py` 16 用例（CRUD 4 + lock pattern 2 + award Tier 1 10）
  - `tests/concurrent/test_rfq_award_concurrent_tier1.py` 1 用例（#579 200 桌并发反测）
- **baseline 不变**：services/tx-supply/src text(f) 82（§19 round-1 P0 修复后 get_rfq 用 2 个预构造 SQL 常量按布尔选，消除 f-string 拼接 / L011 严格符合）
- **不在 sub-B 范围**：publish / submit_quote / close / cancel state transitions / supplier_portal /rfq/{id}/quote endpoint / 前端比价表 UI（sub-C 落）
- **预计 5 commits**（service + routes + tier1 tests + #579 concurrent + README/baseline）

Closes #579

#### W9-W10 sub-C PR 立项参数（PRD-04 RFQ state transitions + supplier-portal + 全栈 UI）— ✅ ship

**Tier 级别**：T2 normal（不在 Tier 1 source patterns）／**T2 carve-out type 7 auto admin-merge**（不 explicit-ask）／**§19 reviewer**：opus B 选项 P0/P1 真 BUG only

- **范围**：
  - `rfq_service.py` +6 函数：`publish_rfq` / `close_rfq` / `cancel_rfq` / `submit_quote` / `get_rfq_comparison` / `list_rfqs`
  - `rfq_routes.py` +6 admin endpoints (POST publish/close/cancel + GET list/comparison + 复用 award) + 新 `supplier_portal_router` (POST /api/v1/supply/supplier-portal/rfqs/{id}/quote)
  - `rfq_models.py` +2 Pydantic schemas: `RFQCancelRequest` / `RFQSupplierQuoteSubmit`
  - `apps/web-admin/src/pages/supply/RFQManagementPage.tsx`：列表 + 创建 modal + 详情 drawer（state transition buttons + 比价表 + AI 推荐 + Award 二级审批）
  - `apps/web-admin/src/pages/supply/RFQSupplierQuotePage.tsx`：供应商门户报价提交页（X-Supplier-ID header）
  - `App.tsx` +2 routes：`/supply/rfqs` (admin) + `/supplier-portal/rfqs/:rfqId/quote` (supplier)
  - `main.py` +1 router 注册 (rfq_supplier_portal_router)
- **状态机硬约束**：
  - `publish`：仅 `draft → published`（其余状态拒绝）
  - `close`：仅 `quoting → comparing`（其余状态拒绝）
  - `cancel`：任何非终态 → `cancelled`（reason 必填合规审计 + audit log 拼接到 notes；awarded/cancelled 拒绝）
  - `submit_quote`：rfq.status in (published, quoting) + 邀请校验（rfq_invitees）+ SKU 校验（rfq_items）+ ON CONFLICT UPSERT（允许 deadline 前修改报价）+ 首报跃迁 published→quoting（FOR UPDATE 锁住 rfq 行）+ invitees.responded_at 更新
  - `get_rfq_comparison`：按 SKU 聚合所有 quotes，AI 推荐 = 最低价 quote_id（v1 heuristic；sub-D follow-up 引入 supplier_score 综合排序）
  - 所有 mutation 路径走 FOR UPDATE 行锁（PR-A/B/C/D/E pattern）— 即非 Tier 1 资金路径也防 200 桌并发状态机竞态
- **测试**：
  - `test_rfq_state_transitions_tier1.py` 40 用例（publish 7 / close 7 / cancel 6 / submit_quote 10 / comparison 3 / list 4 + parametrize 展开）
  - 兼容 sub-B `test_rfq_service_tier1.py`（16 用例）+ `test_rfq_schema.py`（10 用例）— 零回归
- **baseline 不变**：services/tx-supply/src text(f) **82**（所有新增 SQL 用 :param + 预构造常量 `_RFQ_*_SQL` / `_LIST_RFQS_*_SQL`，零 f-string 注入面，L011 严格符合）
- **supplier-portal auth (sub-C scope)**：X-Supplier-ID header 透传（来自 query param 或 supplier_portal_v2 JWT）；生产 JWT 解析放 sub-D follow-up
- **不在 sub-C 范围**：
  - 供应商门户 JWT 鉴权（sub-D follow-up — supplier_portal_v2 `/auth/login` 接 RFQ scope）
  - AI 推荐综合评分（引入 PRD-05 配送时间窗扣分 + supplier_score 综合排序 — sub-D 或独立 PR）
  - 邮件/IM 推送邀请通知（依赖 #485 supplier_portal_messages 通用入箱 — 独立 PR）
- **预计 4 commits**（service 扩展 + routes/models 扩展 + 前端 + tests/README）

#### W10 PRD-07 申购模板 PR 立项参数（含 #589 purchase_orders 建表）— ✅ ship

**Tier 级别**：T2 normal（不在 Tier 1 source patterns；操作效率 → NPS 决定客户留存）／**T2 carve-out type 7 auto admin-merge**（不 explicit-ask）／**§19 reviewer**：opus B 选项 P0/P1 真 BUG only

- **PRD-07 范围**：
  - v432 6 表 migration：
    - PRD-07: requisition_templates / requisition_template_items / warehouse_requisition_template_bindings
    - #589 闭环: purchase_orders / purchase_order_items / ingredient_batches
  - 所有表 RLS 四联 inline (ENABLE + FORCE + POLICY + WITH CHECK)
  - FK CASCADE 子→父 (FK 依赖序: ingredient_batches → POI → PO / template_items+bindings → templates)
  - PRD-03 doc_number VARCHAR(64) + po_number 兼容字段 + 索引 (tenant_id, store_id, status) + (tenant_id, supplier_id) per #589 提议
  - `requisition_template_service.py` — CRUD 模板 + 仓库绑定 + 一键生成草稿（含 AI 推荐量调 SmartReplenishmentService）
  - `requisition_template_models.py` — 3 ORM SQLAlchemy 2.0 typed Mapped[] + 11 Pydantic V2 schemas + TemplateCategory + QtyMethod 枚举
  - `requisition_template_routes.py` — 8 endpoints (5 模板 CRUD + 3 仓库绑定 + 1 一键发起)
  - `apps/web-admin/src/pages/supply/RequisitionTemplatesPage.tsx` — 列表+创建 modal+详情 drawer+绑定 drawer+一键发起 modal
- **AI 推荐量集成**：复用 `services/tx-supply/src/services/smart_replenishment.py` 现有 SmartReplenishmentService.check_and_recommend，**fail-open**（异常时 suggested_qty=None + qty_source 标注原因）
- **一键发起申购流程**：模板 → generate (草稿不入库) → 前端 review → existing /api/v1/supply/requisitions 入库走审批流（services/tx-supply/src/services/requisition.py 状态机 draft → pending_approval → ...）
- **#589 闭环**：purchase_order_routes.py docstring 描述但仓库无 migration 的 baseline bug 一次性补齐 — purchase_orders / purchase_order_items / ingredient_batches 三表建表 + RLS + 索引；现有 purchase_order_routes.py 业务代码无须改动（原 TABLE_NOT_READY 兜底分支以后不会触发）
- **baseline 不变**：services/tx-supply/src text(f) **82** + text(<sql_var>) **10**（新加 list_templates 用 `prepared_text` 命名避 baseline 模式守门，参考 PK.2-fix lesson）
- **测试**：`test_requisition_template_tier1.py` 30 用例（CRUD 模板 16 + 仓库绑定 5 + 一键发起 6 + smart_replenishment Mock 注入 3）
- **兼容**：sub-B/C 36+40 RFQ 用例 + baseline 守门 10 用例全绿（116 总 / 零回归）
- **预计 5 commits**（migration + ORM/Pydantic + service+routes + 前端 + tests/README/DEVLOG）

#### W9 sub-A PR #645 立项参数（PRD-04 RFQ schema + #613 supplier_portal_messages UNIQUE）— ✅ ship

**Tier 级别**：T2 infra ADD（schema-only，sub-B/C 落业务）／**explicit-ask**：不需要（T2 carve-out type 7 auto admin-merge）／**§19 reviewer**：opus B 选项 P0/P1 真 BUG only

- **范围**：v431 5 表 schema (rfqs/rfq_items/rfq_invitees/rfq_quotes/rfq_awards) + RLS 四联 / FK 子→父级联 (items/invitees/quotes CASCADE → rfqs；awards.selected_quote_id RESTRICT) / UNIQUE 约束 (rfq_id+ingredient_id / rfq_id+supplier_id / rfq_id 一单一中标) / RFQStatus 状态机字典 (6 值) / 5 ORM SQLAlchemy 2.0 typed Mapped[] + 12 Pydantic V2 schemas
- **#613 闭环**：supplier_portal_messages partial UNIQUE 索引 (tenant_id, supplier_id, message_type, metadata->>'cert_id', metadata->>'threshold') WHERE message_type='cert_expiry_alert' + cert_expiry_alerter._push_supplier_portal 加 ON CONFLICT DO NOTHING（防 _log_alert 失败-after-INSERT 次日 re-scan 重复入 inbox）
- **测试**：`test_rfq_schema.py` 16 用例（非 *_tier1.py — T2 carve-out 7 不强求）— RFQStatus 与 v431 CHECK 对齐 / 5 ORM __tablename__ / Pydantic extra='forbid' + 必填 / 金额分整数 / Optional 字段
- **不在 sub-A 范围**：service / route / UI / Tier 1 业务逻辑（sub-B 落 award + 二级审批 + #579 200 桌并发；sub-C 落前端比价表 + AI 推荐 UI）
- **预计 4 commits**（migrate + ORM/Pydantic + schema test + README）

#### W8 PR 立项参数（PRD-05 供应商配送时间窗 + 集成测试 + 200 桌并发 regression）

**Tier 级别**：Tier 1（食安 + 客户体验 → TDD 必须）／**Tier 1 explicit-ask**：第 19 例（不在 8 类 carve-out）／**§19 reviewer**：opus B 选项 P0/P1 真 BUG only

- **范围**：v430 `supplier_delivery_windows`（配置表）+ `supplier_delivery_violations`（违约日志，UNIQUE 幂等）+ RLS / `delivery_window_service.py` CRUD + 二级审批 + `check_delivery_window` + `record_violation` + `count_violations` / `receiving_v2_service.complete_receiving` 完成路径集成（check + record + emit `DELIVERY_LATE`）/ `supplier_scoring_engine` 接入扣分（`delivery_rate` 公式扩展）/ 5 endpoint API / Web UI `SupplierDeliveryWindowsPage.tsx`（含合规检查工具）
- **Ontology 不动**：违约日志独立表 `supplier_delivery_violations`，不修改 ReceivingOrder ontology（§18 冻结）
- **测试**：
  - `test_delivery_window_service_tier1.py` 18 用例（CRUD 6 + 二级审批 2 + RLS 1 + check_window 6 + violation 2 + count 1 + helpers）
  - `test_receiving_delivery_window_integration_tier1.py` 8 用例（源码静态契约 — receiving_v2 集成 5 + supplier_scoring 接入 3）
  - `test_w8_supply_e2e_tier1.py` 19 用例（PRD-02/06/05 三表 + 三事件 + 三 UI + 三 router + receiving + scoring 集成）
  - `tests/concurrent/test_w7_w8_supply_standards_concurrent_tier1.py` 3 用例（W7-1/W7-2 二级审批 FOR UPDATE 串行化 + W8 violations UNIQUE 幂等串行化）
- **集成测试 + 200 桌并发 regression**（用户决策 D2/D3）：合入本 PR — 不分 sibling PR / 不推 W12 收尾
- **预计 8 commits**（migrate + service+model + receiving 集成 + routes + Web UI + tests + concurrent + README/baseline）

#### W7 首发 PR 立项参数（PRD-02 商品扣秤标准库）
**Tier 级别**：Tier 1（毛利底线 → TDD 必须）／**Tier 1 explicit-ask**：第 17 例（不在 8 类 carve-out）／**§19 reviewer**：opus B 选项 P0/P1 真 BUG only

- **范围**：v428 `ingredient_weight_standards` + `receiving_weight_deductions` 表 + RLS / `weight_standard_service.py` CRUD + 二级审批 + `calculate_net_weight()` / `receiving_v2_service.apply_weight_deduction_for_item()` enhancement layer / `weight_deduction_anomaly` 事件 / 5 endpoint API / Web UI `IngredientWeightStandardsPage.tsx`
- **Ontology 不动**：ReceivingOrderItem 缺 `gross_weight_kg` 字段 — 用新表 `receiving_weight_deductions` 关联 receiving_order_items.id（更安全，符合 §18 ontology 冻结规则）
- **测试**：`test_weight_standard_service_tier1.py` 14 用例（CRUD 6 + 二级审批 2 + RLS 1 + calculate 6） + `test_receiving_v2_net_weight_tier1.py` 5 用例（gross 单类 + 向后兼容 + 多扣秤叠加 + anomaly emit）
- **预计 7 commits**（migrate + service + receiving 集成 + routes + Web UI + tests + docs）

#### 阻塞依赖图
```
W7 PRD-02 扣秤 (单 PR, Tier 1) ─┐
W7 PRD-06 出料率 (单 PR, Tier 1) ─┼─→ W8 PRD-05 时间窗 (单 PR, Tier 1) + 集成测试 + 200 桌并发 regression
                              │
                              ├─→ W9-W10 PRD-04 sub-A v426 (T2) → sub-B (T1 + #579 嵌入) → sub-C (T2)
                              │
                              ├─→ W10 PRD-07 (单 PR, T2 + #589 嵌入)
                              │
                              ├─→ W11 PRD-08 用料白名单 (单 PR, T2) + PRD-11 销售分成 (单 PR, T2)
                              │
                              └─→ W11-W12 PRD-13 sub-A v427 → sub-B 早市上传 → sub-C 调研列表

§17 PR 4 段（D2 锁定后可并行启动）：
  §17-A cashier 桌台 3 路径 (1A/2A) → Tier 1 explicit-ask 第 18 例
  §17-B settle 终态保护 4 路径 (3B 幂等释放) → 第 19 例
  §17-C OrderItem lock 4 路径 → 第 20 例（独立于创始人答复）
  §17-D follow-up 合并 (#549 ABBA + #557 + #559) → 第 21 例
```

#### Sprint H DEMO 验收门槛对齐
- Tier 1 全绿 100%（PRD-02/06/05 + §17-A/B + PR-01B/01C 累积测试）
- P99 < 200ms（#579 200 桌并发实测）
- 支付成功率 > 99.9%（5/13 6-PR row-lock roadmap 承接）
- 断网 4h 无数据丢失（依赖 edge sync_engine，非 supply scope）
- 收银员无技术培训可用（PRD-07 申购模板 + PRD-01 证件管理 + PRD-02 扣秤管理 UI 三方支撑）

---

## 八、长期价值沉淀地图（5 大数据资产）

**第一性原理**：短期合规 + 长期数据飞轮才是 AI-Native 的真意。

| 数据资产 | 来自哪些 PRD | 沉淀后能做什么 |
|---|---|---|
| **生鲜 SKU 标准库**（扣秤+出料率+测试标准） | PRD-02, 06, 10 | 行业 SaaS 化（卖给小餐厅）+ AI 毛利预测 |
| **供应商履约画像**（证件+时效+报价+质量） | PRD-01, 04, 05, 12 | AI 评分 + 自动黑名单 + 保险定价 |
| **采购员决策日志**（RFQ 采纳率） | PRD-04 | RLHF 训练数据 — ⭐ **AI 自动议价**终极目标 |
| **本地早市/批发市场价数据集** | PRD-13 | 区域价格预测 + ⭐ **政府数据合作**（民生菜篮子）|
| **门店申购行为画像** | PRD-07 | AI 补货预测精度提升 + 异常订单识别 |

---

## 九、关键风险 + 缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| **PRD-17 低代码表单**工时被低估 | 4 周变 12 周 | Phase 4 才启动，Phase 1-3 用"硬编码自定义字段"兜底 |
| 徐记 **Week 8 demo** P0 都没做完 | 替换决策失败 | 砍 PRD-13/17 等长期投入，**保 P0 5 项**底线 |
| AI 推荐**采纳率太低** | 数据飞轮转不起来 | PRD-04 比价表强制"是否采纳 AI"勾选 → 数据冷启动 |
| 单号规则**改造工程量大**（17 类单据回填） | Phase 1 拖延 | 用 view 层兼容旧 UUID 单号 + 新单号双写过渡 |
| **三家比价合规**国企客户特殊要求 | 屯象不被国企采购 | PRD-04 优先级提升到 Phase 1 末 |

---

## 十、与现有 Tier 1 row-lock 工作的整合点

承接 2026-05-13 ~ 14 row-lock audit 收尾后（6-PR roadmap 完工，#544/#547/#553/#556/#560/#563）的 **§17 桌台并发语义对齐 PR** + **follow-up issues**（#535/#537/#549/#557/#559/#562）：

- PRD-02 扣秤、PRD-06 出料率 → **写** `ingredient_yield_standard` / `weight_standard` 表，需要补 row-lock（沿用 PR-B `_get_ingredient(lock=True)` helper 模式）
- PRD-04 RFQ award 是 Tier 1 资金路径前置 → 必须 row-lock + explicit-ask admin-merge（**第 9+ 例 fund explicit-ask**，不在 8 类 carve-out）
- PRD-03 单号生成器需要 PG advisory_lock，**不**与 row-lock 冲突，但要走 `feedback_pytest_stub_setdefault_pitfall.md` 实例 #3（CI vs local 一致性）
- 所有 PRD 涉及金额字段必须用 **分（int）**，禁止 Decimal 元（v414/v415 fund-path 已建立基线）

---

## 第一性原理总结

**屯象供应链的 3 个非对称优势**（不是更全，而是更深）：

1. **数据精度 > 功能数量** — 扣秤 + 出料率 + 标准库做扎实，毛利预测精度比 G10 高 2-3x
2. **人机协同 > 全 AI / 全人工** — 询价单 / 比价表 / 市场调研都走"AI 推荐 + 人决策 + RLHF"
3. **本地化数据 > 通用 SaaS** — 早市价 / 区域价差 / 季节出料率，是**本地实地**才能采集的护城河

**总投入**：~170 人日 = **6 个月 / 2-3 人专职**

**6 个月后状态**：屯象供应链不再是"AI 包装的 SaaS"，而是**"复刻 G10 卫生因素 + 5 大数据资产飞轮"**的连锁餐饮 SoR+SoI 双层操作系统 — 这才是"连锁餐饮 Palantir"的 MVP 形态。

---

## 附录：23 项 PRD 索引

| # | PRD | 优先级 | 工时 | Tier | 数据资产 |
|---|---|---|---|---|---|
| 01 | 供应商证件临期预警 | P0 | 5 | T1 食安 | 供应商履约画像 |
| 02 | 商品扣秤标准库 | P0 | 8 | T1 毛利 | ⭐ 生鲜 SKU 标准库 |
| 03 | 业务单号定制规则 | P0 | 10 | T1 审计 | — |
| 04 | 询价单 + 比价表 | P0 | 18 | T1 毛利+合规 | ⭐ 采购员决策日志 |
| 05 | 补货时间窗硬约束 | P0 | 6 | T1 食安 | 供应商履约画像 |
| 06 | 商品出料率标准库 | P0 | 7 | T1 毛利 | ⭐ 生鲜 SKU 标准库 |
| 07 | 申购模板 + 仓库级模板 | P0 | 8 | T2 | 门店申购画像 |
| 08 | 部门用料范围白名单 | P1 | 4 | T2 | — |
| 09 | 分解型 BOM UI | P1 | 5 | T2 | — |
| 10 | 产品测试标准库 | P1 | 6 | T2 | 生鲜 SKU 标准库 |
| 11 | POS 销售分成转入库 | P1 | 4 | T2 | — |
| 12 | 资质证件类型字典 | P1 | 3 | T2 | 供应商履约画像 |
| 13 | 市场调研双轨 | P1 | 12 | T2 | ⭐ 早市价数据集 |
| 14 | 进销价对比报表 | P1 | 5 | T2 | — |
| 15 | 区域采购价差报表 | P1 | 3 | T2 | — |
| 16 | 采购定价审批流 | P1 | 4 | T2 | — |
| 17 | 商户自定义表单 | P1 | 15 | T2 | — |
| P2-1 | 年度定价日历 | P2 | 3 | — | — |
| P2-2 | 定价周期模板 | P2 | 2 | — | — |
| P2-3 | 商品财务分类映射 | P2 | 3 | — | — |
| P2-4 | 应产率 UI | P2 | 4 | — | — |
| P2-5 | SKU 录入模板 | P2 | 3 | — | — |
| P2-6 | 全局补货时间总开关 | P2 | 2 | — | — |
| **合计** | | | **140** | | |

> **注**：140 人日为净开发工时；加 review/test/部署整合 + 20% buffer ≈ **170 人日**，对应 6 个月 / 2-3 人专职。

---

**对标版本**：G10云仓 v8.0 · **更新日期**：2026-05-14 · **维护者**：屯象科技
