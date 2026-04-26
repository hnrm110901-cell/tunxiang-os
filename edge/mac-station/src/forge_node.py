"""
ForgeNode — mac-station 离线感知决策引擎

从 SkillRegistry 读取 degradation.offline 配置，
动态决策每个 Skill 在离线状态下的行为。

核心逻辑：
1. 连接状态检测（ping 云端 API，30 秒间隔）
2. 按 SKILL.yaml degradation.offline.capabilities 决定操作是否可执行
3. 离线缓冲队列（SQLite WAL，联网后同步）
4. 冲突解决策略执行

SKILL.yaml 扫描路径（glob）：
    /Users/lichun/tunxiang-os/services/*/skills/*/SKILL.yaml
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

import httpx
import structlog
from offline_buffer import BufferedOperation, BufferStats, OfflineBuffer
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

# 云端健康检查地址（可通过环境变量覆盖）
_CLOUD_HEALTH_URL = os.getenv(
    "CLOUD_HEALTH_URL",
    "https://api.tunxiang.com/health",
)
# 连接检测间隔（秒）
_CHECK_INTERVAL = int(os.getenv("FORGE_CHECK_INTERVAL", "30"))
# 连接检测超时（秒）
_CHECK_TIMEOUT = float(os.getenv("FORGE_CHECK_TIMEOUT", "5"))
# SKILL.yaml 根目录（相对于 services/ 下各微服务的 skills/ 子目录）
_SKILLS_ROOT = os.getenv(
    "SKILLS_ROOT",
    "/Users/lichun/tunxiang-os/services",
)


# ─── Pydantic 模型 ────────────────────────────────────────────────────────────


class OfflineDecision(BaseModel):
    """ForgeNode 对某个 Skill+Action 组合的离线决策结果"""
    skill_name: str
    action: str
    can_execute: bool                   # True=可执行  False=拒绝
    mode: str                           # "full" / "limited" / "disabled" / "unknown"
    requires_buffer: bool               # True=需写离线缓冲，联网后同步
    local_storage: Optional[str] = None # "sqlite_wal" 等
    fallback_message: Optional[str] = None
    reason: str = ""                    # 决策原因（调试用）


class SkillOfflineStatus(BaseModel):
    """单个 Skill 的完整离线状态汇总"""
    skill_name: str
    display_name: str = ""
    can_operate: bool
    capabilities_count: int
    actions_available: list[str] = Field(default_factory=list)
    actions_disabled: list[str] = Field(default_factory=list)
    max_offline_hours: int = 4
    sync_strategy: Optional[str] = None
    fallback_message: Optional[str] = None


class ForgeStatus(BaseModel):
    """ForgeNode 整体状态"""
    is_online: bool
    last_check_at: Optional[str] = None
    cloud_url: str
    skills_loaded: int
    buffer_stats: Optional[BufferStats] = None


# ─── ForgeNode ────────────────────────────────────────────────────────────────


class ForgeNode:
    """
    mac-station 离线感知决策引擎。

    用法（在 FastAPI lifespan 中）：
        forge = ForgeNode()
        await forge.initialize()
        asyncio.create_task(forge.start_connectivity_check())
    """

    def __init__(
        self,
        skills_root: Optional[str] = None,
        cloud_health_url: Optional[str] = None,
        check_interval: int = _CHECK_INTERVAL,
        buffer: Optional[OfflineBuffer] = None,
    ) -> None:
        self._skills_root = skills_root or _SKILLS_ROOT
        self._cloud_health_url = cloud_health_url or _CLOUD_HEALTH_URL
        self._check_interval = check_interval
        self._buffer = buffer or OfflineBuffer()

        # 连接状态（初始假设在线，首次检测后更新）
        self._is_online: bool = True
        self._last_check_at: Optional[str] = None

        # Skill 配置缓存：skill_name -> degradation.offline 原始数据
        # 格式：{
        #   "wine-storage": {
        #     "can_operate": True,
        #     "capabilities": [{"action": "store", "mode": "full", ...}],
        #     "sync_strategy": {...},
        #     "display_name": "存酒管理",
        #     "fallback_message": "",
        #   }
        # }
        self._skill_offline_configs: dict[str, dict] = {}

    # ─── 初始化 ───────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """初始化：加载 Skill 配置 + 初始化离线缓冲"""
        await self._buffer.initialize()
        self._load_skill_configs()
        logger.info(
            "forge_node_initialized",
            skills_loaded=len(self._skill_offline_configs),
            skills_root=self._skills_root,
        )

    def _load_skill_configs(self) -> None:
        """
        扫描 services/*/skills/*/SKILL.yaml，提取 degradation.offline 配置。

        使用 pathlib.glob 避免依赖 shell，出错时单个文件跳过，不影响全局。
        """
        from pathlib import Path

        import yaml  # type: ignore[import-untyped]

        root = Path(self._skills_root)
        if not root.exists():
            logger.warning("forge_node_skills_root_not_found", path=str(root))
            return

        loaded = 0
        failed = 0
        for yaml_path in root.glob("*/skills/*/SKILL.yaml"):
            try:
                with yaml_path.open("r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)

                if not isinstance(data, dict):
                    continue

                skill_name = (data.get("meta") or {}).get("name", "")
                display_name = (data.get("meta") or {}).get("display_name", "")
                if not skill_name:
                    skill_name = yaml_path.parent.name  # 降级用目录名

                degradation = data.get("degradation") or {}
                offline_cfg = degradation.get("offline") or {}

                self._skill_offline_configs[skill_name] = {
                    "can_operate": bool(offline_cfg.get("can_operate", False)),
                    "capabilities": offline_cfg.get("capabilities") or [],
                    "sync_strategy": offline_cfg.get("sync_strategy") or {},
                    "fallback_message": offline_cfg.get("fallback_message", ""),
                    "display_name": display_name,
                }
                loaded += 1

            except (OSError, yaml.YAMLError, KeyError, TypeError) as exc:
                logger.warning(
                    "forge_node_skill_load_failed",
                    path=str(yaml_path),
                    error=str(exc),
                )
                failed += 1

        logger.info(
            "forge_node_skills_scanned",
            loaded=loaded,
            failed=failed,
            root=str(root),
        )

    def reload_skills(self) -> int:
        """热重载所有 Skill 配置，返回加载成功数量"""
        self._skill_offline_configs.clear()
        self._load_skill_configs()
        return len(self._skill_offline_configs)

    # ─── 连接状态检测 ─────────────────────────────────────────────────────────

    async def check_online_status(self) -> bool:
        """
        非阻塞 ping 云端 API，更新 self._is_online。

        超时 / 连接错误 = 离线；其他 HTTP 错误也视为在线（云端可达）。

        Returns:
            bool: 当前是否在线
        """
        from datetime import datetime, timezone

        previous = self._is_online
        try:
            async with httpx.AsyncClient(timeout=_CHECK_TIMEOUT) as client:
                resp = await client.get(self._cloud_health_url)
                self._is_online = resp.status_code < 500
        except httpx.TimeoutException:
            self._is_online = False
        except httpx.ConnectError:
            self._is_online = False
        except httpx.RequestError as exc:
            logger.warning("forge_node_connectivity_check_error", error=str(exc))
            self._is_online = False

        self._last_check_at = datetime.now(timezone.utc).isoformat()

        if previous != self._is_online:
            if self._is_online:
                logger.info("forge_node_back_online", url=self._cloud_health_url)
                # 恢复在线后触发同步
                asyncio.create_task(self.sync_on_reconnect())
            else:
                logger.warning("forge_node_went_offline", url=self._cloud_health_url)

        return self._is_online

    async def start_connectivity_check(self) -> None:
        """
        后台持续运行的连接状态检测循环（每 _check_interval 秒一次）。

        在 FastAPI lifespan 中用 asyncio.create_task() 启动。
        """
        logger.info(
            "forge_node_connectivity_check_started",
            interval_seconds=self._check_interval,
        )
        while True:
            await self.check_online_status()
            await asyncio.sleep(self._check_interval)

    @property
    def is_online(self) -> bool:
        """当前连接状态（上次检测结果）"""
        return self._is_online

    # ─── 核心决策 ─────────────────────────────────────────────────────────────

    def can_execute(self, skill_name: str, action: str) -> OfflineDecision:
        """
        决定某个 Skill+Action 在当前状态下是否可执行。

        决策流程：
        1. 在线 → 直接放行（mode="full"，无需缓冲）
        2. 离线 + Skill 无配置 → 保守拒绝
        3. 离线 + can_operate=False → 拒绝，返回 fallback_message
        4. 离线 + can_operate=True → 查找 capabilities 匹配 action
           4a. 找到 + mode="full"/"limited" → 允许，requires_buffer 根据 local_storage 判断
           4b. 找到 + mode="disabled" → 拒绝，返回 fallback_message
           4c. 未找到 → 保守拒绝

        Args:
            skill_name: Skill 名称（与 SKILL.yaml meta.name 对应）
            action: 操作名称（与 capabilities[].action 对应）

        Returns:
            OfflineDecision
        """
        # 在线时直接放行
        if self._is_online:
            return OfflineDecision(
                skill_name=skill_name,
                action=action,
                can_execute=True,
                mode="full",
                requires_buffer=False,
                reason="online",
            )

        # 离线时查找 Skill 配置
        cfg = self._skill_offline_configs.get(skill_name)
        if cfg is None:
            return OfflineDecision(
                skill_name=skill_name,
                action=action,
                can_execute=False,
                mode="disabled",
                requires_buffer=False,
                fallback_message=f"Skill '{skill_name}' 无离线配置，请联网后操作",
                reason="no_skill_config",
            )

        # Skill 整体不支持离线
        if not cfg["can_operate"]:
            fallback = cfg.get("fallback_message") or f"'{skill_name}' 需要联网才能操作"
            return OfflineDecision(
                skill_name=skill_name,
                action=action,
                can_execute=False,
                mode="disabled",
                requires_buffer=False,
                fallback_message=fallback,
                reason="skill_offline_disabled",
            )

        # 查找匹配的 capability
        capabilities: list[dict] = cfg.get("capabilities") or []
        matched: Optional[dict] = None
        for cap in capabilities:
            if cap.get("action") == action:
                matched = cap
                break

        if matched is None:
            return OfflineDecision(
                skill_name=skill_name,
                action=action,
                can_execute=False,
                mode="disabled",
                requires_buffer=False,
                fallback_message=f"操作 '{action}' 在离线模式下不可用",
                reason="action_not_in_capabilities",
            )

        mode = matched.get("mode", "disabled")
        local_storage = matched.get("local_storage") or None
        fallback_message = matched.get("fallback_message") or matched.get("note") or None

        if mode == "disabled":
            return OfflineDecision(
                skill_name=skill_name,
                action=action,
                can_execute=False,
                mode="disabled",
                requires_buffer=False,
                local_storage=local_storage,
                fallback_message=fallback_message or f"'{action}' 在离线模式下已禁用",
                reason="capability_mode_disabled",
            )

        # mode == "full" or "limited"
        requires_buffer = bool(local_storage)  # 有本地存储配置就需要缓冲

        return OfflineDecision(
            skill_name=skill_name,
            action=action,
            can_execute=True,
            mode=mode,
            requires_buffer=requires_buffer,
            local_storage=local_storage,
            fallback_message=fallback_message,
            reason=f"capability_matched_mode_{mode}",
        )

    # ─── 离线缓冲操作 ─────────────────────────────────────────────────────────

    async def buffer_operation(
        self,
        skill_name: str,
        action: str,
        payload: dict,
        tenant_id: str,
    ) -> str:
        """
        将操作写入 SQLite WAL 离线缓冲队列。

        联网后由 sync_on_reconnect() 批量推送到云端。

        Args:
            skill_name: Skill 名称
            action: 操作名称
            payload: 操作数据（金额字段必须以 _fen 结尾，单位：分）
            tenant_id: 租户 ID（RLS 隔离）

        Returns:
            buffer_id: UUID 字符串，可用于查询同步状态
        """
        buffer_id = await self._buffer.write(
            skill_name=skill_name,
            action=action,
            payload=payload,
            tenant_id=tenant_id,
        )
        logger.info(
            "forge_node_operation_buffered",
            buffer_id=buffer_id,
            skill_name=skill_name,
            action=action,
            tenant_id=tenant_id,
        )
        return buffer_id

    # ─── 联网同步 ─────────────────────────────────────────────────────────────

    async def sync_on_reconnect(self) -> dict:
        """
        联网后按 sync_strategy 推送缓冲操作到云端。

        同步策略：push_local_then_pull_remote（先推本地，再拉云端）
        冲突解决：各 Skill 的 sync_strategy.conflict_resolution 字段定义

        Returns:
            {"synced": int, "failed": int, "skipped": int}
        """
        logger.info("forge_node_sync_started")
        synced = 0
        failed = 0

        pending = await self._buffer.get_pending(limit=500)
        if not pending:
            logger.info("forge_node_sync_nothing_to_sync")
            return {"synced": 0, "failed": 0, "skipped": 0}

        # 按 Skill 分组，便于后续按 sync_strategy 处理
        skill_groups: dict[str, list[BufferedOperation]] = {}
        for op in pending:
            skill_groups.setdefault(op.skill_name, []).append(op)

        cloud_base_url = os.getenv("CLOUD_API_URL", "https://api.tunxiang.com")

        for skill_name, ops in skill_groups.items():
            ids = [op.id for op in ops]
            await self._buffer.mark_syncing(ids)

            cfg = self._skill_offline_configs.get(skill_name, {})
            sync_strategy = cfg.get("sync_strategy") or {}
            on_reconnect = sync_strategy.get("on_reconnect", "push_local_then_pull_remote")

            if on_reconnect != "push_local_then_pull_remote":
                logger.warning(
                    "forge_node_sync_strategy_unsupported",
                    skill_name=skill_name,
                    strategy=on_reconnect,
                )

            # 逐条推送（后续可优化为批量）
            success_ids: list[str] = []
            fail_ids: list[str] = []

            for op in ops:
                try:
                    await self._push_operation_to_cloud(cloud_base_url, op)
                    success_ids.append(op.id)
                    synced += 1
                except (httpx.HTTPStatusError, httpx.RequestError, ValueError) as exc:
                    logger.error(
                        "forge_node_sync_operation_failed",
                        buffer_id=op.id,
                        skill_name=op.skill_name,
                        action=op.action,
                        error=str(exc),
                    )
                    fail_ids.append(op.id)
                    failed += 1

            if success_ids:
                await self._buffer.mark_synced(success_ids)
            if fail_ids:
                await self._buffer.mark_failed(fail_ids, "cloud_push_failed")

        logger.info(
            "forge_node_sync_completed",
            synced=synced,
            failed=failed,
        )
        return {"synced": synced, "failed": failed, "skipped": 0}

    async def _push_operation_to_cloud(
        self,
        cloud_base_url: str,
        op: BufferedOperation,
    ) -> None:
        """
        将单条缓冲操作推送到云端 API。

        端点规则：POST {cloud_base_url}/api/v1/{skill_name}/{action}
        附带 X-Buffer-ID 和 X-Tenant-ID 头，云端幂等处理。
        """
        url = f"{cloud_base_url}/api/v1/{op.skill_name}/{op.action}"
        headers = {
            "X-Buffer-ID": op.id,
            "X-Tenant-ID": op.tenant_id,
            "X-Source": "mac-station-offline-buffer",
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=op.payload, headers=headers)
            resp.raise_for_status()

    # ─── 状态汇总 ─────────────────────────────────────────────────────────────

    def get_all_skill_status(self) -> list[SkillOfflineStatus]:
        """
        返回所有已加载 Skill 的离线状态汇总。

        Returns:
            SkillOfflineStatus 列表（按 skill_name 排序）
        """
        result: list[SkillOfflineStatus] = []
        for skill_name, cfg in sorted(self._skill_offline_configs.items()):
            capabilities: list[dict] = cfg.get("capabilities") or []
            sync_strategy: dict = cfg.get("sync_strategy") or {}

            actions_available = [
                cap["action"]
                for cap in capabilities
                if cap.get("mode") in ("full", "limited")
            ]
            actions_disabled = [
                cap["action"]
                for cap in capabilities
                if cap.get("mode") == "disabled"
            ]

            result.append(
                SkillOfflineStatus(
                    skill_name=skill_name,
                    display_name=cfg.get("display_name", ""),
                    can_operate=cfg.get("can_operate", False),
                    capabilities_count=len(capabilities),
                    actions_available=actions_available,
                    actions_disabled=actions_disabled,
                    max_offline_hours=sync_strategy.get("max_offline_hours", 4),
                    sync_strategy=sync_strategy.get("on_reconnect"),
                    fallback_message=cfg.get("fallback_message") or None,
                )
            )
        return result

    async def get_status(self) -> ForgeStatus:
        """返回 ForgeNode 整体状态（含缓冲统计）"""
        buffer_stats = await self._buffer.get_stats()
        return ForgeStatus(
            is_online=self._is_online,
            last_check_at=self._last_check_at,
            cloud_url=self._cloud_health_url,
            skills_loaded=len(self._skill_offline_configs),
            buffer_stats=buffer_stats,
        )
