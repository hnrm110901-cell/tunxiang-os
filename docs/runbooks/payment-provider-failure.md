# 支付渠道故障应急 Runbook

> 版本: 1.0 | 创建: 2026-05-05 | 维护人: 屯象OS Ops 团队
>
> 适用：tx-pay / tx-trade Saga 链路上任一渠道（微信 / 支付宝 / 拉卡拉 / 收钱吧 / 现金
> / 储值 / 信用挂账）故障，且 `PaymentSuccessRateLow` / `PaymentSagaCompensationSpike`
> / `PaymentTrafficStalled` / `PaymentChannelHighErrorRate` 任一告警 firing 时启动。
>
> 关联：审计 OPS-007（cutover 阶段 E 必备）；PR #195 SLO 告警规则；PR #200 渠道指标。
> 核心代码：`services/tx-trade/src/services/payment_saga_service.py:288 compensate()`。
>
> ⚠️ Tier 1 Runbook（CLAUDE.md §17）。**资金安全 + 客户体验 双红线**：
> 任何补偿动作前必须先核对渠道侧扣款状态，宁可慢 5 分钟也不可错发退款。
>
> 目标：凌晨 3 点 oncall 拿到这份文档，10 分钟内完成「检测 → 降级 → 公告」三步。

---

## 目录

- [§1 故障检测信号](#1-故障检测信号)
- [§2 紧急降级（5 分钟内做完）](#2-紧急降级5-分钟内做完)
- [§3 Saga 补偿命令（运维数据库操作）](#3-saga-补偿命令运维数据库操作)
- [§4 与渠道方沟通流程](#4-与渠道方沟通流程)
- [§5 恢复验证 checklist](#5-恢复验证-checklist)
- [§6 事后追溯](#6-事后追溯)
- [§7 紧急联系矩阵](#7-紧急联系矩阵)
- [§8 相关文档与代码](#8-相关文档与代码)
- [附录 A 待补充占位项汇总](#附录-a-待补充占位项汇总)

---

## §1 故障检测信号

任意一项告警 firing 都视为进入故障态，**立刻进入 §2 降级流程，不要先排查根因**。

### 1.1 四大告警速查表

告警源：`infra/monitoring/prometheus/rules/tunxiang-alerts.yml`

| 告警名 | 表达式（要点） | for | severity | 行号 |
|---|---|---|---|---|
| `PaymentSuccessRateLow` | `success / total < 0.999`（Tier 1 红线） | 10m | critical | :124 |
| `PaymentSagaCompensationSpike` | `rate(payment_saga_compensated_total[5m]) > 0.05` | 3m | warning | :139 |
| `PaymentTrafficStalled` | `sum(rate(payment_saga_total[5m])) == 0` | 5m | critical | :150 |
| `PaymentChannelHighErrorRate` | `5xx / total > 0.01` by `channel` | 5m | warning | :161 |

`channel` label 取值：`wechat` / `alipay` / `lakala` / `shouqianba` / `stored_value` / `cash` /
`credit_account`（见 `services/tx-pay/src/channels/*.py` 中 `payment_channel_requests_total.labels(channel=...)`）。

### 1.2 日志 grep 关键字

```bash
# Saga 失败 / 补偿主链路（tx-trade）
docker compose logs --since 15m tx-trade \
  | grep -E "saga_(s2_failed|s3_failed|compensating|compensated|refund_failed)"

# 按补偿原因分组（看 PaymentSagaCompensationSpike 时用）
docker compose logs --since 15m tx-trade \
  | grep -E "saga_compensated" | awk -F'reason=' '{print $2}' | sort | uniq -c | sort -rn

# 按渠道 5xx / timeout（替换 wechat/alipay/lakala/shouqianba）
docker compose logs --since 15m tx-pay | grep -E "wechat.*(timeout|connect_error|5\d\d)"

# Stalled 时看入口是否还在收请求
docker compose logs --since 5m gateway tx-trade tx-pay \
  | grep -E "POST /api/v1/(settle|pay)|saga_created" | tail -50
```

K8s 部署用 `kubectl logs -n tunxiang -l app=tx-trade --since=15m | grep ...` 替代。

### 1.3 客户感知现象

- 收银员点"确认收款"后 POS 转圈 30 秒以上，最终弹"支付失败"
- 顾客微信/支付宝已扣款，但 POS 订单仍显示"待支付"（payment_id 已生成但 saga 卡 paying/completing）
- 顾客付款成功后订单又被自动退款（补偿激增的客户感知）
- 收银员屏幕反复弹"订单回滚"，桌位状态从 occupied 跳回 available
- 整店所有 POS 都收不了款（`PaymentTrafficStalled`，业务高峰几乎一定 P0）

### 1.4 信号联动判断

| 同时 firing | 推断形态 | 进入 |
|---|---|---|
| 仅 `PaymentChannelHighErrorRate{channel="wechat"}` | 微信单挂 | §2.1 |
| 仅 `PaymentChannelHighErrorRate{channel="alipay"}` | 支付宝单挂 | §2.2 |
| 多 channel 同时 5xx + `PaymentSuccessRateLow` | 全渠道扫码故障 / 网络出口挂 | §2.3 |
| 仅 `PaymentTrafficStalled` | 网关或 tx-trade/tx-pay 进程挂 | **不是渠道故障**，走 cutover runbook |
| `PaymentSagaCompensationSpike` 单独 firing | 渠道扣款成功但 S3 失败 | §3：先冻结自动补偿，避免误退款 |

---

## §2 紧急降级（5 分钟内做完）

**行动顺序铁律**：先公告（让一线知道发生什么）→ 再切渠道 → 再处理存量（§3）。
顺序颠倒会让收银员还在用挂掉的渠道收款，事态扩大。

### 2.1 微信支付故障 → 降级支付宝/拉卡拉/现金

```bash
# Step 1: Harness FF 关闭微信渠道入口
curl -X PATCH "https://app.harness.io/cf/admin/features/ff_pay_channel_wechat/environments/env_prod" \
  -H "x-api-key: ${HARNESS_API_KEY}" -H "Content-Type: application/json" \
  -d '{"state": "off"}'

# Step 2: mac-station 广播弹窗到本店所有 POS
curl -X POST "http://<mac-mini-ip>:8000/api/v1/broadcast" \
  -H "X-Tenant-ID: ${TENANT_ID}" -H "Content-Type: application/json" \
  -d '{"level":"warn","title":"微信支付暂时不可用",
       "body":"请引导顾客改用支付宝或现金。预计恢复时间见 oncall 通知。",
       "ttl_sec":1800}'
```

> Flag `ff_pay_channel_wechat`：`<待补充：实际 Harness flag key 由 ops 团队创建后回填，
> 参见 docs/feature-flag-runbook.md>`

**给顾客的话术**（复制到 POS 弹窗 + 桌贴）：

> 「不好意思，微信支付暂时不可用，请尝试支付宝或现金，给您带来不便深表歉意。
> 您也可以使用银联卡刷卡支付。」

**收银员侧操作**：

1. 顾客付款方式选择页 → **不要选微信支付**（按钮已置灰）
2. 引导出示支付宝付款码 → 扫码 → 等待提示音
3. 顾客坚持要用微信：收等额现金（精确到分） → 订单备注「微信故障期间收现金 ¥XX.XX，待恢复后补 e 票」 → 钱箱抽屉点"开钱箱"（`TXBridge.openCashBox()`）
4. 顾客需要电子发票：加微信，故障恢复后通过 `/api/v1/finance/manual-invoice` 补开

### 2.2 支付宝故障 → 降级微信/拉卡拉/现金

操作与 §2.1 完全对称，仅替换 flag 与话术：

```bash
curl -X PATCH "https://app.harness.io/cf/admin/features/ff_pay_channel_alipay/environments/env_prod" \
  -H "x-api-key: ${HARNESS_API_KEY}" -H "Content-Type: application/json" -d '{"state":"off"}'
```

> Flag `ff_pay_channel_alipay`：`<待补充：与 wechat 同步在 Harness 创建>`

话术：「不好意思，支付宝暂时不可用，请尝试微信支付或现金，给您带来不便深表歉意。」

### 2.3 全渠道扫码故障 → 现金 + 银联刷卡

触发条件：3 个以上渠道同时 firing `PaymentChannelHighErrorRate`，或本店出口网络异常。

```bash
# Step 1: 一次性关掉所有扫码渠道
for FLAG in ff_pay_channel_wechat ff_pay_channel_alipay ff_pay_channel_lakala ff_pay_channel_shouqianba; do
  curl -X PATCH "https://app.harness.io/cf/admin/features/${FLAG}/environments/env_prod" \
    -H "x-api-key: ${HARNESS_API_KEY}" -H "Content-Type: application/json" \
    -d '{"state":"off"}'
done

# Step 2: 启用「现金优先 + 银联兜底」模式
curl -X PATCH "https://app.harness.io/cf/admin/features/ff_pay_mode_offline_only/environments/env_prod" \
  -H "x-api-key: ${HARNESS_API_KEY}" -H "Content-Type: application/json" \
  -d '{"state":"on"}'
```

> Flag `ff_pay_mode_offline_only`：`<待补充：定义为仅显示 cash + unionpay 渠道>`

**银联刷卡机走法**（独立物理终端，不依赖屯象OS）：

1. POS 屏幕保留菜单总价 → **不要按"确认收款"**
2. 物理刷卡机输入金额（分） → 顾客插卡/挥卡 → 等待打印小票
3. 收银员手抄物理小票交易号到 POS 订单备注：「UNIONPAY-OFFLINE-{8 位流水}」
4. POS 上点"现金等额标记" → 订单标记为已结
5. 物理小票联与现金一同入账

话术：「您好，目前所有手机支付暂时不可用。我们可以收现金或银联卡（刷卡机），
请问您方便用哪一种？给您带来不便深表歉意。」

### 2.4 现金 / 线下交易后续手工录入

故障期间收的所有现金 / 线下交易，恢复后必须在 24 小时内回灌系统：

```bash
curl -X POST "https://api.tunxiang.cn/api/v1/trade/manual-settle" \
  -H "X-Tenant-ID: ${TENANT_ID}" -H "Authorization: Bearer ${OPS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"order_id":"<订单ID>","amount_fen":8800,"channel":"cash",
       "operator_id":"<收银员ID>","manual_reason":"微信故障期间现金收款 2026-05-05 22:30",
       "external_ref":"PHYSICAL-RECEIPT-XXXX"}'
```

> 端点 `/api/v1/trade/manual-settle`：`<待补充：当前未实现，OPS-007 follow-up，
> 由 tx-trade 团队按本节契约补丁交付。临时降级用 tx-finance 后台手工补单功能>`

---

## §3 Saga 补偿命令（运维数据库操作）

⚠️ **资金安全红线**：补偿前**必须**先到渠道方核对实际扣款状态（§3.2），否则可能对未扣款
Saga 误发退款，导致客户被退两次或我方账面缺口。

### 3.1 查询挂起 Saga（first thing to run）

```sql
-- 连入云端 PG（堡垒机已配置 .pgpass）
PGPASSWORD=$(security find-generic-password -s tunxiang-prod-pg -w) \
  psql -h prod-pg.tunxiang.cn -U ops_readonly -d tunxiang -p 5432

-- 查超过 5 分钟仍处于中间态的 Saga
SELECT saga_id, step, payment_id, payment_amount_fen, payment_method,
       tenant_id, order_id, created_at, updated_at,
       EXTRACT(EPOCH FROM (NOW() - updated_at))::int AS stuck_sec
FROM payment_sagas
WHERE step IN ('paying', 'completing')
  AND updated_at < NOW() - INTERVAL '5 minutes'
ORDER BY created_at;
```

判读：

| step | payment_id | 含义 | 后续 |
|---|---|---|---|
| `paying` | NULL | S2 没成功，渠道大概率没扣款 | §3.3 标记 failed，不退款 |
| `paying` | NOT NULL | S2 已成功（已扣款），卡未推进到 completing | §3.4 推进 S3，失败再补偿 |
| `completing` | NOT NULL | S2 已成功，S3 失败 | §3.4 补偿（退款 + compensated） |

### 3.2 与渠道方账实对账（补偿前必做）

```bash
# 用 payment_id 查渠道侧实际状态（透传 BasePaymentChannel.query()，不修改任何状态）
curl -X POST "https://gateway.tunxiang.cn/api/v1/pay/query" \
  -H "X-Tenant-ID: ${TENANT_ID}" -H "Authorization: Bearer ${OPS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"payment_id":"WX20260505220301AB12CD"}'
```

返回 `status=SUCCESS` → 渠道已扣款，可退款；`NOTPAY` / `CLOSED` → 渠道未扣款，
**禁止退款**，直接 §3.3 标 failed。端点见 `services/tx-pay/src/api/payment_routes.py:122`。

### 3.3 标记未扣款 Saga 为 failed（无副作用）

```sql
BEGIN;
UPDATE payment_sagas
SET step = 'failed',
    compensation_reason = 'OPS-rb-' || NOW()::date || ' 渠道故障期间崩溃恢复 — paying 无 payment_id',
    updated_at = NOW()
WHERE saga_id = '<SAGA_ID>'
  AND tenant_id = '<TENANT_ID>'
  AND step = 'paying'
  AND payment_id IS NULL;
-- rowcount != 1 → ROLLBACK；rowcount = 1 → COMMIT
COMMIT;
```

### 3.4 已扣款 Saga 手动补偿

⚠️ 必须先做完 §3.2 渠道侧账实对账，确认 `status=SUCCESS` 后才进入。

#### 方案 A（推荐，未实现）：tx-trade 管理端点

```bash
curl -X POST "https://gateway.tunxiang.cn/api/v1/saga/${SAGA_ID}/compensate" \
  -H "X-Tenant-ID: ${TENANT_ID}" -H "Authorization: Bearer ${OPS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"reason":"OPS-rb 渠道故障期间手动补偿"}'
```

> **当前未实现。** `<待补充：OPS-007 follow-up — tx-trade 加 routes/saga_admin.py，
> 仅 OPS_TOKEN 可调用，透传 PaymentSagaService.compensate(saga_id, reason)
> （payment_saga_service.py:288），幂等 + 审计日志 saga_compensate_manual_invoked>`

#### 方案 B（当前唯一可行）：SQL UPDATE + tx-pay refund API

```bash
# Step 1: 标记 saga 为 compensating（防并发）
psql -h prod-pg.tunxiang.cn -U ops -d tunxiang <<SQL
BEGIN;
UPDATE payment_sagas
SET step='compensating', compensation_reason='OPS-rb manual', updated_at=NOW()
WHERE saga_id='${SAGA_ID}' AND tenant_id='${TENANT_ID}'
  AND step IN ('paying','completing');
-- rowcount=1 才 COMMIT
COMMIT;
SQL

# Step 2: 取 payment_id / amount，调 tx-pay refund
PAYMENT_ID=$(psql -h prod-pg.tunxiang.cn -U ops -d tunxiang -At \
  -c "SELECT payment_id FROM payment_sagas WHERE saga_id='${SAGA_ID}' AND tenant_id='${TENANT_ID}'")
AMOUNT_FEN=$(psql -h prod-pg.tunxiang.cn -U ops -d tunxiang -At \
  -c "SELECT payment_amount_fen FROM payment_sagas WHERE saga_id='${SAGA_ID}' AND tenant_id='${TENANT_ID}'")

curl -X POST "https://gateway.tunxiang.cn/api/v1/pay/refund" \
  -H "X-Tenant-ID: ${TENANT_ID}" -H "Authorization: Bearer ${OPS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"payment_id\":\"${PAYMENT_ID}\",\"refund_amount_fen\":${AMOUNT_FEN},
       \"reason\":\"OPS-rb manual compensation ${SAGA_ID}\"}"

# Step 3a: refund 成功 → 标 compensated
psql -h prod-pg.tunxiang.cn -U ops -d tunxiang <<SQL
UPDATE payment_sagas
SET step='compensated', compensated_at=NOW(),
    compensation_reason=compensation_reason || ' | refund_id=${REFUND_ID}',
    updated_at=NOW()
WHERE saga_id='${SAGA_ID}' AND tenant_id='${TENANT_ID}' AND step='compensating';
SQL

# Step 3b: refund 失败 → 标 failed（人工介入）
psql -h prod-pg.tunxiang.cn -U ops -d tunxiang <<SQL
UPDATE payment_sagas
SET step='failed',
    compensation_reason=compensation_reason || ' | refund_failed: <错误原因>',
    updated_at=NOW()
WHERE saga_id='${SAGA_ID}' AND tenant_id='${TENANT_ID}' AND step='compensating';
SQL
```

退款 API 见 `services/tx-pay/src/api/payment_routes.py:135 refund_payment`。

### 3.5 验证补偿结果

```sql
-- 1. saga 终态：期望 step='compensated', compensated_at IS NOT NULL
SELECT saga_id, step, compensation_reason, compensated_at, payment_id
FROM payment_sagas WHERE saga_id='<SAGA_ID>' AND tenant_id='<TENANT_ID>';

-- 2. payments 表退款记录：期望 refund_amount_fen > 0
SELECT id, status, refund_amount_fen, refunded_at
FROM payments WHERE id='<PAYMENT_ID>' AND tenant_id='<TENANT_ID>';

-- 3. 渠道侧二次核对：再调 §3.2 query API，确认 status='REFUND'
```

### 3.6 注意事项（务必念三遍）

1. **补偿前必查渠道实际状态**（§3.2）— 对未扣款 Saga 误发退款会被金税系统标红
2. **不要批量退款脚本** — 每个 Saga 单独跑一遍 §3.4，避免广播性资金事故
3. **退款金额 = 扣款金额**（保留分级精度），半退/部分退必须走另外的财务流程
4. **退款幂等**：tx-pay refund 用 `refund_id` 去重；同 saga 重复触发不会双扣（compensate() 在 payment_saga_service.py:298 已置 `compensating` 状态阻止重入）
5. **退款窗口期**：微信 1 年、支付宝 1 年、拉卡拉 6 个月。超期需走线下转账 + 财务对账

---

## §4 与渠道方沟通流程

### 4.1 渠道方对接信息

| 渠道 | 商务联系人 | 商户号 | 平台监控页 / 工单入口 | SLA |
|---|---|---|---|---|
| 微信支付 | `<待补充>` | `<从 secrets 取>` | https://pay.weixin.qq.com/ → 商户平台 / kf.qq.com 工单 | 工时 4h；P0 1h（电话商务通道升级） |
| 支付宝 | `<待补充>` | `<从 secrets 取>` | https://b.alipay.com/ → 服务中心 工单 | 4–8h；P0 同步打 95188 转商户专线 |
| 拉卡拉 | `<待补充：客户经理>` | `<从 secrets 取>` | https://www.lakala.com/（合作伙伴门户） | 4–8h；电话 95016 |
| 收钱吧 | `<待补充>` | `<从 secrets 取>` | shouqianba.com 商户后台 / 公众号在线客服 | 4h；电话 4001-200-200 |

技术接口人：`<待补充：每个渠道单独留一个>`。商户号永远不写入文档，只通过 secrets 引用。

### 4.2 故障 ticket 模板（统一格式）

```
【屯象OS - 渠道故障报障】
我方商户号：<MCH_ID>
品牌名：屯象OS / 客户：<具体品牌如尝在一起>
报障时间：YYYY-MM-DD HH:MM CST
故障开始时间：YYYY-MM-DD HH:MM CST（依 Prometheus firing 时间戳）

问题现象：
- 用户支付返回 [具体错误码 / 错误信息]
- 影响订单数（近 30min）：N 笔
- 失败率：X.X%（取 PaymentChannelHighErrorRate 当前值）

我方已尝试：
1. 通过 query API 复核 [N] 笔失败订单的实际状态
2. 临时降级到备用渠道 [支付宝/拉卡拉/现金]
3. 对挂起 Saga 执行手动补偿 N 笔

请贵方协助：
1. 商户号 <MCH_ID> 是否有限流 / 风控拦截
2. 当前是否有平台侧故障公告
3. 我方上报的失败订单（附件 N 笔 trade_no）是否可在贵方查到

我方对接技术：<姓名 + 手机 + 邮箱>
报障渠道：<工单 ID / 邮件主题 / 微信群通知时间戳>
```

### 4.3 升级规则

- **P0**（影响全店收款 > 30 min）：电话联系商务，要求 1 小时内反馈
- **P1**（单渠道异常 < 30 min）：工单 + 商务微信，4 小时内反馈
- **P2**（局部异常 < 5%）：仅工单通报
- 任何 P0/P1 必须同步抄送 `<待补充：CTO/创始人企微>`

---

## §5 恢复验证 checklist

渠道方反馈"已恢复"后，**不要直接全量放开**，按本 checklist 逐项验证。

### Step 1 — Prometheus 告警全部 recover

```bash
curl -s "https://prometheus.tunxiang.cn/api/v1/alerts" \
  | jq '.data.alerts[] | select(.labels.alertname | startswith("Payment"))
       | {alert: .labels.alertname, state: .state, since: .activeAt}'
```

- [ ] `PaymentSuccessRateLow` not firing
- [ ] `PaymentSagaCompensationSpike` not firing
- [ ] `PaymentTrafficStalled` not firing
- [ ] `PaymentChannelHighErrorRate{channel="<故障渠道>"}` not firing

### Step 2 — 真实 0.01 元小额支付端到端通过

在 oncall 自己的手机上发起 0.01 元真实支付（非 mock），走标准下单 → 收款流程，
然后用 saga 验证：

```sql
SELECT saga_id, step, payment_id FROM payment_sagas
WHERE idempotency_key='oncall-canary-<timestamp>'
ORDER BY created_at DESC LIMIT 1;
```

- [ ] 0.01 元支付返回 `step='done'`
- [ ] 顾客侧（oncall 手机）已扣款
- [ ] payment 表 `status='success'`

### Step 3 — Saga 成功率回升 > 99.9%

```bash
curl -s -G "https://prometheus.tunxiang.cn/api/v1/query" \
  --data-urlencode 'query=sum(rate(payment_saga_total{result="success"}[5m])) / sum(rate(payment_saga_total[5m]))' \
  | jq '.data.result[0].value[1]'
```

- [ ] 输出 > `0.999`，至少持续 10 分钟

### Step 4 — 渠道 5xx 率归零

```bash
curl -s -G "https://prometheus.tunxiang.cn/api/v1/query" \
  --data-urlencode 'query=sum by (channel) (rate(payment_channel_requests_total{status="5xx"}[5m]))' \
  | jq '.data.result[] | {channel: .metric.channel, rate: .value[1]}'
```

- [ ] 故障渠道 `rate ~ 0`（容忍 < 0.001）；其他渠道同样 ~ 0

### Step 5 — tx-pay /metrics 健康

```bash
curl -s "https://gateway.tunxiang.cn/tx-pay/metrics" \
  | grep -E "^(payment_channel|http_requests_total)" | head -20
```

- [ ] 端点 200；各 channel 有 fresh 增量；`db_pool_*` / `python_memory_*` 健康

### Step 6 — 收银员侧 30 分钟无新故障

- [ ] 企微通知所有店长「渠道已恢复，恢复使用」
- [ ] 30 min 内无新增「微信/支付宝转圈」反馈
- [ ] 30 min 内 `PaymentChannelHighErrorRate` 不再 firing

### Step 7 — 重开降级 flag

```bash
for FLAG in ff_pay_channel_wechat ff_pay_channel_alipay ff_pay_channel_lakala ff_pay_channel_shouqianba; do
  curl -X PATCH "https://app.harness.io/cf/admin/features/${FLAG}/environments/env_prod" \
    -H "x-api-key: ${HARNESS_API_KEY}" -d '{"state":"on"}'
done
curl -X PATCH "https://app.harness.io/cf/admin/features/ff_pay_mode_offline_only/environments/env_prod" \
  -H "x-api-key: ${HARNESS_API_KEY}" -d '{"state":"off"}'
```

- [ ] 所有 flag 状态恢复到故障前

---

## §6 事后追溯

故障关闭后 48 小时内必须完成 postmortem。Tier 1 事故同时报创始人审阅。

### 6.1 5 Why 模板

```markdown
故障摘要：YYYY-MM-DD HH:MM 起，<渠道> 持续 <分钟>，5xx 率 > 1%，
影响 <N> 笔订单，影响 GMV ¥<金额>。

Why 1: 为什么 <渠道> 5xx 率突然飙升？ → A1
Why 2: 为什么 SLO 告警迟到了 N 分钟？ → A2
Why 3: 为什么收银员没有第一时间感知？ → A3
Why 4: 为什么降级动作花了 N 分钟？ → A4
Why 5: 为什么最终的根因没有被监控覆盖？ → A5（真正的 root cause）
```

### 6.2 Postmortem 必填字段

文件：`docs/postmortems/YYYY-MM-DD-payment-<channel>-failure.md`

```markdown
# 支付渠道故障 Postmortem — YYYY-MM-DD <channel>

## 概要
- 日期：YYYY-MM-DD HH:MM ~ HH:MM CST，持续 N 分钟
- 影响范围：<受影响商户/门店列表>
- 严重等级：P0 / P1 / P2
- 主导排障：<oncall 工程师>

## 影响
- 失败订单：N 笔
- 金额损失估算：¥X（公式见 §6.3）
- 客户投诉：N
- 客户侧扣款未对应订单：是 / 否（数量）

## Root Cause
<3 句话写清最深层原因，不抄渠道方公告原文>

## 时间线
- HH:MM Prometheus firing → HH:MM oncall 介入 → HH:MM §2 降级
  → HH:MM saga 补偿完成 → HH:MM 渠道方"已恢复" → HH:MM §5 验证通过

## Lessons Learned
- 做对了什么 / 做错了什么 / 哪些信号被忽视

## Action Items（owner + due）
- [ ] [P0] <action> — owner: <name>, due: YYYY-MM-DD
- [ ] [P1] / [P2] ...

## 相关材料
- 告警截图链接 / 渠道方工单号 / DEVLOG 当日条目 / 涉及 saga_id 列表
```

### 6.3 影响金额估算公式

```
影响 GMV = 历史同时段平均 GMV × 故障时长系数 × 故障渠道占比

# 示例：12000/h × 0.583h × 65% = ¥4,547
# 实际损失 = 影响 GMV × (1 - 降级吸收率)
#         = 4547 × (1 - 0.7)  # 假设 70% 顾客接受了备用渠道
#         = ¥1,364
```

```sql
-- 历史同时段 GMV 基线（前 4 周同 DOW + 同 HH）
SELECT AVG(gmv_fen) / 100.0 AS avg_gmv_yuan_per_hour FROM (
  SELECT date_trunc('hour', paid_at) AS hour, SUM(total_fen) AS gmv_fen
  FROM payments
  WHERE tenant_id = '<TENANT_ID>'
    AND paid_at >= NOW() - INTERVAL '28 days'
    AND paid_at <  NOW() - INTERVAL '1 hour'
    AND EXTRACT(HOUR FROM paid_at) = EXTRACT(HOUR FROM NOW())
    AND EXTRACT(DOW  FROM paid_at) = EXTRACT(DOW  FROM NOW())
  GROUP BY 1
) baseline;
```

---

## §7 紧急联系矩阵

故障升级路径：oncall → release manager → 商务对接 → CTO/创始人。
联系方式占位部分由 ops 团队在 onboarding 阶段填入并定期 review（季度更新）。

| # | 角色 | 联系人 | 联系方式 | 响应时间 |
|---|---|---|---|---|
| 1 | oncall 工程师 | `<待补充：当周轮班>` | 企微「屯象 OPS 值班群」+ 手机 | < 5 分钟 |
| 2 | release manager | `<待补充>` | 企微 + 手机 | < 15 分钟 |
| 3 | tx-trade 服务负责人 | `<待补充>` | 企微 | < 30 min（业务时段）/ < 1h（非业务时段） |
| 4 | tx-pay 服务负责人 | `<待补充>` | 企微 | < 30 分钟 |
| 5 | DBA / PG oncall | `<待补充>` | 企微 + 手机 | < 15 分钟 |
| 6 | 商务（微信支付） | `<待补充>` | 微信「微信支付商务对接群」 | < 30 分钟 |
| 7 | 商务（支付宝） | `<待补充>` | 微信「支付宝商务对接群」 | < 30 分钟 |
| 8 | 商务（拉卡拉） | `<待补充>` | 微信群 + 95016 | < 30 分钟 |
| 9 | 商务（收钱吧） | `<待补充>` | 微信群 + 4001-200-200 | < 30 分钟 |
| 10 | CTO | `<待补充>` | 企微 + 手机 | < 30 分钟（P0） |
| 11 | 创始人（未了已） | `<待补充：手机>` | 企微 + 电话 | < 30 分钟（P0 影响标杆客户时） |
| 12 | 法务/财务（涉资金对账） | `<待补充>` | 企微 | 工时内 < 4h |

### 7.1 P0 升级电话顺序（口诀）

「**5 分 oncall，15 分 RM，30 分 CTO**」

- 故障 firing 5 min → 拨 oncall 工程师
- 故障 firing 15 min 未恢复 → 拨 release manager
- 故障 firing 30 min 未恢复 → 拨 CTO + 商务双线
- 故障影响标杆客户（徐记海鲜 / 尝在一起）→ 立刻通知创始人，不等时间窗

### 7.2 沟通群保留

- 故障期间所有通讯走「屯象 OPS P0 故障群」（企微），便于事后溯源
- 关键决策（降级、退款）在群内 @ release manager 二次确认后再执行
- 故障关闭后群消息归档到 `docs/postmortems/<日期>-comms.md`

---

## §8 相关文档与代码

### 8.1 关联文档

| 文档 | 路径 | 用途 |
|---|---|---|
| Cutover Playbook | `docs/runbooks/audit-2026-05-cutover.md` | `<待补充：本 runbook 应在 cutover 阶段 E 之前完成 review>` |
| RLS 强制铺开 | `docs/security/rls-force-rollout.md` | RLS 策略变更影响支付路径时联动 |
| Feature Flag Runbook | `docs/feature-flag-runbook.md` | §2 ff_pay_channel_* 的创建/管理流程 |
| 项目宪法 | `CLAUDE.md` §17（Tier 制） + §22（Week 8 验收） | 99.9% SLO 由来 |
| 财务手工冲销 | `docs/finance-manual-correction.md` | `<待补充：当前不存在，§2.4 引用的依赖>` |
| Postmortem 模板 | `docs/postmortems/_template.md` | `<待补充>` |

### 8.2 关联代码

| 模块 | 路径 | 说明 |
|---|---|---|
| Saga 主流程 | `services/tx-trade/src/services/payment_saga_service.py:91 execute()` | S0–S3 完整 Saga |
| Saga 补偿 | `payment_saga_service.py:288 compensate()` | §3.4 调用的核心方法 |
| 崩溃恢复 | `payment_saga_service.py:373 recover_pending_sagas()` | 启动时扫挂起 saga |
| Saga 指标 | `services/tx-trade/src/metrics.py` | `payment_saga_total` / `payment_saga_compensated_total` |
| 渠道指标 | `services/tx-pay/src/metrics.py` | `payment_channel_requests_total{channel,status}` |
| 渠道实现 | `services/tx-pay/src/channels/{wechat,alipay,lakala,shouqianba,cash,stored_value,credit_account}.py` | 7 渠道；`channel_name` 决定 metric label |
| 渠道注册表 | `services/tx-pay/src/channels/registry.py:25 ChannelRegistry` | §4 升级改造时定位扩展点 |
| 退款 API | `services/tx-pay/src/api/payment_routes.py:135 refund_payment` | §3.4 方案 B 调用的端点 |
| 查询 API | `services/tx-pay/src/api/payment_routes.py:122 query_payment` | §3.2 渠道侧账实对账 |
| Saga 表 schema | `shared/db-migrations/versions/v*_payment_sagas.py` | 字段定义 |

### 8.3 关联 PR

- **PR #195** `feat(tx-trade): 暴露 payment_saga Counter 指标启用 SLO 告警 [Tier1][OPS]` —
  `payment_saga_total` / `payment_saga_compensated_total`，§1 告警依赖此 PR 提供数据。
- **PR #200** `<待补充：渠道指标暴露 PR 编号>` — `payment_channel_requests_total{channel,status}`。
- 本 PR：`docs(runbooks): payment-provider-failure 渠道故障应急流程 [OPS]`（OPS-007）。

---

## 附录 A 待补充占位项汇总

按章节统计，方便接手按图索骥逐项 fill in：

| # | 占位项 | 章节 | 责任方 |
|---|---|---|---|
| 1 | `ff_pay_channel_{wechat,alipay,lakala,shouqianba}` Harness flag 实际 key | §2.1 / §2.2 / §2.3 | ops 团队 |
| 2 | `ff_pay_mode_offline_only` flag 定义与生效逻辑 | §2.3 | tx-pay 团队 |
| 3 | `/api/v1/trade/manual-settle` 端点实现 | §2.4 | tx-trade（OPS-007 follow-up） |
| 4 | `/api/v1/saga/{saga_id}/compensate` 管理端点实现 | §3.4 方案 A | tx-trade（OPS-007 follow-up） |
| 5 | `docs/finance-manual-correction.md` 文档创建 | §2.4 / §8.1 | tx-finance + ops |
| 6 | 4 个渠道方商务联系人 + 微信 + 商户号占位 | §4.1 | 商务团队（每季度 review） |
| 7 | CTO/创始人 P0 抄送企微账号 | §4.3 | ops 团队 |
| 8 | 12 项紧急联系矩阵填空（oncall + 商务 + 高管） | §7 | ops 团队 onboarding |
| 9 | `docs/runbooks/audit-2026-05-cutover.md` 创建并对齐本 runbook | §8.1 | ops + 创始人 |
| 10 | `docs/postmortems/_template.md` 模板创建 | §6 / §8.1 | ops 团队 |
| 11 | 故障 ticket 模板的"我方对接技术"占位（个人手机） | §4.2 | ops 团队 |
| 12 | PR #200（渠道指标暴露）实际 PR 编号 | §8.3 | 文档自维护 |

> 本 runbook 是「上线必备」最小可用版本。OPS-007 修复完成 = 上述 12 项占位全部 fill in
> 且演练（tabletop drill）走过一次，由 release manager 在审计任务清单 sign-off。

---

> 维护守则：
> - 渠道增删（如新接入云闪付）必须同步更新 §1 / §2 / §4 / §8.2
> - 告警阈值变更必须同步更新 §1
> - 季度 tabletop 演练后将"卡壳点"加到 §6 Lessons Learned
> - 实际故障后将关键数据（影响时长、补偿笔数）追加到本文件历史基线
