"""企微/钉钉回调事件处理器。

处理来自 IM 平台的事件推送（员工入职/离职/部门变更），
映射为员工状态更新操作。
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ─── 企微事件类型常量 ─────────────────────────────────────────────────────────

WECOM_EVENT_CREATE_USER = "create_user"
WECOM_EVENT_UPDATE_USER = "update_user"
WECOM_EVENT_DELETE_USER = "delete_user"
WECOM_EVENT_CREATE_PARTY = "create_party"
WECOM_EVENT_UPDATE_PARTY = "update_party"
WECOM_EVENT_DELETE_PARTY = "delete_party"

# ─── 钉钉事件类型常量 ─────────────────────────────────────────────────────────

DINGTALK_EVENT_USER_ADD_ORG = "user_add_org"
DINGTALK_EVENT_USER_MODIFY_ORG = "user_modify_org"
DINGTALK_EVENT_USER_LEAVE_ORG = "user_leave_org"
DINGTALK_EVENT_ORG_DEPT_CREATE = "org_dept_create"
DINGTALK_EVENT_ORG_DEPT_MODIFY = "org_dept_modify"
DINGTALK_EVENT_ORG_DEPT_REMOVE = "org_dept_remove"


# ─── 企微回调处理 ─────────────────────────────────────────────────────────────


async def handle_wecom_callback(data: dict[str, Any]) -> dict[str, Any]:
    """处理企微事件回调。

    企微回调 XML 已由上层路由解密并转为 dict。

    支持事件：
      - create_user / update_user / delete_user
      - create_party / update_party / delete_party

    Args:
        data: 解密后的回调事件 dict，至少包含 ``Event`` / ``ChangeType``

    Returns:
        处理结果摘要 dict
    """
    event = data.get("Event", "")
    change_type = data.get("ChangeType", "")

    logger.info(
        "wecom_callback_received",
        event=event,
        change_type=change_type,
    )

    # 通讯录变更事件
    if event == "change_contact":
        return await _handle_wecom_contact_change(change_type, data)

    # 其他事件（审批回调等）暂记录日志
    logger.info("wecom_callback_unhandled", event=event, change_type=change_type)
    return {"handled": False, "event": event, "change_type": change_type}


async def _handle_wecom_contact_change(change_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """处理企微通讯录变更事件。"""

    if change_type == WECOM_EVENT_CREATE_USER:
        user_id = data.get("UserID", "")
        name = data.get("Name", "")
        mobile = data.get("Mobile", "")
        department = data.get("Department", "")
        position = data.get("Position", "")
        logger.info(
            "wecom_user_created",
            userid=user_id,
            name=name,
            department=department,
        )
        return {
            "handled": True,
            "action": "employee_onboard",
            "im_userid": user_id,
            "name": name,
            "phone": mobile,
            "department": str(department),
            "position": position,
        }

    if change_type == WECOM_EVENT_UPDATE_USER:
        user_id = data.get("UserID", "")
        logger.info("wecom_user_updated", userid=user_id)
        return {
            "handled": True,
            "action": "employee_update",
            "im_userid": user_id,
            "fields": {k: v for k, v in data.items() if k not in ("Event", "ChangeType", "ToUserName", "FromUserName")},
        }

    if change_type == WECOM_EVENT_DELETE_USER:
        user_id = data.get("UserID", "")
        logger.info("wecom_user_deleted", userid=user_id)
        return {
            "handled": True,
            "action": "employee_offboard",
            "im_userid": user_id,
        }

    if change_type in (
        WECOM_EVENT_CREATE_PARTY,
        WECOM_EVENT_UPDATE_PARTY,
        WECOM_EVENT_DELETE_PARTY,
    ):
        party_id = data.get("Id", "")
        party_name = data.get("Name", "")
        logger.info(
            "wecom_party_changed",
            change_type=change_type,
            party_id=party_id,
            party_name=party_name,
        )
        return {
            "handled": True,
            "action": f"department_{change_type.replace('_party', '')}",
            "department_id": str(party_id),
            "department_name": party_name,
        }

    logger.warning("wecom_contact_change_unknown", change_type=change_type)
    return {"handled": False, "change_type": change_type}


# ─── 钉钉回调处理 ─────────────────────────────────────────────────────────────


async def handle_dingtalk_callback(data: dict[str, Any]) -> dict[str, Any]:
    """处理钉钉事件回调。

    钉钉回调已由上层路由解密并转为 dict。

    支持事件：
      - user_add_org / user_modify_org / user_leave_org
      - org_dept_create / org_dept_modify / org_dept_remove

    Args:
        data: 解密后的回调事件 dict，至少包含 ``EventType``

    Returns:
        处理结果摘要 dict
    """
    event_type = data.get("EventType", "")

    logger.info("dingtalk_callback_received", event_type=event_type)

    # 用户变更
    if event_type == DINGTALK_EVENT_USER_ADD_ORG:
        user_ids = data.get("UserId", [])
        if isinstance(user_ids, str):
            user_ids = [user_ids]
        logger.info("dingtalk_user_added", user_ids=user_ids)
        return {
            "handled": True,
            "action": "employee_onboard",
            "im_userids": user_ids,
        }

    if event_type == DINGTALK_EVENT_USER_MODIFY_ORG:
        user_ids = data.get("UserId", [])
        if isinstance(user_ids, str):
            user_ids = [user_ids]
        logger.info("dingtalk_user_modified", user_ids=user_ids)
        return {
            "handled": True,
            "action": "employee_update",
            "im_userids": user_ids,
        }

    if event_type == DINGTALK_EVENT_USER_LEAVE_ORG:
        user_ids = data.get("UserId", [])
        if isinstance(user_ids, str):
            user_ids = [user_ids]
        logger.info("dingtalk_user_left", user_ids=user_ids)
        return {
            "handled": True,
            "action": "employee_offboard",
            "im_userids": user_ids,
        }

    # 部门变更
    if event_type in (
        DINGTALK_EVENT_ORG_DEPT_CREATE,
        DINGTALK_EVENT_ORG_DEPT_MODIFY,
        DINGTALK_EVENT_ORG_DEPT_REMOVE,
    ):
        dept_ids = data.get("DeptId", [])
        if isinstance(dept_ids, (str, int)):
            dept_ids = [dept_ids]
        action_suffix = event_type.replace("org_dept_", "")
        logger.info(
            "dingtalk_dept_changed",
            event_type=event_type,
            dept_ids=dept_ids,
        )
        return {
            "handled": True,
            "action": f"department_{action_suffix}",
            "department_ids": [str(d) for d in dept_ids],
        }

    logger.info("dingtalk_callback_unhandled", event_type=event_type)
    return {"handled": False, "event_type": event_type}
