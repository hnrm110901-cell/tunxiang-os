# 屯象OS 架构事实

> 数据截止：2026-03-31 | 基于代码库实际扫描

## 技术栈（实际使用）

### 后端
- **框架**: FastAPI (所有服务)
- **ORM/验证**: Pydantic V2 + SQLAlchemy
- **数据库**: PostgreSQL 16 (RLS多租户隔离)
- **迁移**: Alembic
- **缓存/消息**: Redis Streams + PG LISTEN/NOTIFY
- **日志**: structlog (JSON格式)
- **AI**: Claude API (云端) + Core ML (边缘)
- **Python版本**: 3.11+
- **测试**: pytest + pytest-asyncio

### 前端
- **框架**: React 18 + TypeScript (strict mode)
- **构建**: Vite
- **状态管理**: Zustand
- **样式**: Tailwind CSS + CSS Variables (Design Tokens)
- **Admin组件库**: Ant Design 5.x + ProComponents
- **Store组件库**: TXTouch (自研触控组件库)
- **小程序**: uni-app + Vue 3 + TypeScript

### 移动端壳层
- **安卓**: Kotlin + WebView + JS Bridge (商米SDK)
- **iOS**: Swift + WKWebView

### 边缘计算
- **硬件**: Mac mini M4 (16GB/256GB+)
- **本地API**: FastAPI (port 8000)
- **ML推理**: Core ML via Swift HTTP Server (port 8100)
- **网络**: Tailscale (安全隧道)

### 基础设施
- **容器**: Docker Compose (dev/staging/gray/prod)
- **云**: 腾讯云
- **CI/CD**: GitHub Actions
- **安全**: git-secrets + pre-commit hooks

## 五层架构（实际代码映射）

```
L4 多形态前端层
   apps/web-pos/          → POS收银
   apps/web-admin/        → 总部管理
   apps/web-kds/          → 厨房显示
   apps/web-crew/         → 服务员PWA
   apps/web-reception/    → 预订管理
   apps/miniapp-customer/ → 消费者小程序
   apps/android-pos/      → 安卓壳层
   apps/ios-shell/        → iPad壳层

L3 Agent OS层
   services/tx-agent/     → Master Agent + 40+ Skill Agents
   services/tx-brain/     → AI推理引擎 + ModelRouter

L2 业务中台层
   services/tx-trade/     → 交易履约
   services/tx-menu/      → 商品菜单
   services/tx-member/    → 会员CDP
   services/tx-supply/    → 供应链
   services/tx-finance/   → 财务结算
   services/tx-org/       → 组织运营
   services/tx-analytics/ → 经营分析
   services/tx-ops/       → 运营管理
   services/tx-growth/    → 增长营销
   services/tx-intel/     → 商业智能

L1 Ontology层
   shared/ontology/       → 6大实体 + 注册表 + 约束检查

L0 设备适配层
   edge/mac-station/      → Mac mini本地服务
   edge/sync-engine/      → 云边同步
   edge/coreml-bridge/    → Core ML桥接
   shared/adapters/       → 旧系统适配器
```

## API规范（实际执行）

- 路径: `/api/v1/`
- 响应: `{ "ok": bool, "data": {}, "error": {} }`
- 认证: `X-Tenant-ID` header (所有请求)
- 分页: `?page=1&size=20` → `{ items: [], total: int }`
- 数据库: 所有表含 `tenant_id` + RLS Policy

## 代码规模

| 语言 | 行数 | 占比 |
|------|------|------|
| Python | ~363,000 | 78% |
| TypeScript | ~93,000 | 20% |
| Kotlin/Swift | ~5,000 | 1% |
| 其他(SQL/YAML/JSON) | ~5,000 | 1% |
| **总计** | **~466,000** | 100% |

## 数据库设计要点

- **多租户**: PostgreSQL RLS, `app.current_tenant` 会话变量
- **基类字段**: `tenant_id`, `created_at`, `updated_at`, `is_deleted`
- **命名**: snake_case, 表名复数
- **软删除**: `is_deleted` 字段, 不物理删除
