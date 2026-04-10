# 屯象OS 监控栈

基于 Prometheus + Grafana 的可观测性方案，覆盖全部13个后端服务、Redis、PostgreSQL及Agent体系。

## 快速启动

```bash
# 在 infra/monitoring 目录下执行
docker-compose -f docker-compose.monitoring.yml up -d
```

## 访问地址

| 服务 | 地址 | 说明 |
|------|------|------|
| Prometheus | http://localhost:9090 | 指标采集与查询 |
| Grafana | http://localhost:3000 | 可视化仪表板（admin/tunxiang2024） |
| Redis Exporter | http://localhost:9121/metrics | Redis指标 |
| PostgreSQL Exporter | http://localhost:9187/metrics | PG指标 |

**注意：生产环境必须修改 `GF_SECURITY_ADMIN_PASSWORD`，使用 Docker Secret 或环境变量注入。**

## 目录结构

```
infra/monitoring/
├── docker-compose.monitoring.yml     # 监控栈编排
├── prometheus/
│   ├── prometheus.yml                # Prometheus主配置（13服务scrape）
│   └── rules/
│       └── tunxiang-alerts.yml       # 告警规则（ServiceDown/HighErrorRate等）
└── grafana/
    ├── dashboards/
    │   ├── tunxiang-overview.json    # 服务总览仪表板
    │   └── tunxiang-agents.json      # Agent体系专用仪表板
    └── provisioning/                 # Grafana自动配置（按需添加datasource/dashboard provisioning）
```

## 仪表板说明

### tunxiang-overview（服务总览）
- 全部13个服务 UP/DOWN 状态矩阵
- 请求 QPS 趋势（按服务分色）
- P99 延迟趋势
- 5xx 错误率趋势
- PostgreSQL 连接数（含上限参考线）
- Redis 内存使用率 Gauge
- LLM API 调用次数与成本估算（Claude 3.5 Sonnet 计价）

### tunxiang-agents（Agent体系）
- 各 Agent 触发次数（按 agent_type，24h 柱状图）
- Agent 执行成功率（按类型，Gauge）
- L1/L2/L3 自治级别分布（饼图 + 趋势）
- LLM Token 消耗趋势（输入/输出分开）
- Agent 决策延迟 P50/P99
- Feature Flag 开启状态（stat面板，ON/OFF显色）
- LLM 成本估算（1h / 24h）

## 告警规则

| 告警名 | 触发条件 | 严重级别 |
|--------|----------|----------|
| ServiceDown | 任意服务 `up==0` 持续1分钟 | critical |
| HighResponseTime | P99延迟 > 2s 持续5分钟 | warning |
| HighErrorRate | 5xx错误率 > 5% 持续5分钟 | critical |
| DBPoolExhausted | DB连接池可用数为0 持续2分钟 | critical |
| LLMAPIFailure | LLM API错误率 > 0.1/s 持续3分钟 | warning |
| RedisHighMemory | Redis内存使用率 > 85% 持续5分钟 | warning |
| OrderProcessingDelay | 订单处理P99 > 5s 持续3分钟 | warning |
| PostgreSQLHighConnections | PG连接数 > 150 持续5分钟 | warning |
| AgentHighFailureRate | Agent失败率 > 10% 持续5分钟 | warning |

## 生产环境配置要点

1. **密码安全**：绝不使用默认密码，通过 Docker Secret 或 K8s Secret 注入。
2. **TLS**：在 Grafana 前加 nginx/traefik 反向代理并配置 HTTPS。
3. **持久化存储**：生产环境将 `prometheus_data` 和 `grafana_data` 挂载到持久化 Volume（或对象存储）。
4. **Prometheus 数据保留**：当前设置为30天，生产可根据需求调整 `--storage.tsdb.retention.time`。
5. **告警通知**：在 Prometheus 配置 `alertmanager` 并接入钉钉/企业微信/PagerDuty。

## K8s 部署

生产 K8s 集群推荐使用 **kube-prometheus-stack** Helm Chart：

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --values values-tunxiang.yaml
```

将 `grafana/dashboards/*.json` 通过 ConfigMap 挂载到 Grafana，或使用 Grafana 的 Sidecar 自动发现机制。

## 为各服务接入 /metrics 端点

各 Python 服务需安装 `prometheus-fastapi-instrumentator`：

```bash
pip install prometheus-fastapi-instrumentator
```

在 `main.py` 中添加：

```python
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(...)
Instrumentator().instrument(app).expose(app)
```

这会自动在 `/metrics` 端点暴露 HTTP 请求相关指标（QPS、延迟直方图、错误率）。
