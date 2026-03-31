# 屯象OS 凭证泄露清理报告

> 审计日期：2026-03-31
> 审计范围：全仓库 .env 文件扫描、.gitignore 检查、pre-commit 配置验证

---

## 1. 审计结论摘要

| 项目 | 状态 |
|------|------|
| 现存 .env 文件扫描 | 已完成 |
| .gitignore 覆盖检查 | 已完备，无需修改 |
| pre-commit 钩子 | 已存在，含 detect-secrets |
| 历史提交中的凭证 | **需手动执行 git filter-repo 清理** |

---

## 2. 发现的文件与处理结果

### 2.1 当前工作区 .env 文件

| 文件路径 | 状态 | 处理动作 |
|----------|------|----------|
| `.env.staging` | 含真实服务器 IP (`STG_HOST`) | **已替换**为 `REPLACE_ME_STG_HOST`，顶部加安全警告注释 |
| `.env.staging.example` | 含相同真实 IP | **已替换**为 `REPLACE_ME_STG_HOST` |
| `.env.gray.example` | 密码为占位符，无真实值 | 无需修改 |

**结论：** 当前工作区无残留真实 API KEY / TOKEN / PASSWORD，仅清理了一个真实 IP 地址。

### 2.2 已移除的历史泄露文件

以下文件在之前的代码审计（2026-03-27）中已从工作区删除，但**仍存在于 git 历史中**：

| 历史文件路径 | 含泄露的凭证类型 |
|--------------|----------------|
| `config/merchants/.env.czyz` | 品智 API TOKEN、奥琦玮 APP_KEY / APP_ID / MERCHANT_ID |
| `config/merchants/.env.zqx` | 品智 API TOKEN、奥琦玮 APP_KEY / APP_ID / MERCHANT_ID |
| `config/merchants/.env.sgc` | 品智 API TOKEN、奥琦玮 APP_KEY / APP_ID / MERCHANT_ID、优惠券 APP_KEY / APP_ID |
| `scripts/probe_pinzhi_v2.py`（旧版） | PINZHI_PROBE_TOKEN（已改为环境变量，旧值仍在历史中） |

---

## 3. 需要轮换的密钥类型

以下密钥**曾以明文存在于 git 历史**，必须在对应平台重新生成（不管是否有外部人员访问过仓库）：

### 尝在一起（czyz）
- 品智 POS API 认证令牌（`CZYZ_PINZHI_API_TOKEN`）
- 奥琦玮应用密钥（`CZYZ_AOQIWEI_APP_KEY`）
- 奥琦玮应用 ID（`CZYZ_AOQIWEI_APP_ID`）

### 最黔线（zqx）
- 品智 POS API 认证令牌（`ZQX_PINZHI_API_TOKEN`）
- 奥琦玮应用密钥（`ZQX_AOQIWEI_APP_KEY`）
- 奥琦玮应用 ID（`ZQX_AOQIWEI_APP_ID`）

### 尚宫厨（sgc）
- 品智 POS API 认证令牌（`SGC_PINZHI_API_TOKEN`）
- 奥琦玮应用密钥（`SGC_AOQIWEI_APP_KEY`）
- 奥琦玮应用 ID（`SGC_AOQIWEI_APP_ID`）
- 优惠券网关应用密钥（`SGC_COUPON_APP_KEY`）
- 优惠券网关应用 ID（`SGC_COUPON_APP_ID`）

### 探测脚本
- 品智 API 探测 TOKEN（`PINZHI_PROBE_TOKEN` — 旧硬编码值）

---

## 4. 用户需手动执行的操作

> **重要警告：** 以下命令会永久重写 git 历史，属于破坏性操作。
> 执行前请确认：
> 1. 所有协作者已推送本地变更
> 2. 已在本地备份完整仓库（`cp -r tunxiang-os tunxiang-os-backup`）
> 3. 如果仓库已推送到远程，需通知所有协作者重新 clone

### Step 1：安装 git-filter-repo

```bash
brew install git-filter-repo
```

### Step 2：查看泄露文件的提交历史（仅查看，不破坏）

```bash
git -C /Users/lichun/tunxiang-os log --all --oneline --diff-filter=A -- \
  "config/merchants/.env.czyz" \
  "config/merchants/.env.zqx" \
  "config/merchants/.env.sgc"
```

### Step 3：从 git 历史中彻底删除泄露文件

```bash
cd /Users/lichun/tunxiang-os

# 删除三个商户 .env 文件的所有历史记录
git filter-repo --path config/merchants/.env.czyz --invert-paths --force
git filter-repo --path config/merchants/.env.zqx --invert-paths --force
git filter-repo --path config/merchants/.env.sgc --invert-paths --force
```

### Step 4：清理 probe 脚本中的硬编码 TOKEN（可选，更彻底）

```bash
# 用正则替换历史中所有32位十六进制字符串（TOKEN格式）
git filter-repo --blob-callback '
import re
blob.data = re.sub(rb"[a-f0-9]{32}", b"REDACTED_CREDENTIAL", blob.data)
' --force
```

### Step 5：验证历史已清理

```bash
# 确认文件不再出现在任何历史提交中
git log --all --oneline -- config/merchants/.env.czyz
git log --all --oneline -- config/merchants/.env.zqx
git log --all --oneline -- config/merchants/.env.sgc
# 以上命令应无任何输出
```

### Step 6：强制推送到远程（如果有远程仓库）

```bash
git push origin --force --all
git push origin --force --tags
```

### Step 7：通知协作者重新 clone

```bash
# 所有协作者执行：
rm -rf tunxiang-os
git clone <仓库地址>
```

---

## 5. 当前安全防护状态

### 已就位的防护
- `.gitignore` 已完整覆盖所有 `.env*` 变体（`.env`, `.env.*`, `.env.local`, `.env.*.local`），同时豁免 `.env.example` 和 `.env.*.example`
- `config/merchants/` 目录已加入 `.gitignore`，新凭证无法被意外提交
- `.pre-commit-config.yaml` 已配置 `detect-secrets`（v1.4.0）+ `detect-private-key` 双重扫描
- `scripts/setup-git-secrets.sh` 已准备好 git-secrets 配置（针对品智/奥琦玮 token 格式）

### 仍需完成的工作
- [ ] 在品智、奥琦玮、优惠券平台重新生成上述所有 API KEY/TOKEN
- [ ] 将新凭证存入腾讯云 SSM 或服务器环境变量
- [ ] 执行本文档 Step 2-7 清理 git 历史
- [ ] 执行 `scripts/setup-git-secrets.sh` 激活 git-secrets 钩子
- [ ] 执行 `pre-commit install` 激活 detect-secrets 钩子

---

*本报告由屯象OS安全审计流程生成于 2026-03-31。*
