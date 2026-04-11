"""
统一上报引擎 — Unified Submission Engine

统一上报入口、幂等检查、重试机制、批量上报、上报日志。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import text

from shared.ontology.src.database import TenantSession

logger = structlog.get_logger(__name__)

# 各领域最大重试次数
MAX_RETRIES = 5


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------

def compute_payload_hash(payload: dict | str) -> str:
    """SHA256 哈希 — 用于幂等性检查。"""
    if isinstance(payload, dict):
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    else:
        raw = str(payload)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def calculate_retry_delay(retry_count: int) -> int:
    """指数退避: 2^retry_count * 60 秒，最大 3600 秒。"""
    delay = min(2 ** retry_count * 60, 3600)
    return delay


def should_auto_submit(domain: str, alert_type: str | None = None) -> bool:
    """判断是否需要自动上报。

    规则:
    - trace (食安追溯): 始终自动上报
    - kitchen (明厨亮灶): 仅 critical 告警自动上报
    - env (环保): 超标时自动上报
    - fire (消防): 不自动上报（人工确认后上报）
    - license (证照): 不自动上报
    """
    auto_domains = {"trace", "env"}
    if domain in auto_domains:
        return True

    if domain == "kitchen" and alert_type in {"fire", "rat", "foreign_object", "smoke"}:
        return True

    return False


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

async def _get_city_adapter(tenant_id: str, store_id: str, domain: str, db: Any) -> dict | None:
    """查找门店所在城市的上报适配器配置。"""
    row = await db.execute(
        text(
            "SELECT s.city_code, a.adapter_name, a.api_endpoint, a.api_key, "
            "  a.config_json "
            "FROM stores s "
            "LEFT JOIN civic_platform_adapters a "
            "  ON a.city_code = s.city_code AND a.domain = :domain AND a.enabled = TRUE "
            "WHERE s.tenant_id = :tenant_id AND s.id = :store_id"
        ),
        {"tenant_id": tenant_id, "store_id": store_id, "domain": domain},
    )
    first = row.mappings().first()
    return dict(first) if first else None


async def _check_idempotent(tenant_id: str, store_id: str, payload_hash: str, db: Any) -> bool:
    """幂等检查 — 同样的 payload 72h内不重复上报。"""
    row = await db.execute(
        text(
            "SELECT id FROM civic_submissions "
            "WHERE tenant_id = :tenant_id AND store_id = :store_id "
            "  AND payload_hash = :hash "
            "  AND created_at >= NOW() - INTERVAL '72 hours' "
            "  AND status IN ('submitted', 'accepted') "
            "LIMIT 1"
        ),
        {"tenant_id": tenant_id, "store_id": store_id, "hash": payload_hash},
    )
    return row.first() is not None


# ---------------------------------------------------------------------------
# 业务服务
# ---------------------------------------------------------------------------

async def submit_to_platform(
    tenant_id: str,
    store_id: str,
    domain: str,
    data: dict[str, Any],
    submission_type: str = "auto",
) -> dict:
    """统一上报入口。

    流程: 查找门店城市 -> 获取适配器 -> 幂等检查 -> 记录日志 -> 返回结果
    domain: trace / kitchen / env / fire / license
    submission_type: auto / manual
    """
    submission_id = str(uuid.uuid4())
    payload_hash = compute_payload_hash(data)
    log = logger.bind(
        tenant_id=tenant_id, store_id=store_id,
        domain=domain, submission_id=submission_id,
    )

    async with TenantSession(tenant_id) as db:
        # 幂等检查
        if await _check_idempotent(tenant_id, store_id, payload_hash, db):
            log.info("submission_duplicate_skipped")
            return {
                "id": submission_id,
                "status": "skipped",
                "reason": "duplicate_payload_within_72h",
            }

        # 获取适配器
        adapter = await _get_city_adapter(tenant_id, store_id, domain, db)
        if not adapter or not adapter.get("adapter_name"):
            log.warning("no_adapter_found")
            status = "no_adapter"
            response_body = json.dumps({"error": "该城市暂未配置上报通道"})
        else:
            # 实际上报逻辑（此处记录为 submitted，实际对接时替换为HTTP调用）
            log.info("submitting_to_platform", adapter=adapter.get("adapter_name"))
            status = "submitted"
            response_body = json.dumps({"adapter": adapter["adapter_name"], "accepted": True})

        # 记录上报日志
        await db.execute(
            text(
                "INSERT INTO civic_submissions "
                "(id, tenant_id, store_id, domain, submission_type, "
                " payload_json, payload_hash, status, response_body, "
                " retry_count, created_at) "
                "VALUES (:id, :tenant_id, :store_id, :domain, :submission_type, "
                " :payload_json, :payload_hash, :status, :response_body, "
                " 0, NOW())"
            ),
            {
                "id": submission_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "domain": domain,
                "submission_type": submission_type,
                "payload_json": json.dumps(data, ensure_ascii=False, default=str),
                "payload_hash": payload_hash,
                "status": status,
                "response_body": response_body,
            },
        )
        await db.commit()

    log.info("submission_completed", status=status)
    return {"id": submission_id, "status": status, "payload_hash": payload_hash}


async def retry_failed(tenant_id: str, submission_id: str) -> dict:
    """重试失败的上报。

    检查 retry_count < MAX_RETRIES，计算指数退避间隔。
    """
    log = logger.bind(tenant_id=tenant_id, submission_id=submission_id)

    async with TenantSession(tenant_id) as db:
        row = await db.execute(
            text(
                "SELECT id, store_id, domain, payload_json, retry_count, "
                "  status, last_retry_at "
                "FROM civic_submissions "
                "WHERE tenant_id = :tenant_id AND id = :submission_id"
            ),
            {"tenant_id": tenant_id, "submission_id": submission_id},
        )
        submission = row.mappings().first()
        if not submission:
            return {"error": "submission_not_found"}

        sub = dict(submission)
        if sub["status"] in ("submitted", "accepted"):
            return {"error": "already_successful", "status": sub["status"]}

        if sub["retry_count"] >= MAX_RETRIES:
            log.warning("max_retries_exceeded", retry_count=sub["retry_count"])
            return {"error": "max_retries_exceeded", "retry_count": sub["retry_count"]}

        # 检查退避间隔
        delay = calculate_retry_delay(sub["retry_count"])
        if sub.get("last_retry_at"):
            last_retry = sub["last_retry_at"]
            if isinstance(last_retry, str):
                last_retry = datetime.fromisoformat(last_retry)
            next_allowed = last_retry + timedelta(seconds=delay)
            if datetime.now(timezone.utc) < next_allowed:
                wait_seconds = int((next_allowed - datetime.now(timezone.utc)).total_seconds())
                return {
                    "error": "retry_too_soon",
                    "wait_seconds": wait_seconds,
                    "next_allowed": next_allowed.isoformat(),
                }

        # 执行重试（此处记录状态，实际对接时替换为HTTP调用）
        new_retry_count = sub["retry_count"] + 1
        payload = json.loads(sub["payload_json"]) if isinstance(sub["payload_json"], str) else sub["payload_json"]

        adapter = await _get_city_adapter(tenant_id, sub["store_id"], sub["domain"], db)
        if adapter and adapter.get("adapter_name"):
            new_status = "submitted"
            response = json.dumps({"adapter": adapter["adapter_name"], "retry": new_retry_count})
        else:
            new_status = "failed"
            response = json.dumps({"error": "no_adapter"})

        await db.execute(
            text(
                "UPDATE civic_submissions "
                "SET retry_count = :retry_count, status = :status, "
                "    response_body = :response, last_retry_at = NOW(), "
                "    updated_at = NOW() "
                "WHERE tenant_id = :tenant_id AND id = :submission_id"
            ),
            {
                "tenant_id": tenant_id,
                "submission_id": submission_id,
                "retry_count": new_retry_count,
                "status": new_status,
                "response": response,
            },
        )
        await db.commit()

    log.info("submission_retried", retry_count=new_retry_count, status=new_status)
    return {
        "submission_id": submission_id,
        "status": new_status,
        "retry_count": new_retry_count,
        "delay_applied": delay,
    }


async def batch_submit(
    tenant_id: str,
    store_id: str,
    domain: str,
    records: list[dict],
) -> dict:
    """批量上报。"""
    results = []
    submitted = 0
    skipped = 0
    failed = 0

    for record in records:
        result = await submit_to_platform(
            tenant_id=tenant_id,
            store_id=store_id,
            domain=domain,
            data=record,
            submission_type="batch",
        )
        results.append(result)
        if result["status"] == "submitted":
            submitted += 1
        elif result["status"] == "skipped":
            skipped += 1
        else:
            failed += 1

    logger.info(
        "batch_submit_completed",
        tenant_id=tenant_id, domain=domain,
        total=len(records), submitted=submitted, skipped=skipped, failed=failed,
    )
    return {
        "total": len(records),
        "submitted": submitted,
        "skipped": skipped,
        "failed": failed,
        "details": results,
    }


async def get_submissions(
    tenant_id: str,
    store_id: str | None = None,
    domain: str | None = None,
    status: str | None = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """上报日志查询。"""
    offset = (page - 1) * size
    conditions = ["tenant_id = :tenant_id"]
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "limit": size,
        "offset": offset,
    }

    if store_id:
        conditions.append("store_id = :store_id")
        params["store_id"] = store_id
    if domain:
        conditions.append("domain = :domain")
        params["domain"] = domain
    if status:
        conditions.append("status = :status")
        params["status"] = status

    where = " AND ".join(conditions)

    async with TenantSession(tenant_id) as db:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) AS cnt FROM civic_submissions WHERE {where}"),
            params,
        )
        total = count_result.scalar() or 0

        rows = await db.execute(
            text(
                f"SELECT id, store_id, domain, submission_type, status, "
                f"  payload_hash, retry_count, response_body, "
                f"  created_at, last_retry_at "
                f"FROM civic_submissions "
                f"WHERE {where} "
                f"ORDER BY created_at DESC "
                f"LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        items = [dict(r) for r in rows.mappings().all()]

    return {"total": total, "page": page, "size": size, "items": items}


async def get_submission_stats(tenant_id: str) -> dict:
    """上报统计: 成功率、失败率、各领域分布。"""
    async with TenantSession(tenant_id) as db:
        # 总体统计
        total_row = await db.execute(
            text(
                "SELECT "
                "  COUNT(*) AS total, "
                "  SUM(CASE WHEN status IN ('submitted', 'accepted') THEN 1 ELSE 0 END) AS success, "
                "  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed, "
                "  SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) AS skipped "
                "FROM civic_submissions "
                "WHERE tenant_id = :tenant_id "
                "  AND created_at >= CURRENT_DATE - 30"
            ),
            {"tenant_id": tenant_id},
        )
        totals = dict(total_row.mappings().first() or {})

        # 按领域分布
        domain_rows = await db.execute(
            text(
                "SELECT domain, COUNT(*) AS cnt, "
                "  SUM(CASE WHEN status IN ('submitted', 'accepted') THEN 1 ELSE 0 END) AS success "
                "FROM civic_submissions "
                "WHERE tenant_id = :tenant_id "
                "  AND created_at >= CURRENT_DATE - 30 "
                "GROUP BY domain"
            ),
            {"tenant_id": tenant_id},
        )
        by_domain = {}
        for r in domain_rows.mappings().all():
            d = dict(r)
            rate = round(d["success"] / d["cnt"] * 100, 1) if d["cnt"] else 0.0
            by_domain[d["domain"]] = {"total": d["cnt"], "success": d["success"], "success_rate": rate}

    total = totals.get("total", 0) or 0
    success = totals.get("success", 0) or 0
    failed_count = totals.get("failed", 0) or 0

    return {
        "period": "last_30_days",
        "total": total,
        "success": success,
        "failed": failed_count,
        "skipped": totals.get("skipped", 0) or 0,
        "success_rate": round(success / total * 100, 1) if total else 0.0,
        "failure_rate": round(failed_count / total * 100, 1) if total else 0.0,
        "by_domain": by_domain,
    }
