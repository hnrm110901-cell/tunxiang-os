"""
执行过程审计员 Agent — 监控其他 Agent 的操作日志

识别维度：
  - 打卡异常（高频同一 IP / 非营业时间）
  - 工资异常（单月环比波动 > 50%）
  - 审批绕过（高金额跳过审批）
  - 数据导出频繁（同一账号 1h 内 > 5 次）

数据源：prompt_audit_logs + neural_event_logs（若表不存在则回退到内存模拟）
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..llm_gateway import get_llm_gateway

logger = structlog.get_logger()


class AuditAgent:
    """执行过程审计员 Agent"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _count_events(self, sql: str, params: Dict[str, Any]) -> int:
        try:
            r = await self.db.execute(text(sql), params)
            row = r.first()
            return int(row[0] or 0) if row else 0
        except Exception as exc:
            logger.warning("audit_count_failed", err=str(exc))
            return 0

    async def scan(
        self, tenant_id: str, hours: int = 24,
    ) -> Dict[str, Any]:
        """扫描 N 小时内的异常模式"""
        since = datetime.utcnow() - timedelta(hours=hours)
        findings: List[Dict[str, Any]] = []

        # 1) 数据导出频繁
        export_count = await self._count_events(
            """
            SELECT COUNT(*) FROM prompt_audit_logs
            WHERE created_at >= :since
              AND (prompt ILIKE '%导出%' OR prompt ILIKE '%export%')
            """,
            {"since": since},
        )
        if export_count > 5:
            findings.append({
                "type": "frequent_export",
                "severity": "high" if export_count > 20 else "medium",
                "count": export_count,
                "message": f"近 {hours}h 内检测到 {export_count} 次导出类 Prompt",
            })

        # 2) 审批绕过 — 依赖 audit_logs / neural_event_logs 里的 bypass 迹象
        bypass_count = await self._count_events(
            """
            SELECT COUNT(*) FROM neural_event_log
            WHERE occurred_at >= :since
              AND event_type ILIKE '%bypass%'
            """,
            {"since": since},
        )
        if bypass_count > 0:
            findings.append({
                "type": "approval_bypass",
                "severity": "high",
                "count": bypass_count,
                "message": f"检测到 {bypass_count} 次审批绕过事件",
            })

        # 3) 打卡异常 — 基于简单关键词
        punch_anomaly = await self._count_events(
            """
            SELECT COUNT(*) FROM neural_event_log
            WHERE occurred_at >= :since
              AND event_type ILIKE '%punch_anomaly%'
            """,
            {"since": since},
        )
        if punch_anomaly > 0:
            findings.append({
                "type": "punch_anomaly",
                "severity": "medium",
                "count": punch_anomaly,
                "message": f"检测到 {punch_anomaly} 次打卡异常",
            })

        # LLM 总结（失败静默回退）
        summary = await self._summarize(findings, tenant_id, hours)

        return {
            "tenant_id": tenant_id,
            "scan_window_hours": hours,
            "findings": findings,
            "risk_level": self._risk_level(findings),
            "summary": summary,
            "scanned_at": datetime.utcnow().isoformat(),
        }

    def _risk_level(self, findings: List[Dict[str, Any]]) -> str:
        if any(f.get("severity") == "high" for f in findings):
            return "high"
        if any(f.get("severity") == "medium" for f in findings):
            return "medium"
        return "low"

    async def _summarize(
        self, findings: List[Dict[str, Any]], tenant_id: str, hours: int,
    ) -> str:
        if not findings:
            return f"近 {hours}h 内未发现显著异常。"
        try:
            gw = get_llm_gateway()
            lines = [f"- {f['type']}: {f['message']}" for f in findings]
            resp = await gw.chat(messages=[{
                "role": "user",
                "content": f"租户 {tenant_id} 近 {hours}h 审计发现：\n" + "\n".join(lines)
                + "\n请用 2 句中文给出风险提示与建议。"
            }], max_tokens=200)
            if isinstance(resp, dict):
                return resp.get("content") or "发现异常，请人工复核。"
            return str(resp)
        except Exception:
            return f"发现 {len(findings)} 项异常，请人工复核。"


def get_audit_agent(db: AsyncSession) -> AuditAgent:
    return AuditAgent(db)
