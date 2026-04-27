"""
品智员工同步模块
拉取品智员工数据并以 UPSERT 模式写入屯象 employees 表
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class PinzhiEmployeeSync:
    """品智员工同步器"""

    def __init__(self, adapter: Any) -> None:
        """
        Args:
            adapter: PinzhiAdapter 实例
        """
        self.adapter = adapter

    async def fetch_employees(self, store_id: str) -> list[dict]:
        """
        从品智拉取指定门店的员工列表。

        Args:
            store_id: 门店 ognid

        Returns:
            品智原始员工列表
        """
        employees = await self.adapter.get_employees(ognid=store_id)
        logger.info("pinzhi_employees_fetched", store_id=store_id, count=len(employees))
        return employees

    @staticmethod
    def map_to_tunxiang_employee(pinzhi_emp: dict, tenant_id: str, store_uuid: str) -> dict:
        """
        将品智原始员工映射为屯象 Employee 格式（纯函数）。

        Args:
            pinzhi_emp: 品智原始员工字典
            tenant_id: 屯象租户ID（UUID 字符串）
            store_uuid: 屯象门店ID（UUID 字符串）

        Returns:
            屯象标准员工字典
        """
        # 品智员工状态：1=在职, 0=离职
        raw_status = pinzhi_emp.get("status", pinzhi_emp.get("userStatus", 1))
        is_active = int(raw_status or 1) == 1

        # 员工ID生成：基于品智员工ID + 租户ID 确保跨商户唯一
        pinzhi_emp_id = str(pinzhi_emp.get("userId", pinzhi_emp.get("employeeId", "")))
        deterministic_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_DNS,
                f"pinzhi:emp:{tenant_id}:{pinzhi_emp_id}",
            )
        )

        # 角色映射
        role_code = str(pinzhi_emp.get("roleCode", pinzhi_emp.get("role", "staff")) or "staff")
        role_map = {
            "manager": "store_manager",
            "cashier": "cashier",
            "waiter": "waiter",
            "cook": "kitchen",
            "admin": "admin",
        }
        mapped_role = role_map.get(role_code.lower(), "staff")

        return {
            "id": deterministic_id,
            "tenant_id": tenant_id,
            "store_id": store_uuid,
            "employee_no": str(pinzhi_emp.get("employeeNo", pinzhi_emp.get("jobNo", pinzhi_emp_id))),
            "name": str(pinzhi_emp.get("userName", pinzhi_emp.get("name", "")) or ""),
            "role": mapped_role,
            "phone": str(pinzhi_emp.get("phone", pinzhi_emp.get("mobile", "")) or ""),
            "is_active": is_active,
            "extra": {
                "source_system": "pinzhi",
                "pinzhi_user_id": pinzhi_emp_id,
                "pinzhi_role_code": role_code,
                "pinzhi_store_id": str(pinzhi_emp.get("ognid", "") or ""),
            },
        }

    async def upsert_employees(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_uuid: str,
        store_id: str,
    ) -> dict:
        """
        完整同步流程：拉取 → 映射 → UPSERT 写入 employees 表。

        每次 DB 操作前设置 set_config 保证 RLS 生效。

        Args:
            db: 异步数据库会话
            tenant_id: 屯象租户ID（UUID 字符串）
            store_uuid: 屯象门店UUID（与 employees.store_id 对应）
            store_id: 品智门店 ognid

        Returns:
            同步统计 {"total": int, "upserted": int, "failed": int}
        """
        raw_employees = await self.fetch_employees(store_id)

        mapped: list[dict] = []
        failed = 0
        for raw in raw_employees:
            try:
                mapped.append(self.map_to_tunxiang_employee(raw, tenant_id, store_uuid))
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning(
                    "employee_mapping_failed",
                    user_id=raw.get("userId"),
                    error=str(exc),
                )
                failed += 1

        if not mapped:
            logger.info("employee_sync_nothing_to_upsert", store_id=store_id)
            return {"total": len(raw_employees), "upserted": 0, "failed": failed}

        # 设置 RLS 租户上下文
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

        upserted = 0
        for row in mapped:
            try:
                await db.execute(
                    text("""
                        INSERT INTO employees (
                            id, tenant_id, store_id, employee_no, name, role,
                            phone, is_active, extra,
                            created_at, updated_at, is_deleted
                        ) VALUES (
                            :id::uuid, :tenant_id::uuid, :store_id::uuid,
                            :employee_no, :name, :role,
                            :phone, :is_active, :extra::jsonb,
                            NOW(), NOW(), false
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            employee_no = EXCLUDED.employee_no,
                            name        = EXCLUDED.name,
                            role        = EXCLUDED.role,
                            phone       = EXCLUDED.phone,
                            is_active   = EXCLUDED.is_active,
                            extra       = EXCLUDED.extra,
                            updated_at  = NOW()
                    """),
                    {**row, "extra": __import__("json").dumps(row["extra"])},
                )
                upserted += 1
            except Exception as exc:  # noqa: BLE001 — 单行失败不阻断整批
                logger.error(
                    "employee_upsert_failed",
                    employee_no=row.get("employee_no"),
                    error=str(exc),
                    exc_info=True,
                )
                failed += 1

        await db.commit()

        logger.info(
            "pinzhi_employees_synced",
            tenant_id=tenant_id,
            store_id=store_id,
            total=len(raw_employees),
            upserted=upserted,
            failed=failed,
        )
        return {"total": len(raw_employees), "upserted": upserted, "failed": failed}
