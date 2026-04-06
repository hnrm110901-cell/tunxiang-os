# 屯象OS Feature Flag 运营手册

> 版本: 1.0 | 最后更新: 2026-04-06 | 维护人: 李淳（屯象OS创始人）
>
> Feature Flag 系统基于 Harness Feature Flags（FF）模块，Flag 定义文件存放于 `flags/` 目录。

---

## 一、基本概念

### Flag 类型

| 类型 | 说明 | 屯象OS用途 |
|------|------|-----------|
| Boolean Flag | 开/关 | 功能灰度发布、紧急开关 |
| String Flag | 多值字符串 | A/B测试不同文案、模型切换 |
| Number Flag | 数值 | 并发限制、Token上限动态调整 |
| JSON Flag | 复杂配置 | Agent 行为配置、UI 配置下发 |

### 目标受众（Targeting）

| 目标 | 说明 | 用法示例 |
|------|------|---------|
| 所有用户 | 全量开启 | 稳定功能上线 |
| 按 Tenant | 指定商户开启 | Pilot 试点商户 |
| 按 Environment | 仅在特定环境开启 | dev 环境测试新功能 |
| 按百分比 | 随机百分比用户 | 灰度 10%/50% |
| 按属性 | 如 plan=enterprise | 按套餐级别差异化 |

---

## 二、新增 Flag 标准流程

### 2.1 全流程概览

```
1. 定义 YAML（flags/ 目录）
        ↓
2. 代码集成（SDK 调用）
        ↓
3. 本地/Dev 环境测试
        ↓
4. 提交 PR → CI 验证 → 合并
        ↓
5. feature-flag-sync 流水线自动同步到 Harness
        ↓
6. Pilot 环境定向开启（指定试点 tenant）
        ↓
7. 观察监控指标（7-14天）
        ↓
8. 确认无异常 → 全量开启（Prod）
        ↓
9. 稳定运行 3 个月后 → Flag 固化清理
```

### 2.2 第一步：定义 Flag YAML

在 `flags/` 目录下创建 Flag 定义文件：

**文件命名规范**: `flags/<service>/<flag-name>.yaml`

```yaml
# 示例: flags/tx-trade/ff_smart_discount.yaml
name: ff_smart_discount
identifier: ff_smart_discount
description: "AI智能折扣推荐功能 - 根据客流量和库存自动建议折扣"
type: boolean
defaultValue: false
tags:
  service: tx-trade
  team: founder
  cost_center: core

# 各环境默认值
environmentOverrides:
  env_dev:
    defaultValue: true
  env_test:
    defaultValue: true
  env_uat:
    defaultValue: false   # UAT需要手动开启验收
  env_pilot:
    defaultValue: false   # Pilot定向开启
  env_prod:
    defaultValue: false   # 最后全量

# 目标规则（Pilot 阶段使用）
targeting:
  - name: pilot-tenants
    enabled: true
    targetGroups:
      - identifier: pilot_merchant_group
        included: true
    variation: true

# 生命周期
lifecycle:
  created_date: "2026-04-06"
  target_cleanup_date: ""  # 全量3个月后填写
  status: development      # development | pilot | rollout | stable | deprecated
```

### 2.3 第二步：代码集成

**Python 后端（FastAPI 服务）**:

```python
# services/tx-trade/src/feature_flags.py
from harness_ff_python_sdk import HarnessClient, Target

ff_client = HarnessClient(
    api_key=settings.HARNESS_FF_SDK_KEY,
    base_url=settings.HARNESS_FF_BASE_URL,
)

def is_smart_discount_enabled(tenant_id: str) -> bool:
    """检查 AI 智能折扣功能是否对指定 tenant 开启"""
    target = Target(
        identifier=tenant_id,
        name=tenant_id,
        attributes={"environment": settings.ENV_NAME}
    )
    return ff_client.bool_variation(
        identifier="ff_smart_discount",
        target=target,
        default=False  # 网络故障时降级为关闭
    )
```

**TypeScript 前端（Next.js / React）**:

```typescript
// apps/web-admin/src/hooks/useFeatureFlag.ts
import { useFeatureFlag } from '@harnessio/ff-react-client-sdk';

export function SmartDiscountBanner() {
  const smartDiscountEnabled = useFeatureFlag('ff_smart_discount', false);

  if (!smartDiscountEnabled) return null;
  return <Banner>智能折扣建议已启用</Banner>;
}
```

**兜底原则**:
- SDK 调用失败时必须返回 `defaultValue: false`（安全降级）
- 核心交易流程中的 Flag 必须有本地缓存，避免 Harness 不可用时影响交易

### 2.4 第三步：Dev 环境测试

```bash
# 临时在 dev 环境开启 Flag（通过 Harness CLI 或 UI）
harness feature-flag toggle \
  --flag ff_smart_discount \
  --environment env_dev \
  --enabled true

# 验证 API 响应中包含新功能
curl http://dev.tunxiang.com/api/v1/trade/discount-suggestions \
  -H "X-Tenant-ID: test_tenant_001"
```

测试 Checklist：
- [ ] 功能开启时，新逻辑正确执行
- [ ] 功能关闭时，降级到旧逻辑（不报错）
- [ ] SDK 超时/网络故障时，自动降级到 `defaultValue: false`
- [ ] 多 Tenant 场景下，Flag 状态互不干扰（多租户隔离验证）

### 2.5 第四步：提交 PR

```bash
git add flags/tx-trade/ff_smart_discount.yaml
git add services/tx-trade/src/feature_flags.py
git commit -m "feat(ff): add ff_smart_discount for AI discount suggestions"
git push origin feature/smart-discount
# 创建 PR → CI 自动触发
```

CI 会执行 `feature-flag-sync` 流水线，验证 Flag YAML 格式正确。

### 2.6 第五步：Pilot 定向开启

Flag 合并到 main 后，在 Harness FF 界面操作：

1. Feature Flags → `ff_smart_discount` → Targeting
2. 在 `env_pilot` 环境下添加 Target Group:
   - Group: `pilot_merchant_group`（预先定义的试点商户列表）
   - Variation: `true`（开启）
3. Save → 立即生效（无需重启服务）

观察指标（7-14天）：
- 折扣建议的接受率是否提升
- 有无导致交易异常的错误日志
- 性能指标（P99 响应时间）是否在正常范围

### 2.7 第六步：全量发布

Pilot 观察无异常后：

1. Harness FF → `ff_smart_discount` → `env_prod`
2. Default Variation 改为 `true`
3. Save → 全量生效
4. 同步更新 Flag YAML 中的 `status: stable` 和 `target_cleanup_date`

---

## 三、紧急关闭 Flag（快速回滚）

当线上发现问题功能需要立即关闭：

### 3.1 通过 Harness UI（最快）

1. 登录 Harness → Feature Flags → 找到目标 Flag
2. 将 `env_prod` 的 Default Variation 切换为 `false`
3. **点击 Save** → 30秒内全量生效（无需部署）

### 3.2 通过 Harness CLI（命令行）

```bash
# 安装好 Harness CLI 后执行
harness feature-flag toggle \
  --flag ff_smart_discount \
  --environment env_prod \
  --enabled false \
  --account-id <account-id> \
  --api-key <api-key>

# 确认关闭成功
harness feature-flag get \
  --flag ff_smart_discount \
  --environment env_prod
```

### 3.3 通过 API（集成到告警自动化）

```bash
# Harness FF REST API 紧急关闭
curl -X PATCH \
  "https://app.harness.io/cf/admin/features/ff_smart_discount/environments/env_prod" \
  -H "x-api-key: ${HARNESS_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"state": "off"}'
```

### 3.4 紧急关闭后续动作

- [ ] 在企微通知团队（或自己）：哪个 Flag 被关闭、原因
- [ ] 记录关闭时间和原因到 DEVLOG.md
- [ ] 排查根因，修复后重新走 Pilot → 全量流程
- [ ] 如果是 RLS 或安全相关 Flag，额外触发安全审查

---

## 四、Flag 清理规范

### 4.1 清理时机

| 状态 | 说明 | 行动 |
|------|------|------|
| `development` | 功能开发中，仅 dev 开启 | 保留，等待 Pilot |
| `pilot` | Pilot 验证中 | 保留，观察指标 |
| `rollout` | 全量灰度中 | 保留，完成全量后转 stable |
| `stable` | 全量生效超过 3 个月 | **触发清理流程** |
| `deprecated` | 标记废弃，等待代码删除 | 下个迭代删除代码 |

### 4.2 清理流程（stable 满 3 个月后）

```
1. 将 status 改为 deprecated
   ↓
2. 提 Ticket 或 PR，在代码中删除 Flag 判断，直接走开启分支
   ↓
3. 代码删除合并后，跑完整测试（CI 全绿）
   ↓
4. 从 flags/ 目录删除对应 YAML 文件
   ↓
5. feature-flag-sync 流水线执行 → Harness FF 中归档此 Flag
```

### 4.3 代码清理示例

**清理前**:
```python
if is_smart_discount_enabled(tenant_id):
    return smart_discount_logic(order)
else:
    return legacy_discount_logic(order)
```

**清理后**（直接走开启逻辑，删除 Flag 调用）:
```python
# ff_smart_discount stable since 2026-07-01，已于 2026-10-01 固化
return smart_discount_logic(order)
```

---

## 五、屯象OS 已有 Flag 运营状态表

> 最后更新: 2026-04-06

| Flag 名称 | 服务 | 类型 | 当前状态 | Dev | Test | UAT | Pilot | Prod | 创建日期 | 预计固化日期 | 说明 |
|---------|------|------|---------|-----|------|-----|-------|------|---------|------------|------|
| `ff_agent_dish_recommend` | tx-brain | Boolean | pilot | ON | ON | ON | 定向 | OFF | 2026-03-01 | 2026-07-01 | AI菜品推荐 Agent |
| `ff_smart_inventory_alert` | tx-trade | Boolean | rollout | ON | ON | ON | ON | 20% | 2026-02-15 | 2026-06-15 | 智能库存预警 |
| `ff_new_kds_ui` | kds | Boolean | pilot | ON | ON | OFF | 定向 | OFF | 2026-03-20 | 待定 | 新版KDS界面 |
| `ff_multi_model_routing` | tx-brain | String | development | ON | OFF | OFF | OFF | OFF | 2026-04-01 | 待定 | 多模型路由（DeepSeek/Claude切换） |
| `ff_pos_offline_mode` | pos-server | Boolean | stable | ON | ON | ON | ON | ON | 2025-12-01 | 2026-03-01（已逾期） | POS 离线模式，**待清理** |
| `ff_split_billing` | tx-trade | Boolean | development | ON | OFF | OFF | OFF | OFF | 2026-04-05 | 待定 | 分单结账功能 |
| `ff_enterprise_report_v2` | report | Boolean | pilot | ON | ON | ON | 定向 | OFF | 2026-03-10 | 2026-07-10 | 企业版报表 V2 |
| `ff_rls_policy_v2` | all | Boolean | stable | ON | ON | ON | ON | ON | 2025-11-01 | **待清理** | v063 RLS 修复后的新策略，已全量 |

### 待处理事项

- **高优先级**: `ff_pos_offline_mode` 和 `ff_rls_policy_v2` 均已达到清理条件，需在下个迭代清理代码并归档 Flag
- **关注**: `ff_smart_inventory_alert` 生产已灰度 20%，如两周内无异常，推进到 100%
- **新建**: `ff_split_billing` 刚创建，需完成代码集成和 Dev 测试

---

## 六、Flag 命名规范

```
ff_<功能域>_<功能名>

示例:
  ff_agent_dish_recommend    # Agent 领域 - 菜品推荐
  ff_pos_offline_mode        # POS 领域 - 离线模式
  ff_trade_split_billing     # 交易领域 - 分单结账
  ff_report_enterprise_v2    # 报表领域 - 企业版V2
```

**规则**:
- 全小写，下划线分隔
- 必须以 `ff_` 开头（Feature Flag 前缀）
- 不超过 50 个字符
- 有明确语义，避免 `ff_new_feature_1` 这类无意义命名

---

*本手册由屯象OS开发团队维护 | 如有疑问联系李淳（创始人）*
