# tiancai-shanglong 适配器评审（Sprint F1）

## 基本信息
- 对接系统：天财商龙（连锁餐饮 ERP/POS）
- 主文件：`shared/adapters/tiancai-shanglong/src/adapter.py`
- 代码行数：923 行
- Tier：T1（交易链路）
- 负责 Squad：Channel-A
- 工时预估：3pd

## 现状快照
- 依赖外部 SDK：httpx / structlog（推断，待 import 核实）
- 是否存在 MOCK_MODE：**否**
- 是否 emit 事件：**否**（未发现 emit_event）
- 是否有幂等检查：**未发现** idempotency/nonce
- 是否有重试退避：有（3 处命中，含 README）
- 测试文件数：2 个（tests/）

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
  - P0-1 未接 emit_event（违反 §XV）
  - P0-2 无 MOCK_MODE 开关，CI 凭证依赖
- P1：
  - P1-1 无 idempotency/nonce 实现（T1 交易链路必须补）
  - P1-2 重试命中含 README 文案，真实重试策略待核实（是否指数退避+最大重试次数上限）
- P2：
  - P2-1 单文件 923 行，建议拆 client/mapper/adapter 三层

## 推荐动作
- [ ] 补 idempotency_key（订单 key=外部订单号+租户）
- [ ] 接 emit_event ORDER.* / CHANNEL.ORDER_SYNCED
- [ ] 评分 <22 时 flag off `agents.channel.tiancai`

## 验收时间盒
- 评分完成：2026-04-22
- P0 缺陷修复：2026-04-28
- 上生产 Gate：2026-04-30
