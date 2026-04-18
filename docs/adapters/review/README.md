# Sprint F1 · 14 非品智适配器评审（7 维评分卡）

> 生成日期：2026-04-18 · 负责人：屯象 Architecture · 门禁：Sprint F1 Go/No-Go

## 1. 评审目的

Sprint F1（W3-4）交付门槛：**14 个非品智适配器**逐一通过 7 维评分卡，≥22 分才能在 `flags/agents/agent_flags.yaml` 置 `enabled=true` 上生产。本目录下 14 份骨架文档用于 Owner 填分、固化证据、汇总 P0/P1/P2 缺陷。本次 PR 只建骨架，不改代码。

## 2. 7 维评分卡（0-4 分锚点）

| 分 | 含义 |
|---|---|
| 0 | 完全缺失，无任何实现 |
| 1 | 有占位，但主路径不可用 |
| 2 | 主路径可用，异常/边界未覆盖 |
| 3 | 主路径+主要异常覆盖，有测试 |
| 4 | 全覆盖，含冲突/降级/重放/审计，测试 ≥80% |

7 维：
1. **订单/菜品双向同步完备性**——拉单/下发菜单/改状态三向是否闭环
2. **状态映射完备性**——含异常态/取消/退款/部分退款/售后
3. **重试/幂等**——签名防重放、idempotency_key、重复消息去重
4. **Mock vs 生产切换机制**——ENV / MOCK_MODE / stub fixtures
5. **凭证托管**——Vault/ENV，是否存在硬编码明文
6. **异常分支**——429/5xx 退避、超时降级、token 自动刷新
7. **事件总线接入**——是否 `emit_event` 到 shared/events（CLAUDE.md §XV）

## 3. 14 适配器对照表

| 代号 | 主目录 | 行数 | 评分 | Tier | 负责 Squad | 状态 | ETA | fix-PR |
|---|---|---|---|---|---|---|---|---|
| aoqiwei | shared/adapters/aoqiwei/ | 2679 | ?/28 | T1 | Channel-A | 待评 | W3 |  |
| tiancai-shanglong | shared/adapters/tiancai-shanglong/ | 923 | ?/28 | T1 | Channel-A | 待评 | W3 |  |
| keruyun | shared/adapters/keruyun/ | 564 | ?/28 | T1 | Channel-A | 待评 | W3 |  |
| weishenghuo | shared/adapters/weishenghuo/ | 800 | ?/28 | T1 | Channel-A | 待评 | W3 |  |
| meituan (-saas + 单文件) | shared/adapters/meituan-saas/ + meituan_adapter.py | 1991+320 | ?/28 | T1 | Channel-B | 待评 | W3 |  |
| eleme | shared/adapters/eleme/ + eleme_adapter.py | 810+437 | ?/28 | T1 | Channel-B | 待评 | W3 |  |
| douyin | shared/adapters/douyin/ + douyin_adapter.py | 537+432 | ?/28 | T1 | Channel-B | 待评 | W3 |  |
| yiding | shared/adapters/yiding/ | 1566 | ?/28 | T1 | Channel-A | 待评 | W4 |  |
| nuonuo | shared/adapters/nuonuo/ | 296 | ?/28 | T1 | Finance | 待评 | W4 |  |
| xiaohongshu | shared/adapters/xiaohongshu/ | 734 | ?/28 | T3 | Growth | 待评 | W4 |  |
| erp | shared/adapters/erp/ | 839 | ?/28 | T1 | Finance | 待评 | W4 |  |
| logistics | shared/adapters/logistics/ | 180 | ?/28 | T3 | Supply | 待评 | W4 |  |
| delivery_factory | shared/adapters/delivery_factory.py + delivery_platform_base.py | 71+160 | ?/28 | T1 | Channel-B | 待评 | W3 |  |
| wechat_delivery | shared/adapters/wechat_delivery_adapter.py | 225 | ?/28 | T1 | Channel-B | 待评 | W3 |  |

## 4. Go / No-Go 规则

| 总分 | 动作 |
|---|---|
| ≥22 | 允许生产 flag on（条件：P0 缺陷清零） |
| 18-21 | 条件放行，需列出缺陷清单 + 灰度 5% |
| <18 | **强制 flag off**，禁止生产启用，列入下 Sprint 整改清单 |

## 5. 评审进度跟踪

- [x] 2026-04-18 建立 14 份骨架文档（本次）
- [ ] W3 Day1 Channel-A/B Owner 填分 + 证据
- [ ] W3 Day3 P0 缺陷清单冻结
- [ ] W3 Day5 Sprint F1 Go/No-Go 评审会
- [ ] W4 P0 修复 → 重跑评分

## 6. 扫描汇总（2026-04-18 初次扫描）

针对 14 个适配器 + 6 个单文件适配器（同域合并计入上表 14 项）：

| 维度 | 命中数 | 详情 |
|---|---|---|
| 有 MOCK_MODE / mock_mode | 4 个 | meituan_adapter.py / eleme_adapter.py / douyin_adapter.py / wechat_delivery_adapter.py（仅作为 `mock_mode=True` 构造参数） |
| 接入 emit_event（事件总线） | **0 个** | 全部未接入 CLAUDE.md §XV 要求的统一事件总线 |
| 有幂等/防重放（idempotency/nonce） | 3 个 | nuonuo（nonce+签名）/ erp-kingdee（HMAC nonce）/ xiaohongshu（nonce） |
| 有重试/退避（retry/backoff） | 10 个 | 大多为字符串命中或注释，需逐一核实是否真实实现指数退避 |
| 有单元测试目录（tests/） | 5 个 | aoqiwei / tiancai-shanglong / keruyun / weishenghuo / meituan-saas / yiding（6 个）。eleme/douyin/nuonuo/xiaohongshu/erp/logistics **零测试** |

### P0 热点（初步推断，以 Owner 填分为准）

1. **全部 14 个未接 emit_event**——违反 CLAUDE.md §XV Phase 1 并行写入规范，属于跨域 P1（非单适配器 P0，但必须在 F1 内一并修复）
2. **logistics（180 行）**：无测试、无幂等、无 MOCK_MODE、仅 1 次签名相关命中——最脆弱
3. **eleme / douyin（单文件 437/432 行）**：无 tests/ 目录且承担 T1 渠道订单职责——P0 风险最高
4. **xiaohongshu / nuonuo / erp**：均无 tests/ 目录，其中 erp 承担金税对账链路（T1 Finance）、nuonuo 承担全电发票（Tier 1 §XVII）——测试缺口=资金安全 P0

### 建议下一步优先级

| # | 适配器 | 首要动作 |
|---|---|---|
| 1 | eleme / douyin / meituan 三件套 | 补 tests/、补 emit_event 注入点（CHANNEL.ORDER_SYNCED） |
| 2 | erp / nuonuo | 补 tests/、Tier 1 资金链路必须先补单元+集成测试再谈其他 |
| 3 | logistics | 评估是否降级到 T3 或限制启用范围（当前实现偏薄） |
| 4 | 全部 14 个 | 统一接入 `shared/events/src/emitter.emit_event`，事件类型依 CLAUDE.md §XV 表 |

---

## 7. 事件总线接入基类（Sprint F1 / PR F 交付）

PR F 为所有 14 个适配器统一交付接入事件总线的基础设施，路径 `shared/adapters/base/src/event_bus.py`。Squad Owner 在补缺口时只需改 3-5 行代码。

### 两种接入方式

**函数式（最小侵入）**：

```python
from shared.adapters.base.src.event_bus import emit_adapter_event
from shared.events.src.event_types import AdapterEventType

asyncio.create_task(emit_adapter_event(
    adapter_name="meituan",
    event_type=AdapterEventType.ORDER_INGESTED,
    tenant_id=tenant_id,
    scope="orders",
    payload={"source_id": raw["order_id"], "amount_fen": raw["total_price"] * 100},
))
```

**Mixin 继承（推荐新适配器）**：

```python
from shared.adapters.base.src.event_bus import AdapterEventMixin

class MeituanAdapter(AdapterEventMixin):
    adapter_name = "meituan"

    async def sync_orders(self, since, tenant_id):
        async with self.track_sync(tenant_id=tenant_id, scope="orders") as track:
            raw = await self._fetch_orders(since)
            track.ingested = len(raw)
            return raw
```

`track_sync` 自动发 `SYNC_STARTED` → `SYNC_FINISHED` / `SYNC_FAILED`，失败原样抛出。

### AdapterEventType 11 种事件

| 事件 | 用途 |
|---|---|
| `SYNC_STARTED` / `SYNC_FINISHED` / `SYNC_FAILED` | 同步三元事件（由 `track_sync` 自动发） |
| `ORDER_INGESTED` | 单条三方订单入库 |
| `MENU_SYNCED` / `MEMBER_SYNCED` / `INVENTORY_SYNCED` | 按实体分流的批次事件 |
| `STATUS_PUSHED` | 状态回写三方（并行运行期） |
| `WEBHOOK_RECEIVED` | 三方 webhook 回调入口（外卖退单/票据回执） |
| `RECONNECTED` | 长时故障首次恢复（触发 Agent 重算、SRE P0） |
| `CREDENTIAL_EXPIRED` | Token/AccessKey 过期 |

### 参考实现

`shared/adapters/pinzhi_adapter.py` `PinzhiPOSAdapter.sync_orders` 已接入 `track_sync`，其余 13 个适配器在填 7 维评分卡后的 fix-PR 中逐一接入，Owner 可对照此模式改造。

### 验收门槛

- [ ] 适配器 `emit_event` 维度得分 ≥ 3/4（即"主要事件+关键异常打点"）
- [ ] 至少覆盖 `ORDER_INGESTED` + `SYNC_FAILED` 两类事件
- [ ] payload 含 `adapter_name` + `source_id` + `amount_fen`（如涉及金额）
- [ ] `shared/adapters/base/tests/test_event_bus.py` 10/10 绿（PR F 已全绿）

---

骨架文档列表：见同目录 `<code>.md`（14 份）。每份骨架的 "7 维评分" 留 `?/4`，由 Squad Owner 在 W3 填写并提交 PR。
