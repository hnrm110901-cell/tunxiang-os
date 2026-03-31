# 屯象OS 数据库备份配置说明

等保三级合规：异地加密备份 + 月度恢复演练。

- 备份方向：腾讯云广州（生产）→ 腾讯云上海（COS 跨地域存储）
- 加密方式：AES-256-CBC + PBKDF2（openssl）
- 保留策略：本地 30 天，COS 永久（按需手动清理 90 天以前数据）

---

## 一、前置依赖安装

```bash
# PostgreSQL 客户端
apt-get install -y postgresql-client

# 腾讯云 COS CLI（coscli）
# 下载地址：https://github.com/tencentyun/coscli/releases/latest
wget https://cosbrowser.cos.ap-guangzhou.myqcloud.com/software/coscli/coscli-linux-arm64
chmod +x coscli-linux-arm64
mv coscli-linux-arm64 /usr/local/bin/coscli

# 配置 COS 认证
coscli config set -e cos.ap-shanghai.myqcloud.com
coscli config add -b txos-backup-sh -r ap-shanghai -a <SecretId> -s <SecretKey>
```

---

## 二、配置环境变量

```bash
# 创建配置目录（仅 root 可读）
mkdir -p /etc/txos
chmod 700 /etc/txos

# 创建配置文件
cat > /etc/txos/backup.env << 'EOF'
# 数据库配置
DB_NAME=tunxiang_os
DB_HOST=127.0.0.1
DB_PORT=5432
DB_USER=txos
BACKUP_DB_PASSWORD=替换为实际密码

# 备份加密密钥（妥善保管！丢失则无法解密备份）
# 生成命令：openssl rand -base64 32
BACKUP_ENCRYPTION_KEY=替换为32字节随机字符串

# COS 配置
COS_BUCKET=txos-backup-sh
COS_REGION=ap-shanghai

# 本地备份目录和日志
BACKUP_DIR=/opt/backups/txos
LOG_FILE=/var/log/txos-backup.log
AUDIT_LOG=/var/log/txos-backup-audit.log

# 本地备份保留天数
RETAIN_DAYS=30
EOF

chmod 600 /etc/txos/backup.env
```

---

## 三、创建 COS 存储桶

腾讯云控制台 → 对象存储 COS → 存储桶列表 → 创建存储桶：

| 配置项 | 值 |
|-------|----|
| 名称 | txos-backup-sh |
| 地域 | 上海（与生产服务器广州不同地域） |
| 访问权限 | 私有读写 |
| 版本控制 | 开启（防误删） |
| 生命周期 | 90天后自动删除（按需配置） |

---

## 四、配置定时任务

```bash
# 安装脚本
mkdir -p /opt/txos/scripts/backup
cp offsite-backup.sh restore-test.sh /opt/txos/scripts/backup/
chmod +x /opt/txos/scripts/backup/*.sh

# 配置 Crontab（用 root 或有 pg_dump 权限的用户）
crontab -e

# 添加以下行：
# 每天凌晨 2:00 执行备份（业务低峰期）
0 2 * * * /opt/txos/scripts/backup/offsite-backup.sh >> /var/log/txos-backup.log 2>&1

# 每月1号凌晨 3:00 执行恢复演练
0 3 1 * * /opt/txos/scripts/backup/restore-test.sh >> /var/log/txos-backup.log 2>&1
```

---

## 五、手动测试

```bash
# 手动执行备份（首次部署验证）
bash /opt/txos/scripts/backup/offsite-backup.sh

# 查看备份日志
tail -50 /var/log/txos-backup.log

# 手动执行恢复演练
bash /opt/txos/scripts/backup/restore-test.sh

# 查看 COS 上的备份文件
coscli ls cos://txos-backup-sh/daily/ --region ap-shanghai
```

---

## 六、解密还原（生产事故恢复）

```bash
# 下载指定日期备份
coscli cp cos://txos-backup-sh/daily/20260101/20260101_020000.sql.gz.enc \
    /tmp/restore.sql.gz.enc --region ap-shanghai

# 解密
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
    -pass "pass:$BACKUP_ENCRYPTION_KEY" \
    -in /tmp/restore.sql.gz.enc \
    | gunzip > /tmp/restore.sql

# 还原（注意：会覆盖目标库！）
# psql -U txos -d tunxiang_os < /tmp/restore.sql

# 还原后删除临时文件
rm -f /tmp/restore.sql /tmp/restore.sql.gz.enc
```

---

## 七、安全注意事项

1. `BACKUP_ENCRYPTION_KEY` 是解密备份的唯一凭证，需单独备份到安全位置（如密码管理器）
2. `/etc/txos/backup.env` 权限必须是 600，不可对外暴露
3. 备份脚本日志不包含密钥内容（已通过 `env:` 方式传递给 openssl）
4. COS 存储桶开启版本控制，防止恶意删除备份

---

## 八、月度成本估算

| 项目 | 规格 | 费用/月 |
|------|------|--------|
| COS 存储（上海） | ~50GB/年（压缩+加密后） | ~5元 |
| COS 流量 | 跨地域上传免费 | 0元 |
| **合计** | | **~5元/月** |
