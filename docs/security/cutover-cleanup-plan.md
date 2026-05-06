# Cutover 后代码清理计划（S-02 闭环最后一公里）

**对应审计项**：[S-02 — X-Tenant-ID transit forgery](../audit-2026-05/01-security.md#s-02)
**关联 PR**：本文档对应分支 `audit/p0-followup-cutover-cleanup`
**状态**：DO NOT MERGE — cutover 完成（PR #208 + #210 + 灰度 100% + 24h 无 5xx）后 1-click 合
**依赖**：
  - PR #208 InternalJwtMiddleware 22 服务挂载已 merge
  - PR #210 K8s NetworkPolicy 已部署（封 nodePort 直连 + 限制 service-to-service）
  - cutover env `TX_INTERNAL_JWT_SECRET` 在所有服务生产 pod 已注入

---

## 一、本 PR 已完成的清理（commit 1-2）

### Commit 1 — `b92a4fe9`：批量删 156 处 fallback
覆盖 22 个服务、155 文件的标准模式：

```diff
- tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
+ tid = getattr(request.state, "tenant_id", "")  # cutover 后只信 InternalJwtMiddleware 注入的 state
```

由 `/tmp/cleanup_xtenant_fallback.py` 脚本批量替换，5 类正则覆盖：标准
state-or-header / 默认值 `""` / `r.state` 简写 / `r.state` 默认 `""` /
带 `or "default"` 后缀。

### Commit 2 — `07c39223`：余 15 处手工补丁
脚本未匹配的 4 类变体：return 语句、顺序颠倒（header THEN state）、
raw header 直读（无 state 兜底）、X-Tenant-Id 大小写变体。

---

## 二、cutover 后保留的 8 处直读 header（合法位置）

下表 8 处保留 `request.headers.get("X-Tenant-ID")` 的代码均经过审查，
均为入口 / 适配 / 测试设施。**任何新增条目必须在 PR review 中辩证。**

| # | 文件:行 | 类别 | 保留理由 |
|---|---------|------|----------|
| 1 | `services/gateway/src/middleware/tenant_middleware.py:68` | gateway 入口 | 公网入口必读 header；本 middleware 校验后注入 state，下游服务消费 state 而非 header |
| 2 | `services/gateway/src/wecom_internal.py:75` | gateway 内部 | 企业微信内部接口；位于 gateway 自身，未跨服务 |
| 3 | `services/gateway/src/api/flags_routes.py:170` | gateway 管理 | 特性开关后台；走 gateway 内 admin 鉴权 |
| 4 | `services/tunxiang-api/src/shared/middleware.py:20` | 单体入口 | 遗留 API 适配层入口 middleware；与 gateway 同性质，本 middleware 注入 state |
| 5 | `services/tx-devforge/src/middlewares/tenant.py:60` | dev tools 入口 | DevForge 自有租户 middleware；devforge 是 dev 工具，不暴露生产数据 |
| 6 | `services/tx-trade/src/security/rbac.py:87` | RBAC context | 本身用于 audit log 的 fallback context 字段；与 tenant_id 受信路径无关 |
| 7 | `services/tx-trade/src/api/webhook_routes.py:105` | 公网回调 | 美团/饿了么/抖音等三方 webhook 入口；不经 gateway，外部签名验证后允许读 header |
| 8 | `services/tx-trade/src/api/booking_webhook_routes.py:100` | 公网回调 | 第三方预订平台 webhook；同上 |

**不再保留 query_params 兜底**：
`tx-org/api/attendance_compliance_routes.py:49` 的 `?tenant_id=X` 兜底已在
commit 2 一并删除（该模式比 header 兜底更严重，攻击者直接 URL 拼接）。

---

## 三、cutover 后剩余的代码清理（**本 PR 不做，避免 cutover 期回退困难**）

下列 3 处代码包含明确的"cutover 期 dev 兜底"逻辑，cutover 完成后应删除。
**留作后续独立 PR**，避免 cutover 期出现 staging vs prod 行为差。

### 3.1 `services/gateway/src/proxy.py` — strip + reinject 简化

**当前行为**（PR #195 引入）：
1. 从客户端请求 strip `X-Tenant-ID` header（防 transit forgery）
2. 由 gateway 中间件验证后重新注入受信 `X-Tenant-ID`
3. 同时 mint internal JWT 注入 `X-Internal-JWT`

**cutover 后**：
- 下游服务全部消费 state（由 InternalJwtMiddleware 从 X-Internal-JWT 解出）
- `X-Tenant-ID` header 注入仅为兼容 8 处合法读 header 的位置（webhook + RBAC）
- 可考虑：仅对 `webhook_routes` 路径保留 header 注入；其他路径 strip 后不重注

**改动复杂度**：低；但需要 staging 跑通 webhook 全链路验证

### 3.2 `shared/ontology/src/database.py:get_db_no_rls()` — 移除双模式

**当前行为**（PR #207 引入）：
```python
use_role = os.environ.get("RLS_USE_TX_SYSTEM_ROLE", "").strip().lower() in ("true", "1", ...)
if use_role:
    await session.execute(text("SET LOCAL ROLE tx_system_role"))
else:
    await session.execute(text("SET LOCAL row_security = off"))
```

**cutover 后**（PR #199 + RLS 阶段 5 灰度 100% 完成后）：
- `tunxiang` role 已 NOBYPASSRLS，`SET LOCAL row_security = off` 失效
- 强制 `SET LOCAL ROLE tx_system_role` 单一路径
- 删除 env 检查 + `else` 分支

**改动复杂度**：低；需先确认所有 prod / staging 已 `ALTER ROLE tunxiang NOBYPASSRLS`

### 3.3 `shared/security/src/internal_jwt_middleware.py` — 移除 dev 兜底

**当前行为**：
```python
secret = os.environ.get("TX_INTERNAL_JWT_SECRET", "").strip()
if not secret:
    return await call_next(request)  # dev mode：无 secret 时透传
```

**cutover 后**：
- 所有 prod / staging pod 已注入 `TX_INTERNAL_JWT_SECRET`
- dev 兜底 `if not secret` 应改为：
  - 选项 A：硬失败 `raise RuntimeError("TX_INTERNAL_JWT_SECRET required")`
  - 选项 B：仅在 `ENV != production` 时透传，prod 硬失败

**改动复杂度**：中；需确认本地 dev / CI 环境 secret 注入到位

---

## 四、cutover 完成判定标准（合本 PR 的前提）

全部 ✅ 才解锁本 PR merge：

- [ ] PR #208 已 merge 至 main
- [ ] PR #210 NetworkPolicy 已应用至 staging + prod
- [ ] 所有 22 服务 prod pod 持有 `TX_INTERNAL_JWT_SECRET` env
- [ ] gateway 已开启 strip `X-Tenant-ID` 并 mint internal JWT（生产灰度 100%）
- [ ] staging 跑通 24h 无 InternalJwt-related 5xx
- [ ] prod 灰度 7 天无 InternalJwt-related 5xx 或 RLS 错误
- [ ] webhook 全链路（美团 + 饿了么 + 抖音 + 微信回调）跑通

---

## 五、合本 PR 后的下一步（已开 3 个独立草稿 PR）

3 个 follow-up cleanup 已作为 DO NOT MERGE 草稿 PR 推送，cutover 完成后按
依赖顺序合：

1. **PR #213** — `audit/p0-followup-cleanup-proxy-simplify`
   - 文件：`services/gateway/src/proxy.py`
   - 删除 `mint_internal_jwt` 的 `ImportError` 兜底（cutover 后 helper 必存在）
   - 移到模块级 import（每请求省 ~50µs）
   - 依赖：PR #195 + #208 已 merge + 全环境注入 `TX_INTERNAL_JWT_SECRET`

2. **PR #214** — `audit/p0-followup-cleanup-rls-no-bypass-single-mode`
   - 文件：`shared/ontology/src/database.py` + 测试同步重写
   - 删除 `get_db_no_rls()` 的双模式 env 切换，强制 `SET LOCAL ROLE tx_system_role`
   - 依赖：PR #207 灰度 100% + DBA `ALTER ROLE tunxiang NOBYPASSRLS` + PR #199 已 merge

3. **PR #215** — `audit/p0-followup-cleanup-internal-jwt-no-dev-fallback`
   - 文件：`shared/security/src/internal_jwt_middleware.py` + 11 测试用例改写
   - 删除 dev/staging 跳过校验路径（无 secret → 500，无 token → 401，全环境一致）
   - 依赖：PR #208 已 merge + 全环境（含 dev/CI）注入 `TX_INTERNAL_JWT_SECRET`

每个 PR 独立 review + 独立灰度 + 独立回滚。

---

## 六、回归检查命令

```bash
# 1. 业务代码不应有 X-Tenant-ID 直读（除 §二 8 处合法保留）
grep -rn 'request\.headers\.get("X-Tenant-ID"\|headers\.get("X-Tenant-ID"\|request\.headers\.get("X-Tenant-Id"' \
  services/ --include='*.py' | grep -v '__pycache__' | grep -v '/tests/' | wc -l
# 期望：8（与 §二 表一致）

# 2. 无 query_params tenant_id 兜底
grep -rn 'query_params\.get("tenant_id"' services/ --include='*.py' | grep -v '/tests/'
# 期望：0

# 3. 业务代码 state 读路径仍正常工作
grep -rn 'getattr(request\.state,\s*"tenant_id"' services/ --include='*.py' | wc -l
# 期望：约 200 处（cutover 后唯一受信来源）
```
