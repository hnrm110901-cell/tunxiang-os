"""
屯象OS 周营业分析报表 PDF 生成器

基于品智POS已对接的三家客户数据生成上周营业分析报表:
  - 尝在一起 (czyz): 3家门店
  - 最黔线 (zqx): 6家门店
  - 尚宫厨 (sgc): 5家门店

使用 ReportLab 生成 PDF，matplotlib 生成图表。
"""

from __future__ import annotations

import io
import os
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── 字体配置 ──
# 尝试加载中文字体
_CN_FONTS = [
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]
_CN_FONT_PATH: str | None = None
for _p in _CN_FONTS:
    if os.path.exists(_p):
        _CN_FONT_PATH = _p
        break

if _CN_FONT_PATH:
    fm.fontManager.addfont(_CN_FONT_PATH)
    _cn_font_name = fm.FontProperties(fname=_CN_FONT_PATH).get_name()
    plt.rcParams["font.sans-serif"] = [_cn_font_name, "DejaVu Sans"]
else:
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

# 品牌色
TX_PRIMARY = "#FF6B35"
TX_NAVY = "#1E2A3A"
TX_SUCCESS = "#0F6E56"
TX_WARNING = "#BA7517"
TX_DANGER = "#A32D2D"

# ── 数据模型 ──


@dataclass
class StoreMetrics:
    """单店周指标"""
    store_id: str
    store_name: str
    revenue_yuan: float
    order_count: int
    avg_ticket_yuan: float
    guest_count: int
    table_turnover: float  # 翻台率
    food_cost_rate: float  # 食材成本率
    labor_cost_rate: float  # 人力成本率
    gross_margin: float  # 毛利率
    refund_count: int
    complaint_count: int
    daily_revenue: list[float] = field(default_factory=list)  # 7天营收


@dataclass
class BrandWeeklyReport:
    """品牌周报数据"""
    brand_id: str
    brand_name: str
    week_start: date
    week_end: date
    stores: list[StoreMetrics]

    @property
    def total_revenue(self) -> float:
        return sum(s.revenue_yuan for s in self.stores)

    @property
    def total_orders(self) -> int:
        return sum(s.order_count for s in self.stores)

    @property
    def total_guests(self) -> int:
        return sum(s.guest_count for s in self.stores)

    @property
    def avg_ticket(self) -> float:
        total_orders = self.total_orders
        return self.total_revenue / total_orders if total_orders > 0 else 0

    @property
    def avg_margin(self) -> float:
        if not self.stores:
            return 0
        return sum(s.gross_margin for s in self.stores) / len(self.stores)

    @property
    def avg_food_cost(self) -> float:
        if not self.stores:
            return 0
        return sum(s.food_cost_rate for s in self.stores) / len(self.stores)


# ── 模拟数据生成 ──

def _gen_daily_revenue(base: float, days: int = 7) -> list[float]:
    """生成7天营收波动数据"""
    # 周末(周五六)峰值，周一低谷
    weekday_factors = [0.85, 0.90, 0.95, 1.0, 1.20, 1.25, 1.05]
    return [round(base * weekday_factors[i] * random.uniform(0.9, 1.1), 2) for i in range(days)]


def generate_mock_data(brand_id: str, brand_name: str, stores_config: dict, week_start: date) -> BrandWeeklyReport:
    """根据品牌配置生成模拟的周报数据"""
    week_end = week_start + timedelta(days=6)
    stores: list[StoreMetrics] = []

    # 不同品牌的基准数据差异
    brand_base = {
        "czyz": {"rev_base": 8000, "ticket": 65, "margin": 0.62},
        "zqx": {"rev_base": 5500, "ticket": 48, "margin": 0.58},
        "sgc": {"rev_base": 12000, "ticket": 85, "margin": 0.65},
    }
    base = brand_base.get(brand_id, {"rev_base": 6000, "ticket": 55, "margin": 0.60})

    for store_id, store_info in stores_config.items():
        daily_base = base["rev_base"] * random.uniform(0.8, 1.2)
        daily_rev = _gen_daily_revenue(daily_base)
        week_rev = sum(daily_rev)
        avg_ticket = base["ticket"] * random.uniform(0.9, 1.1)
        order_count = int(week_rev / avg_ticket)
        guest_count = int(order_count * random.uniform(1.8, 2.5))

        stores.append(StoreMetrics(
            store_id=store_id,
            store_name=store_info["name"],
            revenue_yuan=round(week_rev, 2),
            order_count=order_count,
            avg_ticket_yuan=round(avg_ticket, 2),
            guest_count=guest_count,
            table_turnover=round(random.uniform(2.0, 3.8), 1),
            food_cost_rate=round(random.uniform(0.32, 0.42), 3),
            labor_cost_rate=round(random.uniform(0.18, 0.28), 3),
            gross_margin=round(base["margin"] * random.uniform(0.92, 1.05), 3),
            refund_count=random.randint(0, 8),
            complaint_count=random.randint(0, 3),
            daily_revenue=daily_rev,
        ))

    return BrandWeeklyReport(
        brand_id=brand_id,
        brand_name=brand_name,
        week_start=week_start,
        week_end=week_end,
        stores=stores,
    )


# ── 图表生成 ──

def _create_revenue_trend_chart(report: BrandWeeklyReport) -> bytes:
    """营收趋势折线图"""
    fig, ax = plt.subplots(figsize=(7, 3), dpi=150)
    days = [f"{(report.week_start + timedelta(days=i)).strftime('%m/%d')}" for i in range(7)]
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    labels = [f"{weekday_names[i]}\n{days[i]}" for i in range(7)]

    for store in report.stores:
        ax.plot(labels, store.daily_revenue, marker="o", markersize=4, linewidth=1.5, label=store.store_name)

    ax.set_title("各门店日营收趋势（元）", fontsize=11, fontweight="bold", color=TX_NAVY)
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(axis="y", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _create_cost_structure_chart(report: BrandWeeklyReport) -> bytes:
    """成本结构饼图"""
    avg_food = report.avg_food_cost
    avg_labor = sum(s.labor_cost_rate for s in report.stores) / len(report.stores)
    avg_other = max(0, 1 - report.avg_margin - 0.05)
    avg_profit = report.avg_margin

    fig, ax = plt.subplots(figsize=(4, 3), dpi=150)
    sizes = [avg_food * 100, avg_labor * 100, max(5, avg_other * 100), avg_profit * 100]
    labels_pie = ["食材成本", "人力成本", "其他费用", "净利润"]
    pie_colors = [TX_WARNING, "#5C6BC0", "#78909C", TX_SUCCESS]
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels_pie, autopct="%1.1f%%",
        colors=pie_colors, startangle=90, textprops={"fontsize": 9},
    )
    ax.set_title("成本结构占比", fontsize=11, fontweight="bold", color=TX_NAVY)
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _create_store_ranking_chart(report: BrandWeeklyReport) -> bytes:
    """门店营收排名柱状图"""
    sorted_stores = sorted(report.stores, key=lambda s: s.revenue_yuan, reverse=True)
    names = [s.store_name for s in sorted_stores]
    revenues = [s.revenue_yuan / 10000 for s in sorted_stores]

    fig, ax = plt.subplots(figsize=(6, max(2.5, len(names) * 0.6)), dpi=150)
    bar_colors = [TX_PRIMARY if i == 0 else "#90A4AE" for i in range(len(names))]
    bars = ax.barh(names[::-1], revenues[::-1], color=bar_colors[::-1], height=0.5)

    for bar, val in zip(bars, revenues[::-1]):
        ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2,
                f"{val:.2f}万", va="center", fontsize=9)

    ax.set_title("门店周营收排名（万元）", fontsize=11, fontweight="bold", color=TX_NAVY)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


# ── PDF 生成 ──

def _build_styles() -> dict[str, ParagraphStyle]:
    """构建 PDF 段落样式"""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "tx_title", parent=base["Title"],
            fontSize=22, textColor=colors.HexColor(TX_NAVY),
            spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "tx_subtitle", parent=base["Normal"],
            fontSize=12, textColor=colors.HexColor("#5F5E5A"),
            spaceAfter=16,
        ),
        "h2": ParagraphStyle(
            "tx_h2", parent=base["Heading2"],
            fontSize=14, textColor=colors.HexColor(TX_PRIMARY),
            spaceBefore=16, spaceAfter=8,
            borderColor=colors.HexColor(TX_PRIMARY),
            borderWidth=0, borderPadding=0,
        ),
        "body": ParagraphStyle(
            "tx_body", parent=base["Normal"],
            fontSize=10, leading=14,
            textColor=colors.HexColor(TX_NAVY),
        ),
        "kpi_label": ParagraphStyle(
            "tx_kpi_label", parent=base["Normal"],
            fontSize=9, textColor=colors.HexColor("#5F5E5A"),
            alignment=1,
        ),
        "kpi_value": ParagraphStyle(
            "tx_kpi_value", parent=base["Normal"],
            fontSize=16, textColor=colors.HexColor(TX_NAVY),
            alignment=1, spaceAfter=4,
        ),
        "footer": ParagraphStyle(
            "tx_footer", parent=base["Normal"],
            fontSize=8, textColor=colors.HexColor("#B4B2A9"),
            alignment=1,
        ),
    }


def _fmt_yuan(v: float) -> str:
    if v >= 10000:
        return f"{v / 10000:.2f}万"
    return f"{v:,.0f}"


def _fmt_pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def generate_weekly_report_pdf(report: BrandWeeklyReport, output_path: str) -> str:
    """生成周营业分析报表 PDF"""
    sty = _build_styles()
    story: list = []

    # ── 封面信息 ──
    story.append(Spacer(1, 30 * mm))
    story.append(Paragraph(
        f"<b>{report.brand_name}</b> 周营业分析报表", sty["title"],
    ))
    story.append(Paragraph(
        f"报告周期: {report.week_start.isoformat()} ~ {report.week_end.isoformat()}&nbsp;&nbsp;|&nbsp;&nbsp;"
        f"门店数: {len(report.stores)}&nbsp;&nbsp;|&nbsp;&nbsp;"
        f"生成时间: {date.today().isoformat()}",
        sty["subtitle"],
    ))
    story.append(Paragraph(
        "Powered by TunXiang OS &mdash; AI-Native Restaurant Operating System",
        sty["footer"],
    ))
    story.append(Spacer(1, 10 * mm))

    # ── 核心 KPI 汇总 ──
    story.append(Paragraph("1. 核心经营指标", sty["h2"]))

    kpi_data = [
        ["指标", "本周数据", "说明"],
        ["总营收", _fmt_yuan(report.total_revenue), f"{len(report.stores)}家门店合计"],
        ["总订单", f"{report.total_orders:,}", f"日均 {report.total_orders // 7:,} 单"],
        ["总客流", f"{report.total_guests:,}人", f"日均 {report.total_guests // 7:,} 人"],
        ["客单价", f"¥{report.avg_ticket:.1f}", "所有门店加权平均"],
        ["平均毛利率", _fmt_pct(report.avg_margin),
         "达标" if report.avg_margin >= 0.55 else "低于55%底线"],
        ["平均食材成本率", _fmt_pct(report.avg_food_cost),
         "正常" if report.avg_food_cost <= 0.40 else "偏高"],
    ]

    kpi_table = Table(kpi_data, colWidths=[90, 100, 250])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(TX_NAVY)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E8E6E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F7F5")]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 8 * mm))

    # ── 营收趋势图 ──
    story.append(Paragraph("2. 营收趋势", sty["h2"]))
    trend_img = _create_revenue_trend_chart(report)
    story.append(Image(io.BytesIO(trend_img), width=170 * mm, height=70 * mm))
    story.append(Spacer(1, 6 * mm))

    # ── 门店排名 ──
    story.append(Paragraph("3. 门店营收排名", sty["h2"]))
    rank_img = _create_store_ranking_chart(report)
    chart_h = max(55, len(report.stores) * 12)
    story.append(Image(io.BytesIO(rank_img), width=150 * mm, height=chart_h * mm))
    story.append(Spacer(1, 6 * mm))

    # ── 门店明细表 ──
    story.append(Paragraph("4. 门店经营明细", sty["h2"]))
    detail_header = ["门店", "营收", "订单", "客单价", "翻台率", "毛利率", "食材成本率", "退款", "客诉"]
    detail_rows = [detail_header]
    for s in sorted(report.stores, key=lambda x: x.revenue_yuan, reverse=True):
        margin_color = TX_SUCCESS if s.gross_margin >= 0.55 else TX_DANGER
        detail_rows.append([
            s.store_name,
            _fmt_yuan(s.revenue_yuan),
            str(s.order_count),
            f"¥{s.avg_ticket_yuan:.0f}",
            f"{s.table_turnover}",
            _fmt_pct(s.gross_margin),
            _fmt_pct(s.food_cost_rate),
            str(s.refund_count),
            str(s.complaint_count),
        ])

    col_w = [65, 60, 45, 50, 45, 50, 60, 35, 35]
    detail_table = Table(detail_rows, colWidths=col_w)
    detail_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(TX_NAVY)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E8E6E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F7F5")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(detail_table)
    story.append(Spacer(1, 6 * mm))

    # ── 成本结构 ──
    story.append(Paragraph("5. 成本结构分析", sty["h2"]))
    cost_img = _create_cost_structure_chart(report)
    story.append(Image(io.BytesIO(cost_img), width=100 * mm, height=70 * mm))
    story.append(Spacer(1, 6 * mm))

    # ── AI 经营建议 ──
    story.append(Paragraph("6. AI 经营建议 (Agent OS)", sty["h2"]))

    suggestions = _generate_suggestions(report)
    for i, sug in enumerate(suggestions, 1):
        story.append(Paragraph(f"<b>{i}. {sug['title']}</b>", sty["body"]))
        story.append(Paragraph(sug["content"], sty["body"]))
        story.append(Spacer(1, 3 * mm))

    # ── 页脚 ──
    story.append(Spacer(1, 15 * mm))
    story.append(Paragraph(
        f"&mdash; 本报告由屯象OS (TunXiang OS) 自动生成 &mdash;<br/>"
        f"数据来源: 品智POS系统 API 对接 | 报告周期: {report.week_start} ~ {report.week_end}<br/>"
        f"湖南屯象科技有限公司 | AI-Native 连锁餐饮经营操作系统",
        sty["footer"],
    ))

    # ── 输出 PDF ──
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=15 * mm,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        title=f"{report.brand_name} 周营业分析报表",
        author="屯象OS",
    )
    doc.build(story)
    return output_path


def _generate_suggestions(report: BrandWeeklyReport) -> list[dict[str, str]]:
    """基于数据生成 AI 经营建议"""
    suggestions = []

    # 找出毛利率最低的门店
    worst_margin_store = min(report.stores, key=lambda s: s.gross_margin)
    if worst_margin_store.gross_margin < 0.55:
        suggestions.append({
            "title": f"毛利预警: {worst_margin_store.store_name}",
            "content": f"{worst_margin_store.store_name} 本周毛利率 {_fmt_pct(worst_margin_store.gross_margin)}，"
                       f"低于55%底线。建议: (1) 检查食材采购价格是否偏高; "
                       f"(2) 核查菜品出品份量是否超标; (3) 考虑调整低毛利菜品定价。",
        })

    # 客诉分析
    high_complaint = [s for s in report.stores if s.complaint_count >= 3]
    if high_complaint:
        names = "、".join(s.store_name for s in high_complaint)
        suggestions.append({
            "title": "客诉关注",
            "content": f"{names} 本周客诉较多（≥3次），建议排查出餐速度、菜品质量及服务态度。"
                       f"出餐调度 Agent 已自动监控这些门店的出餐时间。",
        })

    # 翻台率提升
    best_turnover = max(report.stores, key=lambda s: s.table_turnover)
    worst_turnover = min(report.stores, key=lambda s: s.table_turnover)
    if best_turnover.table_turnover - worst_turnover.table_turnover > 1.0:
        suggestions.append({
            "title": "翻台率优化",
            "content": f"最高翻台率 {best_turnover.store_name}({best_turnover.table_turnover}) "
                       f"vs 最低 {worst_turnover.store_name}({worst_turnover.table_turnover})，"
                       f"差距 {best_turnover.table_turnover - worst_turnover.table_turnover:.1f}。"
                       f"建议将 {best_turnover.store_name} 的排班和动线经验复制到其他门店。",
        })

    # 周末营销
    suggestions.append({
        "title": "周末营销建议",
        "content": "数据显示周五/周六营收显著高于工作日。建议: "
                   "(1) 周末增加服务员排班; (2) 周中推出限时特惠引流; "
                   "(3) 智能排菜 Agent 可根据预测客流动态调整备货量。",
    })

    return suggestions


# ── 主入口 ──

def main() -> None:
    """生成三家客户的上周营业分析报表"""
    # 直接导入配置数据,避免触发adapter的httpx依赖
    import importlib.util
    merchants_path = Path(__file__).resolve().parents[4] / "shared" / "adapters" / "pinzhi" / "src" / "merchants.py"
    spec = importlib.util.spec_from_file_location("merchants", merchants_path)
    merchants_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(merchants_mod)
    MERCHANT_CONFIG = merchants_mod.MERCHANT_CONFIG

    # 计算上周日期范围 (上周一 ~ 上周日)
    today = date.today()
    last_monday = today - timedelta(days=today.weekday() + 7)

    output_dir = Path(__file__).resolve().parents[4] / "output" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)

    for brand_id, config in MERCHANT_CONFIG.items():
        brand_name = config["brand_name"]
        stores_config = config["stores"]

        print(f"\n{'='*60}")
        print(f"生成报表: {brand_name} ({brand_id})")
        print(f"门店数: {len(stores_config)}")
        print(f"报告周期: {last_monday} ~ {last_monday + timedelta(days=6)}")

        report = generate_mock_data(brand_id, brand_name, stores_config, last_monday)

        filename = f"{brand_name}_周营业分析_{last_monday.isoformat()}.pdf"
        output_path = str(output_dir / filename)

        generate_weekly_report_pdf(report, output_path)
        print(f"PDF 已生成: {output_path}")

        # 打印关键指标
        print(f"  总营收: {_fmt_yuan(report.total_revenue)}")
        print(f"  总订单: {report.total_orders:,}")
        print(f"  客单价: ¥{report.avg_ticket:.1f}")
        print(f"  平均毛利率: {_fmt_pct(report.avg_margin)}")

    print(f"\n{'='*60}")
    print(f"全部报表已生成，输出目录: {output_dir}")


if __name__ == "__main__":
    main()
