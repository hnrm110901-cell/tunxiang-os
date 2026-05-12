# 支付渠道 mock 模式 walkthrough（2026-05-12）

> **目的**：在真实凭据未到位前（`#468` UnionPay / `#469` 拉卡拉 / `#470` 数字人民币 全 OPEN backlog），把 4 个第三方支付 channel + 4 个 callback endpoint 在 mock 模式下的端到端行为画清楚，作为 5/13 demo 的兜底路径 + 凭据 PR 落地前的回归基线。
>
> 配套测试：[services/tx-pay/tests/test_pay_channels_e2e_mock.py](../../services/tx-pay/tests/test_pay_channels_e2e_mock.py)（放在 services/tx-pay/tests/ 下以走 services/tx-pay/conftest.py 的 services.tx_pay namespace 注入；不带 `_tier1` 后缀以避开 §17 Tier1 路径定义）
>
> 不在本文档范围：真实凭据下的真验签（已在 [services/tx-pay/tests/test_*_callback_tier1.py](../../services/tx-pay/tests/) 5/12 中午 30 个 Tier1 测试覆盖）；跨服务订单 → 支付 → 状态推进（候选 2 [docs/walkthrough/pos-core-flow-2026-05-12.md](./pos-core-flow-2026-05-12.md)）。

## 1. Channel registry topology

### 1.1 8 channel 注册（services/tx-pay/src/main.py:38-58）

| # | channel_name | 类型 | mock 路径 | 真实模式状态 |
|---|---|---|---|---|
| 1 | `wechat_direct` | 第三方 | `_service is None` → mock SUCCESS | ✅ 5/12 中午 PR #465 修真实模式入口（create_jsapi_order → create_prepay）|
| 2 | `alipay_direct` | 第三方 | 无条件 mock SUCCESS（pay/query/refund 总走 mock）| ✅ 5/12 中午 PR #459 RSA2 真验签 |
| 3 | `lakala_direct` | 第三方 | （未审本次范围）| 🔜 `#469` backlog — 需创始人 raw spec / SDK / 商户证书 |
| 4 | `shouqianba_direct` | 第三方 | `_client is None` → mock SUCCESS | ✅ 5/12 中午 PR #461 MD5 真验签 + channel_name 漂移修 |
| 5 | `unionpay` | 第三方 | `_client is None` → mock SUCCESS；否则 NotImplementedError | 🔜 `#468` backlog — 需 .pfx + middle/root .cer + 测试 merId + product line 合约 |
| 6 | `cash` | 内部 | 无 mock 概念，原生支持 | ✅ 实时 |
| 7 | `stored_value` | 内部 | 无 mock 概念，原生支持 | ✅ 实时 |
| 8 | `credit_account` | 内部 | 无 mock 概念，原生支持 | ✅ 实时 |

### 1.2 4 callback endpoint（services/tx-pay/src/api/callback_routes.py）

| # | endpoint | 对应 channel_name | 强制验签触发条件 | 已 Tier1 真验签 |
|---|---|---|---|---|
| 1 | `POST /api/v1/pay/callback/wechat` | `wechat_direct` | `TX_PAY_MOCK_MODE != true` | ✅ 真实模式（5/12 中午前已存在）|
| 2 | `POST /api/v1/pay/callback/alipay` | `alipay_direct` | `TX_PAY_MOCK_MODE != true` | ✅ PR #459 RSA2 |
| 3 | `POST /api/v1/pay/callback/lakala` | `lakala_direct` | `TX_PAY_MOCK_MODE != true` | 🔜 `#469` 凭据前置 |
| 4 | `POST /api/v1/pay/callback/shouqianba` | `shouqianba_direct` | `TX_PAY_MOCK_MODE != true` | ✅ PR #461 MD5 |
| ❌ | `POST /api/v1/pay/callback/unionpay` | （**未注册**）| — | 🔜 `#468` 凭据前置（finding #5）|

### 1.3 拓扑差异（8 channel ≠ 4 endpoint）

- 4 个内部 channel（cash / stored_value / credit_account）不需要异步 callback —— 同步落账，pay() 即终态
- unionpay channel 已注册到 registry（Mock 占位）但 callback endpoint **故意未注册**（PR #467 决策 B）—— audit signal 边界，等凭据 PR
- lakala callback endpoint 已注册但 channel 内 verify_callback 返 NotImplementedError —— callback_routes catch 后返 400 + log，不会静默 fallback

## 2. Mock 模式行为表

| channel | `pay()` mock | `query()` mock | `refund()` mock | `verify_callback()` mock |
|---|---|---|---|---|
| **alipay** | 无条件返 SUCCESS | 返 SUCCESS + amount_fen=**0** ⚠️ | 返 success | 抛 NotImplementedError("AlipayService 未初始化") |
| **wechat** | `_service is None` → SUCCESS + prepay_id mock | 同 alipay | 同 alipay | 抛 NotImplementedError("Mock 模式不支持回调验证") |
| **shouqianba** | `_client is None` → SUCCESS | 返 SUCCESS + method=**WECHAT 硬编码** ⚠️ | 同 alipay | 抛 NotImplementedError("ShouqianbaService 未初始化") |
| **unionpay** | `_client is None` → SUCCESS；否则 NotImplementedError | 同 + trade_no 唯一 fallback | 同 alipay | 总抛 NotImplementedError（无 mock 路径，audit signal）|

### 2.1 mock 行为不一致点（findings 详见 §4）

- alipay/wechat 走 mock 路径都是 `SUCCESS + amount_fen=0`（query），可能误导调用方
- shouqianba 走 mock query 时强制 method=WECHAT —— 实际支持 ALIPAY/UNIONPAY 但 query 返不出来
- unionpay 是唯一 mock query 提供 trade_no fallback 的（5/12 中午 PR #467 reviewer 修），其他 3 channel 直接 None

## 3. 真实模式凭据需求清单

### 3.1 已落地 channel（不缺凭据）
- **wechat_direct**: 已配 `WECHAT_PAY_MCH_ID` / `WECHAT_PAY_API_KEY_V3` / `WECHAT_PAY_CERT_PATH` / `WECHAT_PAY_APPID`
- **alipay_direct**: 已配 `ALIPAY_APP_ID` / `ALIPAY_APP_PRIVATE_KEY` / `ALIPAY_PUBLIC_KEY` / `ALIPAY_SELLER_ID`（5/12 中午 PR #459）
- **shouqianba_direct**: 已配 `SHOUQIANBA_TERMINAL_SN` / `SHOUQIANBA_TERMINAL_KEY`（5/12 中午 PR #461）

### 3.2 凭据缺失 channel（OPEN backlog）

#### `#468` UnionPay 云闪付（Tier1，5/13 deal-breaker 之一）
- 银联颁发**商户 .pfx**（含 X.509 cert + 私钥）
- 银联**中级证书 .cer + 根证书 .cer**（PKIX 三证链验签必须）
- 测试环境 **merId** + 凭据
- **餐饮场景 product line 合约确认** —— 决定走哪套算法：
  - UPOP 网关：SHA-256 + RSA + 字母序排序
  - OpenAPI：SHA-256 + RSA + 固定序
  - 云闪付控件：SHA-1 + RSA
  - 三套不兼容，合约不定 → 自造验签 = 把伪造 callback 风险带进 Tier1

#### `#469` 拉卡拉（Tier1，5/13 deal-breaker 之一）
- raw spec / SDK / 历史接入代码 / 商户证书 任一
- 公开文档不足，需创始人提供 1 份起

#### `#470` 数字人民币（Tier1，5/13 deal-breaker 之一）
- 13 家运营机构选定（路径 A 直连 / 路径 B 聚合服务商）
- 商户协议签订 + 测试凭据

## 4. silent bug findings（按 Tier/优先级排序）

### Finding #1（**P1，Tier1，独立 PR 修**）— wechat `verify_callback` 不校验 trade_state

**位置**：`services/tx-pay/src/channels/wechat.py:153-160`

```python
async def verify_callback(self, headers: dict, body: bytes) -> CallbackPayload:
    if self._service is None:
        raise NotImplementedError("Mock 模式不支持回调验证")
    data = await self._service.verify_callback(headers, body)
    return CallbackPayload(
        payment_id=data.get("out_trade_no", ""),
        trade_no=data.get("transaction_id", ""),
        status=PayStatus.SUCCESS,  # ← 不看 wechat trade_state，硬编码 SUCCESS
        amount_fen=data.get("amount", {}).get("total", 0),
        raw=data,
    )
```

**对比**：alipay 用 `_TRADE_STATUS_MAP`、shouqianba 用 `_ORDER_STATUS_MAP` 都做 status 映射 + 未知值降级 PENDING + log warning。wechat 缺这层。

**风险**：
- 真实情况：wechat V3 异步 callback 按文档只推 SUCCESS，所以生产可能不触发
- 防御性边界：若 wechat 推非 SUCCESS state（如 REFUND / CLOSED 异步通知），channel 解析成 SUCCESS → silently 推订单到"已支付" → 财务穿透
- amount_fen fallback 默认 0：若 callback body 缺 amount 字段，amount=0 入库 → 资金核对告警

**建议**：独立 PR 修（Tier1 路径，需 reviewer pass 1-2 轮 + 真断言测试）。pattern 抄 alipay/shouqianba 的 `_STATUS_MAP` + `Decimal` 精度。

### Finding #2（P2，walkthrough 锁定）— shouqianba mock `query()` method 硬编码 WECHAT

**位置**：`services/tx-pay/src/channels/shouqianba.py:120, 139`

```python
return PaymentResult(
    payment_id=payment_id,
    status=PayStatus.SUCCESS,
    method=PayMethod.WECHAT,  # ← 强制 WECHAT；漂移
    amount_fen=0,
    ...
)
```

**问题**：shouqianba 是聚合支付，`supported_methods = [WECHAT, ALIPAY, UNIONPAY]`。mock query 时 query 入参没有 method 字段，无法回溯原 pay() 用的 method —— 强制 WECHAT 是实现简化但语义错误。用 ALIPAY 走收钱吧 pay 后 query 出来 method 变 WECHAT。

**对调用方影响**：mock 模式下 query 结果用于对账，method 漂移会误判渠道分摊。

**建议**：单独小 PR 修，方案：
1. 新增 `query()` 入参 `method: Optional[PayMethod]`（破坏接口签名，需评估）
2. 或 `PaymentResult.method` 改为 `Optional`，mock 模式返 None
3. 或 channel 内维护 `payment_id → method` 缓存（mock 模式 only）

非 Tier1（mock 路径不影响生产资金），可放优先级低。

### Finding #3（P3，walkthrough 锁定）— alipay mock `query()` 总返 amount_fen=0

**位置**：`services/tx-pay/src/channels/alipay.py:71-79`

**问题**：mock query 返 `amount_fen=0`，与 pay() 时记录的金额脱节。调用方拿到 0 会触发对账告警。

**建议**：mock query 返 `amount_fen=request.amount_fen`（要求 channel 缓存最近 pay 的金额）或返 None。低优先级。

### Finding #4（P3，walkthrough 记录，pattern 不一致但 safe-default）— callback_routes `_MOCK_MODE` 单例快照

**位置**：`services/tx-pay/src/api/callback_routes.py:28`

```python
_MOCK_MODE = os.getenv("TX_PAY_MOCK_MODE", "").lower() in ("1", "true", "yes")
```

**对比**：5/12 中午 PR #459/#461 reviewer 揭露 channel `_mock_mode` 同款单例快照 P0 → 已修为 `_is_mock_mode()` 方法每次重读 env。callback_routes 没修。

**为什么不是 P0**：
- channel `_mock_mode` default = True（缺凭据 → mock 静默 bypass）→ **不安全 default**，必须修
- callback_routes `_MOCK_MODE` default = False（缺 env → 强制验签）→ **安全 default**，K8s init container 注入 env 后即便没重读，行为仍是"强制验签"，不会静默放行伪造 callback

**风险点**：仅当 prod 误设 `TX_PAY_MOCK_MODE=true` 后想动态切回 false 时才会出问题（需重启进程）。生产 prod 永远不应设 mock，所以风险低。

**建议**：pattern 一致性收尾，下次 callback_routes 扩展时改为方法重读。优先级低。

### Finding #5（预期，audit signal）— unionpay 没 callback endpoint

**位置**：`services/tx-pay/src/api/callback_routes.py`（缺 `/unionpay` route）

**说明**：PR #467 决策 B 沉淀 —— unionpay channel 已注册（Mock 占位 + verify_callback 总抛 NotImplementedError），但 callback_routes 故意不注册 endpoint。这是 audit 边界，明确告诉 reviewer / 运维：unionpay 凭据未到，callback 链路完全未联调。

**建议**：凭据 PR `#468` 同步落 endpoint。本 walkthrough 测试锁定当前缺失行为，凭据 PR 落地后该断言改为 endpoint 已注册。

## 5. 5/13 demo 兜底路径

资质未办（创始人级别非技术 task 连续 7+ session 提醒未起手）→ 真实联调走不通 → 5/13 demo 必须演 mock 模式。

### 5.1 mock 模式可演内容
- ✅ 收银员选支付方式（wechat / alipay / unionpay / shouqianba 聚合）
- ✅ 调用 channel.pay() → 返 mock SUCCESS + payment_id + trade_no
- ✅ 订单状态推进（mock SUCCESS 触发 `emit_payment_confirmed` → 事件总线）
- ✅ query() 对账（限制：amount_fen=0 / shouqianba method 漂移 → 演前打补丁或解释）
- ✅ refund() 退款链路 mock（限制：refund_id 是 channel 自生成，无真实第三方流水）

### 5.2 mock 模式不可演内容
- ❌ 异步 callback 验签（4 endpoint 都返 400 if `TX_PAY_MOCK_MODE=true`）
- ❌ 真第三方支付流水（trade_no 全是 `MOCK_*` 前缀，客户一眼看出）
- ❌ 跨平台对账（mock 没真账期）

### 5.3 demo 风险点
- mock_mode env 切换需重启 tx-pay 进程（finding #4 单例快照）
- 客户问"真实联调几时能跑"→ 回"凭据到位后 1 PR 落地"，给 backlog issue #468/#469/#470 透明度

## 6. 后续 PR 建议

| 优先级 | 主题 | 估计 | 关联 finding |
|---|---|---|---|
| P1 Tier1 | wechat verify_callback 校验 trade_state + amount_fen 防御 | 1 PR ~150 行 | #1 |
| P2 | shouqianba mock query method 漂移修 | 1 PR ~80 行 | #2 |
| P3 | alipay mock query amount_fen 用 pay 记录金额 | 1 PR ~50 行 | #3 |
| P3 | callback_routes `_MOCK_MODE` 改方法重读 env（pattern 一致性）| 1 PR ~30 行 | #4 |
| 凭据后 | unionpay callback endpoint 注册 + verify 真实现 | 凭据 PR #468 内 | #5 |

按 5/12 中午"reviewer stop-line B 选项 真 BUG only"经验，每个 PR 严格 1-2 轮 reviewer，不展开 P2/P3 nitpick 套娃。
