# Claude 开发执行方案：门店架构落地 + 单商户环境部署

> **依据**：[`architecture-store-terminals-stable-ai.md`](architecture-store-terminals-stable-ai.md)、[`development-plan-mixed-terminals-claude-2026Q2.md`](development-plan-mixed-terminals-claude-2026Q2.md)  
> **目标**：**今日**完成可合并的 P0 代码与文档；**明日**按 Runbook 在目标环境布署 **一个商户** 的可用链路（网关 + DB + OS 登录 + 租户头一致）。

---

## 第一部分：今日开发包（已在仓库落地，合并后即生效）

| # | 项 | 说明 |
|---|-----|------|
| 1 | **OS 登录写入 `tx_tenant_id`** | `apps/web-admin`：`LoginPage` 在 `json.data.user.tenant_id` 存在时 `localStorage.setItem('tx_tenant_id', …)`；`logout` 时 `removeItem('tx_tenant_id')`。解决分析/供应链等依赖 `X-Tenant-ID` 的页面缺租户问题。 |
| 2 | **Gateway 挂载开放 API** | `services/gateway/src/main.py`：`include_router(open_api_router)`，路径前缀 **`/open-api/*`**（与 `open_api_routes.py` 一致）。Forge / ISV 可联调；DB 未配置时相关端点可能 503。 |
| 3 | **Forge 文档同步** | `docs/forge-openapi-key-lifecycle.md` §5 更新为「已挂载」。 |

**Claude 后续任务（未要求今日全部完成）**

- Phase 1：对齐 `tunxiang-api` POS 同步与 Gateway JWT 的 **tenant UUID 单一事实源**（见开发计划）。  
- Phase 2：Windows 壳工程初始化。  
- `web-hub` 接线 `/api/v1/hub/*` 替换静态 JSON。

---

## 第二部分：明日 — 单商户环境布署 Runbook

以下假设：**一台 Linux 服务器**（或已有 Docker 主机），域名已指向该主机（如 `api.tunxiangos.com`、`os.tunxiangos.com`），仓库已 `git clone` 或可 `git pull`。

### 2.1 部署前检查清单

- [ ] 服务器已安装 **Docker** + **Docker Compose v2**  
- [ ] **PostgreSQL 16** 可访问；已执行 **Alembic 迁移**（至少含 v069 若使用开放 API）  
- [ ] 环境变量：`DATABASE_URL`、`REDIS_URL`（网关）、各 `tx-*` 服务按 `infra` 实际 compose 配置  
- [ ] **CORS**：`CORS_ALLOWED_ORIGINS` 包含 `https://os.你的域名`、本地调试地址  
- [ ] 商户 **tenant_id（UUID）** 已在库中创建；演示用户 `tenant_id` 与该商户一致  

### 2.2 最小链路（推荐顺序）

1. **拉代码并构建网关**  
   ```bash
   cd /path/to/tunxiang-os
   git pull origin main
   cd infra/docker
   docker compose build gateway
   docker compose up -d postgres redis gateway
   ```
   若全栈不在同一 compose，按现网方式仅 **重建并重启 gateway 容器/进程**，保证新代码包含 `open_api` 路由。

2. **数据库迁移**（在可访问 DB 的环境执行）  
   ```bash
   cd shared/db-migrations
   # 按项目惯例：alembic upgrade head 或 make migrate-up
   ```

3. **静态资源：web-admin（OS）**  
   - 构建：`cd apps/web-admin && pnpm install && pnpm build`  
   - 将 `dist/` 部署到 Nginx `root`（如 `os.tunxiangos.com`），`location /api/` 反代到 `gateway:8000`。

4. **验证**  
   - `curl -s https://api.你的域名/health` → `ok`  
   - 浏览器打开 OS，使用 **该商户账号** 登录；开发者工具 Application → Local Storage 应有 **`tx_token`、`tx_user`、`tx_tenant_id`**。  
   - 打开需租户的页面（如经营驾驶舱），请求头带 **`X-Tenant-ID`**，与登录租户一致。

### 2.3 单商户数据与 POS（若对接品智）

- 环境变量：`CZYZ_PINZHI_*` / 对应商户前缀（见 `tunxiang-api` merchant_config）。  
- **租户 UUID** 与 **POS 同步**、**OS 登录** 三者一致（见开发计划 Phase 1）。  
- 首次可只做 **OS + 网关 + 空数据租户**，POS 同步作为后续步骤。

### 2.4 回滚

- 网关：部署上一镜像 tag 或 `git revert` 后重建。  
- 前端：保留上一版 `dist` 备份切换 Nginx `root`。

---

## 第三部分：给明日操作者的「一页纸」

1. `git pull` → 重建 **gateway** → 跑 **migrate**。  
2. 重发 **web-admin** 静态资源（含今日 `tx_tenant_id` 逻辑）。  
3. 用 **单商户测试账号** 登录 OS，确认 **localStorage 三项** 与接口 **X-Tenant-ID** 一致。  
4. 再按需开 POS 同步、Mac mini、门店终端。

---

## 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-02 | 初版：今日 P0 落地项 + 明日单商户 Runbook |
