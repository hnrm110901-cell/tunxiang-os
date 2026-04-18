# weishenghuo 适配器评审（Sprint F1）

## 基本信息
- 对接系统：微生活（会员营销 SaaS）
- 主文件：`shared/adapters/weishenghuo/src/adapter.py`
- 代码行数：800 行
- Tier：T1（会员 + 资金相关）
- 负责 Squad：Channel-A
- 工时预估：3pd

## 现状快照
- 依赖外部 SDK：httpx / structlog（推断）
- 是否存在 MOCK_MODE：**否**
- 是否 emit 事件：**否**
- 是否有幂等检查：**未发现**
- 是否有重试退避：有（3 处命中，含 README）
- 测试文件数：2 个

## 7 维评分（待 Owner 填充）
| 维度 | 分 | 证据 | 缺陷 |
|---|---|---|---|
| 1 订单/菜品双向同步 | ?/4 |  |  |
| 2 状态映射完备 | ?/4 |  |  |
| 3 重试/幂等 | ?/4 |  |  |
| 4 Mock/生产切换 | ?/4 |  |  |
| 5 凭证托管 | ?/4 |  |  |
| 6 异常分支 | ?/4 |  |  |
| 7 事件总线接入 | ?/4 |  |  |
| **总分** | **?/28** | | |

## 已识别缺陷（审计初稿）
- P0：
  - P0-1 未接 emit_event（会员资产变动无法入事件流，违反 §XV MEMBER.RECHARGED/CONSUMED）
  - P0-2 无 MOCK_MODE
- P1：
  - P1-1 无幂等（会员充值/核销接口必须幂等，否则重放=资损）
- P2：
  - P2-1 重试策略覆盖率待评（3 处含 README）

## 推荐动作
- [ ] 补 emit_event MEMBER.RECHARGED / MEMBER.CONSUMED / COUPON.REDEEMED
- [ ] 补 idempotency_key（会员流水=外部流水号）
- [ ] 评分 <22 时 flag off

## 验收时间盒
- 评分完成：2026-04-22
- P0 缺陷修复：2026-04-28
- 上生产 Gate：2026-04-30
