# 字段加密运维手册

等保三级 · 数据保密性与完整性

---

## 一、涉及的环境变量

| 变量名 | 用途 | 格式 | 必须 |
|--------|------|------|------|
| `TX_FIELD_ENCRYPTION_KEY` | AES-256-GCM字段加密主密钥 | 64位十六进制字符串（32字节） | 是 |
| `TX_INTEGRITY_SECRET` | HMAC-SHA256完整性校验密钥 | 任意字符串（建议>=32字节） | 是 |

---

## 二、生成密钥

### 生成 TX_FIELD_ENCRYPTION_KEY（AES-256主密钥）

```bash
python3 -c "import os; print(os.urandom(32).hex())"
# 示例输出（每次不同）：
# a3f8c2d1e4b7a091c5d2e3f4a1b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6
```

生成后立即存入密钥管理系统，不要在终端历史中保留。

### 生成 TX_INTEGRITY_SECRET（HMAC密钥）

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
# 示例输出：
# 7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e
```

---

## 三、密钥安全存储

### 方案A：腾讯云KMS（生产推荐）

1. 在腾讯云控制台创建KMS密钥，用于加密上述两个密钥的明文值
2. 将加密后的密文存入腾讯云 SSM（Secrets Manager）
3. 部署时通过 SSM SDK 动态注入环境变量，不落盘

```python
# 从腾讯云SSM获取密钥示例（伪代码）
import tencentcloud.ssm.v20190923 as ssm_client

def get_secret(secret_name: str) -> str:
    client = ssm_client.SsmClient(cred, "ap-guangzhou")
    req = ssm_client.GetSecretValueRequest()
    req.SecretName = secret_name
    resp = client.GetSecretValue(req)
    return resp.SecretString
```

### 方案B：本地 .env 文件（仅开发/测试）

```bash
# .env（务必加入 .gitignore，绝不提交到代码库）
TX_FIELD_ENCRYPTION_KEY=<64位hex>
TX_INTEGRITY_SECRET=<32字节hex>
DATABASE_URL=postgresql://user:pass@localhost:5432/tunxiang
```

验证 .gitignore 包含：

```
.env
*.env
.env.*
!.env.example
```

---

## 四、部署配置步骤

### 云端服务（腾讯云）

1. 在腾讯云SSM创建两个密钥：`tunxiang/prod/field-encryption-key` 和 `tunxiang/prod/integrity-secret`
2. 在 ECS / CVM 的实例角色中授予 SSM 读取权限
3. 在 systemd 服务文件或 Docker Compose 中，通过启动脚本从 SSM 加载环境变量

```bash
# /etc/systemd/system/tunxiang-api.service 示例
[Service]
EnvironmentFile=/run/tunxiang/secrets.env   # 由 ExecStartPre 脚本从KMS写入
ExecStartPre=/opt/tunxiang/scripts/load-kms-secrets.sh
ExecStart=/opt/tunxiang/venv/bin/uvicorn main:app ...
```

### Mac mini 边缘服务

```bash
# macOS launchd plist 中配置环境变量
# /Library/LaunchDaemons/com.tunxiang.mac-station.plist
<key>EnvironmentVariables</key>
<dict>
    <key>TX_FIELD_ENCRYPTION_KEY</key>
    <string>从KMS拉取，由安装脚本写入</string>
</dict>
```

---

## 五、密钥轮换流程

密钥轮换需要做到"双密钥解密、新密钥加密"，避免数据不可读。

### 步骤

1. **生成新密钥**：按第二节方式生成新的 `TX_FIELD_ENCRYPTION_KEY_NEW`

2. **同时配置两个密钥**：修改 `shared/utils/field_encryption.py`（或通过配置）支持旧密钥解密：
   ```
   TX_FIELD_ENCRYPTION_KEY=<旧密钥>      # 用于解密存量数据
   TX_FIELD_ENCRYPTION_KEY_V2=<新密钥>   # 用于加密新写入数据
   ```

3. **重新加密存量数据**（轮换迁移脚本）：
   ```bash
   python3 scripts/rotate_field_encryption.py \
     --old-key $TX_FIELD_ENCRYPTION_KEY \
     --new-key $TX_FIELD_ENCRYPTION_KEY_V2
   ```
   脚本逻辑：SELECT → 旧密钥解密 → 新密钥加密 → UPDATE，批量处理，断点续传

4. **切换到新密钥**：将 `TX_FIELD_ENCRYPTION_KEY` 更新为新密钥值，移除旧密钥配置

5. **验证**：随机抽查若干记录，确认解密正常

6. **废弃旧密钥**：从KMS中删除旧密钥（保留审计记录）

### 轮换周期

- 等保三级建议：每年至少一次
- 发生密钥泄露时：立即轮换

---

## 六、PII迁移脚本执行步骤

迁移脚本将历史明文手机号加密，回填 `*_encrypted` 列。

### 前提条件

- 已执行数据库迁移 `v074_pii_encryption`（`alembic upgrade v074`）
- 已配置 `TX_FIELD_ENCRYPTION_KEY` 和 `DATABASE_URL`
- 已完成实际DB连接代码（`scripts/migrate_pii_encryption.py` 中的 TODO 注释）
- 生产数据库已做快照备份

### 执行步骤

```bash
# 1. 安装依赖
pip install cryptography asyncpg structlog

# 2. 配置环境变量（从KMS或临时.env）
export TX_FIELD_ENCRYPTION_KEY=<64位hex>
export TX_INTEGRITY_SECRET=<32字节hex>
export DATABASE_URL=postgresql://user:pass@host:5432/tunxiang

# 3. 执行迁移（支持 Ctrl+C 中断后续传）
python3 scripts/migrate_pii_encryption.py

# 4. 验证加密结果（SQL抽样检查）
psql $DATABASE_URL -c "
  SELECT
    COUNT(*) AS total,
    COUNT(phone_encrypted) AS encrypted_count,
    COUNT(phone_last4) AS last4_count,
    COUNT(*) FILTER (WHERE phone_encrypted LIKE 'enc:v1:%') AS valid_format
  FROM customers
  WHERE primary_phone IS NOT NULL;
"

# 5. 验证解密可用（Python）
python3 -c "
from shared.utils.field_encryption import get_encryption
enc = get_encryption()
import asyncpg, asyncio, os
async def check():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    row = await conn.fetchrow('SELECT phone_encrypted, phone_last4, primary_phone FROM customers WHERE phone_encrypted IS NOT NULL LIMIT 1')
    decrypted = enc.decrypt(row['phone_encrypted'])
    assert decrypted == row['primary_phone'], '解密不匹配！'
    print('验证通过：', enc.mask_decrypted_phone(decrypted), '==', row['primary_phone'][-4:])
asyncio.run(check())
"

# 6. 30天后删除明文列（需另建迁移文件 v075_remove_plaintext_phone.py）
# alembic upgrade v075
```

### 30天后清理明文列（v075迁移参考）

```python
# v075_remove_plaintext_phone.py（迁移完成确认后手动创建）
def upgrade():
    op.drop_index("idx_customer_phone_active", table_name="customers")
    op.drop_column("customers", "primary_phone")
    op.drop_column("employees", "phone")
    op.drop_column("employees", "emergency_phone")
    # 为新的加密列创建辅助索引（基于last4模糊搜索）
    op.create_index("idx_customer_phone_last4", "customers", ["phone_last4"])
    op.create_index("idx_employee_phone_last4", "employees", ["phone_last4"])
```

---

## 七、加密字段格式说明

```
enc:v1:<base64编码数据>
         └── base64 decode 后结构：
             [12字节 GCM Nonce][N字节密文+16字节GCM Tag]
```

- 前缀 `enc:v1:` 用于区分加密值与明文值（渐进式迁移兼容）
- 每次加密使用随机Nonce，相同明文每次密文不同（防彩虹表）
- GCM Tag提供认证，密文被篡改时解密抛出 `InvalidTag` 异常

---

## 八、监控与告警

建议配置以下监控：

- `phone_encrypted` 列 NULL 率监控：迁移后应为 0%
- 解密失败率告警（`InvalidTag` 异常）：超过 0.01% 触发告警
- 环境变量缺失告警：服务启动时检测并记录到日志

---

*文档版本：2026-03-31 | 对应迁移：v074_pii_encryption*
