"""商户交付评分卡 — 四维度 100 分制评分

GET /api/v1/analytics/delivery-scorecard          — 三商户汇总
GET /api/v1/analytics/delivery-scorecard/{code}  — 单商户详情
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/analytics", tags=["delivery-scorecard"])

# ── 四维度基线评分（每次代码发布时手动更新） ──────────────────────────
# 维度权重：功能完整度40 + 数据质量25 + 性能15 + 演示就绪度20 = 100
_BASELINES: dict[str, dict[str, Any]] = {
    "czyz": {
        "merchant_name": "尝在一起·长沙五一店",
        "func_completeness": 88,  # /40 → 35.2
        "data_quality": 82,  # /25 → 20.5
        "performance": 90,  # /15 → 13.5
        "demo_readiness": 82,  # /20 → 16.4
        "details": {
            "func_completeness": {
                "收银/桌台/KDS": 100,
                "菜单管理": 95,
                "会员 CDP": 90,
                "库存预警": 85,
                "经营分析驾驶舱": 85,
                "Agent OS": 75,
                "日清日结 E1-E8": 70,
                "供应链采购": 65,
            },
            "data_quality": {
                "门店数据完整率": 95,
                "菜品数据完整率": 90,
                "会员数据完整率": 85,
                "历史订单数据": 75,
                "KPI权重配置": 90,
                "桌台数据": 90,
            },
            "performance": {
                "P99 响应时间": "< 800ms",
                "健康检查": "全绿",
                "并发 50 用户稳定": True,
            },
            "demo_readiness": {
                "演示导播手册": True,
                "种子数据已加载": True,
                "备用话术准备": True,
                "紧急回退脚本": True,
            },
        },
    },
    "zqx": {
        "merchant_name": "最黔线·长沙旗舰店",
        "func_completeness": 85,  # /40 → 34.0
        "data_quality": 78,  # /25 → 19.5
        "performance": 88,  # /15 → 13.2
        "demo_readiness": 78,  # /20 → 15.6
        "details": {
            "func_completeness": {
                "收银/桌台/KDS": 100,
                "菜单管理": 90,
                "会员 CDP": 90,
                "私域运营": 80,
                "经营分析驾驶舱": 80,
                "Agent OS": 70,
                "复购驱动营销": 75,
                "供应链采购": 60,
            },
            "data_quality": {
                "门店数据完整率": 90,
                "菜品数据完整率": 85,
                "会员数据完整率": 80,
                "历史订单数据": 70,
                "KPI权重配置": 90,
                "桌台数据": 85,
            },
            "performance": {
                "P99 响应时间": "< 900ms",
                "健康检查": "全绿",
                "并发 50 用户稳定": True,
            },
            "demo_readiness": {
                "演示导播手册": True,
                "种子数据已加载": True,
                "备用话术准备": True,
                "紧急回退脚本": True,
            },
        },
    },
    "sgc": {
        "merchant_name": "尚宫厨·长沙旗舰店",
        "func_completeness": 78,  # /40 → 31.2
        "data_quality": 72,  # /25 → 18.0
        "performance": 85,  # /15 → 12.75
        "demo_readiness": 72,  # /20 → 14.4
        "details": {
            "func_completeness": {
                "收银/桌台/KDS": 100,
                "菜单管理": 85,
                "宴会管理": 75,
                "会员 CDP": 75,
                "经营分析驾驶舱": 75,
                "Agent OS": 65,
                "供应链采购": 60,
                "财务结算": 60,
            },
            "data_quality": {
                "门店数据完整率": 85,
                "菜品数据完整率": 75,
                "会员数据完整率": 70,
                "历史订单数据": 65,
                "KPI权重配置": 85,
                "桌台数据": 80,
            },
            "performance": {
                "P99 响应时间": "< 1000ms",
                "健康检查": "全绿",
                "并发 50 用户稳定": True,
            },
            "demo_readiness": {
                "演示导播手册": True,
                "种子数据已加载": True,
                "备用话术准备": True,
                "紧急回退脚本": False,
            },
        },
    },
}


def _compute_score(code: str) -> dict[str, Any]:
    b = _BASELINES[code]
    func_score = round(b["func_completeness"] * 0.40, 1)
    data_score = round(b["data_quality"] * 0.25, 1)
    perf_score = round(b["performance"] * 0.15, 1)
    demo_score = round(b["demo_readiness"] * 0.20, 1)
    total = round(func_score + data_score + perf_score + demo_score, 1)

    if total >= 90:
        grade = "A"
    elif total >= 80:
        grade = "B+"
    elif total >= 70:
        grade = "B"
    elif total >= 60:
        grade = "C"
    else:
        grade = "D"

    go_nogo = "GO" if (total >= 75 and b["func_completeness"] >= 70) else "NO-GO"

    return {
        "merchant_code": code,
        "merchant_name": b["merchant_name"],
        "total_score": total,
        "grade": grade,
        "go_nogo": go_nogo,
        "dimensions": {
            "func_completeness": {
                "raw": b["func_completeness"],
                "weight": 0.40,
                "weighted": func_score,
            },
            "data_quality": {
                "raw": b["data_quality"],
                "weight": 0.25,
                "weighted": data_score,
            },
            "performance": {
                "raw": b["performance"],
                "weight": 0.15,
                "weighted": perf_score,
            },
            "demo_readiness": {
                "raw": b["demo_readiness"],
                "weight": 0.20,
                "weighted": demo_score,
            },
        },
        "details": b["details"],
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/delivery-scorecard")
async def list_delivery_scorecards():
    """三商户交付评分卡汇总"""
    results = [_compute_score(c) for c in ("czyz", "zqx", "sgc")]
    go_count = sum(1 for r in results if r["go_nogo"] == "GO")
    return {
        "ok": True,
        "data": {
            "merchants": results,
            "summary": {
                "total_merchants": 3,
                "go_count": go_count,
                "no_go_count": 3 - go_count,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            },
        },
    }


@router.get("/delivery-scorecard/{merchant_code}")
async def get_delivery_scorecard(merchant_code: str):
    """单商户交付评分卡详情"""
    if merchant_code not in _BASELINES:
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": f"Unknown merchant: {merchant_code}"}}
    return {"ok": True, "data": _compute_score(merchant_code)}
