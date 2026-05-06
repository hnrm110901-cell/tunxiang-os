# S-01 — 品智 17 个 Token 轮换 + git 历史清理 Runbook

**对应审计项**：[S-01 — 凭证泄漏（P0）](../audit-2026-05/01-security.md#s-01)（无审计目录则参 [credential-cleanup-guide.md](../credential-cleanup-guide.md)）
**估时**：1.5 个工作日（含品智协调 + 灰度验证）
**执行方**：DevOps + 品智客服 + 屯象后台运维
**风险**：高 — 错误执行将导致 14 个生产门店收银/同步全线掉线

---

## 一、需轮换的 17 个 token 全清单

凭证全部曾以明文存在 git 历史（见 §三 git filter-repo 步骤），**无论是否被外部访问，均必须轮换**。

| # | 品牌 | 门店 ID | 门店名 | env 变量 | 品智后台 base_url |
|---|------|---------|--------|----------|-----------|
| 1 | 尝在一起 | — | API 主令牌 | `CZYZ_PINZHI_API_TOKEN` | http://czyq.pinzhikeji.net:8899 |
| 2 | 尝在一起 | 2461 | 文化城店 | `CZYZ_PINZHI_STORE_2461_TOKEN` | 同上 |
| 3 | 尝在一起 | 7269 | 浏小鲜 | `CZYZ_PINZHI_STORE_7269_TOKEN` | 同上 |
| 4 | 尝在一起 | 19189 | 永安店 | `CZYZ_PINZHI_STORE_19189_TOKEN` | 同上 |
| 5 | 最黔线 | — | API 主令牌 | `ZQX_PINZHI_API_TOKEN` | http://ljcg.pinzhikeji.net:8899 |
| 6 | 最黔线 | 20529 | 门店1 | `ZQX_PINZHI_STORE_20529_TOKEN` | 同上 |
| 7 | 最黔线 | 32109 | 门店2 | `ZQX_PINZHI_STORE_32109_TOKEN` | 同上 |
| 8 | 最黔线 | 32304 | 门店3 | `ZQX_PINZHI_STORE_32304_TOKEN` | 同上 |
| 9 | 最黔线 | 32305 | 门店4 | `ZQX_PINZHI_STORE_32305_TOKEN` | 同上 |
| 10 | 最黔线 | 32306 | 门店5 | `ZQX_PINZHI_STORE_32306_TOKEN` | 同上 |
| 11 | 最黔线 | 32309 | 门店6 | `ZQX_PINZHI_STORE_32309_TOKEN` | 同上 |
| 12 | 尚宫厨 | — | API 主令牌 | `SGC_PINZHI_API_TOKEN` | http://xcsgc.pinzhikeji.net:8899 |
| 13 | 尚宫厨 | 2463 | 门店1 | `SGC_PINZHI_STORE_2463_TOKEN` | 同上 |
| 14 | 尚宫厨 | 7896 | 门店2 | `SGC_PINZHI_STORE_7896_TOKEN` | 同上 |
| 15 | 尚宫厨 | 24777 | 门店3 | `SGC_PINZHI_STORE_24777_TOKEN` | 同上 |
| 16 | 尚宫厨 | 36199 | 门店4 | `SGC_PINZHI_STORE_36199_TOKEN` | 同上 |
| 17 | 尚宫厨 | 41405 | 门店5 | `SGC_PINZHI_STORE_41405_TOKEN` | 同上 |

> 凭证源：`shared/adapters/pinzhi/src/merchants.py`（11–41 行）+ `.env.example`（140–165 行）。
> 单店 token 等于品智后台为该门店签发的"API 接入令牌"；API 主令牌用于跨店 admin 接口。

**额外**：探测脚本 `PINZHI_PROBE_TOKEN`（旧硬编码值仍在 git 历史；轮换不必走品智后台，
本地生成新 32-byte hex 即可，但 git filter-repo 必须连同清理）。

---

## 二、轮换执行流程（按先后顺序）

### Phase 0 — 前置准备（D-1 工作日）

1. **联系品智客服开 case**
   - 微信群 / 商家后台工单 → 主题"屯象OS 全店 token 轮换 (17 个)"
   - 提供商户 ID 列表：czyq / ljcg / xcsgc
   - 约定计划生效时间窗口（建议午夜 02:00-03:00 — 营业低谷）
   - 确认品智侧"老 token 灰度过期"是否支持 24h 双 token 期（必须，避免 cutover 期断流）

2. **腾讯云 SSM secret 准备空位**
   - 17 个新 secret path：`tunxiang/merchant/{brand}/PINZHI_*_TOKEN`
   - 灰度期老 secret 暂留，新增 `_v2` 后缀（如 `PINZHI_API_TOKEN_v2`）

3. **本地环境打印当前 secret hash 备查**
   ```bash
   for env in CZYZ_PINZHI_API_TOKEN ZQX_PINZHI_API_TOKEN SGC_PINZHI_API_TOKEN; do
     echo -n "${env}=" ; echo -n "${!env}" | shasum -a 256 | head -c 16 ; echo
   done > /tmp/old_token_hashes.txt
   ```

### Phase 1 — 品智后台签发新 17 个 token（D 日 02:00）

4. 品智客服或商家后台 admin 逐个生成新 token（按 §一 表顺序）
5. 客服将新 token 通过加密 IM（企业微信 + 阅后即焚）逐条发出，**禁止口头/明文邮件**
6. 接收方（DevOps）立即写入腾讯云 SSM `_v2` 后缀 secret

### Phase 2 — 双 token 灰度（D 日 02:30 - 03:00）

7. 修改 `shared/adapters/pinzhi/src/auth.py` 加 fallback（仅本次轮换期临时）：
   ```python
   token = os.environ.get(f"{prefix}_TOKEN_v2") or os.environ.get(f"{prefix}_TOKEN", "")
   ```
8. 生产 pod 注入 `_v2` env，热更新（kubectl rollout restart deployment/tx-trade）
9. 灰度 5% 流量到新 token：观察 `pinzhi_api_5xx_total`（无突增 = OK）

### Phase 3 — 全量切（D 日 03:00 - 03:30）

10. 全量 pod 切到 `_v2` token，老 secret 仍保留 24h 兜底
11. 启动 `scripts/security/verify_pinzhi_token_rotation.sh`（见 §五）跑 17 个店端到端验证
12. 24h 观察 `tx-trade.pinzhi_*` Prometheus metric，无 401/403 红线

### Phase 4 — 清旧 + 通知品智过期（D+1 日）

13. 删除 `_v2` 后缀代码 fallback，env 重命名为正式名
14. 通知品智客服立即过期老 17 个 token（确认品智后台已 revoke）
15. 删除腾讯云 SSM 老 secret（保留备份至 D+7）

---

## 三、git 历史清理（与 token 轮换并行，不阻塞营业）

> ⚠️ 破坏性操作。所有协作者必须先 push 本地未提交变更。
> 已存在 [credential-cleanup-guide.md §4](../credential-cleanup-guide.md) Step 1-7 详细命令；
> 本节追加 17 token 专用清理 + 校验。

### Step A — 备份 + 安装

```bash
# 镜像备份（破坏性操作前防意外）
git -C /Users/lichun/tunxiang-os bundle create /tmp/tunxiang-os-pre-filter.bundle --all

# 安装 git-filter-repo（macOS）
brew install git-filter-repo
```

### Step B — 删除 4 个泄漏文件的所有历史

```bash
cd /Users/lichun/tunxiang-os
git filter-repo --invert-paths \
  --path config/merchants/.env.czyz \
  --path config/merchants/.env.zqx \
  --path config/merchants/.env.sgc \
  --path scripts/probe_pinzhi_v2.py \
  --force
```

### Step C — 正则擦除任何残留 token 字面值

```bash
# 品智 token 格式：32 位十六进制（小写）— 用 .git-replace 做 blob 替换
git filter-repo --replace-text <(cat <<'EOF'
regex:[a-f0-9]{32}==>REDACTED_PINZHI_TOKEN
EOF
) --force
```

### Step D — 验证清理（无输出 = 已彻底清理）

```bash
# 1. 历史中不应再出现 4 个文件
for f in config/merchants/.env.czyz config/merchants/.env.zqx \
         config/merchants/.env.sgc scripts/probe_pinzhi_v2.py; do
  echo "=== $f ===" ; git log --all --oneline -- "$f"
done

# 2. 全历史 grep 不应有 32 位 hex token
git grep -E '^[a-f0-9]{32}$' $(git rev-list --all) 2>/dev/null | head
# 期望：空输出
```

### Step E — 强推 + 协作者重新 clone

```bash
git push origin --force --all
git push origin --force --tags
# Slack/微信群通知所有协作者：
#   rm -rf tunxiang-os && git clone <repo>
```

---

## 四、回滚预案

| 阶段 | 失败现象 | 回滚动作 |
|------|----------|----------|
| Phase 1 | 品智签发失败 / 个别 token 不可用 | 跳过该店此次轮换，单独 case 跟进；其他 16 token 继续 |
| Phase 2 | 灰度 5% 触发 401/403 突增 | `kubectl rollout undo deployment/tx-trade` 撤回 `_v2` env，回老 token |
| Phase 3 | 全量切后 24h 内出现 401/403 | 同上 + 通知品智 revoke 新 token / 重新签发 |
| Phase 3 | git filter-repo 失败 | 用 Step A bundle 恢复：`git bundle unbundle /tmp/tunxiang-os-pre-filter.bundle` |
| Phase 4 | 老 token 已过期但代码未升级到 _v2 | 紧急 patch 删 fallback 代码 → 重新 deploy（不能撤老 token revoke） |

---

## 五、验证脚本

### 5.1 17 token e2e 探测

文件：`scripts/security/verify_pinzhi_token_rotation.sh`（与本 PR 一同新增）

```bash
bash scripts/security/verify_pinzhi_token_rotation.sh
# 期望：17/17 OK，0 fail
```

### 5.2 SSM secret 存在性

```bash
for var in CZYZ_PINZHI_API_TOKEN \
           CZYZ_PINZHI_STORE_2461_TOKEN CZYZ_PINZHI_STORE_7269_TOKEN CZYZ_PINZHI_STORE_19189_TOKEN \
           ZQX_PINZHI_API_TOKEN \
           ZQX_PINZHI_STORE_20529_TOKEN ZQX_PINZHI_STORE_32109_TOKEN ZQX_PINZHI_STORE_32304_TOKEN \
           ZQX_PINZHI_STORE_32305_TOKEN ZQX_PINZHI_STORE_32306_TOKEN ZQX_PINZHI_STORE_32309_TOKEN \
           SGC_PINZHI_API_TOKEN \
           SGC_PINZHI_STORE_2463_TOKEN SGC_PINZHI_STORE_7896_TOKEN SGC_PINZHI_STORE_24777_TOKEN \
           SGC_PINZHI_STORE_36199_TOKEN SGC_PINZHI_STORE_41405_TOKEN; do
  tccli ssm GetSecretValue --SecretName "tunxiang/merchant/${var}" >/dev/null 2>&1 \
    && echo "✓ $var" || echo "✗ MISSING $var"
done
```

### 5.3 git 历史 grep（filter-repo 后）

```bash
git grep -nE 'pinzhi.*[a-f0-9]{32}' $(git rev-list --all) 2>/dev/null | wc -l
# 期望：0
```

---

## 六、验收标准

全部 ✅ 才算 S-01 闭环：

- [ ] 17 个 SSM secret 存在 + value 与品智后台签发一致
- [ ] `scripts/security/verify_pinzhi_token_rotation.sh` 17/17 OK
- [ ] git filter-repo 后 4 个泄漏文件 + 32-hex 字面值全部清除
- [ ] 全员重新 clone（Slack 接龙签到）
- [ ] 老 17 token 已被品智后台 revoke（客服回执邮件存档）
- [ ] 24h prod 监控 `pinzhi_api_5xx_total` 无突增
- [ ] 腾讯云 SSM `_v2` 后缀 secret 已正名 + 老 secret 已删

---

## 七、相关文档

- [credential-cleanup-guide.md](../credential-cleanup-guide.md) — 总体凭证清理（包含奥琦玮 / 优惠券 token，本 runbook 仅覆盖品智 17 个）
- [credential-migration-guide.md](../credential-migration-guide.md) — 腾讯云 SSM 接入指南
- [shared/adapters/pinzhi/src/merchants.py](../../shared/adapters/pinzhi/src/merchants.py) — 17 个 token env 名权威源
- [.env.example](../../.env.example) — env 变量完整列表（含其他品牌的非品智 token）
