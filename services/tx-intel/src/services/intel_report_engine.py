"""情报周报/月报引擎 — 自动生成结构化报告

支持竞对周报、需求周报、新品周报、食材周报、区域周报、月度市场报告、专题报告。
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()


# ─── 常量 ───

REPORT_TYPES = [
    "competitor_weekly", "demand_weekly", "new_product_weekly",
    "ingredient_weekly", "district_weekly", "monthly_market",
    "special_topic",
]

REPORT_FORMATS = ["pdf", "html", "markdown", "json"]

FREQUENCIES = ["weekly", "biweekly", "monthly"]


# ─── 数据模型 ───

@dataclass
class ReportSection:
    """报告章节"""
    title: str
    content: str
    data: dict = field(default_factory=dict)
    charts: list[str] = field(default_factory=list)


@dataclass
class IntelReport:
    """情报报告"""
    report_id: str
    report_type: str
    title: str
    executive_summary: str
    sections: list[ReportSection] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    date_range: dict = field(default_factory=dict)
    city: str = ""
    generated_at: str = ""
    status: str = "generated"


@dataclass
class AutoSchedule:
    """自动报告计划"""
    schedule_id: str
    report_type: str
    frequency: str
    recipients: list[str]
    next_run: str = ""
    is_active: bool = True
    created_at: str = ""


class IntelReportEngine:
    """情报周报/月报引擎 — 自动生成结构化报告"""

    def __init__(self) -> None:
        self._reports: dict[str, IntelReport] = {}
        self._schedules: dict[str, AutoSchedule] = {}
        self._generate_sample_reports()

    def _generate_sample_reports(self) -> None:
        """生成示例报告"""
        now = datetime.now(timezone.utc)
        week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        week_end = now.strftime("%Y-%m-%d")

        self.generate_report("competitor_weekly", {"start": week_start, "end": week_end})
        self.generate_report("demand_weekly", {"start": week_start, "end": week_end})
        logger.info("sample_reports_generated", count=len(self._reports))

    # ─── 报告生成 ───

    def generate_report(
        self,
        report_type: str,
        date_range: dict,
        city: Optional[str] = None,
    ) -> dict:
        """生成情报报告"""
        if report_type not in REPORT_TYPES:
            raise ValueError(f"Invalid report_type: {report_type}, must be one of {REPORT_TYPES}")

        report_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)

        generators = {
            "competitor_weekly": self._gen_competitor_weekly,
            "demand_weekly": self._gen_demand_weekly,
            "new_product_weekly": self._gen_new_product_weekly,
            "ingredient_weekly": self._gen_ingredient_weekly,
            "district_weekly": self._gen_district_weekly,
            "monthly_market": self._gen_monthly_market,
            "special_topic": self._gen_special_topic,
        }

        gen_func = generators[report_type]
        title, summary, sections, recommendations = gen_func(date_range, city)

        report = IntelReport(
            report_id=report_id,
            report_type=report_type,
            title=title,
            executive_summary=summary,
            sections=sections,
            recommendations=recommendations,
            date_range=date_range,
            city=city or "全国",
            generated_at=now.isoformat(),
        )
        self._reports[report_id] = report

        return {
            "report_id": report_id,
            "report_type": report_type,
            "title": title,
            "executive_summary": summary,
            "sections": [{"title": s.title, "content": s.content} for s in sections],
            "recommendations": recommendations,
            "generated_at": now.isoformat(),
        }

    # ─── 各类报告生成器 ───

    def _gen_competitor_weekly(self, date_range: dict, city: Optional[str]) -> tuple:
        period = f"{date_range.get('start', '')} ~ {date_range.get('end', '')}"
        title = f"竞对动态周报（{period}）"
        summary = (
            "本周竞对动态活跃。海底捞推出'小嗨火锅'子品牌试水中端市场，"
            "费大厨深圳新开5店并上线酸汤系列，太二午市套餐降价15%。"
            "重点关注：费大厨在深圳扩张对我方门店的客流影响。"
        )
        sections = [
            ReportSection(
                title="一、重大竞对动态",
                content=(
                    "1. 海底捞推出'小嗨火锅'子品牌（影响力：高）\n"
                    "   - 人均60-80元，主打社区小火锅，首批30店成都试水\n"
                    "   - 影响评估：下探中端价格带，可能分流部分价格敏感客群\n\n"
                    "2. 费大厨深圳新开5家门店（影响力：高）\n"
                    "   - 南山区、福田区大店策略，月租超30万\n"
                    "   - 影响评估：与我方深圳门店直接竞争\n\n"
                    "3. 费大厨上线酸汤肥牛系列（影响力：中）\n"
                    "   - 3道新品，定价48-68元\n"
                    "   - 影响评估：蹭酸汤热度，需关注市场反馈"
                ),
            ),
            ReportSection(
                title="二、价格变动监测",
                content=(
                    "太二午市套餐降价15%（39.9元），望湘园菜单精简SKU从120+降至80。"
                    "行业整体呈现'精简SKU+套餐引流'趋势。"
                ),
            ),
            ReportSection(
                title="三、威胁与机会",
                content=(
                    "威胁：费大厨深圳扩张+爆品策略可能抢占市场份额\n"
                    "机会：海底捞长沙3店差评突增，可趁势加强本地营销\n"
                    "机会：酸汤品类热度持续，我方可快速跟进"
                ),
            ),
        ]
        recommendations = [
            "紧急：评估费大厨深圳新店对我方福田/南山门店的影响",
            "重要：加速酸汤系列菜品开发，建议2周内完成研发",
            "关注：海底捞长沙差评期，加强本地营销投放",
            "跟踪：太二降价对午市客流的影响数据",
        ]
        return title, summary, sections, recommendations

    def _gen_demand_weekly(self, date_range: dict, city: Optional[str]) -> tuple:
        period = f"{date_range.get('start', '')} ~ {date_range.get('end', '')}"
        title = f"消费需求周报（{period}）"
        summary = (
            "本周消费信号显示：亲子用餐需求持续上升，减脂/健康饮食成为新增长点，"
            "一人食套餐需求在工作日午市尤为突出。酸汤口味热度不减。"
        )
        sections = [
            ReportSection(
                title="一、需求热度TOP5",
                content=(
                    "1. 亲子用餐（信号数↑25%）— 周末家庭客群增长，儿童椅不足\n"
                    "2. 一人食/单人套餐（信号数↑18%）— 午市白领需求强劲\n"
                    "3. 酸汤口味（信号数↑15%）— 搜索趋势持续走高\n"
                    "4. 减脂健康餐（信号数↑12%）— 年轻女性群体推动\n"
                    "5. 等位体验优化（信号数持平）— 核心门店老问题"
                ),
            ),
            ReportSection(
                title="二、新兴需求信号",
                content=(
                    "- 养生湘菜：抖音话题播放量破亿，枸杞煲汤系列走红\n"
                    "- 微辣/不辣：非湘菜客群对辣度选择需求增加\n"
                    "- 生日宴打卡：微博上湘菜馆生日宴成新趋势"
                ),
            ),
        ]
        recommendations = [
            "产品：加快一人食午市套餐SKU扩充（目标3-5个选项）",
            "产品：评估推出'亲子友好'菜单标签",
            "体验：核心门店增配儿童椅和等位管理工具",
            "营销：借势养生湘菜趋势，策划社交媒体内容",
        ]
        return title, summary, sections, recommendations

    def _gen_new_product_weekly(self, date_range: dict, city: Optional[str]) -> tuple:
        period = f"{date_range.get('start', '')} ~ {date_range.get('end', '')}"
        title = f"新品雷达周报（{period}）"
        summary = (
            "本周新品机会排名：贵州酸汤鱼（综合评分最高，品牌适配度90%），"
            "小龙虾新做法（季节性爆品机会），酸汤火锅（市场热度最高但品牌适配需评估）。"
        )
        sections = [
            ReportSection(
                title="一、TOP3 新品机会",
                content=(
                    "1. 贵州酸汤鱼 — 综合评分0.85，品牌适配度极高\n"
                    "   与湘菜酸辣调性一致，费大厨已上线酸汤系列需快速跟进\n\n"
                    "2. 小龙虾新做法 — 综合评分0.80，季节性机会\n"
                    "   湘式口味虾是强项，可延伸酸汤/椰香新口味\n\n"
                    "3. 酸汤火锅 — 市场热度0.95，但品牌适配度中等\n"
                    "   需要评估是否适合湘菜品牌做品类延伸"
                ),
            ),
            ReportSection(
                title="二、食材趋势",
                content=(
                    "- 贵州红酸汤：供应成熟，可直接采购\n"
                    "- 藤椒：年轻人追捧，建议凉菜线增加\n"
                    "- 椰浆：东南亚融合趋势，椰香菜品增长"
                ),
            ),
        ]
        recommendations = [
            "立即：启动贵州酸汤鱼研发，目标2周内出品测试",
            "本月：策划小龙虾新做法（酸汤小龙虾）夏季上新",
            "评估：酸汤火锅子品牌/品类可行性调研",
        ]
        return title, summary, sections, recommendations

    def _gen_ingredient_weekly(self, date_range: dict, city: Optional[str]) -> tuple:
        period = f"{date_range.get('start', '')} ~ {date_range.get('end', '')}"
        title = f"食材趋势周报（{period}）"
        summary = "贵州红酸汤供应充足价格稳定，云南菌菇即将进入应季期，藤椒持续走红。"
        sections = [
            ReportSection(title="一、价格变动", content="本周主要食材价格平稳，猪肉价格微涨2%。"),
            ReportSection(title="二、趋势食材", content="藤椒、紫苏、椰浆持续走红，建议纳入采购计划。"),
        ]
        recommendations = ["关注：云南菌菇6月进入应季，提前锁定供应商", "执行：藤椒采购测试"]
        return title, summary, sections, recommendations

    def _gen_district_weekly(self, date_range: dict, city: Optional[str]) -> tuple:
        city_label = city or "全部区域"
        period = f"{date_range.get('start', '')} ~ {date_range.get('end', '')}"
        title = f"{city_label}区域周报（{period}）"
        summary = f"{city_label}本周经营平稳，客流量环比微增3%。"
        sections = [
            ReportSection(title="一、区域概览", content=f"{city_label}各门店运营指标正常。"),
            ReportSection(title="二、竞对区域动态", content="本区域内无重大竞对动态。"),
        ]
        recommendations = [f"维持{city_label}当前运营节奏"]
        return title, summary, sections, recommendations

    def _gen_monthly_market(self, date_range: dict, city: Optional[str]) -> tuple:
        period = f"{date_range.get('start', '')} ~ {date_range.get('end', '')}"
        title = f"月度市场情报综合报告（{period}）"
        summary = (
            "本月市场情报要点：竞对动态频繁（海底捞子品牌+费大厨扩张），"
            "消费需求向健康/亲子/一人食分化，酸汤品类热度持续。"
            "建议聚焦酸汤系列研发和亲子体验升级两大方向。"
        )
        sections = [
            ReportSection(title="一、竞对格局变化", content="海底捞下探中端，费大厨加速扩张，望湘园精简SKU。"),
            ReportSection(title="二、消费趋势", content="健康化、场景细分、套餐化三大趋势明确。"),
            ReportSection(title="三、新品机会", content="酸汤系列、季节限定、融合创新三条产品线机会。"),
            ReportSection(title="四、价格洞察", content="中端价格带竞争加剧，套餐引流成标配。"),
        ]
        recommendations = [
            "战略：加速酸汤系列产品线开发",
            "体验：全面升级亲子友好配置",
            "价格：优化午市套餐组合，应对竞对降价",
            "扩张：评估费大厨深圳扩张影响，加固存量门店",
        ]
        return title, summary, sections, recommendations

    def _gen_special_topic(self, date_range: dict, city: Optional[str]) -> tuple:
        title = "专题报告：酸汤品类机会分析"
        summary = "酸汤品类2025-2026年持续走红，市场规模预计超500亿，与湘菜品牌高度适配。"
        sections = [
            ReportSection(title="一、市场概况", content="酸汤火锅/酸汤鱼全国搜索量同比增长180%。"),
            ReportSection(title="二、竞对布局", content="费大厨已上线酸汤系列，巴奴推酸汤锅底。"),
            ReportSection(title="三、我方机会", content="湘菜酸辣调性与酸汤高度契合，研发门槛低。"),
        ]
        recommendations = [
            "2周内完成酸汤鱼研发和试吃",
            "1个月内3家门店试点上线",
            "评估是否开设酸汤主题子品牌",
        ]
        return title, summary, sections, recommendations

    # ─── 报告管理 ───

    def list_reports(
        self,
        report_type: Optional[str] = None,
        date_range: Optional[dict] = None,
    ) -> list[dict]:
        """列出报告"""
        results = []
        for r in self._reports.values():
            if report_type and r.report_type != report_type:
                continue
            results.append({
                "report_id": r.report_id,
                "report_type": r.report_type,
                "title": r.title,
                "city": r.city,
                "generated_at": r.generated_at,
                "status": r.status,
            })
        results.sort(key=lambda x: x["generated_at"], reverse=True)
        return results

    def get_report_detail(self, report_id: str) -> dict:
        """获取报告详情"""
        r = self._reports.get(report_id)
        if not r:
            raise KeyError(f"Report not found: {report_id}")
        return {
            "report_id": r.report_id,
            "report_type": r.report_type,
            "title": r.title,
            "executive_summary": r.executive_summary,
            "sections": [{"title": s.title, "content": s.content} for s in r.sections],
            "recommendations": r.recommendations,
            "date_range": r.date_range,
            "city": r.city,
            "generated_at": r.generated_at,
        }

    # ─── 自动报告调度 ───

    def schedule_auto_report(
        self,
        report_type: str,
        frequency: str,
        recipients: list[str],
    ) -> dict:
        """设置自动报告计划"""
        if report_type not in REPORT_TYPES:
            raise ValueError(f"Invalid report_type: {report_type}")
        if frequency not in FREQUENCIES:
            raise ValueError(f"Invalid frequency: {frequency}, must be one of {FREQUENCIES}")

        schedule_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)
        if frequency == "weekly":
            next_run = now + timedelta(days=7)
        elif frequency == "biweekly":
            next_run = now + timedelta(days=14)
        else:
            next_run = now + timedelta(days=30)

        schedule = AutoSchedule(
            schedule_id=schedule_id,
            report_type=report_type,
            frequency=frequency,
            recipients=recipients,
            next_run=next_run.isoformat(),
            created_at=now.isoformat(),
        )
        self._schedules[schedule_id] = schedule

        return {
            "schedule_id": schedule_id,
            "report_type": report_type,
            "frequency": frequency,
            "recipients": recipients,
            "next_run": next_run.isoformat(),
            "status": "active",
        }

    # ─── 导出 ───

    def export_report(self, report_id: str, format: str = "pdf") -> dict:
        """导出报告"""
        r = self._reports.get(report_id)
        if not r:
            raise KeyError(f"Report not found: {report_id}")
        if format not in REPORT_FORMATS:
            raise ValueError(f"Invalid format: {format}, must be one of {REPORT_FORMATS}")

        # 模拟导出
        filename = f"{r.report_type}_{report_id}.{format}"
        return {
            "report_id": report_id,
            "format": format,
            "filename": filename,
            "file_size_kb": 256,
            "download_url": f"/api/v1/intel/reports/{report_id}/download?format={format}",
            "status": "ready",
        }
