"""客户分群引擎 — 基于 RFM、行为特征、消费偏好的精准人群池

分群体系：
  - 内置分群（BUILTIN_SEGMENTS）：28个预定义人群，覆盖 RFM 8象限、时间、
    消费时段、生命周期、宴席等维度，可直接使用，无需用户配置。
  - 自定义分群：运营人员通过规则 DSL 灵活组合条件，AND 逻辑，
    支持 eq/ne/gt/gte/lt/lte/in/contains/between 操作符。

所有实际客户数据通过调用 tx-member 服务获取，本模块负责：
  1. 将分群定义转换为 tx-member API 查询参数
  2. 管理内存分群注册表（含租户自定义分群）
  3. 维护 5 分钟人数缓存，避免频繁打穿 tx-member

金额单位：分(fen)
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

import httpx
import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

TX_MEMBER_URL: str = os.getenv("TX_MEMBER_SERVICE_URL", "http://tx-member:8000")
_CACHE_TTL_SECONDS: int = 300  # 5 分钟

# ---------------------------------------------------------------------------
# 内置分群定义
# ---------------------------------------------------------------------------

BUILTIN_SEGMENTS: dict[str, dict[str, Any]] = {
    # ── RFM 8象限 ───────────────────────────────────────────────────────────
    "rfm_champions": {
        "r": [4, 5], "f": [4, 5], "m": [4, 5],
        "name": "冠军客户",
        "description": "近期消费、高频、高额的最优质客户",
    },
    "rfm_loyal": {
        "r": [2, 5], "f": [3, 5], "m": [3, 5],
        "name": "忠诚客户",
        "description": "消费频次高、金额高的长期客户",
    },
    "rfm_potential": {
        "r": [3, 5], "f": [1, 3], "m": [1, 3],
        "name": "潜力客户",
        "description": "近期活跃但频次和消费额有待提升",
    },
    "rfm_new": {
        "r": [4, 5], "f": [1, 1], "m": [1, 5],
        "name": "新客户",
        "description": "最近消费但仅一次的新会员",
    },
    "rfm_at_risk": {
        "r": [2, 3], "f": [2, 5], "m": [2, 5],
        "name": "流失风险",
        "description": "曾经活跃但近期消费减少",
    },
    "rfm_cant_lose": {
        "r": [1, 2], "f": [4, 5], "m": [4, 5],
        "name": "不能失去",
        "description": "高价值高频但已较长时间未消费，亟需召回",
    },
    "rfm_hibernating": {
        "r": [1, 2], "f": [1, 2], "m": [1, 2],
        "name": "休眠客户",
        "description": "各维度评分均低，处于半休眠状态",
    },
    "rfm_lost": {
        "r": [1, 1], "f": [1, 5], "m": [1, 5],
        "name": "已流失",
        "description": "最近度极低，基本可认定为流失",
    },

    # ── 时间分群 ────────────────────────────────────────────────────────────
    "silent_90d": {
        "last_order_days_min": 90,
        "name": "90天未消费",
        "description": "超过90天没有消费记录",
    },
    "silent_180d": {
        "last_order_days_min": 180,
        "name": "180天未消费",
        "description": "超过180天没有消费记录",
    },
    "silent_365d": {
        "last_order_days_min": 365,
        "name": "1年未消费",
        "description": "超过1年没有消费记录，高度疑似永久流失",
    },
    "active_7d": {
        "last_order_days_max": 7,
        "name": "7天内活跃",
        "description": "7天内有消费，用于复购刺激",
    },
    "active_30d": {
        "last_order_days_max": 30,
        "name": "30天内活跃",
        "description": "30天内有消费",
    },

    # ── 消费时段分群 ────────────────────────────────────────────────────────
    "lunch_regulars": {
        "preferred_time_range": ["11:00", "14:00"],
        "name": "午餐常客",
        "description": "偏好11:00-14:00时段消费",
    },
    "dinner_regulars": {
        "preferred_time_range": ["17:00", "21:00"],
        "name": "晚餐常客",
        "description": "偏好17:00-21:00时段消费",
    },
    "weekend_visitors": {
        "visit_days": [5, 6],
        "name": "周末族",
        "description": "主要在周六/周日消费",
    },
    "weekday_visitors": {
        "visit_days": [0, 1, 2, 3, 4],
        "name": "工作日族",
        "description": "主要在工作日消费",
    },

    # ── 生命周期分群 ────────────────────────────────────────────────────────
    "new_7d": {
        "registered_days_max": 7,
        "name": "新注册7天",
        "description": "注册不超过7天的新会员",
    },
    "new_30d": {
        "registered_days_max": 30,
        "name": "新注册30天",
        "description": "注册不超过30天的新会员",
    },
    "birthday_week": {
        "birthday_days": 7,
        "name": "生日周",
        "description": "未来7天内生日的会员",
    },
    "high_churn_risk": {
        "risk_score_min": 0.7,
        "name": "高流失风险",
        "description": "流失风险评分 ≥ 0.7 的客户",
    },

    # ── 宴席相关 ────────────────────────────────────────────────────────────
    "banquet_prospects": {
        "tags_include": ["宴席意向"],
        "name": "宴席潜客",
        "description": "标签含"宴席意向"的潜在宴席客户",
    },
    "banquet_regulars": {
        "total_banquet_min": 2,
        "name": "宴席常客",
        "description": "累计宴席消费 ≥ 2 次",
    },
}

# ---------------------------------------------------------------------------
# 内存存储
# ---------------------------------------------------------------------------

# 自定义分群注册表：{f"{tenant_id}:{segment_id}": segment_dict}
_custom_segments: dict[str, dict[str, Any]] = {}

# 人数缓存：{f"{tenant_id}:{segment_id}": {"count": int, "expires_at": float}}
_count_cache: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _cache_key(tenant_id: UUID, segment_id: str) -> str:
    return f"{tenant_id}:{segment_id}"


def _build_rfm_params(seg_def: dict[str, Any]) -> dict[str, Any]:
    """将 RFM 分群定义转换为 tx-member 查询参数。"""
    params: dict[str, Any] = {}
    if "r" in seg_def:
        params["r_score_min"], params["r_score_max"] = seg_def["r"]
    if "f" in seg_def:
        params["f_score_min"], params["f_score_max"] = seg_def["f"]
    if "m" in seg_def:
        params["m_score_min"], params["m_score_max"] = seg_def["m"]
    return params


def _build_builtin_params(segment_id: str, seg_def: dict[str, Any]) -> dict[str, Any]:
    """将内置分群定义转换为 tx-member /api/v1/member/customers 查询参数。"""
    params: dict[str, Any] = {}

    # RFM 评分范围
    params.update(_build_rfm_params(seg_def))

    # 时间分群 — 距上次消费天数
    if "last_order_days_min" in seg_def:
        params["no_visit_days_min"] = seg_def["last_order_days_min"]
    if "last_order_days_max" in seg_def:
        params["no_visit_days_max"] = seg_def["last_order_days_max"]

    # 消费时段（传给 tx-member，由其过滤）
    if "preferred_time_range" in seg_def:
        params["preferred_time_start"] = seg_def["preferred_time_range"][0]
        params["preferred_time_end"] = seg_def["preferred_time_range"][1]

    # 偏好星期
    if "visit_days" in seg_def:
        params["visit_weekdays"] = ",".join(str(d) for d in seg_def["visit_days"])

    # 注册天数
    if "registered_days_max" in seg_def:
        params["registered_days_max"] = seg_def["registered_days_max"]

    # 生日
    if "birthday_days" in seg_def:
        params["birthday_within_days"] = seg_def["birthday_days"]

    # 流失风险
    if "risk_score_min" in seg_def:
        params["risk_score_min"] = seg_def["risk_score_min"]

    # 标签
    if "tags_include" in seg_def:
        params["tags_include"] = ",".join(seg_def["tags_include"])

    # 宴席次数
    if "total_banquet_min" in seg_def:
        params["total_banquet_count_min"] = seg_def["total_banquet_min"]

    return params


_SUPPORTED_FIELDS = frozenset({
    "rfm_level", "r_score", "f_score", "m_score", "risk_score",
    "last_order_at", "total_order_count", "total_order_amount_fen",
    "tags", "store_id", "source",
})

_SUPPORTED_OPS = frozenset({
    "eq", "ne", "gt", "gte", "lt", "lte", "in", "contains", "between",
})


def _build_custom_params(rules: list[dict[str, Any]]) -> dict[str, Any]:
    """将自定义规则列表（AND 逻辑）转换为 tx-member 查询参数。

    字段/操作符映射：
      rfm_level     in      → rfm_level (逗号分隔)
      r_score       gte/lte → r_score_min / r_score_max
      f_score       gte/lte → f_score_min / f_score_max
      m_score       gte/lte → m_score_min / m_score_max
      risk_score    gte/lte → risk_score_min / risk_score_max
      last_order_at gte/lte → last_order_after / last_order_before
      total_order_count  gte/lte → order_count_min / order_count_max
      total_order_amount_fen gte/lte → amount_min_fen / amount_max_fen
      tags          contains → tags_include
      store_id      eq/in   → store_id
      source        eq/in   → source
    """
    params: dict[str, Any] = {}

    for rule in rules:
        field: str = rule.get("field", "")
        op: str = rule.get("op", "")
        value: Any = rule.get("value")

        if field not in _SUPPORTED_FIELDS:
            logger.warning("unsupported_segment_field", field=field)
            continue
        if op not in _SUPPORTED_OPS:
            logger.warning("unsupported_segment_op", op=op, field=field)
            continue

        if field == "rfm_level":
            if op == "in" and isinstance(value, list):
                params["rfm_level"] = ",".join(value)
            elif op == "eq":
                params["rfm_level"] = value

        elif field in ("r_score", "f_score", "m_score"):
            prefix = field  # e.g. "r_score"
            if op in ("eq", "gte"):
                params[f"{prefix}_min"] = value
            if op in ("eq", "lte"):
                params[f"{prefix}_max"] = value
            if op == "gt":
                params[f"{prefix}_min"] = value + 1
            if op == "lt":
                params[f"{prefix}_max"] = value - 1
            if op == "between" and isinstance(value, list) and len(value) == 2:
                params[f"{prefix}_min"] = value[0]
                params[f"{prefix}_max"] = value[1]

        elif field == "risk_score":
            if op in ("eq", "gte"):
                params["risk_score_min"] = value
            if op in ("eq", "lte"):
                params["risk_score_max"] = value

        elif field == "last_order_at":
            if op in ("gte", "gt"):
                params["last_order_after"] = value
            if op in ("lte", "lt"):
                params["last_order_before"] = value
            if op == "between" and isinstance(value, list) and len(value) == 2:
                params["last_order_after"] = value[0]
                params["last_order_before"] = value[1]

        elif field == "total_order_count":
            if op in ("eq", "gte"):
                params["order_count_min"] = value
            if op in ("eq", "lte"):
                params["order_count_max"] = value

        elif field == "total_order_amount_fen":
            if op in ("eq", "gte"):
                params["amount_min_fen"] = value
            if op in ("eq", "lte"):
                params["amount_max_fen"] = value

        elif field == "tags":
            if op == "contains":
                params["tags_include"] = value

        elif field == "store_id":
            if op == "eq":
                params["store_id"] = value
            elif op == "in" and isinstance(value, list):
                params["store_id"] = ",".join(value)

        elif field == "source":
            if op == "eq":
                params["source"] = value
            elif op == "in" and isinstance(value, list):
                params["source"] = ",".join(value)

    return params


# ---------------------------------------------------------------------------
# AudienceSegmentationService
# ---------------------------------------------------------------------------

class AudienceSegmentationService:
    """客户分群引擎 — 内置分群 + 自定义规则分群 + 5分钟人数缓存"""

    # ------------------------------------------------------------------
    # 公开：分群查询
    # ------------------------------------------------------------------

    async def get_segment_members(
        self,
        segment_id: str,
        tenant_id: UUID,
        page: int = 1,
        size: int = 100,
    ) -> dict[str, Any]:
        """获取分群成员列表（分页）。

        优先查内置分群，再查租户自定义分群。
        通过 tx-member API 实时获取，返回格式：
          {segment_id, segment_name, total, members: [customer_id, ...], refresh_at}
        """
        seg_name, api_params = self._resolve_segment(segment_id, tenant_id)
        if api_params is None:
            raise ValueError(f"分群不存在: {segment_id}")

        api_params["page"] = page
        api_params["size"] = size

        log = logger.bind(tenant_id=str(tenant_id), segment_id=segment_id, page=page)
        log.info("segment_members_fetch_start")

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{TX_MEMBER_URL}/api/v1/member/customers",
                headers={"X-Tenant-ID": str(tenant_id)},
                params=api_params,
            )
        resp.raise_for_status()

        payload = resp.json()
        items: list[dict] = payload.get("data", {}).get("items", [])
        total: int = payload.get("data", {}).get("total", 0)

        # 仅返回 customer_id 列表，减少数据传输量
        member_ids = [item.get("customer_id") or item.get("id") for item in items]

        log.info("segment_members_fetch_done", total=total, returned=len(member_ids))
        return {
            "segment_id": segment_id,
            "segment_name": seg_name,
            "total": total,
            "members": member_ids,
            "page": page,
            "size": size,
            "refresh_at": datetime.now(timezone.utc).isoformat(),
        }

    async def count_segment(self, segment_id: str, tenant_id: UUID) -> int:
        """快速获取分群人数（仅返回 total，不获取明细）。

        优先从 5 分钟内存缓存读取；缓存失效时查询 tx-member。
        """
        ck = _cache_key(tenant_id, segment_id)
        cached = _count_cache.get(ck)
        if cached and cached["expires_at"] > time.monotonic():
            return cached["count"]

        # 缓存失效或不存在，重新查询（size=1 节省传输）
        seg_name, api_params = self._resolve_segment(segment_id, tenant_id)
        if api_params is None:
            raise ValueError(f"分群不存在: {segment_id}")

        api_params["page"] = 1
        api_params["size"] = 1

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{TX_MEMBER_URL}/api/v1/member/customers",
                headers={"X-Tenant-ID": str(tenant_id)},
                params=api_params,
            )
        resp.raise_for_status()

        total: int = resp.json().get("data", {}).get("total", 0)
        _count_cache[ck] = {
            "count": total,
            "expires_at": time.monotonic() + _CACHE_TTL_SECONDS,
        }
        logger.info("segment_count_refreshed", tenant_id=str(tenant_id),
                    segment_id=segment_id, count=total)
        return total

    async def create_custom_segment(
        self,
        name: str,
        rules: list[dict[str, Any]],
        tenant_id: UUID,
    ) -> dict[str, Any]:
        """创建自定义分群（规则存入内存注册表）。

        Args:
            name:      分群名称
            rules:     规则列表，AND 逻辑，例如:
                       [{"field": "r_score", "op": "gte", "value": 4},
                        {"field": "tags", "op": "contains", "value": "常客"}]
            tenant_id: 租户 UUID

        Returns:
            分群元数据 dict
        """
        # 验证规则字段/操作符合法性
        for rule in rules:
            field = rule.get("field", "")
            op = rule.get("op", "")
            if field not in _SUPPORTED_FIELDS:
                raise ValueError(f"不支持的分群字段: {field}，支持: {sorted(_SUPPORTED_FIELDS)}")
            if op not in _SUPPORTED_OPS:
                raise ValueError(f"不支持的操作符: {op}，支持: {sorted(_SUPPORTED_OPS)}")

        segment_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        segment: dict[str, Any] = {
            "segment_id": segment_id,
            "name": name,
            "segment_type": "custom",
            "rules": rules,
            "tenant_id": str(tenant_id),
            "created_at": now,
            "updated_at": now,
        }
        ck = _cache_key(tenant_id, segment_id)
        _custom_segments[ck] = segment

        logger.info("custom_segment_created", tenant_id=str(tenant_id),
                    segment_id=segment_id, name=name, rule_count=len(rules))
        return segment

    async def list_segments(self, tenant_id: UUID) -> list[dict[str, Any]]:
        """列出所有内置分群 + 该租户的自定义分群，附带缓存人数。

        人数通过 count_segment 读取（5 分钟缓存），首次调用时 total 为 None（异步延迟加载）。
        """
        result: list[dict[str, Any]] = []

        # 内置分群
        for seg_id, seg_def in BUILTIN_SEGMENTS.items():
            ck = _cache_key(tenant_id, seg_id)
            cached = _count_cache.get(ck)
            cached_count = cached["count"] if (cached and cached["expires_at"] > time.monotonic()) else None
            result.append({
                "segment_id": seg_id,
                "name": seg_def["name"],
                "description": seg_def.get("description", ""),
                "segment_type": "builtin",
                "total": cached_count,
            })

        # 自定义分群（当前租户）
        prefix = f"{tenant_id}:"
        for ck, seg in _custom_segments.items():
            if not ck.startswith(prefix):
                continue
            seg_id = seg["segment_id"]
            count_cache = _count_cache.get(ck)
            cached_count = count_cache["count"] if (count_cache and count_cache["expires_at"] > time.monotonic()) else None
            result.append({
                "segment_id": seg_id,
                "name": seg["name"],
                "description": "",
                "segment_type": "custom",
                "rules": seg["rules"],
                "total": cached_count,
                "created_at": seg["created_at"],
            })

        return result

    async def delete_custom_segment(self, segment_id: str, tenant_id: UUID) -> bool:
        """删除租户自定义分群。

        Returns:
            True  — 删除成功
            False — 分群不存在
        """
        ck = _cache_key(tenant_id, segment_id)
        if ck not in _custom_segments:
            return False
        del _custom_segments[ck]
        _count_cache.pop(ck, None)
        logger.info("custom_segment_deleted", tenant_id=str(tenant_id), segment_id=segment_id)
        return True

    async def refresh_segment_cache(self, tenant_id: UUID) -> dict[str, Any]:
        """强制刷新当前租户所有分群的人数缓存（内置 + 自定义）。

        适合后台任务定期调用（如每小时刷一次）。
        Returns:
          {"refreshed": int, "failed": int, "details": {segment_id: count}}
        """
        all_segment_ids = list(BUILTIN_SEGMENTS.keys())

        # 加入当前租户自定义分群
        prefix = f"{tenant_id}:"
        for ck, seg in _custom_segments.items():
            if ck.startswith(prefix):
                all_segment_ids.append(seg["segment_id"])

        refreshed = 0
        failed = 0
        details: dict[str, int] = {}

        for seg_id in all_segment_ids:
            ck = _cache_key(tenant_id, seg_id)
            # 强制过期缓存
            _count_cache.pop(ck, None)
            try:
                count = await self.count_segment(seg_id, tenant_id)
                details[seg_id] = count
                refreshed += 1
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("segment_cache_refresh_failed",
                               segment_id=seg_id, tenant_id=str(tenant_id), error=str(exc))
                failed += 1

        logger.info("segment_cache_refresh_complete",
                    tenant_id=str(tenant_id), refreshed=refreshed, failed=failed)
        return {"refreshed": refreshed, "failed": failed, "details": details}

    # ------------------------------------------------------------------
    # 私有：分群解析
    # ------------------------------------------------------------------

    def _resolve_segment(
        self,
        segment_id: str,
        tenant_id: UUID,
    ) -> tuple[str, dict[str, Any] | None]:
        """根据 segment_id 返回 (名称, tx-member 查询参数)。

        查找顺序：内置分群 → 租户自定义分群。
        未找到时返回 (segment_id, None)。
        """
        # 内置分群
        seg_def = BUILTIN_SEGMENTS.get(segment_id)
        if seg_def is not None:
            api_params = _build_builtin_params(segment_id, seg_def)
            return seg_def["name"], api_params

        # 自定义分群
        ck = _cache_key(tenant_id, segment_id)
        custom = _custom_segments.get(ck)
        if custom is not None:
            api_params = _build_custom_params(custom["rules"])
            return custom["name"], api_params

        return segment_id, None
