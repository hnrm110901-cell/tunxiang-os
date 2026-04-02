# Forge 与开放 API / Key 生命周期对齐说明

> **目标**：`apps/web-forge`（`forge.tunxiangos.com`）与网关开放能力、数据库表、运维流程一致。  
> **代码依据**：`shared/db-migrations/versions/v069_open_api_platform.py`、`services/gateway/src/services/oauth2_service.py`、`services/gateway/src/api/open_api_routes.py`。

---

## 1. 数据模型（v069）

| 表 | 用途 |
|----|------|
| `api_applications` | ISV 应用注册：`app_key`、`app_secret_hash`、`scopes`、`status`（active/suspended/revoked）、`rate_limit_per_min`、`webhook_url` 等 |
| `api_access_tokens` | OAuth2 access token：**仅存哈希**，`token_prefix` 用于展示，`expires_at`、`revoked_at` |
| `api_request_logs` | 按应用/租户的请求审计 |
| `api_webhooks` | Webhook 配置（若迁移中已建，与 Forge「Webhooks」页对齐） |

**RLS**：上述表在租户上下文 `app.tenant_id` 下隔离；**ISV 应用归属于某 merchant `tenant_id`**。

---

## 2. 网关 HTTP 契约（Open API 路由）

`open_api_routes.py` 定义的 **Router prefix** 为 **`/open-api`**（注意：与部分文档中的 `/gateway/...` 示例路径不同，以代码为准）。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/open-api/applications` | 注册应用；需 **租户侧 Bearer（商家用户 JWT）** + `X-Tenant-ID`，返回 **一次性 `app_secret`** |
| GET | `/open-api/applications` | 分页列出应用 |
| GET | `/open-api/applications/{app_id}` | 详情（不含 secret） |
| DELETE | `/open-api/applications/{app_id}` | 吊销应用 |
| POST | `/open-api/oauth/token` | `client_credentials`，`client_id`=`app_key`，`client_secret`=`app_secret` → `access_token` |
| POST | `/open-api/oauth/revoke` | 吊销 token |
| POST | `/open-api/oauth/rotate` | 轮换 `app_secret`（新 secret 仅返回一次） |
| GET | `/open-api/applications/{app_id}/logs` | 请求日志分页 |

**OAuth2Service 行为摘要**（`oauth2_service.py`）

- `app_key` 前缀 `txapp_`；access token 前缀 `txat_`；默认 **24h** 过期。
- Secret / token **PBKDF2-SHA256** 存储，明文仅在创建/轮换瞬间返回。

---

## 3. Forge 页面 ↔ 能力映射（待产品化接线）

| Forge 页面 | 应对齐的后端能力 | 说明 |
|------------|------------------|------|
| **Console** | `POST/GET/DELETE /open-api/applications`，`GET .../logs` | 应用列表、创建（展示一次性 secret）、吊销、调用日志 |
| **Sandbox** | `POST /open-api/oauth/token` + 带 `Authorization: Bearer <access_token>` 的域 API 探测 | 与 `verify_bearer_token`、限流头一致 |
| **Webhooks** | `api_applications.webhook_url` + `api_webhooks` 表（若有） | 投递、重试、签名密钥（若未实现需在规格中补） |
| **SDK** | 文档化：`base_url`、`X-Tenant-ID`、Bearer 两种模式（用户 JWT vs `txat_`） | 与 `DocsPage` 示例路径统一为真实 gateway 前缀 |
| **Marketplace** | 独立商业模块（非 v069） | 与开放 API **解耦**；上架应用可要求已注册 `api_application` |

---

## 4. Key / Token 生命周期（状态机）

```
注册应用 → status=active，展示 app_key + app_secret（一次）
    ↓
client_credentials → 签发 access_token（写入 api_access_tokens）
    ↓
调用业务 API → RateLimiter + api_request_logs
    ↓
过期自动失效 / POST oauth/revoke 主动吊销
    ↓
POST oauth/rotate → 新 secret，旧 secret 立即失效（以代码为准）
    ↓
DELETE application / status=revoked → 应用级失效，级联 token
```

**验收检查项**

- [ ] 吊销应用后，旧 `access_token` 调用域 API 返回 **401**。
- [ ] 日志中仅出现 `token_prefix`，无明文 token。
- [ ] 超限返回 **429**，响应头含 `X-RateLimit-*` / `Retry-After`（与 `open_api_routes` 一致）。

---

## 5. 部署注意（必读）

1. **挂载路由**：`services/gateway/src/main.py` 已 **`include_router(open_api_router)`**（`/open-api/*`）。若相关端点返回 503，检查网关进程是否配置 `DATABASE_URL` 与 `..database` 模块可用（v069 表已迁移）。  
2. **迁移**：生产库必须已执行 **v069**（及依赖的 RLS 修复版本，如 v075 说明中所述）。  
3. **Forge 控制台鉴权**：Console 代表**租户管理员**代 ISV 建应用时，应使用 **OS 登录 JWT**，禁止在浏览器长期存放 `app_secret`（可下载 `.env` 或一次性复制）。  
4. **与 Hub 边界**：Hub 为屯象内部运维，**不**替代租户创建 ISV 应用；若需「代建」，应审计并限制为超级管理员。

---

## 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-02 | 初版：对齐 v069 + OAuth2Service + open_api_routes |
