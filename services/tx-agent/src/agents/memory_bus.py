"""Agent Memory Bus — Agent 间洞察共享

Agent 发布洞察（finding），其他 Agent 可订阅感知。
用于跨 Agent 协同：如库存 Agent 发现低库存 → 排菜 Agent 自动调整推荐。
"""
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import structlog

logger = structlog.get_logger()


@dataclass
class Finding:
    """Agent 洞察"""
    agent_id: str
    finding_type: str
    data: dict
    confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)
    store_id: Optional[str] = None
    ttl_seconds: int = 3600  # 默认 1 小时有效


class MemoryBus:
    """Agent Memory Bus — 进程内实现（生产环境可升级为 Redis Streams）"""

    _instance: Optional["MemoryBus"] = None

    def __init__(self):
        self._findings: dict[str, list[Finding]] = defaultdict(list)
        self._max_per_type = 100

    @classmethod
    def get_instance(cls) -> "MemoryBus":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def publish(self, finding: Finding) -> None:
        """发布洞察"""
        findings = self._findings[finding.finding_type]
        findings.append(finding)
        # 保持每类型最多 100 条
        if len(findings) > self._max_per_type:
            self._findings[finding.finding_type] = findings[-self._max_per_type:]

        logger.info(
            "finding_published",
            agent=finding.agent_id,
            type=finding.finding_type,
            confidence=finding.confidence,
        )

    def get_recent(
        self,
        finding_type: str,
        limit: int = 10,
        min_confidence: float = 0.0,
        store_id: Optional[str] = None,
    ) -> list[Finding]:
        """获取最近的洞察"""
        now = time.time()
        findings = self._findings.get(finding_type, [])

        result = [
            f for f in findings
            if (now - f.timestamp) < f.ttl_seconds
            and f.confidence >= min_confidence
            and (store_id is None or f.store_id == store_id)
        ]

        return sorted(result, key=lambda f: f.timestamp, reverse=True)[:limit]

    def get_peer_context(
        self,
        exclude_agent: str,
        store_id: Optional[str] = None,
        limit: int = 5,
    ) -> list[dict]:
        """获取其他 Agent 的最近洞察（注入 LLM 上下文用）"""
        now = time.time()
        all_findings = []
        for findings in self._findings.values():
            for f in findings:
                if f.agent_id != exclude_agent and (now - f.timestamp) < f.ttl_seconds:
                    if store_id is None or f.store_id == store_id:
                        all_findings.append(f)

        all_findings.sort(key=lambda f: f.timestamp, reverse=True)
        return [
            {
                "agent": f.agent_id,
                "type": f.finding_type,
                "data": f.data,
                "confidence": f.confidence,
                "age_seconds": int(now - f.timestamp),
            }
            for f in all_findings[:limit]
        ]

    def clear(self) -> None:
        """清空所有洞察（测试用）"""
        self._findings.clear()
