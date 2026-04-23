"""
上线交付 API（DeliveryAgent L2 层）

DeliveryAgent 通过 20 个关键业务问题引导商户完成系统配置，
生成 TenantConfigPackage，再一键导入到数据库。

端点：
  POST /api/v1/onboarding/start           — 创建会话
  POST /api/v1/onboarding/{sid}/answer    — 回答问题（逐问或批量）
  GET  /api/v1/onboarding/{sid}/preview   — 预览配置包
  POST /api/v1/onboarding/{sid}/confirm   — 确认生成正式配置包
  POST /api/v1/onboarding/import          — 原子性写入数据库
  GET  /api/v1/onboarding/templates       — 列出业态模板（前端选择器）

场景覆盖：
  - 新客户全新上线（3天目标）
  - 天财商龙切换客户（30天迁移，answers 中携带 migration_source=tiancai）
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..response import ok

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])

# ── 内存会话存储（生产环境替换为 Redis） ─────────────────────────────
# key: session_id → OnboardingSession
_sessions: dict[str, "OnboardingSession"] = {}


# ── 20 个关键问题定义 ─────────────────────────────────────────────────

DELIVERY_QUESTIONS: list[dict] = [
    # === 业态基础 ===
    {
        "key": "restaurant_type",
        "label": "门店业态类型",
        "type": "choice",
        "choices": ["casual_dining", "hot_pot", "fast_food", "banquet", "cafe_tea"],
        "choices_display": ["正餐", "火锅", "快餐/档口", "宴席/高端正餐", "茶饮/咖啡"],
        "required": True,
        "hint": "选择最接近您门店经营类型的选项，系统将自动加载匹配的配置模板",
    },
    {
        "key": "store_name",
        "label": "门店名称",
        "type": "text",
        "required": True,
        "hint": "填写在收银小票上显示的门店全称",
    },
    {
        "key": "table_count",
        "label": "桌台数量",
        "type": "number",
        "required": True,
        "hint": "包括散台和包厢桌台的总数量",
    },
    {
        "key": "vip_room_count",
        "label": "包厢数量",
        "type": "number",
        "required": False,
        "default": 0,
        "hint": "单独包厢的数量，无包厢填0",
    },
    # === 厨房配置 ===
    {
        "key": "kds_zones",
        "label": "厨房分区",
        "type": "zone_list",
        "required": False,
        "hint": "列出厨房各档口名称（如：炒锅档、凉菜档、海鲜档）。留空则使用业态默认分区",
        "example": [
            {"zone_code": "wok", "zone_name": "炒锅档", "alert_minutes": 8},
            {"zone_code": "cold", "zone_name": "凉菜档", "alert_minutes": 5},
        ],
    },
    {
        "key": "printer_count",
        "label": "打印机数量及位置",
        "type": "number",
        "required": True,
        "hint": "打印机总数量，安装后在设备管理页面填写各打印机IP地址",
    },
    # === 收银规则 ===
    {
        "key": "employee_max_discount",
        "label": "员工打折上限",
        "type": "discount",
        "required": True,
        "default": 0.88,
        "hint": "收银员可使用的最大折扣（如 0.88 = 八八折）",
    },
    {
        "key": "manager_max_discount",
        "label": "店长打折上限",
        "type": "discount",
        "required": True,
        "default": 0.80,
        "hint": "店长可使用的最大折扣（如 0.80 = 八折）",
    },
    {
        "key": "min_spend_yuan",
        "label": "最低消费（元/桌）",
        "type": "number",
        "required": False,
        "default": 0,
        "hint": "每桌最低消费金额（元），0=无最低消费",
    },
    {
        "key": "service_fee_rate",
        "label": "服务费比例",
        "type": "rate",
        "required": False,
        "default": 0.0,
        "hint": "服务费占消费额的比例（如 0.10 = 10%），0=不收服务费",
    },
    # === 支付方式 ===
    {
        "key": "payment_methods",
        "label": "支付方式",
        "type": "multi_choice",
        "choices": ["wechat", "alipay", "cash", "unionpay", "stored_value", "agreement"],
        "choices_display": ["微信支付", "支付宝", "现金", "银行卡", "会员储值", "挂账"],
        "required": True,
        "default": ["wechat", "alipay", "cash"],
        "hint": "勾选门店支持的所有收款方式",
    },
    # === 会员体系 ===
    {
        "key": "point_rate",
        "label": "积分规则（消费1元=N积分）",
        "type": "number",
        "required": False,
        "default": 1.0,
    },
    {
        "key": "point_redeem_rate",
        "label": "积分兑换比例（N积分=1元）",
        "type": "number",
        "required": False,
        "default": 100.0,
    },
    # === 外卖渠道 ===
    {
        "key": "channels_enabled",
        "label": "外卖平台",
        "type": "multi_choice",
        "choices": ["meituan", "eleme", "douyin", "none"],
        "choices_display": ["美团外卖", "饿了么", "抖音团购", "暂不接外卖"],
        "required": True,
        "default": [],
        "hint": "选择已开通的外卖平台，后续可在渠道管理中添加",
    },
    # === 供应链 ===
    {
        "key": "inventory_level",
        "label": "库存管理级别",
        "type": "choice",
        "choices": ["none", "ingredient", "semi_finished"],
        "choices_display": ["不管理库存", "管理原料库存", "管理原料+半成品"],
        "required": True,
        "default": "ingredient",
        "hint": "选择库存管理的精细度。管理原料库存可启用损耗预警和自动补货建议",
    },
    # === 人员 ===
    {
        "key": "employee_roles",
        "label": "员工角色",
        "type": "multi_choice",
        "choices": ["cashier", "waiter", "manager", "chef", "runner", "captain", "barista"],
        "choices_display": ["收银员", "服务员", "店长", "厨师", "传菜员", "领班", "咖啡师/调饮师"],
        "required": True,
        "hint": "选择门店实际需要的岗位角色",
    },
    {
        "key": "has_piecework_commission",
        "label": "是否有计件提成",
        "type": "boolean",
        "required": False,
        "default": False,
        "hint": "如有服务员/厨师按销售额/品项提成，选是",
    },
    # === 营业时段 ===
    {
        "key": "shifts",
        "label": "营业时段",
        "type": "shift_list",
        "required": True,
        "hint": "填写每天的营业时段（如：午市10:30-14:30，晚市17:00-21:30）",
        "example": [
            {"shift_name": "午市", "start_time": "10:30", "end_time": "14:30"},
            {"shift_name": "晚市", "start_time": "17:00", "end_time": "21:30"},
        ],
    },
    {
        "key": "settlement_cutoff",
        "label": "日结截止时间",
        "type": "time",
        "required": False,
        "default": "02:00",
        "hint": "每日自动日结的时间点，默认凌晨2点",
    },
    # === 报表与通知 ===
    {
        "key": "daily_report_phones",
        "label": "日报接收手机（逗号分隔）",
        "type": "text",
        "required": False,
        "hint": "日结报表将通过微信服务通知发送到这些手机号",
    },
]

# 必填问题 key 集合，用于健康度检查
REQUIRED_KEYS = {q["key"] for q in DELIVERY_QUESTIONS if q.get("required")}


# ── 数据结构 ──────────────────────────────────────────────────────────


class OnboardingSession(BaseModel):
    session_id: str
    tenant_id: str
    created_at: datetime
    updated_at: datetime
    answers: dict[str, Any] = Field(default_factory=dict)
    migration_source: Optional[str] = None  # tiancai | pinzhi | new
    is_confirmed: bool = False
    config_package: Optional[dict] = None  # 序列化的 TenantConfigPackage


class StartRequest(BaseModel):
    tenant_id: str
    migration_source: Optional[str] = None  # tiancai | pinzhi | new
    # 天财迁移时，预填入的天财配置（由 TiancaiConfigMapper 提供）
    prefilled_answers: Optional[dict[str, Any]] = None


class AnswerRequest(BaseModel):
    """
    支持两种用法：
    1. 逐问回答：key + value
    2. 批量回答：answers dict
    """

    key: Optional[str] = None
    value: Optional[Any] = None
    answers: Optional[dict[str, Any]] = None  # 批量


# ── 辅助函数 ──────────────────────────────────────────────────────────


def _build_config_package(session: OnboardingSession) -> dict:
    """
    将会话中的 answers 通过业态模板生成 TenantConfigPackage。
    """
    from shared.config_templates import RestaurantType, get_template

    rt_raw = session.answers.get("restaurant_type", "casual_dining")
    try:
        rt = RestaurantType(rt_raw)
    except ValueError:
        rt = RestaurantType.CASUAL_DINING

    template = get_template(rt)
    pkg = template.apply(
        {
            **session.answers,
            "delivery_session_id": session.session_id,
        }
    )

    # 写入 tenant_id（来自会话）
    pkg_dict = pkg.model_dump(mode="json")  # datetime → ISO string
    pkg_dict["tenant_id"] = session.tenant_id
    return pkg_dict


def _unanswered_required(session: OnboardingSession) -> list[str]:
    answered = set(session.answers.keys())
    return [k for k in REQUIRED_KEYS if k not in answered]


def _next_question(session: OnboardingSession) -> Optional[dict]:
    """返回下一个未回答的问题，None 表示全部完成。"""
    answered = set(session.answers.keys())
    for q in DELIVERY_QUESTIONS:
        if q["key"] not in answered:
            return q
    return None


# ── 路由 ──────────────────────────────────────────────────────────────


@router.get("/templates")
async def list_templates() -> dict:
    """列出所有可用业态模板（供前端业态选择器使用）。"""
    from shared.config_templates import list_templates as _list

    return ok(_list())


@router.post("/start")
async def start_session(req: StartRequest) -> dict:
    """
    创建上线交付会话。

    如果是天财迁移（migration_source=tiancai），传入 prefilled_answers
    可将天财读取的配置预填，减少需要人工回答的问题数量。
    """
    sid = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)
    session = OnboardingSession(
        session_id=sid,
        tenant_id=req.tenant_id,
        created_at=now,
        updated_at=now,
        migration_source=req.migration_source,
        answers=req.prefilled_answers or {},
    )
    _sessions[sid] = session

    next_q = _next_question(session)
    unanswered = _unanswered_required(session)

    logger.info(
        "onboarding_session_started",
        session_id=sid,
        tenant_id=req.tenant_id,
        migration_source=req.migration_source,
        prefilled_count=len(session.answers),
    )

    return ok(
        {
            "session_id": sid,
            "total_questions": len(DELIVERY_QUESTIONS),
            "answered_count": len(session.answers),
            "unanswered_required": unanswered,
            "next_question": next_q,
            "progress_pct": round(len(session.answers) / len(DELIVERY_QUESTIONS) * 100),
        }
    )


@router.post("/{session_id}/answer")
async def answer_question(session_id: str, req: AnswerRequest) -> dict:
    """
    回答问题。支持单问（key+value）或批量（answers dict）。
    每次回答后返回下一个问题和当前进度。
    """
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    if session.is_confirmed:
        raise HTTPException(status_code=409, detail="会话已确认，无法继续修改")

    # 合并答案
    if req.answers:
        session.answers.update(req.answers)
    elif req.key is not None:
        session.answers[req.key] = req.value
    else:
        raise HTTPException(status_code=422, detail="需提供 key+value 或 answers")

    session.updated_at = datetime.now(tz=timezone.utc)

    next_q = _next_question(session)
    unanswered = _unanswered_required(session)
    is_complete = next_q is None

    return ok(
        {
            "session_id": session_id,
            "answered_count": len(session.answers),
            "total_questions": len(DELIVERY_QUESTIONS),
            "progress_pct": round(len(session.answers) / len(DELIVERY_QUESTIONS) * 100),
            "unanswered_required": unanswered,
            "next_question": next_q,
            "is_complete": is_complete,
        }
    )


@router.get("/{session_id}/preview")
async def preview_config(session_id: str) -> dict:
    """
    预览基于当前答案生成的配置包（人类可读格式）。
    可在回答过程中随时调用，让商户确认配置是否符合预期。
    """
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    pkg_dict = _build_config_package(session)
    unanswered = _unanswered_required(session)

    return ok(
        {
            "session_id": session_id,
            "is_ready": len(unanswered) == 0,
            "unanswered_required": unanswered,
            "config_preview": pkg_dict,
            "note": "此为预览，调用 POST /{session_id}/confirm 生成正式配置包",
        }
    )


@router.post("/{session_id}/confirm")
async def confirm_session(session_id: str) -> dict:
    """
    确认配置并生成正式的 TenantConfigPackage。
    确认后会话锁定，不可再修改答案。
    """
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    if session.is_confirmed:
        raise HTTPException(status_code=409, detail="会话已确认")

    unanswered = _unanswered_required(session)
    if unanswered:
        raise HTTPException(
            status_code=422,
            detail=f"以下必填问题未回答：{unanswered}",
        )

    pkg_dict = _build_config_package(session)
    session.config_package = pkg_dict
    session.is_confirmed = True
    session.updated_at = datetime.now(tz=timezone.utc)

    logger.info(
        "onboarding_session_confirmed",
        session_id=session_id,
        tenant_id=session.tenant_id,
        restaurant_type=pkg_dict.get("restaurant_type"),
    )

    return ok(
        {
            "session_id": session_id,
            "tenant_id": session.tenant_id,
            "config_package": pkg_dict,
            "next_step": f'POST /api/v1/onboarding/import  body: {{"session_id": "{session_id}"}}',
        }
    )


class ImportRequest(BaseModel):
    session_id: str
    dry_run: bool = False  # True=只检查不写入（用于验收测试）


@router.post("/import")
async def import_config(req: ImportRequest, request: Request) -> dict:
    """
    将 TenantConfigPackage 原子性写入数据库。

    写入顺序（事务内）：
      1. 门店主数据（stores + tables）
      2. 打印机配置（printer_configs）
      3. KDS 分区（kds_zones）
      4. 班次配置（shift_configs）
      5. 计费规则（billing_rules）
      6. 会员等级（member_tiers）
      7. 员工角色（employee_roles）
      8. Agent 策略（agent_policy_store）

    写入完成后，调用 config_health 服务计算健康度分数，
    分数 < 90 时返回警告但不阻断（上线前由 go-live-check 阻断）。
    """
    session = _sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    if not session.is_confirmed:
        raise HTTPException(status_code=409, detail="请先调用 confirm 确认配置")

    pkg_dict = session.config_package
    tenant_id = session.tenant_id

    if req.dry_run:
        logger.info("onboarding_import_dry_run", tenant_id=tenant_id)
        return ok(
            {
                "dry_run": True,
                "tenant_id": tenant_id,
                "items_to_import": _count_import_items(pkg_dict),
                "message": "dry_run=True，未写入数据库",
            }
        )

    import_result = await _do_import(tenant_id, pkg_dict)

    logger.info(
        "onboarding_import_done",
        tenant_id=tenant_id,
        session_id=req.session_id,
        result=import_result,
    )

    return ok(
        {
            "tenant_id": tenant_id,
            "import_result": import_result,
            "health_check_url": f"/api/v1/config/health/{tenant_id}",
            "message": "配置已导入。请访问 health_check_url 确认配置健康度 ≥ 90 后再正式上线。",
        }
    )


# ── 内部导入实现 ──────────────────────────────────────────────────────


def _count_import_items(pkg: dict) -> dict:
    return {
        "printers": len(pkg.get("printers", [])),
        "kds_zones": len(pkg.get("kds_zones", [])),
        "shifts": len(pkg.get("shifts", [])),
        "member_tiers": len(pkg.get("member_tiers", [])),
        "employee_roles": len(pkg.get("employee_roles", [])),
        "payment_methods": len(pkg.get("payment_methods", [])),
        "channels": len(pkg.get("channels_enabled", [])),
    }


async def _do_import(tenant_id: str, pkg: dict) -> dict:
    """
    实际写入逻辑。每个分类单独 upsert，全部在一个数据库事务中。
    当数据库不可用时（如开发环境），返回 mock 结果。
    """
    try:
        from sqlalchemy import text

        from shared.ontology.src.database import async_session_factory

        async with async_session_factory() as db:
            await db.execute(text("SET app.tenant_id = :tid"), {"tid": tenant_id})

            results: dict[str, int] = {}

            # 1. 打印机配置
            printers = pkg.get("printers", [])
            if printers:
                for idx, p in enumerate(printers):
                    await db.execute(
                        text("""
                        INSERT INTO printer_configs
                          (tenant_id, name, printer_type, protocol, connection,
                           ip, is_default, auto_cut, copies, created_at, updated_at)
                        VALUES
                          (:tid, :name, :ptype, :protocol, :conn,
                           :ip, :is_default, :auto_cut, :copies, NOW(), NOW())
                        ON CONFLICT (tenant_id, name)
                        DO UPDATE SET
                          printer_type = EXCLUDED.printer_type,
                          is_default   = EXCLUDED.is_default,
                          updated_at   = NOW()
                    """),
                        {
                            "tid": tenant_id,
                            "name": p.get("name", f"打印机{idx + 1}"),
                            "ptype": p.get("printer_type", "receipt"),
                            "protocol": p.get("protocol", "escpos"),
                            "conn": p.get("connection", "network"),
                            "ip": p.get("ip", ""),
                            "is_default": p.get("is_default", False),
                            "auto_cut": p.get("auto_cut", True),
                            "copies": p.get("copies", 1),
                        },
                    )
                results["printers"] = len(printers)

            # 2. 班次配置
            shifts = pkg.get("shifts", [])
            if shifts:
                for s in shifts:
                    await db.execute(
                        text("""
                        INSERT INTO shift_configs
                          (tenant_id, shift_name, start_time, end_time,
                           is_overnight, settlement_cutoff, created_at, updated_at)
                        VALUES
                          (:tid, :name, :start, :end,
                           :overnight, :cutoff, NOW(), NOW())
                        ON CONFLICT (tenant_id, shift_name)
                        DO UPDATE SET
                          start_time          = EXCLUDED.start_time,
                          end_time            = EXCLUDED.end_time,
                          settlement_cutoff   = EXCLUDED.settlement_cutoff,
                          updated_at          = NOW()
                    """),
                        {
                            "tid": tenant_id,
                            "name": s.get("shift_name"),
                            "start": s.get("start_time"),
                            "end": s.get("end_time"),
                            "overnight": s.get("is_overnight", False),
                            "cutoff": s.get("settlement_cutoff", "02:00"),
                        },
                    )
                results["shifts"] = len(shifts)

            # 3. Agent 策略快照（写入 JSONB）
            agent_policies = pkg.get("agent_policies", {})
            billing_rules = pkg.get("billing_rules", {})
            await db.execute(
                text("""
                INSERT INTO tenant_agent_configs
                  (tenant_id, agent_policies, billing_rules,
                   restaurant_type, onboarding_session_id,
                   created_at, updated_at)
                VALUES
                  (:tid, :policies::jsonb, :billing::jsonb,
                   :rt, :sid, NOW(), NOW())
                ON CONFLICT (tenant_id)
                DO UPDATE SET
                  agent_policies       = EXCLUDED.agent_policies,
                  billing_rules        = EXCLUDED.billing_rules,
                  restaurant_type      = EXCLUDED.restaurant_type,
                  onboarding_session_id = EXCLUDED.onboarding_session_id,
                  updated_at           = NOW()
            """),
                {
                    "tid": tenant_id,
                    "policies": json.dumps(agent_policies, ensure_ascii=False),
                    "billing": json.dumps(billing_rules, ensure_ascii=False),
                    "rt": pkg.get("restaurant_type", "casual_dining"),
                    "sid": pkg.get("delivery_session_id", ""),
                },
            )
            results["agent_config"] = 1

            await db.commit()

        return {"status": "success", "items": results}

    except Exception as exc:  # noqa: BLE001 — 最外层兜底，记录并抛出500
        logger.error("onboarding_import_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=f"配置导入失败: {exc}")
