"""
A5 差旅助手 Agent
=================
职责：监听 tx-ops 巡店任务事件，自动为督导生成差旅申请草稿。

核心逻辑：
  1. 收到 ops.inspection_task.assigned 事件
  2. 判断是否需要差旅（同城任务 <50km 不需要）
  3. 需要：调用 travel_expense_service.create_from_inspection_task() 生成草稿
  4. 通过 notification_service 通知督导"已为您生成差旅申请草稿，请确认"
  5. 不需要：记录日志，不操作

Agent 铁律：
  - 只生成草稿，不自动提交（督导本人确认后才提交）
  - 幂等保护：同一任务已有草稿时直接返回，不重复创建
  - 所有操作写入结构化日志，便于审计
  - 不直接操作资金，不修改审批流

量化目标：督导差旅手工填单率 100%→<10%，申请时效 次日→当日
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ..services import travel_expense_service as _travel_svc

log = structlog.get_logger(__name__)

# 同城判断阈值（公里）：行程距离低于此值视为同城，不生成差旅申请
SAME_CITY_THRESHOLD_KM = 50

# 已知同城城市对（小写），超出此列表时回退到城市名匹配
_SAME_CITY_ALIASES: dict[str, set[str]] = {
    "北京": {"北京市", "beijing"},
    "上海": {"上海市", "shanghai"},
    "广州": {"广州市", "guangzhou"},
    "深圳": {"深圳市", "shenzhen"},
}


# =============================================================================
# 核心判断：是否需要差旅
# =============================================================================

async def estimate_travel_needed(
    origin_city: str,
    destination_city: str,
) -> bool:
    """判断是否需要生成差旅申请（简单城市匹配，不调用地图API）。

    规则：
    - 出发城市与目的地城市相同（含别名匹配） → 不需要（同城任务）
    - 城市不同 → 需要差旅

    Returns:
        True  — 需要差旅（跨城）
        False — 不需要（同城）
    """
    if not origin_city or not destination_city:
        # 缺少城市信息，保守处理：需要差旅（让人工确认）
        return True

    origin_norm = origin_city.strip().lower()
    destination_norm = destination_city.strip().lower()

    # 直接相同
    if origin_norm == destination_norm:
        return False

    # 别名匹配（处理"北京" vs "北京市"等情况）
    for canonical, aliases in _SAME_CITY_ALIASES.items():
        canonical_norm = canonical.lower()
        all_variants = aliases | {canonical_norm}
        if origin_norm in all_variants and destination_norm in all_variants:
            return False

    # 城市名包含关系（如"成都" in "成都市"）
    if origin_norm in destination_norm or destination_norm in origin_norm:
        return False

    return True


# =============================================================================
# 事件处理：巡店任务分配
# =============================================================================

async def handle_inspection_task_assigned(
    event_data: dict,
    db: AsyncSession,
) -> Optional[dict]:
    """处理巡店任务分配事件，自动生成差旅申请草稿。

    event_data 结构（来自 tx-ops 巡店任务事件）：
        tenant_id (str)            - 租户ID
        task_id (str)              - 巡店任务ID
        supervisor_id (str)        - 分配到的督导员工ID
        brand_id (str)             - 品牌ID
        store_id (str)             - 督导所属门店ID（申请人所在门店）
        origin_city (str)          - 督导所在城市
        target_stores (list[dict]) - 目标巡店门店列表，每个元素含：
                                       store_id, store_name, city
        planned_start_date (str)   - 计划开始日期 (YYYY-MM-DD)
        planned_end_date (str)     - 计划结束日期 (YYYY-MM-DD, 可选)
        transport_mode (str)       - 交通方式（可选）
        notes (str)                - 备注（可选）

    Returns:
        dict 包含处理结果，或 None（同城跳过时）。
    """
    tenant_id_str: str = event_data.get("tenant_id", "")
    task_id_str: str = event_data.get("task_id", "")
    supervisor_id_str: str = event_data.get("supervisor_id", "")

    event_log = log.bind(
        tenant_id=tenant_id_str,
        task_id=task_id_str,
        supervisor_id=supervisor_id_str,
        agent="a5_travel_assistant",
    )

    # 必填字段校验
    if not tenant_id_str or not task_id_str or not supervisor_id_str:
        event_log.error(
            "a5_event_missing_required_fields",
            missing_fields=[k for k in ("tenant_id", "task_id", "supervisor_id") if not event_data.get(k)],
        )
        return None

    try:
        tenant_id = uuid.UUID(tenant_id_str)
    except ValueError:
        event_log.error("a5_invalid_tenant_id", tenant_id=tenant_id_str)
        return None

    # 判断是否需要差旅（同城任务跳过）
    origin_city: str = event_data.get("origin_city", "")
    target_stores: list[dict] = event_data.get("target_stores", [])
    destination_cities = list({s.get("city", "") for s in target_stores if s.get("city")})
    primary_destination = destination_cities[0] if destination_cities else ""

    travel_needed = await estimate_travel_needed(origin_city, primary_destination)

    if not travel_needed:
        event_log.info(
            "a5_travel_not_needed_same_city",
            origin_city=origin_city,
            destination_city=primary_destination,
            threshold_km=SAME_CITY_THRESHOLD_KM,
        )
        return {
            "action": "skipped",
            "reason": "same_city",
            "origin_city": origin_city,
            "destination_city": primary_destination,
        }

    # 构建 task_data 传递给 travel_expense_service
    task_data = {
        "task_id": task_id_str,
        "supervisor_id": supervisor_id_str,
        "brand_id": event_data.get("brand_id", ""),
        "store_id": event_data.get("store_id", ""),
        "target_stores": target_stores,
        "departure_city": origin_city,
        "planned_start_date": event_data.get("planned_start_date", ""),
        "planned_end_date": event_data.get("planned_end_date", event_data.get("planned_start_date", "")),
        "transport_mode": event_data.get("transport_mode", "train"),
        "notes": event_data.get("notes"),
    }

    # 创建差旅申请草稿（幂等）
    try:
        travel_request = await _travel_svc.create_from_inspection_task(
            db=db,
            tenant_id=tenant_id,
            task_data=task_data,
        )
        await db.commit()
    except ValueError as exc:
        event_log.error(
            "a5_create_draft_failed_validation",
            error=str(exc),
            task_data_keys=list(task_data.keys()),
        )
        return {"action": "error", "reason": str(exc)}
    except Exception as exc:
        event_log.error(
            "a5_create_draft_failed",
            error=f"{type(exc).__name__}: {exc}",
            exc_info=True,
        )
        return {"action": "error", "reason": str(exc)}

    event_log.info(
        "a5_travel_draft_created",
        request_id=str(travel_request.id),
        request_status=travel_request.status,
        planned_days=travel_request.planned_days,
        origin_city=origin_city,
        destination_cities=destination_cities,
    )

    # 通知督导：已生成差旅申请草稿
    await _notify_supervisor_draft_created(
        db=db,
        tenant_id=tenant_id,
        supervisor_id_str=supervisor_id_str,
        travel_request=travel_request,
        brand_id_str=event_data.get("brand_id", ""),
        destination_cities=destination_cities,
        event_log=event_log,
    )

    return {
        "action": "created",
        "request_id": str(travel_request.id),
        "status": travel_request.status,
        "planned_days": travel_request.planned_days,
        "destination_cities": destination_cities,
    }


async def _notify_supervisor_draft_created(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supervisor_id_str: str,
    travel_request: Any,
    brand_id_str: str,
    destination_cities: list[str],
    event_log: Any,
) -> None:
    """通知督导差旅申请草稿已创建。

    通知失败不影响主流程（旁路通知，降级处理）。
    """
    try:
        from ..services import notification_service as _notif_svc

        supervisor_id = uuid.UUID(supervisor_id_str)
        brand_id = uuid.UUID(brand_id_str) if brand_id_str else travel_request.brand_id

        dest_str = "、".join(destination_cities[:3])
        if len(destination_cities) > 3:
            dest_str += f" 等{len(destination_cities)}个城市"

        # 使用通用通知接口
        await _notif_svc.send_notification(
            db=db,
            tenant_id=tenant_id,
            application_id=travel_request.id,
            recipient_id=supervisor_id,
            recipient_role="traveler",
            event_type="travel_draft_created",
            application_title=f"差旅申请草稿 · {dest_str}",
            applicant_name="系统（A5差旅助手）",
            total_amount=travel_request.estimated_cost_fen or 0,
            store_name=dest_str,
            brand_id=brand_id,
            comment=(
                f"A5差旅助手已根据您的巡店任务自动生成差旅申请草稿，"
                f"计划 {travel_request.planned_days} 天，"
                f"目的地：{dest_str}。"
                "请登录费控系统确认申请内容后提交审批。"
            ),
        )
        event_log.info(
            "a5_supervisor_notification_sent",
            supervisor_id=supervisor_id_str,
            request_id=str(travel_request.id),
        )
    except (ImportError, AttributeError) as exc:
        # notification_service 未配置或接口不匹配，记录警告但不阻断
        event_log.warning(
            "a5_notification_skipped",
            reason="notification_service_unavailable",
            error=str(exc),
        )
    except Exception as exc:
        # 通知失败不影响主流程
        event_log.error(
            "a5_notification_failed",
            error=f"{type(exc).__name__}: {exc}",
            supervisor_id=supervisor_id_str,
            exc_info=True,
        )


# =============================================================================
# Agent 主入口
# =============================================================================

async def run(
    event_type: str,
    event_data: dict,
    db: AsyncSession,
) -> Optional[dict]:
    """A5 差旅助手 Agent 主入口（事件路由）。

    支持的事件类型：
        - ops.inspection_task.assigned   巡店任务分配给督导

    其他事件类型：记录日志后忽略。

    Returns:
        处理结果 dict，或 None（不支持的事件类型）。
    """
    agent_log = log.bind(
        agent="a5_travel_assistant",
        event_type=event_type,
        task_id=event_data.get("task_id"),
        tenant_id=event_data.get("tenant_id"),
    )

    if event_type == "ops.inspection_task.assigned":
        agent_log.info("a5_event_received")
        return await handle_inspection_task_assigned(event_data=event_data, db=db)

    # 不支持的事件类型，忽略
    agent_log.debug("a5_event_ignored", reason="unsupported_event_type")
    return None
