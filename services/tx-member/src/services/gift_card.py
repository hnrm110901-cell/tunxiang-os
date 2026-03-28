"""礼品卡服务 — 定额制卡 + 批量激活 + 售卖 + 使用 + 余额查询

礼品卡面值单位：分（fen）。
卡密码：6位随机数字。
"""
import uuid
import random
import string
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()


# ─── 内存存储 ───


class _CardTypeStore:
    """礼品卡类型存储"""
    _types: dict[str, dict] = {}

    @classmethod
    def save(cls, type_id: str, data: dict) -> None:
        cls._types[type_id] = data

    @classmethod
    def get(cls, type_id: str) -> Optional[dict]:
        return cls._types.get(type_id)

    @classmethod
    def list_by_tenant(cls, tenant_id: str) -> list[dict]:
        return [t for t in cls._types.values() if t.get("tenant_id") == tenant_id]

    @classmethod
    def clear(cls) -> None:
        cls._types.clear()


class _CardStore:
    """礼品卡实例存储"""
    _cards: dict[str, dict] = {}
    _card_no_index: dict[str, str] = {}  # card_no -> card_id

    @classmethod
    def save(cls, card_id: str, data: dict) -> None:
        cls._cards[card_id] = data
        cls._card_no_index[data["card_no"]] = card_id

    @classmethod
    def get(cls, card_id: str) -> Optional[dict]:
        return cls._cards.get(card_id)

    @classmethod
    def get_by_no(cls, card_no: str) -> Optional[dict]:
        card_id = cls._card_no_index.get(card_no)
        if card_id:
            return cls._cards.get(card_id)
        return None

    @classmethod
    def list_by_type(cls, type_id: str) -> list[dict]:
        return [c for c in cls._cards.values() if c.get("type_id") == type_id]

    @classmethod
    def list_by_tenant(cls, tenant_id: str) -> list[dict]:
        return [c for c in cls._cards.values() if c.get("tenant_id") == tenant_id]

    @classmethod
    def clear(cls) -> None:
        cls._cards.clear()
        cls._card_no_index.clear()


class _OnlineConfigStore:
    """线上售卖配置存储"""
    _configs: dict[str, dict] = {}

    @classmethod
    def save(cls, type_id: str, data: dict) -> None:
        cls._configs[type_id] = data

    @classmethod
    def get(cls, type_id: str) -> Optional[dict]:
        return cls._configs.get(type_id)

    @classmethod
    def clear(cls) -> None:
        cls._configs.clear()


def _generate_card_no() -> str:
    """生成16位礼品卡号"""
    return "".join(random.choices(string.digits, k=16))


def _generate_password() -> str:
    """生成6位随机数字密码"""
    return "".join(random.choices(string.digits, k=6))


# ─── 创建礼品卡类型 ───


async def create_gift_card_type(
    name: str,
    face_value_fen: int,
    tenant_id: str,
    db=None,
) -> dict:
    """创建定额礼品卡类型"""
    if face_value_fen <= 0:
        raise ValueError("面值必须大于0")

    type_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    card_type = {
        "type_id": type_id,
        "name": name,
        "face_value_fen": face_value_fen,
        "tenant_id": tenant_id,
        "total_created": 0,
        "total_activated": 0,
        "total_sold": 0,
        "status": "active",
        "created_at": now,
    }

    _CardTypeStore.save(type_id, card_type)

    logger.info(
        "gift_card_type_created",
        type_id=type_id,
        name=name,
        face_value_fen=face_value_fen,
        tenant_id=tenant_id,
    )
    return card_type


# ─── 批量制卡 ───


async def batch_create_cards(
    type_id: str,
    count: int,
    tenant_id: str,
    db=None,
) -> dict:
    """批量制卡（生成卡号+密码）"""
    if count <= 0:
        raise ValueError("制卡数量必须大于0")
    if count > 10000:
        raise ValueError("单次制卡数量不能超过10000")

    card_type = _CardTypeStore.get(type_id)
    if not card_type:
        raise ValueError(f"礼品卡类型不存在: {type_id}")
    if card_type["tenant_id"] != tenant_id:
        raise ValueError("租户不匹配")

    now = datetime.now(timezone.utc).isoformat()
    cards: list[dict] = []
    existing_nos: set[str] = {c.get("card_no") for c in _CardStore.list_by_tenant(tenant_id)}

    for _ in range(count):
        card_id = str(uuid.uuid4())
        card_no = _generate_card_no()
        while card_no in existing_nos:
            card_no = _generate_card_no()
        existing_nos.add(card_no)

        password = _generate_password()

        card = {
            "card_id": card_id,
            "card_no": card_no,
            "password": password,
            "type_id": type_id,
            "tenant_id": tenant_id,
            "face_value_fen": card_type["face_value_fen"],
            "balance_fen": card_type["face_value_fen"],
            "status": "created",  # created -> activated -> sold -> used/exhausted
            "buyer_info": None,
            "activated_at": None,
            "sold_at": None,
            "created_at": now,
            "transactions": [],
        }
        _CardStore.save(card_id, card)
        cards.append({
            "card_id": card_id,
            "card_no": card_no,
            "password": password,
        })

    card_type["total_created"] += count
    _CardTypeStore.save(type_id, card_type)

    logger.info(
        "gift_cards_batch_created",
        type_id=type_id,
        count=count,
        tenant_id=tenant_id,
    )
    return {
        "type_id": type_id,
        "created_count": count,
        "cards": cards,
    }


# ─── 批量激活 ───


async def activate_cards(
    card_ids: list[str],
    tenant_id: str,
    db=None,
) -> dict:
    """批量激活礼品卡"""
    now = datetime.now(timezone.utc).isoformat()
    activated = []
    errors = []

    for card_id in card_ids:
        card = _CardStore.get(card_id)
        if not card:
            errors.append({"card_id": card_id, "reason": "卡不存在"})
            continue
        if card["tenant_id"] != tenant_id:
            errors.append({"card_id": card_id, "reason": "租户不匹配"})
            continue
        if card["status"] != "created":
            errors.append({"card_id": card_id, "reason": f"状态异常: {card['status']}"})
            continue

        card["status"] = "activated"
        card["activated_at"] = now
        _CardStore.save(card_id, card)
        activated.append(card_id)

        # 更新类型统计
        card_type = _CardTypeStore.get(card["type_id"])
        if card_type:
            card_type["total_activated"] = card_type.get("total_activated", 0) + 1
            _CardTypeStore.save(card["type_id"], card_type)

    logger.info(
        "gift_cards_activated",
        activated_count=len(activated),
        error_count=len(errors),
        tenant_id=tenant_id,
    )
    return {
        "activated_count": len(activated),
        "activated": activated,
        "errors": errors,
    }


# ─── 售卖 ───


async def sell_card(
    card_id: str,
    buyer_info: dict,
    tenant_id: str,
    db=None,
) -> dict:
    """售卖礼品卡

    buyer_info: {"name": str, "phone": str, "payment_method": str}
    """
    card = _CardStore.get(card_id)
    if not card:
        raise ValueError(f"礼品卡不存在: {card_id}")
    if card["tenant_id"] != tenant_id:
        raise ValueError("租户不匹配")
    if card["status"] != "activated":
        raise ValueError(f"礼品卡状态异常: {card['status']}（需先激活）")

    now = datetime.now(timezone.utc).isoformat()
    card["status"] = "sold"
    card["buyer_info"] = buyer_info
    card["sold_at"] = now
    _CardStore.save(card_id, card)

    # 更新类型统计
    card_type = _CardTypeStore.get(card["type_id"])
    if card_type:
        card_type["total_sold"] = card_type.get("total_sold", 0) + 1
        _CardTypeStore.save(card["type_id"], card_type)

    logger.info(
        "gift_card_sold",
        card_id=card_id,
        card_no=card["card_no"],
        face_value_fen=card["face_value_fen"],
        buyer_name=buyer_info.get("name"),
        tenant_id=tenant_id,
    )
    return {
        "card_id": card_id,
        "card_no": card["card_no"],
        "face_value_fen": card["face_value_fen"],
        "buyer_info": buyer_info,
        "sold_at": now,
    }


# ─── 使用礼品卡 ───


async def use_card(
    card_no: str,
    password: str,
    order_id: str,
    amount_fen: int,
    tenant_id: str,
    db=None,
) -> dict:
    """使用礼品卡支付

    支持部分使用，余额可多次消费。
    """
    card = _CardStore.get_by_no(card_no)
    if not card:
        raise ValueError(f"礼品卡不存在: {card_no}")
    if card["tenant_id"] != tenant_id:
        raise ValueError("租户不匹配")
    if card["password"] != password:
        raise ValueError("密码错误")
    if card["status"] not in ("sold", "activated"):
        raise ValueError(f"礼品卡状态异常: {card['status']}")
    if amount_fen <= 0:
        raise ValueError("使用金额必须大于0")
    if card["balance_fen"] < amount_fen:
        raise ValueError(
            f"余额不足: 当前{card['balance_fen']}分, 需扣{amount_fen}分"
        )

    now = datetime.now(timezone.utc).isoformat()
    card["balance_fen"] -= amount_fen

    if card["balance_fen"] == 0:
        card["status"] = "exhausted"

    card["transactions"].append({
        "type": "consume",
        "amount_fen": -amount_fen,
        "order_id": order_id,
        "balance_after_fen": card["balance_fen"],
        "at": now,
    })
    _CardStore.save(card["card_id"], card)

    logger.info(
        "gift_card_used",
        card_no=card_no,
        amount_fen=amount_fen,
        remaining_fen=card["balance_fen"],
        order_id=order_id,
        tenant_id=tenant_id,
    )
    return {
        "card_no": card_no,
        "deducted_fen": amount_fen,
        "balance_fen": card["balance_fen"],
        "order_id": order_id,
        "status": card["status"],
    }


# ─── 查余额 ───


async def get_card_balance(
    card_no: str,
    tenant_id: str,
    db=None,
) -> dict:
    """查询礼品卡余额"""
    card = _CardStore.get_by_no(card_no)
    if not card:
        raise ValueError(f"礼品卡不存在: {card_no}")
    if card["tenant_id"] != tenant_id:
        raise ValueError("租户不匹配")

    logger.info(
        "gift_card_balance_queried",
        card_no=card_no,
        balance_fen=card["balance_fen"],
        tenant_id=tenant_id,
    )
    return {
        "card_no": card_no,
        "face_value_fen": card["face_value_fen"],
        "balance_fen": card["balance_fen"],
        "status": card["status"],
        "transactions": card["transactions"],
    }


# ─── 线上售卖配置 ───


async def online_purchase_config(
    type_id: str,
    theme: dict,
    tenant_id: str,
    db=None,
) -> dict:
    """线上售卖配置

    theme: {"title": str, "cover_image": str, "description": str, "greeting_template": str}
    """
    card_type = _CardTypeStore.get(type_id)
    if not card_type:
        raise ValueError(f"礼品卡类型不存在: {type_id}")
    if card_type["tenant_id"] != tenant_id:
        raise ValueError("租户不匹配")

    now = datetime.now(timezone.utc).isoformat()
    config = {
        "type_id": type_id,
        "tenant_id": tenant_id,
        "face_value_fen": card_type["face_value_fen"],
        "theme": {
            "title": theme.get("title", card_type["name"]),
            "cover_image": theme.get("cover_image", ""),
            "description": theme.get("description", ""),
            "greeting_template": theme.get("greeting_template", "祝您用餐愉快！"),
        },
        "enabled": True,
        "updated_at": now,
    }
    _OnlineConfigStore.save(type_id, config)

    logger.info(
        "online_purchase_config_set",
        type_id=type_id,
        theme_title=config["theme"]["title"],
        tenant_id=tenant_id,
    )
    return config
