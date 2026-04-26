# toxiproxy 测试设施（Sprint F2）

> Sprint F2 阶段 — **仅设施**。不接入任何 Tier 1 测试套件。
> 等 §19 二次审查通过后再考虑接入 Tier 1 故障注入测试。

## 1. 启动

```bash
# 与主 dev compose 组合启动（生产用法）
docker compose \
  -f infra/docker/docker-compose.dev.yml \
  -f infra/docker/docker-compose.toxiproxy.yml \
  up -d toxiproxy

# 单独启动（仅做设施自检时）
docker compose -f infra/docker/docker-compose.toxiproxy.yml up -d
```

确认 admin 在线：

```bash
curl -s http://localhost:8474/proxies | python3 -m json.tool
```

## 2. 三个预置代理

| 代理名 | 监听端口 | 上游 | 用途 |
|---|---|---|---|
| `pg_proxy` | 9001 | `postgres:5432` | 注入 DB 高延迟 / 断网 / 慢查询场景 |
| `redis_proxy` | 9002 | `redis:6379` | 注入消息队列阻塞 / 缓存抖动 |
| `coreml_proxy` | 9003 | `host.docker.internal:8100` | 注入 Mac mini Core ML 桥接故障 |

> 服务级代理（`tx-trade:18001` 等）由 Sprint A2 维护，不在 F2 改动范围内。

## 3. pytest fixture 用法

```python
import pytest
from shared.test_infra.fixtures import toxiproxy  # noqa: F401

@pytest.mark.toxiproxy_required
@pytest.mark.asyncio
async def test_some_scenario(toxiproxy):
    await toxiproxy.add_latency("pg_proxy", ms=500, jitter_ms=50)
    # ... 跑测试 ...
    # fixture 在 yield 后自动 reset，无需手动清理
```

**关键约定：**
- 凡使用此 fixture 的测试必须打 `@pytest.mark.toxiproxy_required`，CI 在容器未启动时会自动 skip
- fixture 自动调用 `toxiproxy.reset()`，所以测试间无 toxic 残留
- 不要在 Tier 1 测试套件里使用此 fixture（参见 §19 红线）

## 4. 三个典型场景

### 场景 A：60 秒断网

```python
await toxiproxy.disable("pg_proxy")
await asyncio.sleep(60)
await toxiproxy.enable("pg_proxy")
```

### 场景 B：高延迟（500ms）

```python
await toxiproxy.add_latency("pg_proxy", ms=500, jitter_ms=50)
# 模拟跨机房或恶劣 4G 链路
```

### 场景 C：30% 丢包

```python
await toxiproxy.add_packet_loss("redis_proxy", percent=30)
# 30% 概率连接立即断开（toxiproxy 用 timeout=0 + toxicity 实现）
```

## 5. 后续接入 Tier 1 测试的路径

**当前阶段（W7）：禁止接入 Tier 1。**

未来接入流程：
1. Tier 1 测试套件本身先通过 §19 独立验证审查
2. 提交 RFC：明确要在哪些 Tier 1 路径注入哪些故障、验收标准
3. 创始人签字（参考 CLAUDE.md §17 Tier 1 验收标准）
4. 在 nightly job（不在 PR gate）跑故障注入测试，连续 3 日绿后纳入 Week 8 Go/No-Go

## 6. 单元测试 + 烟测

```bash
# 单元测试（不需要 toxiproxy 容器，CI PR gate 跑）
pytest shared/test_infra/tests/test_toxiproxy_client.py

# 烟测（需要 toxiproxy 容器在线，仅手动 workflow_dispatch）
docker compose -f infra/docker/docker-compose.toxiproxy.yml up -d
pytest -m toxiproxy_required shared/test_infra/tests/test_toxiproxy_smoke.py
```

CI workflow：`.github/workflows/toxiproxy-smoke.yml`（手动触发）。

## 7. 故障排查

| 现象 | 原因 | 修复 |
|---|---|---|
| `toxiproxy unreachable` | 容器未启动 | `docker compose -f ...toxiproxy.yml up -d` |
| 9001/9002/9003 端口冲突 | 宿主机占用 | `lsof -i :9001` 找进程，或改 docker-compose ports |
| `host.docker.internal` 无法解析 | Linux 默认无此 alias | 已加 `extra_hosts: host-gateway`，重启容器即可 |
| 测试报 `proxy busy` | 上一次 toxic 残留 | fixture 会 reset；手动跑可 `curl -X POST :8474/reset` |
