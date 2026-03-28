"""打印管理器 — 门店打印机统一管理与任务分发

职责：
1. 打印机注册/配置管理（按角色: 收银/厨打/标签）
2. 打印任务分发（自动选择打印机 + 渲染模板 + 发送打印）
3. 厨打分单（按菜品→档口映射，分发到各厨打打印机）
4. 打印队列管理（排队/补打/状态查询）
5. 连接池复用（避免频繁开关 TCP 连接）
"""
import asyncio
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import structlog

from .printer_driver import ESCPOSPrinter, PrinterStatus
from .print_template import ReceiptTemplate

logger = structlog.get_logger()


class PrinterRole(str, Enum):
    CASHIER = "cashier"    # 收银打印机
    KITCHEN = "kitchen"    # 厨打打印机
    LABEL = "label"        # 标签打印机


class PrintTaskStatus(str, Enum):
    PENDING = "pending"
    PRINTING = "printing"
    SUCCESS = "success"
    FAILED = "failed"


class PrintTask:
    """打印任务。"""

    def __init__(
        self,
        task_id: str,
        printer_id: str,
        template_type: str,
        content: bytes,
        tenant_id: str,
        store_id: str,
        order_id: Optional[str] = None,
    ):
        self.task_id = task_id
        self.printer_id = printer_id
        self.template_type = template_type
        self.content = content
        self.tenant_id = tenant_id
        self.store_id = store_id
        self.order_id = order_id
        self.status = PrintTaskStatus.PENDING
        self.created_at = datetime.now(timezone.utc)
        self.error_msg: Optional[str] = None
        self.retry_count = 0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "printer_id": self.printer_id,
            "template_type": self.template_type,
            "status": self.status.value,
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "order_id": self.order_id,
            "created_at": self.created_at.isoformat(),
            "error_msg": self.error_msg,
            "retry_count": self.retry_count,
            "content_size": len(self.content),
        }


class PrinterInfo:
    """打印机注册信息。"""

    def __init__(
        self,
        printer_id: str,
        ip: str,
        port: int,
        role: PrinterRole,
        store_id: str,
        tenant_id: str,
        dept_id: Optional[str] = None,
        name: Optional[str] = None,
    ):
        self.printer_id = printer_id
        self.ip = ip
        self.port = port
        self.role = role
        self.store_id = store_id
        self.tenant_id = tenant_id
        self.dept_id = dept_id
        self.name = name or f"{role.value}_{ip}"

    def to_dict(self) -> dict:
        return {
            "printer_id": self.printer_id,
            "ip": self.ip,
            "port": self.port,
            "role": self.role.value,
            "store_id": self.store_id,
            "tenant_id": self.tenant_id,
            "dept_id": self.dept_id,
            "name": self.name,
        }


class PrintManager:
    """门店打印机管理器。

    管理所有打印机的注册、连接池、任务分发和状态查询。
    支持多门店、多打印机、多角色的打印任务调度。
    """

    MAX_RETRY = 3
    MAX_QUEUE_SIZE = 500

    def __init__(self):
        self._printers: dict[str, PrinterInfo] = {}    # {printer_id: PrinterInfo}
        self._connections: dict[str, ESCPOSPrinter] = {}  # {printer_id: ESCPOSPrinter}
        self._task_queue: list[PrintTask] = []           # 打印队列
        self._task_history: dict[str, PrintTask] = {}    # {task_id: PrintTask}
        self._lock = asyncio.Lock()
        self._template = ReceiptTemplate()

    # ─── 打印机注册 ───

    async def register_printer(
        self,
        printer_id: str,
        ip: str,
        port: int,
        role: str,
        store_id: str,
        tenant_id: str,
        dept_id: Optional[str] = None,
        name: Optional[str] = None,
    ) -> PrinterInfo:
        """注册打印机。

        Args:
            printer_id: 打印机唯一标识
            ip: 打印机IP地址
            port: 端口号（默认9100）
            role: 角色 cashier(收银) / kitchen(厨打) / label(标签)
            store_id: 所属门店ID
            tenant_id: 租户ID
            dept_id: 关联档口ID（厨打用）
            name: 打印机名称

        Returns:
            PrinterInfo 注册信息
        """
        printer_role = PrinterRole(role)
        info = PrinterInfo(
            printer_id=printer_id,
            ip=ip,
            port=port,
            role=printer_role,
            store_id=store_id,
            tenant_id=tenant_id,
            dept_id=dept_id,
            name=name,
        )

        # 如果已有旧连接先关闭
        old_conn = self._connections.pop(printer_id, None)
        if old_conn is not None:
            await old_conn.disconnect()

        self._printers[printer_id] = info
        logger.info(
            "print_manager.printer_registered",
            printer_id=printer_id,
            ip=ip,
            port=port,
            role=role,
            store_id=store_id,
            dept_id=dept_id,
        )
        return info

    async def unregister_printer(self, printer_id: str) -> None:
        """移除打印机注册。"""
        self._printers.pop(printer_id, None)
        conn = self._connections.pop(printer_id, None)
        if conn is not None:
            await conn.disconnect()
        logger.info("print_manager.printer_unregistered", printer_id=printer_id)

    # ─── 连接池 ───

    async def _get_connection(self, printer_id: str) -> ESCPOSPrinter:
        """获取或创建打印机连接（连接池复用）。"""
        info = self._printers.get(printer_id)
        if info is None:
            raise ValueError(f"打印机未注册: {printer_id}")

        conn = self._connections.get(printer_id)
        if conn is not None and conn.is_connected:
            return conn

        # 创建新连接
        conn = ESCPOSPrinter(ip=info.ip, port=info.port, timeout=5)
        await conn.connect()
        self._connections[printer_id] = conn
        return conn

    # ─── 打印任务 ───

    async def print_receipt(
        self,
        order_id: str,
        template_type: str,
        tenant_id: str,
        store_id: str,
        order: dict,
        store: Optional[dict] = None,
        payment: Optional[dict] = None,
    ) -> PrintTask:
        """打印小票（自动选择打印机 + 渲染模板 + 发送）。

        Args:
            order_id: 订单ID
            template_type: 模板类型 cashier_receipt / checkout_bill / shift_report
            tenant_id: 租户ID
            store_id: 门店ID
            order: 订单数据
            store: 门店信息
            payment: 支付信息

        Returns:
            PrintTask 打印任务
        """
        store = store or {}
        payment = payment or {}

        # 选择收银打印机
        printer_id = self._find_printer(store_id, PrinterRole.CASHIER)
        if printer_id is None:
            raise ValueError(f"门店 {store_id} 无可用收银打印机")

        # 渲染模板
        if template_type == "cashier_receipt":
            content = await self._template.render_cashier_receipt(order, store, payment)
        elif template_type == "checkout_bill":
            content = await self._template.render_checkout_bill(order, store)
        elif template_type == "shift_report":
            content = await self._template.render_shift_report(order)
        elif template_type == "daily_report":
            content = await self._template.render_daily_report(order)
        else:
            raise ValueError(f"未知模板类型: {template_type}")

        # 创建任务并执行
        task = PrintTask(
            task_id=str(uuid.uuid4()),
            printer_id=printer_id,
            template_type=template_type,
            content=content,
            tenant_id=tenant_id,
            store_id=store_id,
            order_id=order_id,
        )
        await self._execute_task(task)
        return task

    async def print_kitchen_order(
        self,
        order_id: str,
        tenant_id: str,
        store_id: str,
        order: dict,
    ) -> list[PrintTask]:
        """厨打分单 — 根据菜品→档口映射，分发到各厨打打印机。

        Args:
            order_id: 订单ID
            tenant_id: 租户ID
            store_id: 门店ID
            order: 订单数据（含 items，每个 item 有 kitchen_station/dept_id）

        Returns:
            各厨打任务列表
        """
        # 按档口分组
        dept_items: dict[str, list[dict]] = {}
        for item in order.get("items", []):
            dept = item.get("dept_id") or item.get("kitchen_station") or "default"
            dept_items.setdefault(dept, []).append(item)

        tasks: list[PrintTask] = []
        table_no = order.get("table_number", "-")
        order_no = order.get("order_no", "")

        for dept_id, items in dept_items.items():
            # 找到对应档口的厨打打印机
            printer_id = self._find_kitchen_printer(store_id, dept_id)
            if printer_id is None:
                # 回退到任意厨打打印机
                printer_id = self._find_printer(store_id, PrinterRole.KITCHEN)
            if printer_id is None:
                logger.warning(
                    "print_manager.no_kitchen_printer",
                    store_id=store_id,
                    dept_id=dept_id,
                )
                continue

            dept_name = items[0].get("kitchen_station") or dept_id
            content = await self._template.render_kitchen_ticket(
                order_items=items,
                table_no=table_no,
                dept_name=dept_name,
                order_no=order_no,
            )

            task = PrintTask(
                task_id=str(uuid.uuid4()),
                printer_id=printer_id,
                template_type="kitchen_ticket",
                content=content,
                tenant_id=tenant_id,
                store_id=store_id,
                order_id=order_id,
            )
            await self._execute_task(task)
            tasks.append(task)

        logger.info(
            "print_manager.kitchen_dispatched",
            order_id=order_id,
            dept_count=len(dept_items),
            task_count=len(tasks),
        )
        return tasks

    async def reprint(self, task_id: str) -> PrintTask:
        """补打 — 重新执行历史打印任务。

        Args:
            task_id: 原始任务ID

        Returns:
            新的打印任务
        """
        original = self._task_history.get(task_id)
        if original is None:
            raise ValueError(f"打印任务不存在: {task_id}")

        new_task = PrintTask(
            task_id=str(uuid.uuid4()),
            printer_id=original.printer_id,
            template_type=original.template_type,
            content=original.content,
            tenant_id=original.tenant_id,
            store_id=original.store_id,
            order_id=original.order_id,
        )
        await self._execute_task(new_task)
        logger.info(
            "print_manager.reprint",
            original_task_id=task_id,
            new_task_id=new_task.task_id,
        )
        return new_task

    # ─── 状态查询 ───

    async def get_print_queue(self, store_id: str) -> list[dict]:
        """获取门店打印队列。"""
        return [
            t.to_dict()
            for t in self._task_queue
            if t.store_id == store_id
        ]

    async def get_printer_status(self, store_id: str) -> list[dict]:
        """获取门店所有打印机状态。"""
        results = []
        for pid, info in self._printers.items():
            if info.store_id != store_id:
                continue

            conn = self._connections.get(pid)
            if conn is not None and conn.is_connected:
                try:
                    status = await conn.get_status()
                except (ConnectionError, OSError):
                    status = PrinterStatus.OFFLINE
            else:
                status = PrinterStatus.OFFLINE

            results.append({
                **info.to_dict(),
                "status": status.value,
                "connected": conn is not None and conn.is_connected if conn else False,
            })
        return results

    async def configure_store_printers(
        self,
        store_id: str,
        config: list[dict],
        tenant_id: str,
    ) -> list[PrinterInfo]:
        """批量配置门店打印机。

        Args:
            store_id: 门店ID
            config: 打印机配置列表 [{ip, port, role, dept_id, name}]
            tenant_id: 租户ID

        Returns:
            注册后的 PrinterInfo 列表
        """
        # 移除该门店的旧配置
        old_ids = [
            pid for pid, info in self._printers.items()
            if info.store_id == store_id
        ]
        for pid in old_ids:
            await self.unregister_printer(pid)

        # 注册新配置
        results = []
        for item in config:
            printer_id = item.get("printer_id") or str(uuid.uuid4())
            info = await self.register_printer(
                printer_id=printer_id,
                ip=item["ip"],
                port=item.get("port", 9100),
                role=item["role"],
                store_id=store_id,
                tenant_id=tenant_id,
                dept_id=item.get("dept_id"),
                name=item.get("name"),
            )
            results.append(info)

        logger.info(
            "print_manager.store_configured",
            store_id=store_id,
            printer_count=len(results),
        )
        return results

    # ─── 测试打印 ───

    async def test_print(self, printer_id: str) -> PrintTask:
        """打印测试页。"""
        info = self._printers.get(printer_id)
        if info is None:
            raise ValueError(f"打印机未注册: {printer_id}")

        # 构建测试页内容
        from .printer_driver import (
            ESC_INIT, ESC_ALIGN_CENTER, ESC_ALIGN_LEFT,
            GS_SIZE_DOUBLE_BOTH, GS_SIZE_NORMAL,
            ESC_BOLD_ON, ESC_BOLD_OFF,
            GS_CUT_PARTIAL, ESC_FEED, LF, LINE_WIDTH,
        )
        buf = bytearray()
        buf += ESC_INIT
        buf += ESC_ALIGN_CENTER + GS_SIZE_DOUBLE_BOTH + ESC_BOLD_ON
        buf += "屯象OS 打印测试".encode("gbk", errors="replace") + LF
        buf += GS_SIZE_NORMAL + ESC_BOLD_OFF
        buf += (b'=' * LINE_WIDTH) + LF
        buf += ESC_ALIGN_LEFT
        buf += f"打印机ID: {printer_id}".encode("gbk", errors="replace") + LF
        buf += f"IP地址:   {info.ip}:{info.port}".encode("gbk", errors="replace") + LF
        buf += f"角色:     {info.role.value}".encode("gbk", errors="replace") + LF
        buf += f"门店ID:   {info.store_id}".encode("gbk", errors="replace") + LF
        if info.dept_id:
            buf += f"档口ID:   {info.dept_id}".encode("gbk", errors="replace") + LF
        buf += (b'-' * LINE_WIDTH) + LF
        buf += "中文打印测试: 屯象科技".encode("gbk", errors="replace") + LF
        buf += "1234567890 ABCDEFGHIJ".encode("gbk", errors="replace") + LF
        buf += (b'-' * LINE_WIDTH) + LF
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        buf += ESC_ALIGN_CENTER
        buf += f"测试时间: {now}".encode("gbk", errors="replace") + LF
        buf += "打印正常".encode("gbk", errors="replace") + LF
        buf += ESC_ALIGN_LEFT
        buf += ESC_FEED + b'\x03' + GS_CUT_PARTIAL

        task = PrintTask(
            task_id=str(uuid.uuid4()),
            printer_id=printer_id,
            template_type="test_page",
            content=bytes(buf),
            tenant_id=info.tenant_id,
            store_id=info.store_id,
        )
        await self._execute_task(task)
        return task

    # ─── 关闭 ───

    async def shutdown(self) -> None:
        """关闭所有打印机连接。"""
        for pid, conn in self._connections.items():
            try:
                await conn.disconnect()
            except OSError:
                pass
        self._connections.clear()
        logger.info("print_manager.shutdown")

    # ─── 内部方法 ───

    def _find_printer(self, store_id: str, role: PrinterRole) -> Optional[str]:
        """查找门店指定角色的打印机。"""
        for pid, info in self._printers.items():
            if info.store_id == store_id and info.role == role:
                return pid
        return None

    def _find_kitchen_printer(self, store_id: str, dept_id: str) -> Optional[str]:
        """查找门店指定档口的厨打打印机。"""
        for pid, info in self._printers.items():
            if (
                info.store_id == store_id
                and info.role == PrinterRole.KITCHEN
                and info.dept_id == dept_id
            ):
                return pid
        return None

    async def _execute_task(self, task: PrintTask) -> None:
        """执行打印任务（含重试）。"""
        async with self._lock:
            self._task_queue.append(task)
            # 限制队列长度
            if len(self._task_queue) > self.MAX_QUEUE_SIZE:
                self._task_queue = self._task_queue[-self.MAX_QUEUE_SIZE:]

        task.status = PrintTaskStatus.PRINTING

        for attempt in range(self.MAX_RETRY):
            try:
                conn = await self._get_connection(task.printer_id)
                await conn.send_raw(task.content)
                task.status = PrintTaskStatus.SUCCESS
                logger.info(
                    "print_manager.task_success",
                    task_id=task.task_id,
                    printer_id=task.printer_id,
                    template=task.template_type,
                    size=len(task.content),
                    attempt=attempt + 1,
                )
                break
            except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
                task.retry_count = attempt + 1
                task.error_msg = str(exc)
                # 断开旧连接以便重试时重建
                old_conn = self._connections.pop(task.printer_id, None)
                if old_conn is not None:
                    try:
                        await old_conn.disconnect()
                    except OSError:
                        pass
                logger.warning(
                    "print_manager.task_retry",
                    task_id=task.task_id,
                    printer_id=task.printer_id,
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt < self.MAX_RETRY - 1:
                    await asyncio.sleep(1)
        else:
            task.status = PrintTaskStatus.FAILED
            logger.error(
                "print_manager.task_failed",
                task_id=task.task_id,
                printer_id=task.printer_id,
                error=task.error_msg,
            )

        self._task_history[task.task_id] = task


# ─── 模块级单例 ───

_print_manager: Optional[PrintManager] = None


def get_print_manager() -> PrintManager:
    """获取全局 PrintManager 单例。"""
    global _print_manager
    if _print_manager is None:
        _print_manager = PrintManager()
    return _print_manager
