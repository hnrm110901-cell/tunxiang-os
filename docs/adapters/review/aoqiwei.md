# aoqiwei 适配器评审（Sprint F1）

## 基本信息
- 对接系统：奥琦玮（连锁餐饮 POS + CRM 会员中台）
- 主文件：
  - `shared/adapters/aoqiwei/src/adapter.py`（POS 订单/菜品）
  - `shared/adapters/aoqiwei/src/crm_adapter.py`（会员 CRM）
  - `shared/adapters/aoqiwei/src/supply_mapper.py`（供应链映射）
- 代码行数：2679 行（含 tests，最大体量非品智适配器）
- Tier：T1（交易+会员双链路）
- 负责 Squad：Channel-A
- 工时预估：5pd（含评分+P0 修复）

## 现状快照
- 依赖外部 SDK：httpx / structlog / hashlib（自建签名）
- 是否存在 MOCK_MODE：**否**（未发现 mock_mode 分支）
- 是否 emit 事件：**否**（未发现 emit_event 调用）
- 是否有幂等检查：**未发现** idempotency/nonce/replay 关键字
- 是否有重试退避：有（6 处命中 retry/backoff，需逐一核实是否指数退避）
- 测试文件数：4 个（test_adapter.py / test_aoqiwei_adapter_full.py / test_crm_adapter.py / test_supply_mapper.py）

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
- P0（上生产阻断）：
  - P0-1 未接入事件总线 emit_event（违反 CLAUDE.md §XV）——CRM 变更无法驱动下游物化视图
  - P0-2 无 MOCK_MODE 开关——CI 无法在无真机凭证下跑端到端测试
- P1（推荐修复）：
  - P1-1 未发现 idempotency_key / nonce 显式实现，签名重放风险待复核（adapter 自签名逻辑需审）
  - P1-2 凭证托管是否走 Vault 需在 adapter.py 顶部环境变量加载处确认
- P2（优化建议）：
  - P2-1 supply_mapper 与 crm 分三文件，状态机是否统一需评估

## 推荐动作
- [ ] 补 MOCK_MODE=True 分支 + stub fixtures
- [ ] 接入 emit_event（ORDER.PAID / MEMBER.UPDATED / INVENTORY.ADJUSTED 依业务域）
- [ ] 评分 <22 时 flag off `agents.channel.aoqiwei`

## 验收时间盒
- 评分完成：2026-04-22（W3 Day2）
- P0 缺陷修复：2026-04-28（W3 Day5）
- 上生产 Gate：2026-04-30（W4 Day1）
