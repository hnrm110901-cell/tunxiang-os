# 屯象OS 架构修正方案 — 7个结构性问题的修正

> 基于从2030回看的架构审视，在MVP前必须纠正的结构性问题
> 不修正 = 后期重写代价

---

## 修正 #1: 金额单位统一 — 全部存分(Integer)

### 现状问题
- V1: `Numeric(10,2)` 存元
- V3: `Integer` 存分(fen)
- V1迁入18,490行代码时每处金额计算都需确认单位

### 修正规则
```
所有数据库字段: INTEGER, 单位=分(fen)
所有API入参出参: 整数, 单位=分(fen)
所有内部变量: 后缀_fen (amount_fen, total_fen, cost_fen)
前端展示层: fen / 100 → 显示元, 显示时加千分位
```

### 代码修正清单
- V1迁入文件: 所有 `Numeric(10,2)` → `Integer`
- V1迁入文件: 所有金额变量加 `_fen` 后缀
- V1迁入文件: 所有 `amount * 100` 转换处理
- 已有V3代码: 审查确认一致性

---

## 修正 #2: MVP单体架构 — 1个FastAPI进程

### 现状问题
- 12微服务 = 12个Docker + 12个CI + 12个健康检查 + 12个连接池
- 单人团队运维不可持续

### 修正方案
```
MVP阶段 (0-20家店):
  1个FastAPI单体 (services/tunxiang-api/)
  + 1个POS App (apps/android-pos/)
  + 1个前端Web (apps/web-admin/)

内部按模块组织:
  services/tunxiang-api/src/
    modules/
      trade/      # 原tx-trade + tx-menu + tx-member + tx-finance
      ops/        # 原tx-org + tx-supply + tx-ops
      brain/      # 原tx-agent + tx-analytics + tx-growth + tx-intel
      gateway/    # 路由/认证/Hub API
    shared/
      ontology/   # 实体定义
      auth/       # 认证
      config/     # 配置
    main.py       # 单入口

未来拆分触发条件:
  - 第2个开发者加入
  - 客户超过20家
  - 单进程QPS>1000
```

### 关键约束
- 内部模块间通过Python函数调用,不走HTTP
- 保持V3的分层规范(api/services/models)
- 每个模块独立目录,未来可一键拆出微服务

---

## 修正 #3: Ontology模式 — MVP用PG JSONB, 非旁路CDC

### 现状问题
- Neo4j通过CDC异步同步 → 延迟/失败 → Agent基于过时数据
- Agent决策结果不回写Neo4j → 因果关系链断裂

### MVP方案
```
Sprint 1-8: 不用Neo4j
  - PG JSONB字段存储轻量级实体关系
  - Order.metadata: {"related_dishes": [...], "cost_breakdown": {...}}
  - Dish.relationships: {"bom": [...], "suppliers": [...]}
  - Agent decision写入PG decision_log表,含因果链JSON

Sprint 9+: 引入Neo4j Write-Through(非CDC)
  - 每笔订单结算时同步写入PG + Neo4j
  - Agent决策作为Action节点写入Neo4j
  - 废弃V1的data_sync.py CDC模式
```

---

## 修正 #4: POS原生覆盖 — 点单全链路原生

### 现状问题
- 只有5页原生 → 中间被WebView/Native边界切断
- 午高峰每分钟3-4次加菜,200ms延迟累积明显

### 修正方案
```
Compose原生(零延迟操作):
  开台 → 点单 → 加菜 → 改菜 → 退菜 → 送厨房 → 催菜
  → 结算 → 交接班
  = 一个完整的Order操作链路

WebView(非高频操作):
  日结 → 报表 → 配置 → 会员管理 → 库存查看

Kotlin开发量: 5-6周(原3-4周)
换来: 收银操作零卡顿 ≥ 品智基线
```

---

## 修正 #5: 回滚方案 — 品智热备+双向同步

### 现状问题
- S3完全替代后无退路
- 回滚品智 = 丢失切换后的所有业务数据

### 修正方案
```
S2阶段(屯象主用):
  方案A(品智有导入API):
    屯象OS订单/支付 → 实时反向写入品智
    品智数据保持最新 → 可随时切回

  方案B(品智无导入API,大概率):
    品智POS保持开机热备(不操作)
    菜品主档/桌台配置在品智端保持同步更新
    屯象出问题 → 员工5分钟内切回品智收银

  切换回品智的操作SOP:
    1. 品智POS登录(已保持开机)
    2. 确认菜品/桌台配置(已同步)
    3. 用品智开始收银
    4. 屯象OS修复后,补录品智期间的数据

回滚触发条件:
  - 支付对账差异 > 1%
  - 连续2单支付失败
  - POS崩溃无法恢复
```

---

## 修正 #6: 测试纳入Sprint交付物

### 每Sprint必须交付的测试

```
Sprint 1-2 必须测试:
  [ ] 断网离线收银E2E (开台→点单→结账→日结,联网后同步)
  [ ] 多支付拆单 (微信200+支付宝100+现金50+会员100=450)
  [ ] 高并发点单 (模拟20台同时点单,不丢单不重复)
  [ ] 毛利底线校验 (折扣后毛利<30%拒绝)

Sprint 3-4 必须测试:
  [ ] 预订→排队→入座全链路
  [ ] 宴会定金→结算→80%最低消费
  [ ] 对账CSV导入→匹配→差异(微信/支付宝)
  [ ] RLS租户隔离 (品牌A看不到品牌B数据)

Sprint 5-8 必须测试:
  [ ] 排班约束(40h上限,11h休息,6天连续)
  [ ] 薪资全流程(基本+提成+社保+个税=实发)
  [ ] Agent Level 1建议→采纳→效果追踪
  [ ] 门店P&L异常检测(食材>35%告警)

Sprint 9-12 必须测试:
  [ ] Neo4j因果链("酸菜鱼毛利下降" → 根因)
  [ ] 语音下单("三号桌加酸菜鱼微辣" → 订单)
  [ ] CFO多品牌合并报表
  [ ] 2030弹性(新渠道/新业态不改代码)

上线前置条件: 所有标记测试必须PASS,否则不上真实门店。
```

---

## 修正 #7: 数据模型弹性

### 现状问题
- Order.table_number是必选 → 预制菜零售没有桌台
- sales_channel是枚举 → 新渠道要改代码
- Store假设physical seats → 中央厨房/电商仓库不适用

### 修正方案

```python
# Order: table_no改为可选,放metadata
class Order:
    order_id: str
    tenant_id: str
    store_id: str
    order_type: str           # dine_in/takeaway/delivery/retail/catering
    sales_channel_id: str     # 引用配置表,不是枚举
    status: str
    total_fen: int
    discount_fen: int
    payable_fen: int
    metadata: dict = {}       # {"table_no": "A03", "guest_count": 4, ...}
    # table_no不再是顶层必选字段

# SalesChannel: 配置表,不是枚举
class SalesChannel:
    channel_id: str
    channel_name: str         # "堂食"/"美团外卖"/"预制菜零售"
    channel_type: str         # dine_in/delivery/retail/catering/b2b
    commission_rate: float    # 平台抽成
    settlement_days: int      # T+N结算
    margin_rules: dict        # 毛利核算规则
    is_active: bool
    # 新增渠道 = 加一条记录,不改代码

# Store: 支持虚拟门店
class Store:
    store_id: str
    tenant_id: str
    store_name: str
    store_type: str           # physical/virtual/central_kitchen/warehouse
    business_type: str        # fine_dining/fast_food/retail/catering
    has_physical_seats: bool  # True for restaurants, False for warehouses
    seat_count: int | None    # None for virtual stores
    address: str | None       # None for virtual stores
    metadata: dict = {}       # 灵活扩展
```

---

## 执行优先级

```
现在做(写第一行MVP代码前):
  #1 金额统一 → 审查所有_fen后缀
  #2 单体架构 → 设计tunxiang-api目录
  #4 POS全链路 → 更新Kotlin范围
  #7 数据模型 → 改Order/Store/SalesChannel

首店上线前做:
  #3 Ontology → PG JSONB方案
  #5 回滚方案 → 品智热备SOP

贯穿全程:
  #6 测试 → 每Sprint交付E2E测试
```
