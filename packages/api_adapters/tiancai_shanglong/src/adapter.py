"""
天财商龙 POS 系统 API 适配器（可 import 版）

本文件是 packages/api-adapters/tiancai-shanglong/src/adapter.py 的
可 Python import 版本（因 api-adapters 含连字符，Python 无法直接导入）。

相比原版变更：
  1. 构造函数同时支持 dict config 和 keyword args 两种调用方式
  2. pull_daily_orders 新增 target_date / store_id 关键字参数，
     兼容 pull_historical_backfill 的调用约定
  3. to_order() 返回 OrderSchema 同时暴露两套字段名，消除 celery
     任务中的字段不一致问题
  4. 去除 sys.path 注入，改用本模块自定义的轻量级 schema

认证方式：MD5 签名 + 请求头（X-App-Id / X-Timestamp / X-Sign）
API 响应格式：{"code": 0, "message": "ok", "data": {...}}
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import httpx
import structlog

logger = structlog.get_logger()


# ── 枚举 ──────────────────────────────────────────────────────────────────────

class OrderStatus(str, Enum):
    PENDING   = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REFUNDED  = "refunded"


class OrderType(str, Enum):
    DINE_IN  = "dine_in"
    TAKEAWAY = "takeaway"
    PICKUP   = "pickup"


# ── 轻量级 Schema ─────────────────────────────────────────────────────────────

class _Base:
    """极简 dataclass 替代：允许任意关键字参数初始化。"""
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class OrderItemSchema(_Base):
    """订单明细行。"""
    item_id: str
    dish_id: str
    dish_name: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal
    special_requirements: Optional[str] = None


class StaffAction(_Base):
    """员工操作记录。"""
    action_type: str
    brand_id: str
    store_id: str
    operator_id: str
    amount: Optional[Decimal]
    reason: Optional[str]
    approved_by: Optional[str]
    created_at: datetime


class OrderSchema(_Base):
    """
    天财商龙订单标准结构。

    同时支持两套字段名，消除 celery 任务的访问不一致问题：
    - pull_tiancai_daily_orders 使用：
        order_id / total / discount / table_number /
        order_status / created_at / waiter_id / notes
    - pull_historical_backfill 使用：
        order_id / total_amount / discount_amount / paid_amount /
        table_no / status / order_time
    """

    # ── 核心字段 ──
    order_id: str
    order_number: str
    order_type: OrderType
    order_status: OrderStatus
    store_id: str
    brand_id: str
    table_number: Optional[str]
    customer_id: Optional[str]
    items: List[OrderItemSchema]
    subtotal: Decimal
    discount: Decimal
    service_charge: Decimal
    total: Decimal
    created_at: datetime
    waiter_id: Optional[str]
    notes: Optional[str]

    # ── 别名属性（历史回灌调用方期望的字段名）──

    @property
    def table_no(self) -> Optional[str]:
        return self.table_number

    @property
    def status(self) -> str:
        return self.order_status.value if isinstance(self.order_status, OrderStatus) else str(self.order_status)

    @property
    def total_amount(self) -> Decimal:
        return self.total

    @property
    def discount_amount(self) -> Decimal:
        return self.discount

    @property
    def paid_amount(self) -> Decimal:
        return self.total

    @property
    def order_time(self) -> str:
        if isinstance(self.created_at, datetime):
            return self.created_at.strftime("%Y-%m-%d %H:%M:%S")
        return str(self.created_at)


# ── 主适配器类 ────────────────────────────────────────────────────────────────

class TiancaiShanglongAdapter:
    """
    天财商龙 POS 系统适配器。

    构造方式（两种均支持）：
      # 方式一：dict config（原始约定）
      TiancaiShanglongAdapter({
          "base_url": "https://api.tiancai.com",
          "app_id": "xxx", "app_secret": "yyy",
          "store_id": "S001", "timeout": 30,
      })
      # 方式二：keyword args（onboarding 回灌约定）
      TiancaiShanglongAdapter(
          base_url="https://api.tiancai.com",
          app_id="xxx", app_secret="yyy", brand_id="B001",
      )
    """

    def __init__(
        self,
        config_or_base_url: Union[Dict[str, Any], str, None] = None,
        *,
        base_url: str = "",
        app_id: str = "",
        app_secret: str = "",
        brand_id: str = "",
        store_id: str = "",
        timeout: int = 30,
        retry_times: int = 3,
    ) -> None:
        if isinstance(config_or_base_url, dict):
            cfg = config_or_base_url
            self.base_url    = cfg.get("base_url", "https://api.tiancai.com")
            self.app_id      = cfg.get("app_id", app_id)
            self.app_secret  = cfg.get("app_secret", app_secret)
            self.brand_id    = cfg.get("brand_id", brand_id)
            self.store_id    = cfg.get("store_id", store_id)
            self.timeout     = int(cfg.get("timeout", timeout))
            self.retry_times = int(cfg.get("retry_times", retry_times))
        else:
            self.base_url    = (config_or_base_url or base_url or "https://api.tiancai.com").rstrip("/")
            self.app_id      = app_id
            self.app_secret  = app_secret
            self.brand_id    = brand_id
            self.store_id    = store_id
            self.timeout     = timeout
            self.retry_times = retry_times

        self.base_url = self.base_url.rstrip("/")

        if not self.app_id or not self.app_secret:
            raise ValueError("app_id和app_secret不能为空")

        # 短连接模式：每次请求新建 client（与原版保持兼容）
        logger.info(
            "TiancaiShanglongAdapter.init",
            base_url=self.base_url,
            store_id=self.store_id,
        )

    # ── 签名 & 认证 ───────────────────────────────────────────────────────────

    def _generate_sign(self, params: Dict[str, Any], timestamp: str) -> str:
        """
        MD5 签名（与原 api-adapters 版本一致）：
          sign = MD5(app_id=X&k1=v1&...&timestamp=T&app_secret=S).upper()
        """
        sorted_params = sorted(params.items())
        sign_str = f"app_id={self.app_id}&"
        sign_str += "&".join(f"{k}={v}" for k, v in sorted_params)
        sign_str += f"&timestamp={timestamp}&app_secret={self.app_secret}"
        return hashlib.md5(sign_str.encode()).hexdigest().upper()

    def _auth_headers(self, params: Dict[str, Any]) -> Dict[str, str]:
        timestamp = str(int(datetime.now().timestamp()))
        sign = self._generate_sign(params, timestamp)
        return {
            "Content-Type": "application/json",
            "X-App-Id":     self.app_id,
            "X-Timestamp":  timestamp,
            "X-Sign":       sign,
        }

    def handle_error(self, response: Dict[str, Any]) -> None:
        code = response.get("code", 0)
        if code not in (0, 200):
            raise Exception(f"天财商龙API错误 [{code}]: {response.get('message', '未知错误')}")

    # ── HTTP 基础 ─────────────────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """发送 HTTP 请求（含重试）。"""
        request_data = data or {}
        for attempt in range(self.retry_times):
            try:
                headers = self._auth_headers(request_data)
                async with httpx.AsyncClient(
                    base_url=self.base_url,
                    timeout=float(self.timeout),
                    follow_redirects=True,
                ) as client:
                    if method.upper() == "GET":
                        resp = await client.get(endpoint, params=request_data, headers=headers)
                    elif method.upper() == "POST":
                        resp = await client.post(endpoint, json=request_data, headers=headers)
                    else:
                        raise ValueError(f"不支持的HTTP方法: {method}")

                resp.raise_for_status()
                result = resp.json()
                self.handle_error(result)
                return result

            except httpx.HTTPStatusError as exc:
                logger.error("tiancai.http_error", endpoint=endpoint,
                             status=exc.response.status_code, attempt=attempt + 1)
                if attempt == self.retry_times - 1:
                    raise Exception(f"HTTP请求失败: {exc.response.status_code}") from exc
            except Exception as exc:
                logger.error("tiancai.request_error", endpoint=endpoint,
                             error=str(exc), attempt=attempt + 1)
                if attempt == self.retry_times - 1:
                    raise

        raise Exception("请求失败，已达到最大重试次数")

    # ── 低层分页拉取 ──────────────────────────────────────────────────────────

    async def fetch_orders_by_date(
        self,
        date_str: str,
        page: int = 1,
        page_size: int = 100,
        status: Optional[int] = None,
    ) -> Dict[str, Any]:
        """分页拉取指定日期订单。"""
        data: Dict[str, Any] = {
            "store_id":   self.store_id,
            "start_time": f"{date_str} 00:00:00",
            "end_time":   f"{date_str} 23:59:59",
            "page":       page,
            "page_size":  page_size,
        }
        if status is not None:
            data["status"] = status

        response = await self._request("POST", "/api/order/list", data=data)
        raw_data = response.get("data", {})
        raw_items = raw_data.get("list", raw_data.get("orders", []))
        total = int(raw_data.get("total", len(raw_items)))

        return {
            "items":     raw_items,
            "page":      page,
            "page_size": page_size,
            "total":     total,
            "has_more":  page * page_size < total,
        }

    async def fetch_dishes(
        self,
        page: int = 1,
        page_size: int = 100,
        category_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """分页拉取菜品列表。"""
        data: Dict[str, Any] = {
            "store_id":  self.store_id,
            "page":      page,
            "page_size": page_size,
        }
        if category_id:
            data["category_id"] = category_id

        response = await self._request("POST", "/api/dish/list", data=data)
        raw_data = response.get("data", {})
        raw_items = raw_data.get("list", raw_data.get("items", []))
        total = int(raw_data.get("total", len(raw_items)))

        return {
            "items":     [self.to_dish(item) for item in raw_items],
            "page":      page,
            "page_size": page_size,
            "total":     total,
            "has_more":  page * page_size < total,
        }

    async def fetch_inventory(
        self,
        page: int = 1,
        page_size: int = 200,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """分页拉取库存/原料列表。"""
        data: Dict[str, Any] = {
            "store_id":  self.store_id,
            "page":      page,
            "page_size": page_size,
        }
        if category:
            data["category"] = category

        response = await self._request("POST", "/api/inventory/list", data=data)
        raw_data = response.get("data", {})
        raw_items = raw_data.get("list", raw_data.get("materials", []))
        total = int(raw_data.get("total", len(raw_items)))

        return {
            "items":     [self.to_inventory_item(item) for item in raw_items],
            "page":      page,
            "page_size": page_size,
            "total":     total,
            "has_more":  page * page_size < total,
        }

    # ── 高层全量拉取（自动分页） ──────────────────────────────────────────────

    async def pull_daily_orders(
        self,
        target_date: Optional[str] = None,
        brand_id: Optional[str] = None,
        *,
        store_id: Optional[str] = None,
        status: int = 2,
        max_pages: int = 50,
    ) -> List[OrderSchema]:
        """
        拉取指定日期全量已支付订单（自动翻页）。

        兼容两种调用约定：
          pull_daily_orders("2026-03-06", "BRAND001")       # 按位置
          pull_daily_orders(store_id="S1", target_date="2026-03-06")  # 关键字
        """
        if target_date is None:
            raise ValueError("target_date 不能为空")

        effective_store = store_id or self.store_id
        effective_brand = brand_id or self.brand_id

        # 临时切换 store_id 以支持 store_id 关键字参数
        original_store = self.store_id
        if effective_store:
            self.store_id = effective_store

        all_orders: List[OrderSchema] = []
        page = 1
        try:
            while page <= max_pages:
                result = await self.fetch_orders_by_date(
                    date_str=target_date,
                    page=page,
                    page_size=100,
                    status=status,
                )
                for raw in result["items"]:
                    try:
                        all_orders.append(self.to_order(raw, effective_store, effective_brand))
                    except Exception as exc:
                        logger.warning(
                            "tiancai.order_map_failed",
                            order_id=raw.get("order_id"),
                            error=str(exc),
                        )

                if not result["has_more"]:
                    break
                page += 1
        finally:
            self.store_id = original_store

        logger.info(
            "tiancai.pull_daily_orders.done",
            date=target_date,
            store_id=effective_store,
            total=len(all_orders),
        )
        return all_orders

    async def pull_all_dishes(self, max_pages: int = 20) -> List[Dict[str, Any]]:
        """全量菜品（自动翻页）。"""
        all_dishes: List[Dict[str, Any]] = []
        page = 1
        while page <= max_pages:
            result = await self.fetch_dishes(page=page, page_size=100)
            all_dishes.extend(result["items"])
            if not result["has_more"]:
                break
            page += 1
        logger.info("tiancai.pull_all_dishes.done", total=len(all_dishes))
        return all_dishes

    async def pull_all_inventory(self, max_pages: int = 20) -> List[Dict[str, Any]]:
        """全量库存原料（自动翻页）。"""
        all_items: List[Dict[str, Any]] = []
        page = 1
        while page <= max_pages:
            result = await self.fetch_inventory(page=page, page_size=200)
            all_items.extend(result["items"])
            if not result["has_more"]:
                break
            page += 1
        logger.info("tiancai.pull_all_inventory.done", total=len(all_items))
        return all_items

    # ── 原有单条查询 & 写入方法 ───────────────────────────────────────────────

    async def query_order(
        self,
        order_id: Optional[str] = None,
        order_no: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """按订单 ID/单号查询，返回原始 dict（供 AdapterIntegrationService 使用）。"""
        data: Dict[str, Any] = {"store_id": self.store_id}
        if order_id:   data["order_id"]   = order_id
        if order_no:   data["order_no"]   = order_no
        if start_time: data["start_time"] = start_time
        if end_time:   data["end_time"]   = end_time

        response = await self._request("POST", "/api/order/query", data=data)
        return response.get("data", {})

    async def query_dish(
        self,
        dish_id: Optional[str] = None,
        category_id: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """查询菜品列表，返回原始 list（供 AdapterIntegrationService 使用）。"""
        data: Dict[str, Any] = {"store_id": self.store_id}
        if dish_id:     data["dish_id"]     = dish_id
        if category_id: data["category_id"] = category_id
        if keyword:     data["keyword"]     = keyword

        response = await self._request("POST", "/api/dish/query", data=data)
        return response.get("data", [])

    async def update_inventory(
        self,
        material_id: str,
        quantity: float,
        operation_type: int = 1,
    ) -> Dict[str, Any]:
        """
        更新原料库存。
        operation_type: 1=入库  2=出库  3=盘点
        """
        data = {
            "store_id":       self.store_id,
            "material_id":    material_id,
            "quantity":       quantity,
            "operation_type": operation_type,
        }
        response = await self._request("POST", "/api/inventory/update", data=data)
        logger.info("tiancai.update_inventory.done",
                    material_id=material_id, quantity=quantity, op=operation_type)
        return response.get("data", {})

    async def fetch_store_info(self) -> Dict[str, Any]:
        """拉取门店基础信息。"""
        response = await self._request("POST", "/api/store/info", data={"store_id": self.store_id})
        return self._normalize_store(response.get("data", {}))

    async def close(self) -> None:
        """释放资源（短连接模式，无需操作）。"""

    # ── 数据映射 ──────────────────────────────────────────────────────────────

    def to_order(self, raw: Dict[str, Any], store_id: str, brand_id: str) -> OrderSchema:
        """
        天财商龙原始订单 → OrderSchema。

        天财商龙订单字段：
          order_id, order_no, store_id, table_no, status (1/2/3),
          pay_amount (分), discount_amount (分), create_time,
          dishes[dish_id, dish_name, quantity, price(分)],
          member_id, waiter_id, remark
        """
        _STATUS_MAP = {
            1: OrderStatus.PENDING,
            2: OrderStatus.COMPLETED,
            3: OrderStatus.CANCELLED,
            4: OrderStatus.REFUNDED,
            5: OrderStatus.COMPLETED,
        }
        order_status = _STATUS_MAP.get(int(raw.get("status", 2)), OrderStatus.COMPLETED)

        items = []
        for idx, item in enumerate(raw.get("dishes", raw.get("items", [])), start=1):
            unit_price = Decimal(str(item.get("price", 0))) / 100
            qty = int(item.get("quantity", item.get("qty", 1)))
            items.append(OrderItemSchema(
                item_id=str(item.get("item_id", f"{raw.get('order_id', '')}_{idx}")),
                dish_id=str(item.get("dish_id", item.get("good_id", ""))),
                dish_name=str(item.get("dish_name", item.get("good_name", ""))),
                quantity=qty,
                unit_price=unit_price,
                subtotal=unit_price * qty,
                special_requirements=item.get("remark"),
            ))

        total    = Decimal(str(raw.get("pay_amount", raw.get("total_amount", 0)))) / 100
        discount = Decimal(str(raw.get("discount_amount", 0))) / 100
        subtotal = total + discount

        create_time_raw = raw.get("create_time", raw.get("order_time", ""))
        try:
            if isinstance(create_time_raw, (int, float)) and create_time_raw > 1e9:
                created_at = datetime.fromtimestamp(create_time_raw)
            else:
                created_at = datetime.fromisoformat(str(create_time_raw).replace("T", " "))
        except (ValueError, TypeError, OSError):
            created_at = datetime.utcnow()

        return OrderSchema(
            order_id=str(raw.get("order_id", "")),
            order_number=str(raw.get("order_no", raw.get("order_id", ""))),
            order_type=OrderType.DINE_IN,
            order_status=order_status,
            store_id=store_id,
            brand_id=brand_id,
            table_number=raw.get("table_no"),
            customer_id=raw.get("member_id"),
            items=items,
            subtotal=subtotal,
            discount=discount,
            service_charge=Decimal("0"),
            total=total,
            created_at=created_at,
            waiter_id=raw.get("waiter_id", raw.get("operator_id")),
            notes=raw.get("remark"),
        )

    def to_staff_action(self, raw: Dict[str, Any], store_id: str, brand_id: str) -> StaffAction:
        """天财商龙操作日志 → StaffAction。"""
        action_time_raw = raw.get("action_time", raw.get("create_time", ""))
        try:
            if isinstance(action_time_raw, (int, float)) and action_time_raw > 1e9:
                created_at = datetime.fromtimestamp(action_time_raw)
            else:
                created_at = datetime.fromisoformat(str(action_time_raw).replace("T", " "))
        except (ValueError, TypeError, OSError):
            created_at = datetime.utcnow()

        amount_raw = raw.get("amount", raw.get("pay_amount"))
        amount = Decimal(str(amount_raw)) / 100 if amount_raw is not None else None

        return StaffAction(
            action_type=str(raw.get("action_type", raw.get("type", "unknown"))),
            brand_id=brand_id,
            store_id=store_id,
            operator_id=str(raw.get("operator_id", raw.get("staff_id", ""))),
            amount=amount,
            reason=raw.get("reason"),
            approved_by=raw.get("approved_by"),
            created_at=created_at,
        )

    def to_dish(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """天财商龙菜品原始字段 → 标准化 dict。"""
        price_raw = raw.get("price", raw.get("sale_price", 0))
        price_yuan = round(int(price_raw) / 100, 2) if price_raw else 0.0

        cost_raw = raw.get("cost", raw.get("cost_price", 0))
        cost_fen = int(cost_raw) if cost_raw else 0

        return {
            "pos_dish_id":  str(raw.get("dish_id", raw.get("good_id", ""))),
            "name":         str(raw.get("dish_name", raw.get("good_name", ""))),
            "category":     str(raw.get("category_name", raw.get("category_id", ""))),
            "price_yuan":   price_yuan,
            "cost_fen":     cost_fen,
            "cost_yuan":    round(cost_fen / 100, 2),
            "unit":         raw.get("unit", "份"),
            "is_available": int(raw.get("status", 1)) == 1,
        }

    def to_inventory_item(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """天财商龙原料原始字段 → 标准化 dict。"""
        unit_cost_raw = raw.get("unit_cost", raw.get("price", 0))
        unit_cost_val = float(unit_cost_raw) if unit_cost_raw else 0.0
        # 小于 1000 且非零 → 推断为元，否则推断为分
        if 0 < unit_cost_val < 1000:
            unit_cost_fen = int(unit_cost_val * 100)
        else:
            unit_cost_fen = int(unit_cost_val)

        return {
            "pos_material_id": str(raw.get("material_id", raw.get("id", ""))),
            "name":            str(raw.get("material_name", raw.get("name", ""))),
            "category":        str(raw.get("category", "")),
            "unit":            raw.get("unit", "kg"),
            "current_quantity": float(raw.get("current_qty", raw.get("qty", 0))),
            "min_quantity":    float(raw.get("min_qty", raw.get("reorder_point", 0))),
            "unit_cost_fen":   unit_cost_fen,
            "unit_cost_yuan":  round(unit_cost_fen / 100, 2),
            "supplier_name":   raw.get("supplier_name", raw.get("supplier", "")),
        }

    def _normalize_store(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """天财商龙门店原始字段 → 标准化 dict。"""
        return {
            "pos_store_id": str(raw.get("store_id", self.store_id)),
            "name":         str(raw.get("store_name", raw.get("name", ""))),
            "address":      raw.get("address", ""),
            "phone":        raw.get("phone", raw.get("tel", "")),
            "open_time":    raw.get("open_time", ""),
            "close_time":   raw.get("close_time", ""),
            "is_active":    int(raw.get("status", 1)) == 1,
        }
