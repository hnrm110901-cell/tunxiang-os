# meituan 适配器评审（Sprint F1）

## 基本信息
- 对接系统：美团外卖 / 美团点评团购
- 主文件：
  - `shared/adapters/meituan-saas/src/adapter.py` + `client.py` + `order_webhook_handler.py` + `reservation.py`
  - `shared/adapters/meituan_adapter.py`（单文件版 320 行）
- 代码行数：1991 + 320 = 2311 行（双实现并存，需在 F1 内合并或明确边界）
- Tier：T1（渠道订单）
- 负责 Squad：Channel-B
- 工时预估：4pd（含合并决策）

## 现状快照
- 依赖外部 SDK：httpx / structlog / hashlib
- 是否存在 MOCK_MODE：**是**（meituan_adapter.py 第 78 行 `mock_mode=True`）
- 是否 emit 事件：**否**（0 命中）
- 是否有幂等检查：**未发现** idempotency/nonce
- 是否有重试退避：有（3 处命中 meituan-saas + 0 处 meituan_adapter.py）
- 测试文件数：3 个（test_meituan_adapter_full.py 等）

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
  - P0-1 未接 emit_event（渠道订单必须 CHANNEL.ORDER_SYNCED）
  - P0-2 双实现并存（meituan-saas/ 与 meituan_adapter.py）——状态机不一致风险
  - P0-3 webhook 处理器无 idempotency——美团重推同一订单会重复入账
- P1：
  - P1-1 单文件版 mock_mode 仅构造参数，未贯穿所有分支
  - P1-2 meituan-saas webhook 签名验证覆盖率待评（5 处命中）
- P2：
  - P2-1 合并双实现到 meituan-saas/ 统一目录

## 推荐动作
- [ ] 合并 meituan_adapter.py 到 meituan-saas/（或明确各自职责边界）
- [ ] webhook 处理加 idempotency_key（美团订单号+事件 ID）
- [ ] 接 emit_event CHANNEL.ORDER_SYNCED
- [ ] 评分 <22 时 flag off `agents.channel.meituan`

## 验收时间盒
- 评分完成：2026-04-22
- P0 缺陷修复：2026-04-28
- 上生产 Gate：2026-04-30
