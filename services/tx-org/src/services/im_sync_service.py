"""企微/钉钉 IM 员工同步与消息投递服务。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Employee, Store

logger = structlog.get_logger(__name__)


@dataclass
class IMSyncConfig:
    """IM 同步与消息发送配置。"""

    provider: str
    corp_id: str
    corp_secret: str
    agent_id: str = ""
    sync_interval_sec: int = 3600


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _provider_im_field(provider: str) -> str:
    if provider == "wecom":
        return "wechat_userid"
    if provider == "dingtalk":
        return "dingtalk_userid"
    raise ValueError(f"不支持的 provider: {provider}")


def _emp_im_id(emp: Employee, provider: str) -> str | None:
    if provider == "wecom":
        return emp.wechat_userid
    return emp.dingtalk_userid


async def fetch_im_department_users(config: IMSyncConfig) -> list[dict[str, Any]]:
    """从 IM 平台拉取部门员工列表（当前为 Mock）。"""
    if config.provider not in ("wecom", "dingtalk"):
        raise ValueError(f"不支持的 provider: {config.provider}")
    _ = (config.corp_id, config.corp_secret, config.agent_id, config.sync_interval_sec)
    base = [
        ("wx001", "张三", "13800001001", "总经办", "店长", "active"),
        ("wx002", "李四", "13800001002", "前厅", "服务员", "active"),
        ("wx003", "王五", "13800001003", "后厨", "厨师", "active"),
        ("wx004", "赵六", "13800001004", "前厅", "领班", "active"),
        ("wx005", "钱七", "13800001005", "后厨", "副厨", "inactive"),
        ("wx006", "孙八", "13800001006", "收银", "收银员", "active"),
        ("wx007", "周九", "13800001007", "库管", "库管员", "active"),
        ("wx008", "吴十", "13800001008", "前厅", "服务员", "active"),
        ("wx009", "郑一", "13800001009", "后厨", "打荷", "active"),
        ("wx010", "王二", "13800001010", "保洁", "保洁员", "active"),
    ]
    if config.provider == "dingtalk":
        base = [(f"dt{k[2:]}", n, p, d, pos, s) for k, n, p, d, pos, s in base]
    out: list[dict[str, Any]] = []
    for im_userid, name, phone, department, position, status in base:
        out.append(
            {
                "im_userid": im_userid,
                "name": name,
                "phone": phone,
                "department": department,
                "position": position,
                "status": status,
            }
        )
    return out


async def diff_employees(
    db: AsyncSession,
    tenant_id: str,
    im_users: list[dict[str, Any]],
    provider: str,
) -> dict[str, Any]:
    """对比 IM 用户与库内员工，生成待绑定、待新建、待停用与未变化数量。"""
    if provider not in ("wecom", "dingtalk"):
        raise ValueError(f"不支持的 provider: {provider}")
    await _set_tenant(db, tenant_id)
    tid = uuid.UUID(tenant_id)
    result = await db.execute(
        select(Employee).where(Employee.tenant_id == tid).where(Employee.is_deleted.is_(False))
    )
    employees = list(result.scalars().all())
    by_phone: dict[str, Employee] = {}
    for emp in employees:
        if emp.phone:
            key = emp.phone.strip()
            if key and key not in by_phone:
                by_phone[key] = emp

    im_ids = {str(u.get("im_userid", "")) for u in im_users if u.get("im_userid")}
    im_phones: set[str] = set()
    for u in im_users:
        pr = u.get("phone")
        if isinstance(pr, str) and pr.strip():
            im_phones.add(pr.strip())

    to_bind: list[dict[str, Any]] = []
    to_create: list[dict[str, Any]] = []
    unchanged = 0

    for im in im_users:
        uid = im.get("im_userid")
        if not uid:
            continue
        phone_raw = im.get("phone")
        phone = phone_raw.strip() if isinstance(phone_raw, str) else ""
        phone = phone or None
        if not phone:
            to_create.append(im)
            continue
        emp = by_phone.get(phone)
        if not emp:
            to_create.append(im)
            continue
        current = _emp_im_id(emp, provider)
        if not current or str(current) != str(uid):
            to_bind.append({"employee_id": str(emp.id), "im_userid": str(uid), "phone": phone})
        else:
            unchanged += 1

    to_deactivate: list[dict[str, Any]] = []
    for emp in employees:
        bound = _emp_im_id(emp, provider)
        if not bound or str(bound) in im_ids:
            continue
        ep = emp.phone.strip() if isinstance(emp.phone, str) else ""
        if ep and ep in im_phones:
            continue
        if emp.is_active:
            to_deactivate.append({"employee_id": str(emp.id), "im_userid": str(bound)})

    return {
        "to_bind": to_bind,
        "to_create": to_create,
        "to_deactivate": to_deactivate,
        "unchanged": unchanged,
    }


async def _default_store_id(db: AsyncSession, tenant_id: str) -> uuid.UUID | None:
    tid = uuid.UUID(tenant_id)
    r = await db.execute(
        select(Store.id)
        .where(Store.tenant_id == tid)
        .where(Store.is_deleted.is_(False))
        .order_by(Store.created_at.asc())
        .limit(1)
    )
    row = r.scalar_one_or_none()
    return row


async def apply_sync(
    db: AsyncSession,
    tenant_id: str,
    diff_result: dict[str, Any],
    provider: str,
    auto_create: bool = False,
) -> dict[str, Any]:
    """应用同步差异：绑定 IM 账号、可选自动建档、停用 IM 侧已不存在账号。"""
    await _set_tenant(db, tenant_id)
    tid = uuid.UUID(tenant_id)
    field = _provider_im_field(provider)
    bound = 0
    created = 0
    deactivated = 0
    errors: list[str] = []

    to_bind = diff_result.get("to_bind") or []
    for item in to_bind:
        eid = item.get("employee_id")
        im_uid = item.get("im_userid")
        if not eid or not im_uid:
            errors.append("to_bind 缺少 employee_id 或 im_userid")
            continue
        try:
            emp_uuid = uuid.UUID(str(eid))
        except ValueError:
            errors.append(f"非法 employee_id: {eid}")
            continue
        try:
            await db.execute(
                update(Employee)
                .where(Employee.id == emp_uuid)
                .where(Employee.tenant_id == tid)
                .where(Employee.is_deleted.is_(False))
                .values(**{field: str(im_uid)})
            )
            bound += 1
        except SQLAlchemyError as exc:
            errors.append(f"绑定失败 {eid}: {exc}")

    if auto_create:
        store_id = await _default_store_id(db, tenant_id)
        if not store_id:
            errors.append("auto_create 需要租户下至少一家门店")
        else:
            for im in diff_result.get("to_create") or []:
                im_uid = im.get("im_userid")
                name = im.get("name") or "未命名"
                phone = im.get("phone")
                if isinstance(phone, str):
                    phone = phone.strip() or None
                role = im.get("position") if isinstance(im.get("position"), str) else None
                role = (role or "staff").strip()[:50] or "staff"
                vals: dict[str, Any] = {
                    "tenant_id": tid,
                    "store_id": store_id,
                    "emp_name": str(name)[:100],
                    "phone": phone,
                    "role": role,
                    "is_active": im.get("status") != "inactive",
                }
                if field == "wechat_userid":
                    vals["wechat_userid"] = str(im_uid) if im_uid else None
                else:
                    vals["dingtalk_userid"] = str(im_uid) if im_uid else None
                emp = Employee(**vals)
                try:
                    async with db.begin_nested():
                        db.add(emp)
                        await db.flush()
                    created += 1
                except IntegrityError as exc:
                    errors.append(f"创建员工失败 {im_uid}: {exc}")
                except SQLAlchemyError as exc:
                    errors.append(f"创建员工失败 {im_uid}: {exc}")

    for item in diff_result.get("to_deactivate") or []:
        eid = item.get("employee_id")
        if not eid:
            errors.append("to_deactivate 缺少 employee_id")
            continue
        try:
            emp_uuid = uuid.UUID(str(eid))
        except ValueError:
            errors.append(f"非法 employee_id: {eid}")
            continue
        try:
            await db.execute(
                update(Employee)
                .where(Employee.id == emp_uuid)
                .where(Employee.tenant_id == tid)
                .where(Employee.is_deleted.is_(False))
                .values(is_active=False)
            )
            deactivated += 1
        except SQLAlchemyError as exc:
            errors.append(f"停用失败 {eid}: {exc}")

    return {"bound": bound, "created": created, "deactivated": deactivated, "errors": errors}


async def get_sync_status(db: AsyncSession, tenant_id: str) -> dict[str, Any]:
    """统计租户内员工 IM 绑定概况。"""
    await _set_tenant(db, tenant_id)
    tid = uuid.UUID(tenant_id)
    total_r = await db.execute(
        select(func.count())
        .select_from(Employee)
        .where(Employee.tenant_id == tid)
        .where(Employee.is_deleted.is_(False))
    )
    total_employees = int(total_r.scalar_one() or 0)

    wecom_r = await db.execute(
        select(func.count())
        .select_from(Employee)
        .where(Employee.tenant_id == tid)
        .where(Employee.is_deleted.is_(False))
        .where(Employee.wechat_userid.is_not(None))
    )
    wecom_bound = int(wecom_r.scalar_one() or 0)

    ding_r = await db.execute(
        select(func.count())
        .select_from(Employee)
        .where(Employee.tenant_id == tid)
        .where(Employee.is_deleted.is_(False))
        .where(Employee.dingtalk_userid.is_not(None))
    )
    dingtalk_bound = int(ding_r.scalar_one() or 0)

    unbound_r = await db.execute(
        select(func.count())
        .select_from(Employee)
        .where(Employee.tenant_id == tid)
        .where(Employee.is_deleted.is_(False))
        .where(Employee.wechat_userid.is_(None))
        .where(Employee.dingtalk_userid.is_(None))
    )
    unbound = int(unbound_r.scalar_one() or 0)

    return {
        "total_employees": total_employees,
        "wecom_bound": wecom_bound,
        "dingtalk_bound": dingtalk_bound,
        "unbound": unbound,
    }


async def send_im_message(
    config: IMSyncConfig,
    user_ids: list[str],
    message: dict[str, Any],
) -> dict[str, int]:
    """通过 IM 发送消息（当前为 Mock）。"""
    _ = (config.corp_id, config.corp_secret, config.agent_id)
    msg_type = message.get("type")
    if msg_type not in ("text", "card"):
        logger.warning("im_message_unknown_type", type=msg_type)
    logger.debug(
        "im_message_mock",
        recipients=len(user_ids),
        msg_type=msg_type,
        title=message.get("title"),
    )
    return {"sent": len(user_ids), "failed": 0}
