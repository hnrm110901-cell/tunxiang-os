# nuonuo 适配器评审（Sprint F1）

## 基本信息
- 对接系统：诺诺网（全电发票 / 金税四期）
- 主文件：
  - `shared/adapters/nuonuo/src/adapter.py`
  - `shared/adapters/nuonuo/src/invoice_client.py`
- 代码行数：296 行
- Tier：T1（发票与资金，§XVII 列为 Tier 1 zero-tolerance）
- 负责 Squad：Finance
- 工时预估：4pd（Tier 1 必须 TDD）

## 现状快照
- 依赖外部 SDK：httpx / hashlib / uuid
- 是否存在 MOCK_MODE：**否**
- 是否 emit 事件：**否**
- 是否有幂等检查：**是**（adapter.py 第 51-69 行实现了 nonce + X-Nuonuo-Sign HMAC 签名）
- 是否有重试退避：**否**（0 处命中）
- 测试文件数：**0 个** ——P0（Tier 1 不得无测试）

## 7 维评分（待 Owner 填充）
| 维度 | 分 | 证据 | 缺陷 |
|---|---|---|---|
| 1 订单/菜品双向同步 | ?/4 | N/A（发票域） |  |
| 2 状态映射完备 | ?/4 |  |  |
| 3 重试/幂等 | ?/4 | 有 nonce+签名，无重试 |  |
| 4 Mock/生产切换 | ?/4 |  |  |
| 5 凭证托管 | ?/4 |  |  |
| 6 异常分支 | ?/4 |  |  |
| 7 事件总线接入 | ?/4 |  |  |
| **总分** | **?/28** | | |

## 已识别缺陷（审计初稿）
- P0：
  - P0-1 **无 tests/ 目录**（Tier 1 金税链路，禁止裸奔）
  - P0-2 **无重试退避**——金税四期接口拒单/限流无降级
  - P0-3 未接 emit_event（应 emit INVOICE.ISSUED / INVOICE.FAILED）
- P1：
  - P1-1 无 MOCK_MODE——CI 无法跑全电发票金税样本
  - P1-2 凭证托管：app_secret 加载路径需确认是否走 Vault
- P2：
  - P2-1 代码体量偏小（296 行），金税场景覆盖是否充分待评

## 推荐动作
- [ ] 紧急补 tests/（覆盖蓝票/红票/作废/查询 4 大场景 + XSD 校验）
- [ ] 补指数退避重试（429/5xx）
- [ ] 接 emit_event INVOICE.ISSUED / INVOICE.VOIDED
- [ ] 评分 <22 时 flag off `agents.finance.invoice.nuonuo`——金税不合规=刑事风险

## 验收时间盒
- 评分完成：2026-04-29
- P0 缺陷修复：2026-05-05
- 上生产 Gate：2026-05-07（含 10% 金税抽检）
