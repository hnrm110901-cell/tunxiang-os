"""商户交付评分卡 API — 四月交付计划门店就绪度评估

端点：
  GET /api/v1/analytics/delivery-scorecard                   — 三商户总览
  GET /api/v1/analytics/delivery-scorecard/{merchant_code}   — 单商户详细评分

评分维度（满分100）：
  功能完整度 40分  — 核心API可用 / 前端路由 / 打印 / KDS / 会员功能
  数据质量   25分  — 菜单数据 / 会员数据 / 历史订单 / KPI基线
  性能       15分  — P99延迟 / 并发 / 离线可用
  演示就绪度 20分  — 种子数据 / 演示账号 / 打印机联通 / 健康检查

商户代码：czyz（尝在一起）/ zqx（最黔线）/ sgc（尚宫厨）
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/v1/analytics/delivery-scorecard", tags=["delivery-scorecard"])

# ─── 商户基础信息 ─────────────────────────────────────────────────────────────

MERCHANT_INFO: dict[str, dict[str, str]] = {
    "czyz": {
        "name":    "尝在一起",
        "brand":   "品智POS",
        "focus":   "翻台率→桌台周转优化",
        "contact": "czyz门店演示",
    },
    "zqx": {
        "name":    "最黔线",
        "brand":   "最黔线",
        "focus":   "复购率→会员运营深度",
        "contact": "zqx门店演示",
    },
    "sgc": {
        "name":    "尚宫厨",
        "brand":   "尚宫厨",
        "focus":   "宴会定金率→宴席管理",
        "contact": "sgc门店演示",
    },
}

# ─── 评分维度权重定义 ──────────────────────────────────────────────────────────
# 每个维度包含子项清单（item, weight, notes模板）

CATEGORY_DEFINITIONS: list[dict[str, Any]] = [
    {
        "category": "功能完整度",
        "total_weight": 40.0,
        "items": [
            {"item": "核心API可用（收银/订单/会员接口正常响应）", "weight": 12.0},
            {"item": "前端路由可访问（POS/KDS/Admin/Crew 四端）", "weight": 10.0},
            {"item": "打印功能（厨打单 + 收银小票）",             "weight": 8.0},
            {"item": "KDS出餐屏功能（排队/催菜/完成核销）",       "weight": 5.0},
            {"item": "会员功能（积分/储值卡/优惠券核销）",         "weight": 5.0},
        ],
    },
    {
        "category": "数据质量",
        "total_weight": 25.0,
        "items": [
            {"item": "菜单数据完整（菜品/价格/图片/BOM）",         "weight": 8.0},
            {"item": "会员数据存在（≥50条真实/模拟会员记录）",     "weight": 6.0},
            {"item": "历史订单数据（≥7天历史订单供驾驶舱展示）",   "weight": 7.0},
            {"item": "KPI基线数据（毛利率/翻台率/复购率基准值）",  "weight": 4.0},
        ],
    },
    {
        "category": "性能",
        "total_weight": 15.0,
        "items": [
            {"item": "P99延迟<500ms（核心收银路径）",              "weight": 6.0},
            {"item": "并发10用户无降级（模拟高峰期）",             "weight": 5.0},
            {"item": "离线可用（Mac mini断网本地PG继续服务）",     "weight": 4.0},
        ],
    },
    {
        "category": "演示就绪度",
        "total_weight": 20.0,
        "items": [
            {"item": "种子数据已加载（演示用菜单/会员/订单）",     "weight": 6.0},
            {"item": "演示账号可用（demo_admin + demo_cashier）",  "weight": 5.0},
            {"item": "打印机联通（厨打机 + 收银打印机 IP已配置）", "weight": 5.0},
            {"item": "健康检查通过（/api/v1/demo/health-check）",  "weight": 4.0},
        ],
    },
]

# ─── 各商户已知基线评分（硬编码，待实测后替换） ───────────────────────────────
# 格式：merchant_code → {category → raw_score (0-100)}

_BASELINE_SCORES: dict[str, dict[str, float]] = {
    "czyz": {
        "功能完整度": 85.0,
        "数据质量":   78.0,
        "性能":       90.0,
        "演示就绪度": 72.0,
    },
    "zqx": {
        "功能完整度": 80.0,
        "数据质量":   82.0,
        "性能":       88.0,
        "演示就绪度": 68.0,
    },
    "sgc": {
        "功能完整度": 75.0,
        "数据质量":   70.0,
        "性能":       85.0,
        "演示就绪度": 60.0,
    },
}

# ─── 风险提示模板（按商户特化） ───────────────────────────────────────────────

_RISK_TEMPLATES: dict[str, list[str]] = {
    "czyz": [
        "演示就绪度偏低：打印机联调待确认",
        "数据质量：历史订单数据量偏少，建议补充至14天",
        "翻台率指标依赖 dining_sessions 表数据完整性，需提前验证",
    ],
    "zqx": [
        "演示就绪度偏低：演示账号权限配置待核查",
        "功能完整度：会员复购分析页面加载时间需优化",
        "会员数据存量充足，复购率演示路径建议优先排练",
    ],
    "sgc": [
        "演示就绪度较低：种子数据、打印机联调均未完成",
        "功能完整度：宴会定金模块部分路由待 QA 验证",
        "数据质量：KPI基线数据缺失，建议使用行业均值占位",
        "建议将 sgc 排在三商户演示最后，给出更多准备时间",
    ],
}

_ACTION_TEMPLATES: dict[str, list[str]] = {
    "czyz": [
        "本周内完成打印机 IP 配置 + 联调测试（厨打机 + 收银机各1台）",
        "补充历史订单种子数据至 ≥14 天（scripts/seed_orders.py --days 14 --merchant czyz）",
        "在演示前一天运行完整演示流程（Dry Run），确认翻台率数据可视化正常",
    ],
    "zqx": [
        "核查 demo_admin / demo_cashier 账号权限，确保会员模块完整可见",
        "优化会员复购分析页面查询，目标 P99 < 300ms",
        "准备复购率对比图（本月 vs 上月），作为演示亮点",
    ],
    "sgc": [
        "优先完成种子数据加载（scripts/seed_demo.py --merchant sgc）",
        "宴会定金模块完成 QA 后，标记 demo-ready 并通知演示负责人",
        "用行业均值填充 KPI 基线（毛利率 58%、翻台率 2.5次/天）",
        "排练宴席预订→定金→尾款结算完整链路，确认无异常",
    ],
}


# ─── 计算函数 ─────────────────────────────────────────────────────────────────

def _grade(total_score: float) -> str:
    if total_score >= 90:
        return "A"
    if total_score >= 80:
        return "B+"
    if total_score >= 70:
        return "B"
    if total_score >= 60:
        return "C"
    return "D"


def _go_no_go(total_score: float, func_score: float) -> str:
    """≥75 总分 AND 功能完整度原始分≥70 → GO，否则 NO-GO"""
    return "GO" if total_score >= 75.0 and func_score >= 70.0 else "NO-GO"


def _build_scorecard(merchant_code: str) -> dict[str, Any]:
    baseline = _BASELINE_SCORES[merchant_code]
    info = MERCHANT_INFO[merchant_code]

    categories: list[dict[str, Any]] = []
    total_score = 0.0

    for cat_def in CATEGORY_DEFINITIONS:
        cat_name = cat_def["category"]
        raw_score = baseline[cat_name]          # 0-100 scale per category
        cat_weight = cat_def["total_weight"]    # contribution in final 100-pt scale
        weighted_contribution = raw_score * cat_weight / 100.0

        # Status emoji
        if raw_score >= 85:
            status = "✅"
        elif raw_score >= 70:
            status = "⚠️"
        else:
            status = "❌"

        # Build per-item breakdown (proportional to sub-weights)
        items_detail: list[dict[str, Any]] = []
        for item_def in cat_def["items"]:
            item_weight = item_def["weight"]
            # Assume uniform performance within category for baseline
            item_raw = raw_score
            item_status = status
            items_detail.append({
                "item":             item_def["item"],
                "weight_in_total":  round(item_weight, 2),
                "raw_score":        round(item_raw, 1),
                "status":           item_status,
            })

        categories.append({
            "category":              cat_name,
            "total_weight":          cat_weight,
            "raw_score":             round(raw_score, 1),
            "weighted_contribution": round(weighted_contribution, 2),
            "status":                status,
            "items":                 items_detail,
        })
        total_score += weighted_contribution

    func_raw = baseline["功能完整度"]
    grade = _grade(total_score)
    go_no_go = _go_no_go(total_score, func_raw)

    return {
        "merchant_code":        merchant_code,
        "merchant_name":        info["name"],
        "brand":                info["brand"],
        "focus_metric":         info["focus"],
        "total_score":          round(total_score, 1),
        "grade":                grade,
        "go_no_go":             go_no_go,
        "categories":           categories,
        "top_risks":            _RISK_TEMPLATES.get(merchant_code, []),
        "recommended_actions":  _ACTION_TEMPLATES.get(merchant_code, []),
        "assessed_at":          datetime.now(timezone.utc).isoformat(),
        "note":                 "当前评分为已知基线估算值，待实测数据接入后将自动替换",
    }


# ─── 端点 ─────────────────────────────────────────────────────────────────────

@router.get("", summary="获取三商户交付评分卡总览")
async def list_delivery_scorecards():
    """
    返回 czyz / zqx / sgc 三商户的交付就绪度评分卡汇总。
    包含总分、等级、GO/NO-GO 判断及最高风险项。
    四月交付演示专用 — Week 4 P0 验收物。
    """
    summaries = []
    for code in ["czyz", "zqx", "sgc"]:
        sc = _build_scorecard(code)
        summaries.append({
            "merchant_code":  sc["merchant_code"],
            "merchant_name":  sc["merchant_name"],
            "total_score":    sc["total_score"],
            "grade":          sc["grade"],
            "go_no_go":       sc["go_no_go"],
            "top_risk":       sc["top_risks"][0] if sc["top_risks"] else None,
            "assessed_at":    sc["assessed_at"],
        })

    overall_avg = round(sum(s["total_score"] for s in summaries) / len(summaries), 1)
    go_count = sum(1 for s in summaries if s["go_no_go"] == "GO")

    return {
        "ok": True,
        "data": {
            "summary": {
                "total_merchants": len(summaries),
                "go_count":        go_count,
                "no_go_count":     len(summaries) - go_count,
                "average_score":   overall_avg,
            },
            "merchants":   summaries,
            "assessed_at": datetime.now(timezone.utc).isoformat(),
        },
    }


@router.get("/{merchant_code}", summary="获取单商户交付评分卡详情")
async def get_delivery_scorecard(merchant_code: str):
    """
    返回指定商户的完整交付就绪度评分卡，包含：
    - 四个维度（功能完整度/数据质量/性能/演示就绪度）得分明细
    - 子项评分列表
    - GO/NO-GO 判定
    - 风险提示及行动建议
    """
    if merchant_code not in MERCHANT_INFO:
        raise HTTPException(
            status_code=404,
            detail=f"商户代码 {merchant_code!r} 不存在，有效代码：czyz / zqx / sgc",
        )

    scorecard = _build_scorecard(merchant_code)
    return {"ok": True, "data": scorecard}
