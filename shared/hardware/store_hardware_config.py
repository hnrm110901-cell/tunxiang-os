"""门店硬件配置管理

负责门店级别的硬件设备配置、连接测试、状态监控、模板管理。
支持多租户隔离，所有操作必须携带 tenant_id。

典型流程：
1. 总部创建硬件模板（标准店/旗舰店/小店）
2. 新开门店应用模板
3. 门店运维微调（更换打印机IP等）
4. 日常监控设备状态
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from .device_registry import DEVICE_REGISTRY, get_device
from .protocol_support import create_protocol_handler, ProtocolHandler

logger = structlog.get_logger()


class DeviceInstance:
    """门店中一台具体设备的实例。"""

    def __init__(
        self,
        instance_id: str,
        device_key: str,
        store_id: str,
        tenant_id: str,
        connection_params: dict,
        role: str = "",
        name: str = "",
        dept_id: str = "",
    ):
        self.instance_id = instance_id
        self.device_key = device_key
        self.store_id = store_id
        self.tenant_id = tenant_id
        self.connection_params = connection_params
        self.role = role
        self.name = name
        self.dept_id = dept_id
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
        self.last_status: str = "unknown"
        self.last_check_at: Optional[datetime] = None
        self._protocol_handler: Optional[ProtocolHandler] = None

    def to_dict(self) -> dict:
        """序列化为字典。"""
        device_info = DEVICE_REGISTRY.get(self.device_key, {})
        return {
            "instance_id": self.instance_id,
            "device_key": self.device_key,
            "brand": device_info.get("brand", ""),
            "model": device_info.get("model", ""),
            "category": device_info.get("category", ""),
            "store_id": self.store_id,
            "tenant_id": self.tenant_id,
            "connection_params": self.connection_params,
            "role": self.role,
            "name": self.name,
            "dept_id": self.dept_id,
            "last_status": self.last_status,
            "last_check_at": self.last_check_at.isoformat() if self.last_check_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class HardwareTemplate:
    """硬件配置模板 -- 用于快速部署新门店。"""

    def __init__(
        self,
        template_id: str,
        template_name: str,
        tenant_id: str,
        devices: list[dict],
        description: str = "",
    ):
        self.template_id = template_id
        self.template_name = template_name
        self.tenant_id = tenant_id
        self.devices = devices
        self.description = description
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "template_id": self.template_id,
            "template_name": self.template_name,
            "tenant_id": self.tenant_id,
            "devices": self.devices,
            "description": self.description,
            "device_count": len(self.devices),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class StoreHardwareConfig:
    """门店硬件配置管理器。

    管理门店的硬件设备配置、连接测试、状态监控。
    内存存储，生产环境应替换为数据库持久化。
    """

    def __init__(self) -> None:
        # {store_id: {instance_id: DeviceInstance}}
        self._store_devices: dict[str, dict[str, DeviceInstance]] = {}
        # {template_id: HardwareTemplate}
        self._templates: dict[str, HardwareTemplate] = {}
        # {device_key: ProtocolHandler} — 活跃连接池
        self._connections: dict[str, ProtocolHandler] = {}

    # ─── 门店设备配置 ───

    async def configure_store(
        self,
        store_id: str,
        devices: list[dict],
        tenant_id: str,
        db: Any = None,
    ) -> list[dict]:
        """配置门店硬件设备。

        Args:
            store_id: 门店 ID
            devices: 设备配置列表，每项包含:
                - device_key: 设备注册表中的标识
                - connection_params: 连接参数 {"ip": "...", "port": 9100} 等
                - role: 设备角色，如 "cashier", "kitchen"
                - name: 设备名称（可选）
                - dept_id: 关联档口 ID（可选，厨打用）
            tenant_id: 租户 ID
            db: 数据库会话（可选，当前为内存存储）

        Returns:
            已配置的设备实例列表
        """
        # 清除该门店旧配置
        old_devices = self._store_devices.pop(store_id, {})
        for inst in old_devices.values():
            conn = self._connections.pop(inst.instance_id, None)
            if conn is not None:
                await conn.disconnect()

        # 创建新配置
        store_instances: dict[str, DeviceInstance] = {}
        results: list[dict] = []

        for item in devices:
            device_key = item["device_key"]
            # 验证设备存在
            get_device(device_key)

            instance_id = item.get("instance_id", str(uuid.uuid4()))
            instance = DeviceInstance(
                instance_id=instance_id,
                device_key=device_key,
                store_id=store_id,
                tenant_id=tenant_id,
                connection_params=item.get("connection_params", {}),
                role=item.get("role", ""),
                name=item.get("name", ""),
                dept_id=item.get("dept_id", ""),
            )
            store_instances[instance_id] = instance
            results.append(instance.to_dict())

        self._store_devices[store_id] = store_instances

        logger.info(
            "store_hardware.configured",
            store_id=store_id,
            device_count=len(results),
            tenant_id=tenant_id,
        )
        return results

    async def add_device(
        self,
        store_id: str,
        device_key: str,
        connection_params: dict,
        tenant_id: str,
        role: str = "",
        name: str = "",
        dept_id: str = "",
        db: Any = None,
    ) -> dict:
        """向门店添加单个设备。

        Args:
            store_id: 门店 ID
            device_key: 设备注册表标识
            connection_params: 连接参数
            tenant_id: 租户 ID
            role: 设备角色
            name: 设备名称
            dept_id: 关联档口 ID
            db: 数据库会话

        Returns:
            设备实例信息
        """
        get_device(device_key)  # 验证设备存在

        instance_id = str(uuid.uuid4())
        instance = DeviceInstance(
            instance_id=instance_id,
            device_key=device_key,
            store_id=store_id,
            tenant_id=tenant_id,
            connection_params=connection_params,
            role=role,
            name=name,
            dept_id=dept_id,
        )

        if store_id not in self._store_devices:
            self._store_devices[store_id] = {}
        self._store_devices[store_id][instance_id] = instance

        logger.info(
            "store_hardware.device_added",
            store_id=store_id,
            device_key=device_key,
            instance_id=instance_id,
            tenant_id=tenant_id,
        )
        return instance.to_dict()

    async def remove_device(
        self,
        store_id: str,
        instance_id: str,
        tenant_id: str,
        db: Any = None,
    ) -> None:
        """从门店移除设备。

        Args:
            store_id: 门店 ID
            instance_id: 设备实例 ID
            tenant_id: 租户 ID
            db: 数据库会话
        """
        store_devices = self._store_devices.get(store_id, {})
        instance = store_devices.pop(instance_id, None)
        if instance is None:
            raise ValueError(f"设备实例不存在: {instance_id}")
        if instance.tenant_id != tenant_id:
            raise PermissionError("无权操作该设备")

        conn = self._connections.pop(instance_id, None)
        if conn is not None:
            await conn.disconnect()

        logger.info(
            "store_hardware.device_removed",
            store_id=store_id,
            instance_id=instance_id,
            tenant_id=tenant_id,
        )

    async def get_store_config(
        self,
        store_id: str,
        tenant_id: str,
        db: Any = None,
    ) -> list[dict]:
        """获取门店所有设备配置。

        Args:
            store_id: 门店 ID
            tenant_id: 租户 ID
            db: 数据库会话

        Returns:
            设备实例列表
        """
        store_devices = self._store_devices.get(store_id, {})
        return [
            inst.to_dict()
            for inst in store_devices.values()
            if inst.tenant_id == tenant_id
        ]

    # ─── 设备测试与状态 ───

    async def test_device(
        self,
        store_id: str,
        instance_id: str,
        tenant_id: str,
    ) -> dict:
        """测试单个设备连通性。

        Args:
            store_id: 门店 ID
            instance_id: 设备实例 ID
            tenant_id: 租户 ID

        Returns:
            {"instance_id": str, "status": "online"/"offline", "latency_ms": float}
        """
        store_devices = self._store_devices.get(store_id, {})
        instance = store_devices.get(instance_id)
        if instance is None:
            raise ValueError(f"设备实例不存在: {instance_id}")
        if instance.tenant_id != tenant_id:
            raise PermissionError("无权操作该设备")

        device_info = DEVICE_REGISTRY.get(instance.device_key, {})
        protocol = device_info.get("protocol", "")

        start_time = datetime.now(timezone.utc)
        status = "offline"

        try:
            handler = create_protocol_handler(protocol, tenant_id, instance.device_key)
            await handler.connect(**instance.connection_params)
            is_healthy = await handler.health_check()
            status = "online" if is_healthy else "offline"
            await handler.disconnect()
        except (ConnectionError, ValueError, OSError) as exc:
            status = "offline"
            logger.warning(
                "store_hardware.test_failed",
                instance_id=instance_id,
                error=str(exc),
                tenant_id=tenant_id,
            )

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        instance.last_status = status
        instance.last_check_at = datetime.now(timezone.utc)

        result = {
            "instance_id": instance_id,
            "device_key": instance.device_key,
            "brand": device_info.get("brand", ""),
            "model": device_info.get("model", ""),
            "status": status,
            "latency_ms": round(elapsed, 2),
        }

        logger.info(
            "store_hardware.device_tested",
            **result,
            tenant_id=tenant_id,
        )
        return result

    async def test_all_devices(
        self,
        store_id: str,
        tenant_id: str,
    ) -> list[dict]:
        """批量测试门店所有设备连通性。

        Args:
            store_id: 门店 ID
            tenant_id: 租户 ID

        Returns:
            各设备测试结果列表
        """
        store_devices = self._store_devices.get(store_id, {})
        results = []

        for instance_id, instance in store_devices.items():
            if instance.tenant_id != tenant_id:
                continue
            try:
                result = await self.test_device(store_id, instance_id, tenant_id)
                results.append(result)
            except (ValueError, PermissionError) as exc:
                results.append({
                    "instance_id": instance_id,
                    "device_key": instance.device_key,
                    "status": "error",
                    "error": str(exc),
                })

        logger.info(
            "store_hardware.all_devices_tested",
            store_id=store_id,
            total=len(results),
            online=sum(1 for r in results if r.get("status") == "online"),
            tenant_id=tenant_id,
        )
        return results

    async def get_device_status(
        self,
        store_id: str,
        tenant_id: str,
    ) -> list[dict]:
        """获取门店所有设备最新状态（不重新测试，返回缓存状态）。

        Args:
            store_id: 门店 ID
            tenant_id: 租户 ID

        Returns:
            各设备状态列表
        """
        store_devices = self._store_devices.get(store_id, {})
        return [
            {
                **inst.to_dict(),
                "status": inst.last_status,
            }
            for inst in store_devices.values()
            if inst.tenant_id == tenant_id
        ]

    # ─── 硬件模板管理 ───

    async def create_store_template(
        self,
        template_name: str,
        devices: list[dict],
        tenant_id: str,
        description: str = "",
        db: Any = None,
    ) -> dict:
        """创建门店硬件配置模板。

        Args:
            template_name: 模板名称，如 "标准店配置", "旗舰店配置"
            devices: 设备配置列表（同 configure_store 的 devices 参数）
            tenant_id: 租户 ID
            description: 模板说明
            db: 数据库会话

        Returns:
            模板信息字典
        """
        # 验证所有设备 key 有效
        for item in devices:
            get_device(item["device_key"])

        template_id = str(uuid.uuid4())
        template = HardwareTemplate(
            template_id=template_id,
            template_name=template_name,
            tenant_id=tenant_id,
            devices=devices,
            description=description,
        )
        self._templates[template_id] = template

        logger.info(
            "store_hardware.template_created",
            template_id=template_id,
            template_name=template_name,
            device_count=len(devices),
            tenant_id=tenant_id,
        )
        return template.to_dict()

    async def list_templates(self, tenant_id: str) -> list[dict]:
        """列出租户的所有硬件模板。

        Args:
            tenant_id: 租户 ID

        Returns:
            模板列表
        """
        return [
            tpl.to_dict()
            for tpl in self._templates.values()
            if tpl.tenant_id == tenant_id
        ]

    async def apply_template(
        self,
        template_id: str,
        store_id: str,
        tenant_id: str,
        connection_overrides: dict | None = None,
        db: Any = None,
    ) -> list[dict]:
        """将硬件模板应用到门店。

        Args:
            template_id: 模板 ID
            store_id: 目标门店 ID
            tenant_id: 租户 ID
            connection_overrides: 连接参数覆盖（每个设备可单独覆盖 IP 等）
                格式: {"device_key": {"ip": "192.168.1.100"}}
            db: 数据库会话

        Returns:
            门店设备配置列表
        """
        template = self._templates.get(template_id)
        if template is None:
            raise ValueError(f"模板不存在: {template_id}")
        if template.tenant_id != tenant_id:
            raise PermissionError("无权使用该模板")

        overrides = connection_overrides or {}

        # 合并覆盖参数
        devices = []
        for device_config in template.devices:
            merged = {**device_config}
            device_key = merged["device_key"]
            if device_key in overrides:
                conn_params = {
                    **merged.get("connection_params", {}),
                    **overrides[device_key],
                }
                merged["connection_params"] = conn_params
            devices.append(merged)

        result = await self.configure_store(store_id, devices, tenant_id, db)

        logger.info(
            "store_hardware.template_applied",
            template_id=template_id,
            template_name=template.template_name,
            store_id=store_id,
            device_count=len(result),
            tenant_id=tenant_id,
        )
        return result

    # ─── 关闭 ───

    async def shutdown(self) -> None:
        """关闭所有活跃连接。"""
        for conn in self._connections.values():
            try:
                await conn.disconnect()
            except OSError:
                pass
        self._connections.clear()
        logger.info("store_hardware.shutdown")


# ─── 模块级单例 ───

_config_instance: Optional[StoreHardwareConfig] = None


def get_store_hardware_config() -> StoreHardwareConfig:
    """获取全局 StoreHardwareConfig 单例。"""
    global _config_instance
    if _config_instance is None:
        _config_instance = StoreHardwareConfig()
    return _config_instance
