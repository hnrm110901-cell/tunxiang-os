# 腾讯云 CLS 日志配置方案

将屯象OS的 structlog JSON 日志推送到腾讯云日志服务（CLS），
满足等保三级日志留存要求，并支持安全告警。

- 服务器：腾讯云广州 42.194.229.21
- 日志框架：structlog（JSON 格式，见 CLAUDE.md 编码规范）
- 日志分类：audit（审计） / security（安全） / business（业务）

---

## 一、创建日志集与日志主题

### 1.1 创建日志集

路径：腾讯云控制台 → 日志服务 CLS → 日志集 → 创建日志集。

| 日志集名称 | 地域 | 说明 |
|-----------|------|------|
| `txos-logs` | 广州 | 屯象OS全量日志集 |

### 1.2 创建日志主题（按类型分离）

在 `txos-logs` 日志集下创建以下主题：

| 主题名称 | 保留时长 | 说明 |
|---------|---------|------|
| `audit` | **180 天** | 操作审计（等保强制要求） |
| `security` | **90 天** | 安全事件（登录异常/权限变更） |
| `business` | **30 天** | 业务日志（订单/菜品/会员） |
| `waf-access-log` | **180 天** | WAF 访问日志（见 WAF 配置文档） |
| `nginx-access` | **30 天** | Nginx 访问日志 |

**保留时长说明**：
- audit 180 天：等保三级明确要求用户操作日志至少保留 6 个月
- security 90 天：安全事件溯源需要，ISO 27001 建议值
- business 30 天：业务运营分析够用，节省存储成本

---

## 二、LogListener 安装（服务器端采集）

### 2.1 下载安装 LogListener

```bash
# SSH 登录服务器
ssh deploy@42.194.229.21

# 下载 LogListener（腾讯云提供，免费）
wget https://mirrors.tencent.com/install/cls/loglistener-linux-arm64-2.9.3.tar.gz
tar -xzf loglistener-linux-arm64-2.9.3.tar.gz
mv loglistener /usr/local/loglistener

# 安装为系统服务（开机自启）
/usr/local/loglistener/tools/loglistener.sh install
systemctl enable loglistener
systemctl start loglistener
```

### 2.2 配置 LogListener 认证

```bash
# 编辑配置文件
vim /usr/local/loglistener/etc/loglistener.conf
```

```ini
[LogListener]
# 腾讯云 API 密钥（使用最小权限子账号）
# 权限：QcloudCLSFullAccess（或自定义最小权限）
secret_id  = AKID替换为实际值
secret_key = 替换为实际值
region     = ap-guangzhou

# LogListener 自身日志级别
log_level  = WARN
```

---

## 三、采集规则配置

### 3.1 采集 audit 日志

路径：CLS 控制台 → 日志主题 `audit` → 采集配置 → 新建采集配置。

| 配置项 | 值 |
|-------|----|
| 采集方式 | LogListener（机器组） |
| 机器组 | txos-prod（42.194.229.21） |
| 日志路径 | `/opt/txos/logs/audit/*.log` |
| 采集模式 | 单行-完整日志（JSON 格式自动解析） |

**屯象OS audit 日志格式**（structlog JSON）：
```json
{
  "event": "auth.login",
  "level": "info",
  "timestamp": "2026-03-31T10:00:00+08:00",
  "user_id": "uuid",
  "tenant_id": "uuid",
  "role": "store_admin",
  "ip": "1.2.3.4",
  "user_agent": "...",
  "result": "success"
}
```

**开启索引**（用于 SQL 检索告警）：
- `event`：字符串
- `user_id`：字符串
- `tenant_id`：字符串
- `role`：字符串
- `ip`：字符串
- `result`：字符串
- `timestamp`：时间戳（自动解析）

### 3.2 采集 security 日志

| 配置项 | 值 |
|-------|----|
| 日志路径 | `/opt/txos/logs/security/*.log` |
| 关键字段索引 | `event` / `severity` / `ip` / `user_id` |

### 3.3 采集 Nginx 访问日志

| 配置项 | 值 |
|-------|----|
| 日志路径 | `/var/log/nginx/txos-access.log` |
| 解析模式 | Nginx 访问日志（使用正则或 Nginx JSON 格式） |

**建议将 Nginx 日志改为 JSON 格式**（在 nginx-tls-hardened.conf 中添加）：

```nginx
log_format json_combined escape=json
  '{'
    '"time":"$time_iso8601",'
    '"remote_addr":"$remote_addr",'
    '"method":"$request_method",'
    '"uri":"$uri",'
    '"status":$status,'
    '"body_bytes_sent":$body_bytes_sent,'
    '"request_time":$request_time,'
    '"http_referer":"$http_referer",'
    '"http_user_agent":"$http_user_agent"'
  '}';

access_log /var/log/nginx/txos-access.log json_combined;
```

---

## 四、关键安全告警规则（CLS SQL）

路径：CLS 控制台 → 日志主题 `audit` → 告警策略 → 新建告警。

### 告警1：登录失败暴增（暴力破解预警）

```sql
-- 5分钟内同一IP登录失败超过50次
SELECT ip, count(*) AS cnt
FROM audit
WHERE event = 'auth.login_failed'
  AND __TIMESTAMP__ > now() - 5 * 60 * 1000
GROUP BY ip
HAVING cnt > 50
```

| 配置项 | 值 |
|-------|----|
| 执行周期 | 每 5 分钟 |
| 触发条件 | 结果行数 > 0 |
| 告警级别 | 紧急（P0） |
| 通知方式 | 短信 + 企业微信 |

### 告警2：非工作时间 Admin 登录

```sql
-- 22:00 ~ 08:00 期间 system_admin 角色登录
SELECT *
FROM audit
WHERE event = 'auth.login'
  AND role IN ('system_admin', 'tenant_admin')
  AND (
    HOUR(FROM_UNIXTIME(__TIMESTAMP__ / 1000, 8)) > 22
    OR HOUR(FROM_UNIXTIME(__TIMESTAMP__ / 1000, 8)) < 8
  )
  AND result = 'success'
```

| 配置项 | 值 |
|-------|----|
| 执行周期 | 每 15 分钟 |
| 触发条件 | 结果行数 > 0 |
| 告警级别 | 高（P1） |
| 通知方式 | 短信 |

### 告警3：批量数据导出

```sql
-- 单次导出记录数超过1000条
SELECT user_id, event, record_count, tenant_id
FROM audit
WHERE event IN ('data.export', 'member.export', 'order.export')
  AND record_count > 1000
  AND __TIMESTAMP__ > now() - 60 * 60 * 1000
```

| 配置项 | 值 |
|-------|----|
| 执行周期 | 每小时 |
| 触发条件 | 结果行数 > 0 |
| 告警级别 | 中（P2） |
| 通知方式 | 企业微信 |

### 告警4：RLS 绕过尝试（安全红线）

```sql
-- 检测到 tenant_id = NULL 或跨租户查询尝试
SELECT *
FROM security
WHERE event = 'rls.bypass_attempt'
   OR event = 'auth.unauthorized_tenant_access'
```

| 配置项 | 值 |
|-------|----|
| 执行周期 | 每 1 分钟 |
| 触发条件 | 结果行数 > 0 |
| 告警级别 | 紧急（P0） |
| 通知方式 | 短信 + 立即通知 |

### 告警5：Agent 决策三条硬约束违反

```sql
-- 折扣守护 / 食安 / 出餐时间硬约束被违反
SELECT agent_id, decision_type, constraint_violated, tenant_id
FROM audit
WHERE event = 'agent.constraint_violation'
```

| 配置项 | 值 |
|-------|----|
| 执行周期 | 每 5 分钟 |
| 触发条件 | 结果行数 > 0 |
| 告警级别 | 高（P1） |
| 通知方式 | 短信 + 企业微信 |

---

## 五、FastAPI structlog 日志路由配置

屯象OS 各 FastAPI 服务需要按日志类型写入不同文件，
LogListener 按路径分别采集。

```python
# services/gateway/logging_config.py
import structlog
import logging

def configure_logging():
    """配置 structlog 按类型分发日志文件."""

    # audit 日志（操作审计）：用户登录/数据操作/权限变更
    audit_handler = logging.FileHandler("/opt/txos/logs/audit/audit.log")

    # security 日志（安全事件）：异常访问/RLS告警/Agent约束违反
    security_handler = logging.FileHandler("/opt/txos/logs/security/security.log")

    # business 日志（业务日志）：订单/菜品/库存等常规操作
    business_handler = logging.FileHandler("/opt/txos/logs/business/business.log")

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=False),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
```

**使用示例**：

```python
import structlog

audit_log = structlog.get_logger("audit")
security_log = structlog.get_logger("security")

# 记录用户登录审计
audit_log.info(
    "auth.login",
    user_id=str(user.id),
    tenant_id=str(user.tenant_id),
    role=user.role,
    ip=request.client.host,
    result="success",
)

# 记录安全事件
security_log.warning(
    "auth.login_failed",
    ip=request.client.host,
    username=username,
    reason="invalid_password",
)
```

---

## 六、月度成本估算

| 项目 | 存储量 | 费用/月 |
|------|-------|--------|
| audit 日志（180天） | ~10GB | ~5元 |
| security 日志（90天） | ~2GB | ~1元 |
| business 日志（30天） | ~5GB | ~2元 |
| waf-access-log（180天） | ~15GB | ~8元 |
| nginx-access（30天） | ~3GB | ~1元 |
| CLS 检索费用 | - | ~5元 |
| **合计** | | **~22元/月** |

---

## 七、检查清单

- [ ] CLS 日志集和所有主题已创建，保留时长正确
- [ ] LogListener 已安装并启动（`systemctl status loglistener`）
- [ ] 各日志路径采集规则已配置
- [ ] 关键字段索引已开启（支持 SQL 检索）
- [ ] 5个告警规则已创建并测试
- [ ] 告警通知人已配置（短信验证）
- [ ] Nginx 日志格式已改为 JSON（可选优化）
