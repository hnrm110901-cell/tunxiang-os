# 屯象OS v3.2 Migration Guide

> 从 v3.1（含）之前的版本升级到 v3.2 的步骤指南

---

## 📋 适用范围

- **源版本**：v3.0 / v3.1（Wave 1-4 已部署）
- **目标版本**：v3.2（Wave 1-5 全部）
- **Alembic 起点**：任意 z66 以前
- **Alembic 终点**：`z69_merge_wave5` (HEAD)

---

## 🎯 升级路径概览

```
已在 z66 之前 ──► z67_merge_wave4 ──► z68×3 ──► z69_merge_wave5 (HEAD)
                   (Wave 4 HR 基础)    (Wave 5 分支)    (Wave 5 合并)
```

---

## Step 1: 停机准备（约 5 分钟）

### 1.1 备份数据库
```bash
pg_dump -U postgres zhilian_os > backup_pre_v3.2_$(date +%Y%m%d_%H%M%S).sql
```

### 1.2 确认当前迁移版本
```bash
cd apps/api-gateway
alembic current
# 预期输出：z67_merge_wave4 或更早
```

### 1.3 停止服务
```bash
# API Gateway
systemctl stop tunxiang-api

# Celery
systemctl stop tunxiang-celery-worker
systemctl stop tunxiang-celery-beat
```

---

## Step 2: 拉取 v3.2 代码（约 2 分钟）

```bash
cd /opt/tunxiang-os
git fetch origin
git checkout feature/d5-d12-compliance-wave123
git log --oneline -5
# 预期看到：23a88baf / 360ec0f8 / 0c2fb5bf / 73af464d / fe352e8
```

### 安装新增依赖
```bash
cd apps/api-gateway
pip install -r requirements.txt
# 新增依赖：
#   reportlab>=4.0.0
#   qrcode[pil]>=7.4.0
#   openai>=1.40.0  (LLM 三级降级需要)
```

---

## Step 3: Docker 镜像更新（重要！）

> 如用 Docker 部署，Dockerfile 必须加中文字体，否则 PDF 中文显示方块

### 编辑 Dockerfile
```dockerfile
FROM python:3.11-slim

# ⭐ 新增：中文字体（证书 PDF / 电子签约 PDF 依赖）
RUN apt-get update && apt-get install -y \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# ... 其余保持不变
```

### 重新构建
```bash
docker build -t tunxiang-api:v3.2 .
```

---

## Step 4: 应用数据库迁移（约 3 分钟）

### 4.1 预览即将执行的迁移
```bash
alembic history | head -30
# 应看到从 z67_merge_wave4 到 z69_merge_wave5 的链路
```

### 4.2 执行升级
```bash
alembic upgrade head
```

**预期新建 20 张表**：
- `legal_entities` / `store_legal_entities`
- `signature_templates` / `signature_seals` / `signature_envelopes` / `signature_records` / `signature_audit_logs`
- `objectives` / `key_results` / `okr_updates` / `okr_alignments`
- `learning_paths` / `learning_path_enrollments` / `learning_points` / `learning_achievements`
- `pulse_survey_templates` / `pulse_survey_instances` / `pulse_survey_responses`
- `hr_conversations` / `hr_messages`

### 4.3 验证
```bash
alembic current
# 预期：z69_merge_wave5 (head)

alembic heads
# 预期：
#   z51_customer_dish_interactions (head)   ← 遗留技术债，不动
#   z69_merge_wave5 (head)
```

---

## Step 5: 新增环境变量配置

### 5.1 编辑 `.env`
```diff
# 原有
  ANTHROPIC_API_KEY=sk-ant-xxx

# 新增（Wave 2 LLM 降级链）
+ DEEPSEEK_API_KEY=sk-xxxxx
+ OPENAI_API_KEY=sk-xxxxx
+ LLM_PROVIDER_PRIORITY=claude,deepseek,openai
+ LLM_FALLBACK_ENABLED=true
+ LLM_TIMEOUT_SEC=5

# 新增（Wave 3 证书公开验证）
+ PUBLIC_DOMAIN=https://zlsjos.cn
```

### 5.2 如客户未开通 DeepSeek/OpenAI
```env
# 仍保留默认配置，LLM_FALLBACK_ENABLED=true 不会因缺 Key 报错
# 但生产建议至少配置 2 家，否则 Claude 挂了整个 AI 层停摆
```

---

## Step 6: 运行种子数据（重要！）

> ⚠️ 仅在 Wave 4/5 首次升级时跑，避免重复 upsert

### 6.1 会计科目（Wave 1，如已跑过可跳过）
```bash
python scripts/seed_chart_of_accounts.py
```

### 6.2 社保配置（Wave 1，如已跑过可跳过）
```bash
python scripts/seed_si_config.py
```

### 6.3 **薪资项目库**（Wave 4 新增，必须）
```bash
python scripts/seed_salary_items.py
# 40 项分 7 大类：出勤/假期/绩效/提成/补贴/扣款/社保
```

### 6.4 验证种子
```sql
SELECT COUNT(*) FROM chart_of_accounts;        -- 预期 >= 26
SELECT COUNT(*) FROM social_insurance_configs; -- 预期 >= 4（4 城市）
SELECT COUNT(*) FROM salary_items;             -- 预期 >= 40
```

---

## Step 7: 重启服务

### 7.1 启动顺序
```bash
# 1. API Gateway 先启
systemctl start tunxiang-api
sleep 5
curl http://localhost:8000/health
# 预期 {"status": "ok"}

# 2. Celery Worker
systemctl start tunxiang-celery-worker

# 3. Celery Beat（定时任务）
systemctl start tunxiang-celery-beat

# 4. 验证 Beat 任务注册
celery -A src.core.celery_app.celery_app inspect scheduled
# 应看到：
#   scan-health-certs-daily     08:00 Asia/Shanghai
#   scan-labor-contracts-daily  08:10 Asia/Shanghai
```

### 7.2 烟测 LLM 网关
```bash
python scripts/smoke_test_llm_gateway.py
# 预期 [OK] provider=claude（若 Claude Key 存在）
# 或   [OK] provider=deepseek（若只有 DeepSeek Key）
```

---

## Step 8: 前端构建部署

```bash
cd apps/web
pnpm install   # 无新增依赖
pnpm build
# 部署 dist/ 到 Nginx
```

### 新增路由（需在前端菜单/权限确认可访问）
- `/hr/talent/nine-box` — 九宫格人才盘点
- `/hr/legal-entities` — 法人主体管理
- `/hr/e-signature/envelopes` — 电子签约信封列表
- `/hr/e-signature/sign/:id` — 员工签署页
- `/hr/okr` — OKR 看板
- `/hr/learning/map` — 学习地图
- `/hr/learning/leaderboard` — 积分排行
- `/hr/pulse` — 脉搏调研
- `/hr/assistant` — **🤖 HR 数字人助手**
- `/public/cert/verify/:certNo` — 证书公开验证（**无需登录**，Nginx 需放行 `/public/*`）

### Nginx 配置追加
```nginx
# 公开路径不走 auth（证书扫码验证）
location /public/ {
    proxy_pass http://api:8000/public/;
    proxy_set_header Host $host;
    # 不加 Authorization 验证
}
```

---

## Step 9: 回滚方案

> 如升级失败，15 分钟内可完全回滚

### 9.1 降级 Alembic
```bash
cd apps/api-gateway
alembic downgrade z67_merge_wave4
# 回到 Wave 4 结束位置（删除 Wave 5 的 20 张新表）
```

### 9.2 回滚代码
```bash
git checkout 0c2fb5bf  # Wave 4 commit
```

### 9.3 恢复数据库（如必要）
```bash
psql -U postgres zhilian_os < backup_pre_v3.2_YYYYMMDD_HHMMSS.sql
```

### 9.4 重启
```bash
systemctl restart tunxiang-api tunxiang-celery-worker tunxiang-celery-beat
```

---

## Step 10: 验证检查清单

```
□ Alembic current = z69_merge_wave5
□ /health 返回 ok
□ LLM 烟测通过
□ Celery Beat 显示 2 个定时任务
□ 首页 ManagementHub 人事合规板块看到 10+ 新瓦片
□ /hr/assistant 聊天页加载成功
□ /public/cert/verify/XXX 不要求登录
□ Nginx 日志无 403/500
□ 启动后 15 分钟内无 ERROR 级别日志
□ 创建一个测试储值卡充值订单 → vouchers 表出现新凭证
□ 创建一个测试 1-on-1 面谈并完成 → ai_summary 非空 JSON
```

---

## 常见问题

### Q1: 证书 PDF 中文显示方块？
**A**: Dockerfile 未安装 `fonts-noto-cjk`，见 Step 3。

### Q2: LLM 网关报 `LLMAllProvidersFailedError`？
**A**: 三家 API Key 都未配置或都不可达。至少配置 1 家（推荐 Claude+DeepSeek）。

### Q3: `alembic upgrade head` 报 Multiple heads？
**A**: 本次升级**不会**产生多 head（`z69_merge_wave5` 已合并 3 个 z68）。如报错，检查是否 pull 到完整 feature 分支：`git log --oneline | grep z69`。

### Q4: 数据库升级过慢？
**A**: 20 张新表建表+索引，小数据量（<100万员工）应在 30 秒内完成。超过 5 分钟检查 PG 连接+磁盘空间。

### Q5: 生产环境是否必须接 DeepSeek/OpenAI？
**A**: 建议接**至少 2 家**。Claude 单家宕机时（去年发生过 2 次），降级到 DeepSeek 可保业务不中断。

### Q6: 电子签约可以立即用吗？
**A**: **不可以**。当前实现是内部签名+审计链，不具法律效力。必须对接第三方 CA（法大大/e签宝）才能作为正式合同证据。

### Q7: 匿名调研真的匿名吗？
**A**: `is_anonymous=true` 时写 `sha256(employee_id|instance_id)` 哈希而非员工 ID。但**当前未加 salt**，严格匿名化要求需在 `pulse_survey_service.submit_response()` 加统一 salt（见 Release Notes §P0 清单）。

---

*如需升级协助，请联系：屯象科技（长沙）支持团队*
