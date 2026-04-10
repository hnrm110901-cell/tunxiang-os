# 屯象OS 微信支付代码地图（对接必读）

## 1) 现有入口与职责

- `services/tx-trade/src/api/wechat_pay_routes.py`
  - `/prepay`：创建预支付
  - `/callback`：处理微信回调（当前含 TODO：支付成功后订单落库/事件发布）
  - `/query/{order_no}`：主动查单
  - `/refund`：申请退款
- `shared/integrations/wechat_pay.py`
  - `WechatPayService.create_prepay/query_order/refund/query_refund`
  - 未配置环境变量时自动进入 Mock 模式
  - 回调 `verify_callback` 中“平台证书验签”仍是 TODO，仅有占位逻辑
- `services/tx-trade/src/services/payment_saga_service.py`
  - 负责支付与订单完成的 Saga 编排，可用于支付成功后的一致性闭环

## 2) 对接优先级（建议）

### P0：先跑通真实收款闭环

1. 配置真实商户参数与证书，关闭生产 Mock 依赖。
2. 在回调里实现：验签通过 → 支付流水落库 → 订单改为已支付/已完成。
3. 失败回调与异常重试必须幂等。

### P1：提升稳定性

1. 接入平台证书拉取与轮换策略（serial 匹配）。
2. 增加主动查单补偿任务（应对回调丢失）。
3. 统一支付状态映射（微信状态 → 屯象订单状态）。

### P2：运营与合规

1. 对账下载与账务核对。
2. 退款闭环（申请、查询、状态同步、失败告警）。
3. 审计日志与脱敏策略完善。

## 3) 推荐改造文件清单

- `shared/integrations/wechat_pay.py`
  - 完成平台证书验签逻辑
  - 增加证书缓存/轮换策略
- `services/tx-trade/src/api/wechat_pay_routes.py`
  - 回调成功分支接入订单与支付流水更新
  - 强化错误码与可观测日志
- `services/tx-trade/src/services/payment_saga_service.py`
  - 结合回调或查单结果触发后续状态收敛

## 4) 常见坑位

1. 同一个 `out_trade_no` 被重复下单。
2. 回调先到、业务库写入失败导致“微信成功、订单未成功”。
3. 仅依赖前端 `wx.requestPayment` 成功回调而未二次确认。
4. 未做金额一致性校验（回调金额与订单应付金额不一致）。
