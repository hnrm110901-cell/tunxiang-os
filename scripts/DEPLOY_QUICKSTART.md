# 屯象OS 部署快速启动指南

> Docker 就绪后，按以下步骤执行。每步都可独立运行。

## 前置条件

```bash
# 确认 Docker 可用
docker ps

# 确认 psql 可用
export PATH="/opt/homebrew/opt/libpq/bin:$PATH"
psql --version
```

## Step 1: P1 — 本地 Dev 环境 + 迁移验证

```bash
cd ~/tunxiang-os

# 启动 dev 环境（PostgreSQL + Redis）
make up
# 等待 ~30s 数据库初始化

# 验证迁移预检
make migrate-check

# 执行迁移（dev 环境不备份）
make migrate-up

# 确认迁移结果
make migrate-history
```

**预期结果**: 7 个版本全部成功，所有表 RLS 启用。

## Step 2: P2 — Staging 环境

```bash
# 创建 staging 环境变量
cp .env.staging.example .env.staging
# 编辑 .env.staging，修改密码

# 启动 staging
make up-staging
# 等待 ~60s 构建和启动

# 检查 staging 健康
curl http://localhost:8080/health

# staging 数据库迁移
DATABASE_URL=postgresql://tunxiang_stg:changeme_stg@localhost:5433/tunxiang_os_stg \
  make migrate-up
```

**预期结果**: `http://localhost:8080` 返回 JSON，staging DB 迁移完成。

## Step 3: P3 — 部署脚本验证

```bash
# 完整 staging 部署流程（预检→测试→迁移→构建→部署→健康检查）
make deploy-staging

# 观察日志
make logs-staging
```

**预期结果**: 所有步骤绿色通过，健康检查 OK。

## Step 4: P4 — 监控

```bash
# 手动运行一次监控检查
make monitor

# 安装 crontab 自动监控（每5分钟）
make monitor-install

# 确认 crontab
crontab -l | grep tunxiang

# （可选）配置企业微信告警
export ALERT_WEBHOOK="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY"
```

**预期结果**: 5 项检查全部 OK，crontab 已安装。

## 常用命令速查

| 命令 | 说明 |
|------|------|
| `make up` | 启动 dev 环境 |
| `make up-staging` | 启动 staging |
| `make up-prod` | 启动生产 |
| `make migrate-check` | 迁移预检 |
| `make migrate-up` | 执行迁移（dev） |
| `make migrate-up-safe` | 执行迁移（含备份） |
| `make migrate-rollback` | 回滚最近一次迁移 |
| `make deploy-staging` | 部署到 staging |
| `make deploy-prod` | 部署到生产 |
| `make monitor` | 手动监控检查 |
| `make test` | 运行全部测试 |
| `make smoke` | 冒烟测试 |

## 生产部署流程

```
1. make deploy-staging     # 先部署 staging
2. 手动验证 staging 功能    # 访问 http://localhost:8080
3. make deploy-prod        # 部署生产（需输入 DEPLOY 确认）
```

## 故障排查

```bash
# 查看 staging 日志
make logs-staging

# 查看特定服务日志
docker-compose -f docker-compose.staging.yml logs stg-gateway --tail=50

# 监控告警日志
tail -20 logs/monitor-alerts.log

# 迁移回滚
make migrate-rollback

# 部署历史
cat logs/deploy-history.log
```
