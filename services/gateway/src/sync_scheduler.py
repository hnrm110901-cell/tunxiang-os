"""
屯象OS 品智POS 自动数据同步调度器

调度计划（Asia/Shanghai）：
  - 每日 02:00  — 全量拉取菜品（三商户所有门店并行）
  - 每日 03:00  — 全量拉取员工 + 桌台基础资料
  - 每小时      — 增量拉取当日订单
  - 每15分钟    — 增量拉取会员变更

三商户（czyz / zqx / sgc）并行执行（asyncio.gather）。
失败重试 3 次，重试间隔 5 分钟。
同步结果写入 sync_logs 表。
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date, datetime, timedelta
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = structlog.get_logger(__name__)

# ── 常量 ────────────────────────────────────────────────────────────────────

MERCHANTS = ["czyz", "zqx", "sgc"]
RETRY_TIMES = 3
RETRY_DELAY_SECONDS = 300  # 5 分钟

# 商户级 tenant_id 从环境变量加载（部署时注入真实 UUID）
# 格式：CZYZ_TENANT_ID / ZQX_TENANT_ID / SGC_TENANT_ID
_TENANT_ID_ENVS: dict[str, str] = {
    "czyz": "CZYZ_TENANT_ID",
    "zqx": "ZQX_TENANT_ID",
    "sgc": "SGC_TENANT_ID",
}


def _get_tenant_id(merchant_code: str) -> str:
    """从环境变量获取商户的屯象租户ID。"""
    env_var = _TENANT_ID_ENVS[merchant_code]
    tenant_id = os.getenv(env_var)
    if not tenant_id:
        raise ValueError(f"商户 {merchant_code} 的租户ID环境变量 {env_var} 未配置")
    return tenant_id


# ── 辅助：写入 sync_logs ────────────────────────────────────────────────────


async def _write_sync_log(
    db: Any,
    tenant_id: str,
    merchant_code: str,
    sync_type: str,
    status: str,
    records_synced: int,
    error_msg: str | None,
    started_at: datetime,
    *,
    error_detail: str | None = None,
    retry_count: int = 0,
    next_retry_at: datetime | None = None,
) -> None:
    """向 sync_logs 表写入一条同步记录（使用 RLS set_config）。

    v161 新增字段：
      error_detail  — 完整失败详情（堆栈 / 上游响应体）
      retry_count   — 本次任务已重试次数
      next_retry_at — 下次计划重试时间（None 表示无需重试）
    """
    from sqlalchemy import text

    finished_at = datetime.utcnow()
    log_id = str(uuid.uuid4())

    try:
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})
        await db.execute(
            text("""
                INSERT INTO sync_logs (
                    id, tenant_id, merchant_code, sync_type, status,
                    records_synced, error_msg, error_detail,
                    retry_count, next_retry_at,
                    started_at, finished_at
                ) VALUES (
                    :id::uuid, :tenant_id::uuid, :merchant_code, :sync_type, :status,
                    :records_synced, :error_msg, :error_detail,
                    :retry_count, :next_retry_at,
                    :started_at, :finished_at
                )
            """),
            {
                "id": log_id,
                "tenant_id": tenant_id,
                "merchant_code": merchant_code,
                "sync_type": sync_type,
                "status": status,
                "records_synced": records_synced,
                "error_msg": error_msg,
                "error_detail": error_detail,
                "retry_count": retry_count,
                "next_retry_at": next_retry_at,
                "started_at": started_at,
                "finished_at": finished_at,
            },
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — 日志写入失败不应影响主流程
        logger.error(
            "sync_log_write_failed",
            merchant_code=merchant_code,
            sync_type=sync_type,
            error=str(exc),
            exc_info=True,
        )


# ── 各类型同步任务 ──────────────────────────────────────────────────────────


async def _sync_dishes_for_merchant(merchant_code: str) -> dict:
    """全量拉取指定商户所有门店的菜品，返回统计信息。"""
    from shared.adapters.pinzhi.src.dish_sync import PinzhiDishSync
    from shared.adapters.pinzhi.src.factory import PinzhiAdapterFactory
    from shared.adapters.pinzhi.src.merchants import MERCHANT_CONFIG

    log = logger.bind(merchant_code=merchant_code, sync_type="dishes")
    tenant_id = _get_tenant_id(merchant_code)
    merchant_cfg = MERCHANT_CONFIG[merchant_code]
    total_records = 0
    started_at = datetime.utcnow()

    try:
        adapter = PinzhiAdapterFactory.create_for_merchant(merchant_code)
        syncer = PinzhiDishSync(adapter)

        # 全商户所有门店并行拉取（品智菜品接口不区分门店，逐门店拉避免遗漏）
        tasks = [syncer.sync_dishes(f"{merchant_code}:{store_id}") for store_id in merchant_cfg["stores"]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for store_id, result in zip(merchant_cfg["stores"], results):
            if isinstance(result, BaseException):
                log.error("dish_sync_store_failed", store_id=store_id, error=str(result))
            else:
                total_records += result.get("success", 0)

        log.info("dish_sync_merchant_done", total_records=total_records)
        return {"status": "success", "records_synced": total_records, "error_msg": None}

    except (ValueError, RuntimeError, OSError) as exc:
        log.error("dish_sync_merchant_failed", error=str(exc), exc_info=True)
        return {"status": "failed", "records_synced": total_records, "error_msg": str(exc)}
    finally:
        try:
            await adapter.client.aclose()  # type: ignore[possibly-undefined]
        except Exception:  # noqa: BLE001 — 关闭客户端失败不应上报
            pass

    # 写日志由调用方 _run_dishes_sync 统一处理，此处返回结果


async def _sync_tables_for_merchant(merchant_code: str, db: Any) -> dict:
    """全量拉取指定商户所有门店的桌台，UPSERT 写入数据库。"""

    from shared.adapters.pinzhi.src.factory import PinzhiAdapterFactory
    from shared.adapters.pinzhi.src.merchants import MERCHANT_CONFIG
    from shared.adapters.pinzhi.src.table_sync import PinzhiTableSync

    log = logger.bind(merchant_code=merchant_code, sync_type="tables")
    tenant_id = _get_tenant_id(merchant_code)
    merchant_cfg = MERCHANT_CONFIG[merchant_code]
    total_upserted = 0
    started_at = datetime.utcnow()

    adapter = None
    try:
        adapter = PinzhiAdapterFactory.create_for_merchant(merchant_code)
        syncer = PinzhiTableSync(adapter)

        for store_id in merchant_cfg["stores"]:
            # store_uuid：用确定性 UUID 对应品智门店ID（真实项目需从 stores 表查）
            store_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"pinzhi:store:{tenant_id}:{store_id}"))
            result = await syncer.upsert_tables(db, tenant_id, store_uuid, store_id)
            total_upserted += result.get("upserted", 0)

        log.info("table_sync_merchant_done", total_upserted=total_upserted)
        return {"status": "success", "records_synced": total_upserted, "error_msg": None}

    except (ValueError, RuntimeError, OSError) as exc:
        log.error("table_sync_merchant_failed", error=str(exc), exc_info=True)
        return {"status": "failed", "records_synced": total_upserted, "error_msg": str(exc)}
    finally:
        if adapter is not None:
            try:
                await adapter.client.aclose()
            except Exception:  # noqa: BLE001
                pass


async def _sync_employees_for_merchant(merchant_code: str, db: Any) -> dict:
    """全量拉取指定商户所有门店的员工，UPSERT 写入数据库。"""
    from shared.adapters.pinzhi.src.employee_sync import PinzhiEmployeeSync
    from shared.adapters.pinzhi.src.factory import PinzhiAdapterFactory
    from shared.adapters.pinzhi.src.merchants import MERCHANT_CONFIG

    log = logger.bind(merchant_code=merchant_code, sync_type="employees")
    tenant_id = _get_tenant_id(merchant_code)
    merchant_cfg = MERCHANT_CONFIG[merchant_code]
    total_upserted = 0

    adapter = None
    try:
        adapter = PinzhiAdapterFactory.create_for_merchant(merchant_code)
        syncer = PinzhiEmployeeSync(adapter)

        for store_id in merchant_cfg["stores"]:
            store_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"pinzhi:store:{tenant_id}:{store_id}"))
            result = await syncer.upsert_employees(db, tenant_id, store_uuid, store_id)
            total_upserted += result.get("upserted", 0)

        log.info("employee_sync_merchant_done", total_upserted=total_upserted)
        return {"status": "success", "records_synced": total_upserted, "error_msg": None}

    except (ValueError, RuntimeError, OSError) as exc:
        log.error("employee_sync_merchant_failed", error=str(exc), exc_info=True)
        return {"status": "failed", "records_synced": total_upserted, "error_msg": str(exc)}
    finally:
        if adapter is not None:
            try:
                await adapter.client.aclose()
            except Exception:  # noqa: BLE001
                pass


async def _sync_orders_incremental_for_merchant(merchant_code: str) -> dict:
    """增量拉取指定商户当日订单（调用已有 order_sync 模块）。"""
    from shared.adapters.pinzhi.src.factory import PinzhiAdapterFactory
    from shared.adapters.pinzhi.src.merchants import MERCHANT_CONFIG
    from shared.adapters.pinzhi.src.order_sync import PinzhiOrderSync

    log = logger.bind(merchant_code=merchant_code, sync_type="orders_incremental")
    merchant_cfg = MERCHANT_CONFIG[merchant_code]
    today = date.today().isoformat()
    total_records = 0

    adapter = None
    try:
        adapter = PinzhiAdapterFactory.create_for_merchant(merchant_code)
        syncer = PinzhiOrderSync(adapter)

        tasks = [
            syncer.fetch_orders(
                store_id=store_id,
                start_date=today,
                end_date=today,
            )
            for store_id in merchant_cfg["stores"]
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for store_id, result in zip(merchant_cfg["stores"], results):
            if isinstance(result, BaseException):
                log.error("order_incremental_store_failed", store_id=store_id, error=str(result))
            else:
                total_records += len(result)

        log.info("order_incremental_merchant_done", total_records=total_records)
        return {"status": "success", "records_synced": total_records, "error_msg": None}

    except (ValueError, RuntimeError, OSError) as exc:
        log.error("order_incremental_merchant_failed", error=str(exc), exc_info=True)
        return {"status": "failed", "records_synced": total_records, "error_msg": str(exc)}
    finally:
        if adapter is not None:
            try:
                await adapter.client.aclose()
            except Exception:  # noqa: BLE001
                pass


async def _sync_members_incremental_for_merchant(merchant_code: str, db: Any) -> dict:
    """增量拉取指定商户会员变更（调用已有 member_sync 模块）。"""
    from shared.adapters.pinzhi.src.factory import PinzhiAdapterFactory
    from shared.adapters.pinzhi.src.member_sync import PinzhiMemberSync
    from shared.adapters.pinzhi.src.merchants import MERCHANT_CONFIG

    log = logger.bind(merchant_code=merchant_code, sync_type="members_incremental")
    merchant_cfg = MERCHANT_CONFIG[merchant_code]
    total_records = 0

    adapter = None
    try:
        adapter = PinzhiAdapterFactory.create_for_merchant(merchant_code)
        syncer = PinzhiMemberSync(adapter)

        tasks = [syncer.fetch_members(store_id=store_id) for store_id in merchant_cfg["stores"]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for store_id, result in zip(merchant_cfg["stores"], results):
            if isinstance(result, BaseException):
                log.error("member_incremental_store_failed", store_id=store_id, error=str(result))
            else:
                total_records += len(result)

        log.info("member_incremental_merchant_done", total_records=total_records)
        return {"status": "success", "records_synced": total_records, "error_msg": None}

    except (ValueError, RuntimeError, OSError) as exc:
        log.error("member_incremental_merchant_failed", error=str(exc), exc_info=True)
        return {"status": "failed", "records_synced": total_records, "error_msg": str(exc)}
    finally:
        if adapter is not None:
            try:
                await adapter.client.aclose()
            except Exception:  # noqa: BLE001
                pass


# ── 带重试的包装器 ───────────────────────────────────────────────────────────


async def _with_retry(coro_factory: Any, sync_type: str, merchant_code: str) -> dict:
    """
    对同步协程执行最多 RETRY_TIMES 次重试，每次失败等待 RETRY_DELAY_SECONDS 秒（指数退避）。

    Args:
        coro_factory: 无参可调用对象，每次调用返回一个新协程
        sync_type: 同步类型（用于日志）
        merchant_code: 商户代码（用于日志）

    Returns:
        最后一次执行的结果字典，额外包含：
          retry_count   (int)           — 已重试次数（0 = 首次成功，1+ = 有过重试）
          next_retry_at (datetime|None) — 放弃时的预期下次重试时间（已用尽则为 None）
    """
    log = logger.bind(merchant_code=merchant_code, sync_type=sync_type)
    last_result: dict = {
        "status": "failed",
        "records_synced": 0,
        "error_msg": "未执行",
        "error_detail": None,
        "retry_count": 0,
        "next_retry_at": None,
    }

    for attempt in range(1, RETRY_TIMES + 1):
        try:
            result = await coro_factory()
            result.setdefault("error_detail", None)
            result["retry_count"] = attempt - 1
            result["next_retry_at"] = None
            if result.get("status") == "success":
                return result
            last_result = result
            log.warning(
                "sync_attempt_failed",
                attempt=attempt,
                error_msg=last_result.get("error_msg"),
            )
        except (ValueError, RuntimeError, OSError) as exc:
            import traceback

            log.error("sync_attempt_exception", attempt=attempt, error=str(exc), exc_info=True)
            last_result = {
                "status": "failed",
                "records_synced": 0,
                "error_msg": str(exc),
                "error_detail": traceback.format_exc(),
                "retry_count": attempt - 1,
                "next_retry_at": None,
            }

        if attempt < RETRY_TIMES:
            # 指数退避：第 1 次等 300s，第 2 次等 600s
            wait_secs = RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
            next_retry = datetime.utcnow() + timedelta(seconds=wait_secs)
            last_result["next_retry_at"] = next_retry
            log.info(
                "sync_retry_waiting",
                wait_seconds=wait_secs,
                next_attempt=attempt + 1,
                next_retry_at=next_retry.isoformat(),
            )
            await asyncio.sleep(wait_secs)

    last_result["retry_count"] = RETRY_TIMES - 1
    last_result["next_retry_at"] = None  # 已用尽所有重试，不再调度
    log.error("sync_all_attempts_failed", total_attempts=RETRY_TIMES)
    return last_result


# ── 调度任务入口 ─────────────────────────────────────────────────────────────


async def _run_dishes_sync() -> None:
    """每日 02:00 — 全量拉取三商户菜品（并行）。"""
    log = logger.bind(job="daily_dishes_sync")
    log.info("daily_dishes_sync_started")

    from shared.ontology.src.database import async_session_factory

    tasks = []
    for merchant_code in MERCHANTS:

        async def _task(mc: str = merchant_code) -> None:
            started_at = datetime.utcnow()
            result = await _with_retry(
                lambda m=mc: _sync_dishes_for_merchant(m),
                sync_type="dishes",
                merchant_code=mc,
            )
            async with async_session_factory() as db:
                tenant_id = _get_tenant_id(mc)
                await _write_sync_log(
                    db,
                    tenant_id,
                    mc,
                    "dishes",
                    result["status"],
                    result["records_synced"],
                    result.get("error_msg"),
                    started_at,
                    error_detail=result.get("error_detail"),
                    retry_count=result.get("retry_count", 0),
                    next_retry_at=result.get("next_retry_at"),
                )

        tasks.append(_task())

    await asyncio.gather(*tasks, return_exceptions=True)
    log.info("daily_dishes_sync_finished")


async def _run_master_data_sync() -> None:
    """每日 03:00 — 全量拉取三商户员工 + 桌台基础资料（并行）。"""
    log = logger.bind(job="daily_master_data_sync")
    log.info("daily_master_data_sync_started")

    from shared.ontology.src.database import async_session_factory

    async def _sync_merchant_master(merchant_code: str) -> None:
        started_at = datetime.utcnow()

        async with async_session_factory() as db:
            tenant_id = _get_tenant_id(merchant_code)

            # 桌台同步
            table_result = await _with_retry(
                lambda mc=merchant_code, session=db: _sync_tables_for_merchant(mc, session),
                sync_type="tables",
                merchant_code=merchant_code,
            )
            await _write_sync_log(
                db,
                tenant_id,
                merchant_code,
                "tables",
                table_result["status"],
                table_result["records_synced"],
                table_result.get("error_msg"),
                started_at,
                error_detail=table_result.get("error_detail"),
                retry_count=table_result.get("retry_count", 0),
                next_retry_at=table_result.get("next_retry_at"),
            )

            # 员工同步
            employee_result = await _with_retry(
                lambda mc=merchant_code, session=db: _sync_employees_for_merchant(mc, session),
                sync_type="employees",
                merchant_code=merchant_code,
            )
            await _write_sync_log(
                db,
                tenant_id,
                merchant_code,
                "employees",
                employee_result["status"],
                employee_result["records_synced"],
                employee_result.get("error_msg"),
                started_at,
                error_detail=employee_result.get("error_detail"),
                retry_count=employee_result.get("retry_count", 0),
                next_retry_at=employee_result.get("next_retry_at"),
            )

    tasks = [_sync_merchant_master(mc) for mc in MERCHANTS]
    await asyncio.gather(*tasks, return_exceptions=True)
    log.info("daily_master_data_sync_finished")


async def _run_orders_incremental_sync() -> None:
    """每小时 — 增量拉取三商户当日订单（并行）。"""
    log = logger.bind(job="hourly_orders_incremental_sync")
    log.info("hourly_orders_incremental_sync_started")

    from shared.ontology.src.database import async_session_factory

    async def _sync_merchant_orders(merchant_code: str) -> None:
        started_at = datetime.utcnow()
        result = await _with_retry(
            lambda mc=merchant_code: _sync_orders_incremental_for_merchant(mc),
            sync_type="orders_incremental",
            merchant_code=merchant_code,
        )
        async with async_session_factory() as db:
            tenant_id = _get_tenant_id(merchant_code)
            await _write_sync_log(
                db,
                tenant_id,
                merchant_code,
                "orders_incremental",
                result["status"],
                result["records_synced"],
                result.get("error_msg"),
                started_at,
                error_detail=result.get("error_detail"),
                retry_count=result.get("retry_count", 0),
                next_retry_at=result.get("next_retry_at"),
            )

    tasks = [_sync_merchant_orders(mc) for mc in MERCHANTS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for mc, res in zip(MERCHANTS, results):
        if isinstance(res, BaseException):
            log.error("hourly_orders_merchant_error", merchant_code=mc, error=str(res))

    log.info("hourly_orders_incremental_sync_finished")


async def _run_members_incremental_sync() -> None:
    """每15分钟 — 增量拉取三商户会员变更（并行）。"""
    log = logger.bind(job="quarter_members_incremental_sync")
    log.info("quarter_members_incremental_sync_started")

    from shared.ontology.src.database import async_session_factory

    async def _sync_merchant_members(merchant_code: str) -> None:
        started_at = datetime.utcnow()
        async with async_session_factory() as db:
            tenant_id = _get_tenant_id(merchant_code)
            result = await _with_retry(
                lambda mc=merchant_code, session=db: _sync_members_incremental_for_merchant(mc, session),
                sync_type="members_incremental",
                merchant_code=merchant_code,
            )
            await _write_sync_log(
                db,
                tenant_id,
                merchant_code,
                "members_incremental",
                result["status"],
                result["records_synced"],
                result.get("error_msg"),
                started_at,
                error_detail=result.get("error_detail"),
                retry_count=result.get("retry_count", 0),
                next_retry_at=result.get("next_retry_at"),
            )

    tasks = [_sync_merchant_members(mc) for mc in MERCHANTS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for mc, res in zip(MERCHANTS, results):
        if isinstance(res, BaseException):
            log.error("quarter_members_merchant_error", merchant_code=mc, error=str(res))

    log.info("quarter_members_incremental_sync_finished")


# ── 调度器工厂 ───────────────────────────────────────────────────────────────


def create_sync_scheduler() -> AsyncIOScheduler:
    """
    创建并配置数据同步调度器。

    调度计划（Asia/Shanghai 时区）：
      - 02:00 cron  — 全量菜品同步
      - 03:00 cron  — 全量员工 + 桌台同步
      - 每小时       — 增量订单同步
      - 每15分钟     — 增量会员同步

    Returns:
        已配置但尚未启动的 AsyncIOScheduler 实例
    """
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

    # 每日 02:00 — 全量菜品
    scheduler.add_job(
        lambda: asyncio.create_task(_run_dishes_sync()),
        "cron",
        hour=2,
        minute=0,
        id="daily_dishes_sync",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # 每日 03:00 — 全量员工 + 桌台
    scheduler.add_job(
        lambda: asyncio.create_task(_run_master_data_sync()),
        "cron",
        hour=3,
        minute=0,
        id="daily_master_data_sync",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # 每小时 — 增量订单
    scheduler.add_job(
        lambda: asyncio.create_task(_run_orders_incremental_sync()),
        "interval",
        hours=1,
        id="hourly_orders_incremental_sync",
        replace_existing=True,
        misfire_grace_time=120,
    )

    # 每15分钟 — 增量会员
    scheduler.add_job(
        lambda: asyncio.create_task(_run_members_incremental_sync()),
        "interval",
        minutes=15,
        id="quarter_members_incremental_sync",
        replace_existing=True,
        misfire_grace_time=60,
    )

    logger.info(
        "sync_scheduler_configured",
        jobs=[
            "daily_dishes_sync @ 02:00 Asia/Shanghai",
            "daily_master_data_sync @ 03:00 Asia/Shanghai",
            "hourly_orders_incremental_sync",
            "quarter_members_incremental_sync",
        ],
    )
    return scheduler


# ── 同步健康检查 API 路由 ─────────────────────────────────────────────────────

from fastapi import APIRouter  # noqa: E402 — 避免循环导入，在文件底部引入

sync_router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


@sync_router.get("/health", summary="查询各商户同步健康度（最近7天成功率）")
async def get_sync_health() -> dict:
    """
    从 sync_health_scores 视图返回三商户各同步类型的最近7天成功率。

    响应示例：
    {
      "ok": true,
      "data": [
        {
          "merchant_code": "czyz",
          "sync_type": "dishes",
          "total_runs": 7,
          "success_runs": 7,
          "success_rate": "1.0000",
          "last_run_at": "2026-04-04T02:03:12Z",
          "last_status": "success"
        },
        ...
      ]
    }
    """
    from sqlalchemy import text

    from shared.ontology.src.database import async_session_factory

    try:
        async with async_session_factory() as db:
            result = await db.execute(
                text(
                    """
                    SELECT
                        merchant_code,
                        sync_type,
                        total_runs,
                        success_runs,
                        failed_runs,
                        success_rate,
                        avg_records,
                        last_run_at,
                        last_status,
                        window_start
                    FROM sync_health_scores
                    ORDER BY merchant_code, sync_type
                    """
                )
            )
            rows = result.mappings().all()
            data = [dict(row) for row in rows]

        return {"ok": True, "data": data}

    except Exception as exc:  # noqa: BLE001 — 健康检查失败返回 503，不崩溃
        logger.error("sync_health_query_failed", error=str(exc), exc_info=True)
        return {"ok": False, "error": {"code": "SYNC_HEALTH_UNAVAILABLE", "message": str(exc)}}
