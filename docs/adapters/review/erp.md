# erp 适配器评审（Sprint F1）

## 基本信息
- 对接系统：金蝶（Kingdee）+ 用友（Yonyou）双 ERP
- 主文件：
  - `shared/adapters/erp/src/base.py`
  - `shared/adapters/erp/src/factory.py`
  - `shared/adapters/erp/src/kingdee_adapter.py`
  - `shared/adapters/erp/src/yonyou_adapter.py`
- 代码行数：839 行
- Tier：T1（财务同步，与月结/P&L 联动）
- 负责 Squad：Finance
- 工时预估：4pd

## 现状快照
- 依赖外部 SDK：httpx / hashlib / hmac / uuid
- 是否存在 MOCK_MODE：**否**
- 是否 emit 事件：**否**
- 是否有幂等检查：**是**（kingdee_adapter.py 第 59-94 行 HMAC-SHA256 签名含 nonce）
- 是否有重试退避：**否**（0 处命中）
- 测试文件数：**0 个**——P0（Tier 1 财务链路）

## 7 维评分（待 Owner 填充）
| 维度 | 分 | 证据 | 缺陷 |
|---|---|---|---|
| 1 订单/菜品双向同步 | ?/4 | 凭证推送+主数据同步 |  |
| 2 状态映射完备 | ?/4 |  |  |
| 3 重试/幂等 | ?/4 | HMAC nonce 有，无重试 |  |
| 4 Mock/生产切换 | ?/4 |  |  |
| 5 凭证托管 | ?/4 |  |  |
| 6 异常分支 | ?/4 |  |  |
| 7 事件总线接入 | ?/4 |  |  |
| **总分** | **?/28** | | |

## 已识别缺陷（审计初稿）
- P0：
  - P0-1 **无 tests/ 目录**（Tier 1 财务必须 TDD）
  - P0-2 **无重试退避**——ERP 网关常态级 5xx 必须退避
  - P0-3 未接 emit_event（应 emit FINANCE.VOUCHER_PUSHED）
- P1：
  - P1-1 无 MOCK_MODE（金蝶/用友沙箱 token 受限）
  - P1-2 yonyou_adapter 凭证流程与 kingdee 是否对齐 base.py 抽象需核查
- P2：
  - P2-1 factory 模式是否支持租户级多 ERP 切换待评

## 推荐动作
- [ ] 紧急补 tests/（kingdee + yonyou 双通道 fixtures）
- [ ] 补重试退避（429/5xx，最大 3 次指数退避）
- [ ] 接 emit_event FINANCE.VOUCHER_PUSHED / FAILED
- [ ] 评分 <22 时 flag off `agents.finance.erp.*`

## 验收时间盒
- 评分完成：2026-04-29
- P0 缺陷修复：2026-05-05
- 上生产 Gate：2026-05-07
