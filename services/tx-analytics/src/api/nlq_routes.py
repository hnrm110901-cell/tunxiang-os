"""
对话式经营助手 (NLQ Engine) — 对标 Toast IQ Conversational Assistant

端点：
  POST /api/v1/nlq/ask             — 自然语言提问（核心端点）
  GET  /api/v1/nlq/suggestions     — 推荐问题列表（基于当前时间+门店状态）
  GET  /api/v1/nlq/history         — 历史问答记录
  POST /api/v1/nlq/execute-action  — 执行AI建议的操作

流程:
  1. 意图识别（50个预设模板正则匹配 + Claude API 兜底）
  2. 路由到对应查询（SQL模板 / Agent调用 / 物化视图）
  3. 执行查询获取数据
  4. 生成自然语言回答 + 操作建议
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/nlq", tags=["nlq"])


# ═══════════════════════════════════════════════════════════════════
# 意图模板（50个预设 — 正则匹配，无外部NLP依赖）
# ═══════════════════════════════════════════════════════════════════

INTENT_TEMPLATES: list[dict[str, Any]] = [
    # ─── 营收类 (1-10) ──────────────────────────────────────────────
    {
        "pattern": r"今天.*营业额|今日.*营收|今天.*卖了多少|今天.*收入",
        "intent": "revenue_today",
        "category": "revenue",
        "sql": (
            "SELECT COALESCE(SUM(total_fen), 0) AS total_fen,"
            " COUNT(*) AS order_count"
            " FROM orders"
            " WHERE tenant_id = :tenant_id"
            " AND created_at >= :today_start AND created_at < :tomorrow_start"
            " AND is_deleted = FALSE"
        ),
        "answer_tpl": "今日营业额 {revenue}，共 {order_count} 笔订单。",
        "chart_type": "metric",
    },
    {
        "pattern": r"昨天|昨日.*营业|昨天.*卖|昨日.*收入",
        "intent": "revenue_yesterday",
        "category": "revenue",
        "sql": (
            "SELECT COALESCE(SUM(total_fen), 0) AS total_fen,"
            " COUNT(*) AS order_count"
            " FROM orders"
            " WHERE tenant_id = :tenant_id"
            " AND created_at >= :yesterday_start AND created_at < :today_start"
            " AND is_deleted = FALSE"
        ),
        "answer_tpl": "昨日营业额 {revenue}，共 {order_count} 笔订单。",
        "chart_type": "metric",
    },
    {
        "pattern": r"本周|这周.*营收|本周.*营业|这周.*收入",
        "intent": "revenue_this_week",
        "category": "revenue",
        "sql": (
            "SELECT COALESCE(SUM(total_fen), 0) AS total_fen,"
            " COUNT(*) AS order_count"
            " FROM orders"
            " WHERE tenant_id = :tenant_id"
            " AND created_at >= :week_start AND created_at < :tomorrow_start"
            " AND is_deleted = FALSE"
        ),
        "answer_tpl": "本周累计营业额 {revenue}，共 {order_count} 笔订单。",
        "chart_type": "metric",
    },
    {
        "pattern": r"本月|这个月.*营收|本月.*营业|这个月.*收入",
        "intent": "revenue_this_month",
        "category": "revenue",
        "sql": (
            "SELECT COALESCE(SUM(total_fen), 0) AS total_fen,"
            " COUNT(*) AS order_count"
            " FROM orders"
            " WHERE tenant_id = :tenant_id"
            " AND created_at >= :month_start AND created_at < :tomorrow_start"
            " AND is_deleted = FALSE"
        ),
        "answer_tpl": "本月累计营业额 {revenue}，共 {order_count} 笔订单。",
        "chart_type": "metric",
    },
    {
        "pattern": r"哪个门店.*最好|门店.*最高|最好.*门店|营业额.*排名",
        "intent": "top_store",
        "category": "revenue",
        "sql": (
            "SELECT s.name AS store_name, COALESCE(SUM(o.total_fen), 0) AS total_fen"
            " FROM orders o JOIN stores s ON o.store_id = s.id"
            " WHERE o.tenant_id = :tenant_id"
            " AND o.created_at >= :today_start AND o.created_at < :tomorrow_start"
            " AND o.is_deleted = FALSE"
            " GROUP BY s.name ORDER BY total_fen DESC LIMIT 5"
        ),
        "answer_tpl": "今日营业额最高的门店：{top_list}。",
        "chart_type": "bar",
    },
    {
        "pattern": r"哪个门店.*最差|门店.*最低|最差.*门店|业绩.*最低",
        "intent": "bottom_store",
        "category": "revenue",
        "sql": (
            "SELECT s.name AS store_name, COALESCE(SUM(o.total_fen), 0) AS total_fen"
            " FROM orders o JOIN stores s ON o.store_id = s.id"
            " WHERE o.tenant_id = :tenant_id"
            " AND o.created_at >= :today_start AND o.created_at < :tomorrow_start"
            " AND o.is_deleted = FALSE"
            " GROUP BY s.name ORDER BY total_fen ASC LIMIT 5"
        ),
        "answer_tpl": "今日营业额最低的门店：{bottom_list}。",
        "chart_type": "bar",
    },
    {
        "pattern": r"日均.*营业|平均.*每天.*收入|日均.*营收",
        "intent": "avg_daily_revenue",
        "category": "revenue",
        "sql": (
            "SELECT COALESCE(AVG(daily_total), 0) AS avg_fen FROM ("
            "  SELECT DATE(created_at) AS d, SUM(total_fen) AS daily_total"
            "  FROM orders WHERE tenant_id = :tenant_id"
            "  AND created_at >= :month_start AND created_at < :tomorrow_start"
            "  AND is_deleted = FALSE GROUP BY DATE(created_at)"
            ") sub"
        ),
        "answer_tpl": "本月日均营业额 {revenue}。",
        "chart_type": "metric",
    },
    {
        "pattern": r"营业额.*趋势|收入.*走势|每日.*营业",
        "intent": "revenue_trend",
        "category": "revenue",
        "sql": (
            "SELECT DATE(created_at) AS biz_date,"
            " COALESCE(SUM(total_fen), 0) AS total_fen"
            " FROM orders WHERE tenant_id = :tenant_id"
            " AND created_at >= :week_start AND created_at < :tomorrow_start"
            " AND is_deleted = FALSE"
            " GROUP BY DATE(created_at) ORDER BY biz_date"
        ),
        "answer_tpl": "近7日营业额趋势如下：{trend_data}。",
        "chart_type": "line",
    },
    {
        "pattern": r"环比|同比|对比.*昨天|和昨天比",
        "intent": "revenue_comparison",
        "category": "revenue",
        "sql": (
            "SELECT"
            " (SELECT COALESCE(SUM(total_fen),0) FROM orders"
            "  WHERE tenant_id=:tenant_id AND created_at>=:today_start"
            "  AND created_at<:tomorrow_start AND is_deleted=FALSE) AS today_fen,"
            " (SELECT COALESCE(SUM(total_fen),0) FROM orders"
            "  WHERE tenant_id=:tenant_id AND created_at>=:yesterday_start"
            "  AND created_at<:today_start AND is_deleted=FALSE) AS yesterday_fen"
        ),
        "answer_tpl": "今日营业额 {today}，昨日 {yesterday}，环比 {change}。",
        "chart_type": "comparison",
    },
    {
        "pattern": r"客单价|人均消费|平均.*订单",
        "intent": "avg_order_value",
        "category": "revenue",
        "sql": (
            "SELECT CASE WHEN COUNT(*)>0"
            " THEN COALESCE(SUM(total_fen),0)/COUNT(*) ELSE 0 END AS avg_fen,"
            " COUNT(*) AS order_count"
            " FROM orders WHERE tenant_id = :tenant_id"
            " AND created_at >= :today_start AND created_at < :tomorrow_start"
            " AND is_deleted = FALSE"
        ),
        "answer_tpl": "今日客单价 {avg_price}，共 {order_count} 笔订单。",
        "chart_type": "metric",
    },

    # ─── 菜品类 (11-20) ─────────────────────────────────────────────
    {
        "pattern": r"最畅销|卖得最好.*菜|销量.*最高.*菜|热销",
        "intent": "top_dishes",
        "category": "dish",
        "sql": (
            "SELECT d.name AS dish_name, SUM(oi.quantity) AS total_qty,"
            " SUM(oi.subtotal_fen) AS total_fen"
            " FROM order_items oi JOIN dishes d ON oi.dish_id = d.id"
            " JOIN orders o ON oi.order_id = o.id"
            " WHERE o.tenant_id = :tenant_id"
            " AND o.created_at >= :today_start AND o.created_at < :tomorrow_start"
            " AND o.is_deleted = FALSE"
            " GROUP BY d.name ORDER BY total_qty DESC LIMIT 10"
        ),
        "answer_tpl": "今日畅销菜品TOP10：{dish_list}。",
        "chart_type": "bar",
    },
    {
        "pattern": r"毛利.*最高|最赚钱.*菜|利润.*最高.*菜",
        "intent": "most_profitable_dish",
        "category": "dish",
        "sql": (
            "SELECT d.name AS dish_name,"
            " COALESCE(d.margin_rate, 0) AS margin_rate,"
            " SUM(oi.subtotal_fen) AS total_fen"
            " FROM order_items oi JOIN dishes d ON oi.dish_id = d.id"
            " JOIN orders o ON oi.order_id = o.id"
            " WHERE o.tenant_id = :tenant_id"
            " AND o.created_at >= :today_start AND o.created_at < :tomorrow_start"
            " AND o.is_deleted = FALSE"
            " GROUP BY d.name, d.margin_rate"
            " ORDER BY margin_rate DESC LIMIT 10"
        ),
        "answer_tpl": "毛利率最高的菜品：{dish_list}。",
        "chart_type": "bar",
    },
    {
        "pattern": r"卖得最差|滞销.*菜|没人点|点单.*最少",
        "intent": "worst_dishes",
        "category": "dish",
        "sql": (
            "SELECT d.name AS dish_name, COALESCE(SUM(oi.quantity), 0) AS total_qty"
            " FROM dishes d LEFT JOIN order_items oi ON d.id = oi.dish_id"
            " LEFT JOIN orders o ON oi.order_id = o.id"
            " AND o.created_at >= :today_start AND o.created_at < :tomorrow_start"
            " AND o.is_deleted = FALSE"
            " WHERE d.tenant_id = :tenant_id AND d.is_deleted = FALSE"
            " GROUP BY d.name ORDER BY total_qty ASC LIMIT 10"
        ),
        "answer_tpl": "今日销量最低的菜品：{dish_list}。",
        "chart_type": "bar",
    },
    {
        "pattern": r"毛利率.*低于|毛利.*不达标|低毛利.*菜",
        "intent": "low_margin_dishes",
        "category": "dish",
        "sql": (
            "SELECT name AS dish_name, COALESCE(margin_rate, 0) AS margin_rate"
            " FROM dishes"
            " WHERE tenant_id = :tenant_id AND is_deleted = FALSE"
            " AND COALESCE(margin_rate, 0) < 0.30"
            " ORDER BY margin_rate ASC LIMIT 20"
        ),
        "answer_tpl": "毛利率低于30%的菜品共{count}个：{dish_list}。",
        "chart_type": "table",
    },
    {
        "pattern": r"菜品.*分类|各分类.*销量|品类.*占比",
        "intent": "dish_category_breakdown",
        "category": "dish",
        "sql": (
            "SELECT d.category, SUM(oi.quantity) AS total_qty,"
            " SUM(oi.subtotal_fen) AS total_fen"
            " FROM order_items oi JOIN dishes d ON oi.dish_id = d.id"
            " JOIN orders o ON oi.order_id = o.id"
            " WHERE o.tenant_id = :tenant_id"
            " AND o.created_at >= :today_start AND o.created_at < :tomorrow_start"
            " AND o.is_deleted = FALSE"
            " GROUP BY d.category ORDER BY total_fen DESC"
        ),
        "answer_tpl": "今日各品类销售：{category_list}。",
        "chart_type": "pie",
    },
    {
        "pattern": r"套餐.*销量|套餐.*情况|组合.*菜",
        "intent": "combo_sales",
        "category": "dish",
        "sql": (
            "SELECT d.name AS dish_name, SUM(oi.quantity) AS total_qty"
            " FROM order_items oi JOIN dishes d ON oi.dish_id = d.id"
            " JOIN orders o ON oi.order_id = o.id"
            " WHERE o.tenant_id = :tenant_id"
            " AND o.created_at >= :today_start AND o.created_at < :tomorrow_start"
            " AND d.category = 'combo' AND o.is_deleted = FALSE"
            " GROUP BY d.name ORDER BY total_qty DESC LIMIT 10"
        ),
        "answer_tpl": "今日套餐销售情况：{dish_list}。",
        "chart_type": "bar",
    },
    {
        "pattern": r"退菜.*多|退菜.*排名|退菜.*原因",
        "intent": "dish_return_ranking",
        "category": "dish",
        "sql": (
            "SELECT d.name AS dish_name, COUNT(*) AS return_count"
            " FROM order_item_returns oir"
            " JOIN order_items oi ON oir.order_item_id = oi.id"
            " JOIN dishes d ON oi.dish_id = d.id"
            " JOIN orders o ON oi.order_id = o.id"
            " WHERE o.tenant_id = :tenant_id"
            " AND oir.created_at >= :today_start AND oir.created_at < :tomorrow_start"
            " GROUP BY d.name ORDER BY return_count DESC LIMIT 10"
        ),
        "answer_tpl": "今日退菜最多的菜品：{dish_list}。",
        "chart_type": "bar",
    },
    {
        "pattern": r"新菜.*表现|上新.*销量|新品.*如何",
        "intent": "new_dish_performance",
        "category": "dish",
        "sql": (
            "SELECT d.name AS dish_name, COALESCE(SUM(oi.quantity), 0) AS total_qty,"
            " COALESCE(SUM(oi.subtotal_fen), 0) AS total_fen"
            " FROM dishes d LEFT JOIN order_items oi ON d.id = oi.dish_id"
            " LEFT JOIN orders o ON oi.order_id = o.id"
            " AND o.created_at >= :week_start AND o.created_at < :tomorrow_start"
            " AND o.is_deleted = FALSE"
            " WHERE d.tenant_id = :tenant_id AND d.is_deleted = FALSE"
            " AND d.created_at >= :month_start"
            " GROUP BY d.name ORDER BY total_qty DESC LIMIT 10"
        ),
        "answer_tpl": "本月新菜表现：{dish_list}。",
        "chart_type": "bar",
    },
    {
        "pattern": r"菜品.*推荐|今天.*推什么|推荐.*主推",
        "intent": "dish_recommendation",
        "category": "dish",
        "agent_call": "menu_optimizer",
        "answer_tpl": "基于库存和销售数据，建议今日主推：{recommendations}。",
        "chart_type": None,
    },
    {
        "pattern": r"四象限|BCG.*矩阵|菜品.*分析.*矩阵",
        "intent": "dish_bcg_matrix",
        "category": "dish",
        "sql": (
            "SELECT d.name, COALESCE(d.margin_rate, 0) AS margin,"
            " COALESCE(SUM(oi.quantity), 0) AS qty"
            " FROM dishes d LEFT JOIN order_items oi ON d.id = oi.dish_id"
            " LEFT JOIN orders o ON oi.order_id = o.id"
            " AND o.created_at >= :month_start AND o.created_at < :tomorrow_start"
            " AND o.is_deleted = FALSE"
            " WHERE d.tenant_id = :tenant_id AND d.is_deleted = FALSE"
            " GROUP BY d.name, d.margin_rate"
        ),
        "answer_tpl": "菜品四象限分析：明星{star}、金牛{cash_cow}、问号{question}、瘦狗{dog}。",
        "chart_type": "scatter",
    },

    # ─── 会员类 (21-28) ─────────────────────────────────────────────
    {
        "pattern": r"新增会员|今天.*会员|今日.*注册",
        "intent": "new_members_today",
        "category": "member",
        "sql": (
            "SELECT COUNT(*) AS new_count FROM members"
            " WHERE tenant_id = :tenant_id"
            " AND created_at >= :today_start AND created_at < :tomorrow_start"
            " AND is_deleted = FALSE"
        ),
        "answer_tpl": "今日新增会员 {count} 人。",
        "chart_type": "metric",
    },
    {
        "pattern": r"复购率|回头客|老客.*比例",
        "intent": "repurchase_rate",
        "category": "member",
        "sql": (
            "SELECT"
            " COUNT(DISTINCT CASE WHEN order_cnt > 1 THEN member_id END) AS repeat_count,"
            " COUNT(DISTINCT member_id) AS total_count"
            " FROM ("
            "  SELECT member_id, COUNT(*) AS order_cnt FROM orders"
            "  WHERE tenant_id = :tenant_id AND member_id IS NOT NULL"
            "  AND created_at >= :month_start AND created_at < :tomorrow_start"
            "  AND is_deleted = FALSE"
            "  GROUP BY member_id"
            ") sub"
        ),
        "answer_tpl": "本月会员复购率 {rate}（{repeat}/{total}）。",
        "chart_type": "metric",
    },
    {
        "pattern": r"会员.*消费|会员.*贡献|会员.*占比",
        "intent": "member_revenue_share",
        "category": "member",
        "sql": (
            "SELECT"
            " COALESCE(SUM(CASE WHEN member_id IS NOT NULL THEN total_fen ELSE 0 END), 0) AS member_fen,"
            " COALESCE(SUM(total_fen), 0) AS total_fen"
            " FROM orders WHERE tenant_id = :tenant_id"
            " AND created_at >= :today_start AND created_at < :tomorrow_start"
            " AND is_deleted = FALSE"
        ),
        "answer_tpl": "今日会员消费占比 {share}（{member_rev} / {total_rev}）。",
        "chart_type": "pie",
    },
    {
        "pattern": r"储值.*余额|充值.*总额|储值.*统计",
        "intent": "stored_value_balance",
        "category": "member",
        "sql": (
            "SELECT COALESCE(SUM(balance_fen), 0) AS total_balance,"
            " COUNT(*) AS member_count"
            " FROM members WHERE tenant_id = :tenant_id"
            " AND balance_fen > 0 AND is_deleted = FALSE"
        ),
        "answer_tpl": "当前储值余额合计 {balance}，涉及 {count} 位会员。",
        "chart_type": "metric",
    },
    {
        "pattern": r"流失.*会员|沉睡.*会员|多久没来",
        "intent": "churned_members",
        "category": "member",
        "sql": (
            "SELECT COUNT(*) AS churned_count FROM members m"
            " WHERE m.tenant_id = :tenant_id AND m.is_deleted = FALSE"
            " AND NOT EXISTS ("
            "  SELECT 1 FROM orders o WHERE o.member_id = m.id"
            "  AND o.created_at >= :month_start - INTERVAL '60 days'"
            "  AND o.is_deleted = FALSE"
            " )"
        ),
        "answer_tpl": "近60天未消费的沉睡会员共 {count} 人，建议启动召回计划。",
        "chart_type": "metric",
    },
    {
        "pattern": r"VIP.*会员|高价值.*会员|大客户",
        "intent": "vip_members",
        "category": "member",
        "sql": (
            "SELECT m.name, m.phone, COALESCE(SUM(o.total_fen), 0) AS total_spend"
            " FROM members m JOIN orders o ON m.id = o.member_id"
            " WHERE m.tenant_id = :tenant_id AND m.is_deleted = FALSE"
            " AND o.created_at >= :month_start AND o.is_deleted = FALSE"
            " GROUP BY m.id, m.name, m.phone"
            " ORDER BY total_spend DESC LIMIT 10"
        ),
        "answer_tpl": "本月消费最高的VIP会员：{member_list}。",
        "chart_type": "table",
    },
    {
        "pattern": r"会员.*生日|本月.*生日|生日.*提醒",
        "intent": "birthday_members",
        "category": "member",
        "sql": (
            "SELECT name, phone, birthday FROM members"
            " WHERE tenant_id = :tenant_id AND is_deleted = FALSE"
            " AND EXTRACT(MONTH FROM birthday) = EXTRACT(MONTH FROM CURRENT_DATE)"
            " AND EXTRACT(DAY FROM birthday) BETWEEN"
            " EXTRACT(DAY FROM CURRENT_DATE) AND EXTRACT(DAY FROM CURRENT_DATE) + 7"
            " LIMIT 20"
        ),
        "answer_tpl": "未来7天过生日的会员有{count}位：{member_list}。",
        "chart_type": "table",
    },
    {
        "pattern": r"优惠券.*核销|券.*使用|优惠券.*效果",
        "intent": "coupon_usage",
        "category": "member",
        "sql": (
            "SELECT c.name AS coupon_name,"
            " COUNT(CASE WHEN cr.status='redeemed' THEN 1 END) AS used,"
            " COUNT(*) AS total"
            " FROM coupon_records cr JOIN coupons c ON cr.coupon_id = c.id"
            " WHERE cr.tenant_id = :tenant_id"
            " AND cr.created_at >= :month_start"
            " GROUP BY c.name ORDER BY used DESC LIMIT 10"
        ),
        "answer_tpl": "本月优惠券核销情况：{coupon_list}。",
        "chart_type": "bar",
    },

    # ─── 运营类 (29-36) ─────────────────────────────────────────────
    {
        "pattern": r"翻台率|桌台.*利用|翻台.*次数",
        "intent": "table_turnover",
        "category": "ops",
        "sql": (
            "SELECT COUNT(DISTINCT o.id)::FLOAT /"
            " GREATEST((SELECT COUNT(*) FROM tables WHERE store_id = :store_id"
            " AND is_deleted = FALSE), 1) AS turnover_rate"
            " FROM orders o WHERE o.tenant_id = :tenant_id"
            " AND o.created_at >= :today_start AND o.created_at < :tomorrow_start"
            " AND o.is_deleted = FALSE"
        ),
        "answer_tpl": "今日翻台率 {rate} 次/桌。",
        "chart_type": "metric",
    },
    {
        "pattern": r"出餐.*时间|等餐.*时间|平均.*出餐",
        "intent": "avg_serve_time",
        "category": "ops",
        "sql": (
            "SELECT AVG(EXTRACT(EPOCH FROM (served_at - created_at))/60) AS avg_minutes"
            " FROM order_items WHERE tenant_id = :tenant_id"
            " AND created_at >= :today_start AND created_at < :tomorrow_start"
            " AND served_at IS NOT NULL"
        ),
        "answer_tpl": "今日平均出餐时间 {minutes} 分钟。",
        "chart_type": "metric",
    },
    {
        "pattern": r"高峰.*时段|忙.*时间|客流.*分布",
        "intent": "peak_hours",
        "category": "ops",
        "sql": (
            "SELECT EXTRACT(HOUR FROM created_at)::INT AS hour,"
            " COUNT(*) AS order_count"
            " FROM orders WHERE tenant_id = :tenant_id"
            " AND created_at >= :today_start AND created_at < :tomorrow_start"
            " AND is_deleted = FALSE"
            " GROUP BY EXTRACT(HOUR FROM created_at)"
            " ORDER BY order_count DESC"
        ),
        "answer_tpl": "今日客流高峰时段：{peak_hours}。",
        "chart_type": "bar",
    },
    {
        "pattern": r"废单|作废.*订单|取消.*订单",
        "intent": "void_orders",
        "category": "ops",
        "sql": (
            "SELECT COUNT(*) AS void_count,"
            " COALESCE(SUM(total_fen), 0) AS void_fen"
            " FROM orders WHERE tenant_id = :tenant_id"
            " AND created_at >= :today_start AND created_at < :tomorrow_start"
            " AND status = 'voided'"
        ),
        "answer_tpl": "今日废单 {count} 笔，合计 {amount}。",
        "chart_type": "metric",
    },
    {
        "pattern": r"折扣.*多少|折扣.*总额|今天.*打折",
        "intent": "discount_total",
        "category": "ops",
        "sql": (
            "SELECT COALESCE(SUM(discount_fen), 0) AS discount_fen,"
            " COUNT(CASE WHEN discount_fen > 0 THEN 1 END) AS discount_count,"
            " COUNT(*) AS total_count"
            " FROM orders WHERE tenant_id = :tenant_id"
            " AND created_at >= :today_start AND created_at < :tomorrow_start"
            " AND is_deleted = FALSE"
        ),
        "answer_tpl": "今日折扣合计 {amount}，{discount_count}/{total_count} 笔订单享受折扣。",
        "chart_type": "metric",
    },
    {
        "pattern": r"堂食.*外卖|渠道.*占比|线上.*线下",
        "intent": "channel_breakdown",
        "category": "ops",
        "sql": (
            "SELECT COALESCE(channel, 'dine_in') AS channel,"
            " COUNT(*) AS order_count,"
            " COALESCE(SUM(total_fen), 0) AS total_fen"
            " FROM orders WHERE tenant_id = :tenant_id"
            " AND created_at >= :today_start AND created_at < :tomorrow_start"
            " AND is_deleted = FALSE"
            " GROUP BY COALESCE(channel, 'dine_in')"
        ),
        "answer_tpl": "今日渠道分布：{channel_list}。",
        "chart_type": "pie",
    },
    {
        "pattern": r"日结|今天.*结算|日清",
        "intent": "daily_settlement",
        "category": "ops",
        "sql": (
            "SELECT status, revenue_fen, cost_fen, cash_actual_fen, cash_expected_fen"
            " FROM daily_settlements"
            " WHERE tenant_id = :tenant_id AND biz_date = :today_date"
            " LIMIT 1"
        ),
        "answer_tpl": "今日日结状态：{status}，营收 {revenue}，成本 {cost}。",
        "chart_type": "metric",
    },
    {
        "pattern": r"员工.*排班|今天.*上班|谁.*值班",
        "intent": "staff_schedule",
        "category": "ops",
        "sql": (
            "SELECT e.name, s.shift_type, s.start_time, s.end_time"
            " FROM schedules s JOIN employees e ON s.employee_id = e.id"
            " WHERE s.tenant_id = :tenant_id AND s.shift_date = :today_date"
            " AND s.is_deleted = FALSE"
            " ORDER BY s.start_time"
        ),
        "answer_tpl": "今日排班：{schedule_list}。",
        "chart_type": "table",
    },

    # ─── 异常/预警类 (37-42) ────────────────────────────────────────
    {
        "pattern": r"异常|预警|问题|告警|警报",
        "intent": "anomalies_today",
        "category": "anomaly",
        "agent_call": "anomaly_detector",
        "answer_tpl": "今日发现 {count} 项异常：{anomaly_list}。",
        "chart_type": None,
    },
    {
        "pattern": r"为什么.*下降|毛利.*低|利润.*降",
        "intent": "margin_attribution",
        "category": "anomaly",
        "agent_call": "finance_auditor",
        "answer_tpl": "{attribution_analysis}",
        "chart_type": None,
    },
    {
        "pattern": r"库存.*预警|快.*断货|缺货|库存.*不足",
        "intent": "inventory_alert",
        "category": "anomaly",
        "sql": (
            "SELECT ingredient_name, current_qty, unit, min_qty"
            " FROM inventory"
            " WHERE tenant_id = :tenant_id AND is_deleted = FALSE"
            " AND current_qty <= min_qty"
            " ORDER BY (current_qty::FLOAT / GREATEST(min_qty, 1)) ASC"
            " LIMIT 10"
        ),
        "answer_tpl": "当前库存预警食材{count}种：{ingredient_list}。",
        "chart_type": "table",
    },
    {
        "pattern": r"临期|过期|食材.*效期|保质期",
        "intent": "expiry_alert",
        "category": "anomaly",
        "sql": (
            "SELECT ingredient_name, current_qty, unit, expiry_date"
            " FROM inventory"
            " WHERE tenant_id = :tenant_id AND is_deleted = FALSE"
            " AND expiry_date <= CURRENT_DATE + INTERVAL '3 days'"
            " AND expiry_date >= CURRENT_DATE"
            " ORDER BY expiry_date ASC LIMIT 10"
        ),
        "answer_tpl": "临期食材（3天内）{count}种：{ingredient_list}。请立即处理！",
        "chart_type": "table",
    },
    {
        "pattern": r"折扣.*异常|折扣.*可疑|折扣.*守护",
        "intent": "discount_anomaly",
        "category": "anomaly",
        "mv_query": "mv_discount_health",
        "answer_tpl": "折扣健康状况：{health_summary}。",
        "chart_type": None,
    },
    {
        "pattern": r"舆情|差评|投诉|口碑",
        "intent": "reputation_alert",
        "category": "anomaly",
        "mv_query": "mv_public_opinion",
        "answer_tpl": "近期舆情摘要：{opinion_summary}。",
        "chart_type": None,
    },

    # ─── 财务类 (43-47) ─────────────────────────────────────────────
    {
        "pattern": r"毛利|利润率|今天.*赚",
        "intent": "gross_margin",
        "category": "finance",
        "sql": (
            "SELECT COALESCE(SUM(total_fen), 0) AS revenue_fen,"
            " COALESCE(SUM(cost_fen), 0) AS cost_fen"
            " FROM orders WHERE tenant_id = :tenant_id"
            " AND created_at >= :today_start AND created_at < :tomorrow_start"
            " AND is_deleted = FALSE"
        ),
        "answer_tpl": "今日营收 {revenue}，成本 {cost}，毛利率 {margin_rate}。",
        "chart_type": "metric",
    },
    {
        "pattern": r"食材.*成本|成本率|成本.*占比",
        "intent": "food_cost_rate",
        "category": "finance",
        "sql": (
            "SELECT COALESCE(SUM(total_fen), 0) AS revenue_fen,"
            " COALESCE(SUM(cost_fen), 0) AS cost_fen"
            " FROM orders WHERE tenant_id = :tenant_id"
            " AND created_at >= :month_start AND created_at < :tomorrow_start"
            " AND is_deleted = FALSE"
        ),
        "answer_tpl": "本月食材成本率 {cost_rate}（{cost} / {revenue}）。",
        "chart_type": "metric",
    },
    {
        "pattern": r"人力.*成本|工资.*占比|人效",
        "intent": "labor_cost",
        "category": "finance",
        "sql": (
            "SELECT COALESCE(SUM(salary_fen), 0) AS salary_fen,"
            " COUNT(DISTINCT employee_id) AS headcount"
            " FROM payroll_records WHERE tenant_id = :tenant_id"
            " AND pay_month = TO_CHAR(:today_date, 'YYYY-MM')"
        ),
        "answer_tpl": "本月人力成本 {salary}，共 {headcount} 人。",
        "chart_type": "metric",
    },
    {
        "pattern": r"P&?L|损益|盈亏|利润表",
        "intent": "pnl_summary",
        "category": "finance",
        "mv_query": "mv_store_pnl",
        "answer_tpl": "门店P&L概览：{pnl_summary}。",
        "chart_type": "table",
    },
    {
        "pattern": r"能耗|电费|水费|用电",
        "intent": "energy_cost",
        "category": "finance",
        "mv_query": "mv_energy_efficiency",
        "answer_tpl": "能耗概览：{energy_summary}。",
        "chart_type": "bar",
    },

    # ─── Agent/综合类 (48-50) ───────────────────────────────────────
    {
        "pattern": r"Agent.*行动|待办.*任务|智能.*建议|AI.*建议",
        "intent": "agent_actions",
        "category": "agent",
        "agent_call": "master_agent",
        "answer_tpl": "当前待处理的Agent行动：{action_list}。",
        "chart_type": None,
    },
    {
        "pattern": r"经营.*健康|整体.*状况|门店.*评分|健康度",
        "intent": "store_health",
        "category": "comprehensive",
        "mv_query": "mv_store_pnl",
        "answer_tpl": "门店经营健康度评分：{score}/100。{summary}",
        "chart_type": "gauge",
    },
    {
        "pattern": r"日报|经营.*报告|今天.*汇总|总结",
        "intent": "daily_report",
        "category": "comprehensive",
        "agent_call": "narrative_report",
        "answer_tpl": "{daily_report}",
        "chart_type": None,
    },
]

# 编译正则（只做一次）
_COMPILED_TEMPLATES = [
    {**tpl, "_re": re.compile(tpl["pattern"], re.IGNORECASE)}
    for tpl in INTENT_TEMPLATES
]


# ═══════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════

def _fen_to_yuan(fen: int) -> str:
    """分转元，带千分位符"""
    return f"\u00a5{fen / 100:,.2f}"


def _build_time_params(store_id: str | None = None) -> dict[str, Any]:
    """构建查询常用时间参数"""
    now = datetime.now(timezone.utc)
    today = now.date()
    today_start = datetime.combine(today, time.min, tzinfo=timezone.utc)
    tomorrow_start = today_start + timedelta(days=1)
    yesterday_start = today_start - timedelta(days=1)
    # ISO周一为本周开始
    week_start = today_start - timedelta(days=today.weekday())
    month_start = datetime.combine(today.replace(day=1), time.min, tzinfo=timezone.utc)

    params: dict[str, Any] = {
        "today_start": today_start,
        "tomorrow_start": tomorrow_start,
        "yesterday_start": yesterday_start,
        "week_start": week_start,
        "month_start": month_start,
        "today_date": today,
    }
    if store_id:
        params["store_id"] = store_id
    return params


def match_intent(question: str) -> dict[str, Any] | None:
    """在50个预设模板中做正则匹配，返回第一个命中的模板或None"""
    for tpl in _COMPILED_TEMPLATES:
        if tpl["_re"].search(question):
            return tpl
    return None


async def _call_claude_for_intent(
    question: str,
    tenant_id: str,
) -> dict[str, Any]:
    """当50个模板都不匹配时，通过 tx-brain 的 Claude API 做意图识别和回答。
    通过 HTTP 调用 tx-brain 服务（ModelRouter 原则：不直接调 Claude API）。
    """
    brain_url = "http://localhost:8010/api/v1/brain/customer-service/handle"
    payload = {
        "tenant_id": tenant_id,
        "store_id": "",
        "channel": "nlq",
        "message": question,
        "message_type": "inquiry",
        "context_history": [],
        "customer_tier": "regular",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(brain_url, json=payload)
            if resp.status_code == 200:
                body = resp.json()
                if body.get("ok"):
                    data = body["data"]
                    return {
                        "intent": "claude_freeform",
                        "answer": data.get("response", "AI正在分析您的问题..."),
                        "source": "claude_api",
                        "raw": data,
                    }
    except httpx.TimeoutException:
        logger.warning("nlq.claude_timeout", question=question)
    except httpx.ConnectError:
        logger.warning("nlq.brain_unreachable", question=question)

    return {
        "intent": "unknown",
        "answer": f"抱歉，暂时无法理解您的问题：「{question}」。请换个说法试试，或从推荐问题中选择。",
        "source": "fallback",
    }


async def _execute_sql_query(
    db: AsyncSession,
    sql_str: str,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    """安全执行 SQL 查询，返回行字典列表"""
    try:
        result = await db.execute(text(sql_str), params)
        columns = list(result.keys())
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
        return rows
    except (SQLAlchemyError, ConnectionError) as exc:
        logger.error("nlq.sql_exec_error", error=str(exc), sql=sql_str[:200])
        return []


async def _read_mv(
    db: AsyncSession,
    mv_name: str,
    tenant_id: str,
    store_id: str | None = None,
) -> list[dict[str, Any]]:
    """从物化视图读取数据"""
    safe_mv = re.sub(r"[^a-z0-9_]", "", mv_name)
    sql = f"SELECT * FROM {safe_mv} WHERE tenant_id = :tenant_id"  # noqa: S608
    params: dict[str, Any] = {"tenant_id": tenant_id}
    if store_id:
        sql += " AND store_id = :store_id"
        params["store_id"] = store_id
    sql += " LIMIT 50"
    return await _execute_sql_query(db, sql, params)


def _format_answer(
    tpl: dict[str, Any],
    rows: list[dict[str, Any]],
) -> str:
    """根据意图模板和查询结果生成自然语言回答"""
    intent = tpl["intent"]
    answer_tpl = tpl.get("answer_tpl", "")

    if not rows:
        return f"暂无数据。（意图：{intent}）"

    row = rows[0]

    # 根据不同意图做格式化
    try:
        if intent in ("revenue_today", "revenue_yesterday", "revenue_this_week",
                       "revenue_this_month", "avg_daily_revenue"):
            fen = int(row.get("total_fen", 0) or row.get("avg_fen", 0))
            count = row.get("order_count", "")
            return answer_tpl.format(
                revenue=_fen_to_yuan(fen),
                order_count=count,
            )

        if intent == "revenue_comparison":
            today_fen = int(row.get("today_fen", 0))
            yesterday_fen = int(row.get("yesterday_fen", 0))
            if yesterday_fen > 0:
                change = (today_fen - yesterday_fen) / yesterday_fen
                change_str = f"{change:+.1%}"
            else:
                change_str = "N/A"
            return answer_tpl.format(
                today=_fen_to_yuan(today_fen),
                yesterday=_fen_to_yuan(yesterday_fen),
                change=change_str,
            )

        if intent == "avg_order_value":
            avg_fen = int(row.get("avg_fen", 0))
            return answer_tpl.format(
                avg_price=_fen_to_yuan(avg_fen),
                order_count=row.get("order_count", 0),
            )

        if intent in ("top_store", "bottom_store"):
            items = [f"{r['store_name']}({_fen_to_yuan(int(r['total_fen']))})"
                     for r in rows[:5]]
            key = "top_list" if intent == "top_store" else "bottom_list"
            return answer_tpl.format(**{key: "、".join(items)})

        if intent == "revenue_trend":
            items = [f"{r['biz_date']}:{_fen_to_yuan(int(r['total_fen']))}"
                     for r in rows]
            return answer_tpl.format(trend_data="、".join(items))

        if intent in ("top_dishes", "worst_dishes", "most_profitable_dish",
                       "combo_sales", "dish_return_ranking", "new_dish_performance"):
            items = []
            for r in rows[:10]:
                name = r.get("dish_name", "")
                qty = r.get("total_qty", r.get("return_count", 0))
                items.append(f"{name}({qty}份)")
            return answer_tpl.format(
                dish_list="、".join(items),
                count=len(rows),
            )

        if intent == "low_margin_dishes":
            items = [f"{r['dish_name']}({r['margin_rate']:.0%})"
                     for r in rows[:10]]
            return answer_tpl.format(
                dish_list="、".join(items),
                count=len(rows),
            )

        if intent == "dish_category_breakdown":
            items = [f"{r['category']}({_fen_to_yuan(int(r['total_fen']))})"
                     for r in rows]
            return answer_tpl.format(category_list="、".join(items))

        if intent == "new_members_today":
            return answer_tpl.format(count=row.get("new_count", 0))

        if intent == "repurchase_rate":
            repeat = int(row.get("repeat_count", 0))
            total = int(row.get("total_count", 0))
            rate = f"{repeat/total:.1%}" if total > 0 else "N/A"
            return answer_tpl.format(rate=rate, repeat=repeat, total=total)

        if intent == "member_revenue_share":
            m_fen = int(row.get("member_fen", 0))
            t_fen = int(row.get("total_fen", 0))
            share = f"{m_fen/t_fen:.1%}" if t_fen > 0 else "N/A"
            return answer_tpl.format(
                share=share,
                member_rev=_fen_to_yuan(m_fen),
                total_rev=_fen_to_yuan(t_fen),
            )

        if intent == "gross_margin":
            rev = int(row.get("revenue_fen", 0))
            cost = int(row.get("cost_fen", 0))
            margin = f"{(rev-cost)/rev:.1%}" if rev > 0 else "N/A"
            return answer_tpl.format(
                revenue=_fen_to_yuan(rev),
                cost=_fen_to_yuan(cost),
                margin_rate=margin,
            )

        if intent == "void_orders":
            return answer_tpl.format(
                count=row.get("void_count", 0),
                amount=_fen_to_yuan(int(row.get("void_fen", 0))),
            )

        if intent == "discount_total":
            return answer_tpl.format(
                amount=_fen_to_yuan(int(row.get("discount_fen", 0))),
                discount_count=row.get("discount_count", 0),
                total_count=row.get("total_count", 0),
            )

        # 通用回退：返回第一行数据的字符串
        return f"查询结果：{row}"

    except (KeyError, ValueError, ZeroDivisionError) as exc:
        logger.warning("nlq.format_error", intent=intent, error=str(exc))
        return f"查询到 {len(rows)} 条数据，但格式化时出错。原始数据: {rows[0]}"


def _generate_actions(
    intent: str,
    rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """基于意图和数据生成可执行操作建议"""
    actions: list[dict[str, str]] = []

    if intent in ("inventory_alert", "expiry_alert"):
        actions.append({
            "action_id": "create_purchase_order",
            "label": "一键生成采购单",
            "description": "根据预警食材自动创建采购订单",
            "endpoint": "/api/v1/supply/purchase-orders/auto-generate",
        })
    if intent in ("discount_anomaly", "discount_total"):
        actions.append({
            "action_id": "review_discounts",
            "label": "查看折扣明细",
            "description": "跳转折扣守护面板查看详情",
            "endpoint": "/api/v1/brain/discount/mv-insight",
        })
    if intent in ("churned_members",):
        actions.append({
            "action_id": "launch_recall_campaign",
            "label": "启动会员召回",
            "description": "创建沉睡会员召回营销活动",
            "endpoint": "/api/v1/brain/crm/campaign",
        })
    if intent in ("worst_dishes", "low_margin_dishes"):
        actions.append({
            "action_id": "optimize_menu",
            "label": "优化菜单",
            "description": "调用智能排菜Agent优化菜品结构",
            "endpoint": "/api/v1/brain/menu/optimize",
        })
    if intent == "anomalies_today":
        actions.append({
            "action_id": "view_anomaly_detail",
            "label": "查看异常详情",
            "description": "进入异常叙事面板查看详情",
            "endpoint": "/api/v1/analytics/narrative/anomaly",
        })
    if intent == "daily_report":
        actions.append({
            "action_id": "push_daily_report",
            "label": "推送日报到企微",
            "description": "将日报推送到企业微信群",
            "endpoint": "/api/v1/analytics/narrative/daily-report",
        })
    if intent in ("birthday_members",):
        actions.append({
            "action_id": "send_birthday_coupon",
            "label": "发送生日券",
            "description": "为即将过生日的会员发送生日优惠券",
            "endpoint": "/api/v1/member/coupons/batch-send",
        })

    return actions


def _get_suggestions_by_time() -> list[dict[str, str]]:
    """根据当前时间段生成推荐问题"""
    now = datetime.now(timezone.utc)
    hour = (now.hour + 8) % 24  # 简易CST转换

    base = [
        {"id": "s1", "text": "今天各门店营业额对比", "category": "revenue"},
        {"id": "s2", "text": "最畅销的菜品TOP10", "category": "dish"},
        {"id": "s3", "text": "会员复购率是多少", "category": "member"},
        {"id": "s4", "text": "有哪些异常预警", "category": "anomaly"},
    ]

    if hour < 11:
        # 早间
        base.extend([
            {"id": "s5", "text": "昨天营业额和前天对比如何", "category": "revenue"},
            {"id": "s6", "text": "今天哪些食材临期需要处理", "category": "anomaly"},
            {"id": "s7", "text": "今天谁排班了", "category": "ops"},
            {"id": "s8", "text": "生成昨日经营日报", "category": "comprehensive"},
        ])
    elif hour < 14:
        # 午市
        base.extend([
            {"id": "s5", "text": "午市客单价是多少", "category": "revenue"},
            {"id": "s6", "text": "出餐速度怎么样", "category": "ops"},
            {"id": "s7", "text": "哪些菜品卖得最好", "category": "dish"},
            {"id": "s8", "text": "翻台率怎么样", "category": "ops"},
        ])
    elif hour < 17:
        # 下午
        base.extend([
            {"id": "s5", "text": "库存有预警吗", "category": "anomaly"},
            {"id": "s6", "text": "毛利率低于30%的菜品", "category": "dish"},
            {"id": "s7", "text": "本周营收趋势", "category": "revenue"},
            {"id": "s8", "text": "沉睡会员有多少", "category": "member"},
        ])
    else:
        # 晚市+打烊
        base.extend([
            {"id": "s5", "text": "今天营业额目标完成了吗", "category": "revenue"},
            {"id": "s6", "text": "今天折扣打了多少", "category": "ops"},
            {"id": "s7", "text": "今天废单情况如何", "category": "ops"},
            {"id": "s8", "text": "生成今日经营日报", "category": "comprehensive"},
        ])

    return base


# ═══════════════════════════════════════════════════════════════════
# Pydantic Models
# ═══════════════════════════════════════════════════════════════════

class NLQAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500, description="自然语言问题")
    context: dict[str, Any] | None = Field(
        default=None,
        description="上下文：{store_id, brand_id, date_start, date_end}",
    )
    session_id: str | None = Field(
        default=None,
        description="会话ID，关联多轮对话",
    )


class NLQExecuteActionRequest(BaseModel):
    action_id: str = Field(..., description="操作ID")
    params: dict[str, Any] = Field(default_factory=dict, description="操作参数")
    session_id: str | None = None


# ═══════════════════════════════════════════════════════════════════
# 数据库依赖
# ═══════════════════════════════════════════════════════════════════

async def _get_db_with_tenant(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ═══════════════════════════════════════════════════════════════════
# 端点1: POST /api/v1/nlq/ask — 核心问答
# ═══════════════════════════════════════════════════════════════════

@router.post("/ask")
async def nlq_ask(
    body: NLQAskRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """
    对话式经营助手 — 核心问答端点。

    处理流程：
    1. 意图识别（50个预设模板正则匹配）
    2. 若无匹配 → Claude API 兜底（通过 tx-brain）
    3. 执行查询（SQL / Agent / 物化视图）
    4. 格式化自然语言回答 + 操作建议
    """
    question = body.question.strip()
    ctx = body.context or {}
    store_id = ctx.get("store_id")
    session_id = body.session_id or str(uuid.uuid4())
    log = logger.bind(
        tenant=x_tenant_id,
        question=question[:80],
        session_id=session_id,
    )

    # Step 1: 意图匹配
    matched = match_intent(question)

    if not matched:
        # Claude API 兜底
        log.info("nlq.claude_fallback")
        claude_result = await _call_claude_for_intent(question, x_tenant_id)
        # 持久化消息到 nlq_messages
        await _save_message(db, x_tenant_id, session_id, question,
                            claude_result["intent"], claude_result["answer"])
        return {
            "ok": True,
            "data": {
                "session_id": session_id,
                "question": question,
                "intent": claude_result["intent"],
                "answer": claude_result["answer"],
                "data": None,
                "chart_type": None,
                "actions": [],
                "source": claude_result.get("source", "claude_api"),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    intent = matched["intent"]
    log = log.bind(intent=intent)
    log.info("nlq.intent_matched")

    # Step 2: 路由到查询
    time_params = _build_time_params(store_id)
    query_params = {**time_params, "tenant_id": x_tenant_id}
    rows: list[dict[str, Any]] = []
    source = "sql_template"

    if "sql" in matched:
        rows = await _execute_sql_query(db, matched["sql"], query_params)
        source = "sql_template"
    elif "mv_query" in matched:
        rows = await _read_mv(db, matched["mv_query"], x_tenant_id, store_id)
        source = "materialized_view"
    elif "agent_call" in matched:
        # Agent 调用走 Claude 兜底通道
        claude_result = await _call_claude_for_intent(question, x_tenant_id)
        answer = claude_result.get("answer", "Agent正在分析中...")
        await _save_message(db, x_tenant_id, session_id, question, intent, answer)
        return {
            "ok": True,
            "data": {
                "session_id": session_id,
                "question": question,
                "intent": intent,
                "answer": answer,
                "data": claude_result.get("raw"),
                "chart_type": matched.get("chart_type"),
                "actions": _generate_actions(intent, []),
                "source": "agent_call",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    # Step 3: 格式化回答
    answer = _format_answer(matched, rows)
    actions = _generate_actions(intent, rows)

    # Step 4: 持久化
    await _save_message(db, x_tenant_id, session_id, question, intent, answer)

    return {
        "ok": True,
        "data": {
            "session_id": session_id,
            "question": question,
            "intent": intent,
            "answer": answer,
            "data": rows,
            "chart_type": matched.get("chart_type"),
            "actions": actions,
            "source": source,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ═══════════════════════════════════════════════════════════════════
# 端点2: GET /api/v1/nlq/suggestions — 推荐问题
# ═══════════════════════════════════════════════════════════════════

@router.get("/suggestions")
async def get_suggestions(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> dict:
    """推荐问题列表 — 根据当前时间段动态生成"""
    suggestions = _get_suggestions_by_time()
    return {"ok": True, "data": suggestions}


# ═══════════════════════════════════════════════════════════════════
# 端点3: GET /api/v1/nlq/history — 历史问答
# ═══════════════════════════════════════════════════════════════════

@router.get("/history")
async def get_query_history(
    limit: int = Query(20, ge=1, le=100),
    session_id: str | None = Query(None, description="按会话ID筛选"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """问答历史 — 从 nlq_messages 表读取"""
    try:
        sql = (
            "SELECT id, session_id, role, content, intent, created_at"
            " FROM nlq_messages"
            " WHERE tenant_id = :tenant_id"
        )
        params: dict[str, Any] = {"tenant_id": x_tenant_id}
        if session_id:
            sql += " AND session_id = :session_id"
            params["session_id"] = session_id
        sql += " ORDER BY created_at DESC LIMIT :limit"
        params["limit"] = limit

        rows = await _execute_sql_query(db, sql, params)
        # 序列化 datetime/uuid
        for row in rows:
            for k, v in row.items():
                if isinstance(v, (datetime, date)):
                    row[k] = v.isoformat()
                elif isinstance(v, uuid.UUID):
                    row[k] = str(v)

        return {"ok": True, "data": rows, "total": len(rows)}
    except (SQLAlchemyError, ConnectionError) as exc:
        logger.warning("nlq.history_read_error", error=str(exc))
        return {"ok": True, "data": [], "total": 0}


# ═══════════════════════════════════════════════════════════════════
# 端点4: POST /api/v1/nlq/execute-action — 执行建议操作
# ═══════════════════════════════════════════════════════════════════

@router.post("/execute-action")
async def execute_action(
    body: NLQExecuteActionRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """执行 AI 建议的操作 — 代理转发到对应服务端点"""
    action_id = body.action_id
    log = logger.bind(tenant=x_tenant_id, action_id=action_id)

    # 操作路由表
    action_map: dict[str, dict[str, str]] = {
        "create_purchase_order": {
            "url": "http://localhost:8006/api/v1/supply/purchase-orders/auto-generate",
            "method": "POST",
        },
        "review_discounts": {
            "url": "http://localhost:8010/api/v1/brain/discount/mv-insight",
            "method": "GET",
        },
        "launch_recall_campaign": {
            "url": "http://localhost:8010/api/v1/brain/crm/campaign",
            "method": "POST",
        },
        "optimize_menu": {
            "url": "http://localhost:8010/api/v1/brain/menu/optimize",
            "method": "POST",
        },
        "view_anomaly_detail": {
            "url": "http://localhost:8009/api/v1/analytics/narrative/anomaly",
            "method": "GET",
        },
        "push_daily_report": {
            "url": "http://localhost:8009/api/v1/analytics/narrative/daily-report",
            "method": "POST",
        },
        "send_birthday_coupon": {
            "url": "http://localhost:8003/api/v1/member/coupons/batch-send",
            "method": "POST",
        },
    }

    route = action_map.get(action_id)
    if not route:
        return {
            "ok": False,
            "error": {"code": "UNKNOWN_ACTION", "message": f"未知操作: {action_id}"},
        }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            params_with_tenant = {
                **body.params,
                "tenant_id": x_tenant_id,
            }
            if route["method"] == "GET":
                resp = await client.get(
                    route["url"],
                    params={"tenant_id": x_tenant_id},
                    headers={"X-Tenant-ID": x_tenant_id},
                )
            else:
                resp = await client.post(
                    route["url"],
                    json=params_with_tenant,
                    headers={"X-Tenant-ID": x_tenant_id},
                )

            log.info("nlq.action_executed", status=resp.status_code)
            return {
                "ok": resp.status_code < 400,
                "data": {
                    "action_id": action_id,
                    "status_code": resp.status_code,
                    "result": resp.json() if resp.status_code < 400 else None,
                },
            }
    except httpx.TimeoutException:
        log.warning("nlq.action_timeout")
        return {
            "ok": False,
            "error": {"code": "ACTION_TIMEOUT", "message": "操作执行超时"},
        }
    except httpx.ConnectError:
        log.warning("nlq.action_unreachable")
        return {
            "ok": False,
            "error": {"code": "SERVICE_UNREACHABLE", "message": "目标服务不可达"},
        }


# ═══════════════════════════════════════════════════════════════════
# 保留旧端点（向后兼容）
# ═══════════════════════════════════════════════════════════════════

@router.post("/query")
async def nlq_query_compat(
    body: NLQAskRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """旧版 /query 端点 — 转发到 /ask"""
    return await nlq_ask(body, x_tenant_id, db)


# ═══════════════════════════════════════════════════════════════════
# 持久化辅助
# ═══════════════════════════════════════════════════════════════════

async def _save_message(
    db: AsyncSession,
    tenant_id: str,
    session_id: str,
    question: str,
    intent: str,
    answer: str,
) -> None:
    """将问答记录保存到 nlq_messages 表（best-effort，不阻塞主流程）"""
    try:
        # 确保 session 存在
        await db.execute(
            text(
                "INSERT INTO nlq_sessions (id, tenant_id, created_at)"
                " VALUES (:sid, :tid, NOW())"
                " ON CONFLICT (id) DO NOTHING"
            ),
            {"sid": session_id, "tid": tenant_id},
        )
        # 写用户消息
        await db.execute(
            text(
                "INSERT INTO nlq_messages"
                " (id, session_id, tenant_id, role, content, intent, created_at)"
                " VALUES (gen_random_uuid(), :sid, :tid, 'user', :content, :intent, NOW())"
            ),
            {"sid": session_id, "tid": tenant_id, "content": question, "intent": intent},
        )
        # 写助手回答
        await db.execute(
            text(
                "INSERT INTO nlq_messages"
                " (id, session_id, tenant_id, role, content, intent, created_at)"
                " VALUES (gen_random_uuid(), :sid, :tid, 'assistant', :content, :intent, NOW())"
            ),
            {"sid": session_id, "tid": tenant_id, "content": answer, "intent": intent},
        )
        await db.flush()
    except (SQLAlchemyError, ConnectionError) as exc:
        logger.warning("nlq.save_message_error", error=str(exc))
        # best-effort: 不影响主流程
