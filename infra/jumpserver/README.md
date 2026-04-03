# JumpServer 堡垒机部署指南

等保三级合规要求：统一运维入口、操作录屏存档、账号审计、危险命令拦截。

## 架构说明

```
运维人员本地
    │ Tailscale VPN
    ▼
腾讯云服务器 42.194.229.21
    │ 127.0.0.1:9090 (Web UI)
    │ 127.0.0.1:2222 (SSH Proxy)
    ▼
JumpServer (Docker)
    │ 代理 SSH / 录屏
    ▼
目标服务器（禁止直连）
```

**核心原则**：部署后，服务器 22 端口改为只允许 Tailscale IP 访问，
所有运维操作必须经过 JumpServer。

---

## 一、首次部署步骤

### 1.1 准备数据库

```sql
-- 在 PostgreSQL 中创建 JumpServer 专用库和用户
CREATE DATABASE jumpserver;
CREATE USER jumpserver WITH PASSWORD '强密码';
GRANT ALL PRIVILEGES ON DATABASE jumpserver TO jumpserver;
```

### 1.2 配置环境变量

```bash
cd /Users/lichun/tunxiang-os/infra/jumpserver

# 复制示例配置
cp .env.example .env

# 生成必填密钥
echo "JMS_SECRET_KEY=$(openssl rand -base64 42)"
echo "JMS_BOOTSTRAP_TOKEN=$(openssl rand -base64 16)"

# 编辑 .env 填写实际值
vim .env
```

### 1.3 启动服务

```bash
docker compose up -d

# 查看启动日志（等待约2分钟初始化完成）
docker compose logs -f jms_all

# 验证服务可用
curl -s http://127.0.0.1:9090/api/v1/health/
```

### 1.4 设置初始管理员密码

通过 Tailscale 访问 `http://<tailscale-ip>:9090`，
使用默认账号 `admin / admin` 登录，**立即修改密码**。

---

## 二、录入服务器资产

进入 `资产管理 → 资产列表 → 创建资产`：

| 字段 | 值 |
|------|----|
| 名称 | txos-prod-gz（腾讯云广州生产） |
| IP   | 42.194.229.21 |
| 协议 | SSH / 22 |
| 系统用户 | deploy（非root） |
| 认证方式 | SSH 密钥（推荐）|

**创建系统用户**（`系统用户 → 创建`）：
- 用户名：`deploy`
- 认证方式：上传 SSH 私钥
- 提权方式：`sudo`

---

## 三、配置 SSH 代理（禁止直连）

### 3.1 修改服务器 SSH 配置

```bash
# 编辑 /etc/ssh/sshd_config
# 限制直连：只允许 Tailscale IP（100.x.x.x）直接 SSH
AllowUsers deploy@100.64.0.0/10
# 禁止 root 直接登录
PermitRootLogin no
# 禁止密码认证
PasswordAuthentication no

# 重启 SSH
systemctl restart sshd
```

### 3.2 运维人员通过 JumpServer SSH

```bash
# 通过 JumpServer SSH 代理登录（替代直连服务器）
ssh -p 2222 用户名@<tailscale-ip>

# 然后在交互菜单中选择目标资产
```

---

## 四、启用操作录屏

进入 `系统设置 → 终端设置`：

- [x] 开启会话录制
- 录制存储：本地（`./data/replay/`）
- 录制格式：`asciicast`（可在 Web 界面回放）
- 保留时长：**180天**（等保三级要求）

录屏文件路径：`infra/jumpserver/data/replay/`

---

## 五、危险命令告警规则

进入 `系统设置 → 命令过滤 → 创建规则`：

### 5.1 高危命令拦截（直接阻断）

| 规则名称 | 命令正则 | 动作 |
|----------|---------|------|
| 禁止删除根目录 | `rm\s+-rf\s+/` | 拒绝 |
| 禁止格式化磁盘 | `mkfs\|fdisk\|dd\s+if=` | 拒绝 |
| 禁止关闭防火墙 | `iptables\s+-F\|ufw\s+disable` | 拒绝 |
| 禁止删除系统目录 | `rm\s+-rf\s+/(etc\|var\|usr\|opt)` | 拒绝 |

### 5.2 高风险命令告警（允许但记录告警）

| 规则名称 | 命令正则 | 动作 |
|----------|---------|------|
| 数据库DDL操作 | `DROP\s+TABLE\|DROP\s+DATABASE\|TRUNCATE` | 告警 |
| 批量删除文件 | `rm\s+-rf` | 告警 |
| 服务重启 | `systemctl\s+(stop\|restart)\|docker\s+stop` | 告警 |
| 修改nginx配置 | `vim\s+.*nginx\|nano\s+.*nginx` | 告警 |

---

## 六、账号审计配置

### 6.1 用户账号策略

- 运维人员：每人独立账号，禁止共用
- 账号命名：`姓名拼音`（如 `lichun`）
- 密码策略：长度≥12位，包含大小写+数字+特殊字符，90天强制更换

### 6.2 访问权限矩阵

| 用户 | 生产服务器 | 录屏查看 | 命令审计 |
|------|-----------|---------|---------|
| admin（创始人） | 全权 | 全部 | 全部 |
| ops-readonly | 禁止 | 禁止 | 仅查看 |

### 6.3 审计日志导出

```bash
# 导出最近30天操作记录（等保检查时使用）
# JumpServer Web UI → 审计中心 → 会话历史 → 导出CSV
```

---

## 七、日常维护

```bash
# 查看运行状态
docker compose ps

# 更新版本
docker compose pull
docker compose up -d

# 备份录屏文件
tar -czf jms-replay-$(date +%Y%m).tar.gz data/replay/

# 查看存储占用
du -sh data/replay/
```

---

## 八、月度成本估算

| 项目 | 费用 |
|------|------|
| JumpServer 社区版 | 免费 |
| 额外服务器资源（内存+磁盘） | 已含在现有服务器内 |
| 录屏存储（COS备份） | ~5元/月（预计50GB/年） |
| **合计** | **~5元/月** |
