# Prometheus Dev E2E Scrape Verify Runbook

**Issue:** #831  
**Tier:** T2 ops/infra  
**Last updated:** 2026-05-18  

验证 dev compose 环境的 Prometheus 端到端 scrape 链路可用性:
gateway + tx-trade + tx-event-relay 的 `/metrics` 端点能被 Prometheus 正常抓取 (Bearer token 鉴权)。

---

## Prerequisites

- Docker Compose v2 (`docker compose version`)
- `jq` (`brew install jq`)
- `curl`
- Python 3 (`python3 --version`)
- 仓库根目录: `tunxiang-os/`

---

## Step 1: 生成 dev bearer token

```bash
# 从仓库根执行; source 确保 PROMETHEUS_BEARER_TOKEN export 到当前 shell
source scripts/dev/setup-prometheus-token.sh
```

**⚠️ token 每次运行覆盖**: 若 backend svc 已在跑, 必须 restart 让新 token 生效 (容器内旧 token 不会自动更新):

```bash
# 首次启动 (Step 2) 无需 restart; 重新 source 后必须 restart
docker compose -f infra/compose/base.yml -f infra/compose/envs/dev.yml \
  restart gateway tx-trade tx-event-relay prometheus
```

预期输出:
```
PROMETHEUS_BEARER_TOKEN generated and exported (length=43)
Token file: .../infra/compose/envs/tx-metrics-token (chmod 600, gitignored)
```

验证 gitignore 生效 (token 文件不出现在 git status):
```bash
git status infra/compose/envs/tx-metrics-token
# 预期: 无输出 (gitignored)
```

---

## Step 2: 启动服务

```bash
docker compose \
  -f infra/compose/base.yml \
  -f infra/compose/envs/dev.yml \
  up -d postgres redis gateway tx-trade tx-event-relay prometheus
```

等待服务就绪 (约 60s):
```bash
docker compose \
  -f infra/compose/base.yml \
  -f infra/compose/envs/dev.yml \
  ps
# 期望 gateway/tx-trade/tx-event-relay/prometheus 全部 running
```

---

## Step 3: 健康检查 (三服务)

```bash
TOKEN=$(cat infra/compose/envs/tx-metrics-token)

# gateway
curl -sf http://localhost:8000/health | jq '.ok'
# tx-trade
curl -sf http://localhost:8001/health | jq '.ok'
# tx-event-relay
curl -sf http://localhost:8020/health | jq '.ok'
```

预期全部返回 `true`。

---

## Step 4: 直接 scrape 后端 /metrics (验证 Bearer 鉴权)

```bash
TOKEN=$(cat infra/compose/envs/tx-metrics-token)

# gateway /metrics (须 Bearer token)
curl -sf -H "Authorization: Bearer ${TOKEN}" \
  http://localhost:8000/metrics | grep -m 3 "python_info\|process_"

# tx-trade /metrics
curl -sf -H "Authorization: Bearer ${TOKEN}" \
  http://localhost:8001/metrics | grep -m 3 "python_info\|process_"

# tx-event-relay /metrics (outbox relay 专属指标)
curl -sf -H "Authorization: Bearer ${TOKEN}" \
  http://localhost:8020/metrics | grep "tx_event_relay_"
```

预期: 每条命令有输出 (>0 行)。
无 token 时应返回 403:
```bash
curl -si http://localhost:8020/metrics | head -1
# 预期: HTTP/1.1 403 Forbidden
```

---

## Step 5: Prometheus targets 健康 verify

```bash
curl -sf http://localhost:9090/api/v1/targets \
  | jq '[.data.activeTargets[] | select(.labels.job | test("tunxiang-gateway|tunxiang-tx-trade|tunxiang-tx-event-relay")) | {job: .labels.job, health: .health}]'
```

预期:
```json
[
  {"job": "tunxiang-gateway",         "health": "up"},
  {"job": "tunxiang-tx-trade",        "health": "up"},
  {"job": "tunxiang-tx-event-relay",  "health": "up"}
]
```

如果 health 为 "down", 查看 lastError:
```bash
curl -sf http://localhost:9090/api/v1/targets \
  | jq '[.data.activeTargets[] | select(.health == "down") | {job: .labels.job, lastError: .lastError}]'
```

---

## Step 6: Seed emit_event 真触发 `tx_events_emit_total` Counter (必选, issue #831 验收)

`tx_events_emit_total` 由 `shared/events/src/emitter.py` 注册, 当任何服务调用
`emit_event()` 时递增。**Issue #831 验收明确要求 `tx_events_emit_total` 非空 vector "至少 tx-trade emit_event 样本"**, 不能仅靠 `tx_event_relay_outbox_pending_count` (relay 指标) 替代。

### Step 6a (必选): 通过 tx-trade 业务路径触发 emit_event

dev 环境通过 tx-trade settle 或 cashier 路径下一笔测试订单, 触发 ORDER.PAID/DISCOUNT.APPLIED/PAYMENT.CONFIRMED 事件:

```bash
# 选项 1: 直接调用 tx-trade 测试 fixture (推荐 dev 环境)
docker compose -f infra/compose/base.yml -f infra/compose/envs/dev.yml \
  exec tx-trade python -c "
import asyncio
from shared.events.src.emitter import emit_event
from shared.events.src.event_types import OrderEventType
asyncio.run(emit_event(
    event_type=OrderEventType.PAID,
    tenant_id='00000000-0000-0000-0000-000000000001',
    stream_id='dev-test-order-001',
    payload={'total_fen': 100},
    source_service='tx-trade',
))
print('emit_event dispatched')
"

# 选项 2: HTTP 调用 cashier endpoint (若 dev 已 seed 测试数据)
# curl -sf -X POST http://localhost:8001/api/v1/dev/seed-emit-event \
#   -H "X-Tenant-ID: 00000000-0000-0000-0000-000000000001"
```

等待 Prometheus 下一轮 scrape (默认 15s) 后查询:

```bash
curl -sf "http://localhost:9090/api/v1/query?query=tx_events_emit_total" \
  | jq '.data.result'
# 预期: [{"metric":{"__name__":"tx_events_emit_total","event_type":"order.paid",...},"value":[<ts>,"1"]}]
# **必须非空 vector**, 否则验收 fail (回查 tx-trade /metrics 是否真见 Counter)
```

### Step 6b (辅助): relay 自身指标 (无 emit_event 即有值)

```bash
curl -sf "http://localhost:9090/api/v1/query?query=tx_event_relay_outbox_pending_count" \
  | jq '.data.result'
# 预期: [{...,"value":[timestamp,"0"]}] (shadow 期间 outbox 表为空, count=0)
```

**验收硬约束** (本 PR ship 前 §19 reviewer 真跑 verify): Step 6a 必须见 `tx_events_emit_total` 非空 vector。若仅靠 Step 6b 通过, 是 P1 漂移 (per `feedback_metric_counter_ship_unblock_e2e_scrape.md` lesson — Counter 加了等于没加直到真业务流量触发 + Prometheus 真 scrape 到非空 vector)。

---

## Step 7: Prometheus UI (可选)

浏览器打开 http://localhost:9090

- Status > Targets: 确认三 job 绿色
- Graph: 输入 `tx_event_relay_outbox_pending_count` → Execute

---

## 常见故障排查

### 401 / 403 on /metrics

```bash
# 检查 PROMETHEUS_BEARER_TOKEN 是否正确 export
echo ${PROMETHEUS_BEARER_TOKEN:0:8}...  # 显示前 8 字符

# 检查 token 文件内容与 env 一致
diff <(echo "$PROMETHEUS_BEARER_TOKEN") <(cat infra/compose/envs/tx-metrics-token)
# 预期: 无差异

# 重新 source token
source scripts/dev/setup-prometheus-token.sh
docker compose -f infra/compose/base.yml -f infra/compose/envs/dev.yml restart gateway tx-trade tx-event-relay
```

### 9090 端口已占用

```bash
lsof -i :9090
# 找到占用进程 PID 并 kill, 或修改 dev.yml prometheus ports 到其他端口
```

### Prometheus target health=down lastError: 401

token 文件路径不匹配。检查 prometheus 容器内 token 文件:
```bash
docker compose -f infra/compose/base.yml -f infra/compose/envs/dev.yml \
  exec prometheus cat /etc/prometheus/secrets/tx-metrics-token
```
若文件不存在或内容错误, 重跑 `source scripts/dev/setup-prometheus-token.sh` + 重启 prometheus。

### 服务 network 不通 (connection refused)

确认 prometheus 与 backend svc 在同一 txos-net:
```bash
docker compose -f infra/compose/base.yml -f infra/compose/envs/dev.yml \
  exec prometheus wget -qO- http://gateway:8000/health
# 预期: {"ok": true, ...}
```

---

## Cleanup

```bash
docker compose \
  -f infra/compose/base.yml \
  -f infra/compose/envs/dev.yml \
  down -v
```

`-v` 删除 named volumes (pg_data/redis_data)。如需保留数据去掉 `-v`。

---

## Follow-up

- Issue: GHA nightly e2e workflow (`act` 本地预验证 + dev compose 全栈启动 + scrape verify, ~5-10 min CI 时间)
