"""A2UI Surface 生成器 — Sprint 3 S3-03

为 discount_guard / member_insight / inventory_alert 三个 Skill Agent 提供
A2UI v0.8 协议的 Surface 构造函数，让 Agent 输出从纯业务 JSON 升级为可直接
被 web-pos A2UIRenderer 渲染的 UI 声明。

设计原则：
  - 函数式构造（无状态、可独立测试）
  - 与 voice_order._build_*_surface 系列风格一致
  - severity 字段决定卡片视觉等级（critical/warning/info）
  - actionId 全部走 Agent 白名单（discount_guard.* / member.* / inventory.*）
  - 金额单位 **分**（整数），渲染层 fenToYuan 转换

返回格式（A2UI v0.8 spec）：
  {
    "surfaceId": str,
    "version": "0.8",
    "surface": {  # 根 A2UINode
      "id": ...,
      "type": "card",
      "props": {...},
      "children": [...]
    },
    "metadata": {
      "agentId": str,
      "confidence": float,
      "timestamp": ISO 8601
    }
  }
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def _surface_id(prefix: str) -> str:
    """生成 surface 唯一 ID（前缀-uuid8）"""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _now_iso() -> str:
    """当前时间 ISO 8601 字符串"""
    return datetime.now(timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────────────────────
# 1. 折扣守护 Agent — critical alert surface
# ──────────────────────────────────────────────────────────────────────────────

def build_discount_alert_surface(
    *,
    order_id: str,
    discount_rate: float,           # 0-1，如 0.352 = 35.2%
    margin_after_discount_fen: int,  # 折后毛利（分）
    margin_threshold_fen: int,       # 毛利底线（分）
    operator_id: str | None = None,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """折扣守护 critical alert：毛利已跌破底线时输出 critical 卡片 + approve/reject 操作。

    Args:
        order_id: 订单 ID
        discount_rate: 折扣率 (0-1)
        margin_after_discount_fen: 折后毛利（分，可负）
        margin_threshold_fen: 毛利底线（分）
        operator_id: 触发操作员 ID（用于决策留痕）
        confidence: 检测置信度 (0-1)
    """
    sid = _surface_id("disc-alert")
    breach_fen = margin_threshold_fen - margin_after_discount_fen

    return {
        "surfaceId": sid,
        "version": "0.8",
        "surface": {
            "id": f"{sid}-root",
            "type": "card",
            "props": {
                "title": "🚨 毛利底线告警",
                "subtitle": f"订单 {order_id}",
                "severity": "critical",
            },
            "children": [
                {
                    "id": f"{sid}-rate",
                    "type": "text",
                    "props": {
                        "content": f"当前折扣率 {discount_rate * 100:.1f}%，"
                                   f"折后毛利 ¥{margin_after_discount_fen / 100:.2f}",
                        "variant": "subheading",
                    },
                },
                {
                    "id": f"{sid}-breach",
                    "type": "text",
                    "props": {
                        "content": f"已突破毛利底线 ¥{margin_threshold_fen / 100:.2f}，"
                                   f"差额 ¥{breach_fen / 100:.2f}",
                        "color": "#EF4444",
                    },
                },
                {
                    "id": f"{sid}-actions",
                    "type": "actions",
                    "props": {
                        "buttons": [
                            {"label": "退回审核", "variant": "danger",
                             "action": "discount_guard.reject",
                             "actionPayload": {"order_id": order_id}},
                            {"label": "强制通过", "variant": "secondary",
                             "action": "discount_guard.approve",
                             "actionPayload": {"order_id": order_id, "operator_id": operator_id}},
                        ],
                    },
                },
            ],
        },
        "metadata": {
            "agentId": "discount_guard",
            "confidence": confidence,
            "timestamp": _now_iso(),
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# 2. 会员洞察 Agent — recommendation surface
# ──────────────────────────────────────────────────────────────────────────────

def build_member_recommendation_surface(
    *,
    member_id: str,
    member_name: str,
    member_level: str,                  # 钻石/金/银/普通
    last_visit_days: int,
    preferences: list[str],
    recommendations: list[dict[str, Any]],  # [{label, action, payload}]
    confidence: float = 0.85,
) -> dict[str, Any]:
    """会员洞察 recommendation：会员到店时提供画像 + AI 推荐操作。

    Args:
        member_id: 会员 ID
        member_name: 会员姓名/昵称
        member_level: 会员等级
        last_visit_days: 距上次到店天数
        preferences: 偏好标签（如 ['靠窗位', '少辣', '清蒸系']）
        recommendations: AI 推荐操作列表
        confidence: 推荐置信度
    """
    sid = _surface_id("member-rec")

    return {
        "surfaceId": sid,
        "version": "0.8",
        "surface": {
            "id": f"{sid}-root",
            "type": "card",
            "props": {
                "title": f"⭐ {member_level}会员 · {member_name}",
                "subtitle": f"距上次到店 {last_visit_days} 天",
                "severity": "info",
            },
            "children": [
                {
                    "id": f"{sid}-prefs",
                    "type": "list",
                    "props": {
                        "items": [
                            {"id": f"{sid}-pref-{i}", "title": pref}
                            for i, pref in enumerate(preferences)
                        ],
                    },
                },
                {
                    "id": f"{sid}-rec-text",
                    "type": "text",
                    "props": {
                        "content": "基于历史订单 + RFM 分层的推荐操作：",
                        "variant": "caption",
                    },
                },
                {
                    "id": f"{sid}-actions",
                    "type": "actions",
                    "props": {
                        "buttons": [
                            {
                                "label": rec["label"],
                                "variant": rec.get("variant", "secondary"),
                                "action": rec["action"],
                                "actionPayload": {
                                    "member_id": member_id,
                                    **rec.get("payload", {}),
                                },
                            }
                            for rec in recommendations
                        ],
                    },
                },
            ],
        },
        "metadata": {
            "agentId": "member_insight",
            "confidence": confidence,
            "timestamp": _now_iso(),
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# 3. 库存预警 Agent — warning surface
# ──────────────────────────────────────────────────────────────────────────────

def build_inventory_warning_surface(
    *,
    items: list[dict[str, Any]],  # [{name, remaining_qty, unit, expiry_minutes, severity}]
    confidence: float = 0.90,
) -> dict[str, Any]:
    """库存预警 warning：临期/即将沽清食材清单 + 一键安排补货。

    Args:
        items: 食材清单，每项含 name/remaining_qty/unit/expiry_minutes/severity
        confidence: 预测置信度
    """
    sid = _surface_id("inv-warn")

    # 决定整体严重等级（任一 critical → 整体 critical）
    severities = [item.get("severity", "warning") for item in items]
    overall_severity = "critical" if "critical" in severities else "warning"

    return {
        "surfaceId": sid,
        "version": "0.8",
        "surface": {
            "id": f"{sid}-root",
            "type": "card",
            "props": {
                "title": f"⚠ 库存预警（{len(items)} 项）",
                "severity": overall_severity,
            },
            "children": [
                {
                    "id": f"{sid}-table",
                    "type": "table",
                    "props": {
                        "columns": [
                            {"key": "name", "title": "食材", "align": "left"},
                            {"key": "remaining", "title": "剩余", "align": "right"},
                            {"key": "expiry", "title": "预计沽清", "align": "right"},
                        ],
                        "rows": [
                            {
                                "name": item["name"],
                                "remaining": f"{item.get('remaining_qty', 0)} {item.get('unit', '')}",
                                "expiry": (
                                    f"{item['expiry_minutes']} 分钟后"
                                    if item.get("expiry_minutes")
                                    else "-"
                                ),
                            }
                            for item in items
                        ],
                    },
                },
                {
                    "id": f"{sid}-actions",
                    "type": "actions",
                    "props": {
                        "buttons": [
                            {"label": "立即补货", "variant": "primary",
                             "action": "inventory.order_now",
                             "actionPayload": {"items": [item["name"] for item in items]}},
                            {"label": "稍后处理", "variant": "ghost",
                             "action": "inventory.snooze"},
                        ],
                    },
                },
            ],
        },
        "metadata": {
            "agentId": "inventory_alert",
            "confidence": confidence,
            "timestamp": _now_iso(),
        },
    }
