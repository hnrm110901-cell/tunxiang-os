# 屯象OS 跨平台人财物信息聚合 — 升级迭代开发计划

> 方案C（事件驱动聚合层）落地路线图
> 日期：2026-05-05 | 状态：P0 实施已完成

## 一、现状诊断

### 已就绪
- 事件总线 v147+v148（39 枚举类/25+ 域）
- OmniChannelService（美团/饿了么/抖音统一接单）
- delivery_canonical（标准化数据模型 + transformers）
- 美团/抖音/小红书/饿了么/品智/奥琦玮/天财商龙 Adapter（真实实现）
- Agent 体系（约束框架 + Master + 9 Skill Agent）

### 关键问题
1. 两条渠道路径并行（webhook_routes.py → delivery_orders vs OmniChannelService → orders）
2. channel_canonical_orders 未接入
3. 缺高德团购 Adapter、缺淘宝闪购 Adapter
4. 抖音/饿了么 Adapter 无测试

## 二、目标架构

```
前端 → 领域Hub (OrderHub/MenuHub/MemberHub/ReviewHub/FinanceHub)
     → 事件总线 (v147+v148)
     → 平台Adapter (美团/点评/抖音/小红书/高德/淘宝闪购)
     → 外部平台 Open API
```

## 三、分期计划

### P0：地基加固（已完成 ✅）
- P0.1: 合并渠道路径（deprecation + 迁移 v398/v399）
- P0.2: 接入 channel_canonical_orders（v400 + canonical write）
- P0.3: 高德 Adapter + 淘宝 Adapter + factory 注册
- P0.4: 抖音 + 饿了么 Adapter 测试补充
- P0.5: OmniService 改用共享 delivery_factory

### P1：财·全渠道订单聚合（待规划）
- OrderHub 领域服务
- 实时库存同步 + 反超卖
- KDS 接入
- 门店管理后台

### P2：物·菜品与库存统一管理（待规划）
- MenuHub 跨平台菜品发布引擎
- BOM 库存联动

### P3：人·会员统一 CDP（待规划）
- Golden ID 跨平台匹配
- 积分通兑 + 营销统一

### P4：信息·评价与舆情聚合（待规划）
- 多平台评价拉取 + 差评预警
- 竞品监控

### P5：财·结算对账 + Agent 编排（待规划）
- 自动对账引擎
- Agent 跨渠道监控升级
- 经营驾驶舱

## 四、P0 交付摘要

**10 个提交**，涉及：
- 4 个迁移（v398/v399/v400）
- 2 个新 Adapter（amap/taobao + 测试）
- 2 个现有 Adapter 测试补充（douyin/eleme，36 个测试）
- factory 重构 + 签名验证器
- OmniService 重构使用共享工厂
- 文档（spec + plan）
