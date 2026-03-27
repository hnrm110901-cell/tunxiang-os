# 屯象OS 2030开发计划（合并版）

> 合并自：tunxiang-os-dev-blueprint-2030.docx + tunxiang-os-detail-spec.docx
> 基于 V1(637K行) + V3(73K行) 两个代码库深度审计
> 当前 V3 状态：v5.1.0, 14域服务, 25 Agent, 75+页面, 1100+测试

---

## 一、架构重组：12微服务 → 4战斗单元

### 现状(V3 v5.1.0)
```
gateway / tx-trade / tx-menu / tx-member / tx-supply / tx-finance
tx-org / tx-analytics / tx-agent / tx-ops / tx-growth / tx-intel
+ mcp-server
```

### 目标(V4 4战斗单元)
```
tx-core   = tx-trade + tx-menu + tx-member + tx-finance
            + 支付对账(V1迁入) + 宴会(V1迁入) + 排队(V1迁入) + 日结(V1迁入)

tx-ops    = tx-org + tx-supply + tx-ops
            + 智能排班(V1迁入) + 薪资完整版(V1迁入) + 考勤(V1迁入) + 损耗完整版(V1迁入)

tx-brain  = tx-agent + tx-analytics + tx-growth + tx-intel
            + Neo4j本体层(V1迁入) + 成本真相引擎(V1迁入) + 推理引擎(V1迁入)
            + 语音全栈(V1迁入) + CFO驾驶舱(V1迁入)

gateway   = gateway (路由/认证/限流/Webhook)
```

### 迁移原则
- V3架构保留，V1业务代码迁入
- 不重写，是融合：每个文件有明确的V1来源和V3目标位置
- 迁移代码时同步迁移V1对应测试

---

## 二、5大关键决策

| # | 决策 | 方案 | 理由 |
|---|------|------|------|
| 1 | POS终端 | 5核心页Compose原生 + 其余WebView | 收银必须原生，其余React复用 |
| 2 | 边缘策略 | 放弃Mac mini，云优先，POS本地Room DB | Phase 1-2不需要边缘，Room DB够用 |
| 3 | Ontology | PG RLS(事务层) + Neo4j(知识关系层)双层 | RLS管事务ACID，Neo4j管因果推理 |
| 4 | Agent放权 | 3级：建议→自动可回滚→完全自主 | 渐进建立客户信任 |
| 5 | V1迁移 | 18,490行核心业务代码迁回V3 | 每行代码有明确来源，不是重写 |

---

## 三、12 Sprint 开发计划（每Sprint 4周）

### Sprint 1-2：收银核心闭环 (Week 1-8)

**验收：W8 尝在一起门店用屯象OS完成一整天收银（零品智依赖）**

#### S1 (W1-4)
| Wk | 任务 | 代码来源 | 验收 |
|----|------|---------|------|
| 1-2 | Compose POS原生: 开台页+点单页+结算页 | V3 android-shell + 新写Compose | 商米T2可开台、点菜、结账 |
| 3-4 | tx-core后端: 订单引擎+菜品+收钱吧支付 | V3 tx-trade + tx-menu + 新写支付 | 微信扫码→订单完成→打印小票 |

#### S2 (W5-8)
| Wk | 任务 | 代码来源 | 验收 |
|----|------|---------|------|
| 5-6 | KDS+服务员PWA+Room DB离线 | V3 web-kds + web-crew + 新写Room | 3端联动+断网收银 |
| 7-8 | 多支付拆单+折扣引擎+日结 | 新写 + V1 daily_settlement迁入 | 1单多付+整单折+日结完整 |

**DB迁移 v002**: payments(补trade_no索引) + payment_records + reconciliation_batches + reconciliation_diffs + tri_reconciliation_records + store_daily_settlements

**API端点 (Sprint 1-2)**:
- POST /api/v1/orders (开台建单)
- POST /api/v1/orders/{id}/items (加菜，支持称重/时价)
- PUT /api/v1/orders/{id}/items/{item_id} (改菜)
- DELETE /api/v1/orders/{id}/items/{item_id} (退菜)
- POST /api/v1/orders/{id}/discount (折扣，触发毛利底线校验)
- POST /api/v1/orders/{id}/settle (结账，多支付拆单)
- POST /api/v1/orders/{id}/cancel (取消)
- GET /api/v1/orders/{id} (详情)
- GET /api/v1/tables?store_id= (桌台列表)
- PUT /api/v1/tables/{id}/status (状态变更)

**Compose POS 5页规格**:
| 页面 | 功能 | 外设 | 离线 |
|------|------|------|------|
| 开台页 | 桌台地图+状态+开台+人数+茶位费 | 无 | Room缓存桌台 |
| 点单页 | 菜品分类+搜索+称重/时价+口味+送KDS | 称重+打印 | 菜品库Room全量缓存 |
| 结算页 | 汇总+折扣+多支付+扫码+会员余额+挂账+小票 | 扫码+打印+钱箱 | 现金可完全离线 |
| 交接班页 | 班次汇总+支付分布+现金盘点+交接确认 | 钱箱+打印 | Room本地计算 |
| 日结页 | 全天营收+客单+翻台+异常+店长说明+提交 | 打印 | Room本地汇总 |

**Room DB实体**: LocalOrder, LocalOrderItem, LocalPayment, LocalTableState, LocalDishCache, SyncQueue
**同步策略**: SyncQueue FIFO + WorkManager指数退避重试(最多3次) + 菜品5min增量同步

---

### Sprint 3-4：交易完整+宴会+对账 (Week 9-16)

**验收：W16 完整交易闭环(预订→排队→点单→出餐→结账→日结→对账) + 宴会 + 2家客户**

#### S3 (W9-12)
| Wk | 任务 | 代码来源 | 验收 |
|----|------|---------|------|
| 9-10 | 预订+排队+宴会全链路 | V1 queue(547)+reservation(336)+banquet_*(1,815)迁入 | VIP预订→排队→叫号→入座 |
| 11-12 | 支付三层对账体系 | V1 payment_reconcile(694)+tri(691)+bank(422)迁入 | 微信CSV→自动匹配→差异报告 |

#### S4 (W13-16)
| Wk | 任务 | 代码来源 | 验收 |
|----|------|---------|------|
| 13-14 | 外卖平台对接+会员Golden ID | V3 adapters(eleme/meituan/douyin) + V3 tx-member | 美团/饿了么订单自动入屯象 |
| 15-16 | 稳定性+第二家客户接入 | Bug fix + 最黔线或尚宫厨接入 | 连续14天零交易失败 |

**DB迁移 v003**: reservations + queues + banquet_halls + banquet_leads + banquet_orders + banquet_contracts + menu_packages

**API端点 (Sprint 3-4)**:
- POST/PUT /api/v1/reservations (预订CRUD + 7状态机)
- POST /api/v1/queues (排队) + POST /api/v1/queues/{id}/call (叫号)
- POST /api/v1/banquet/leads (宴会线索)
- POST /api/v1/banquet/orders (宴会订单+定金)
- POST /api/v1/reconcile/import (CSV导入)
- POST /api/v1/reconcile/run (执行对账)
- POST /api/v1/reconcile/tri (三角对账)
- GET /api/v1/daily-settlement + POST confirm

---

### Sprint 5-8：运营引擎+AI首发 (Week 17-32)

**验收：W32 运营全闭环(排班→薪资) + AI首发 + 3家客户 + 开始营收**

| Sprint | 任务 | 代码来源 | 验收 |
|--------|------|---------|------|
| S5 | BOM联动+采购+出入库+盘点+损耗 | V3 tx-supply + V1 waste_guard(579)迁入 | 食材成本自动→毛利实时 |
| S6 | 智能排班+考勤+薪资全闭环 | V1 smart_schedule(1993)+attendance(635)+payroll(928)迁入 | 自动排班→考勤→薪资→工资条 |
| S7 | discount_guard Agent上线+企微推送 | V3 tx-agent启用 | 折扣异常5min内推送店长 |
| S8 | 离职结算+门店P&L自动生成 | V1 settlement(612)迁入+新写P&L | 每日自动门店利润表 |

**DB迁移 v004**: attendance_rules + clock_records + daily_attendance + payroll_batches + payroll_items + leave_requests + leave_balances + settlement_records

**V1迁入文件(S5-S8)**:
- smart_schedule_service.py (1,993行) → tx-ops
- payroll_service.py (928行) → tx-ops
- attendance_engine.py (635行) → tx-ops
- settlement_service.py (612行) → tx-ops
- waste_guard_service.py (579行) → tx-ops

---

### Sprint 9-12：智能内核+Voice+2030 (Week 33-48)

**验收：W48 Neo4j+Voice+CFO驾驶舱+2030就绪**

| Sprint | 任务 | 代码来源 | 验收 |
|--------|------|---------|------|
| S9 | Neo4j本体层恢复+PG→Neo4j同步 | V1 ontology(2,369)全层迁入tx-brain | 菜品→BOM→食材因果链可查询 |
| S10 | cost_truth_engine+reasoning_engine | V1 cost_truth(560)+reasoning(530)迁入 | "上周酸菜鱼毛利多少"精准回答 |
| S11 | Voice AI: 语音下单+语音查询 | V1 voice_*(1,307)迁入+Whisper v3 | "三号桌加一份酸菜鱼微辣"直接下单 |
| S12 | CFO驾驶舱+多品牌合并+2030基础 | V1 cfo_dashboard(550)+新写合并 | 集团看全品牌财务全貌 |

**Neo4j恢复(7文件, 2,369行)**:
| 文件 | 行数 | 功能 |
|------|------|------|
| schema.py | 83 | 11节点+15关系枚举 |
| bootstrap.py | 175 | 约束和索引初始化 |
| repository.py | 847 | Neo4j CRUD封装 |
| data_sync.py | 765 | PG→Neo4j CDC同步 |
| reasoning.py | 229 | 因果链推理 |
| models.py | 186 | Pydantic模型 |
| cypher_schema.py | 46 | Cypher模板 |

**同步机制**: PG写→LISTEN/NOTIFY→Redis Stream→Neo4j Worker, 延迟<5秒

---

## 四、V1→V3 迁移总表（18文件, 14,397行）

| # | V1文件 | 行数 | V3目标 | Sprint |
|---|--------|------|--------|--------|
| 1 | payment_reconcile_service | 694 | tx-core/reconcile/ | S3 |
| 2 | tri_reconcile_service | 691 | tx-core/reconcile/ | S3 |
| 3 | bank_reconcile_service | 422 | tx-core/reconcile/ | S3 |
| 4 | banquet_planning_engine | 751 | tx-core/banquet/ | S3 |
| 5 | banquet_lifecycle_service | 641 | tx-core/banquet/ | S3 |
| 6 | banquet_sales_service | 423 | tx-core/banquet/ | S3 |
| 7 | queue_service | 547 | tx-core/ | S3 |
| 8 | daily_settlement_service | 165 | tx-core/ | S2 |
| 9 | smart_schedule_service | 1,993 | tx-ops/ | S6 |
| 10 | payroll_service | 928 | tx-ops/ | S6 |
| 11 | attendance_engine | 635 | tx-ops/ | S6 |
| 12 | settlement_service(离职) | 612 | tx-ops/hr/ | S8 |
| 13 | waste_guard_service | 579 | tx-ops/ | S5 |
| 14 | cost_truth_engine | 560 | tx-brain/ | S10 |
| 15 | reasoning_engine | 530 | tx-brain/ | S10 |
| 16 | cfo_dashboard_service | 550 | tx-brain/ | S12 |
| 17 | voice_*(3文件) | 1,307 | tx-brain/voice/ | S11 |
| 18 | ontology(7文件) | 2,369 | tx-brain/ontology/ | S9 |

---

## 五、Agent整合 + 3级放权

### 整合策略
保留V3的Master+Skill架构，把V1深度Agent的业务逻辑补入V3 Skill

| 域 | V3 Skill(保留) | V1补入内容 | Sprint |
|----|---------------|-----------|--------|
| 折扣守护 | discount_guard(160行) | 已完整 | S7启用 |
| 库存预警 | inventory_alert(350行) | V1更深的安全库存算法 | S5 |
| 菜品工程 | menu_advisor(341行) | V1新品研发+四象限 | S10 |
| 私域运营 | private_ops(275行) | V1心理细分+裂变(1,035行) | S8 |
| 宴会智能 | 无(待新增) | V1自动报价+跟进 | S4 |
| 排班智能 | serve_dispatch(283行) | V1客流预测驱动排班 | S6 |
| 培训智能 | 无(待新增) | V1损耗关联培训推荐 | S10 |
| 食材雷达 | ingredient_radar(313行) | V1供应商可靠度评分 | S9 |

### 3级放权机制（新增到BaseAgent）
```python
# agent_level: 1=建议(S7默认) / 2=自动+可回滚 / 3=完全自主(2028+)
# rollback_window: Level 2的30分钟回滚窗口
# decision_log记录level: "Level 1: 建议将周三中班从6人减到4人，预计节省¥320"
```

---

## 六、2030可演进性设计

| 架构决策 | 当前基础 | 2030演进 |
|---------|---------|---------|
| 多区域联邦 | V3 RLS四层治理 + 新增region_id | 50+店时CockroachDB替换PG |
| 多业态功能集 | V3 business_type + Feature Flag | 自定义业态模板 |
| 多收入渠道 | V3 sales_channel扩展8种 | 预制菜/大厨到家/食材电商 |
| Agent放权 | 3级放权机制 | 跨门店Federated Learning |
| 开放平台 | V3 Forge + MCP Server | Plugin Marketplace |
| 国际化 | 金额存分 + 新增currency_code | 多语言/多币种/多税制 |

---

## 七、测试策略

| 阶段 | V1迁移测试 | 新增测试 | 目标覆盖率 |
|------|-----------|---------|-----------|
| S1-2 | 无(新写) | Compose离线测试+多支付拆单+RLS隔离 | ≥80% |
| S3-4 | reconcile+banquet+queue | 宴会状态机+对账差异 | ≥80% |
| S5-8 | schedule+payroll+attendance | Agent真实决策验证 | ≥80% |
| S9-12 | ontology+reasoning+voice | Neo4j因果链+语音E2E | ≥80% |

---

## 八、里程碑验收标准

| Week | 验收 | 客户 |
|------|------|------|
| **W8** | 尝在一起1家门店完整一天收银（零品智） | 1家 |
| **W16** | 预订→排队→收银→日结→对账全闭环+宴会 | 2家 |
| **W32** | 运营全闭环+AI首发(折扣守护)+门店P&L | 3家+营收 |
| **W48** | Neo4j+Voice+CFO驾驶舱+2030就绪 | 3家+稳定营收 |

---

## 九、一句话总结

> V1有业务没架构，V3有架构没业务。继续开发的本质是：在V3的4战斗单元架构上，把V1的18,490行核心业务代码按优先级迁回。同时用Compose原生重写POS收银核心页、恢复Neo4j本体层、建立支付三层对账。这不是重构，是融合。
