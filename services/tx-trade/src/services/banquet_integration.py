"""宴会跨域集成服务 — 桥接 banquet_lifecycle 与其他域服务

解决的3个致命断裂：
1. 菜单确认 → BOM展开 → 采购单（tx-supply）
2. 定金收取 → 支付记录（tx-trade/payment）
3. 结账 → 创建订单 → 结算（tx-trade/cashier）

以及：
4. 会员联动（tx-member）
5. KDS 执行（tx-trade/kds）
6. Agent 嵌入（tx-agent）

设计原则：包装 BanquetLifecycleService，不修改其1347行代码。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .banquet_lifecycle import BanquetLifecycleService

logger = structlog.get_logger()

# Mac mini / tx-supply API base（同进程可直接 import，跨进程走 HTTP）
_SUPPLY_API = "http://localhost:8004"
_MAC_MINI_API = "http://localhost:8000"


class BanquetIntegrationService:
    """宴会集成层 — 在 lifecycle 基础上添加跨域调用"""

    def __init__(self, tenant_id: str, store_id: str, db: Optional[AsyncSession] = None):
        self.tenant_id = tenant_id
        self.store_id = store_id
        self.db = db
        self.lifecycle = BanquetLifecycleService(tenant_id, store_id)

    # ─── 1. 创建线索 + Agent 企业评估 ───

    async def create_lead(self, **kwargs) -> dict:
        result = self.lifecycle.create_lead(store_id=self.store_id, **kwargs)
        lead_id = result.get("lead_id", "")

        # Agent: 企业价值评估（异步不阻塞）
        try:
            await self._call_agent("enterprise_activation", {
                "action": "evaluate_lead",
                "lead_id": lead_id,
                "company": kwargs.get("company_name", ""),
                "budget_fen": kwargs.get("estimated_budget_fen", 0),
            })
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("agent_call_failed", agent="enterprise_activation", error=str(e))

        return result

    # ─── 2. 创建报价 + Agent 毛利守护 ───

    async def create_quotation(self, lead_id: str, **kwargs) -> dict:
        result = self.lifecycle.create_quotation(lead_id=lead_id, **kwargs)

        # Agent: 毛利底线检查
        total_fen = result.get("total_price_fen", 0)
        cost_fen = result.get("cost_estimate_fen", 0)
        if total_fen > 0 and cost_fen > 0:
            margin = (total_fen - cost_fen) / total_fen
            if margin < 0.3:
                result["margin_warning"] = {
                    "margin_rate": round(margin, 4),
                    "message": f"毛利率 {margin:.1%} 低于30%底线，建议调整报价",
                    "needs_approval": True,
                }
                logger.warning("banquet_margin_below_floor",
                               lead_id=lead_id, margin=round(margin, 4))

        return result

    # ─── 3. 收定金 + 创建支付记录 ───

    async def collect_deposit(self, contract_id: str, method: str = "wechat",
                              amount_fen: int = 0, **kwargs) -> dict:
        result = self.lifecycle.collect_deposit(contract_id=contract_id, **kwargs)

        actual_amount = amount_fen or result.get("deposit_fen", 0)
        if actual_amount <= 0:
            return result

        # 创建 Payment 记录
        if self.db:
            try:
                payment_id = str(uuid.uuid4())
                payment_no = f"BQ-DEP-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
                await self.db.execute(text("""
                    INSERT INTO payments (id, tenant_id, order_id, method, amount_fen, status, payment_no, extra, created_at)
                    VALUES (:id, :tid, :cid, :method, :amount, 'paid', :pno, :extra, NOW())
                """), {
                    "id": payment_id,
                    "tid": self.tenant_id,
                    "cid": contract_id,
                    "method": method,
                    "amount": actual_amount,
                    "pno": payment_no,
                    "extra": f'{{"type": "banquet_deposit", "contract_id": "{contract_id}"}}',
                })
                await self.db.flush()
                result["payment_id"] = payment_id
                result["payment_no"] = payment_no
                logger.info("banquet_deposit_payment_created",
                            contract_id=contract_id, amount_fen=actual_amount, payment_no=payment_no)
            except (ValueError, OSError) as e:
                logger.error("banquet_deposit_payment_failed", error=str(e))
                result["payment_error"] = str(e)

        return result

    # ─── 4. 确认菜单 + BOM展开 + 采购单 ───

    async def confirm_menu(self, contract_id: str, **kwargs) -> dict:
        result = self.lifecycle.confirm_menu(contract_id=contract_id, **kwargs)

        menu_items = result.get("confirmed_menu", [])
        if not menu_items:
            return result

        # BOM 展开 → 食材需求清单
        bom_result = await self._explode_bom(menu_items)
        result["bom_items"] = bom_result.get("items", [])
        result["total_ingredients"] = len(result["bom_items"])

        # 自动创建采购申请
        if result["bom_items"]:
            event_date = result.get("event_date", "")
            req_result = await self._create_requisition(
                items=result["bom_items"],
                reason=f"宴会 {contract_id} 食材采购",
                required_date=event_date,
            )
            result["requisition_id"] = req_result.get("requisition_id")
            result["requisition_status"] = req_result.get("status", "created")

        # 库存检查 → 标记缺货
        shortage = []
        for item in result["bom_items"]:
            # 简化：标记高价食材提醒
            if item.get("unit_cost_fen", 0) > 10000:  # 单价>100元的高价食材
                shortage.append({
                    "ingredient": item.get("name", ""),
                    "required_qty": item.get("qty", 0),
                    "warning": "高价食材，建议提前2周采购",
                })
        if shortage:
            result["shortage_warnings"] = shortage

        logger.info("banquet_menu_confirmed_with_procurement",
                     contract_id=contract_id,
                     ingredients=len(result["bom_items"]),
                     requisition_id=result.get("requisition_id"))

        return result

    # ─── 5. 开始执行 + 创建订单 + KDS分单 ───

    async def start_execution(self, contract_id: str) -> dict:
        result = self.lifecycle.start_execution(contract_id=contract_id)

        # 创建正式餐饮订单
        if self.db:
            try:
                order_id = str(uuid.uuid4())
                order_no = f"BQ-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{contract_id[-4:]}"
                table_no = result.get("venue", {}).get("hall_name", "宴会厅")

                await self.db.execute(text("""
                    INSERT INTO orders (id, tenant_id, store_id, order_no, table_number,
                        order_type, status, total_amount_fen, final_amount_fen, order_time, created_at)
                    VALUES (:id, :tid, :sid, :ono, :tbl, 'banquet', 'confirmed',
                        :total, :final, NOW(), NOW())
                """), {
                    "id": order_id,
                    "tid": self.tenant_id,
                    "sid": self.store_id,
                    "ono": order_no,
                    "tbl": table_no,
                    "total": result.get("total_price_fen", 0),
                    "final": result.get("total_price_fen", 0),
                })

                # 写入菜品到 order_items
                menu_items = result.get("confirmed_menu", [])
                for idx, item in enumerate(menu_items):
                    item_id = str(uuid.uuid4())
                    await self.db.execute(text("""
                        INSERT INTO order_items (id, tenant_id, order_id, dish_id, item_name,
                            quantity, unit_price_fen, subtotal_fen, sort_order, created_at)
                        VALUES (:id, :tid, :oid, :did, :name, :qty, :price, :sub, :sort, NOW())
                    """), {
                        "id": item_id,
                        "tid": self.tenant_id,
                        "oid": order_id,
                        "did": item.get("dish_id", item_id),
                        "name": item.get("name", f"宴会菜品{idx+1}"),
                        "qty": item.get("quantity", 1),
                        "price": item.get("price_fen", 0),
                        "sub": item.get("price_fen", 0) * item.get("quantity", 1),
                        "sort": idx,
                    })

                await self.db.flush()
                result["order_id"] = order_id
                result["order_no"] = order_no

                # KDS 分单
                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        await client.post(f"{_MAC_MINI_API}/api/v1/kds/push", json={
                            "station_id": "all",
                            "message": {
                                "type": "new_ticket",
                                "payload": {
                                    "order_id": order_id,
                                    "order_no": order_no,
                                    "order_type": "banquet",
                                    "items": menu_items,
                                },
                            },
                        })
                except (httpx.ConnectError, httpx.TimeoutException) as e:
                    logger.warning("banquet_kds_push_failed", error=str(e))

                logger.info("banquet_execution_started",
                            contract_id=contract_id, order_id=order_id, items=len(menu_items))

            except (ValueError, OSError) as e:
                logger.error("banquet_order_creation_failed", error=str(e))
                result["order_error"] = str(e)

        return result

    # ─── 6. 结账 + 扣除定金 ───

    async def settle_banquet(self, contract_id: str, payments: list[dict] = None) -> dict:
        result = self.lifecycle.settle_banquet(contract_id=contract_id)

        total_fen = result.get("total_price_fen", 0)
        deposit_paid = result.get("deposit_paid_fen", 0)
        balance_due = total_fen - deposit_paid

        result["balance_due_fen"] = balance_due
        result["deposit_already_paid_fen"] = deposit_paid

        # 如果有传入支付方式，创建尾款支付记录
        if self.db and payments and balance_due > 0:
            for pay in payments:
                try:
                    pay_id = str(uuid.uuid4())
                    pay_no = f"BQ-BAL-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
                    await self.db.execute(text("""
                        INSERT INTO payments (id, tenant_id, order_id, method, amount_fen, status, payment_no, extra, created_at)
                        VALUES (:id, :tid, :cid, :method, :amount, 'paid', :pno, :extra, NOW())
                    """), {
                        "id": pay_id,
                        "tid": self.tenant_id,
                        "cid": result.get("order_id", contract_id),
                        "method": pay.get("method", "wechat"),
                        "amount": pay.get("amount_fen", balance_due),
                        "pno": pay_no,
                        "extra": f'{{"type": "banquet_balance", "contract_id": "{contract_id}"}}',
                    })
                    result.setdefault("balance_payments", []).append({
                        "payment_id": pay_id,
                        "payment_no": pay_no,
                        "method": pay.get("method"),
                        "amount_fen": pay.get("amount_fen", balance_due),
                    })
                except (ValueError, OSError) as e:
                    logger.error("banquet_balance_payment_failed", error=str(e))

            await self.db.flush()

        logger.info("banquet_settled", contract_id=contract_id,
                     total=total_fen, deposit=deposit_paid, balance=balance_due)
        return result

    # ─── 7. 回访 + 会员联动 ───

    async def complete_feedback(self, contract_id: str, **kwargs) -> dict:
        result = self.lifecycle.complete_feedback(contract_id=contract_id, **kwargs)

        # 会员 RFM 更新
        customer_id = result.get("customer_id") or result.get("contact_phone", "")
        total_fen = result.get("total_spent_fen", 0)
        if customer_id and total_fen > 0 and self.db:
            try:
                await self.db.execute(text("""
                    INSERT INTO member_transactions (id, tenant_id, customer_id, store_id,
                        transaction_type, points, amount_fen, description, created_at)
                    VALUES (:id, :tid, :cid, :sid, 'earn', :pts, :amt, :desc, NOW())
                """), {
                    "id": str(uuid.uuid4()),
                    "tid": self.tenant_id,
                    "cid": customer_id,
                    "sid": self.store_id,
                    "pts": total_fen // 100,  # 1元=1积分
                    "amt": total_fen,
                    "desc": f"宴会消费 合同{contract_id}",
                })
                await self.db.flush()
                result["member_points_earned"] = total_fen // 100
                logger.info("banquet_member_updated", customer_id=customer_id, points=total_fen // 100)
            except (ValueError, OSError) as e:
                logger.warning("banquet_member_update_failed", error=str(e))

        return result

    # ─── 内部工具方法 ───

    async def _explode_bom(self, menu_items: list[dict]) -> dict:
        """调用 tx-supply BOM 展开服务"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(f"{_SUPPLY_API}/api/v1/supply/bom/explode", json={
                    "items": [{"dish_id": i.get("dish_id", ""), "qty": i.get("quantity", 1)}
                              for i in menu_items],
                })
                if resp.status_code == 200:
                    return resp.json().get("data", {})
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning("bom_explode_failed", error=str(e))

        # 降级：返回菜品本身作为"原材料"
        return {"items": [{"name": i.get("name", ""), "qty": i.get("quantity", 1),
                           "unit_cost_fen": i.get("cost_fen", 0)} for i in menu_items]}

    async def _create_requisition(self, items: list[dict], reason: str,
                                   required_date: str = "") -> dict:
        """调用 tx-supply 创建采购申请"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(f"{_SUPPLY_API}/api/v1/supply/requisitions", json={
                    "store_id": self.store_id,
                    "items": items,
                    "reason": reason,
                    "required_date": required_date,
                    "source": "banquet",
                })
                if resp.status_code == 200:
                    return resp.json().get("data", {})
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning("requisition_create_failed", error=str(e))

        return {"requisition_id": None, "status": "failed"}

    async def _call_agent(self, agent_name: str, payload: dict) -> dict:
        """调用 Agent 服务"""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(f"http://localhost:8008/api/v1/agent/{agent_name}/invoke",
                                         json=payload)
                if resp.status_code == 200:
                    return resp.json().get("data", {})
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.debug("agent_unavailable", agent=agent_name, error=str(e))
        return {}
