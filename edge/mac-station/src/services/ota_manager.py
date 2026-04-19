"""OTA 更新管理器 — 检查 / 下载 / 校验 / 应用 / 回滚

职责：
1. 检查更新（对比本地版本 vs 云端最新版本）
2. 下载更新包（支持断点续传）
3. 验证完整性（SHA256 校验）
4. 应用更新（备份当前版本 -> 解压新版本 -> 重启服务）
5. 回滚机制（更新失败自动回滚到备份）
6. 更新日志记录

Mock 模式：无可用更新时返回空结果，不会触发实际文件操作。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

# ── 常量 ──
_CLOUD_TIMEOUT_S = 10
_DOWNLOAD_CHUNK_SIZE = 1024 * 256  # 256KB
_CHECK_INTERVAL_S = 3600  # 默认1小时检查一次


class OTAState(str, Enum):
    """OTA 更新状态机。"""

    IDLE = "idle"
    CHECKING = "checking"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    BACKING_UP = "backing_up"
    APPLYING = "applying"
    RESTARTING = "restarting"
    ROLLING_BACK = "rolling_back"
    FAILED = "failed"
    SUCCESS = "success"


@dataclass
class OTAUpdateInfo:
    """一次更新的完整信息。"""

    version_name: str = ""
    version_code: int = 0
    download_url: str = ""
    file_sha256: str = ""
    release_notes: str = ""
    is_forced: bool = False
    file_size_bytes: int = 0


@dataclass
class OTAHistoryEntry:
    """更新历史记录条目。"""

    version_name: str
    version_code: int
    state: str
    started_at: float
    finished_at: float = 0.0
    success: bool = False
    error: str = ""
    rolled_back: bool = False


class OTAManager:
    """OTA 更新管理器。

    管理完整的更新生命周期：检查 -> 下载 -> 校验 -> 备份 -> 应用 -> 重启。
    失败时自动回滚到备份版本。

    Attributes:
        _cloud_api_url: 云端 API 网关地址
        _current_version: 当前本地版本号
        _current_version_code: 当前版本数字编号
        _install_dir: 应用安装目录
        _backup_dir: 备份目录
        _download_dir: 下载临时目录
        _state: 当前 OTA 状态
        _progress: 下载进度 0.0-1.0
        _history: 更新历史
    """

    def __init__(
        self,
        cloud_api_url: str | None = None,
        current_version: str | None = None,
        current_version_code: int | None = None,
        install_dir: str | None = None,
    ) -> None:
        self._cloud_api_url = cloud_api_url or os.getenv("CLOUD_API_URL", "http://localhost:8000")
        self._current_version = current_version or os.getenv("APP_VERSION", "0.0.0")
        self._current_version_code = current_version_code or int(os.getenv("APP_VERSION_CODE", "0"))
        self._tenant_id = os.getenv("TENANT_ID", "default_tenant")
        self._device_type = os.getenv("DEVICE_TYPE", "mac_mini")

        base = install_dir or os.getenv("APP_INSTALL_DIR", "/opt/tunxiang")
        self._install_dir = Path(base)
        self._backup_dir = Path(base) / "_backup"
        self._download_dir = Path(base) / "_downloads"

        self._state: OTAState = OTAState.IDLE
        self._progress: float = 0.0
        self._current_update: OTAUpdateInfo | None = None
        self._history: list[OTAHistoryEntry] = []
        self._last_check_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> OTAState:
        return self._state

    @property
    def progress(self) -> float:
        return self._progress

    @property
    def current_version(self) -> str:
        return self._current_version

    @property
    def current_version_code(self) -> int:
        return self._current_version_code

    def get_status(self) -> dict[str, Any]:
        """返回当前 OTA 状态摘要。"""
        return {
            "state": self._state.value,
            "progress": round(self._progress, 2),
            "current_version": self._current_version,
            "current_version_code": self._current_version_code,
            "last_check_at": self._last_check_at,
            "pending_update": {
                "version_name": self._current_update.version_name,
                "version_code": self._current_update.version_code,
                "is_forced": self._current_update.is_forced,
            }
            if self._current_update
            else None,
        }

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """返回更新历史。"""
        entries = self._history[-limit:]
        return [
            {
                "version_name": e.version_name,
                "version_code": e.version_code,
                "state": e.state,
                "started_at": e.started_at,
                "finished_at": e.finished_at,
                "success": e.success,
                "error": e.error,
                "rolled_back": e.rolled_back,
            }
            for e in reversed(entries)
        ]

    # ── 检查更新 ──

    async def check_update(self) -> OTAUpdateInfo | None:
        """向云端查询是否有可用更新。

        Returns:
            有更新时返回 OTAUpdateInfo，无更新返回 None。
        """
        self._state = OTAState.CHECKING
        self._last_check_at = time.time()

        try:
            async with httpx.AsyncClient(timeout=_CLOUD_TIMEOUT_S) as client:
                resp = await client.get(
                    f"{self._cloud_api_url}/api/v1/org/ota/versions/latest",
                    params={
                        "device_type": self._device_type,
                        "current_version_code": self._current_version_code,
                    },
                    headers={"X-Tenant-ID": self._tenant_id},
                )
                resp.raise_for_status()
                body = resp.json()

            data = body.get("data")
            if not data or not data.get("has_update"):
                self._state = OTAState.IDLE
                logger.info("ota_no_update_available", current=self._current_version)
                return None

            latest_code = data.get("version_code", 0)
            if latest_code <= self._current_version_code:
                self._state = OTAState.IDLE
                return None

            update = OTAUpdateInfo(
                version_name=data.get("version_name", ""),
                version_code=latest_code,
                download_url=data.get("download_url", ""),
                file_sha256=data.get("file_sha256", ""),
                release_notes=data.get("release_notes", ""),
                is_forced=data.get("is_forced", False),
                file_size_bytes=data.get("file_size_bytes", 0),
            )

            self._current_update = update
            self._state = OTAState.IDLE

            logger.info(
                "ota_update_available",
                current=self._current_version,
                latest=update.version_name,
                latest_code=update.version_code,
                forced=update.is_forced,
            )
            return update

        except httpx.TimeoutException:
            self._state = OTAState.IDLE
            logger.warning("ota_check_timeout")
            return None
        except httpx.ConnectError:
            self._state = OTAState.IDLE
            logger.warning("ota_check_connect_error")
            return None
        except httpx.HTTPStatusError as exc:
            self._state = OTAState.IDLE
            logger.warning("ota_check_http_error", status=exc.response.status_code)
            return None

    # ── 下载更新包（断点续传） ──

    async def download_update(self, update: OTAUpdateInfo) -> Path | None:
        """下载更新包，支持断点续传。

        Args:
            update: 要下载的更新信息

        Returns:
            下载成功返回本地文件路径，失败返回 None。
        """
        if not update.download_url:
            logger.error("ota_download_no_url")
            return None

        self._state = OTAState.DOWNLOADING
        self._progress = 0.0

        self._download_dir.mkdir(parents=True, exist_ok=True)
        filename = f"update_{update.version_code}.tar.gz"
        target_path = self._download_dir / filename
        temp_path = self._download_dir / f"{filename}.part"

        # 断点续传：检查已下载的部分
        downloaded_bytes = 0
        if temp_path.exists():
            downloaded_bytes = temp_path.stat().st_size
            logger.info("ota_download_resuming", downloaded=downloaded_bytes)

        headers: dict[str, str] = {}
        if downloaded_bytes > 0:
            headers["Range"] = f"bytes={downloaded_bytes}-"

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", update.download_url, headers=headers) as resp:
                    if resp.status_code == 416:
                        # Range Not Satisfiable - 文件已完整下载
                        if temp_path.exists():
                            temp_path.rename(target_path)
                            self._progress = 1.0
                            self._state = OTAState.IDLE
                            return target_path

                    resp.raise_for_status()

                    total_size = update.file_size_bytes or 0
                    content_length = resp.headers.get("content-length")
                    if content_length:
                        total_size = downloaded_bytes + int(content_length)

                    mode = "ab" if downloaded_bytes > 0 else "wb"
                    with open(temp_path, mode) as f:
                        async for chunk in resp.aiter_bytes(chunk_size=_DOWNLOAD_CHUNK_SIZE):
                            f.write(chunk)
                            downloaded_bytes += len(chunk)
                            if total_size > 0:
                                self._progress = downloaded_bytes / total_size

            # 下载完成，重命名
            temp_path.rename(target_path)
            self._progress = 1.0

            logger.info(
                "ota_download_complete",
                version=update.version_name,
                size_bytes=downloaded_bytes,
                path=str(target_path),
            )
            return target_path

        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.warning(
                "ota_download_failed",
                error=str(exc),
                downloaded=downloaded_bytes,
            )
            self._state = OTAState.FAILED
            return None
        except httpx.HTTPStatusError as exc:
            logger.error(
                "ota_download_http_error",
                status=exc.response.status_code,
            )
            self._state = OTAState.FAILED
            return None
        except OSError as exc:
            logger.error("ota_download_io_error", error=str(exc))
            self._state = OTAState.FAILED
            return None

    # ── SHA256 校验 ──

    def verify_checksum(self, file_path: Path, expected_sha256: str) -> bool:
        """校验下载文件的 SHA256 哈希值。

        Args:
            file_path: 待校验文件路径
            expected_sha256: 预期的 SHA256 hex 字符串

        Returns:
            校验通过返回 True。
        """
        if not expected_sha256:
            logger.warning("ota_verify_no_checksum_provided")
            return True  # 无校验值时跳过

        self._state = OTAState.VERIFYING

        sha256 = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(_DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    sha256.update(chunk)
        except OSError as exc:
            logger.error("ota_verify_read_error", error=str(exc))
            self._state = OTAState.FAILED
            return False

        actual = sha256.hexdigest()
        matched = actual.lower() == expected_sha256.lower()

        if matched:
            logger.info("ota_verify_ok", sha256=actual[:16] + "...")
        else:
            logger.error(
                "ota_verify_mismatch",
                expected=expected_sha256[:16] + "...",
                actual=actual[:16] + "...",
            )
            self._state = OTAState.FAILED

        return matched

    # ── 备份当前版本 ──

    def _backup_current(self) -> bool:
        """备份当前安装目录。

        Returns:
            备份成功返回 True。
        """
        self._state = OTAState.BACKING_UP

        if not self._install_dir.exists():
            logger.info("ota_backup_skip_no_install_dir")
            return True

        try:
            if self._backup_dir.exists():
                shutil.rmtree(self._backup_dir)
            shutil.copytree(
                self._install_dir,
                self._backup_dir,
                ignore=shutil.ignore_patterns("_backup", "_downloads"),
            )
            logger.info(
                "ota_backup_complete",
                source=str(self._install_dir),
                backup=str(self._backup_dir),
            )
            return True
        except OSError as exc:
            logger.error("ota_backup_failed", error=str(exc))
            self._state = OTAState.FAILED
            return False

    # ── 应用更新 ──

    async def _apply_update(self, package_path: Path) -> bool:
        """解压更新包到安装目录。

        Args:
            package_path: 更新包本地路径（tar.gz）

        Returns:
            应用成功返回 True。
        """
        self._state = OTAState.APPLYING

        try:
            import tarfile

            with tarfile.open(package_path, "r:gz") as tar:
                # 安全检查：防止路径遍历
                for member in tar.getmembers():
                    member_path = Path(self._install_dir / member.name).resolve()
                    if not str(member_path).startswith(str(self._install_dir.resolve())):
                        logger.error(
                            "ota_apply_path_traversal_blocked",
                            member=member.name,
                        )
                        self._state = OTAState.FAILED
                        return False

                tar.extractall(path=self._install_dir, filter="data")

            logger.info(
                "ota_apply_complete",
                package=str(package_path),
                install_dir=str(self._install_dir),
            )
            return True

        except tarfile.TarError as exc:
            logger.error("ota_apply_tar_error", error=str(exc))
            self._state = OTAState.FAILED
            return False
        except OSError as exc:
            logger.error("ota_apply_io_error", error=str(exc))
            self._state = OTAState.FAILED
            return False

    # ── 回滚 ──

    def rollback(self) -> bool:
        """回滚到备份版本。

        Returns:
            回滚成功返回 True。
        """
        self._state = OTAState.ROLLING_BACK

        if not self._backup_dir.exists():
            logger.error("ota_rollback_no_backup")
            self._state = OTAState.FAILED
            return False

        try:
            # 删除当前（损坏的）安装
            if self._install_dir.exists():
                # 保留 _backup 和 _downloads
                for item in self._install_dir.iterdir():
                    if item.name in ("_backup", "_downloads"):
                        continue
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()

            # 从备份恢复
            for item in self._backup_dir.iterdir():
                dest = self._install_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

            logger.info("ota_rollback_complete")
            self._state = OTAState.IDLE
            return True

        except OSError as exc:
            logger.error("ota_rollback_failed", error=str(exc))
            self._state = OTAState.FAILED
            return False

    # ── 重启服务 ──

    async def _restart_service(self) -> bool:
        """重启 mac-station 服务。

        通过 launchctl 重启 launchd 管理的服务。
        """
        self._state = OTAState.RESTARTING

        service_label = os.getenv("LAUNCHD_SERVICE_LABEL", "com.tunxiang.mac-station")

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

            if proc.returncode == 0:
                logger.info("ota_restart_triggered", service=service_label)
                return True

            logger.warning(
                "ota_restart_launchctl_failed",
                returncode=proc.returncode,
                stderr=stderr.decode("utf-8", errors="replace")[:500],
            )
            return False

        except FileNotFoundError:
            logger.warning("ota_restart_launchctl_not_found")
            return False
        except asyncio.TimeoutError:
            logger.error("ota_restart_timeout")
            return False

    # ── 完整更新流程 ──

    async def perform_update(self, update: OTAUpdateInfo | None = None) -> dict[str, Any]:
        """执行完整的 OTA 更新流程。

        流程：检查 -> 下载 -> 校验 -> 备份 -> 应用 -> 重启
        任一步骤失败时自动回滚。

        Args:
            update: 更新信息。为 None 时先检查更新。

        Returns:
            更新结果字典。
        """
        async with self._lock:
            history_entry = OTAHistoryEntry(
                version_name="",
                version_code=0,
                state="started",
                started_at=time.time(),
            )

            try:
                # 1. 检查更新
                if update is None:
                    update = await self.check_update()
                    if update is None:
                        return {"ok": True, "action": "no_update"}

                history_entry.version_name = update.version_name
                history_entry.version_code = update.version_code

                # 2. 下载
                package_path = await self.download_update(update)
                if package_path is None:
                    history_entry.state = "download_failed"
                    history_entry.error = "Download failed"
                    history_entry.finished_at = time.time()
                    self._history.append(history_entry)
                    return {"ok": False, "error": "download_failed"}

                # 3. 校验
                if not self.verify_checksum(package_path, update.file_sha256):
                    history_entry.state = "verify_failed"
                    history_entry.error = "Checksum mismatch"
                    history_entry.finished_at = time.time()
                    self._history.append(history_entry)
                    # 删除损坏的下载文件
                    try:
                        package_path.unlink()
                    except OSError:
                        pass
                    return {"ok": False, "error": "checksum_mismatch"}

                # 4. 备份
                if not self._backup_current():
                    history_entry.state = "backup_failed"
                    history_entry.error = "Backup failed"
                    history_entry.finished_at = time.time()
                    self._history.append(history_entry)
                    return {"ok": False, "error": "backup_failed"}

                # 5. 应用
                if not await self._apply_update(package_path):
                    # 回滚
                    self.rollback()
                    history_entry.state = "apply_failed"
                    history_entry.error = "Apply failed, rolled back"
                    history_entry.rolled_back = True
                    history_entry.finished_at = time.time()
                    self._history.append(history_entry)
                    return {"ok": False, "error": "apply_failed_rolled_back"}

                # 6. 更新版本号
                self._current_version = update.version_name
                self._current_version_code = update.version_code
                self._state = OTAState.SUCCESS

                history_entry.state = "success"
                history_entry.success = True
                history_entry.finished_at = time.time()
                self._history.append(history_entry)

                # 清理下载文件
                try:
                    package_path.unlink()
                except OSError:
                    pass

                logger.info(
                    "ota_update_success",
                    version=update.version_name,
                    version_code=update.version_code,
                )

                # 7. 重启（异步，不阻塞响应）
                asyncio.create_task(self._restart_service())

                return {
                    "ok": True,
                    "action": "updated",
                    "version": update.version_name,
                    "version_code": update.version_code,
                }

            except asyncio.CancelledError:
                history_entry.state = "cancelled"
                history_entry.error = "Update cancelled"
                history_entry.finished_at = time.time()
                self._history.append(history_entry)
                self._state = OTAState.IDLE
                raise

    # ── 定时检查循环 ──

    async def run_check_loop(self, interval_s: int = _CHECK_INTERVAL_S) -> None:
        """后台定期检查更新。仅检查不自动安装（除非 is_forced=True）。"""
        while True:
            await asyncio.sleep(interval_s)
            try:
                update = await self.check_update()
                if update and update.is_forced:
                    logger.info(
                        "ota_forced_update_detected",
                        version=update.version_name,
                    )
                    await self.perform_update(update)
            except asyncio.CancelledError:
                break


# ── 模块级单例 ──

_manager: OTAManager | None = None


def get_ota_manager() -> OTAManager:
    """获取 OTA 管理器单例（懒初始化）。"""
    global _manager
    if _manager is None:
        _manager = OTAManager()
    return _manager
