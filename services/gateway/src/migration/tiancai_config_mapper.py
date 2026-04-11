"""
天财商龙 → 屯象OS 配置智能映射

将天财商龙门店配置项映射到屯象OS三层配置架构：
  L1 (业态模板)   — 推断业态类型，选择最接近的模板
  L2 (DeliveryAgent) — 预填入 20 问中可从天财自动读取的答案
  L3 (Agent动态策略) — 将天财折扣/报表配置映射到 Agent 策略参数

核心价值：
  天财切换客户无需从零回答 20 问，系统自动从天财读取已有配置，
  DeliveryAgent 只需客户确认/调整少数无法自动读取的关键决策
  （通常只剩 5-8 个问题需要人工回答）。

使用方式：
    mapper = TiancaiConfigMapper(adapter)
    prefilled = await mapper.extract_prefilled_answers()
    # 然后传给 POST /api/v1/onboarding/start 的 prefilled_answers
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class TiancaiConfigMapper:
    """
    从天财商龙 API 读取门店配置，映射到 DeliveryAgent 的 prefilled_answers。

    映射规则（天财字段 → 屯象 DeliveryAgent key）：
    ┌─────────────────────────────────┬─────────────────────────────┐
    │ 天财配置项                        │ 屯象 DeliveryAgent key       │
    ├─────────────────────────────────┼─────────────────────────────┤
    │ shop.name                       │ store_name                  │
    │ shop.tableCount                 │ table_count                 │
    │ shop.vipRoomCount               │ vip_room_count              │
    │ printer[type=receipt].ip        │ printers[receipt]           │
    │ printer[type=kitchen].ip        │ printers[kitchen]           │
    │ bizHours[].startTime/endTime    │ shifts                      │
    │ discount.employeeMaxRate        │ employee_max_discount       │
    │ discount.managerMaxRate         │ manager_max_discount        │
    │ billing.minConsume              │ min_spend_yuan              │
    │ billing.serviceFeeRate          │ service_fee_rate            │
    │ kitchen[].name                  │ kds_zones                   │
    │ payChannel[].type               │ payment_methods             │
    │ memberConfig.pointRate          │ point_rate                  │
    │ memberConfig.redeemRate         │ point_redeem_rate           │
    │ deliveryPlatform[]              │ channels_enabled            │
    └─────────────────────────────────┴─────────────────────────────┘
    """

    def __init__(self, adapter) -> None:
        self._adapter = adapter

    async def extract_prefilled_answers(self) -> dict[str, Any]:
        """
        从天财 API 读取门店配置，返回 prefilled_answers dict。

        如果某项天财 API 不提供，对应 key 不会出现在结果中，
        DeliveryAgent 会在会话中继续提问。
        """
        answers: dict[str, Any] = {}

        # 并发读取所有天财 API（各映射独立，单项失败不阻断整体）
        await asyncio.gather(
            self._map_shop_basic(answers),
            self._map_printers(answers),
            self._map_shifts(answers),
            self._map_discount_policy(answers),
            self._map_billing_rules(answers),
            self._map_kitchen_zones(answers),
            self._map_payment_methods(answers),
            self._map_member_config(answers),
            self._map_delivery_channels(answers),
        )
        self._infer_restaurant_type(answers)

        logger.info(
            "tiancai_config_mapped",
            shop_id=self._adapter.shop_id,
            prefilled_keys=list(answers.keys()),
        )
        return answers

    # ── 各映射方法 ────────────────────────────────────────────────────

    async def _map_shop_basic(self, answers: dict) -> None:
        """门店基础信息：名称、桌台数、包厢数"""
        try:
            data = await self._adapter._request(
                "/api/shop/getShopInfo",
                {"centerId": self._adapter.center_id, "shopId": self._adapter.shop_id},
            )
            if name := data.get("shopName", data.get("name")):
                answers["store_name"] = str(name)
            if tc := data.get("tableCount", data.get("table_count")):
                answers["table_count"] = int(tc)
            if vc := data.get("vipRoomCount", data.get("vip_room_count")):
                answers["vip_room_count"] = int(vc)
        except Exception as exc:
            logger.debug("tiancai_map_shop_basic_failed", error=str(exc))

    async def _map_printers(self, answers: dict) -> None:
        """打印机配置：类型和IP"""
        try:
            data = await self._adapter._request(
                "/api/device/getPrinterList",
                {"shopId": self._adapter.shop_id},
            )
            printers_raw = data.get("printerList", data.get("list", []))
            if not printers_raw:
                return

            printers = []
            for p in printers_raw:
                ptype_raw = str(p.get("type", p.get("printerType", "receipt"))).lower()
                # 天财类型映射：0/receipt/收银 → receipt；1/kitchen/厨房 → kitchen
                if ptype_raw in ("0", "receipt", "收银台", "收银"):
                    ptype = "receipt"
                elif ptype_raw in ("1", "kitchen", "厨房", "厨打"):
                    ptype = "kitchen"
                elif ptype_raw in ("2", "label", "标签"):
                    ptype = "label"
                else:
                    ptype = "kitchen"

                printers.append({
                    "name": p.get("name", p.get("printerName", f"{ptype}打印机")),
                    "printer_type": ptype,
                    "ip": p.get("ip", p.get("ipAddress", "")),
                    "is_default": bool(p.get("isDefault", p.get("default", False))),
                })

            if printers:
                answers["printers"] = printers
                answers["printer_count"] = len(printers)

        except Exception as exc:
            logger.debug("tiancai_map_printers_failed", error=str(exc))

    async def _map_shifts(self, answers: dict) -> None:
        """营业时段→班次配置"""
        try:
            data = await self._adapter._request(
                "/api/shop/getBizHours",
                {"shopId": self._adapter.shop_id},
            )
            hours = data.get("bizHours", data.get("hours", []))
            if not hours:
                return

            shifts = []
            for h in hours:
                shifts.append({
                    "shift_name": h.get("name", h.get("shiftName", "营业时段")),
                    "start_time": h.get("startTime", h.get("start", "10:00")),
                    "end_time": h.get("endTime", h.get("end", "22:00")),
                    "settlement_cutoff": h.get("settleTime", "02:00"),
                    "is_overnight": bool(h.get("overnight", False)),
                })

            if shifts:
                answers["shifts"] = shifts

        except Exception as exc:
            logger.debug("tiancai_map_shifts_failed", error=str(exc))

    async def _map_discount_policy(self, answers: dict) -> None:
        """折扣授权配置→折扣守护阈值"""
        try:
            data = await self._adapter._request(
                "/api/config/getDiscountConfig",
                {"shopId": self._adapter.shop_id},
            )
            # 天财折扣率通常是 0-100 的百分比，屯象用 0-1
            if emp := data.get("employeeMaxRate", data.get("staffMaxDiscount")):
                rate = float(emp)
                answers["employee_max_discount"] = rate / 100 if rate > 1 else rate
            if mgr := data.get("managerMaxRate", data.get("managerMaxDiscount")):
                rate = float(mgr)
                answers["manager_max_discount"] = rate / 100 if rate > 1 else rate

        except Exception as exc:
            logger.debug("tiancai_map_discount_failed", error=str(exc))

    async def _map_billing_rules(self, answers: dict) -> None:
        """最低消费和服务费"""
        try:
            data = await self._adapter._request(
                "/api/config/getBillingConfig",
                {"shopId": self._adapter.shop_id},
            )
            if mc := data.get("minConsume", data.get("minimumCharge")):
                # 天财最低消费单位为分
                answers["min_spend_yuan"] = int(mc) / 100

            if sfr := data.get("serviceFeeRate", data.get("serviceCharge")):
                rate = float(sfr)
                # 天财服务费率可能是百分比（10）或小数（0.10）
                answers["service_fee_rate"] = rate / 100 if rate > 1 else rate

        except Exception as exc:
            logger.debug("tiancai_map_billing_failed", error=str(exc))

    async def _map_kitchen_zones(self, answers: dict) -> None:
        """厨房分区→KDS分区"""
        try:
            data = await self._adapter._request(
                "/api/kitchen/getKitchenList",
                {"shopId": self._adapter.shop_id},
            )
            kitchens = data.get("kitchenList", data.get("list", []))
            if not kitchens:
                return

            zones = []
            for idx, k in enumerate(kitchens):
                zones.append({
                    "zone_code": str(k.get("code", k.get("kitchenCode", f"zone_{idx}"))),
                    "zone_name": str(k.get("name", k.get("kitchenName", f"档口{idx+1}"))),
                    "display_order": idx,
                    "alert_minutes": int(k.get("alertMinutes", k.get("warnTime", 8))),
                })

            if zones:
                answers["kds_zones"] = zones

        except Exception as exc:
            logger.debug("tiancai_map_kitchen_failed", error=str(exc))

    async def _map_payment_methods(self, answers: dict) -> None:
        """支付方式"""
        try:
            data = await self._adapter._request(
                "/api/config/getPayChannels",
                {"shopId": self._adapter.shop_id},
            )
            channels = data.get("payChannels", data.get("list", []))
            if not channels:
                return

            # 天财支付类型 → 屯象支付方式
            TIANCAI_PAY_MAP = {
                "WEIXIN": "wechat", "WECHAT": "wechat",
                "ALIPAY": "alipay", "ZHIFUBAO": "alipay",
                "CASH": "cash", "XIANJIN": "cash",
                "UNIONPAY": "unionpay", "YINHANGKA": "unionpay",
                "MEMBER": "stored_value", "HUIYUAN": "stored_value",
                "GUAZHANG": "agreement", "CREDIT": "agreement",
            }

            methods = []
            for c in channels:
                tc = str(c.get("type", c.get("payType", ""))).upper()
                mapped = TIANCAI_PAY_MAP.get(tc)
                if mapped and mapped not in methods:
                    methods.append(mapped)

            if methods:
                answers["payment_methods"] = methods

        except Exception as exc:
            logger.debug("tiancai_map_payment_failed", error=str(exc))

    async def _map_member_config(self, answers: dict) -> None:
        """会员积分配置"""
        try:
            data = await self._adapter._request(
                "/api/member/getMemberConfig",
                {"shopId": self._adapter.shop_id},
            )
            if pr := data.get("pointRate", data.get("scoreRate")):
                answers["point_rate"] = float(pr)
            if rr := data.get("redeemRate", data.get("exchangeRate")):
                answers["point_redeem_rate"] = float(rr)

        except Exception as exc:
            logger.debug("tiancai_map_member_config_failed", error=str(exc))

    async def _map_delivery_channels(self, answers: dict) -> None:
        """外卖平台开通情况"""
        try:
            data = await self._adapter._request(
                "/api/delivery/getChannels",
                {"shopId": self._adapter.shop_id},
            )
            platforms = data.get("platforms", data.get("channels", []))
            if not platforms:
                return

            TIANCAI_CHANNEL_MAP = {
                "MEITUAN": "meituan", "MT": "meituan",
                "ELEME": "eleme", "ELM": "eleme",
                "DOUYIN": "douyin", "TK": "douyin",
            }

            channels = []
            for p in platforms:
                ptype = str(p.get("type", p.get("platform", ""))).upper()
                mapped = TIANCAI_CHANNEL_MAP.get(ptype)
                if mapped and mapped not in channels:
                    channels.append(mapped)

            if channels:
                answers["channels_enabled"] = channels

        except Exception as exc:
            logger.debug("tiancai_map_delivery_failed", error=str(exc))

    def _infer_restaurant_type(self, answers: dict) -> None:
        """
        根据已收集的配置信息推断业态类型。
        优先使用显式的业态标识，否则从厨房分区/菜品数量等特征推断。
        """
        if "restaurant_type" in answers:
            return  # 已有值，不覆写

        kds_zones = answers.get("kds_zones", [])
        zone_names = " ".join(z.get("zone_name", "") for z in kds_zones).lower()
        store_name = answers.get("store_name", "").lower()

        # 简单规则推断（后续可升级为 ML 分类）
        if any(kw in store_name for kw in ["海鲜", "宴", "酒楼", "酒家", "大酒店"]):
            answers["restaurant_type"] = "banquet"
        elif any(kw in store_name for kw in ["火锅", "串串", "烤肉", "麻辣烫"]):
            answers["restaurant_type"] = "hot_pot"
        elif any(kw in store_name for kw in ["奶茶", "咖啡", "饮品", "茶饮"]):
            answers["restaurant_type"] = "cafe_tea"
        elif any(kw in store_name for kw in ["快餐", "档口", "盖饭", "米粉"]):
            answers["restaurant_type"] = "fast_food"
        elif "海鲜" in zone_names or "宴" in zone_names:
            answers["restaurant_type"] = "banquet"
        else:
            # 默认正餐
            answers["restaurant_type"] = "casual_dining"


# ── 完整迁移流程入口 ──────────────────────────────────────────────────


async def run_tiancai_migration(
    adapter,
    tenant_id: str,
    brand_id: str,
    dry_run: bool = False,
) -> dict:
    """
    天财商龙完整迁移流程入口函数。

    执行顺序：
      1. 配置映射 → 生成 prefilled_answers
      2. 菜品迁移 → UPSERT dishes
      3. 会员迁移 → 自动迁移零余额 + 写入待审核队列

    返回迁移摘要，供 MigrationDashboard 展示。
    """
    from shared.adapters.tiancai_shanglong.src.menu_sync import TiancaiMenuSync
    from shared.adapters.tiancai_shanglong.src.member_sync import TiancaiMemberSync

    summary: dict = {
        "tenant_id": tenant_id,
        "dry_run": dry_run,
        "steps": {},
    }

    # Step 1: 配置映射
    mapper = TiancaiConfigMapper(adapter)
    prefilled = await mapper.extract_prefilled_answers()
    summary["steps"]["config_mapping"] = {
        "prefilled_keys": list(prefilled.keys()),
        "prefilled_count": len(prefilled),
        "remaining_questions": max(0, 20 - len(prefilled)),
    }

    # Step 2: 菜品迁移
    menu_sync = TiancaiMenuSync(adapter)
    menu_result = await menu_sync.pull_and_upsert(tenant_id, brand_id, dry_run=dry_run)
    summary["steps"]["menu_migration"] = {
        "total_fetched": menu_result.total_fetched,
        "upserted": menu_result.total_upserted,
        "errors": len(menu_result.errors),
        "success_rate": round(menu_result.success_rate * 100, 1),
    }

    # Step 3: 会员迁移
    member_sync = TiancaiMemberSync(adapter)
    member_result = await member_sync.pull_and_migrate(tenant_id, dry_run=dry_run)
    summary["steps"]["member_migration"] = {
        "total_fetched": member_result.total_fetched,
        "auto_migrated": member_result.auto_migrated,
        "pending_review": member_result.pending_review,
        "pending_balance_yuan": member_result._pending_balance_fen / 100,
        "errors": len(member_result.errors),
    }

    summary["prefilled_answers"] = prefilled
    summary["next_step"] = (
        f"POST /api/v1/onboarding/start  body: "
        f'{{\"tenant_id\": \"{tenant_id}\", '
        f'\"migration_source\": \"tiancai\", '
        f'\"prefilled_answers\": <见 prefilled_answers>}}'
    )

    return summary
