# wechat_delivery 适配器评审（Sprint F1）

## 基本信息
- 对接系统：微信配送（小程序同城配送 + 达达/顺丰/美团直送聚合）
- 主文件：`shared/adapters/wechat_delivery_adapter.py`
- 代码行数：225 行
- Tier：T1（配送订单，影响客户体验）
- 负责 Squad：Channel-B
- 工时预估：2pd

## 现状快照
- 依赖外部 SDK：httpx（推断）
- 是否存在 MOCK_MODE：**是**（第 77 行 `mock_mode=True`）
- 是否 emit 事件：**否**
- 是否有幂等检查：**未发现**
- 是否有重试退避：**否**（0 处命中）
- 测试文件数：**0 个**（该单文件无独立测试）

## 7 维评分（待 Owner 填充）
| 维度 | 分 | 证据 | 缺陷 |
|---|---|---|---|
| 1 订单/菜品双向同步 | ?/4 |  |  |
| 2 状态映射完备 | ?/4 |  |  |
| 3 重试/幂等 | ?/4 |  |  |
| 4 Mock/生产切换 | ?/4 | 有 mock_mode 构造参数 |  |
| 5 凭证托管 | ?/4 |  |  |
| 6 异常分支 | ?/4 |  |  |
| 7 事件总线接入 | ?/4 |  |  |
| **总分** | **?/28** | | |

## 已识别缺陷（审计初稿）
- P0：
  - P0-1 **无 tests/**（Tier 1 配送订单）
  - P0-2 **无重试**（达达/顺丰聚合层 5xx 高频）
  - P0-3 未接 emit_event（DELIVERY.DISPATCHED / ARRIVED / FAILED）
  - P0-4 无 idempotency（重复派单=双倍骑手费）
- P1：
  - P1-1 mock_mode 仅构造参数，未覆盖主路径分支
  - P1-2 未继承 `delivery_platform_base` 的统一接口（需核对）
- P2：
  - P2-1 与 delivery_factory 的集成边界待梳理

## 推荐动作
- [ ] 紧急补 tests/（含聚合路由 + 派单去重 + 轨迹回调）
- [ ] 补 idempotency_key（门店订单号 + 配送单号）
- [ ] 补指数退避重试
- [ ] 接 emit_event DELIVERY.*
- [ ] 评分 <22 时 flag off `agents.channel.wechat_delivery`

## 验收时间盒
- 评分完成：2026-04-22
- P0 缺陷修复：2026-04-28
- 上生产 Gate：2026-04-30
