# eleme 适配器评审（Sprint F1）

## 基本信息
- 对接系统：饿了么商家开放平台
- 主文件：
  - `shared/adapters/eleme/src/adapter.py` + `client.py` + `webhook.py`
  - `shared/adapters/eleme_adapter.py`（单文件 437 行）
- 代码行数：810 + 437 = 1247 行（双实现）
- Tier：T1（渠道订单）
- 负责 Squad：Channel-B
- 工时预估：4pd

## 现状快照
- 依赖外部 SDK：httpx / structlog / hashlib
- 是否存在 MOCK_MODE：**是**（eleme_adapter.py 第 92 行 `mock_mode=True`）
- 是否 emit 事件：**否**
- 是否有幂等检查：**未发现**
- 是否有重试退避：有（2 处命中 eleme/src）
- 测试文件数：**0 个**（eleme/ 下无 tests/ 目录）——P0

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
  - P0-3 双实现（eleme/ + eleme_adapter.py），webhook 路径不一致
  - P0-4 无 idempotency——饿了么 webhook 重推会重复下订单
- P1：
  - P1-1 mock_mode 仅构造参数，未覆盖主路径分支
  - P1-2 webhook 签名验证需复核（webhook.py 独立文件）
- P2：
  - P2-1 合并双实现

## 推荐动作
- [ ] 紧急补 tests/ 目录（fixtures + 签名样本 + 订单推送样本）
- [ ] webhook 幂等（订单号去重表）
- [ ] 接 emit_event CHANNEL.ORDER_SYNCED
- [ ] 评分 <22 时 flag off `agents.channel.eleme`

## 验收时间盒
- 评分完成：2026-04-22
- P0 缺陷修复：2026-04-28
- 上生产 Gate：2026-04-30
