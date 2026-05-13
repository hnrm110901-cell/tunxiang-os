"""doc_number_service — 业务单号定制规则引擎（PRD-03 / Tier 1 审计+财务）

为 17 类业务单据生成人类可读单号（PO20260513-001 / STK-CS01-202605-0001）。
财务对账 / 食药监稽查 / 银行流水匹配场景必备 — UUID 不可读。

设计要点：
  1. 模板 DSL：`PO{yyyy}{MM}{dd}-{seq:03d}` / `STK-{store_code}-{yyyyMM}-{seq:04d}`
     占位符：yyyy / yy / MM / dd / HH / mm / store_code / seq / seq:Nd
     seq:Nd 表示 zero-padded 到 N 位（seq:03d → 001/002/.../999）

  2. PG advisory_xact_lock 并发安全：
     - lock_id = SHA256(tenant|doc_type|scope_key)[:8] signed int64
     - 同 (tenant, doc_type, scope_key) 并发自动串行
     - 跨 (tenant) 或跨 (doc_type) 不互相阻塞
     - commit/rollback 自动释放，无需显式 unlock
     - 参考 services/tx-trade/src/services/api_idempotency.py

  3. scope_key 计算：
       global  → 'global'
       daily   → 'YYYY-MM-DD'
       monthly → 'YYYY-MM'
       store   → str(store_id) — 需 caller 提供

  4. fallback 顺序（创始人 Q4 决策 2026-05-14）：
     tenant 自定义规则 → 系统默认规则（tenant_id '00...000'）→ raise
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


SYSTEM_TENANT_ID = "00000000-0000-0000-0000-000000000000"

# DSL 允许的占位符（包含 seq:Nd 变体）
# 注意 store_code 必须 caller 传入（不在 datetime 派生范围）
_PLACEHOLDER_RE = re.compile(
    r"\{(yyyy|yy|MM|dd|HH|mm|store_code|seq(?::(\d+)d)?)\}"
)


class DocNumberError(Exception):
    """业务单号生成失败（DSL 非法 / 规则不存在 / scope 参数缺失）。"""


@dataclass(frozen=True)
class DocNumberRule:
    tenant_id: str
    doc_type: str
    template: str
    seq_scope: str  # global / daily / monthly / store
    is_active: bool


# ─── DSL 解析 ─────────────────────────────────────────────────────────────


def _validate_template(template: str) -> None:
    """检查模板里的占位符全部合法，且至少含 {seq...}。"""
    if not template:
        raise DocNumberError("template_empty")
    # 找所有 {...} 段
    raw_tokens = re.findall(r"\{[^}]+\}", template)
    seq_count = 0
    for tok in raw_tokens:
        if not _PLACEHOLDER_RE.fullmatch(tok):
            raise DocNumberError(f"template_invalid_placeholder:{tok}")
        if tok.startswith("{seq"):
            seq_count += 1
    if seq_count == 0:
        raise DocNumberError("template_missing_seq")
    if seq_count > 1:
        raise DocNumberError("template_multiple_seq")


def _render_template(
    template: str,
    *,
    now: datetime,
    seq: int,
    store_code: Optional[str] = None,
) -> str:
    """把模板里的占位符替换为实际值。

    占位符未提供（如 store_code）→ raise DocNumberError，不静默替换为空串。
    """

    def _replace(match: re.Match[str]) -> str:
        token = match.group(1)
        seq_width = match.group(2)  # seq:Nd 的 N
        if token == "yyyy":
            return f"{now.year:04d}"
        if token == "yy":
            return f"{now.year % 100:02d}"
        if token == "MM":
            return f"{now.month:02d}"
        if token == "dd":
            return f"{now.day:02d}"
        if token == "HH":
            return f"{now.hour:02d}"
        if token == "mm":
            return f"{now.minute:02d}"
        if token == "store_code":
            if not store_code:
                raise DocNumberError("store_code_required_but_missing")
            return store_code
        if token == "seq" or token.startswith("seq:"):
            width = int(seq_width) if seq_width else 0
            return f"{seq:0{width}d}" if width else str(seq)
        raise DocNumberError(f"unknown_placeholder:{token}")

    return _PLACEHOLDER_RE.sub(_replace, template)


# ─── scope_key 计算 ───────────────────────────────────────────────────────


def _scope_key(
    seq_scope: str,
    *,
    now: datetime,
    store_id: Optional[str] = None,
) -> str:
    if seq_scope == "global":
        return "global"
    if seq_scope == "daily":
        return now.strftime("%Y-%m-%d")
    if seq_scope == "monthly":
        return now.strftime("%Y-%m")
    if seq_scope == "store":
        if not store_id:
            raise DocNumberError("store_id_required_for_store_scope")
        return str(store_id)
    raise DocNumberError(f"unknown_seq_scope:{seq_scope}")


# ─── advisory lock ────────────────────────────────────────────────────────


def _compute_lock_id(tenant_id: str, doc_type: str, scope_key: str) -> int:
    """SHA256(tenant|doc_type|scope_key)[:8] → signed BIGINT for pg_advisory_xact_lock。

    跨 (tenant, doc_type, scope_key) 哈希几乎不碰撞，并发不互相阻塞。
    同 (tenant, doc_type, scope_key) 自动串行。
    """
    h = hashlib.sha256(f"{tenant_id}|{doc_type}|{scope_key}".encode()).digest()
    return int.from_bytes(h[:8], "big", signed=True)


async def _acquire_advisory_lock(
    db: AsyncSession,
    *,
    tenant_id: str,
    doc_type: str,
    scope_key: str,
) -> None:
    lock_id = _compute_lock_id(tenant_id, doc_type, scope_key)
    await db.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": lock_id})


# ─── 规则读取（带 fallback）──────────────────────────────────────────────


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


async def get_rule(
    db: AsyncSession,
    *,
    tenant_id: str,
    doc_type: str,
) -> DocNumberRule:
    """先查 tenant 自定义，未命中则查系统默认（'00...000'）。"""
    await _set_rls(db, tenant_id)
    row = (
        await db.execute(
            text(
                """
                SELECT tenant_id::text AS tenant_id, doc_type, template,
                       seq_scope, is_active
                FROM doc_number_rules
                WHERE doc_type = :doc_type
                  AND is_active = TRUE
                  AND (tenant_id::text = :tid OR tenant_id = :sys::uuid)
                ORDER BY (tenant_id::text = :tid) DESC
                LIMIT 1
                """
            ),
            {"doc_type": doc_type, "tid": str(tenant_id), "sys": SYSTEM_TENANT_ID},
        )
    ).mappings().first()
    if not row:
        raise DocNumberError(f"no_active_rule:{doc_type}")
    return DocNumberRule(
        tenant_id=row["tenant_id"],
        doc_type=row["doc_type"],
        template=row["template"],
        seq_scope=row["seq_scope"],
        is_active=bool(row["is_active"]),
    )


# ─── 序号增量（UPSERT + advisory_lock）────────────────────────────────────


async def _next_seq(
    db: AsyncSession,
    *,
    tenant_id: str,
    doc_type: str,
    scope_key: str,
) -> int:
    """UPSERT 取下一个 seq；advisory_lock 已 caller 持有，保证唯一。

    系统默认 tenant 的 sequence 仍写入实际 tenant_id（不写系统 tenant），
    系统默认规则只是 template 来源，状态归各租户自己。
    """
    row = (
        await db.execute(
            text(
                """
                INSERT INTO doc_number_sequences (
                    tenant_id, doc_type, scope_key, current_seq, last_used_at
                ) VALUES (
                    :tid::uuid, :doc_type, :scope_key, 1, NOW()
                )
                ON CONFLICT (tenant_id, doc_type, scope_key) DO UPDATE
                SET current_seq = doc_number_sequences.current_seq + 1,
                    last_used_at = NOW()
                RETURNING current_seq
                """
            ),
            {
                "tid": str(tenant_id),
                "doc_type": doc_type,
                "scope_key": scope_key,
            },
        )
    ).mappings().first()
    if not row:
        raise DocNumberError("seq_upsert_failed")
    return int(row["current_seq"])


# ─── 公共 API ─────────────────────────────────────────────────────────────


async def generate(
    db: AsyncSession,
    *,
    tenant_id: str,
    doc_type: str,
    now: Optional[datetime] = None,
    store_id: Optional[str] = None,
    store_code: Optional[str] = None,
) -> str:
    """生成单号。

    Args:
        tenant_id: 租户 UUID（用于 RLS）
        doc_type: 单据类型（如 'purchase_order'）
        now: 单据时间（默认当前 UTC）— 用于 daily/monthly scope 与 yyyy/MM 占位符
        store_id: 门店 UUID（seq_scope='store' 必填）
        store_code: 门店编码（模板含 {store_code} 必填）

    Returns:
        生成的单号字符串。

    Raises:
        DocNumberError: 规则不存在 / 模板非法 / 必需参数缺失
    """
    if now is None:
        now = datetime.now(timezone.utc)

    rule = await get_rule(db, tenant_id=tenant_id, doc_type=doc_type)
    _validate_template(rule.template)

    scope_key = _scope_key(rule.seq_scope, now=now, store_id=store_id)
    await _acquire_advisory_lock(
        db, tenant_id=tenant_id, doc_type=doc_type, scope_key=scope_key
    )
    seq = await _next_seq(
        db, tenant_id=tenant_id, doc_type=doc_type, scope_key=scope_key
    )
    return _render_template(rule.template, now=now, seq=seq, store_code=store_code)


async def upsert_rule(
    db: AsyncSession,
    *,
    tenant_id: str,
    doc_type: str,
    template: str,
    seq_scope: str,
    description: Optional[str] = None,
    created_by: Optional[str] = None,
) -> DocNumberRule:
    """tenant 级模板配置（覆盖系统默认）。先校验模板合法。"""
    _validate_template(template)
    if seq_scope not in ("global", "daily", "monthly", "store"):
        raise DocNumberError(f"invalid_seq_scope:{seq_scope}")

    await _set_rls(db, tenant_id)
    await db.execute(
        text(
            """
            INSERT INTO doc_number_rules (
                tenant_id, doc_type, template, seq_scope, description, created_by
            ) VALUES (
                :tid::uuid, :doc_type, :template, :seq_scope, :description, :created_by
            )
            ON CONFLICT (tenant_id, doc_type) DO UPDATE
            SET template    = EXCLUDED.template,
                seq_scope   = EXCLUDED.seq_scope,
                description = EXCLUDED.description,
                updated_at  = NOW()
            """
        ),
        {
            "tid": str(tenant_id),
            "doc_type": doc_type,
            "template": template,
            "seq_scope": seq_scope,
            "description": description,
            "created_by": str(created_by) if created_by else None,
        },
    )
    return DocNumberRule(
        tenant_id=str(tenant_id),
        doc_type=doc_type,
        template=template,
        seq_scope=seq_scope,
        is_active=True,
    )
