# yiding 适配器评审（Sprint F1）

## 基本信息
- 对接系统：易订（预订/排队 SaaS）
- 主文件：
  - `shared/adapters/yiding/src/adapter.py`
  - `shared/adapters/yiding/src/client.py`
  - `shared/adapters/yiding/src/cache.py`
  - `shared/adapters/yiding/src/mapper.py`
  - `shared/adapters/yiding/src/types.py`
- 代码行数：1566 行
- Tier：T1（预订与到店，与桌台状态机绑定）
- 负责 Squad：Channel-A
- 工时预估：3pd

## 现状快照
- 依赖外部 SDK：httpx / structlog（推断）
- 是否存在 MOCK_MODE：**否**
- 是否 emit 事件：**否**
- 是否有幂等检查：**未发现**
- 是否有重试退避：有（1 处，仅 client.py 命中）
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
  - P0-1 未接 emit_event（预订状态变更未入事件流，影响桌台联动）
  - P0-2 无 MOCK_MODE
- P1：
  - P1-1 无 idempotency（预订重复提交风险）
  - P1-2 重试仅 1 处命中，需评估覆盖率
- P2：
  - P2-1 已拆分 5 文件，结构较好，维持

## 推荐动作
- [ ] 接 emit_event RESERVATION.CREATED / RESERVATION.CANCELED（如 event_types 缺则先在 §XV 表注册）
- [ ] 补 MOCK_MODE + stub fixtures
- [ ] 评分 <22 时 flag off

## 验收时间盒
- 评分完成：2026-04-29（W4 Day1）
- P0 缺陷修复：2026-05-05
- 上生产 Gate：2026-05-07
