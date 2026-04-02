# 数据库迁移链完整性报告

> 生成日期：2026-04-02
> 检查范围：`shared/db-migrations/versions/` 目录下全部 `.py` 迁移文件

---

## 概要

| 项目 | 数值 |
|------|------|
| 迁移文件总数 | 130 |
| 最早版本 | v001 |
| 最新版本 | v125 |
| 重复 revision | **4 组**（见下方详情）|
| 断链节点 | **1 处**（v056 跨越 v048-v055）|
| 跳号段 | v041、v044（无对应文件）|

---

## 发现的问题

### 问题一：重复 revision（4 组，CRITICAL）

以下版本号存在两个同名文件，Alembic 在运行时只会识别其中一个，另一个将被忽略，存在迁移冲突风险：

| Revision ID | 文件1 | 文件2 |
|-------------|-------|-------|
| `v022` | `v022_customer_wecom_fields.py` | `v022_stored_value_v2_fields.py` |
| `v100` | `v100_profit_split_engine.py` | `v100_xiaohongshu_integration.py` |
| `v101` | `v101_budget_management.py` | `v101_group_buy.py` |
| `v102` | `v102_enterprise_vat.py` | `v102_stamp_card.py` |
| `v103` | `v103_gdpr_compliance.py` | `v103_retail_mall.py` |

**说明**：上述每对文件在文件头部注释中均声明了相同的 `Revision ID`，Alembic 迁移图将出现多头节点，`alembic upgrade head` 时行为不确定。

### 问题二：断链节点（v056 跳过了 v048-v055 的多个版本）

```
v047  →  v056  (down_revision = v047)
```

文件 `v056_fix_rls_vulnerabilities.py` 声明 `Revises: v047`，但该文件之前还存在以下文件（均在 v047 之后，v056 之前）：

| 文件 | 实际 Revision |
|------|--------------|
| `v048_discount_audit_log.py` | v048 |
| `v049_service_bell.py` | v049 |
| `v050_course_firing.py` | v050 |
| `v051_seat_ordering.py` | v051 |
| `v052_allergen_management.py` | v052 |
| `v053_supply_chain_mobile.py` | v053 |
| `v054_business_diagnosis.py` | v054 |
| `v055_patrol_logs.py` | v055 |

其中 `v056b_multichannel_publish.py` 声明 `Revises: v055`（正确），但 `v056_fix_rls_vulnerabilities.py` 跳回 `v047`，导致链路出现分叉：

```
v047 → v048 → v049 → v050 → v051 → v052 → v053 → v054 → v055 → v056b
  └→ v056 (正确应为 down_revision=v055，目前指向 v047)
```

**实际影响**：`v056` 的 `down_revision = v047` 使得 Alembic 认为 v056 是从 v047 分叉的独立分支，与 v048-v055 形成多头（multiple heads）。`alembic upgrade head` 会报错 `Multiple head revisions are present`，需要指定 `--branch-label` 或 merge。

### 问题三：跳号（v041、v044 文件不存在）

以下版本号在 v040-v045 序列中缺失对应文件：

| 跳过的版本号 | 前驱 | 后继 |
|------------|------|------|
| `v041` | v040 (settlement_engine) | v042 (cross_brand_member, down_revision=v040) |
| `v044` | v043 (banquet_deposit, down_revision=v042) | v045 (collab_order, down_revision=v043) |

**说明**：v042 的 down_revision 指向 v040（跳过 v041），v045 的 down_revision 指向 v043（跳过 v044）。这说明 v041 和 v044 从未被创建，而不是被删除。对链路完整性没有直接影响（链路是连通的），但版本号不连续。

---

## 正常链路段

以下版本段经验证 down_revision 链连通：

| 段 | 说明 |
|----|------|
| v001 → v002 → ... → v040 | 正常，无断链（v041 跳过）|
| v040 → v042 → v043 → v045 → v046 → v047 | 跳 v041/v044，但链路连通 |
| v047 → v048 → v049 → ... → v055 → v056b | 正常 |
| v056b → v057 → ... → v099 → v100（一个）→ v101（一个）→ v102（一个）→ v103（一个）→ v104 → v105 → ... → v125 | 重复 revision 段，后续取决于 Alembic 如何解析 |

---

## 修复建议（供其他团队处理，本报告不做修复）

| 问题 | 建议修复方式 |
|------|-------------|
| 重复 revision v022 | 将 `v022_stored_value_v2_fields.py` 的 revision 改为 `v022b`，down_revision 指向 `v022` |
| 重复 revision v100/v101/v102/v103 | 每对中选一个改为 `vXXXb`，串联到另一个之后（如 `v100b` 的 down_revision = `v100`）|
| v056 断链 | 将 `v056_fix_rls_vulnerabilities.py` 的 `down_revision` 从 `v047` 改为 `v055`（或 `v056b` 改为 `v056`）|
| 跳号 v041/v044 | 可不处理（不影响链路），或补充空迁移文件作为占位符 |

---

## 完整文件清单（130个）

```
v001  v002  v003  v004  v005  v006  v007  v008  v009  v010
v011  v012  v013  v014  v015  v016  v017  v018  v019  v020
v021  v022(×2)  v023  v024  v025  v026  v027  v028  v029  v030
v031  v032  v033  v034  v035  v036  v037  v038  v039  v040
[v041缺失]  v042  v043  [v044缺失]  v045  v046  v047  v048  v049  v050
v051  v052  v053  v054  v055  v056  v056b  v057  v058  v059
v060  v061  v062  v063  v064  v065  v066  v067  v068  v069
v070  v071  v072  v073  v074  v075  v076  v077  v078  v079
v080  v081  v082  v083  v084  v085  v086  v087  v088  v089
v090  v091  v092  v093  v094  v095  v096  v097  v098  v099
v100(×2)  v101(×2)  v102(×2)  v103(×2)  v104  v105  v106  v107  v108  v109
v110  v111  v112  v113  v114  v115  v116  v117  v118  v119
v120  v121  v122  v123  v124  v125
```
