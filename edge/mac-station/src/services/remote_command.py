"""远程命令执行服务 — 接收云端下发的远程命令并安全执行

支持的命令类型（白名单）：
- restart_service  — 重启指定服务
- clear_cache      — 清除缓存
- sync_now         — 立即触发同步
- collect_logs     — 上传日志到云端
- update_config    — 更新配置
- health_check     — 执行健康检查

安全限制：
- 命令白名单，不在白名单内的命令拒绝执行
- 命令执行结果回报云端
- 所有命令执行留痕（structlog）

Mock 模式：云端不可达时命令结果本地缓存。
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx
import structlog

logger = structlog.get_logger(__name__)

# ── 常量 ──
_POLL_INTERVAL_S = 30
_CLOUD_TIMEOUT_S = 10
_COMMAND_TIMEOUT_S = 60
_MAX_HISTORY = 200


@dataclass
class CommandRequest:
    """云端下发的命令请求。"""

    command_id: str
    command_type: str
    params: dict[str, Any] = field(default_factory=dict)
    issued_at: float = 0.0
    timeout_seconds: int = _COMMAND_TIMEOUT_S


@dataclass
class CommandResult:
    """命令执行结果。"""

    command_id: str
    command_type: str
    success: bool
    started_at: float
    finished_at: float = 0.0
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""


# 命令处理器类型：接收 params，返回 output dict
CommandHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class RemoteCommandService:
    """远程命令执行服务。

    通过长轮询从云端拉取待执行命令，执行后回报结果。
    所有命令必须在白名单中注册，未注册命令拒绝执行。

    Attributes:
        _cloud_api_url: 云端 API 地址
        _device_id: 本机设备 ID
        _handlers: 命令类型 -> 处理函数的映射
        _history: 命令执行历史
        _running: 是否正在运行轮询
    """

    # 命令白名单
    ALLOWED_COMMANDS: set[str] = {
        "restart_service",
        "clear_cache",
        "sync_now",
        "collect_logs",
        "update_config",
        "health_check",
    }

    def __init__(
        self,
        cloud_api_url: str | None = None,
        device_id: str | None = None,
    ) -> None:
        self._cloud_api_url = cloud_api_url or os.getenv(
            "CLOUD_API_URL", "http://localhost:8000"
        )
        self._device_id = device_id or os.getenv("DEVICE_ID", "")
        self._tenant_id = os.getenv("TENANT_ID", "default_tenant")
        self._store_id = os.getenv("STORE_ID", "default_store")

        self._handlers: dict[str, CommandHandler] = {}
        self._history: list[CommandResult] = []
        self._running = False
        self._pending_results: list[CommandResult] = []

        # 注册内置命令处理器
        self._register_builtin_handlers()

    def _register_builtin_handlers(self) -> None:
        """注册内置的命令处理器。"""
        self.register_handler("restart_service", self._handle_restart_service)
        self.register_handler("clear_cache", self._handle_clear_cache)
        self.register_handler("sync_now", self._handle_sync_now)
        self.register_handler("collect_logs", self._handle_collect_logs)
        self.register_handler("update_config", self._handle_update_config)
        self.register_handler("health_check", self._handle_health_check)

    def register_handler(self, command_type: str, handler: CommandHandler) -> None:
        """注册命令处理器。

        Args:
            command_type: 命令类型（必须在白名单中）
            handler: 异步处理函数
        """
        if command_type not in self.ALLOWED_COMMANDS:
            logger.warning(
                "remote_cmd_handler_not_whitelisted",
                command_type=command_type,
            )
            return
        self._handlers[command_type] = handler
        logger.debug("remote_cmd_handler_registered", command_type=command_type)

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """返回命令执行历史。"""
        entries = self._history[-limit:]
        return [
            {
                "command_id": r.command_id,
                "command_type": r.command_type,
                "success": r.success,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "output": r.output,
                "error": r.error,
            }
            for r in reversed(entries)
        ]

    # ── 命令执行 ──

    async def execute_command(self, request: CommandRequest) -> CommandResult:
        """执行单条命令。

        Args:
            request: 命令请求

        Returns:
            执行结果
        """
        result = CommandResult(
            command_id=request.command_id,
            command_type=request.command_type,
            success=False,
            started_at=time.time(),
        )

        # 白名单检查
        if request.command_type not in self.ALLOWED_COMMANDS:
            result.error = f"Command type '{request.command_type}' not in whitelist"
            result.finished_at = time.time()
            logger.warning(
                "remote_cmd_rejected",
                command_id=request.command_id,
                command_type=request.command_type,
            )
            self._record_result(result)
            return result

        handler = self._handlers.get(request.command_type)
        if handler is None:
            result.error = f"No handler registered for '{request.command_type}'"
            result.finished_at = time.time()
            logger.warning(
                "remote_cmd_no_handler",
                command_id=request.command_id,
                command_type=request.command_type,
            )
            self._record_result(result)
            return result

        logger.info(
            "remote_cmd_executing",
            command_id=request.command_id,
            command_type=request.command_type,
            params=request.params,
        )

        try:
            output = await asyncio.wait_for(
                handler(request.params),
                timeout=request.timeout_seconds,
            )
            result.success = True
            result.output = output
            logger.info(
                "remote_cmd_success",
                command_id=request.command_id,
                command_type=request.command_type,
            )

        except asyncio.TimeoutError:
            result.error = f"Command timed out after {request.timeout_seconds}s"
            logger.error(
                "remote_cmd_timeout",
                command_id=request.command_id,
                command_type=request.command_type,
                timeout=request.timeout_seconds,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            result.error = str(exc)
            logger.error(
                "remote_cmd_error",
                command_id=request.command_id,
                command_type=request.command_type,
                error=str(exc),
            )

        result.finished_at = time.time()
        self._record_result(result)
        return result

    def _record_result(self, result: CommandResult) -> None:
        """记录命令结果到历史并加入待回报队列。"""
        self._history.append(result)
        if len(self._history) > _MAX_HISTORY:
            self._history = self._history[-_MAX_HISTORY:]
        self._pending_results.append(result)

    # ── 云端交互 ──

    async def poll_commands(self) -> list[CommandRequest]:
        """从云端拉取待执行命令。

        Returns:
            命令列表（可能为空）。
        """
        if not self._device_id:
            return []

        try:
            async with httpx.AsyncClient(timeout=_CLOUD_TIMEOUT_S) as client:
                resp = await client.get(
                    f"{self._cloud_api_url}/api/v1/devices/{self._device_id}/commands",
                    headers={
                        "X-Tenant-ID": self._tenant_id,
                        "X-Store-ID": self._store_id,
                    },
                )
                if resp.status_code == 404:
                    # 云端尚未实现此端点，静默返回空
                    return []
                resp.raise_for_status()
                body = resp.json()

            commands: list[CommandRequest] = []
            for item in body.get("data", {}).get("items", []):
                commands.append(
                    CommandRequest(
                        command_id=item.get("command_id", ""),
                        command_type=item.get("command_type", ""),
                        params=item.get("params", {}),
                        issued_at=item.get("issued_at", 0),
                        timeout_seconds=item.get("timeout_seconds", _COMMAND_TIMEOUT_S),
                    )
                )

            if commands:
                logger.info("remote_cmd_polled", count=len(commands))
            return commands

        except (httpx.ConnectError, httpx.TimeoutException):
            return []
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                logger.warning(
                    "remote_cmd_poll_error", status=exc.response.status_code
                )
            return []

    async def report_results(self) -> int:
        """将待回报的命令执行结果推送到云端。

        Returns:
            成功回报的数量。
        """
        if not self._pending_results or not self._device_id:
            return 0

        reported = 0
        remaining: list[CommandResult] = []

        for result in self._pending_results:
            payload = {
                "command_id": result.command_id,
                "command_type": result.command_type,
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "started_at": result.started_at,
                "finished_at": result.finished_at,
            }

            try:
                async with httpx.AsyncClient(timeout=_CLOUD_TIMEOUT_S) as client:
                    resp = await client.post(
                        f"{self._cloud_api_url}/api/v1/devices/{self._device_id}/commands/results",
                        json=payload,
                        headers={"X-Tenant-ID": self._tenant_id},
                    )
                    if resp.status_code == 404:
                        # 云端尚未实现，丢弃结果
                        reported += 1
                        continue
                    resp.raise_for_status()
                    reported += 1
            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
                remaining.append(result)

        self._pending_results = remaining
        if reported:
            logger.info("remote_cmd_results_reported", count=reported)
        return reported

    # ── 后台轮询循环 ──

    async def run_poll_loop(self) -> None:
        """后台循环：轮询命令 -> 执行 -> 回报结果。"""
        self._running = True
        logger.info("remote_cmd_poll_loop_started", interval_s=_POLL_INTERVAL_S)

        while self._running:
            try:
                # 拉取命令
                commands = await self.poll_commands()
                for cmd in commands:
                    await self.execute_command(cmd)

                # 回报结果
                await self.report_results()

            except asyncio.CancelledError:
                self._running = False
                break

            await asyncio.sleep(_POLL_INTERVAL_S)

        logger.info("remote_cmd_poll_loop_stopped")

    def stop(self) -> None:
        """停止轮询循环。"""
        self._running = False

    # ── 内置命令处理器 ──

    async def _handle_restart_service(self, params: dict[str, Any]) -> dict[str, Any]:
        """重启指定服务。"""
        service_name = params.get("service_name", "mac-station")
        service_label = f"com.tunxiang.{service_name}"

        try:
            proc = await asyncio.create_subprocess_exec(
                "launchctl",
                "kickstart",
                "-k",
                f"system/{service_label}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            return {
                "service": service_name,
                "restarted": proc.returncode == 0,
                "returncode": proc.returncode,
            }
        except FileNotFoundError:
            return {"service": service_name, "restarted": False, "error": "launchctl not found"}
        except asyncio.TimeoutError:
            return {"service": service_name, "restarted": False, "error": "timeout"}

    async def _handle_clear_cache(self, params: dict[str, Any]) -> dict[str, Any]:
        """清除缓存。"""
        from services.offline_cache import get_offline_cache

        cache = get_offline_cache()
        cache_type = params.get("cache_type", "all")

        if cache_type in ("all", "read"):
            cleared = cache.cache_clear()
        else:
            cleared = 0

        return {"cache_type": cache_type, "cleared_entries": cleared}

    async def _handle_sync_now(self, params: dict[str, Any]) -> dict[str, Any]:
        """立即触发同步。"""
        from services.offline_cache import get_offline_cache
        from config import get_config

        cache = get_offline_cache()
        cfg = get_config()

        if cfg.offline:
            return {"triggered": False, "reason": "device_offline"}

        result = await cache.replay_queue(cfg.cloud_api_url, cfg.tenant_id)
        return {"triggered": True, "replay_result": result}

    async def _handle_collect_logs(self, params: dict[str, Any]) -> dict[str, Any]:
        """收集并上传日志到云端。"""
        import glob
        from pathlib import Path

        log_dir = params.get("log_dir", "/var/log/tunxiang")
        max_lines = params.get("max_lines", 1000)
        log_pattern = params.get("pattern", "*.log")

        collected: dict[str, list[str]] = {}
        log_path = Path(log_dir)

        if not log_path.exists():
            return {"collected": 0, "error": f"Log directory {log_dir} not found"}

        for log_file in sorted(log_path.glob(log_pattern)):
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                    collected[log_file.name] = lines[-max_lines:]
            except OSError as exc:
                collected[log_file.name] = [f"Error reading: {exc}"]

        # 上传到云端（如果可达）
        upload_success = False
        if self._device_id and collected:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        f"{self._cloud_api_url}/api/v1/devices/{self._device_id}/logs",
                        json={"logs": {k: v for k, v in collected.items()}},
                        headers={"X-Tenant-ID": self._tenant_id},
                    )
                    upload_success = resp.status_code < 400
            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
                pass

        return {
            "collected_files": len(collected),
            "total_lines": sum(len(v) for v in collected.values()),
            "uploaded": upload_success,
        }

    async def _handle_update_config(self, params: dict[str, Any]) -> dict[str, Any]:
        """更新配置。仅允许更新安全的配置项。"""
        from config import get_config

        cfg = get_config()
        updated_keys: list[str] = []

        # 安全配置白名单
        safe_keys = {
            "cloud_api_url": "cloud_api_url",
            "redis_url": "redis_url",
        }

        for key, attr_name in safe_keys.items():
            if key in params:
                setattr(cfg, attr_name, params[key])
                updated_keys.append(key)
                logger.info("config_updated_remotely", key=key)

        return {"updated_keys": updated_keys, "count": len(updated_keys)}

    async def _handle_health_check(self, params: dict[str, Any]) -> dict[str, Any]:
        """执行健康检查并返回结果。"""
        from config import get_config

        cfg = get_config()

        checks: dict[str, Any] = {
            "cloud_reachable": not cfg.offline,
            "store_id": cfg.store_id,
            "uptime_seconds": time.time() - cfg.boot_time,
        }

        # 检查本地 PG（如果可用）
        try:
            import asyncpg

            conn = await asyncio.wait_for(
                asyncpg.connect(cfg.local_db_url.replace("postgresql+asyncpg://", "postgresql://")),
                timeout=5,
            )
            await conn.execute("SELECT 1")
            await conn.close()
            checks["local_pg"] = "ok"
        except (ImportError, OSError, asyncio.TimeoutError):
            checks["local_pg"] = "unavailable"

        return checks


# ── 模块级单例 ──

_service: RemoteCommandService | None = None


def get_remote_command_service() -> RemoteCommandService:
    """获取远程命令服务单例（懒初始化）。"""
    global _service
    if _service is None:
        _service = RemoteCommandService()
    return _service
