# 屯象OS 等保三级合规开发计划

> **制定日期**: 2026-03-31
> **依据标准**: GB/T 22239-2019《信息安全技术 网络安全等级保护基本要求》三级
> **参考系统**: 点评微生活系统等保三级测评报告（2024年，综合得分84.29分/良）
> **目标**: 屯象OS通过等保三级认证（目标得分≥85分/良）
> **执行人**: 单人开发（李淳）

---

## 一、当前安全状态基线

### 已有（合规基础）
| 项目 | 现状 | 等保映射 |
|------|------|---------|
| HTTPS全站加密 | ✅ 已实现 | 安全通信网络-通信传输 |
| RLS多租户隔离 | ✅ 19张表正确（3张有缺陷） | 安全计算环境-访问控制 |
| KMS密钥管理 | ✅ env-based + PBKDF2 | 安全计算环境-数据保密性 |
| structlog结构化日志 | ✅ 已实现 | 安全计算环境-安全审计 |
| git-secrets扫描 | ✅ CI已配置 | 安全建设管理-自行软件开发 |
| Docker容器化 | ✅ 已实现 | 安全运维管理-环境管理 |
| Tailscale VPN | ✅ Mac mini→云端 | 安全通信网络-网络架构 |

### 缺口（需补齐）
| 风险级别 | 问题 | 等保映射 | 阻塞测评 |
|---------|------|---------|---------|
| **P0-CRITICAL** | 3个商户.env含真实API密钥已提交git | 安全运维-密码管理 | ✅ 是 |
| **P0-CRITICAL** | RLS 3张表(bom/waste)使用错误session变量 | 安全计算环境-访问控制 | ✅ 是 |
| **P0-HIGH** | 1,898处 broad except Exception | 安全计算环境-入侵防范 | ✅ 是 |
| P1 | 无MFA双因素认证 | 安全计算环境-身份鉴别 | ✅ 是 |
| P1 | 无WAF应用防火墙 | 安全区域边界-边界防护 | ✅ 是 |
| P1 | 无堡垒机/跳板机 | 安全计算环境-身份鉴别 | ✅ 是 |
| P1 | 无数据库审计 | 安全计算环境-安全审计 | ✅ 是 |
| P1 | 无异地备份 | 安全计算环境-数据备份恢复 | ✅ 是 |
| P1 | PII字段明文存储（手机号等） | 安全计算环境-数据保密性 | ✅ 是 |
| P1 | 无最小权限/三权分立 | 安全计算环境-访问控制 | ✅ 是 |
| P2 | 无漏洞扫描定期机制 | 安全运维管理-漏洞风险管理 | 否 |
| P2 | 无安全事件应急预案 | 安全运维管理-应急预案管理 | 否 |
| P2 | 无安全管理制度文档体系 | 安全管理制度 | 否 |

---

## 二、等保三级控制点全景映射

### 技术要求（必须开发）

```
安全计算环境
├── 身份鉴别          → MFA双因素认证（TOTP + 短信）
├── 访问控制          → RBAC三权分立 + 最小权限 + RLS修复
├── 安全审计          → 操作日志统一收集 + 审计管理员角色
├── 入侵防范          → 异常处理收窄 + 接口防刷 + 漏洞扫描
├── 数据完整性        → HMAC-SHA256签名校验关键数据
├── 数据保密性        → AES-256字段加密（PII：手机/身份证）
├── 数据备份恢复      → 腾讯云跨地域备份 + 定期恢复演练
└── 个人信息保护      → 数据收集最小化 + 删除机制

安全区域边界
├── 边界防护          → 腾讯云WAF接入
├── 访问控制          → VPC安全组白名单收紧
├── 入侵防范          → 腾讯云云防火墙开启IDS
└── 安全审计          → 网络访问日志→CLS

安全通信网络
├── 网络架构          → 安全防护区/服务区/管理区三区分离
└── 通信传输          → TLS 1.2+，禁用弱密码套件

安全管理中心
├── 系统管理          → 统一运维入口（堡垒机/JumpServer）
├── 审计管理          → 独立审计账户，日志不可删除
└── 集中管控          → 腾讯云CLS统一日志 + 告警规则
```

### 管理要求（需要写文档）

```
安全管理制度  → 信息安全管理办法、数据备份恢复规定等4份文档
安全建设管理  → 安全设计方案、开发管理制度（已有部分）
安全运维管理  → 运维操作日志、变更管理流程、应急预案
```

---

## 三、20周分阶段开发计划

### Phase 0：消除P0阻塞（Week 1-2）

> **目标**: 解决凭证泄露和RLS失效，达到"可接入客户数据"的最低安全线

#### Week 1：凭证清理 + RLS修复

**任务1.1：Git凭证清除**（1天）
```bash
# 参考 docs/credential-cleanup-guide.md 执行
# 1. 轮换所有已泄露的API密钥（品智/奥琦玮/美团）
# 2. git filter-branch 清除历史记录
# 3. 强制推送（需要所有协作者重新clone）
# 4. 配置 .gitignore 规则：config/merchants/ 目录永不提交
```

**任务1.2：RLS修复迁移脚本**（1天）
```sql
-- shared/db-migrations/versions/r05_fix_rls_session_variables.py
-- 修复 bom_templates / bom_items / waste_events 的RLS策略
-- 将 app.current_store_id → app.current_tenant
DROP POLICY IF EXISTS bom_templates_tenant_policy ON bom_templates;
CREATE POLICY bom_templates_tenant_policy ON bom_templates
  USING (tenant_id::text = current_setting('app.current_tenant', TRUE));
-- (同理 bom_items, waste_events)
```

**任务1.3：RLS覆盖率补全**（2天）
- 审计32个缺少tenant_id的模型文件
- 对确实需要隔离的表补充tenant_id + RLS策略
- 目标：租户敏感表100% RLS覆盖

#### Week 2：异常处理收窄（优先级最高的500处）

**任务2.1：自动化扫描定位**（半天）
```bash
# 使用ruff规则批量定位
ruff check services/ --select E722 --output-format=json > except_audit.json
# 按服务分类：gateway、tx-trade、tx-member优先
```

**任务2.2：核心服务异常收窄**（4.5天）
- gateway：全部收窄（对外API安全边界）
- tx-trade：交易链路全部收窄
- tx-member：会员数据链路全部收窄
- 其他服务：P0静默吞没全部修复

**P0完成标准**:
- [ ] git history无凭证（BFG Repo-Cleaner验证）
- [ ] 3张表RLS策略正确（迁移脚本通过）
- [ ] gateway/tx-trade/tx-member无broad except
- [ ] git push触发git-secrets扫描通过

---

### Phase 1：身份鉴别 + 访问控制（Week 3-6）

> **对应等保控制点**: 安全计算环境-身份鉴别、安全计算环境-访问控制

#### Week 3-4：MFA双因素认证

**背景**: 等保三级要求"两种或两种以上组合的鉴别技术"，这是点评微生活被标记的**中风险问题**，屯象OS必须解决。

**实现方案**: TOTP（Google Authenticator）+ 手机验证码，二选一（满足等保要求）

**任务1.1：后端MFA基础设施**（3天）
```python
# services/gateway/src/auth/mfa.py

# 依赖：pyotp（TOTP） + 腾讯云SMS SDK
# 存储：users表新增字段
#   mfa_enabled: bool
#   mfa_secret: str (AES加密存储)
#   mfa_type: enum('totp', 'sms')
#   mfa_backup_codes: jsonb (加密，8个一次性备用码)

class MFAService:
    def generate_totp_secret(self, user_id: UUID) -> str: ...
    def verify_totp(self, user_id: UUID, token: str) -> bool: ...
    def send_sms_code(self, phone: str) -> bool: ...      # 腾讯云SMS
    def verify_sms_code(self, phone: str, code: str) -> bool: ...
```

**任务1.2：登录流程改造**（2天）
```
登录流程:
1. POST /auth/login {username, password}
   → 密码验证通过
   → 返回 {mfa_required: true, session_token: "临时token(5min有效)"}

2. POST /auth/mfa/verify {session_token, mfa_code}
   → MFA验证通过
   → 返回正式 JWT access_token + refresh_token

强制MFA的角色: admin、ops（运维）、auditor（审计员）
可选MFA的角色: store_manager（门店管理员）
不要求MFA: 普通员工（收银员、服务员）
```

**任务1.3：MFA管理界面**（2天）
- web-admin：用户MFA启用/禁用界面
- MFA绑定流程（扫码绑定Authenticator）
- 备用码下载功能

#### Week 5-6：RBAC三权分立 + 最小权限

**背景**: 等保三级要求系统管理员、审计管理员、安全管理员三权分立。单人团队需要在系统层面实现角色分离，即使实际操作者是同一人。

**任务2.1：角色体系重构**（3天）
```python
# 等保三级要求的三权分立角色
class SystemRole(str, Enum):
    # 系统管理员：配置系统、管理用户，不可查看审计日志
    SYSTEM_ADMIN = "system_admin"
    # 审计管理员：只读审计日志，不可修改系统配置
    AUDIT_ADMIN = "audit_admin"
    # 安全管理员：管理安全策略，不可操作业务数据
    SECURITY_ADMIN = "security_admin"

    # 业务角色（租户内）
    TENANT_ADMIN = "tenant_admin"       # 集团管理员
    BRAND_MANAGER = "brand_manager"     # 品牌经理
    STORE_MANAGER = "store_manager"     # 门店经理
    CASHIER = "cashier"                 # 收银员
    WAITER = "waiter"                   # 服务员
    CHEF = "chef"                       # 厨师
    AUDITOR = "auditor"                 # 内部审计（租户级）
```

**任务2.2：API权限矩阵**（2天）
```python
# 每个API端点明确最小权限
# 例：
@router.delete("/users/{user_id}")
@require_roles([SystemRole.SYSTEM_ADMIN])   # 只有系统管理员可删除用户
async def delete_user(): ...

@router.get("/audit-logs")
@require_roles([SystemRole.AUDIT_ADMIN, SystemRole.SECURITY_ADMIN])
async def get_audit_logs(): ...  # 系统管理员不可访问审计日志
```

**任务2.3：数据库三权分立实现**（2天）
```sql
-- 创建独立数据库用户，对应三个角色
CREATE ROLE txos_app_admin;        -- 系统管理员连接用
CREATE ROLE txos_app_auditor;      -- 审计管理员连接用（只读审计表）
CREATE ROLE txos_app_service;      -- 业务服务连接用

-- 审计表只允许INSERT，不允许UPDATE/DELETE（防篡改）
GRANT INSERT ON audit_logs TO txos_app_service;
GRANT SELECT ON audit_logs TO txos_app_auditor;
REVOKE UPDATE, DELETE ON audit_logs FROM txos_app_service;
REVOKE UPDATE, DELETE ON audit_logs FROM txos_app_auditor;
```

**Phase 1 完成标准**:
- [ ] admin/ops登录强制MFA（TOTP或短信）
- [ ] 系统管理员/审计管理员/安全管理员三角色存在且权限互斥
- [ ] API权限矩阵覆盖所有sensitive端点（≥50个）
- [ ] 数据库用户三权分立（3个独立DB角色）

---

### Phase 2：数据安全（Week 7-10）

> **对应等保控制点**: 数据保密性、数据完整性、数据备份恢复、个人信息保护

#### Week 7-8：PII字段加密

**背景**: 点评微生活被标记**中风险**：敏感数据明文存储。屯象OS持有大量餐饮会员PII数据，必须字段级加密。

**需要加密的字段**:
```
Customer: phone（手机号）, id_card（身份证）, real_name
Employee: phone, id_card, bank_account
users: phone
```

**任务3.1：字段加密基础设施**（3天）
```python
# shared/utils/field_encryption.py
# 方案：AES-256-GCM（对称加密）+ 腾讯云KMS托管密钥

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import base64

class FieldEncryption:
    """
    加密：encrypt(plaintext) → "enc:v1:<base64(nonce+ciphertext)>"
    解密：decrypt("enc:v1:...") → plaintext
    前缀 "enc:v1:" 标识已加密，便于迁移和版本控制
    """
    def encrypt(self, plaintext: str) -> str: ...
    def decrypt(self, ciphertext: str) -> str: ...
    def is_encrypted(self, value: str) -> bool:
        return value.startswith("enc:v1:")
```

**任务3.2：手机号加密迁移**（2天）
```python
# shared/db-migrations/versions/r06_encrypt_pii_fields.py
# 步骤：
# 1. 新增 phone_encrypted 列
# 2. 数据迁移：读取phone → 加密 → 写入phone_encrypted
# 3. 更新应用代码使用phone_encrypted
# 4. 保留明文列30天，确认无误后删除

# 搜索索引问题解决方案：
# 手机号末4位单独存储（明文，用于展示）
# 精确匹配：先加密查询值，再查加密列（等值查询仍可走索引）
```

**任务3.3：数据完整性校验**（2天）
```python
# 对关键业务数据（订单金额、交易记录）添加HMAC-SHA256签名
# shared/utils/data_integrity.py
class DataIntegrity:
    def sign(self, data: dict) -> str:
        """生成HMAC-SHA256签名，存储到记录的 _integrity_hash 字段"""
    def verify(self, data: dict, signature: str) -> bool:
        """验证数据未被篡改"""

# 适用表：orders, financial_records, pos_transactions
```

#### Week 9-10：数据备份与恢复

**任务4.1：腾讯云数据库异地备份**（2天）
```yaml
# 配置腾讯云PostgreSQL（CDB）跨地域备份
# 主库：广州 → 备份：上海
# 策略：
#   - 全量备份：每天凌晨1:00
#   - 增量备份：每2小时
#   - 备份保留：30天
#   - 跨地域保留：7天
# 费用估算：~50-100元/月（根据数据量）
```

**任务4.2：备份恢复演练机制**（2天）
```python
# scripts/backup-recovery-test.sh
# 每月自动触发一次恢复测试：
# 1. 从备份恢复到测试实例
# 2. 运行数据完整性检查SQL
# 3. 验证关键表记录数对比
# 4. 发送演练报告到指定邮件
# 记录测试结果到 audit_logs 表

# 等保要求：需要保留恢复演练记录
```

**任务4.3：业务数据实时异地备份（Redis流水）**（2天）
```python
# edge/sync-engine/disaster_recovery.py
# 关键交易数据（orders/pos_transactions）写入时
# 同步推送到腾讯云COS对象存储（另一地域）
# 保留最近7天的WAL日志供时间点恢复
```

**任务4.4：个人信息保护合规**（2天）
```python
# 等保 + 个人信息保护法(PIPL)要求
# 1. 数据最小化：在Customer模型中标记必填vs可选字段
# 2. 删除机制：实现"客户注销"功能（软删除+定期清理加密字段）
# 3. 数据导出：支持客户申请导出自己的数据
# 4. 隐私协议版本管理：记录用户同意记录
```

**Phase 2 完成标准**:
- [ ] Customer/Employee表phone字段已加密存储（AES-256）
- [ ] orders/financial_records有HMAC完整性签名
- [ ] 广州→上海异地备份已开启，每日全量验证
- [ ] 首次恢复演练记录已存档

---

### Phase 3：网络安全 + 边界防护（Week 11-13）

> **对应等保控制点**: 安全区域边界、安全通信网络

#### Week 11：腾讯云WAF + 安全组收紧

**任务5.1：WAF接入**（2天）
```
腾讯云WAF（Web应用防火墙）接入：
1. 购买腾讯云WAF（入门版，约200元/月）
2. 配置防护域名：api.tunxiang.com
3. 开启规则集：
   - OWASP Top 10防护
   - SQL注入防护
   - XSS防护
   - CC攻击防护（API接口限速）
4. 自定义规则：
   - /api/v1/auth/* 接口：IP限速 10次/分钟
   - /api/v1/admin/* 接口：仅允许指定IP段访问
```

**任务5.2：VPC安全组白名单收紧**（1天）
```
当前问题：腾讯云服务器安全组过于宽松
收紧策略：
- 22(SSH)：仅允许 管理员固定IP + Tailscale网段 (100.x.x.x)
- 5432(PostgreSQL)：仅允许 VPC内网IP
- 8000(FastAPI)：仅允许 WAF回源IP段 + VPC内网
- 80/443：全开（通过WAF）
- 其他端口：全部关闭
```

**任务5.3：TLS安全配置**（1天）
```nginx
# 禁用TLS 1.0/1.1，仅允许TLS 1.2+
ssl_protocols TLSv1.2 TLSv1.3;
# 禁用弱密码套件
ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:...;
# HSTS
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains";
# 安全响应头
add_header X-Frame-Options DENY;
add_header X-Content-Type-Options nosniff;
add_header Content-Security-Policy "default-src 'self'";
```

#### Week 12-13：堡垒机 + 运维审计

**背景**: 等保三级要求"通过堡垒机对数据库和服务器进行统一管理"。点评微生活使用阿里云堡垒机，屯象OS可使用腾讯云堡垒机或开源JumpServer。

**任务6.1：JumpServer堡垒机部署**（3天）
```yaml
# 方案：JumpServer Community Edition（开源，免费）
# 部署在独立Docker容器，独立网络分区

# docker-compose.jumpserver.yml（新增）
services:
  jumpserver:
    image: jumpserver/jms_all:latest
    ports:
      - "2222:2222"   # SSH代理端口（内网only）
      - "9090:80"     # Web界面（内网only）
    volumes:
      - ./data/jumpserver:/opt/jumpserver/data

# 配置：
# 1. 将所有服务器资产录入JumpServer
# 2. 禁止直接SSH到服务器（安全组收紧22端口只允许JumpServer IP）
# 3. 所有运维操作通过JumpServer，自动录屏存档
```

**任务6.2：数据库审计**（2天）
```
方案A：腾讯云数据库审计（推荐，~30元/月）
- 开启SQL审计，记录所有DDL/DML操作
- 审计日志保留180天
- 配置告警：DROP TABLE / DELETE大量数据 / 非工作时间操作

方案B：pgaudit扩展（自建，免费）
- 在PostgreSQL中安装pgaudit
- 配置审计规则写入pg日志
- 日志推送到腾讯云CLS
```

**任务6.3：Mac mini 安全加固**（2天）
```bash
# Mac mini边缘节点安全配置
# 1. 禁用密码登录，仅允许SSH密钥认证
# 2. 配置macOS防火墙，只开放8000/8100端口（localhost访问）
# 3. Tailscale ACL：Mac mini只允许访问云端PostgreSQL和Redis
# 4. 自动安全更新开启
# 5. 定期轮换Tailscale预共享密钥
```

**Phase 3 完成标准**:
- [ ] WAF已接入，OWASP规则集开启
- [ ] 安全组白名单：SSH仅限管理IP
- [ ] JumpServer堡垒机可用，所有服务器运维通过堡垒机
- [ ] 数据库审计日志开启，保留≥180天
- [ ] TLS 1.2+，安全响应头配置完成

---

### Phase 4：安全审计中心（Week 14-16）

> **对应等保控制点**: 安全管理中心、安全审计

#### Week 14-15：统一安全审计日志

**任务7.1：审计日志表设计**（2天）
```python
# 等保要求审计日志覆盖：用户行为、管理操作、安全事件
# shared/ontology/audit.py

class AuditLog(BaseModel):
    id: UUID
    # 事件基础信息
    event_type: AuditEventType    # LOGIN/LOGOUT/DATA_ACCESS/CONFIG_CHANGE/SECURITY_EVENT
    event_time: datetime
    # 主体（操作者）
    operator_id: UUID | None
    operator_role: str
    operator_ip: str
    operator_ua: str             # User-Agent
    # 客体（被操作资源）
    resource_type: str           # 表名/模块名
    resource_id: str | None
    action: str                  # CREATE/READ/UPDATE/DELETE
    # 结果
    result: Literal["success", "failure", "blocked"]
    failure_reason: str | None
    # 租户隔离
    tenant_id: UUID | None       # NULL表示系统级操作
    # 防篡改
    log_hash: str                # HMAC-SHA256(所有字段)，链式校验
```

**任务7.2：审计日志中间件**（2天）
```python
# services/gateway/src/middleware/audit.py
# FastAPI中间件：自动记录所有API请求到审计日志

class AuditMiddleware(BaseHTTPMiddleware):
    SENSITIVE_PATHS = ["/auth/", "/admin/", "/api/v1/members/"]

    async def dispatch(self, request: Request, call_next):
        # 记录请求开始
        start_time = time.time()
        response = await call_next(request)
        # 写入审计日志（异步，不阻塞响应）
        await self.log_audit_event(request, response, time.time() - start_time)
        return response
```

**任务7.3：腾讯云CLS统一日志**（2天）
```python
# 所有服务日志→腾讯云CLS（Cloud Log Service）
# 日志分类：
# - 业务日志（info级别，保留30天）
# - 安全审计日志（全级别，保留180天，等保要求）
# - 异常告警日志（error级别，保留90天）

# 告警规则配置：
# - 5分钟内同一IP登录失败≥10次 → 告警+自动封禁IP
# - 非工作时间（23:00-6:00）admin登录 → 即时告警
# - 数据批量导出（>1000条）→ 审计告警
# - 数据库DROP/TRUNCATE操作 → 紧急告警
```

#### Week 16：安全监控 + 漏洞扫描

**任务8.1：接口防刷 + 异常检测**（2天）
```python
# services/gateway/src/security/rate_limiter.py
# 基于Redis的分布式限速

RATE_LIMITS = {
    "/auth/login": RateLimit(requests=10, window=60),      # 10次/分钟/IP
    "/auth/mfa/verify": RateLimit(requests=5, window=60),  # 5次/分钟
    "/api/v1/members/": RateLimit(requests=100, window=60), # 100次/分钟/租户
    "default": RateLimit(requests=500, window=60),
}

# 自动封禁：连续10次失败→封禁IP 30分钟
# 记录到audit_logs（event_type=SECURITY_EVENT）
```

**任务8.2：CI/CD漏洞扫描集成**（2天）
```yaml
# .github/workflows/security-scan.yml
# 每次PR触发 + 每周全量扫描

jobs:
  security:
    steps:
      - name: 依赖漏洞扫描
        uses: aquasecurity/trivy-action@master
        with:
          scan-type: fs
          security-checks: vuln,secret

      - name: SAST静态代码分析
        run: |
          bandit -r services/ -f json -o bandit-report.json

      - name: 密钥泄露扫描
        run: git-secrets --scan

      - name: 端口暴露扫描（每周）
        run: nmap -sV 42.194.229.21 >> scan-report.txt
```

**Phase 4 完成标准**:
- [ ] 审计日志表设计完成，覆盖LOGIN/DATA_ACCESS/CONFIG_CHANGE
- [ ] 所有API操作自动写审计日志
- [ ] CLS日志保留180天，告警规则≥5条
- [ ] 接口限速：auth类≤10次/分钟/IP
- [ ] CI/CD集成bandit+trivy扫描，有缺陷阻断合并

---

### Phase 5：安全管理制度文档（Week 17-18）

> **对应等保控制点**: 安全管理制度、安全建设管理、安全运维管理

**等保测评时，文档是重要评分项。点评微生活因文档不全被扣分多处。**

#### 必须准备的文档（9份）

| 文档名称 | 对应等保控制点 | 目标完成周 |
|---------|-------------|----------|
| 信息安全管理办法 | 安全管理制度-安全策略 | Week 17 |
| 网络安全管理规定 | 安全管理制度-管理制度 | Week 17 |
| 数据备份和恢复管理规定 | 安全管理制度-管理制度 | Week 17 |
| 信息系统运维安全管理规定 | 安全管理制度-管理制度 | Week 17 |
| 安全事件分类分级及应急预案 | 安全运维管理-应急预案管理 | Week 18 |
| 信息资产清单（含数据分类分级） | 安全运维管理-资产管理 | Week 18 |
| 密码管理制度 | 安全运维管理-密码管理 | Week 18 |
| 软件开发安全管理规定 | 安全建设管理-自行软件开发 | Week 18 |
| 供应商安全管理规定 | 安全建设管理-服务供应商选择 | Week 18 |

**模板指引**（减少写作工作量）：

```
信息安全管理办法（核心，约3000字）：
1. 适用范围：屯象OS及其服务的所有客户数据处理
2. 信息安全目标：保密性/完整性/可用性
3. 岗位职责：系统管理员/审计管理员/安全管理员
4. 违规处理：分级处罚条款

应急预案（核心，约2000字）：
分级：特别重大事件/重大事件/较大事件/一般事件
每级：发现→报告→隔离→恢复→复盘的标准流程
联系人：李淳 + 腾讯云应急响应 + 客户联系人

信息资产清单（表格，关键）：
| 资产名称 | 类型 | 重要级别 | 负责人 | 存储位置 | 备份策略 |
| 客户会员数据 | 数据资产 | 机密 | 李淳 | 腾讯云广州+上海 | 每日备份 |
| 交易流水数据 | 数据资产 | 机密 | 李淳 | 腾讯云广州+上海 | 实时备份 |
...
```

**Week 17-18 任务**:
- [ ] 9份安全管理文档完成（Word格式）
- [ ] 文档通过企业微信或内部系统发布（留存发布记录）
- [ ] 应急预案演练一次（桌面推演即可），留存记录

---

### Phase 6：等保测评准备（Week 19-20）

> **目标**: 完成自测，向测评机构提交申请

#### Week 19：自查整改

**任务9.1：等保自查清单验证**（3天）
```
按照GB/T 22239-2019三级要求，逐项自查：
参考点评微生活报告的20个中风险问题，确认屯象OS已全部解决：
✅ 双因素认证（Phase 1实现）
✅ 最小权限 + 三权分立（Phase 1实现）
✅ 敏感数据加密存储（Phase 2实现）
✅ 异地备份（Phase 2实现）
✅ WAF（Phase 3实现）
✅ 堡垒机（Phase 3实现）
✅ 数据库审计（Phase 3实现）
✅ 审计日志180天（Phase 4实现）
✅ 安全管理制度文档（Phase 5实现）
```

**任务9.2：渗透测试自测**（2天）
```bash
# 使用OWASP ZAP或Burp Suite Community对自身系统做基础渗透测试
# 重点检查：
# - SQL注入
# - XSS
# - 越权访问（租户隔离是否严格）
# - 接口枚举
# - JWT伪造
# 发现问题立即修复，留存测试报告
```

#### Week 20：测评机构申请

**申请流程**:
```
1. 确定等保定级（目标：S3A2，业务信息三级+系统服务二级）
2. 填写《信息系统安全等级保护定级报告》
3. 向公安机关（长沙市）提交备案申请
4. 选择具备等级测评资质的机构
   推荐：CAICT（中国信通院）、中国电子信息产业集团六所等
   费用预算：3-8万元
5. 提交测评材料包：
   - 网络安全等级保护定级报告
   - 系统资产清单（附录A）
   - 各类安全管理制度文档
   - 安全建设方案
6. 配合现场测评（约2天）
7. 整改复核
8. 获得测评报告
```

---

## 四、技术实现优先级矩阵

### 开发工作量估算

| 任务 | 工作量 | 测评影响 | 优先级 |
|------|-------|---------|-------|
| RLS修复 | 1天 | 阻塞 | P0 |
| 凭证清理 | 1天 | 阻塞 | P0 |
| 异常处理收窄 | 1周 | 阻塞 | P0 |
| MFA双因素认证 | 1周 | 中风险→修复 | P1 |
| RBAC三权分立 | 1周 | 中风险→修复 | P1 |
| PII字段加密 | 1周 | 中风险→修复 | P1 |
| 异地备份 | 3天 | 中风险→修复 | P1 |
| WAF接入 | 2天 | 中风险→修复 | P1 |
| 堡垒机 | 3天 | 中风险→修复 | P1 |
| 数据库审计 | 1天 | 中风险→修复 | P1 |
| 审计日志中间件 | 1周 | 符合性 | P2 |
| 安全管理文档 | 1周 | 符合性 | P2 |
| 漏洞扫描CI | 3天 | 符合性 | P2 |
| 应急预案 | 2天 | 符合性 | P2 |

### 云服务成本预算（月均）

| 服务 | 费用 | 说明 |
|------|------|------|
| 腾讯云WAF（入门版） | ~200元/月 | 必须 |
| 腾讯云数据库审计 | ~50元/月 | 必须 |
| 腾讯云CLS日志 | ~30元/月 | 必须 |
| 腾讯云跨地域备份 | ~100元/月 | 必须 |
| 腾讯云SMS（验证码） | ~50元/月 | MFA短信 |
| JumpServer堡垒机 | 0元 | 开源自部署 |
| **合计新增** | **~430元/月** | |

### 测评一次性成本

| 项目 | 费用 |
|------|------|
| 等保测评费用 | 3-8万元 |
| 整改后复核 | 包含在测评费中 |
| 年度维护（复测） | 约2-3万元/年 |

---

## 五、20周甘特图

```
周次  | 1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20
------+------------------------------------------------------------
P0修复| ██ ██
身份鉴别|        ██ ██ ██ ██
RBAC  |              ██ ██ ██ ██
PII加密|                       ██ ██
备份  |                          ██ ██
WAF   |                                ██
堡垒机|                                   ██ ██
数据库审|                                      ██
审计日志|                                         ██ ██ ██
漏洞扫描|                                               ██
文档  |                                                  ██ ██
等保申请|                                                        ██ ██
```

---

## 六、点评微生活 vs 屯象OS合规目标对比

| 等保控制项 | 点评微生活现状 | 屯象OS目标 |
|-----------|-------------|----------|
| 双因素认证 | ❌ 中风险缺失 | ✅ Phase 1实现 |
| 最小权限/三权分立 | ❌ 中风险缺失 | ✅ Phase 1实现 |
| 数据加密存储 | ❌ 中风险缺失 | ✅ Phase 2实现 |
| 异地备份 | ❌ 中风险缺失 | ✅ Phase 2实现 |
| WAF | ✅ 已有 | ✅ Phase 3实现 |
| 堡垒机 | ✅ 已有 | ✅ Phase 3实现 |
| 数据库审计 | ✅ 已有 | ✅ Phase 3实现 |
| 安全审计日志 | ✅ 已有（覆盖全用户） | ✅ Phase 4实现 |
| 安全管理制度 | ✅ 已有（部分不完善） | ✅ Phase 5实现 |
| 应急预案 | ❌ 未演练 | ✅ Phase 5实现 |

**目标得分**: 屯象OS补齐以上20个中风险项后，对标点评微生活84.29分基础上，可期望达到**87-90分（良）**。

---

## 七、关键里程碑

| 里程碑 | 时间节点 | 验收标准 |
|-------|---------|---------|
| **M0: P0清零** | Week 2末 | 无凭证泄露/无RLS失效/无静默异常 |
| **M1: 身份安全** | Week 6末 | MFA上线/三权分立/权限矩阵完成 |
| **M2: 数据安全** | Week 10末 | PII加密/异地备份/完整性校验 |
| **M3: 边界安全** | Week 13末 | WAF/堡垒机/数据库审计全部上线 |
| **M4: 审计体系** | Week 16末 | 统一日志/告警规则/漏洞扫描CI |
| **M5: 制度体系** | Week 18末 | 9份文档完成并发布 |
| **M6: 测评申请** | Week 20末 | 提交备案+选定测评机构+约定测评时间 |

---

*文档维护*: 每个Phase完成后更新完成状态。测评整改后在此文档记录实际得分和整改项。
