"""Action Executors — 每种 action_type 的具体执行器

各执行器通过 HTTP 调用下游服务或直接更新 DB。
所有执行器实现 BaseActionExecutor.execute() 接口。

action_type 列表：
  wait              — 等待（无实际动作，直接返回成功）
  send_wecom        — 发企业微信消息（调用 WeCom API）
  send_sms          — 发短信（调用 SMS adapter）
  send_miniapp_push — 小程序推送（调用 tx-member 接口）
  award_coupon      — 发放优惠券（调用 tx-member 接口）
  tag_customer      — 打标签（更新 customer tags）
  condition_branch  — 条件分支（查询客户行为数据）
  notify_staff      — 通知门店人员（调用 tx-ops 接口）
"""

import os
import uuid
from abc import ABC, abstractmethod
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 服务地址配置
# ---------------------------------------------------------------------------

_WECOM_API_URL: str = os.getenv("WECOM_API_URL", "http://tx-ops:8000")
_TX_MEMBER_URL: str = os.getenv("TX_MEMBER_SERVICE_URL", "http://tx-member:8000")
_TX_OPS_URL: str = os.getenv("TX_OPS_SERVICE_URL", "http://tx-ops:8000")
_HTTP_TIMEOUT: float = 10.0  # 秒


# ---------------------------------------------------------------------------
# 基类
# ---------------------------------------------------------------------------


class BaseActionExecutor(ABC):
    """所有 Action Executor 的抽象基类。"""

    @abstractmethod
    async def execute(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        action_config: dict,
        context: dict,
    ) -> dict[str, Any]:
        """
        执行动作。

        Args:
            tenant_id:     租户 UUID
            customer_id:   客户 UUID
            action_config: 步骤配置（来自 journey_definitions.steps[].action_config）
            context:       enrollment 上下文数据（含客户数据 + 触发时数据）

        Returns:
            {"success": bool, ...执行结果字段}
        """


# ---------------------------------------------------------------------------
# Wait — 等待
# ---------------------------------------------------------------------------


class WaitActionExecutor(BaseActionExecutor):
    """等待步骤：无实际动作，时间推迟由 JourneyEngine 处理。"""

    async def execute(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        action_config: dict,
        context: dict,
    ) -> dict[str, Any]:
        wait_hours = action_config.get("wait_hours", 0)
        logger.info(
            "wait_step_executed",
            customer_id=str(customer_id),
            wait_hours=wait_hours,
        )
        return {"success": True, "action": "wait", "wait_hours": wait_hours}


# ---------------------------------------------------------------------------
# WeCom — 企业微信消息
# ---------------------------------------------------------------------------


class WeComActionExecutor(BaseActionExecutor):
    """发企业微信消息（调用 tx-ops WeCom API）。"""

    async def execute(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        action_config: dict,
        context: dict,
    ) -> dict[str, Any]:
        template_id = action_config.get("template_id", "")
        message = action_config.get("message", "")
        # 支持模板变量替换
        if template_id and context:
            message = _render_template(message, context)

        phone = context.get("phone") or action_config.get("phone")

        log = logger.bind(
            tenant_id=str(tenant_id),
            customer_id=str(customer_id),
            template_id=template_id,
        )

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(
                    f"{_WECOM_API_URL}/api/v1/wecom/send_message",
                    json={
                        "tenant_id": str(tenant_id),
                        "customer_id": str(customer_id),
                        "phone": phone,
                        "template_id": template_id,
                        "message": message,
                        "source": "journey_engine",
                    },
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
                resp.raise_for_status()
                result = resp.json()
                log.info("wecom_message_sent", msgid=result.get("data", {}).get("msgid"))
                return {
                    "success": True,
                    "action": "send_wecom",
                    "msgid": result.get("data", {}).get("msgid"),
                    "phone": phone,
                }
        except httpx.HTTPStatusError as exc:
            log.error("wecom_send_failed", status_code=exc.response.status_code)
            return {
                "success": False,
                "action": "send_wecom",
                "error": f"HTTP {exc.response.status_code}",
            }
        except httpx.RequestError as exc:
            log.error("wecom_request_error", error=str(exc))
            return {"success": False, "action": "send_wecom", "error": str(exc)}


# ---------------------------------------------------------------------------
# SMS — 短信
# ---------------------------------------------------------------------------


class SMSActionExecutor(BaseActionExecutor):
    """发短信（调用 tx-ops SMS adapter）。"""

    async def execute(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        action_config: dict,
        context: dict,
    ) -> dict[str, Any]:
        template_id = action_config.get("template_id", "")
        template_params = action_config.get("template_params", {})
        phone = context.get("phone") or action_config.get("phone")

        if not phone:
            return {"success": False, "action": "send_sms", "error": "no_phone"}

        log = logger.bind(
            tenant_id=str(tenant_id),
            customer_id=str(customer_id),
        )

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(
                    f"{_TX_OPS_URL}/api/v1/sms/send",
                    json={
                        "tenant_id": str(tenant_id),
                        "phone": phone,
                        "template_id": template_id,
                        "template_params": template_params,
                        "source": "journey_engine",
                    },
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
                resp.raise_for_status()
                result = resp.json()
                log.info("sms_sent", phone=phone, template_id=template_id)
                return {
                    "success": True,
                    "action": "send_sms",
                    "phone": phone,
                    "request_id": result.get("data", {}).get("request_id"),
                }
        except httpx.HTTPStatusError as exc:
            log.error("sms_send_failed", status_code=exc.response.status_code)
            return {
                "success": False,
                "action": "send_sms",
                "error": f"HTTP {exc.response.status_code}",
            }
        except httpx.RequestError as exc:
            log.error("sms_request_error", error=str(exc))
            return {"success": False, "action": "send_sms", "error": str(exc)}


# ---------------------------------------------------------------------------
# Miniapp Push — 小程序推送
# ---------------------------------------------------------------------------


class MiniappPushActionExecutor(BaseActionExecutor):
    """小程序推送（调用 tx-member 订阅消息接口）。"""

    async def execute(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        action_config: dict,
        context: dict,
    ) -> dict[str, Any]:
        template_id = action_config.get("template_id", "")
        page = action_config.get("page", "pages/index/index")
        data = action_config.get("data", {})
        # 合并上下文数据
        merged_data = {**context, **data}

        log = logger.bind(
            tenant_id=str(tenant_id),
            customer_id=str(customer_id),
            template_id=template_id,
        )

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(
                    f"{_TX_MEMBER_URL}/api/v1/miniapp/subscribe_message",
                    json={
                        "tenant_id": str(tenant_id),
                        "customer_id": str(customer_id),
                        "template_id": template_id,
                        "page": page,
                        "data": merged_data,
                    },
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
                resp.raise_for_status()
                log.info("miniapp_push_sent", template_id=template_id)
                return {
                    "success": True,
                    "action": "send_miniapp_push",
                    "template_id": template_id,
                }
        except httpx.HTTPStatusError as exc:
            log.error("miniapp_push_failed", status_code=exc.response.status_code)
            return {
                "success": False,
                "action": "send_miniapp_push",
                "error": f"HTTP {exc.response.status_code}",
            }
        except httpx.RequestError as exc:
            log.error("miniapp_push_error", error=str(exc))
            return {"success": False, "action": "send_miniapp_push", "error": str(exc)}


# ---------------------------------------------------------------------------
# Coupon — 发放优惠券
# ---------------------------------------------------------------------------


class CouponActionExecutor(BaseActionExecutor):
    """发放优惠券（调用 tx-member 优惠券接口）。"""

    async def execute(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        action_config: dict,
        context: dict,
    ) -> dict[str, Any]:
        coupon_template_id = action_config.get("coupon_template_id", "")
        quantity = action_config.get("quantity", 1)
        note = action_config.get("note", "journey_engine_award")

        log = logger.bind(
            tenant_id=str(tenant_id),
            customer_id=str(customer_id),
            coupon_template_id=coupon_template_id,
        )

        if not coupon_template_id:
            return {
                "success": False,
                "action": "award_coupon",
                "error": "no_coupon_template_id",
            }

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(
                    f"{_TX_MEMBER_URL}/api/v1/coupons/award",
                    json={
                        "tenant_id": str(tenant_id),
                        "customer_id": str(customer_id),
                        "coupon_template_id": coupon_template_id,
                        "quantity": quantity,
                        "note": note,
                        "source": "journey_engine",
                    },
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
                resp.raise_for_status()
                result = resp.json()
                coupon_ids = result.get("data", {}).get("coupon_ids", [])
                log.info(
                    "coupon_awarded",
                    coupon_template_id=coupon_template_id,
                    quantity=quantity,
                    coupon_ids=coupon_ids,
                )
                return {
                    "success": True,
                    "action": "award_coupon",
                    "coupon_template_id": coupon_template_id,
                    "quantity": quantity,
                    "coupon_ids": coupon_ids,
                }
        except httpx.HTTPStatusError as exc:
            log.error("coupon_award_failed", status_code=exc.response.status_code)
            return {
                "success": False,
                "action": "award_coupon",
                "error": f"HTTP {exc.response.status_code}",
            }
        except httpx.RequestError as exc:
            log.error("coupon_award_error", error=str(exc))
            return {"success": False, "action": "award_coupon", "error": str(exc)}


# ---------------------------------------------------------------------------
# Tag — 打标签
# ---------------------------------------------------------------------------


class TagActionExecutor(BaseActionExecutor):
    """给客户打标签（调用 tx-member 客户标签接口）。"""

    async def execute(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        action_config: dict,
        context: dict,
    ) -> dict[str, Any]:
        tags_to_add: list[str] = action_config.get("tags_add", [])
        tags_to_remove: list[str] = action_config.get("tags_remove", [])

        log = logger.bind(
            tenant_id=str(tenant_id),
            customer_id=str(customer_id),
            tags_add=tags_to_add,
            tags_remove=tags_to_remove,
        )

        if not tags_to_add and not tags_to_remove:
            return {"success": True, "action": "tag_customer", "note": "no_tags_specified"}

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.patch(
                    f"{_TX_MEMBER_URL}/api/v1/customers/{customer_id}/tags",
                    json={
                        "tenant_id": str(tenant_id),
                        "tags_add": tags_to_add,
                        "tags_remove": tags_to_remove,
                        "source": "journey_engine",
                    },
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
                resp.raise_for_status()
                log.info("customer_tagged", tags_add=tags_to_add, tags_remove=tags_to_remove)
                return {
                    "success": True,
                    "action": "tag_customer",
                    "tags_added": tags_to_add,
                    "tags_removed": tags_to_remove,
                }
        except httpx.HTTPStatusError as exc:
            log.error("tag_customer_failed", status_code=exc.response.status_code)
            return {
                "success": False,
                "action": "tag_customer",
                "error": f"HTTP {exc.response.status_code}",
            }
        except httpx.RequestError as exc:
            log.error("tag_customer_error", error=str(exc))
            return {"success": False, "action": "tag_customer", "error": str(exc)}


# ---------------------------------------------------------------------------
# Branch — 条件分支
# ---------------------------------------------------------------------------


class BranchActionExecutor(BaseActionExecutor):
    """
    条件分支：根据客户行为/属性数据，决定走 true_next 还是 false_next。

    action_config 格式：
    {
        "condition": {"field": "has_returned", "operator": "eq", "value": true},
        "true_next": "step_4",
        "false_next": "step_5"
    }

    执行结果携带 next_step_id，由 JourneyEngine.advance_enrollment 读取。
    """

    async def execute(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        action_config: dict,
        context: dict,
    ) -> dict[str, Any]:
        condition = action_config.get("condition", {})
        true_next = action_config.get("true_next")
        false_next = action_config.get("false_next")

        field = condition.get("field", "")
        operator = condition.get("operator", "eq")
        expected = condition.get("value")

        actual = context.get(field)

        condition_met = False
        if actual is not None:
            from engine.journey_engine import OPERATORS

            op_fn = OPERATORS.get(operator)
            if op_fn:
                try:
                    condition_met = bool(op_fn(actual, expected))
                except (ValueError, TypeError):
                    condition_met = False

        next_step_id = true_next if condition_met else false_next

        logger.info(
            "branch_evaluated",
            customer_id=str(customer_id),
            field=field,
            condition_met=condition_met,
            next_step_id=next_step_id,
        )
        return {
            "success": True,
            "action": "condition_branch",
            "condition_met": condition_met,
            "next_step_id": next_step_id,
        }


# ---------------------------------------------------------------------------
# Notify Staff — 通知门店人员
# ---------------------------------------------------------------------------


class NotifyStaffActionExecutor(BaseActionExecutor):
    """通知门店人员（调用 tx-ops 企微通知接口）。"""

    async def execute(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        action_config: dict,
        context: dict,
    ) -> dict[str, Any]:
        staff_role = action_config.get("staff_role", "store_manager")
        message = action_config.get("message", "")
        store_id = context.get("store_id") or action_config.get("store_id")

        if message and context:
            message = _render_template(message, context)

        log = logger.bind(
            tenant_id=str(tenant_id),
            customer_id=str(customer_id),
            staff_role=staff_role,
        )

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(
                    f"{_TX_OPS_URL}/api/v1/notifications/staff",
                    json={
                        "tenant_id": str(tenant_id),
                        "customer_id": str(customer_id),
                        "store_id": store_id,
                        "staff_role": staff_role,
                        "message": message,
                        "source": "journey_engine",
                    },
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
                resp.raise_for_status()
                log.info("staff_notified", staff_role=staff_role)
                return {
                    "success": True,
                    "action": "notify_staff",
                    "staff_role": staff_role,
                }
        except httpx.HTTPStatusError as exc:
            log.error("notify_staff_failed", status_code=exc.response.status_code)
            return {
                "success": False,
                "action": "notify_staff",
                "error": f"HTTP {exc.response.status_code}",
            }
        except httpx.RequestError as exc:
            log.error("notify_staff_error", error=str(exc))
            return {"success": False, "action": "notify_staff", "error": str(exc)}


# ---------------------------------------------------------------------------
# Noop — 兜底执行器
# ---------------------------------------------------------------------------


class NoopActionExecutor(BaseActionExecutor):
    """未知 action_type 的兜底执行器，记录警告并返回成功。"""

    def __init__(self, action_type: str) -> None:
        self._action_type = action_type

    async def execute(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        action_config: dict,
        context: dict,
    ) -> dict[str, Any]:
        logger.warning(
            "unknown_action_type_noop",
            action_type=self._action_type,
            customer_id=str(customer_id),
        )
        return {
            "success": True,
            "action": self._action_type,
            "note": "noop_executor",
        }


# ---------------------------------------------------------------------------
# Registry — 统一注册表
# ---------------------------------------------------------------------------


class ActionExecutorRegistry:
    """Action Executor 注册表，按 action_type 分发执行器。"""

    _registry: dict[str, BaseActionExecutor] = {
        "wait": WaitActionExecutor(),
        "send_wecom": WeComActionExecutor(),
        "send_sms": SMSActionExecutor(),
        "send_miniapp_push": MiniappPushActionExecutor(),
        "award_coupon": CouponActionExecutor(),
        "tag_customer": TagActionExecutor(),
        "condition_branch": BranchActionExecutor(),
        "notify_staff": NotifyStaffActionExecutor(),
    }

    def get(self, action_type: str) -> BaseActionExecutor:
        """获取对应 action_type 的执行器，未注册时返回 NoopActionExecutor。"""
        executor = self._registry.get(action_type)
        if executor is None:
            return NoopActionExecutor(action_type)
        return executor

    def register(self, action_type: str, executor: BaseActionExecutor) -> None:
        """注册自定义执行器（扩展点）。"""
        self._registry[action_type] = executor


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _render_template(template: str, context: dict) -> str:
    """简单模板渲染：将 {key} 替换为 context[key] 的值。"""
    for key, value in context.items():
        placeholder = "{" + key + "}"
        if placeholder in template:
            template = template.replace(placeholder, str(value))
    return template
