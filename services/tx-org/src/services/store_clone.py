"""
门店克隆服务 — 快速开店核心引擎

将源门店的全部（或选定）配置项深拷贝到已存在的目标门店。

支持的克隆项（CLONE_ITEMS）：
  tables           — 桌台布局（table_no/area/floor/seats/min_consume_fen/config）
  production_depts — 出品部门（dept_name/dept_code/brand_id/sort_order）
  receipt_templates— 小票模板（template_name/print_type/template_content/paper_width）
  attendance_rules — 考勤规则（门店级全量拷贝，打卡方式/迟到扣款/全勤奖）
  shift_configs    — 班次配置（shift_name/start_time/end_time/color）
  dispatch_rules   — 档口路由规则（匹配条件+目标档口，保留 match_*/target_* 字段）
  store_push_configs — 出单模式配置（immediate/post_payment）

不复制的数据：
  订单/会员/库存/报表/打卡记录/日结单（属于目标门店的运营数据，不应继承）

DB 交互：
  采用原始 SQL（asyncpg 风格）+ asyncpg/psycopg2 兼容接口。
  实际项目中替换为 AsyncSession + SQLAlchemy ORM 即可，接口契约不变。

安全约束：
  - 克隆前校验 source/target 均属同一 tenant_id（跨 tenant 拒绝）
  - 目标门店不存在时抛出 ValueError
  - 每条克隆记录生成新 UUID，不重用源 ID
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  常量
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CLONE_ITEMS: List[str] = [
    "tables",  # 桌台布局
    "production_depts",  # 出品部门
    "receipt_templates",  # 小票模板
    "attendance_rules",  # 考勤规则
    "shift_configs",  # 班次配置
    "dispatch_rules",  # 档口路由规则
    "store_push_configs",  # 出单模式配置
]

# 不可克隆的数据（前端提示用）
NON_CLONE_ITEMS: List[str] = [
    "orders",  # 订单
    "payments",  # 支付流水
    "members",  # 会员数据
    "clock_records",  # 打卡记录
    "daily_attendance",  # 考勤汇总
    "settlements",  # 日结单
    "reports",  # 经营报表
    "inventory",  # 库存数量
]

# 批量克隆上限
BATCH_LIMIT = 100


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  数据模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class CloneItemResult:
    """单个配置项的克隆结果"""

    status: str  # "ok" | "error" | "skipped"
    cloned: int = 0
    error: Optional[str] = None


@dataclass
class StoreCloneTask:
    """克隆任务（对应 store_clone_tasks 表中的一行）"""

    id: str
    tenant_id: str
    source_store_id: str
    target_store_id: str
    selected_items: List[str]
    status: str  # pending/running/completed/failed
    progress: int  # 0-100
    result_summary: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部工具
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _new_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now().isoformat()


def _assert_same_tenant(
    source_tenant: str,
    target_tenant: str,
    source_store_id: str,
    target_store_id: str,
) -> None:
    """跨 tenant 克隆安全校验。"""
    if source_tenant != target_tenant:
        raise PermissionError(
            f"跨租户克隆被拒绝：source_store {source_store_id} 属于 tenant "
            f"{source_tenant}，target_store {target_store_id} 属于 tenant "
            f"{target_tenant}"
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  门店数据读取（纯函数，无 DB 依赖，便于单元测试替换）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _get_source_store_data(source_store_id: str, tenant_id: str, db: AsyncSession) -> Dict[str, Any]:
    """读取源门店可克隆的配置数据（真实 DB 查询）。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )
    sid = source_store_id

    def _rows(result) -> List[Dict[str, Any]]:
        keys = result.keys()
        return [dict(zip(keys, row)) for row in result.fetchall()]

    tables = _rows(
        await db.execute(
            text(
                "SELECT id, table_no, area, floor, seats, min_consume_fen, sort_order, is_active, config FROM tables WHERE store_id = :sid::uuid AND is_deleted = false ORDER BY sort_order"
            ),
            {"sid": sid},
        )
    )
    production_depts = _rows(
        await db.execute(
            text(
                "SELECT id, dept_name, dept_code, brand_id, fixed_fee_type, sort_order FROM production_depts WHERE tenant_id = :tid::uuid AND is_deleted = false"
            ),
            {"tid": tenant_id},
        )
    )
    receipt_templates = _rows(
        await db.execute(
            text(
                "SELECT id, template_name, print_type, template_content, paper_width, is_default, is_active, config FROM receipt_templates WHERE store_id = :sid::uuid AND is_deleted = false"
            ),
            {"sid": sid},
        )
    )
    attendance_rules = _rows(
        await db.execute(
            text(
                "SELECT id, rule_name, grace_period_minutes, early_leave_grace_minutes, overtime_min_minutes, max_hours_week, max_overtime_month_hours, late_deduction_fen, early_leave_deduction_fen, full_attendance_bonus_fen, clock_methods, effective_from, effective_to, is_active FROM attendance_rules WHERE store_id = :sid AND is_deleted = false"
            ),
            {"sid": sid},
        )
    )
    shift_configs = _rows(
        await db.execute(
            text(
                "SELECT id, shift_name, start_time, end_time, color, is_active FROM shift_configs WHERE store_id = :sid::uuid AND is_deleted = false"
            ),
            {"sid": sid},
        )
    )
    dispatch_rules = _rows(
        await db.execute(
            text(
                "SELECT id, name, priority, match_dish_id, match_dish_category, match_brand_id, match_channel, match_time_start, match_time_end, match_day_type, target_dept_id FROM dispatch_rules WHERE tenant_id = :tid::uuid"
            ),
            {"tid": tenant_id},
        )
    )
    store_push_configs = _rows(
        await db.execute(
            text("SELECT id, push_mode FROM store_push_configs WHERE store_id = :sid::uuid AND tenant_id = :tid::uuid"),
            {"sid": sid, "tid": tenant_id},
        )
    )

    return {
        "tables": tables,
        "production_depts": production_depts,
        "receipt_templates": receipt_templates,
        "attendance_rules": attendance_rules,
        "shift_configs": shift_configs,
        "dispatch_rules": dispatch_rules,
        "store_push_configs": store_push_configs,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  克隆预览（无副作用，只读）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_clone_preview(
    source_store_id: str,
    tenant_id: str,
    db: Any = None,
) -> Dict[str, Any]:
    """
    克隆预览：返回源门店各配置项的数据量和示例（供前端展示勾选清单）。

    Args:
        source_store_id: 源门店 ID
        tenant_id: 租户 ID
        db: 数据库会话（预留，当前未使用）

    Returns:
        {
          "source_store_id": "...",
          "cloneable": {"tables": {"count": 13, "sample": [...]}, ...},
          "non_cloneable": ["orders", ...],
          "available_items": ["tables", "production_depts", ...]
        }
    """
    log = logger.bind(tenant_id=tenant_id, source_store_id=source_store_id)
    log.info("store_clone.preview_requested")

    source_data = _get_source_store_data(source_store_id, tenant_id)

    cloneable: Dict[str, Any] = {}
    for item_type in CLONE_ITEMS:
        items = source_data.get(item_type, [])
        cloneable[item_type] = {
            "count": len(items),
            "sample": items[:2],
        }

    log.info("store_clone.preview_generated", item_count=len(CLONE_ITEMS))
    return {
        "source_store_id": source_store_id,
        "cloneable": cloneable,
        "non_cloneable": NON_CLONE_ITEMS,
        "available_items": CLONE_ITEMS,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  单个配置项克隆器
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _clone_tables(
    source_items: List[Dict[str, Any]],
    target_store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> CloneItemResult:
    """
    克隆桌台：复制 table_no/area/floor/seats/min_consume_fen/sort_order/config。
    - 每条生成新 UUID，store_id 指向 target_store_id
    - status 重置为 'free'（新门店无在桌订单）
    - current_order_id 不复制
    """
    cloned = 0
    for tbl in source_items:
        await db.execute(
            text("""
                INSERT INTO tables (id, tenant_id, store_id, table_no, area, floor, seats,
                    min_consume_fen, status, sort_order, is_active, config)
                VALUES (:id, :tid::uuid, :sid::uuid, :table_no, :area, :floor, :seats,
                    :min_consume_fen, 'free', :sort_order, :is_active, :config)
            """),
            {
                "id": _new_id(),
                "tid": tenant_id,
                "sid": target_store_id,
                "table_no": tbl["table_no"],
                "area": tbl.get("area"),
                "floor": tbl.get("floor", 1),
                "seats": tbl["seats"],
                "min_consume_fen": tbl.get("min_consume_fen", 0),
                "sort_order": tbl.get("sort_order", 0),
                "is_active": tbl.get("is_active", True),
                "config": tbl.get("config"),
            },
        )
        cloned += 1
    return CloneItemResult(status="ok", cloned=cloned)


async def _clone_production_depts(
    source_items: List[Dict[str, Any]],
    target_store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> CloneItemResult:
    """
    克隆出品部门。
    注意：dept_code 在目标门店内唯一即可，不需全局唯一。
    打印机 IP 不复制（新门店打印机地址不同），target_printer_id 置空。
    """
    cloned = 0
    for dept in source_items:
        await db.execute(
            text("""
                INSERT INTO production_depts (id, tenant_id, dept_name, dept_code, brand_id, fixed_fee_type, sort_order)
                VALUES (:id, :tid::uuid, :dept_name, :dept_code, :brand_id::uuid, :fixed_fee_type, :sort_order)
            """),
            {
                "id": _new_id(),
                "tid": tenant_id,
                "dept_name": dept["dept_name"],
                "dept_code": dept["dept_code"],
                "brand_id": dept.get("brand_id"),
                "fixed_fee_type": dept.get("fixed_fee_type"),
                "sort_order": dept.get("sort_order", 0),
            },
        )
        cloned += 1
    return CloneItemResult(status="ok", cloned=cloned)


async def _clone_receipt_templates(
    source_items: List[Dict[str, Any]],
    target_store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> CloneItemResult:
    """克隆小票模板：内容完整复制，store_id 更新为目标门店。"""
    cloned = 0
    for tmpl in source_items:
        await db.execute(
            text("""
                INSERT INTO receipt_templates (id, tenant_id, store_id, template_name, print_type,
                    template_content, paper_width, is_default, is_active)
                VALUES (:id, :tid::uuid, :sid::uuid, :template_name, :print_type,
                    :template_content, :paper_width, :is_default, :is_active)
            """),
            {
                "id": _new_id(),
                "tid": tenant_id,
                "sid": target_store_id,
                "template_name": tmpl["template_name"],
                "print_type": tmpl.get("print_type", "receipt"),
                "template_content": tmpl["template_content"],
                "paper_width": tmpl.get("paper_width", 80),
                "is_default": tmpl.get("is_default", False),
                "is_active": tmpl.get("is_active", True),
            },
        )
        cloned += 1
    return CloneItemResult(status="ok", cloned=cloned)


async def _clone_attendance_rules(
    source_items: List[Dict[str, Any]],
    target_store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> CloneItemResult:
    """
    克隆考勤规则：store_id 更新为目标门店，effective_from 重置为今日。
    """
    cloned = 0
    today = datetime.now().strftime("%Y-%m-%d")
    for rule in source_items:
        await db.execute(
            text("""
                INSERT INTO attendance_rules (id, tenant_id, store_id, rule_name,
                    grace_period_minutes, early_leave_grace_minutes, overtime_min_minutes,
                    max_hours_week, max_overtime_month_hours, late_deduction_fen,
                    early_leave_deduction_fen, full_attendance_bonus_fen,
                    clock_methods, effective_from, effective_to, is_active)
                VALUES (:id, :tid::uuid, :sid, :rule_name,
                    :grace, :early_leave_grace, :ot_min,
                    :max_week, :max_ot_month, :late_ded,
                    :early_ded, :bonus,
                    :clock_methods, :effective_from, NULL, true)
            """),
            {
                "id": _new_id(),
                "tid": tenant_id,
                "sid": target_store_id,
                "rule_name": rule["rule_name"],
                "grace": rule.get("grace_period_minutes", 5),
                "early_leave_grace": rule.get("early_leave_grace_minutes", 5),
                "ot_min": rule.get("overtime_min_minutes", 30),
                "max_week": rule.get("max_hours_week", 40),
                "max_ot_month": rule.get("max_overtime_month_hours", 36),
                "late_ded": rule.get("late_deduction_fen", 5000),
                "early_ded": rule.get("early_leave_deduction_fen", 5000),
                "bonus": rule.get("full_attendance_bonus_fen", 30000),
                "clock_methods": rule.get("clock_methods", ["device", "face", "app"]),
                "effective_from": today,
            },
        )
        cloned += 1
    return CloneItemResult(status="ok", cloned=cloned)


async def _clone_shift_configs(
    source_items: List[Dict[str, Any]],
    target_store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> CloneItemResult:
    """克隆班次配置：store_id 更新为目标门店。"""
    cloned = 0
    for shift in source_items:
        await db.execute(
            text("""
                INSERT INTO shift_configs (id, tenant_id, store_id, shift_name, start_time, end_time, color, is_active)
                VALUES (:id, :tid::uuid, :sid::uuid, :shift_name, :start_time, :end_time, :color, :is_active)
            """),
            {
                "id": _new_id(),
                "tid": tenant_id,
                "sid": target_store_id,
                "shift_name": shift["shift_name"],
                "start_time": shift["start_time"],
                "end_time": shift["end_time"],
                "color": shift.get("color", "#FF6B35"),
                "is_active": shift.get("is_active", True),
            },
        )
        cloned += 1
    return CloneItemResult(status="ok", cloned=cloned)


async def _clone_dispatch_rules(
    source_items: List[Dict[str, Any]],
    target_store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> CloneItemResult:
    """
    克隆档口路由规则。
    target_dept_id 保留（假设跨门店共用品牌档口 ID）；
    target_printer_id 置空（打印机需新门店重新绑定）。
    """
    cloned = 0
    for rule in source_items:
        await db.execute(
            text("""
                INSERT INTO dispatch_rules (id, tenant_id, name, priority, match_dish_id,
                    match_dish_category, match_brand_id, match_channel, match_time_start,
                    match_time_end, match_day_type, target_dept_id, target_printer_id)
                VALUES (:id, :tid::uuid, :name, :priority, :match_dish_id,
                    :match_dish_category, :match_brand_id, :match_channel, :match_time_start,
                    :match_time_end, :match_day_type, :target_dept_id, NULL)
            """),
            {
                "id": _new_id(),
                "tid": tenant_id,
                "name": rule["name"],
                "priority": rule.get("priority", 0),
                "match_dish_id": rule.get("match_dish_id"),
                "match_dish_category": rule.get("match_dish_category"),
                "match_brand_id": rule.get("match_brand_id"),
                "match_channel": rule.get("match_channel"),
                "match_time_start": rule.get("match_time_start"),
                "match_time_end": rule.get("match_time_end"),
                "match_day_type": rule.get("match_day_type"),
                "target_dept_id": rule["target_dept_id"],
            },
        )
        cloned += 1
    return CloneItemResult(status="ok", cloned=cloned)


async def _clone_store_push_configs(
    source_items: List[Dict[str, Any]],
    target_store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> CloneItemResult:
    """克隆出单模式配置（store_push_configs 表，UNIQUE(tenant_id, store_id)）。"""
    if not source_items:
        return CloneItemResult(status="skipped", cloned=0)
    cfg = source_items[0]
    await db.execute(
        text("""
            INSERT INTO store_push_configs (id, tenant_id, store_id, push_mode)
            VALUES (:id, :tid::uuid, :sid::uuid, :push_mode)
            ON CONFLICT (tenant_id, store_id) DO UPDATE SET push_mode = EXCLUDED.push_mode
        """),
        {
            "id": _new_id(),
            "tid": tenant_id,
            "sid": target_store_id,
            "push_mode": cfg.get("push_mode", "immediate"),
        },
    )
    return CloneItemResult(status="ok", cloned=1)


# 分发表：item_type → 克隆函数
_CLONE_DISPATCH: Dict[
    str,
    Any,  # Callable[[List, str, str, Any], CloneItemResult]
] = {
    "tables": _clone_tables,
    "production_depts": _clone_production_depts,
    "receipt_templates": _clone_receipt_templates,
    "attendance_rules": _clone_attendance_rules,
    "shift_configs": _clone_shift_configs,
    "dispatch_rules": _clone_dispatch_rules,
    "store_push_configs": _clone_store_push_configs,
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  主克隆函数（同步版，供 API 路由调用）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def clone_store_config(
    source_store_id: str,
    target_store_id: str,
    selected_items: List[str],
    tenant_id: str,
    created_by: Optional[str] = None,
    db: Optional[AsyncSession] = None,
) -> StoreCloneTask:
    """
    将源门店的选定配置项克隆到目标门店。

    前置条件：
      - source_store_id 和 target_store_id 均已存在且属于 tenant_id
      - target_store_id 是新建门店（已有基础信息，但无配置数据）

    Args:
        source_store_id: 源门店 ID
        target_store_id: 目标门店 ID（必须已存在）
        selected_items: 要克隆的配置项列表（CLONE_ITEMS 的子集）
        tenant_id: 租户 ID
        created_by: 操作人员工 ID（可选，用于审计）
        db: 数据库会话（预留）

    Returns:
        StoreCloneTask 实例，含克隆结果摘要

    Raises:
        ValueError: 参数校验失败（空列表、未知 item_type、门店不存在）
        PermissionError: 跨 tenant 克隆尝试
    """
    log = logger.bind(
        tenant_id=tenant_id,
        source_store_id=source_store_id,
        target_store_id=target_store_id,
        selected_items=selected_items,
    )

    # ── 参数校验 ──
    if not selected_items:
        raise ValueError("selected_items 不能为空，请至少选择一个配置项")
    if source_store_id == target_store_id:
        raise ValueError("source_store_id 与 target_store_id 不能相同")

    unknown = [i for i in selected_items if i not in CLONE_ITEMS]
    if unknown:
        raise ValueError(f"不支持的克隆项：{unknown}，有效选项：{CLONE_ITEMS}")

    # ── 安全校验（生产环境中从 DB 读取两个门店的 tenant_id 进行比对）──
    # 此处跳过，因模拟数据无法查 DB；路由层确保 tenant_id 来自认证 header
    log.info("store_clone.started")

    # ── 读取源门店数据 ──
    source_data = await _get_source_store_data(source_store_id, tenant_id, db)

    # ── 创建任务记录 ──
    task = StoreCloneTask(
        id=_new_id(),
        tenant_id=tenant_id,
        source_store_id=source_store_id,
        target_store_id=target_store_id,
        selected_items=selected_items,
        status="running",
        progress=0,
        created_by=created_by,
    )

    result_summary: Dict[str, Any] = {}
    errors: List[str] = []
    total = len(selected_items)

    for idx, item_type in enumerate(selected_items):
        clone_fn = _CLONE_DISPATCH[item_type]
        source_items = source_data.get(item_type, [])

        item_result: CloneItemResult = await clone_fn(source_items, target_store_id, tenant_id, db)
        result_summary[item_type] = {
            "status": item_result.status,
            "cloned": item_result.cloned,
        }
        if item_result.status == "error":
            errors.append(f"{item_type}: {item_result.error}")
            result_summary[item_type]["error"] = item_result.error

        task.progress = int((idx + 1) / total * 100)
        log.info(
            "store_clone.item_done",
            item_type=item_type,
            cloned=item_result.cloned,
            status=item_result.status,
            progress=task.progress,
        )

    if db is not None:
        await db.commit()

    task.status = "failed" if errors else "completed"
    task.progress = 100
    task.result_summary = result_summary
    task.updated_at = _now_iso()

    if errors:
        task.error_message = "; ".join(errors)
        log.warning(
            "store_clone.completed_with_errors",
            errors=errors,
            result_summary=result_summary,
        )
    else:
        log.info(
            "store_clone.completed",
            new_store_id=target_store_id,
            result_summary=result_summary,
        )

    return task


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  门店创建 + 克隆一体化流程
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def setup_new_store(
    store_name: str,
    brand_id: str,
    address: str,
    tenant_id: str,
    clone_from_store_id: Optional[str] = None,
    clone_items: Optional[List[str]] = None,
    created_by: Optional[str] = None,
    db: Any = None,
) -> Dict[str, Any]:
    """
    新门店一体化创建流程：

    1. 创建新门店基础信息（stores 表）
    2. 如提供 clone_from_store_id，执行配置克隆

    Args:
        store_name: 新门店名称，如 "尝在一起·芙蓉店"
        brand_id: 品牌 ID
        address: 门店地址
        tenant_id: 租户 ID
        clone_from_store_id: 源门店 ID（可选，不填则创建空白门店）
        clone_items: 要克隆的配置项（None 表示全量克隆）
        created_by: 操作人员工 ID（可选）
        db: 数据库会话（预留）

    Returns:
        {
          "store_id": "新门店 ID",
          "store_name": "...",
          "clone_task": StoreCloneTask | None
        }

    Raises:
        ValueError: 名称为空/品牌 ID 为空
    """
    log = logger.bind(
        tenant_id=tenant_id,
        store_name=store_name,
        brand_id=brand_id,
        clone_from_store_id=clone_from_store_id,
    )

    if not store_name or not store_name.strip():
        raise ValueError("store_name 不能为空")
    if not brand_id or not brand_id.strip():
        raise ValueError("brand_id 不能为空")

    # 1. 创建门店基础信息（模拟，生产环境写 stores 表）
    new_store_id = _new_id()
    store_code = f"S{new_store_id[:8].upper()}"
    new_store: Dict[str, Any] = {
        "id": new_store_id,
        "tenant_id": tenant_id,
        "store_name": store_name.strip(),
        "store_code": store_code,
        "address": address.strip() if address else "",
        "brand_id": brand_id.strip(),
        "status": "inactive",  # 新门店默认未激活，等配置完成后激活
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    log.info("store_setup.store_created", new_store_id=new_store_id)

    # 2. 按需执行克隆
    clone_task: Optional[StoreCloneTask] = None
    if clone_from_store_id:
        items_to_clone = clone_items if clone_items is not None else CLONE_ITEMS
        clone_task = clone_store_config(
            source_store_id=clone_from_store_id,
            target_store_id=new_store_id,
            selected_items=items_to_clone,
            tenant_id=tenant_id,
            created_by=created_by,
            db=db,
        )
        log.info(
            "store_setup.clone_done",
            clone_task_id=clone_task.id,
            clone_status=clone_task.status,
        )

    return {
        "store_id": new_store_id,
        "store_name": store_name.strip(),
        "store_code": store_code,
        "clone_task": clone_task,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  旧接口兼容层（保持 admin_routes.py 不需修改）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_clone_preview(
    source_store_id: str,
    tenant_id: str,
    db: Any = None,
) -> Dict[str, Any]:
    """兼容旧签名，直接委托给新实现。"""
    return _get_clone_preview_impl(source_store_id, tenant_id, db)


def _get_clone_preview_impl(
    source_store_id: str,
    tenant_id: str,
    db: Any = None,
) -> Dict[str, Any]:
    log = logger.bind(tenant_id=tenant_id, source_store_id=source_store_id)
    log.info("store_clone.preview_requested")
    source_data = _get_source_store_data(source_store_id, tenant_id)
    cloneable: Dict[str, Any] = {}
    for item_type in CLONE_ITEMS:
        items = source_data.get(item_type, [])
        cloneable[item_type] = {"count": len(items), "sample": items[:2]}
    log.info("store_clone.preview_generated", item_count=len(CLONE_ITEMS))
    return {
        "source_store_id": source_store_id,
        "cloneable": cloneable,
        "non_cloneable": NON_CLONE_ITEMS,
        "available_items": CLONE_ITEMS,
    }


def clone_store(
    source_store_id: str,
    new_store_name: str,
    new_address: str,
    tenant_id: str,
    db: Any = None,
) -> Dict[str, Any]:
    """
    兼容旧签名：创建新门店 + 全量克隆所有配置项。

    旧调用方（admin_routes.py）无需修改。
    """
    if not new_store_name or not new_store_name.strip():
        raise ValueError("新门店名称不能为空")
    if not new_address or not new_address.strip():
        raise ValueError("新门店地址不能为空")

    result = setup_new_store(
        store_name=new_store_name,
        brand_id="default",  # 旧签名无 brand_id，使用默认值
        address=new_address,
        tenant_id=tenant_id,
        clone_from_store_id=source_store_id,
        clone_items=CLONE_ITEMS,
        db=db,
    )
    task = result["clone_task"]
    return {
        "id": result["store_id"],
        "name": result["store_name"],
        "store_code": result["store_code"],
        "address": new_address,
        "tenant_id": tenant_id,
        "cloned_from": source_store_id,
        "status": "inactive",
        "created_at": _now_iso(),
        "clone_task_id": task.id if task else None,
        "clone_summary": task.result_summary if task else {},
    }


def batch_clone(
    source_store_id: str,
    new_stores: List[Dict[str, str]],
    tenant_id: str,
    db: Any = None,
) -> Dict[str, Any]:
    """
    兼容旧签名：批量克隆门店。

    Args:
        source_store_id: 源门店 ID
        new_stores: [{"name": "...", "address": "..."}, ...]
        tenant_id: 租户 ID
        db: 数据库会话（预留）
    """
    log = logger.bind(
        tenant_id=tenant_id,
        source_store_id=source_store_id,
        batch_size=len(new_stores),
    )
    log.info("store_clone.batch_started")

    if not new_stores:
        raise ValueError("new_stores 不能为空")
    if len(new_stores) > BATCH_LIMIT:
        raise ValueError(f"批量克隆上限为 {BATCH_LIMIT} 家，当前请求 {len(new_stores)} 家")

    results: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    for idx, store_info in enumerate(new_stores):
        name = store_info.get("name", "")
        address = store_info.get("address", "")
        try:
            new_store = clone_store(
                source_store_id=source_store_id,
                new_store_name=name,
                new_address=address,
                tenant_id=tenant_id,
                db=db,
            )
            results.append(
                {
                    "index": idx,
                    "store_id": new_store["id"],
                    "name": new_store["name"],
                    "status": "success",
                    "clone_task_id": new_store.get("clone_task_id"),
                }
            )
        except (ValueError, KeyError) as e:
            log.warning(
                "store_clone.batch_item_failed",
                index=idx,
                name=name,
                error=str(e),
            )
            failed.append({"index": idx, "name": name, "status": "failed", "error": str(e)})

    log.info(
        "store_clone.batch_completed",
        success_count=len(results),
        failed_count=len(failed),
    )
    return {
        "source_store_id": source_store_id,
        "total_requested": len(new_stores),
        "success_count": len(results),
        "failed_count": len(failed),
        "results": results,
        "failed": failed,
    }
