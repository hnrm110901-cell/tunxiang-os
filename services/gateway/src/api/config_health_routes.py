"""
配置健康度检查 API（上线前门控）

在正式上线前，通过一系列检查项验证租户配置的完整性和一致性，
给出 0-100 分的健康度评分。

评分规则：
  - critical 检查（每项 20 分，共 5 项）：任一失败即无法上线
  - important 检查（每项 6 分，共 5 项）：影响体验但不阻断
  - advisory 检查（每项 4 分，共 5 项）：建议项

总分 ≥ 90 且 critical 全通过 → 允许上线
总分 60-89 → 发出警告
总分 < 60 → 严重问题，阻断上线

端点：
  GET  /api/v1/config/health/{tenant_id}         — 运行全量健康检查
  GET  /api/v1/config/health/{tenant_id}/summary — 摘要（给前端上线按钮用）
  POST /api/v1/config/health/{tenant_id}/fix-hint — 返回修复建议
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from ..response import ok as ok_response

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/config", tags=["config-health"])


# ── 检查项定义 ────────────────────────────────────────────────────────

class CheckResult(BaseModel):
    check_id: str
    name: str
    severity: str          # critical | important | advisory
    status: str            # pass | fail | warn | skip
    score_earned: int
    score_max: int
    message: str
    fix_hint: str = ""


class HealthReport(BaseModel):
    tenant_id: str
    overall_score: int      # 0-100
    go_live_ready: bool     # score ≥ 90 且无 critical fail
    checks: list[CheckResult]
    critical_fails: list[str]
    warnings: list[str]
    advice: list[str]
    checked_at: str


# ── 检查项实现 ────────────────────────────────────────────────────────


async def _check_printer_configured(tenant_id: str, db) -> CheckResult:
    """至少配置一台收银打印机"""
    from sqlalchemy import text

    result = await db.execute(text(
        "SELECT COUNT(*) FROM printer_configs "
        "WHERE tenant_id = :tid AND printer_type = 'receipt' AND is_deleted = FALSE"
    ), {"tid": tenant_id})
    count = result.scalar() or 0
    ok = count >= 1
    return CheckResult(
        check_id="printer_receipt",
        name="收银打印机已配置",
        severity="critical",
        status="pass" if ok else "fail",
        score_earned=20 if ok else 0,
        score_max=20,
        message=f"找到 {count} 台收银打印机" if ok else "未找到收银打印机",
        fix_hint="" if ok else "在设备管理→打印机中添加至少一台收银打印机，填写 IP 地址",
    )


async def _check_shift_configured(tenant_id: str, db) -> CheckResult:
    """至少配置一个营业班次"""
    from sqlalchemy import text

    result = await db.execute(text(
        "SELECT COUNT(*) FROM shift_configs "
        "WHERE tenant_id = :tid AND is_deleted = FALSE"
    ), {"tid": tenant_id})
    count = result.scalar() or 0
    ok = count >= 1
    return CheckResult(
        check_id="shift_config",
        name="营业班次已配置",
        severity="critical",
        status="pass" if ok else "fail",
        score_earned=20 if ok else 0,
        score_max=20,
        message=f"找到 {count} 个营业班次" if ok else "未配置营业班次",
        fix_hint="" if ok else "在系统设置→营业时段中添加午市/晚市班次",
    )


async def _check_payment_methods(tenant_id: str, db, *, tenant_config=None) -> CheckResult:
    """至少配置一种支付方式"""
    has_config = tenant_config is not None
    return CheckResult(
        check_id="payment_methods",
        name="支付方式已配置",
        severity="critical",
        status="pass" if has_config else "fail",
        score_earned=20 if has_config else 0,
        score_max=20,
        message="支付方式配置已写入" if has_config else "未找到支付方式配置",
        fix_hint="" if has_config else "请重新运行上线交付向导（onboarding）完成配置",
    )


async def _check_kds_zone(tenant_id: str, db, *, tenant_config=None) -> CheckResult:
    """已配置 KDS 分区（非快餐业态必须）"""
    from sqlalchemy import text

    rt = (tenant_config.get("restaurant_type") if tenant_config else None) or "casual_dining"

    # 快餐可以没有专门的KDS分区（用出品台就够了）
    if rt == "fast_food":
        return CheckResult(
            check_id="kds_zone",
            name="KDS分区配置",
            severity="important",
            status="skip",
            score_earned=6,
            score_max=6,
            message="快餐业态：KDS分区可选，跳过检查",
        )

    result2 = await db.execute(text(
        "SELECT COUNT(*) FROM kds_display_rules WHERE tenant_id = :tid AND is_deleted = FALSE"
    ), {"tid": tenant_id})
    count = result2.scalar() or 0
    ok = count >= 1

    return CheckResult(
        check_id="kds_zone",
        name="KDS出餐分区已配置",
        severity="important",
        status="pass" if ok else "warn",
        score_earned=6 if ok else 0,
        score_max=6,
        message=f"已配置 {count} 个KDS分区" if ok else "未配置KDS分区，厨房将无法正常显示出品任务",
        fix_hint="" if ok else "在设备管理→KDS设置中添加厨房分区（如：炒锅档、凉菜档）",
    )


async def _check_agent_policy(tenant_id: str, db, *, tenant_config=None) -> CheckResult:
    """折扣守护 Agent 策略已初始化"""
    has_policy = bool(tenant_config and tenant_config.get("agent_policies"))

    return CheckResult(
        check_id="agent_policy",
        name="折扣守护Agent策略已初始化",
        severity="critical",
        status="pass" if has_policy else "fail",
        score_earned=20 if has_policy else 0,
        score_max=20,
        message="折扣守护Agent策略已配置" if has_policy else "折扣守护Agent策略未初始化",
        fix_hint="" if has_policy else "请完成上线交付向导，系统将自动初始化Agent策略",
    )


async def _check_member_tier(tenant_id: str, db) -> CheckResult:
    """会员体系已配置"""
    from sqlalchemy import text

    result = await db.execute(text(
        "SELECT COUNT(*) FROM member_tiers WHERE tenant_id = :tid AND is_deleted = FALSE"
    ), {"tid": tenant_id})
    count = result.scalar() or 0
    ok = count >= 1
    return CheckResult(
        check_id="member_tier",
        name="会员等级已配置",
        severity="important",
        status="pass" if ok else "warn",
        score_earned=6 if ok else 3,  # 未配置扣半分
        score_max=6,
        message=f"已配置 {count} 个会员等级" if ok else "未配置会员等级，会员系统将使用默认设置",
        fix_hint="" if ok else "在会员管理→等级设置中配置会员等级和积分规则",
    )


async def _check_menu_exists(tenant_id: str, db) -> CheckResult:
    """菜品库非空（至少有1道菜）"""
    from sqlalchemy import text

    result = await db.execute(text(
        "SELECT COUNT(*) FROM dishes WHERE tenant_id = :tid AND is_deleted = FALSE"
    ), {"tid": tenant_id})
    count = result.scalar() or 0
    ok = count >= 1
    return CheckResult(
        check_id="menu_not_empty",
        name="菜品库非空",
        severity="critical",
        status="pass" if ok else "fail",
        score_earned=20 if ok else 0,
        score_max=20,
        message=f"已录入 {count} 道菜品" if ok else "菜品库为空，无法正常开台收银",
        fix_hint="" if ok else "请在菜品管理中录入菜品，或从天财/品智导入菜品数据",
    )


async def _check_store_configured(tenant_id: str, db) -> CheckResult:
    """门店主数据已配置"""
    from sqlalchemy import text

    result = await db.execute(text(
        "SELECT COUNT(*) FROM stores WHERE tenant_id = :tid AND is_deleted = FALSE"
    ), {"tid": tenant_id})
    count = result.scalar() or 0
    ok = count >= 1
    return CheckResult(
        check_id="store_configured",
        name="门店主数据已配置",
        severity="important",
        status="pass" if ok else "warn",
        score_earned=6 if ok else 0,
        score_max=6,
        message=f"已配置 {count} 个门店" if ok else "门店主数据未配置",
        fix_hint="" if ok else "在组织管理→门店中录入门店信息",
    )


async def _check_table_configured(tenant_id: str, db, *, tenant_config=None) -> CheckResult:
    """桌台已配置（非快餐必须）"""
    from sqlalchemy import text

    rt = (tenant_config.get("restaurant_type") if tenant_config else None) or "casual_dining"

    if rt == "fast_food":
        return CheckResult(
            check_id="table_configured",
            name="桌台配置",
            severity="advisory",
            status="skip",
            score_earned=4,
            score_max=4,
            message="快餐业态：桌台配置可选，跳过检查",
        )

    result2 = await db.execute(text(
        "SELECT COUNT(*) FROM tables WHERE tenant_id = :tid AND is_deleted = FALSE"
    ), {"tid": tenant_id})
    count = result2.scalar() or 0
    ok = count >= 1

    return CheckResult(
        check_id="table_configured",
        name="桌台已配置",
        severity="advisory",
        status="pass" if ok else "warn",
        score_earned=4 if ok else 0,
        score_max=4,
        message=f"已配置 {count} 张桌台" if ok else "未配置桌台，开台功能不可用",
        fix_hint="" if ok else "在门店管理→桌台管理中配置桌台布局",
    )


async def _check_employee_exists(tenant_id: str, db) -> CheckResult:
    """至少有一名员工账号"""
    from sqlalchemy import text

    result = await db.execute(text(
        "SELECT COUNT(*) FROM employees WHERE tenant_id = :tid AND is_deleted = FALSE"
    ), {"tid": tenant_id})
    count = result.scalar() or 0
    ok = count >= 1
    return CheckResult(
        check_id="employee_exists",
        name="员工账号已创建",
        severity="advisory",
        status="pass" if ok else "warn",
        score_earned=4 if ok else 0,
        score_max=4,
        message=f"已创建 {count} 名员工账号" if ok else "尚未创建员工账号",
        fix_hint="" if ok else "在员工管理中创建收银员和店长账号",
    )


# ── 路由 ──────────────────────────────────────────────────────────────


@router.get("/health/{tenant_id}")
async def get_health_report(
    tenant_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """
    运行全量配置健康度检查，返回详细报告。

    score ≥ 90 且 critical_fails 为空 → go_live_ready = true
    """
    if x_tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="X-Tenant-ID 与路径 tenant_id 不匹配")

    from datetime import datetime, timezone

    checks = await _run_all_checks(tenant_id)

    total_earned = sum(c.score_earned for c in checks)
    total_max = sum(c.score_max for c in checks)
    # 对100分制做归一化
    overall_score = round(total_earned / total_max * 100) if total_max > 0 else 0

    critical_fails = [
        c.name for c in checks
        if c.severity == "critical" and c.status == "fail"
    ]
    warnings = [
        c.message for c in checks
        if c.status in ("fail", "warn") and c.severity != "critical"
    ]
    advice = [
        c.fix_hint for c in checks
        if c.fix_hint and c.status in ("fail", "warn")
    ]

    go_live_ready = overall_score >= 90 and len(critical_fails) == 0

    report = HealthReport(
        tenant_id=tenant_id,
        overall_score=overall_score,
        go_live_ready=go_live_ready,
        checks=checks,
        critical_fails=critical_fails,
        warnings=warnings,
        advice=advice,
        checked_at=datetime.now(tz=timezone.utc).isoformat(),
    )

    logger.info(
        "config_health_checked",
        tenant_id=tenant_id,
        score=overall_score,
        go_live_ready=go_live_ready,
        critical_fails=critical_fails,
    )

    return ok_response(report.model_dump())


@router.get("/health/{tenant_id}/summary")
async def get_health_summary(
    tenant_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """
    轻量健康度摘要（给前端「立即上线」按钮使用）。

    返回：{ go_live_ready, score, blocking_issues }
    """
    if x_tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="X-Tenant-ID 与路径 tenant_id 不匹配")

    checks = await _run_all_checks(tenant_id)
    total_earned = sum(c.score_earned for c in checks)
    total_max = sum(c.score_max for c in checks)
    overall_score = round(total_earned / total_max * 100) if total_max > 0 else 0

    blocking = [
        {"check": c.name, "fix_hint": c.fix_hint}
        for c in checks
        if c.severity == "critical" and c.status == "fail"
    ]

    return ok_response({
        "tenant_id": tenant_id,
        "score": overall_score,
        "go_live_ready": overall_score >= 90 and len(blocking) == 0,
        "blocking_issues": blocking,
    })


# ── 检查执行器 ────────────────────────────────────────────────────────


ALL_CHECKS = [
    _check_printer_configured,
    _check_shift_configured,
    _check_payment_methods,
    _check_agent_policy,
    _check_menu_exists,
    _check_member_tier,
    _check_kds_zone,
    _check_store_configured,
    _check_table_configured,
    _check_employee_exists,
]


_CHECKS_USING_TENANT_CONFIG = {"_check_payment_methods", "_check_agent_policy", "_check_kds_zone", "_check_table_configured"}


async def _run_all_checks(tenant_id: str) -> list[CheckResult]:
    """执行所有检查项，DB 不可用时返回跳过结果。"""
    try:
        from shared.ontology.src.database import async_session_factory
        from sqlalchemy import text

        async with async_session_factory() as db:
            await db.execute(text("SET app.tenant_id = :tid"), {"tid": tenant_id})

            # 预取 tenant_agent_configs（4 个检查项共用，避免重复查询）
            tac_row = await db.execute(text(
                "SELECT restaurant_type, agent_policies, billing_rules "
                "FROM tenant_agent_configs WHERE tenant_id = :tid LIMIT 1"
            ), {"tid": tenant_id})
            tac = tac_row.fetchone()
            tenant_config = {
                "restaurant_type": tac[0],
                "agent_policies": tac[1],
                "billing_rules": tac[2],
            } if tac else None

            results = []
            for check_fn in ALL_CHECKS:
                try:
                    if check_fn.__name__ in _CHECKS_USING_TENANT_CONFIG:
                        results.append(await check_fn(tenant_id, db, tenant_config=tenant_config))
                    else:
                        results.append(await check_fn(tenant_id, db))
                except Exception as exc:  # noqa: BLE001 — 单项检查失败不阻塞其他项
                    logger.warning(
                        "health_check_item_error",
                        check=check_fn.__name__,
                        error=str(exc),
                    )
                    results.append(CheckResult(
                        check_id=check_fn.__name__,
                        name=check_fn.__name__,
                        severity="advisory",
                        status="skip",
                        score_earned=0,
                        score_max=4,
                        message=f"检查执行失败: {exc}",
                    ))
            return results

    except Exception as exc:  # noqa: BLE001 — DB 不可用时全部跳过
        logger.error("health_check_db_unavailable", error=str(exc), exc_info=True)
        return [
            CheckResult(
                check_id="db_connection",
                name="数据库连接",
                severity="critical",
                status="fail",
                score_earned=0,
                score_max=100,
                message=f"数据库不可用: {exc}",
                fix_hint="请检查数据库连接配置",
            )
        ]
