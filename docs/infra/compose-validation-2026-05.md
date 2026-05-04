# Compose 全矩阵自检结果 — 2026-05-04

> P0.5 阶段 E。验证所有 base + env / base + env + tenant / base + env + special 组合在 `docker compose config` 阶段全部通过。

## 验证环境
- Docker Compose: v5.0.2
- 工作目录: `/Users/lichun/.tunxiang-p0-worktrees/compose`
- 分支: `feat/p0-compose-consolidation`

## 必填环境变量（用最小占位测试）

```bash
export DATABASE_URL=postgresql://x@x/x
export POSTGRES_USER=tunxiang
export POSTGRES_PASSWORD=x
export POSTGRES_DB=tunxiang_os
export TX_JWT_SECRET_KEY=x
export DEVFORGE_DATABASE_URL=postgresql://x@x/x
export REDIS_PASSWORD=p
```

## 矩阵结果

| # | 组合 | 命令 | 结果 |
|---|------|------|------|
| 1 | base | `docker compose -f infra/compose/base.yml config` | ✅ OK |
| 2 | base + dev | `... -f infra/compose/envs/dev.yml config` | ✅ OK |
| 3 | base + staging | `... -f infra/compose/envs/staging.yml config` | ✅ OK |
| 4 | base + prod | `... -f infra/compose/envs/prod.yml config` | ✅ OK |
| 5 | base + demo | `... -f infra/compose/envs/demo.yml config` | ✅ OK |
| 6 | base + gray | `... -f infra/compose/envs/gray.yml config` | ✅ OK |
| 7 | base + demo + czyz | `... -f infra/compose/tenants/czyz.yml config` | ✅ OK |
| 8 | base + demo + zqx | `... -f infra/compose/tenants/zqx.yml config` | ✅ OK |
| 9 | base + demo + sgc | `... -f infra/compose/tenants/sgc.yml config` | ✅ OK |
| 10 | base + dev + resource-limits | `... -f infra/compose/special/resource-limits.yml config` | ✅ OK |
| 11 | base + dev + toxiproxy | `... -f infra/compose/special/toxiproxy.yml config` | ✅ OK |

**11/11 通过。** 全部 config 校验返回 exit 0。

## 不在矩阵的组合（已验证不会同时使用）
- prod + tenants：tenants 设计上只与 demo 叠加（业务定义为客户演示环境）
- gray + tenants：gray 走 host 网络复用生产 PG，与租户独立 DB 互斥
- prod + special/toxiproxy：toxiproxy 仅用于 dev/staging 故障注入
- prod + resource-limits + toxiproxy：未来需要测试 prod 压测时再单独验证

## 关键决策落地的 yaml 验证点
- gray.yml 的 `network_mode: host` + `networks: !reset null` 已在每个 service 显式声明（19 处），合并 base 后无 mutually exclusive 冲突
- 所有 service 含 `labels.tunxiang.env=${TUNXIANG_ENV:-…}`，`docker ps --filter "label=tunxiang.env=dev"` 可定位
- prod.yml 内 `postgres-replica` 是 base 之外新增 service（不修改 base 的 postgres）
- tenants/*.yml 用 `ports: !override` 替换 base 的 ports 数组，避免端口列表合并污染

## 后续 CI 接入提示
本次未改动 `.github/workflows/`。当 CI 切换至新路径时，建议先用本表的 11 项作为 CI 冒烟。

## 端口最终分配
见 `docs/infra/port-allocation-2026-05.md`。
