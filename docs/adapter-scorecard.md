# 屯象OS 适配器评分卡（Sprint F / F1）

> 14 个目录形适配器的 7 维评分快照。门禁线 22/35 才能上生产。
> 数据由 `scripts/score_adapters.py` 自动生成；本文件与脚本输出同步。
> 重新生成：`python3 scripts/score_adapters.py --markdown docs/adapter-scorecard.md`
> （请保留下方人工解读段落，仅刷新表格）

---

## 一、评分维度

每维 0-5，总 35。

| # | 维度 | 评估方法 | 自动 / 半自动 |
|---|---|---|---|
| 1 | 契约完整度 (contract) | 是否有 `adapter.py` / 继承 BaseAdapter / Protocol / src 文件数 | 半自动 |
| 2 | 错误处理 (error_handling) | broad except 数量（扣分）+ retry/timeout/error_code 引用 | 半自动 |
| 3 | 测试覆盖 (testing) | `tests/test_*.py` 数量 / `src/*.py` 数量 | 全自动 |
| 4 | RLS / 租户 (rls) | `tenant_id` 出现密度（hits / src_files） | 全自动 |
| 5 | 幂等性 (idempotency) | `idempotency / unique_key / dedup / nonce / on_conflict` 命中 | 全自动 |
| 6 | 事件发射 (events) | `emit_event / event_types / EventType` 命中 | 全自动 |
| 7 | 文档 (docs) | README 行数 + 字段映射段 + corner case 段 | 全自动 |

---

## 二、当前快照（生成时间：2026-04-25）

| Adapter | Contract | Errors | Tests | RLS | Idempot | Events | Docs | Total | Pass(>=22) |
|---|---|---|---|---|---|---|---|---|---|
| aoqiwei | 2 | 5 | 5 | 5 | 0 | 0 | 3 | **20** | FAIL |
| base | 5 | 3 | 2 | 2 | 0 | 5 | 0 | **17** | FAIL |
| douyin | 2 | 5 | 0 | 3 | 0 | 0 | 0 | **10** | FAIL |
| eleme | 2 | 4 | 0 | 0 | 0 | 0 | 0 | **6** | FAIL |
| erp | 3 | 4 | 0 | 1 | 4 | 0 | 0 | **12** | FAIL |
| keruyun | 1 | 5 | 3 | 0 | 0 | 0 | 0 | **9** | FAIL |
| logistics | 0 | 2 | 0 | 0 | 0 | 0 | 0 | **2** | FAIL |
| meituan-saas | 2 | 4 | 3 | 3 | 0 | 0 | 4 | **16** | FAIL |
| nuonuo | 2 | 2 | 0 | 0 | 4 | 0 | 0 | **8** | FAIL |
| pinzhi | 3 | 3 | 3 | 3 | 0 | 0 | 4 | **16** | FAIL |
| tiancai-shanglong | 2 | 3 | 2 | 5 | 0 | 0 | 4 | **16** | FAIL |
| weishenghuo | 1 | 5 | 3 | 0 | 0 | 0 | 1 | **10** | FAIL |
| xiaohongshu | 1 | 3 | 0 | 5 | 1 | 0 | 0 | **10** | FAIL |
| yiding | 3 | 3 | 1 | 0 | 0 | 0 | 2 | **9** | FAIL |

**汇总：0 / 14 达标。** 全员未过线，事件发射（Phase 1 接入）+ 幂等性是普遍洼地。

> sprint plan 中 "14 适配器" 与目录数完全对齐。`base` 是契约层（不是业务适配器）但也按同口径打分，便于一致比较。

---

## 三、单适配器简评（≤200 字）

### aoqiwei（奥琦韦微生活）—— 20/35（最接近门槛）
契约/错误处理/RLS/测试都到位（4 测试文件、20 处 tenant_id、零 broad except），文档 243 行。
**缺口：** events=0 / idempotency=0。补 emit_event 接入 + idempotency_key 即可破 22。
**必补：** 1）会员储值/扣减 emit MEMBER.RECHARGED/CONSUMED；2）写入路径加 nonce dedup。

### base（契约基类）—— 17/35
事件发射 5 满分（提供 `AdapterEventMixin`）、契约 5 满分。**缺口：** 文档（无 README）+ idempotency 接口未在基类约束。**必补：** README + 在 BaseAdapter 上增加 `idempotency_key` 抽象方法。

### douyin（抖音）—— 10/35
**缺口：** 无 tests、无 README、无 events、无 idempotency。
**必补：** 1）补 README（字段映射）；2）至少 3 个 test 用例（订单同步/退款/异常路径）；3）emit CHANNEL.ORDER_SYNCED；4）补 tenant_id 隔离。

### eleme（饿了么）—— 6/35（最低之一）
**缺口：** 几乎全维度都缺（无 tests、无 README、tenant_id=0、无 events）。
**必补：** 重写测试套件、补 README、租户隔离全链路 review、events 接入。属于 Sprint F 后置项。

### erp（通用 ERP）—— 12/35
幂等性 4 分（少见亮点：有 unique_key/on_conflict）；**缺口：** 无 tests、无 README、无 events、tenant_id 仅 1 处。
**必补：** README + 测试 + RLS 全链路 + events。

### keruyun（客如云）—— 9/35
**缺口：** 几乎所有客观维度都缺（无 tenant_id / 无 events / 无 README / 无 idempotency）。仅 1 个测试文件勉强支撑。
**必补：** 全维度补强；属低优先级，等客户实际签约再投入。

### logistics（物流）—— 2/35（垫底）
src 仅 2 文件 180 行。**缺口：** 几乎一切。属于桩代码。
**必补：** 待具体业务接入再补——目前不应作为生产路径。

### meituan-saas（美团 SAAS）—— 16/35
README 379 行、3 测试文件、tenant_id 9 处。
**缺口：** events / idempotency / 错误处理还有 broad except。
**必补：** 1）emit CHANNEL.ORDER_SYNCED；2）订单写入加 idempotency_key（防回调重投）；3）替换 broad except。

### nuonuo（诺诺发票）—— 8/35
broad except 5 处（错误处理仅 2 分）；**缺口：** 几乎全维度都低。
**必补：** §17 Tier 1 全电发票路径必经，**演示前必须修**。重写错误处理 + 加 RLS + 加 idempotency。

### pinzhi（品智 POS）—— 16/35（czyz 必经）
12 src 文件、5 测试文件、318 行 README，tenant_id 34 处密度最好。
**缺口：** events / idempotency / broad except 3 处。
**必补：** 1）emit ORDER.PAID / DISCOUNT.APPLIED；2）订单同步加幂等；3）替换 broad except。**czyz playbook 阻塞项。**

### tiancai-shanglong（天财商龙）—— 16/35
RLS 满分 5（28 处 tenant_id）、README 302 行、4 测试文件。
**缺口：** broad except 7 处（最多）、events=0、idempotency=0。
**必补：** 替换 broad except（最高优先级）+ events + idempotency。

### weishenghuo（微生活）—— 10/35
**缺口：** 无 tenant_id（!）、无 events、无 idempotency。零 broad except 是亮点。
**必补：** 1）RLS 全链路（最严重，会员系统不能跨租户漏查）；2）events 接入 MEMBER.* 系列。

### xiaohongshu（小红书）—— 10/35
RLS 满分 5（46 处 tenant_id 最高）。
**缺口：** 无 tests、无 README、无 events、错误处理弱。
**必补：** README + 测试套件 + events（CHANNEL.ORDER_SYNCED 走小红书电商）。

### yiding（易订）—— 9/35
**缺口：** 无 tenant_id、无 events、测试覆盖低。
**必补：** RLS 全链路（预订系统跨租户隔离）+ events RESERVATION.* + 补 broad except。

---

## 四、三商户切片（必装适配器）

| 商户 | 必装适配器 | 当前总分 | 阻塞 DEMO？ |
|---|---|---|---|
| **czyz（尝在一起 / 品智）** | pinzhi(16), nuonuo(8), aoqiwei(20)? 待确认 | 16 ~ 20 | YES — pinzhi/nuonuo 都未过线 |
| **zqx（最黔线）** | TBD（创始人指定）。候选：pinzhi(16) 或 keruyun(9) | TBD | TBD |
| **sgc（尚宫厨）** | TBD（创始人指定）。候选：tiancai-shanglong(16) 或 keruyun(9) | TBD | TBD |

**结论：三商户均未过线。** Sprint F 演示前需要至少把 pinzhi / aoqiwei / nuonuo 推过 22 分。

---

## 五、过线优先级（投入产出比排序）

> "最少改动 → 最快过线" 的顺序。

1. **aoqiwei**（20→22+）：补 events 即可（+2~5 分）。**最高 ROI**。
2. **base**（17→22+）：补 README + idempotency 抽象方法。
3. **pinzhi**（16→22+）：events + idempotency + 替换 3 处 broad except。**czyz 阻塞项。**
4. **meituan-saas**（16→22+）：events + idempotency + 替换 1 处 broad except。
5. **tiancai-shanglong**（16→22+）：替换 7 处 broad except 是关键。
6. **nuonuo**（8→22+）：差距最大但 Tier 1（金税四期发票），**演示必修**，需要重大投入。

---

## 六、自动评分使用方式

```bash
# 全扫
python3 scripts/score_adapters.py --markdown -

# 单独看一个
python3 scripts/score_adapters.py --adapter pinzhi --json -

# CI 集成（exit code = 失败适配器数）
python3 scripts/score_adapters.py --json /tmp/scores.json
echo "失败数: $?"
```

CI 推荐：将 exit code 作为门禁，失败数 > N 阻断合并。

---

## 七、人工待确认项

脚本对以下两维只做"自动估算"，最终需人工 review：

- **契约完整度**：脚本只检查文件存在 + 关键字匹配，无法判断方法语义是否正确；
- **错误处理**：脚本基于 broad except 计数 + 关键字命中，无法判断错误码映射是否覆盖业务场景。

人工 review 模板见 `docs/development-plan-v6-remediation.md`。

---

## 八、变更日志

- 2026-04-25 v1：14 适配器首次评分，0/14 过线，Sprint F1 基线建立。
