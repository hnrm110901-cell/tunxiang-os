"""
品智会员同步模块
拉取品智会员数据并映射为屯象 Customer Golden ID 格式
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()


class PinzhiMemberSync:
    """品智会员同步器"""

    def __init__(self, adapter):
        """
        Args:
            adapter: PinzhiAdapter 实例
        """
        self.adapter = adapter

    async def fetch_members(self, store_id: str, page: int = 1) -> list[dict]:
        """
        从品智拉取指定门店的会员列表。

        品智挂账客户接口 paymentCustomer.do 返回会员/客户数据，
        自动翻页直至数据取完。

        Args:
            store_id: 门店 ognid
            page: 起始页码

        Returns:
            品智原始会员列表
        """
        all_members: list[dict] = []
        params = {"ognid": store_id}
        params = self.adapter._add_sign(params)

        # 品智会员接口目前不支持分页，一次返回全部
        # 但保留 page 参数以备后续扩展
        try:
            response = await self.adapter._request("GET", "/pinzhi/paymentCustomer.do", params=params)
            members = response.get("data", [])
            all_members.extend(members)
        except (ConnectionError, TimeoutError) as exc:
            logger.error("pinzhi_member_fetch_failed", store_id=store_id, error=str(exc))

        logger.info(
            "pinzhi_members_fetched",
            store_id=store_id,
            count=len(all_members),
        )
        return all_members

    @staticmethod
    def map_to_golden_id(pinzhi_member: dict) -> dict:
        """
        将品智会员映射为屯象 Customer Golden ID 格式（纯函数）。

        Golden ID 是屯象全渠道统一客户标识，整合品智会员卡号、
        手机号、微信 openid 等多个身份标识。

        金额单位统一为分(fen)。

        Args:
            pinzhi_member: 品智原始会员字典

        Returns:
            屯象 Customer Golden ID 字典
        """
        # 身份标识集合
        identities = []

        phone = pinzhi_member.get("phone", pinzhi_member.get("mobile"))
        if phone:
            identities.append({"type": "phone", "value": str(phone)})

        card_no = pinzhi_member.get("cardNo", pinzhi_member.get("vipCard"))
        if card_no:
            identities.append({"type": "pinzhi_card", "value": str(card_no)})

        wechat_id = pinzhi_member.get("wechatOpenId", pinzhi_member.get("openId"))
        if wechat_id:
            identities.append({"type": "wechat_openid", "value": str(wechat_id)})

        # 会员等级
        level_map = {0: "normal", 1: "silver", 2: "gold", 3: "platinum", 4: "diamond"}
        raw_level = pinzhi_member.get("vipLevel", pinzhi_member.get("memberLevel", 0))

        # 余额/储值（分）
        balance_fen = int(pinzhi_member.get("balance", pinzhi_member.get("storedValue", 0)))
        points = int(pinzhi_member.get("points", pinzhi_member.get("integral", 0)))

        return {
            "golden_id": None,  # 由屯象系统分配，此处占位
            "name": str(pinzhi_member.get("name", pinzhi_member.get("customerName", ""))),
            "gender": pinzhi_member.get("sex", pinzhi_member.get("gender")),
            "birthday": pinzhi_member.get("birthday"),
            "identities": identities,
            "level": level_map.get(raw_level, "normal"),
            "balance_fen": balance_fen,
            "points": points,
            "total_consumption_fen": int(pinzhi_member.get("totalConsume", pinzhi_member.get("consumeAmount", 0))),
            "visit_count": int(pinzhi_member.get("visitCount", pinzhi_member.get("consumeCount", 0))),
            "last_visit_date": pinzhi_member.get("lastConsumeDate"),
            "created_at": pinzhi_member.get("createTime", pinzhi_member.get("regTime")),
            "source_system": "pinzhi",
            "source_id": str(pinzhi_member.get("customerId", pinzhi_member.get("id", ""))),
        }

    @staticmethod
    def merge_identity(existing: dict, incoming: dict) -> dict:
        """
        合并两个 Golden ID 记录的身份信息（纯函数）。

        合并规则：
        1. identities 列表按 (type, value) 去重合并
        2. 数值字段取较大值（消费、积分等累加型指标）
        3. 基本信息字段以 incoming 为准（如有值则覆盖）
        4. last_visit_date 取较近日期

        Args:
            existing: 已有的 Golden ID 记录
            incoming: 新传入的记录

        Returns:
            合并后的 Golden ID 字典
        """
        merged = {**existing}

        # 合并身份标识（去重）
        existing_ids = {(ident["type"], ident["value"]) for ident in existing.get("identities", [])}
        merged_identities = list(existing.get("identities", []))
        for ident in incoming.get("identities", []):
            key = (ident["type"], ident["value"])
            if key not in existing_ids:
                merged_identities.append(ident)
                existing_ids.add(key)
        merged["identities"] = merged_identities

        # 基本信息：incoming 非空则覆盖
        for field in ("name", "gender", "birthday", "level"):
            incoming_val = incoming.get(field)
            if incoming_val is not None and incoming_val != "":
                merged[field] = incoming_val

        # 数值字段取较大值
        for field in ("balance_fen", "points", "total_consumption_fen", "visit_count"):
            merged[field] = max(
                existing.get(field, 0),
                incoming.get(field, 0),
            )

        # last_visit_date 取较近日期
        existing_date = existing.get("last_visit_date") or ""
        incoming_date = incoming.get("last_visit_date") or ""
        merged["last_visit_date"] = max(existing_date, incoming_date) or None

        return merged

    async def sync_members(self, store_id: str) -> dict:
        """
        完整同步流程：拉取 + 映射 + 返回统计。

        Args:
            store_id: 门店 ognid

        Returns:
            同步统计 {"total": int, "success": int, "failed": int, "members": list}
        """
        raw_members = await self.fetch_members(store_id)

        mapped: list[dict] = []
        failed = 0
        for raw in raw_members:
            try:
                mapped.append(self.map_to_golden_id(raw))
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning(
                    "member_mapping_failed",
                    member_id=raw.get("customerId", raw.get("id")),
                    error=str(exc),
                )
                failed += 1

        logger.info(
            "pinzhi_members_synced",
            store_id=store_id,
            total=len(raw_members),
            success=len(mapped),
            failed=failed,
        )

        return {
            "total": len(raw_members),
            "success": len(mapped),
            "failed": failed,
            "members": mapped,
        }
