"""渠道菜单独立管控服务

职责：
- 管理平台SKU ⇄ 内部菜品持久化映射
- 按名称相似度自动匹配建议（编辑距离）
- 发布渠道菜单版本（快照 + 回滚支持）
- 查询各渠道菜品价格与可用性差异

所有金额单位：分（int）。
"""

from __future__ import annotations

import uuid
from typing import Optional

import structlog
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


# ─── Pydantic 数据模型 ───────────────────────────────────────────────────────


class PlatformDishMapping(BaseModel):
    id: uuid.UUID
    platform: str
    platform_item_id: str
    platform_item_name: Optional[str]
    dish_id: Optional[uuid.UUID]
    dish_name: Optional[str]
    platform_price_fen: Optional[int]
    platform_sku_name: Optional[str]
    is_mapped: bool
    is_active: bool


class MappingSuggestion(BaseModel):
    platform_item_id: str
    platform_item_name: str
    dish_id: uuid.UUID
    dish_name: str
    confidence: float  # 0.0 ~ 1.0
    reason: str  # "exact_match" / "edit_distance:2" / ...


class AutoMatchResult(BaseModel):
    suggested: list[MappingSuggestion]
    unmatched_count: int


class DishOverride(BaseModel):
    dish_id: uuid.UUID
    channel_price_fen: Optional[int] = None
    is_available: bool = True
    channel_name: Optional[str] = None


class ChannelMenuVersion(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    channel_id: str
    version_no: int
    dish_overrides: list[DishOverride]
    published_at: Optional[str]
    published_by: Optional[uuid.UUID]
    status: str


class DishChannelRow(BaseModel):
    dish_id: uuid.UUID
    dish_name: str
    prices_by_channel: dict[str, Optional[int]]  # channel_id → price_fen
    availability_by_channel: dict[str, bool]  # channel_id → is_available


class ChannelDiff(BaseModel):
    channels: list[str]
    dishes: list[DishChannelRow]


# ─── 编辑距离工具 ────────────────────────────────────────────────────────────


def _levenshtein(a: str, b: str) -> int:
    """计算两个字符串的 Levenshtein 编辑距离"""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * lb
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[lb]


def _name_confidence(a: str, b: str) -> float:
    """基于编辑距离计算名称相似度置信度（0.0~1.0）"""
    a, b = a.strip().lower(), b.strip().lower()
    if a == b:
        return 1.0
    max_len = max(len(a), len(b), 1)
    dist = _levenshtein(a, b)
    return max(0.0, 1.0 - dist / max_len)


# ─── 主服务类 ────────────────────────────────────────────────────────────────


class ChannelMappingService:
    """渠道菜单独立管控服务"""

    # 自动匹配置信度阈值（低于此值不建议）
    AUTO_MATCH_MIN_CONFIDENCE = 0.60

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._tenant_uuid = uuid.UUID(tenant_id)

    async def _set_rls(self) -> None:
        """设置 RLS tenant context"""
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ── 映射查询 ─────────────────────────────────────────────────────────────

    async def get_mappings(
        self,
        store_id: str,
        platform: str,
        unmapped_only: bool = False,
    ) -> list[PlatformDishMapping]:
        """获取平台映射列表。unmapped_only=True 只返回未映射的条目。"""
        await self._set_rls()
        sid = uuid.UUID(store_id)

        where_extra = "AND m.dish_id IS NULL" if unmapped_only else ""
        result = await self.db.execute(
            text(f"""
                SELECT
                    m.id,
                    m.platform,
                    m.platform_item_id,
                    m.platform_item_name,
                    m.dish_id,
                    d.dish_name,
                    m.platform_price_fen,
                    m.platform_sku_name,
                    m.is_active
                FROM platform_dish_mappings m
                LEFT JOIN dishes d ON d.id = m.dish_id
                WHERE m.tenant_id = :tid
                  AND m.store_id  = :sid
                  AND m.platform  = :platform
                  {where_extra}
                ORDER BY m.is_active DESC, m.created_at DESC
            """),
            {"tid": self._tenant_uuid, "sid": sid, "platform": platform},
        )
        rows = result.fetchall()
        return [
            PlatformDishMapping(
                id=r[0],
                platform=r[1],
                platform_item_id=r[2],
                platform_item_name=r[3],
                dish_id=r[4],
                dish_name=r[5],
                platform_price_fen=r[6],
                platform_sku_name=r[7],
                is_mapped=r[4] is not None,
                is_active=r[8],
            )
            for r in rows
        ]

    # ── 创建/更新映射 ─────────────────────────────────────────────────────────

    async def upsert_mapping(
        self,
        store_id: str,
        platform: str,
        platform_item_id: str,
        dish_id: Optional[str],
        platform_price_fen: Optional[int] = None,
        platform_item_name: Optional[str] = None,
        platform_sku_name: Optional[str] = None,
        is_active: bool = True,
    ) -> PlatformDishMapping:
        """创建或更新平台菜品映射（以 tenant+store+platform+platform_item_id 为唯一键）。"""
        await self._set_rls()
        sid = uuid.UUID(store_id)
        did = uuid.UUID(dish_id) if dish_id else None

        result = await self.db.execute(
            text("""
                INSERT INTO platform_dish_mappings
                    (tenant_id, store_id, platform, platform_item_id,
                     platform_item_name, dish_id, platform_price_fen,
                     platform_sku_name, is_active, updated_at)
                VALUES
                    (:tid, :sid, :platform, :platform_item_id,
                     :platform_item_name, :dish_id, :platform_price_fen,
                     :platform_sku_name, :is_active, NOW())
                ON CONFLICT (tenant_id, store_id, platform, platform_item_id)
                DO UPDATE SET
                    dish_id            = EXCLUDED.dish_id,
                    platform_price_fen = EXCLUDED.platform_price_fen,
                    platform_item_name = COALESCE(EXCLUDED.platform_item_name, platform_dish_mappings.platform_item_name),
                    platform_sku_name  = COALESCE(EXCLUDED.platform_sku_name, platform_dish_mappings.platform_sku_name),
                    is_active          = EXCLUDED.is_active,
                    updated_at         = NOW()
                RETURNING
                    id, platform, platform_item_id, platform_item_name,
                    dish_id, platform_price_fen, platform_sku_name, is_active
            """),
            {
                "tid": self._tenant_uuid,
                "sid": sid,
                "platform": platform,
                "platform_item_id": platform_item_id,
                "platform_item_name": platform_item_name,
                "dish_id": did,
                "platform_price_fen": platform_price_fen,
                "platform_sku_name": platform_sku_name,
                "is_active": is_active,
            },
        )
        row = result.fetchone()

        # 获取菜品名称（如果有 dish_id）
        dish_name: Optional[str] = None
        if row[4]:
            d_result = await self.db.execute(
                text("SELECT dish_name FROM dishes WHERE id = :did"),
                {"did": row[4]},
            )
            d_row = d_result.fetchone()
            if d_row:
                dish_name = d_row[0]

        log.info(
            "channel_mapping.upsert",
            platform=platform,
            platform_item_id=platform_item_id,
            dish_id=str(did) if did else None,
        )
        return PlatformDishMapping(
            id=row[0],
            platform=row[1],
            platform_item_id=row[2],
            platform_item_name=row[3],
            dish_id=row[4],
            dish_name=dish_name,
            platform_price_fen=row[5],
            platform_sku_name=row[6],
            is_mapped=row[4] is not None,
            is_active=row[7],
        )

    # ── 按名称自动匹配 ────────────────────────────────────────────────────────

    async def auto_match_by_name(
        self,
        store_id: str,
        platform: str,
    ) -> AutoMatchResult:
        """按名称相似度自动匹配未映射的平台SKU与内部菜品。

        策略：
        1. 精确匹配（dish_name == platform_item_name）→ confidence=1.0
        2. Levenshtein 编辑距离匹配 → confidence = 1 - dist/max_len
        3. 低于 AUTO_MATCH_MIN_CONFIDENCE 的不建议
        """
        await self._set_rls()
        sid = uuid.UUID(store_id)

        # 未映射的平台条目
        unmapped_result = await self.db.execute(
            text("""
                SELECT platform_item_id, platform_item_name
                FROM platform_dish_mappings
                WHERE tenant_id = :tid
                  AND store_id  = :sid
                  AND platform  = :platform
                  AND dish_id IS NULL
                  AND is_active = true
                ORDER BY created_at DESC
            """),
            {"tid": self._tenant_uuid, "sid": sid, "platform": platform},
        )
        unmapped_rows = unmapped_result.fetchall()

        if not unmapped_rows:
            return AutoMatchResult(suggested=[], unmatched_count=0)

        # 内部菜品候选（当前门店 + 集团通用）
        dish_result = await self.db.execute(
            text("""
                SELECT id, dish_name
                FROM dishes
                WHERE tenant_id = :tid
                  AND (store_id = :sid OR store_id IS NULL)
                  AND is_available = true
                  AND is_deleted = false
                ORDER BY dish_name
            """),
            {"tid": self._tenant_uuid, "sid": sid},
        )
        dish_rows = dish_result.fetchall()

        if not dish_rows:
            return AutoMatchResult(suggested=[], unmatched_count=len(unmapped_rows))

        suggested: list[MappingSuggestion] = []
        unmatched_count = 0

        for platform_item_id, platform_item_name in unmapped_rows:
            if not platform_item_name:
                unmatched_count += 1
                continue

            best_confidence = 0.0
            best_dish_id: Optional[uuid.UUID] = None
            best_dish_name = ""
            best_reason = ""

            for dish_id, dish_name in dish_rows:
                confidence = _name_confidence(platform_item_name, dish_name)
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_dish_id = dish_id
                    best_dish_name = dish_name
                    if confidence >= 1.0:
                        best_reason = "exact_match"
                    else:
                        dist = _levenshtein(
                            platform_item_name.strip().lower(),
                            dish_name.strip().lower(),
                        )
                        best_reason = f"edit_distance:{dist}"

            if best_confidence >= self.AUTO_MATCH_MIN_CONFIDENCE and best_dish_id:
                suggested.append(
                    MappingSuggestion(
                        platform_item_id=platform_item_id,
                        platform_item_name=platform_item_name,
                        dish_id=best_dish_id,
                        dish_name=best_dish_name,
                        confidence=round(best_confidence, 4),
                        reason=best_reason,
                    )
                )
            else:
                unmatched_count += 1

        log.info(
            "channel_mapping.auto_match",
            platform=platform,
            suggested=len(suggested),
            unmatched=unmatched_count,
        )
        return AutoMatchResult(suggested=suggested, unmatched_count=unmatched_count)

    # ── 发布渠道菜单版本 ──────────────────────────────────────────────────────

    async def publish_channel_menu(
        self,
        store_id: str,
        channel_id: str,
        dish_overrides: list[dict],
        published_by: Optional[str] = None,
    ) -> ChannelMenuVersion:
        """发布渠道菜单版本（自动递增版本号）。

        dish_overrides 格式：
          [{dish_id, channel_price_fen?, is_available?, channel_name?}]
        """
        await self._set_rls()
        sid = uuid.UUID(store_id)
        pub_by = uuid.UUID(published_by) if published_by else None

        import json as _json

        # 获取当前最大版本号
        ver_result = await self.db.execute(
            text("""
                SELECT COALESCE(MAX(version_no), 0)
                FROM channel_menu_versions
                WHERE tenant_id  = :tid
                  AND store_id   = :sid
                  AND channel_id = :channel_id
            """),
            {"tid": self._tenant_uuid, "sid": sid, "channel_id": channel_id},
        )
        current_max = ver_result.scalar() or 0
        new_version_no = current_max + 1

        # 将 draft→archived 已有 published 版本
        await self.db.execute(
            text("""
                UPDATE channel_menu_versions
                SET status = 'archived'
                WHERE tenant_id  = :tid
                  AND store_id   = :sid
                  AND channel_id = :channel_id
                  AND status     = 'published'
            """),
            {"tid": self._tenant_uuid, "sid": sid, "channel_id": channel_id},
        )

        overrides_json = _json.dumps(
            [
                {
                    "dish_id": str(o.get("dish_id", "")),
                    "channel_price_fen": o.get("channel_price_fen"),
                    "is_available": o.get("is_available", True),
                    "channel_name": o.get("channel_name"),
                }
                for o in dish_overrides
            ],
            ensure_ascii=False,
        )

        result = await self.db.execute(
            text("""
                INSERT INTO channel_menu_versions
                    (tenant_id, store_id, channel_id, version_no,
                     dish_overrides, published_at, published_by, status)
                VALUES
                    (:tid, :sid, :channel_id, :version_no,
                     :dish_overrides::jsonb, NOW(), :published_by, 'published')
                RETURNING id, version_no, dish_overrides, published_at, published_by, status
            """),
            {
                "tid": self._tenant_uuid,
                "sid": sid,
                "channel_id": channel_id,
                "version_no": new_version_no,
                "dish_overrides": overrides_json,
                "published_by": pub_by,
            },
        )
        row = result.fetchone()
        raw_overrides = row[2] if isinstance(row[2], list) else _json.loads(row[2] or "[]")

        log.info(
            "channel_mapping.publish_menu",
            store_id=store_id,
            channel_id=channel_id,
            version_no=new_version_no,
        )
        return ChannelMenuVersion(
            id=row[0],
            store_id=sid,
            channel_id=channel_id,
            version_no=row[1],
            dish_overrides=[DishOverride(**o) for o in raw_overrides],
            published_at=row[3].isoformat() if row[3] else None,
            published_by=row[4],
            status=row[5],
        )

    # ── 回滚渠道菜单版本 ──────────────────────────────────────────────────────

    async def rollback_channel_version(self, version_id: str) -> ChannelMenuVersion:
        """回滚到指定版本（将其重新设为 published，当前 published→archived）。"""
        await self._set_rls()
        import json as _json

        vid = uuid.UUID(version_id)

        # 查找目标版本
        ver_result = await self.db.execute(
            text("""
                SELECT id, store_id, channel_id, version_no,
                       dish_overrides, published_at, published_by, status
                FROM channel_menu_versions
                WHERE id = :vid AND tenant_id = :tid
            """),
            {"vid": vid, "tid": self._tenant_uuid},
        )
        row = ver_result.fetchone()
        if not row:
            raise ValueError(f"版本不存在: {version_id}")

        store_id_val: uuid.UUID = row[1]
        channel_id_val: str = row[2]

        # 将当前 published 版本归档
        await self.db.execute(
            text("""
                UPDATE channel_menu_versions
                SET status = 'archived'
                WHERE tenant_id  = :tid
                  AND store_id   = :sid
                  AND channel_id = :channel_id
                  AND status     = 'published'
            """),
            {"tid": self._tenant_uuid, "sid": store_id_val, "channel_id": channel_id_val},
        )

        # 将目标版本重新 published
        await self.db.execute(
            text("""
                UPDATE channel_menu_versions
                SET status = 'published', published_at = NOW()
                WHERE id = :vid AND tenant_id = :tid
            """),
            {"vid": vid, "tid": self._tenant_uuid},
        )

        raw_overrides = row[4] if isinstance(row[4], list) else _json.loads(row[4] or "[]")
        log.info("channel_mapping.rollback", version_id=version_id, channel_id=channel_id_val)
        return ChannelMenuVersion(
            id=row[0],
            store_id=store_id_val,
            channel_id=channel_id_val,
            version_no=row[3],
            dish_overrides=[DishOverride(**o) for o in raw_overrides],
            published_at=None,  # 刚回滚，由 DB trigger 更新
            published_by=row[6],
            status="published",
        )

    # ── 渠道价格查询 ──────────────────────────────────────────────────────────

    async def get_channel_price(
        self,
        store_id: str,
        channel_id: str,
        dish_id: str,
    ) -> int:
        """获取菜品在特定渠道的价格（有 override 用 override，否则用内部价）。"""
        await self._set_rls()
        sid = uuid.UUID(store_id)
        did = uuid.UUID(dish_id)

        # 查最新 published 版本的 overrides
        ver_result = await self.db.execute(
            text("""
                SELECT dish_overrides
                FROM channel_menu_versions
                WHERE tenant_id  = :tid
                  AND store_id   = :sid
                  AND channel_id = :channel_id
                  AND status     = 'published'
                ORDER BY version_no DESC
                LIMIT 1
            """),
            {"tid": self._tenant_uuid, "sid": sid, "channel_id": channel_id},
        )
        ver_row = ver_result.fetchone()

        import json as _json

        if ver_row:
            overrides = ver_row[0] if isinstance(ver_row[0], list) else _json.loads(ver_row[0] or "[]")
            for item in overrides:
                if str(item.get("dish_id", "")) == str(did):
                    price = item.get("channel_price_fen")
                    if price is not None:
                        return int(price)

        # 内部默认价格
        price_result = await self.db.execute(
            text("SELECT price_fen FROM dishes WHERE id = :did AND tenant_id = :tid"),
            {"did": did, "tid": self._tenant_uuid},
        )
        price_row = price_result.fetchone()
        if price_row:
            return int(price_row[0])
        return 0

    # ── 渠道差异对比 ─────────────────────────────────────────────────────────

    async def get_channel_diff(self, store_id: str) -> ChannelDiff:
        """对比各渠道菜单差异（价格/可用性）。

        返回以菜品为行、渠道为列的差异矩阵。
        """
        await self._set_rls()
        sid = uuid.UUID(store_id)
        import json as _json

        # 获取所有有 published 版本的渠道
        chan_result = await self.db.execute(
            text("""
                SELECT DISTINCT channel_id
                FROM channel_menu_versions
                WHERE tenant_id = :tid
                  AND store_id  = :sid
                  AND status    = 'published'
                ORDER BY channel_id
            """),
            {"tid": self._tenant_uuid, "sid": sid},
        )
        channels = [r[0] for r in chan_result.fetchall()]

        if not channels:
            return ChannelDiff(channels=[], dishes=[])

        # 获取每个渠道最新 published 版本
        channel_overrides: dict[str, list[dict]] = {}
        for ch in channels:
            ver_result = await self.db.execute(
                text("""
                    SELECT dish_overrides
                    FROM channel_menu_versions
                    WHERE tenant_id  = :tid
                      AND store_id   = :sid
                      AND channel_id = :channel_id
                      AND status     = 'published'
                    ORDER BY version_no DESC
                    LIMIT 1
                """),
                {"tid": self._tenant_uuid, "sid": sid, "channel_id": ch},
            )
            ver_row = ver_result.fetchone()
            if ver_row:
                raw = ver_row[0] if isinstance(ver_row[0], list) else _json.loads(ver_row[0] or "[]")
                channel_overrides[ch] = raw

        # 收集所有 dish_id
        all_dish_ids: set[str] = set()
        for overrides in channel_overrides.values():
            for item in overrides:
                if item.get("dish_id"):
                    all_dish_ids.add(str(item["dish_id"]))

        if not all_dish_ids:
            return ChannelDiff(channels=channels, dishes=[])

        # 批量获取菜品名称
        dish_names: dict[str, str] = {}
        dish_prices: dict[str, int] = {}
        placeholders = ", ".join(f":did_{i}" for i in range(len(all_dish_ids)))
        params: dict = {"tid": self._tenant_uuid}
        for i, did in enumerate(all_dish_ids):
            params[f"did_{i}"] = uuid.UUID(did)

        d_result = await self.db.execute(
            text(f"""
                SELECT id, dish_name, price_fen
                FROM dishes
                WHERE tenant_id = :tid AND id IN ({placeholders})
            """),
            params,
        )
        for d_id, d_name, d_price in d_result.fetchall():
            dish_names[str(d_id)] = d_name
            dish_prices[str(d_id)] = d_price

        # 构建差异矩阵
        dish_rows: list[DishChannelRow] = []
        for dish_id_str in sorted(all_dish_ids):
            prices_by_channel: dict[str, Optional[int]] = {}
            availability_by_channel: dict[str, bool] = {}
            for ch in channels:
                found = False
                for item in channel_overrides.get(ch, []):
                    if str(item.get("dish_id", "")) == dish_id_str:
                        override_price = item.get("channel_price_fen")
                        prices_by_channel[ch] = (
                            int(override_price) if override_price is not None else dish_prices.get(dish_id_str)
                        )
                        availability_by_channel[ch] = bool(item.get("is_available", True))
                        found = True
                        break
                if not found:
                    prices_by_channel[ch] = dish_prices.get(dish_id_str)
                    availability_by_channel[ch] = False  # 未发布到该渠道视为不可用

            dish_rows.append(
                DishChannelRow(
                    dish_id=uuid.UUID(dish_id_str),
                    dish_name=dish_names.get(dish_id_str, dish_id_str),
                    prices_by_channel=prices_by_channel,
                    availability_by_channel=availability_by_channel,
                )
            )

        return ChannelDiff(channels=channels, dishes=dish_rows)

    # ── 渠道发布历史 ──────────────────────────────────────────────────────────

    async def get_channel_versions(
        self,
        store_id: str,
        channel_id: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[ChannelMenuVersion], int]:
        """查询渠道发布历史（分页）。"""
        await self._set_rls()
        sid = uuid.UUID(store_id)
        import json as _json

        where_channel = "AND channel_id = :channel_id" if channel_id else ""
        params: dict = {
            "tid": self._tenant_uuid,
            "sid": sid,
            "offset": (page - 1) * size,
            "limit": size,
        }
        if channel_id:
            params["channel_id"] = channel_id

        count_result = await self.db.execute(
            text(f"""
                SELECT COUNT(*)
                FROM channel_menu_versions
                WHERE tenant_id = :tid AND store_id = :sid {where_channel}
            """),
            params,
        )
        total = count_result.scalar() or 0

        list_result = await self.db.execute(
            text(f"""
                SELECT id, store_id, channel_id, version_no,
                       dish_overrides, published_at, published_by, status
                FROM channel_menu_versions
                WHERE tenant_id = :tid AND store_id = :sid {where_channel}
                ORDER BY version_no DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        versions = [
            ChannelMenuVersion(
                id=r[0],
                store_id=r[1],
                channel_id=r[2],
                version_no=r[3],
                dish_overrides=[
                    DishOverride(**o) for o in (r[4] if isinstance(r[4], list) else _json.loads(r[4] or "[]"))
                ],
                published_at=r[5].isoformat() if r[5] else None,
                published_by=r[6],
                status=r[7],
            )
            for r in list_result.fetchall()
        ]
        return versions, int(total)
