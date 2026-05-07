# InternalJwtMiddleware 24 服务挂载 + 路由改造 rollout

**对应审计项**：[S-02](../audit-2026-05/01-security.md#s-02) 闭环 part 2
**当前完成度**：50% → 70%（tx-trade 示范挂载，剩 23 服务）→ 100%（全部挂 + 路由切信任源）

---

## 背景

PR #195 已实现：
- `shared/security/src/internal_jwt.py` `mint_internal_jwt()` / `verify_internal_jwt()`
- gateway proxy 在已认证路径附加 `X-Internal-JWT` header

但下游 24 服务的路由仍然读 `X-Tenant-ID` header（不验签的）—— gateway 之外
任何能到 pod 的请求伪造 header 即可绕 RLS。

本 PR（follow-up #4）实现：
- `shared/security/src/internal_jwt_middleware.py` `InternalJwtMiddleware`
- `services/tx-trade/src/main.py` 示范挂载
- 11 个 Tier 1 测试全过

剩余工作：把 middleware 挂到剩 23 个服务 + 路由 `_get_tenant_id()` 改造。

---

## 服务挂载 checklist

每个服务在 `services/{service}/src/main.py` 的 FastAPI 实例化后加：

```python
from shared.security.src.internal_jwt_middleware import InternalJwtMiddleware
app.add_middleware(InternalJwtMiddleware)
```

| # | 服务 | 端口 | 挂载状态 | 路由改造（_get_tenant_id 优先 state）|
|---|---|---|---|---|
| 1 | gateway | 8000 | N/A（gateway 自己签 JWT，不验自己的） | — |
| 2 | tx-trade | 8001 | ✅ PR #202 + 本 PR 修挂载位置 | ✅ 现有路由已优先 state |
| 3 | tx-menu | 8002 | ✅ 本 PR | ⏳ 路由现写法已支持 state |
| 4 | tx-member | 8003 | ✅ 本 PR | ⏳ 同上 |
| 5 | tx-growth | 8004 | ✅ 本 PR（无 CORS） | ⏳ 同上 |
| 6 | tx-ops | 8005 | ✅ 本 PR | ⏳ 同上 |
| 7 | tx-supply | 8006 | ✅ 本 PR（无 CORS） | ⏳ 同上 |
| 8 | tx-finance | 8007 | ✅ 本 PR | ⏳ 同上 |
| 9 | tx-agent | 8008 | ✅ 本 PR | ⏳ 同上 |
| 10 | tx-analytics | 8009 | ✅ 本 PR（无 CORS） | ⏳ 同上 |
| 11 | tx-brain | 8010 | ✅ 本 PR | ⏳ 同上 |
| 12 | tx-intel | 8011 | ✅ 本 PR（无 CORS） | ⏳ 同上 |
| 13 | tx-org | 8012 | ✅ 本 PR（无 CORS） | ⏳ 同上 |
| 14 | tx-civic | 8014 | ✅ 本 PR | ⏳ 同上 |
| 15 | tx-pay | 8016 | ✅ 本 PR | ⏳ 同上 |
| 16 | tx-forge | 8013 | ✅ 本 PR | ⏳ 同上 |
| 17 | tx-devforge | 8017 | ✅ 本 PR | ⏳ 同上 |
| 18 | tx-expense | — | ✅ 本 PR | ⏳ 同上 |
| 19 | tx-predict | — | ✅ 本 PR（无 CORS） | ⏳ 同上 |
| 20 | tx-indonesia | — | ✅ 本 PR | ⏳ 同上 |
| 21 | tx-malaysia | — | ✅ 本 PR | ⏳ 同上 |
| 22 | tx-vietnam | — | ✅ 本 PR | ⏳ 同上 |
| 23 | mcp-server | — | N/A（无 main.py 入口） | — |
| 24 | tunxiang-api | — | ✅ 本 PR | ⏳ 同上 |

**S-02 完成度：50% (PR #202) → 70% (本 PR 含 22 服务挂载) → 100% (待 ops 配 secret + 24h 灰度)**

⚠️ **修复 PR #202 引入的挂载顺序错**：tx-trade main.py 原本把 InternalJwtMiddleware
add 在 CORS 之前 → InternalJwt 在外层 → CORS preflight (OPTIONS) **先经 JWT 校验** →
生产模式 cutover 时所有 OPTIONS 请求 401 → CORS 失效，前端跨域请求全断。

正确顺序：CORS 先 add（外层）→ InternalJwt 后 add（内层）→ OPTIONS 走外层
CORS 直接返 200，不进 JWT 校验。本 PR 修了 tx-trade 同样问题。

各服务路由 `_get_tenant_id()` 模板（兼容期写法）：

```python
def _get_tenant_id(request: Request) -> str:
    # InternalJwtMiddleware 通过后 request.state.tenant_id 是受信值
    # cutover 完成前继续 fallback X-Tenant-ID header
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID required")
    return tid
```

注：tx-trade 的多数路由本身已是这个写法（PR #195 之前就有），所以本 PR
仅挂载 middleware 即生效。

---

## 灰度上线策略

### 阶段 1：本 PR merge（仅 tx-trade 挂载，dev 行为兼容）

部署后 dev/staging 无 `TX_INTERNAL_JWT_SECRET`，middleware skip，现状不变。

### 阶段 2：6 服务挂载（高频域）

- tx-pay / tx-member / tx-menu / tx-ops / tx-finance / tx-agent
- 新 PR / 每服务 2 commit（main.py + 路由改造）+ 测试
- merge 顺序：tx-pay 先（最敏感），其余并行

### 阶段 3：剩 17 服务批量挂载

- 同模板批量 PR
- 每服务最少 2 路由测试覆盖（以 \_get\_tenant\_id 验证 state 优先）

### 阶段 4：开启 cutover

ops 步骤：
1. 配 `TX_INTERNAL_JWT_SECRET` 到 K8s Secret（用 sealed-secret / Vault）
2. gateway pod 滚动更新读取 secret 开始签发 JWT
3. 灰度 24h 观察：
   - tx-trade /metrics 看 `internal_jwt_middleware_verify_failed` 计数
   - 任何 401 立刻排查（gateway secret 与下游 secret 是否对齐）
4. 全量门店灰度通过后，路由代码可改为**只读 state，不再 fallback header**
   （此时 cutover 完成，gateway 之外伪造 X-Tenant-ID 完全无效）

### 阶段 5（cutover 完成后）

清理代码：
- 路由 `_get_tenant_id()` 删 `or request.headers.get("X-Tenant-ID", "")` fallback
- gateway proxy 不再 strip + reinject `X-Tenant-ID`（让客户端发的 header 进 gateway 就被 middleware 读，统一信任源）
- NetworkPolicy 限只有 gateway namespace 可达 tx-* pod 端口（纵深防御）

---

## 验收标准

完成判定（**全部 ✅**）：

- [ ] 24 个服务全部挂 InternalJwtMiddleware（包括 tx-trade ✅）
- [ ] 24 个服务的路由 `_get_tenant_id()` 都先读 `request.state.tenant_id`
- [ ] CI 加新 lint：扫描 `request.headers.get("X-Tenant-ID", "")` 必须紧邻 `getattr(request.state, "tenant_id", ...)`
- [ ] 生产环境 `TX_INTERNAL_JWT_SECRET` 配进 K8s Secret + 验证签发流程
- [ ] 灰度 24h `internal_jwt_middleware_verify_failed` 告警 = 0
- [ ] NetworkPolicy 部署 + 验证 tx-* pod 直接访问被拒（404 / connection refused）

---

## 已知遗留风险

1. **HS256 共享密钥爆炸半径**（PR #195 internal_jwt.py 已注释）：
   单 pod 内存被 dump 即可签任意租户。生产应配 Vault 限制 secret 投放范围；
   或后续升级 RS256 非对称（gateway 持私钥签，下游持公钥验，私钥可单独保护）。

2. **JWT 过期窗口 60s**：跨服务调用链延迟 > 60s 会被拒。当前 60s 足够（gateway → 下游一跳），
   但若未来出现 service mesh 重试、慢路径，需按需调高 `TX_INTERNAL_JWT_TTL_SECONDS`。

3. **环境变量切换风险**：cutover 过程中如果 ops 误把 `TX_INTERNAL_JWT_SECRET`
   先配下游再配 gateway，下游会立即开始拒所有请求（gateway 还没签）。
   推荐顺序：先 gateway → 灰度 5% → 配下游 → 灰度门店 → 全量。
