"""通用报表引擎 — 报表定义、执行、渲染、定时推送

支持60+报表的统一定义、参数化SQL执行、多格式导出、定时调度。
所有SQL使用 sqlalchemy.text() 参数化，金额字段自动 /100 转元。
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


# ──────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────

class ReportCategory(str, Enum):
    REVENUE = "revenue"
    DISH = "dish"
    AUDIT = "audit"
    MARGIN = "margin"
    COMMISSION = "commission"
    FINANCE = "finance"
    MEMBER = "member"
    SUPPLY = "supply"
    OPERATION = "operation"
    HR = "hr"


class ExportFormat(str, Enum):
    JSON = "json"
    CSV = "csv"
    EXCEL = "excel"


class SortDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


@dataclass
class FilterDef:
    """筛选器定义"""
    name: str               # 参数名 (SQL中的 :name)
    label: str              # 显示名
    field_type: str         # string / date / date_range / select / number
    required: bool = False
    default: Any = None
    options: list[str] = field(default_factory=list)  # field_type=select 时可用选项


@dataclass
class MetricDef:
    """指标定义"""
    name: str               # SQL列名
    label: str              # 显示名
    unit: str = ""          # 单位: yuan / count / pct / minutes
    is_money_fen: bool = False  # True表示原始值为分，展示时自动/100


@dataclass
class DimensionDef:
    """维度定义"""
    name: str               # SQL列名
    label: str              # 显示名


@dataclass
class ReportDefinition:
    """报表定义 — 描述一张报表的元数据和SQL模板"""
    report_id: str
    name: str
    category: ReportCategory
    description: str
    sql_template: str           # SQL模板，支持 :param 参数 + {dim_clause} 动态维度
    dimensions: list[DimensionDef] = field(default_factory=list)
    metrics: list[MetricDef] = field(default_factory=list)
    filters: list[FilterDef] = field(default_factory=list)
    default_sort: str = ""
    default_sort_direction: SortDirection = SortDirection.DESC
    permissions: list[str] = field(default_factory=list)  # 允许的角色
    is_active: bool = True


@dataclass
class ReportResult:
    """报表执行结果"""
    report_id: str
    report_name: str
    executed_at: datetime
    params: dict[str, Any]
    columns: list[str]          # 列名列表
    rows: list[dict[str, Any]]  # 数据行(金额已转元)
    total_rows: int
    metadata: dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────
# 报表引擎核心
# ──────────────────────────────────────────────

class ReportEngine:
    """报表引擎 — 解析定义、构建SQL、执行查询、转换结果"""

    def __init__(self, registry: Any = None):
        """
        Args:
            registry: ReportRegistry 实例，用于查找报表定义
        """
        self._registry = registry

    def set_registry(self, registry: Any) -> None:
        self._registry = registry

    async def execute_report(
        self,
        report_id: str,
        params: dict[str, Any],
        tenant_id: str,
        db: AsyncSession,
        *,
        page: int = 1,
        page_size: int = 100,
        sort_by: Optional[str] = None,
        sort_dir: Optional[SortDirection] = None,
    ) -> ReportResult:
        """执行报表查询

        Args:
            report_id: 报表ID
            params: 查询参数 (对应 FilterDef 中定义的参数名)
            tenant_id: 租户ID
            db: 异步数据库会话
            page: 页码(从1开始)
            page_size: 每页条数
            sort_by: 排序字段
            sort_dir: 排序方向

        Returns:
            ReportResult 包含列名、数据行(金额已转元)、总行数
        """
        if self._registry is None:
            raise RuntimeError("ReportEngine has no registry attached")

        definition = self._registry.get(report_id)
        if definition is None:
            raise ReportNotFoundError(f"Report not found: {report_id}")

        if not definition.is_active:
            raise ReportInactiveError(f"Report is inactive: {report_id}")

        log.info(
            "report_engine.execute",
            report_id=report_id,
            tenant_id=tenant_id,
            params=params,
            page=page,
            page_size=page_size,
        )

        # 构建完整SQL
        sql, bind_params = self._build_sql(
            definition, params, tenant_id,
            page=page, page_size=page_size,
            sort_by=sort_by, sort_dir=sort_dir,
        )

        # 执行查询
        result = await db.execute(text(sql), bind_params)
        rows_raw = result.mappings().all()

        # 金额字段 fen→yuan 转换
        money_fields = {m.name for m in definition.metrics if m.is_money_fen}
        rows = [self._convert_row(dict(r), money_fields) for r in rows_raw]

        # 列名
        all_columns = [d.name for d in definition.dimensions] + [m.name for m in definition.metrics]

        # 总行数（简化：不带分页执行count查询）
        total_rows = len(rows)
        if len(rows) == page_size:
            # 可能有更多数据，执行count查询
            count_sql, count_params = self._build_count_sql(definition, params, tenant_id)
            count_result = await db.execute(text(count_sql), count_params)
            total_rows = int(count_result.scalar() or 0)

        return ReportResult(
            report_id=report_id,
            report_name=definition.name,
            executed_at=datetime.now(timezone.utc),
            params=params,
            columns=all_columns,
            rows=rows,
            total_rows=total_rows,
            metadata={
                "page": page,
                "page_size": page_size,
                "category": definition.category.value,
            },
        )

    async def list_reports(
        self,
        category: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """列出可用报表目录

        Args:
            category: 按分类过滤 (可选)
            tenant_id: 租户ID (预留权限过滤)

        Returns:
            报表摘要列表
        """
        if self._registry is None:
            raise RuntimeError("ReportEngine has no registry attached")

        if category:
            definitions = self._registry.get_by_category(category)
        else:
            definitions = self._registry.get_all()

        return [
            {
                "report_id": d.report_id,
                "name": d.name,
                "category": d.category.value,
                "description": d.description,
                "is_active": d.is_active,
                "dimensions": [{"name": dim.name, "label": dim.label} for dim in d.dimensions],
                "metrics": [
                    {"name": m.name, "label": m.label, "unit": m.unit}
                    for m in d.metrics
                ],
                "filters": [
                    {
                        "name": f.name, "label": f.label,
                        "field_type": f.field_type, "required": f.required,
                        "default": f.default, "options": f.options,
                    }
                    for f in d.filters
                ],
                "permissions": d.permissions,
            }
            for d in definitions
            if d.is_active
        ]

    async def get_report_metadata(self, report_id: str) -> dict[str, Any]:
        """获取单个报表的完整元数据"""
        if self._registry is None:
            raise RuntimeError("ReportEngine has no registry attached")

        d = self._registry.get(report_id)
        if d is None:
            raise ReportNotFoundError(f"Report not found: {report_id}")

        return {
            "report_id": d.report_id,
            "name": d.name,
            "category": d.category.value,
            "description": d.description,
            "is_active": d.is_active,
            "sql_template": d.sql_template,
            "dimensions": [{"name": dim.name, "label": dim.label} for dim in d.dimensions],
            "metrics": [
                {"name": m.name, "label": m.label, "unit": m.unit, "is_money_fen": m.is_money_fen}
                for m in d.metrics
            ],
            "filters": [
                {
                    "name": f.name, "label": f.label,
                    "field_type": f.field_type, "required": f.required,
                    "default": f.default, "options": f.options,
                }
                for f in d.filters
            ],
            "default_sort": d.default_sort,
            "default_sort_direction": d.default_sort_direction.value,
            "permissions": d.permissions,
        }

    # ─── 内部方法 ───

    def _build_sql(
        self,
        definition: ReportDefinition,
        params: dict[str, Any],
        tenant_id: str,
        *,
        page: int = 1,
        page_size: int = 100,
        sort_by: Optional[str] = None,
        sort_dir: Optional[SortDirection] = None,
    ) -> tuple[str, dict[str, Any]]:
        """根据定义和参数构建最终SQL

        Returns:
            (sql_string, bind_params)
        """
        sql = definition.sql_template
        bind_params: dict[str, Any] = {"tenant_id": tenant_id}

        # 填充用户参数
        for f in definition.filters:
            if f.name in params:
                bind_params[f.name] = params[f.name]
            elif f.required:
                raise ReportParamError(f"Missing required parameter: {f.name}")
            elif f.default is not None:
                bind_params[f.name] = f.default

        # 排序
        effective_sort = sort_by or definition.default_sort
        effective_dir = sort_dir or definition.default_sort_direction
        if effective_sort:
            # 安全校验：排序字段必须是已定义的维度或指标名
            valid_columns = {d.name for d in definition.dimensions} | {m.name for m in definition.metrics}
            if effective_sort in valid_columns:
                sql = sql.rstrip().rstrip(";")
                sql += f"\nORDER BY {effective_sort} {effective_dir.value}"

        # 分页
        offset = (page - 1) * page_size
        sql = sql.rstrip().rstrip(";")
        sql += "\nLIMIT :_limit OFFSET :_offset"
        bind_params["_limit"] = page_size
        bind_params["_offset"] = offset

        return sql, bind_params

    def _build_count_sql(
        self,
        definition: ReportDefinition,
        params: dict[str, Any],
        tenant_id: str,
    ) -> tuple[str, dict[str, Any]]:
        """构建 COUNT 查询用于获取总行数"""
        bind_params: dict[str, Any] = {"tenant_id": tenant_id}

        for f in definition.filters:
            if f.name in params:
                bind_params[f.name] = params[f.name]
            elif f.default is not None:
                bind_params[f.name] = f.default

        count_sql = f"SELECT COUNT(*) FROM ({definition.sql_template.rstrip().rstrip(';')}) AS _sub"
        return count_sql, bind_params

    @staticmethod
    def _convert_row(row: dict[str, Any], money_fields: set[str]) -> dict[str, Any]:
        """将分字段转为元(保留2位小数)"""
        converted = {}
        for k, v in row.items():
            if k in money_fields and v is not None:
                # fen → yuan，保留2位
                yuan_key = k.replace("_fen", "_yuan") if k.endswith("_fen") else f"{k}_yuan"
                converted[yuan_key] = round(int(v) / 100, 2)
                converted[k] = int(v)  # 保留原始分值
            else:
                converted[k] = v
        return converted


# ──────────────────────────────────────────────
# 报表渲染器
# ──────────────────────────────────────────────

class ReportRenderer:
    """将 ReportResult 渲染为不同格式"""

    @staticmethod
    def to_json(result: ReportResult) -> dict[str, Any]:
        """转为JSON字典(适合API返回)"""
        return {
            "report_id": result.report_id,
            "report_name": result.report_name,
            "executed_at": result.executed_at.isoformat(),
            "params": result.params,
            "columns": result.columns,
            "rows": result.rows,
            "total_rows": result.total_rows,
            "metadata": result.metadata,
        }

    @staticmethod
    def to_csv(result: ReportResult) -> str:
        """转为CSV字符串"""
        if not result.rows:
            return ""

        output = io.StringIO()
        # 使用实际数据行的键作为列头(包含转换后的yuan字段)
        fieldnames = list(result.rows[0].keys()) if result.rows else result.columns
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in result.rows:
            writer.writerow(row)
        return output.getvalue()

    @staticmethod
    def to_excel(result: ReportResult) -> bytes:
        """转为Excel bytes (openpyxl)

        Returns:
            xlsx 文件的 bytes 内容

        Raises:
            ImportError: 如果 openpyxl 未安装
        """
        try:
            import openpyxl
        except ImportError as e:
            raise ImportError("openpyxl is required for Excel export: pip install openpyxl") from e

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = result.report_name[:31]  # Excel sheet名最长31字符

        if not result.rows:
            ws.append(["No data"])
            buf = io.BytesIO()
            wb.save(buf)
            return buf.getvalue()

        # 写表头
        headers = list(result.rows[0].keys())
        ws.append(headers)

        # 写数据行
        for row in result.rows:
            ws.append([row.get(h) for h in headers])

        # 自动列宽
        for col_idx, header in enumerate(headers, 1):
            max_len = len(str(header))
            for row in result.rows[:50]:  # 取前50行估算宽度
                cell_val = str(row.get(header, ""))
                max_len = max(max_len, len(cell_val))
            ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = min(max_len + 2, 50)

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    @staticmethod
    def to_summary(result: ReportResult) -> str:
        """转为文字摘要(给Agent用)

        生成可读的中文摘要文本，包含报表名、执行时间、关键数据。
        """
        lines = [
            f"报表: {result.report_name}",
            f"执行时间: {result.executed_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"总行数: {result.total_rows}",
        ]

        if result.params:
            param_str = ", ".join(f"{k}={v}" for k, v in result.params.items())
            lines.append(f"查询参数: {param_str}")

        lines.append("")

        if not result.rows:
            lines.append("无数据")
            return "\n".join(lines)

        # 展示前10行数据
        display_rows = result.rows[:10]
        headers = list(display_rows[0].keys())

        # 简单表格
        lines.append(" | ".join(headers))
        lines.append("-" * 60)
        for row in display_rows:
            vals = [str(row.get(h, "")) for h in headers]
            lines.append(" | ".join(vals))

        if result.total_rows > 10:
            lines.append(f"... 还有 {result.total_rows - 10} 行")

        return "\n".join(lines)


# ──────────────────────────────────────────────
# 报表定时调度器
# ──────────────────────────────────────────────

@dataclass
class ScheduleConfig:
    """定时报表配置"""
    schedule_id: str
    report_id: str
    cron_expression: str        # cron表达式 (如 "0 8 * * *" 每天8点)
    recipients: list[str]       # 接收人列表 (user_id / email / webhook_url)
    channel: str                # 推送渠道: email / webhook / wechat
    params: dict[str, Any] = field(default_factory=dict)  # 报表参数
    export_format: ExportFormat = ExportFormat.JSON
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tenant_id: str = ""


class ReportScheduler:
    """报表定时调度器

    管理报表定时任务的创建、查询、执行。
    实际的 cron 触发由外部调度器(如 APScheduler / celery beat)驱动，
    本类提供配置管理和执行逻辑。
    """

    def __init__(self, engine: ReportEngine, renderer: ReportRenderer):
        self._engine = engine
        self._renderer = renderer
        # 内存存储(生产环境应持久化到DB)
        self._schedules: dict[str, ScheduleConfig] = {}

    async def schedule_report(
        self,
        report_id: str,
        cron_expression: str,
        recipients: list[str],
        channel: str,
        tenant_id: str,
        db: AsyncSession,
        *,
        params: Optional[dict[str, Any]] = None,
        export_format: ExportFormat = ExportFormat.JSON,
    ) -> ScheduleConfig:
        """创建定时报表任务

        Args:
            report_id: 报表ID
            cron_expression: cron表达式
            recipients: 接收人列表
            channel: 推送渠道
            tenant_id: 租户ID
            db: 数据库会话
            params: 报表参数
            export_format: 导出格式

        Returns:
            创建的 ScheduleConfig
        """
        # 校验报表存在
        metadata = await self._engine.get_report_metadata(report_id)

        schedule_id = f"sched_{report_id}_{tenant_id}_{len(self._schedules)}"
        config = ScheduleConfig(
            schedule_id=schedule_id,
            report_id=report_id,
            cron_expression=cron_expression,
            recipients=recipients,
            channel=channel,
            params=params or {},
            export_format=export_format,
            tenant_id=tenant_id,
        )
        self._schedules[schedule_id] = config

        log.info(
            "report_scheduler.created",
            schedule_id=schedule_id,
            report_id=report_id,
            cron=cron_expression,
            tenant_id=tenant_id,
        )
        return config

    async def run_scheduled(
        self,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """执行租户下所有到期的定时报表

        Returns:
            执行结果列表 [{"schedule_id", "report_id", "status", "detail"}]
        """
        results = []
        tenant_schedules = [
            s for s in self._schedules.values()
            if s.tenant_id == tenant_id and s.is_active
        ]

        for config in tenant_schedules:
            try:
                report_result = await self._engine.execute_report(
                    config.report_id, config.params, tenant_id, db,
                )
                # 渲染
                if config.export_format == ExportFormat.CSV:
                    rendered = self._renderer.to_csv(report_result)
                elif config.export_format == ExportFormat.JSON:
                    rendered = self._renderer.to_json(report_result)
                else:
                    rendered = self._renderer.to_summary(report_result)

                # 推送(预留接口 — 实际推送由外部集成实现)
                log.info(
                    "report_scheduler.executed",
                    schedule_id=config.schedule_id,
                    report_id=config.report_id,
                    channel=config.channel,
                    recipients_count=len(config.recipients),
                    tenant_id=tenant_id,
                )
                results.append({
                    "schedule_id": config.schedule_id,
                    "report_id": config.report_id,
                    "status": "success",
                    "rows_generated": report_result.total_rows,
                })
            except (ReportNotFoundError, ReportParamError) as e:
                log.error(
                    "report_scheduler.failed",
                    schedule_id=config.schedule_id,
                    error=str(e),
                    tenant_id=tenant_id,
                )
                results.append({
                    "schedule_id": config.schedule_id,
                    "report_id": config.report_id,
                    "status": "error",
                    "detail": str(e),
                })

        return results

    async def get_schedule_list(
        self,
        tenant_id: str,
        db: Optional[AsyncSession] = None,
    ) -> list[dict[str, Any]]:
        """获取租户下所有定时报表配置"""
        return [
            {
                "schedule_id": s.schedule_id,
                "report_id": s.report_id,
                "cron_expression": s.cron_expression,
                "recipients": s.recipients,
                "channel": s.channel,
                "export_format": s.export_format.value,
                "is_active": s.is_active,
                "created_at": s.created_at.isoformat(),
            }
            for s in self._schedules.values()
            if s.tenant_id == tenant_id
        ]

    async def delete_schedule(self, schedule_id: str, tenant_id: str) -> bool:
        """删除定时报表"""
        config = self._schedules.get(schedule_id)
        if config and config.tenant_id == tenant_id:
            del self._schedules[schedule_id]
            log.info("report_scheduler.deleted", schedule_id=schedule_id, tenant_id=tenant_id)
            return True
        return False


# ──────────────────────────────────────────────
# 异常类
# ──────────────────────────────────────────────

class ReportNotFoundError(ValueError):
    """报表定义不存在"""
    pass


class ReportInactiveError(ValueError):
    """报表已停用"""
    pass


class ReportParamError(ValueError):
    """报表参数错误"""
    pass
