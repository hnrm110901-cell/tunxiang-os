# douyin 适配器评审（Sprint F1）

## 基本信息
- 对接系统：抖音生活服务（团购 / 外卖）
- 主文件：
  - `shared/adapters/douyin/src/adapter.py` + `client.py` + `order_webhook_handler.py`
  - `shared/adapters/douyin_adapter.py`（单文件 432 行）
- 代码行数：537 + 432 = 969 行（双实现）
- Tier：T1（渠道订单）
- 负责 Squad：Channel-B
- 工时预估：4pd

## 现状快照
- 依赖外部 SDK：httpx / structlog / hashlib
- 是否存在 MOCK_MODE：**是**（douyin_adapter.py 第 100 行 `mock_mode=True`）
- 是否 emit 事件：**否**
- 是否有幂等检查：**未发现**
- 是否有重试退避：有（2 处命中）
- 测试文件数：**0 个**（douyin/ 下无 tests/ 目录）——P0

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
  - P0-1 **无 tests/ 目录**——T1 渠道不得上生产
  - P0-2 未接 emit_event
  - P0-3 双实现并存，状态机一致性风险
  - P0-4 无 idempotency（抖音 webhook 重推高频）
- P1：
  - P1-1 mock_mode 仅构造参数
  - P1-2 order_webhook_handler 签名/重放防护需复核
- P2：
  - P2-1 合并双实现

## 推荐动作
- [ ] 补 tests/（含 webhook 签名 / 团购核销 / 退款回调样本）
- [ ] 幂等：抖音订单号 + nonce
- [ ] 接 emit_event CHANNEL.ORDER_SYNCED
- [ ] 评分 <22 时 flag off `agents.channel.douyin`

## 验收时间盒
- 评分完成：2026-04-22
- P0 缺陷修复：2026-04-28
- 上生产 Gate：2026-04-30
