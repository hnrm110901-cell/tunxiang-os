"""企微会话存档 + AI客诉识别 业务逻辑

职责：
  - 拉取加密会话数据（调用 WeComChatArchiveSDK）
  - 调用 ComplaintDetectionAgent 分析消息
  - 存储客诉记录（当前 Phase 2 使用内存，Phase 3 迁移至 DB）
  - 客诉工单流转
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog

from shared.integrations.wecom_chat_archive import get_chat_archive_sdk
from agents.complaint_detection_agent import (
    ComplaintDetectionAgent,
    get_complaint_detection_agent,
)

logger = structlog.get_logger(__name__)


class WeComChatArchiveService:
    """企微会话存档服务"""

    def __init__(self) -> None:
        self._sdk = get_chat_archive_sdk()
        self._agent = get_complaint_detection_agent()
        # Phase 2: 内存存储；Phase 3: 迁移至 DB
        self._complaints: dict[str, dict[str, Any]] = {}
        self._messages: list[dict[str, Any]] = []

    async def check_permission(self) -> dict[str, Any]:
        """检查会话存档权限。"""
        return await self._sdk.get_permission()

    async def fetch_and_analyze(self, seq: int = 0, limit: int = 100) -> dict[str, Any]:
        """拉取加密会话数据并执行客诉分析。

        Args:
            seq: 起始序列号
            limit: 拉取条数

        Returns:
            {seq, total, complaints_found, messages, complaints}
        """
        raw = await self._sdk.get_raw_data(seq, limit)
        raw_list = raw.get("raw_data_list", [])

        # 解析消息（Mock 模式下直接返回模拟数据）
        parsed: list[dict[str, Any]] = []
        for item in raw_list:
            parsed.append({
                "msgid": item.get("msgid", str(uuid.uuid4())),
                "seq": item.get("seq", seq),
                "content": "模拟消息内容：等待真实解密实现",  # Phase 2 占位
                "sender": "mock_user",
                "timestamp": datetime.now().isoformat(),
            })

        # AI 客诉分析
        analyzed = self._agent.analyze_batch(parsed)

        # 记录客诉
        complaints_found = []
        for msg in analyzed:
            complaint = msg.get("complaint", {})
            if complaint.get("is_complaint"):
                cid = str(uuid.uuid4())
                self._complaints[cid] = {
                    "id": cid,
                    "msgid": msg["msgid"],
                    "content": msg["content"],
                    "sender": msg["sender"],
                    "severity": complaint["severity"],
                    "category": complaint["category"],
                    "matched_keywords": complaint["matched_keywords"],
                    "confidence": complaint["confidence"],
                    "summary": complaint["summary"],
                    "status": "open",
                    "created_at": datetime.now().isoformat(),
                }
                complaints_found.append(self._complaints[cid])

        self._messages.extend(analyzed)

        logger.info(
            "chat_archive.fetch_and_analyze",
            seq=seq,
            total=len(analyzed),
            complaints=len(complaints_found),
        )

        return {
            "seq": seq,
            "total": len(analyzed),
            "complaints_found": len(complaints_found),
            "messages": analyzed,
            "complaints": complaints_found,
        }

    def list_complaints(
        self,
        severity: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """查询客诉记录。"""
        results = list(self._complaints.values())
        if severity:
            results = [c for c in results if c["severity"] == severity]
        if status:
            results = [c for c in results if c["status"] == status]
        results.sort(key=lambda c: c["created_at"], reverse=True)
        return results[:limit]

    def get_complaint(self, complaint_id: str) -> dict[str, Any] | None:
        """获取客诉详情。"""
        return self._complaints.get(complaint_id)

    def update_complaint_status(
        self,
        complaint_id: str,
        status: str,
        handler: str = "",
        note: str = "",
    ) -> dict[str, Any] | None:
        """更新客诉处理状态。

        Args:
            complaint_id: 客诉 ID
            status: 新状态（open / handling / resolved / closed）
            handler: 处理人
            note: 处理备注
        """
        record = self._complaints.get(complaint_id)
        if not record:
            return None
        record["status"] = status
        if handler:
            record["handler"] = handler
        if note:
            record["note"] = note
        record["updated_at"] = datetime.now().isoformat()

        logger.info(
            "chat_archive.complaint_updated",
            complaint_id=complaint_id,
            status=status,
            handler=handler,
        )
        return record


# ─── 全局单例 ───

_instance: WeComChatArchiveService | None = None


def get_chat_archive_service() -> WeComChatArchiveService:
    global _instance
    if _instance is None:
        _instance = WeComChatArchiveService()
    return _instance
