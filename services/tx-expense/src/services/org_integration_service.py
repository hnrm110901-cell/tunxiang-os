"""
tx-org 集成服务
封装对 tx-org 微服务的所有 API 调用，为 tx-expense 提供员工和组织数据。

缓存策略：
  - 员工基础信息：TTL 5分钟（姓名/职级变化不频繁）
  - 门店信息：TTL 10分钟
  - 组织架构（主管关系）：TTL 15分钟

安全：
  - 内部服务间调用使用 INTERNAL_SERVICE_KEY 头部认证
  - 密钥从环境变量 INTERNAL_SERVICE_KEY 读取
  - 调用超时：3秒（不阻塞主业务）
  - 所有调用失败时返回 fallback 值，不抛出异常

环境变量：
  TX_ORG_URL: tx-org 服务地址，默认 http://tx-org:8012
  INTERNAL_SERVICE_KEY: 服务间认证密钥
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Optional
from uuid import UUID

import httpx
import structlog

log = structlog.get_logger(__name__)

TX_ORG_URL = os.environ.get("TX_ORG_URL", "http://tx-org:8012")
INTERNAL_SERVICE_KEY = os.environ.get("INTERNAL_SERVICE_KEY", "")

# 缓存 TTL（秒）
_TTL_EMPLOYEE = 300    # 5 分钟
_TTL_STORE = 600       # 10 分钟
_TTL_SUPERVISOR = 900  # 15 分钟

# 内存缓存（进程级，服务重启后重新加载）
_cache: dict = {}


# ─────────────────────────────────────────────────────────────────────────────
# 内部缓存工具
# ─────────────────────────────────────────────────────────────────────────────

def _cache_get(key: str) -> Optional[dict]:
    """获取缓存，过期返回 None。"""
    if key in _cache:
        data, expire_at = _cache[key]
        if time.time() < expire_at:
            return data
        del _cache[key]
    return None


def _cache_set(key: str, data: dict, ttl: int) -> None:
    """设置缓存。"""
    _cache[key] = (data, time.time() + ttl)


def _make_headers(tenant_id: UUID) -> dict[str, str]:
    """构造内部服务调用头部。"""
    headers: dict[str, str] = {
        "X-Tenant-ID": str(tenant_id),
        "Content-Type": "application/json",
    }
    if INTERNAL_SERVICE_KEY:
        headers["X-Internal-Service-Key"] = INTERNAL_SERVICE_KEY
    return headers


# ─────────────────────────────────────────────────────────────────────────────
# 1. 员工基础信息
# ─────────────────────────────────────────────────────────────────────────────

def _employee_fallback(employee_id: UUID, fallback: bool = True) -> dict:
    """返回员工信息 fallback 结构。"""
    eid = str(employee_id)
    return {
        "employee_id": eid,
        "name": f"员工{eid[:6]}",
        "staff_level": "store_staff",
        "store_id": None,
        "store_name": None,
        "brand_id": None,
        "supervisor_id": None,
        "phone": None,
        "is_active": True,
        "_from_cache": False,
        "_fallback": fallback,
    }


async def get_employee_info(tenant_id: UUID, employee_id: UUID) -> dict:
    """
    获取员工基础信息。
    调用 tx-org: GET /api/v1/employees/{employee_id}

    返回（无论成功失败都返回完整结构，失败时用占位值）：
    {
      "employee_id": str,
      "name": str,                # 员工姓名，失败时返回 "员工{id[:6]}"
      "staff_level": str,         # StaffLevel 枚举值，失败时返回 "store_staff"
      "store_id": str | None,
      "store_name": str | None,
      "brand_id": str | None,
      "supervisor_id": str | None,  # 直属主管员工ID
      "phone": str | None,
      "is_active": bool,
      "_from_cache": bool,
      "_fallback": bool,          # True=使用了fallback值
    }
    缓存 TTL：5分钟
    失败时返回 fallback 结构，记录 warning 日志
    """
    cache_key = f"employee:{tenant_id}:{employee_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return {**cached, "_from_cache": True}

    url = f"{TX_ORG_URL}/api/v1/employees/{employee_id}"
    headers = _make_headers(tenant_id)

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code == 200:
            body = resp.json()
            raw: dict = body.get("data", {}) or {}

            # 将 tx-org 字段映射到统一结构
            # tx-org 中职级通过 job_grade_name / job_grade_category 反映
            # 此处将 position 映射为粗粒度 staff_level
            staff_level = _infer_staff_level(raw)

            info: dict = {
                "employee_id": raw.get("employee_id", str(employee_id)),
                "name": raw.get("emp_name") or f"员工{str(employee_id)[:6]}",
                "staff_level": staff_level,
                "store_id": raw.get("store_id"),
                "store_name": None,  # 需要单独查门店
                "brand_id": raw.get("brand_id"),
                "supervisor_id": raw.get("supervisor_id"),
                "phone": raw.get("phone"),
                "is_active": raw.get("status") == "active",
                "_from_cache": False,
                "_fallback": False,
            }
            _cache_set(cache_key, info, _TTL_EMPLOYEE)
            log.debug(
                "org_integration.employee_fetched",
                tenant_id=str(tenant_id),
                employee_id=str(employee_id),
            )
            return info

        elif resp.status_code == 404:
            log.warning(
                "org_integration.employee_not_found",
                tenant_id=str(tenant_id),
                employee_id=str(employee_id),
                status_code=resp.status_code,
            )
            return _employee_fallback(employee_id)

        else:
            log.warning(
                "org_integration.employee_fetch_error",
                tenant_id=str(tenant_id),
                employee_id=str(employee_id),
                status_code=resp.status_code,
                body_preview=resp.text[:200],
            )
            return _employee_fallback(employee_id)

    except httpx.TimeoutException as exc:
        log.warning(
            "org_integration.employee_timeout",
            tenant_id=str(tenant_id),
            employee_id=str(employee_id),
            error=str(exc),
        )
        return _employee_fallback(employee_id)
    except httpx.RequestError as exc:
        log.warning(
            "org_integration.employee_request_error",
            tenant_id=str(tenant_id),
            employee_id=str(employee_id),
            error=str(exc),
        )
        return _employee_fallback(employee_id)


def _infer_staff_level(raw: dict) -> str:
    """
    从 tx-org 员工数据推断 StaffLevel 枚举值。

    推断规则（按优先级）：
    1. job_grade_category（tx-org 标准化字段）
    2. position 关键字匹配
    3. 默认 store_staff
    """
    category = (raw.get("job_grade_category") or "").lower()
    position = (raw.get("position") or "").lower()

    # tx-org job_grade_category 直接映射
    category_map = {
        "executive": "executive",
        "brand_manager": "brand_manager",
        "region_manager": "region_manager",
        "store_manager": "store_manager",
        "store_staff": "store_staff",
    }
    if category in category_map:
        return category_map[category]

    # position 关键字匹配
    if any(kw in position for kw in ("总监", "cfo", "ceo", "高管", "总裁", "副总")):
        return "executive"
    if any(kw in position for kw in ("品牌", "运营总")):
        return "brand_manager"
    if any(kw in position for kw in ("区域", "督导", "大区")):
        return "region_manager"
    if any(kw in position for kw in ("店长", "门店经理")):
        return "store_manager"

    return "store_staff"


# ─────────────────────────────────────────────────────────────────────────────
# 2. 批量员工信息
# ─────────────────────────────────────────────────────────────────────────────

async def get_employees_batch(
    tenant_id: UUID,
    employee_ids: list[UUID],
) -> dict[str, dict]:
    """
    批量获取员工信息（最多50个）。
    并发调用（最多5并发），返回 {employee_id_str: employee_info}
    """
    if not employee_ids:
        return {}

    # 最多处理50个
    ids_to_query = employee_ids[:50]
    semaphore = asyncio.Semaphore(5)

    async def _fetch_one(eid: UUID) -> tuple[str, dict]:
        async with semaphore:
            info = await get_employee_info(tenant_id, eid)
            return str(eid), info

    tasks = [asyncio.create_task(_fetch_one(eid)) for eid in ids_to_query]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    out: dict[str, dict] = {}
    for item in results:
        if isinstance(item, tuple):
            eid_str, info = item
            out[eid_str] = info
        else:
            # 捕获到异常（不应该发生，get_employee_info 本身已兜底）
            log.warning(
                "org_integration.batch_item_error",
                error=str(item),
            )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 3. 门店信息
# ─────────────────────────────────────────────────────────────────────────────

def _store_fallback(store_id: UUID) -> dict:
    """返回门店信息 fallback 结构。"""
    sid = str(store_id)
    return {
        "store_id": sid,
        "store_name": f"门店{sid[:6]}",
        "brand_id": None,
        "brand_name": None,
        "region_id": None,
        "region_name": None,
        "city": None,
        "address": None,
        "manager_id": None,
        "_fallback": True,
    }


async def get_store_info(tenant_id: UUID, store_id: UUID) -> dict:
    """
    获取门店基础信息。
    调用 tx-org: GET /api/v1/org-structure/departments/{store_id}
    （tx-org 中门店以 dept_type='store' 的部门形式存储，同时尝试直接门店端点）

    返回：
    {
      "store_id": str,
      "store_name": str,          # 失败时返回 "门店{id[:6]}"
      "brand_id": str | None,
      "brand_name": str | None,
      "region_id": str | None,
      "region_name": str | None,
      "city": str | None,         # 所在城市（用于差标城市匹配）
      "address": str | None,
      "manager_id": str | None,   # 店长员工ID
      "_fallback": bool,
    }
    缓存 TTL：10分钟
    """
    cache_key = f"store:{tenant_id}:{store_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    headers = _make_headers(tenant_id)

    # 优先尝试 /api/v1/stores/{store_id}（如果 tx-org 暴露了该端点）
    # 兜底通过 org-structure departments 接口查询
    urls_to_try = [
        f"{TX_ORG_URL}/api/v1/stores/{store_id}",
        f"{TX_ORG_URL}/api/v1/org-structure/departments/{store_id}",
    ]

    for url in urls_to_try:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url, headers=headers)

            if resp.status_code == 200:
                body = resp.json()
                raw: dict = body.get("data", {}) or {}

                info: dict = {
                    "store_id": raw.get("store_id") or raw.get("id") or str(store_id),
                    "store_name": (
                        raw.get("store_name")
                        or raw.get("name")
                        or f"门店{str(store_id)[:6]}"
                    ),
                    "brand_id": raw.get("brand_id"),
                    "brand_name": raw.get("brand_name"),
                    "region_id": raw.get("region_id"),
                    "region_name": raw.get("region_name"),
                    "city": raw.get("city"),
                    "address": raw.get("address"),
                    "manager_id": raw.get("manager_id"),
                    "_fallback": False,
                }
                _cache_set(cache_key, info, _TTL_STORE)
                log.debug(
                    "org_integration.store_fetched",
                    tenant_id=str(tenant_id),
                    store_id=str(store_id),
                    via_url=url,
                )
                return info

            elif resp.status_code == 404:
                # 该端点不存在或记录不存在，尝试下一个 URL
                continue

            else:
                log.warning(
                    "org_integration.store_fetch_error",
                    tenant_id=str(tenant_id),
                    store_id=str(store_id),
                    url=url,
                    status_code=resp.status_code,
                    body_preview=resp.text[:200],
                )
                continue

        except httpx.TimeoutException as exc:
            log.warning(
                "org_integration.store_timeout",
                tenant_id=str(tenant_id),
                store_id=str(store_id),
                url=url,
                error=str(exc),
            )
            continue
        except httpx.RequestError as exc:
            log.warning(
                "org_integration.store_request_error",
                tenant_id=str(tenant_id),
                store_id=str(store_id),
                url=url,
                error=str(exc),
            )
            continue

    # 所有端点均失败，返回 fallback
    log.warning(
        "org_integration.store_all_urls_failed",
        tenant_id=str(tenant_id),
        store_id=str(store_id),
    )
    return _store_fallback(store_id)


# ─────────────────────────────────────────────────────────────────────────────
# 4. 获取员工的直属主管
# ─────────────────────────────────────────────────────────────────────────────

async def get_supervisor(tenant_id: UUID, employee_id: UUID) -> Optional[dict]:
    """
    获取员工直属主管信息。
    先从 get_employee_info 的 supervisor_id 字段获取，
    再调用 get_employee_info(supervisor_id) 获取主管详情。
    返回主管的 employee_info dict，或 None（无主管或查询失败）。
    缓存 TTL：15分钟（通过 employee_info 自身缓存实现）
    """
    cache_key = f"supervisor:{tenant_id}:{employee_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached if cached else None

    try:
        employee_info = await get_employee_info(tenant_id, employee_id)
        supervisor_id_str = employee_info.get("supervisor_id")

        if not supervisor_id_str:
            # 无主管，缓存空结果避免频繁查询
            _cache_set(cache_key, {}, _TTL_SUPERVISOR)
            return None

        supervisor_id = UUID(supervisor_id_str)
        supervisor_info = await get_employee_info(tenant_id, supervisor_id)

        if supervisor_info.get("_fallback"):
            _cache_set(cache_key, {}, _TTL_SUPERVISOR)
            return None

        _cache_set(cache_key, supervisor_info, _TTL_SUPERVISOR)
        return supervisor_info

    except (ValueError, KeyError) as exc:
        log.warning(
            "org_integration.get_supervisor_error",
            tenant_id=str(tenant_id),
            employee_id=str(employee_id),
            error=str(exc),
        )
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 5. 通知上下文富化
# ─────────────────────────────────────────────────────────────────────────────

async def enrich_notification_context(
    tenant_id: UUID,
    applicant_id: UUID,
    store_id: UUID,
) -> dict:
    """
    为通知推送获取真实的申请人姓名和门店名。
    并发获取员工信息和门店信息。
    返回：{"applicant_name": str, "store_name": str}
    失败时返回占位值，不抛出异常。
    """
    employee_info, store_info = await asyncio.gather(
        get_employee_info(tenant_id, applicant_id),
        get_store_info(tenant_id, store_id),
        return_exceptions=True,
    )
    applicant_name = (
        employee_info.get("name", f"员工{str(applicant_id)[:6]}")
        if isinstance(employee_info, dict)
        else f"员工{str(applicant_id)[:6]}"
    )
    store_name = (
        store_info.get("store_name", f"门店{str(store_id)[:6]}")
        if isinstance(store_info, dict)
        else f"门店{str(store_id)[:6]}"
    )
    return {"applicant_name": applicant_name, "store_name": store_name}


# ─────────────────────────────────────────────────────────────────────────────
# 6. 缓存管理（管理端）
# ─────────────────────────────────────────────────────────────────────────────

def clear_cache(pattern: Optional[str] = None) -> int:
    """
    清除缓存。pattern=None 清全部，否则清匹配前缀的 key。
    返回清除的 key 数量。
    """
    if pattern is None:
        count = len(_cache)
        _cache.clear()
        log.info("org_integration.cache_cleared_all", count=count)
        return count

    keys_to_delete = [k for k in _cache if k.startswith(pattern)]
    for k in keys_to_delete:
        del _cache[k]
    log.info(
        "org_integration.cache_cleared_pattern",
        pattern=pattern,
        count=len(keys_to_delete),
    )
    return len(keys_to_delete)


# ─────────────────────────────────────────────────────────────────────────────
# 7. 服务健康检查
# ─────────────────────────────────────────────────────────────────────────────

async def health_check() -> dict:
    """
    检查 tx-org 服务连通性。
    调用 GET {TX_ORG_URL}/health，超时2秒。
    返回：{"reachable": bool, "latency_ms": int | None}
    """
    url = f"{TX_ORG_URL}/health"
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(url)
        latency_ms = int((time.monotonic() - start) * 1000)
        reachable = resp.status_code < 500
        log.debug(
            "org_integration.health_check",
            url=url,
            status_code=resp.status_code,
            latency_ms=latency_ms,
            reachable=reachable,
        )
        return {"reachable": reachable, "latency_ms": latency_ms}
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        log.warning(
            "org_integration.health_check_failed",
            url=url,
            error=str(exc),
        )
        return {"reachable": False, "latency_ms": None}
