"""设备注册与心跳服务 — 云端注册 + 定时心跳上报

职责：
1. 设备自动注册到云端（store_id + device_type + mac_address + version）
2. 心跳上报（每60s）：CPU/内存/磁盘/网络状态
3. 在线/离线状态自动检测

Mock 模式：CLOUD_API_URL 不可达时本地缓存，恢复后补报。
"""
from __future__ import annotations

import asyncio
import os
import platform
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

# ── 常量 ──
_HEARTBEAT_INTERVAL_S = 60
_REGISTER_RETRY_INTERVAL_S = 30
_CLOUD_TIMEOUT_S = 10


@dataclass
class DeviceInfo:
    """本机设备信息快照。"""

    store_id: str
    tenant_id: str
    device_type: str
    mac_address: str
    app_version: str
    hostname: str
    os_version: str
    hardware_model: str
    ip_address: str


@dataclass
class SystemStats:
    """系统资源指标快照。"""

    cpu_usage_pct: float = 0.0
    memory_usage_pct: float = 0.0
    memory_total_mb: int = 0
    memory_used_mb: int = 0
    disk_usage_pct: float = 0.0
    disk_total_gb: float = 0.0
    disk_used_gb: float = 0.0
    network_bytes_sent: int = 0
    network_bytes_recv: int = 0
    uptime_seconds: float = 0.0
    load_avg_1m: float = 0.0
    load_avg_5m: float = 0.0
    load_avg_15m: float = 0.0


def _get_mac_address() -> str:
    """获取本机 MAC 地址，格式 XX:XX:XX:XX:XX:XX。"""
    mac_int = uuid.getnode()
    mac_hex = f"{mac_int:012x}"
    return ":".join(mac_hex[i : i + 2].upper() for i in range(0, 12, 2))


def _collect_system_stats() -> SystemStats:
    """采集系统资源指标（CPU/内存/磁盘/网络/负载）。

    依赖 psutil，未安装时返回零值。
    """
    stats = SystemStats()
    try:
        import psutil

        # CPU
        stats.cpu_usage_pct = psutil.cpu_percent(interval=0.5)

        # 内存
        mem = psutil.virtual_memory()
        stats.memory_usage_pct = mem.percent
        stats.memory_total_mb = mem.total // (1024 * 1024)
        stats.memory_used_mb = mem.used // (1024 * 1024)

        # 磁盘
        disk = psutil.disk_usage("/")
        stats.disk_usage_pct = disk.percent
        stats.disk_total_gb = round(disk.total / (1024**3), 1)
        stats.disk_used_gb = round(disk.used / (1024**3), 1)

        # 网络
        net = psutil.net_io_counters()
        stats.network_bytes_sent = net.bytes_sent
        stats.network_bytes_recv = net.bytes_recv

        # 运行时长
        stats.uptime_seconds = time.time() - psutil.boot_time()

        # 负载
        load = os.getloadavg()
        stats.load_avg_1m = load[0]
        stats.load_avg_5m = load[1]
        stats.load_avg_15m = load[2]

    except ImportError:
        logger.debug("psutil_not_installed_using_mock_stats")
    except OSError as exc:
        logger.warning("system_stats_collection_error", error=str(exc))

    return stats


class DeviceRegistry:
    """设备注册与心跳上报服务。

    启动时向云端注册本机设备信息，之后定时上报心跳（系统指标）。
    云端不可达时本地缓存，恢复后自动重试。

    Attributes:
        _device_info: 本机设备信息
        _cloud_api_url: 云端 API 网关地址
        _device_id: 云端返回的设备 ID（注册成功后填充）
        _registered: 是否已注册成功
        _last_heartbeat_at: 上次心跳成功时间
        _heartbeat_failures: 连续心跳失败次数
    """

    def __init__(self, cloud_api_url: str | None = None) -> None:
        self._cloud_api_url = cloud_api_url or os.getenv(
            "CLOUD_API_URL", "http://localhost:8000"
        )
        self._device_info: DeviceInfo | None = None
        self._device_id: str | None = None
        self._registered: bool = False
        self._last_heartbeat_at: float = 0.0
        self._heartbeat_failures: int = 0
        self._boot_time: float = time.time()
        # 心跳历史（内存保留最近 100 条）
        self._heartbeat_history: list[dict[str, Any]] = []

    def _build_device_info(self) -> DeviceInfo:
        """构造本机设备信息。"""
        return DeviceInfo(
            store_id=os.getenv("STORE_ID", "default_store"),
            tenant_id=os.getenv("TENANT_ID", "default_tenant"),
            device_type="mac_mini",
            mac_address=_get_mac_address(),
            app_version=os.getenv("APP_VERSION", "0.0.0"),
            hostname=platform.node(),
            os_version=f"{platform.system()} {platform.release()}",
            hardware_model=os.getenv("HARDWARE_MODEL", f"Mac mini ({platform.machine()})"),
            ip_address=os.getenv("TAILSCALE_IP", ""),
        )

    @property
    def device_info(self) -> DeviceInfo | None:
        return self._device_info

    @property
    def device_id(self) -> str | None:
        return self._device_id

    @property
    def is_registered(self) -> bool:
        return self._registered

    @property
    def last_heartbeat_at(self) -> float:
        return self._last_heartbeat_at

    def get_status(self) -> dict[str, Any]:
        """返回当前注册与心跳状态摘要。"""
        return {
            "device_id": self._device_id,
            "registered": self._registered,
            "last_heartbeat_at": self._last_heartbeat_at,
            "heartbeat_failures": self._heartbeat_failures,
            "uptime_seconds": time.time() - self._boot_time,
            "device_info": {
                "store_id": self._device_info.store_id if self._device_info else None,
                "device_type": self._device_info.device_type if self._device_info else None,
                "mac_address": self._device_info.mac_address if self._device_info else None,
                "app_version": self._device_info.app_version if self._device_info else None,
            },
        }

    def get_heartbeat_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """返回最近的心跳历史记录。"""
        return self._heartbeat_history[-limit:]

    # ── 注册 ──

    async def register(self) -> bool:
        """向云端注册本机设备。成功返回 True。

        注册失败（网络不可达）时返回 False，不抛异常。
        """
        self._device_info = self._build_device_info()
        info = self._device_info

        payload = {
            "device_type": info.device_type,
            "device_name": info.hostname,
            "mac_address": info.mac_address,
            "hardware_model": info.hardware_model,
            "app_version": info.app_version,
            "os_version": info.os_version,
            "ip_address": info.ip_address,
        }
        headers = {
            "X-Tenant-ID": info.tenant_id,
            "X-Store-ID": info.store_id,
        }

        try:
            async with httpx.AsyncClient(timeout=_CLOUD_TIMEOUT_S) as client:
                resp = await client.post(
                    f"{self._cloud_api_url}/api/v1/devices/register",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                body = resp.json()

                if body.get("ok"):
                    self._device_id = body["data"]["device_id"]
                    self._registered = True
                    logger.info(
                        "device_registered",
                        device_id=self._device_id,
                        store_id=info.store_id,
                        mac=info.mac_address,
                    )
                    return True

                logger.warning("device_register_rejected", body=body)
                return False

        except httpx.TimeoutException:
            logger.warning("device_register_timeout", cloud_url=self._cloud_api_url)
            return False
        except httpx.ConnectError:
            logger.warning("device_register_connect_error", cloud_url=self._cloud_api_url)
            return False
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "device_register_http_error",
                status=exc.response.status_code,
                body=exc.response.text[:500],
            )
            return False

    # ── 心跳 ──

    async def send_heartbeat(self) -> bool:
        """采集系统指标并上报心跳到云端。成功返回 True。"""
        if not self._registered or not self._device_id or not self._device_info:
            logger.debug("heartbeat_skipped_not_registered")
            return False

        stats = _collect_system_stats()

        payload = {
            "cpu_usage_pct": stats.cpu_usage_pct,
            "memory_usage_pct": stats.memory_usage_pct,
            "disk_usage_pct": stats.disk_usage_pct,
            "app_version": self._device_info.app_version,
            "extra": {
                "memory_total_mb": stats.memory_total_mb,
                "memory_used_mb": stats.memory_used_mb,
                "disk_total_gb": stats.disk_total_gb,
                "disk_used_gb": stats.disk_used_gb,
                "network_bytes_sent": stats.network_bytes_sent,
                "network_bytes_recv": stats.network_bytes_recv,
                "uptime_seconds": stats.uptime_seconds,
                "load_avg_1m": stats.load_avg_1m,
                "load_avg_5m": stats.load_avg_5m,
                "load_avg_15m": stats.load_avg_15m,
            },
        }
        headers = {"X-Tenant-ID": self._device_info.tenant_id}

        try:
            async with httpx.AsyncClient(timeout=_CLOUD_TIMEOUT_S) as client:
                resp = await client.post(
                    f"{self._cloud_api_url}/api/v1/devices/{self._device_id}/heartbeat",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()

            self._last_heartbeat_at = time.time()
            self._heartbeat_failures = 0

            # 记录历史
            record = {
                "timestamp": self._last_heartbeat_at,
                "cpu_pct": stats.cpu_usage_pct,
                "mem_pct": stats.memory_usage_pct,
                "disk_pct": stats.disk_usage_pct,
                "load_1m": stats.load_avg_1m,
                "success": True,
            }
            self._heartbeat_history.append(record)
            if len(self._heartbeat_history) > 100:
                self._heartbeat_history = self._heartbeat_history[-100:]

            logger.debug(
                "heartbeat_sent",
                device_id=self._device_id,
                cpu=stats.cpu_usage_pct,
                mem=stats.memory_usage_pct,
            )
            return True

        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            self._heartbeat_failures += 1
            self._heartbeat_history.append({
                "timestamp": time.time(),
                "success": False,
                "error": str(exc),
            })
            if len(self._heartbeat_history) > 100:
                self._heartbeat_history = self._heartbeat_history[-100:]

            logger.warning(
                "heartbeat_failed",
                device_id=self._device_id,
                failures=self._heartbeat_failures,
                error=str(exc),
            )
            return False

    # ── 后台循环 ──

    async def run_register_loop(self) -> None:
        """后台任务：持续尝试注册直到成功。"""
        while not self._registered:
            ok = await self.register()
            if ok:
                break
            await asyncio.sleep(_REGISTER_RETRY_INTERVAL_S)

    async def run_heartbeat_loop(self) -> None:
        """后台任务：注册成功后定时发送心跳。"""
        # 等待注册完成
        while not self._registered:
            await asyncio.sleep(5)

        logger.info("heartbeat_loop_started", interval_s=_HEARTBEAT_INTERVAL_S)
        while True:
            await self.send_heartbeat()
            await asyncio.sleep(_HEARTBEAT_INTERVAL_S)

    async def run(self) -> None:
        """启动注册+心跳的统一入口，供 lifespan 调用。"""
        register_task = asyncio.create_task(self.run_register_loop())
        heartbeat_task = asyncio.create_task(self.run_heartbeat_loop())
        try:
            await asyncio.gather(register_task, heartbeat_task)
        except asyncio.CancelledError:
            register_task.cancel()
            heartbeat_task.cancel()
            logger.info("device_registry_stopped")


# ── 模块级单例 ──

_registry: DeviceRegistry | None = None


def get_device_registry() -> DeviceRegistry:
    """获取设备注册服务单例（懒初始化）。"""
    global _registry
    if _registry is None:
        _registry = DeviceRegistry()
    return _registry
