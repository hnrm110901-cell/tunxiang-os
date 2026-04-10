"""
徐记海鲜门店业务场景模拟测试
测试范围：桌台全生命周期 × 徐记典型业务

门店配置（模拟）：
  - 大厅：20张圆桌（10-12人/桌），A区/B区各10张
  - 包间：8个（VIP包间3个，普通包间5个），最低消费 3000~15000元
  - 宴席厅：1个（可容纳30桌婚宴）
  - 活鲜区：4个鱼缸区域，品种 30+
  - 档口：热菜间/海鲜蒸锅间/冷菜间/主食间
"""
import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# ────────────────────────────────────────────────────────────────────
# 测试数据定义（不依赖真实DB，使用mock结构验证业务逻辑完整性）
# ────────────────────────────────────────────────────────────────────

STORE_ID    = uuid.UUID("00000000-0000-0000-0000-000000000001")
TENANT_ID   = uuid.UUID("00000000-0000-0000-0000-000000000099")
WAITER_A    = uuid.UUID("10000000-0000-0000-0000-000000000001")  # 大厅A区服务员
WAITER_B    = uuid.UUID("10000000-0000-0000-0000-000000000002")  # 包间服务员
MANAGER     = uuid.UUID("10000000-0000-0000-0000-000000000099")

# 桌台配置
TABLE_A01   = uuid.UUID("20000000-0000-0000-0000-000000000001")  # 大厅A区01
TABLE_VIP01 = uuid.UUID("20000000-0000-0000-0000-000000000101")  # VIP包间01
TABLE_VIP02 = uuid.UUID("20000000-0000-0000-0000-000000000102")  # VIP包间02
ZONE_HALL   = uuid.UUID("30000000-0000-0000-0000-000000000001")  # 大厅
ZONE_VIP    = uuid.UUID("30000000-0000-0000-0000-000000000002")  # VIP区


# ────────────────────────────────────────────────────────────────────
# 场景定义（每个场景包含：操作序列、预期结果、实测调用路径）
# ────────────────────────────────────────────────────────────────────

@dataclass
class TestResult:
    scenario: str
    step: str
    expected: str
    actual: str
    passed: bool
    gap: Optional[str] = None

results: list[TestResult] = []

def check(scenario: str, step: str, expected: str, actual: str, gap: Optional[str] = None):
    passed = actual == "OK" or (gap is None and actual == expected)
    results.append(TestResult(scenario, step, expected, actual, passed, gap))
    status = "✅" if passed else ("⚠️ GAP" if gap else "❌ FAIL")
    print(f"  {status} [{step}] {expected}")
    if gap:
        print(f"       差距: {gap}")


# ════════════════════════════════════════════════════════════════════
# 场景 A：15人商务宴请 VIP包间 + 活鲜点餐 + 企业结账
# 徐记高频场景：占营业额约35%
# ════════════════════════════════════════════════════════════════════
print("\n【场景A】15人商务宴请 VIP包间")

check("A", "A1_预订转开台",
    expected="预订seat → 自动创建 dining_session（含 booking_id、room_config）",
    actual="PARTIAL",
    gap="booking_api.py 自动开台仅传入基础参数，未从预订单提取 "
        "min_spend_fen/room_fee_fen/decoration_requests 写入 room_config。"
        "包间最低消费 (15000元) 丢失。"
)

check("A", "A2_包间开台写低消",
    expected="open_table() 从 tables.min_consume_fen 读取并写入 dining_session.room_config",
    actual="MISSING",
    gap="DiningSessionService.open_table() 未查询 tables.min_consume_fen，"
        "room_config 始终为空 {}。"
        "结账时 check_minimum_charge() 无从比对。"
)

check("A", "A3_点活鱼称重绑会话",
    expected="live_seafood_weigh_records 通过 dining_session_id 关联会话",
    actual="MISSING",
    gap="live_seafood_routes.py 的 /confirm 端点只绑定 order_id，"
        "无 dining_session_id 字段。"
        "转台时称重记录不会跟随迁移。"
        "大板看板无法显示'这桌有X条活鱼待称重'。"
)

check("A", "A4_活鱼加工方式选择",
    expected="称重记录携带 cooking_method（清蒸/红烧/盐焗）→ KDS展示",
    actual="OK",  # live_seafood_routes 支持 cooking_method 字段
)

check("A", "A5_KDS出餐回调会话",
    expected="kds_actions.finish_cooking() → DiningSessionService.record_dish_served()",
    actual="MISSING",
    gap="finish_cooking() 完成后无回调 dining_session。"
        "导致 first_dish_served_at 永远为 NULL，"
        "会话状态无法从 ordering 自动推进到 dining。"
        "翻台率物化视图中的出餐时长数据缺失。"
)

check("A", "A6_中途VIP识别触发推荐",
    expected="identify_vip() → TABLE.VIP_IDENTIFIED → 会员洞察Agent推送历史偏好",
    actual="OK",  # API已实现，Agent订阅已注册
)

check("A", "A7_结账低消校验",
    expected="request_bill() 时校验 room_config.min_spend_fen，不足提示差额",
    actual="MISSING",
    gap="DiningSessionService.request_bill() 直接跳转 billing 状态，"
        "未调用 room_rules.check_minimum_charge()。"
        "15000元包间低消，消费12000元可直接买单，系统不提示。"
)

check("A", "A8_企业发票开具",
    expected="结账时填企业抬头 → 绑定 dining_session_id 发票记录",
    actual="PARTIAL",
    gap="invoice_routes.py 按 order_id 开票，多轮点菜（主单+加菜单）"
        "需分别开票，无法合并为一张企业发票绑定到 dining_session。"
)

check("A", "A9_存酒自动关联",
    expected="开台时查询该VIP的存酒记录，提示服务员可取酒",
    actual="MISSING",
    gap="wine_storage 在 tx-finance，与 dining_session 服务完全隔离。"
        "开台时无自动查询存酒，服务员需手动去另一系统查找。"
)


# ════════════════════════════════════════════════════════════════════
# 场景 B：高峰期25桌同时运营（周五晚市）
# 徐记大厅A区+B区同时开台
# ════════════════════════════════════════════════════════════════════
print("\n【场景B】周五晚市高峰期25桌同时运营")

check("B", "B1_大板并发性能",
    expected="get_store_board() 25桌时响应 < 200ms",
    actual="RISK",
    gap="get_store_board SQL 中 pending_calls 是相关子查询（每桌一次）。"
        "25桌同时开台 = 25次子查询，高峰期响应可能 > 500ms。"
        "应改为 LEFT JOIN + GROUP BY 或窗口函数。"
)

check("B", "B2_服务员分区路由",
    expected="waiter_zone_assignments 自动将服务呼叫路由到对应服务员",
    actual="PARTIAL",
    gap="service_call_routes.py 创建呼叫时未从 waiter_zone_assignments "
        "自动填充 handled_by。服务员需手动抢单，无法实现'大厅A区呼叫只推给A区服务员'。"
)

check("B", "B3_出餐优先级_实时刷新",
    expected="KDS大板优先级评分随催菜次数实时更新",
    actual="PARTIAL",
    gap="kds_by_session_routes.py 优先级计算依赖 kds_tasks.is_rushed，"
        "但 rush_count 只在查询时计算，无推送机制。"
        "服务员催菜后，KDS大板需手动刷新才能看到优先级变化。"
)

check("B", "B4_翻台率实时统计",
    expected="今日翻台率实时显示在大板汇总",
    actual="MISSING",
    gap="mv_table_turnover 是物化视图，由投影器异步填充。"
        "但 TableTurnoverProjector 未实现（仅注册了 checkpoint）。"
        "今日翻台率数据为空。"
)

check("B", "B5_桌台大板状态颜色编码",
    expected="9态状态对应9种颜色，前端 diningSessionStore 驱动",
    actual="PARTIAL",
    gap="DiningSessionStore 已定义9种状态，但 web-pos TableManagement 页面"
        "（TableCardView/TableMapView）仍读取旧 tableStore，"
        "未切换到 diningSessionStore。需重构3个视图组件。"
)

check("B", "B6_WebSocket实时更新",
    expected="开台/清台时通过WS推送到所有POS客户端，大板自动刷新",
    actual="PARTIAL",
    gap="table_layout_service.broadcast_table_update() 只广播桌台布局变更。"
        "dining_session 状态变更（点菜→用餐→买单）无WS广播。"
        "各POS客户端需定时轮询，不是事件驱动。"
)


# ════════════════════════════════════════════════════════════════════
# 场景 C：30桌婚宴（宴席厅）
# 同一宴席合同，独立开桌但汇总账单
# ════════════════════════════════════════════════════════════════════
print("\n【场景C】30桌婚宴宴席管理")

check("C", "C1_宴席桌编组",
    expected="宴席下30张桌台绑定同一 banquet_session_id，支持统一出餐管理",
    actual="MISSING",
    gap="dining_sessions 表无 banquet_session_id 字段（宴席编组ID）。"
        "banquet_lifecycle.py 是独立状态机，与 dining_sessions 完全脱离。"
        "30桌婚宴无法在桌台大板上按'婚宴编组'显示和操作。"
)

check("C", "C2_宴席统一菜单下发",
    expected="宴席确认菜单后，30桌同时接收相同点单，自动发KDS分单",
    actual="MISSING",
    gap="banquet_menu_routes.py 创建宴席场次时无法批量关联多个 dining_session。"
        "需手动在每桌分别点菜，无批量下发能力。"
)

check("C", "C3_宴席统一结账",
    expected="30桌消费汇总到宴席合同，一张账单结清",
    actual="MISSING",
    gap="merge_sessions 并台最多支持多桌合并到一个 dining_session，"
        "但30桌婚宴全并台在数据库层面可行（数据量大），"
        "但前端无'宴席结账'入口，split_payment 也不支持宴席维度拆分。"
)

check("C", "C4_宴席上菜节奏控制",
    expected="宴席分道上菜（冷盘→热菜→主食→甜品），按道次控制出餐",
    actual="PARTIAL",
    gap="course_firing_routes.py 和 course_firing_service.py 存在，"
        "但与 dining_sessions 无关联。"
        "宴席道次控制仅在订单层，无法与30桌的 dining_session 状态联动。"
)

check("C", "C5_宴席定金抵扣",
    expected="结账时宴席定金自动抵扣，剩余金额支付",
    actual="PARTIAL",
    gap="banquet_payment_service.py 有定金管理，但结账路径走 dining_session → "
        "payment_service，二者未打通。"
        "结账时不会自动查询并抵扣宴席定金。"
)


# ════════════════════════════════════════════════════════════════════
# 场景 D：包间转台（从小包间升级到大VIP包间）
# VIP客人临时要求换更大包间
# ════════════════════════════════════════════════════════════════════
print("\n【场景D】包间升级转台")

check("D", "D1_转台保留会话数据",
    expected="transfer_table() 保留所有订单、服务呼叫、活鲜记录",
    actual="PARTIAL",
    gap="transfer_table() 更新 dining_session.table_id 和 table_no_snapshot，"
        "订单通过 dining_session_id 关联自动跟随。"
        "但活鲜称重记录（live_seafood_weigh_records）绑定的是 order_id，"
        "虽间接跟随，但会话事件中未记录'活鱼随桌迁移'，审计链断裂。"
)

check("D", "D2_转台更新包间低消",
    expected="转台到新包间时，room_config.min_spend_fen 更新为新包间配置",
    actual="MISSING",
    gap="transfer_table() 只更新 table_id，未查询新桌台的 min_consume_fen "
        "并更新 dining_session.room_config。"
        "从5000元小包间转到15000元大包间，低消不会自动更新。"
)

check("D", "D3_转台通知KDS",
    expected="转台后 KDS 所有待出菜品的桌号更新为新桌号",
    actual="MISSING",
    gap="transfer_table() 未通知 KDS 更新 kds_tasks 中的 table_number 字段。"
        "厨师和传菜员的 KDS 屏幕仍显示旧桌号，导致送餐错误。"
)

check("D", "D4_存酒迁移",
    expected="转台时提示服务员将存酒记录关联到新桌台",
    actual="MISSING",
    gap="wine_storage 无 dining_session_id 关联，转台时存酒与桌台完全脱钩，"
        "无任何提示机制。"
)


# ════════════════════════════════════════════════════════════════════
# 场景 E：AA制结账（8人饭局，部分先离席）
# ════════════════════════════════════════════════════════════════════
print("\n【场景E】8人AA制 + 部分先走结账")

check("E", "E1_多轮点菜跨单分账",
    expected="AA制拆账支持跨主单+加菜单合并计算每人应付金额",
    actual="PARTIAL",
    gap="split_settle_service.py 按 order_id 拆分，无法跨多个订单（主单+2轮加菜）"
        "做整体AA计算。需先把所有orders的items合并，目前无此API。"
)

check("E", "E2_活鱼按人分摊",
    expected="活鱼费用（浮动价格）纳入AA计算",
    actual="MISSING",
    gap="live_seafood_weigh_records 未与 seat_order（座位点餐）关联。"
        "活鱼是直接绑到订单，无法追踪'这条鱼是谁点的'，AA时需手动分摊。"
)

check("E", "E3_部分结账离席",
    expected="3人先买单，剩余5人继续用餐，会话保持活跃",
    actual="MISSING",
    gap="dining_session 不支持'部分结账'概念。"
        "complete_payment() 直接将整个会话状态改为 paid。"
        "无法实现部分人先结账、其余人继续点菜。"
)


# ════════════════════════════════════════════════════════════════════
# 场景 F：活鱼价格浮动 × 折扣守护
# ════════════════════════════════════════════════════════════════════
print("\n【场景F】活鱼浮动价格 × 折扣管控")

check("F", "F1_活鱼当日定价",
    expected="活鱼价格随当日进货价动态调整，自动更新菜单显示价",
    actual="PARTIAL",
    gap="tx-menu 的菜品价格是固定的。"
        "live_seafood_routes.py 确实支持 unit_price_fen 参数，"
        "但价格与 Dish 主表脱钩，无'当日水产价格表'驱动机制。"
)

check("F", "F2_折扣守护兼容活鱼",
    expected="折扣守护毛利底线校验对活鱼浮动价格有效",
    actual="MISSING",
    gap="折扣守护 Agent 基于 Dish.unit_price_fen（固定价）计算毛利。"
        "活鱼称重记录的 unit_price_fen 是临时录入，不在 dish_cost_records 中。"
        "折扣守护无法感知活鱼真实成本，毛利校验形同虚设。"
)


# ════════════════════════════════════════════════════════════════════
# 输出测试报告
# ════════════════════════════════════════════════════════════════════

def print_report():
    total = len(results)
    passed  = sum(1 for r in results if r.passed)
    gaps    = sum(1 for r in results if r.gap)
    missing = sum(1 for r in results if r.actual == "MISSING")
    partial = sum(1 for r in results if r.actual == "PARTIAL")
    risks   = sum(1 for r in results if r.actual == "RISK")

    print("\n" + "═" * 70)
    print(f"  徐记海鲜桌台能力测试报告  {datetime.now().strftime('%Y-%m-%d')}")
    print("═" * 70)
    print(f"  总测试项: {total}")
    print(f"  ✅ 已实现 (OK):      {passed}")
    print(f"  ❌ 完全缺失 (MISSING): {missing}")
    print(f"  ⚠️  部分实现 (PARTIAL): {partial}")
    print(f"  🔴 性能风险 (RISK):   {risks}")
    print(f"  覆盖率: {passed/total*100:.0f}%")
    print("═" * 70)

    print("\n【关键差距汇总（按优先级）】\n")
    p0_gaps = [r for r in results if r.gap and r.actual in ("MISSING",)]
    p1_gaps = [r for r in results if r.gap and r.actual in ("PARTIAL",)]
    risk_gaps = [r for r in results if r.gap and r.actual == "RISK"]

    print("P0 — 核心业务断路（立即影响正常运营）：")
    for r in p0_gaps:
        print(f"  [{r.scenario}-{r.step}] {r.expected[:40]}...")
        print(f"    → {r.gap[:80]}...")
        print()

    print("P1 — 部分实现（功能降级，影响体验）：")
    for r in p1_gaps:
        print(f"  [{r.scenario}-{r.step}] {r.expected[:40]}...")
        print(f"    → {r.gap[:80]}...")
        print()

    print("P2 — 性能/架构风险：")
    for r in risk_gaps:
        print(f"  [{r.scenario}-{r.step}] {r.gap}")

print_report()
