"""Mac Station 门店配置 — 本地PG / 云端API / Tailscale / 离线模式

环境变量优先，未设置则使用默认值。
离线模式通过定期探测云端 /health 自动切换。
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field

import httpx
import structlog

logger = structlog.get_logger(__name__)

# ── 离线检测常量 ──
_CLOUD_PROBE_INTERVAL_S = 30  # 每30秒探测一次云端
_CLOUD_PROBE_TIMEOUT_S = 5  # 探测超时5秒视为离线


@dataclass(frozen=False)
class StationConfig:
    """门店 Mac Station 全局配置（单例）。

    Attributes:
        store_id: 本机归属的门店 ID（环境变量 STORE_ID）
        tenant_id: 租户 ID（环境变量 TENANT_ID）
        local_db_url: 本地 PostgreSQL 连接串
        cloud_api_url: 云端 API 网关地址
        coreml_bridge_url: 本地 Core ML 桥接地址
        tailscale_ip: Tailscale 分配的内网 IP
        redis_url: 本地 Redis（用于 Pub/Sub，可选）
        offline: 当前是否处于离线模式
        last_cloud_check_at: 上次云端探测的 UNIX 时间戳
        boot_time: 进程启动的 UNIX 时间戳
    """

    store_id: str = ""
    tenant_id: str = ""
    local_db_url: str = ""
    cloud_api_url: str = ""
    coreml_bridge_url: str = ""
    tailscale_ip: str = ""
    redis_url: str = ""
    offline: bool = False
    last_cloud_check_at: float = 0.0
    boot_time: float = field(default_factory=time.time)

    @classmethod
    def from_env(cls) -> StationConfig:
        """从环境变量构造配置实例。"""
        return cls(
            store_id=os.getenv("STORE_ID", "default_store"),
            tenant_id=os.getenv("TENANT_ID", "default_tenant"),
            local_db_url=os.getenv(
                "LOCAL_DB_URL",
                "postgresql+asyncpg://tunxiang:tunxiang@localhost:5432/tunxiang_local",
            ),
            cloud_api_url=os.getenv("CLOUD_API_URL", "http://localhost:8000"),
            coreml_bridge_url=os.getenv("COREML_BRIDGE_URL", "http://localhost:8100"),
            tailscale_ip=os.getenv("TAILSCALE_IP", ""),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        )

    async def probe_cloud(self) -> bool:
        """探测云端 API 网关是否可达。

        更新 offline 状态和 last_cloud_check_at 时间戳。

        Returns:
            True 表示云端可达（在线模式）。
        """
        try:
            async with httpx.AsyncClient(timeout=_CLOUD_PROBE_TIMEOUT_S) as client:
                resp = await client.get(f"{self.cloud_api_url}/health")
                reachable = resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError, OSError):
            reachable = False

        previous = self.offline
        self.offline = not reachable
        self.last_cloud_check_at = time.time()

        if previous != self.offline:
            logger.warning(
                "offline_mode_changed",
                offline=self.offline,
                cloud_url=self.cloud_api_url,
            )

        return reachable

    async def run_cloud_probe_loop(self) -> None:
        """后台定期探测云端可达性的死循环任务。

        在 lifespan 中通过 asyncio.create_task 启动，进程退出时自动取消。
        """
        while True:
            await self.probe_cloud()
            await asyncio.sleep(_CLOUD_PROBE_INTERVAL_S)


# ── 模块级单例 ──

_config: StationConfig | None = None


def get_config() -> StationConfig:
    """获取全局配置单例（懒初始化）。"""
    global _config
    if _config is None:
        _config = StationConfig.from_env()
    return _config
