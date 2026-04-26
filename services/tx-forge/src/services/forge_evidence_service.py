"""Forge 证据卡片系统 — 对标 Salesforce AgentExchange Trust Signals

职责：
  1. create_card()            — 创建证据卡片
  2. list_cards()             — 分页列出证据卡片
  3. get_app_trust_profile()  — 应用信任画像（加权信任分）
  4. update_card()            — 更新卡片内容
  5. deactivate_expired()     — 批量停用过期卡片
"""

from __future__ import annotations

import json
from uuid import uuid4

import structlog
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import TRUST_TIERS

logger = structlog.get_logger(__name__)

# ── 证据卡片类型 + 权重 ──────────────────────────────────────
CARD_TYPES: dict[str, dict] = {
    "security_audit":    {"name": "安全审计",   "weight": 0.25},
    "performance_test":  {"name": "性能测试",   "weight": 0.15},
    "compliance_cert":   {"name": "合规认证",   "weight": 0.20},
    "user_review":       {"name": "用户评价",   "weight": 0.10},
    "uptime_sla":        {"name": "SLA 可用性", "weight": 0.15},
    "data_handling":     {"name": "数据处理",   "weight": 0.10},
    "incident_history":  {"name": "事故记录",   "weight": 0.05},
}

UPDATABLE_FIELDS = {"title", "summary", "evidence_data", "score", "is_active"}


class ForgeEvidenceService:
    """证据卡片系统 — 对标 Salesforce AgentExchange Trust Signals"""

    # ── 1. 创建证据卡片 ─────────────────────────────────────────
    async def create_card(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        card_type: str,
        title: str,
        summary: str = "",
        evidence_data: dict | None = None,
        score: int | None = None,
        verified_by: str = "",
        verification_method: str = "auto",
        expires_at: str | None = None,
    ) -> dict:
        """创建一张证据卡片。"""
        if evidence_data is None:
            evidence_data = {}

        if card_type not in CARD_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"无效 card_type: {card_type}，可选: {sorted(CARD_TYPES)}",
            )

        if score is not None and not (0 <= score <= 100):
            raise HTTPException(
                status_code=422,
                detail="score 必须在 0-100 之间",
            )

        card_id = f"ec_{uuid4().hex[:12]}"

        result = await db.execute(
            text("""
                INSERT INTO forge_evidence_cards
                    (card_id, app_id, card_type, title, summary,
                     evidence_data, score, verified_by,
                     verification_method, expires_at)
                VALUES
                    (:card_id, :app_id, :card_type, :title, :summary,
                     :evidence_data::jsonb, :score, :verified_by,
                     :verification_method, :expires_at::timestamptz)
                RETURNING card_id, app_id, card_type, title, summary,
                          evidence_data, score, verified_by,
                          verification_method, is_active,
                          expires_at, created_at
            """),
            {
                "card_id": card_id,
                "app_id": app_id,
                "card_type": card_type,
                "title": title,
                "summary": summary,
                "evidence_data": json.dumps(evidence_data, ensure_ascii=False),
                "score": score,
                "verified_by": verified_by,
                "verification_method": verification_method,
                "expires_at": expires_at,
            },
        )
        row = dict(result.mappings().one())
        await db.commit()

        logger.info(
            "evidence_card_created",
            card_id=card_id,
            app_id=app_id,
            card_type=card_type,
            score=score,
        )
        return row

    # ── 2. 列出证据卡片 ─────────────────────────────────────────
    async def list_cards(
        self,
        db: AsyncSession,
        *,
        app_id: str | None = None,
        card_type: str | None = None,
        active_only: bool = True,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询证据卡片，自动过滤已过期的。"""
        clauses: list[str] = []
        params: dict = {}

        if app_id:
            clauses.append("app_id = :app_id")
            params["app_id"] = app_id
        if card_type:
            clauses.append("card_type = :card_type")
            params["card_type"] = card_type
        if active_only:
            clauses.append("is_active = true")
            clauses.append("(expires_at IS NULL OR expires_at > NOW())")

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        # 总数
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM forge_evidence_cards {where}"),
            params,
        )
        total = count_result.scalar_one()

        # 数据
        result = await db.execute(
            text(f"""
                SELECT card_id, app_id, card_type, title, summary,
                       evidence_data, score, verified_by,
                       verification_method, is_active,
                       expires_at, created_at
                FROM forge_evidence_cards
                {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(r) for r in result.mappings().all()]

        return {"items": items, "total": total, "page": page, "size": size}

    # ── 3. 应用信任画像 ─────────────────────────────────────────
    async def get_app_trust_profile(
        self,
        db: AsyncSession,
        app_id: str,
    ) -> dict:
        """获取应用所有活跃证据卡片，计算加权信任分。"""
        result = await db.execute(
            text("""
                SELECT card_id, card_type, title, summary,
                       evidence_data, score, verified_by,
                       verification_method, is_active,
                       expires_at, created_at
                FROM forge_evidence_cards
                WHERE app_id = :app_id
                  AND is_active = true
                  AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY card_type, created_at DESC
            """),
            {"app_id": app_id},
        )
        cards = [dict(r) for r in result.mappings().all()]

        # 按类型分组
        cards_by_type: dict[str, list[dict]] = {}
        for card in cards:
            ct = card["card_type"]
            if ct not in cards_by_type:
                cards_by_type[ct] = []
            cards_by_type[ct].append(card)

        # 计算加权信任分
        # 每个类型取最高分的卡片，乘以类型权重
        weighted_sum = 0.0
        total_weight = 0.0

        for card_type, type_cards in cards_by_type.items():
            weight = CARD_TYPES.get(card_type, {}).get("weight", 0.05)
            scored_cards = [c for c in type_cards if c.get("score") is not None]
            if scored_cards:
                best_score = max(c["score"] for c in scored_cards)
                weighted_sum += best_score * weight
                total_weight += weight

        trust_score = round(
            weighted_sum / total_weight, 1
        ) if total_weight > 0 else 0.0

        # 统计过期卡片
        expired_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM forge_evidence_cards
                WHERE app_id = :app_id
                  AND is_active = true
                  AND expires_at IS NOT NULL
                  AND expires_at <= NOW()
            """),
            {"app_id": app_id},
        )
        expired_count = expired_result.scalar_one()

        return {
            "app_id": app_id,
            "trust_score": trust_score,
            "cards_by_type": cards_by_type,
            "total_cards": len(cards),
            "expired_cards": expired_count,
        }

    # ── 4. 更新卡片 ─────────────────────────────────────────────
    async def update_card(
        self,
        db: AsyncSession,
        card_id: str,
        updates: dict,
    ) -> dict:
        """更新证据卡片（仅允许 title/summary/evidence_data/score/is_active）。"""
        invalid_keys = set(updates.keys()) - UPDATABLE_FIELDS
        if invalid_keys:
            raise HTTPException(
                status_code=422,
                detail=f"不可更新的字段: {sorted(invalid_keys)}，仅允许: {sorted(UPDATABLE_FIELDS)}",
            )

        if not updates:
            raise HTTPException(status_code=422, detail="更新内容不能为空")

        if "score" in updates and updates["score"] is not None:
            if not (0 <= updates["score"] <= 100):
                raise HTTPException(status_code=422, detail="score 必须在 0-100 之间")

        # 动态构建 SET 子句
        set_parts: list[str] = ["updated_at = NOW()"]
        params: dict = {"card_id": card_id}

        for field, value in updates.items():
            if field == "evidence_data":
                set_parts.append(f"{field} = :{field}::jsonb")
                params[field] = json.dumps(value, ensure_ascii=False)
            else:
                set_parts.append(f"{field} = :{field}")
                params[field] = value

        set_clause = ", ".join(set_parts)

        result = await db.execute(
            text(f"""
                UPDATE forge_evidence_cards
                SET {set_clause}
                WHERE card_id = :card_id
                RETURNING card_id, app_id, card_type, title, summary,
                          evidence_data, score, is_active, updated_at
            """),
            params,
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"证据卡片不存在: {card_id}")

        await db.commit()

        logger.info(
            "evidence_card_updated",
            card_id=card_id,
            updated_fields=list(updates.keys()),
        )
        return dict(row)

    # ── 5. 批量停用过期卡片 ─────────────────────────────────────
    async def deactivate_expired(
        self,
        db: AsyncSession,
    ) -> dict:
        """停用所有已过期但仍标记为活跃的卡片。"""
        result = await db.execute(
            text("""
                UPDATE forge_evidence_cards
                SET is_active = false,
                    updated_at = NOW()
                WHERE expires_at < NOW()
                  AND is_active = true
                RETURNING card_id
            """),
        )
        deactivated = result.mappings().all()
        count = len(deactivated)
        await db.commit()

        if count > 0:
            logger.info(
                "evidence_cards_expired",
                deactivated_count=count,
            )

        return {
            "deactivated_count": count,
            "deactivated_card_ids": [r["card_id"] for r in deactivated],
        }
