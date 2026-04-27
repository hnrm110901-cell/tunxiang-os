# tx-devforge

屯象 OS 内部研发运维平台后端 (DevForge)。端口 `:8017`。

## 用途

为屯象 OS 自身研发团队提供一站式工程运维平台：

- **应用目录 (Application Catalog)** — 统一管理 5 类资源：后端服务、前端应用、边缘镜像、适配器、数据资产。
- **CMDB / 拓扑** — 服务依赖、版本、Owner、Runbook（后续 Phase 接入）
- **CI/CD 编排** — 流水线触发、镜像构建、灰度上线（后续 Phase 接入）
- **巡检与告警** — 健康巡检、SLO、值班排班（后续 Phase 接入）

完整规划见 `docs/devforge-platform-plan.md`。

> 注意：本服务与 `services/tx-forge`（对外 ISV / Agent 应用市场）是两个独立产品，
> 不要混淆。tx-forge 面向第三方开发者；tx-devforge 面向屯象内部研发团队。

## 启动

本地直接运行（已装依赖、PG 已就绪）：

```bash
export DATABASE_URL="postgresql+asyncpg://tunxiang:changeme_dev@localhost/tunxiang_os"
uvicorn services.tx_devforge.src.main:app --host 0.0.0.0 --port 8017 --reload
```

容器化：

```bash
docker build -f services/tx-devforge/Dockerfile -t tunxiang/tx-devforge:dev .
docker run -p 8017:8017 -e DATABASE_URL=... tunxiang/tx-devforge:dev
```

## 数据库迁移

迁移脚本归口在 `shared/db-migrations/versions/`。本服务的首个版本为
`v366_devforge_application`。在仓库根目录运行：

```bash
cd shared/db-migrations
alembic upgrade head
```

## API 一览（v0.1.0 骨架）

| 路径 | 说明 |
| --- | --- |
| `GET /health` | 服务存活 |
| `GET /readiness` | DB 可连通性 |
| `GET /api/v1/devforge/applications` | 分页列出应用 |
| `POST /api/v1/devforge/applications` | 创建应用 |
| `GET /api/v1/devforge/applications/{id}` | 应用详情 |
| `PATCH /api/v1/devforge/applications/{id}` | 更新应用 |
| `DELETE /api/v1/devforge/applications/{id}` | 软删除 |

所有业务接口必须传 `X-Tenant-ID` header（合法 UUID）。
