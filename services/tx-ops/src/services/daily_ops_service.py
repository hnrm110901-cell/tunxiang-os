"""日清日结服务 — E1-E8 八节点流程引擎

纯函数部分 + 流程状态机。

节点定义：
  E1 开店准备：设备检查 + 食材到货确认 + 环境卫生
  E2 营业巡航：客流监控 + 出餐时效 + 服务质量
  E3 异常处理：投诉/退菜/设备故障/缺料
  E4 交接班：  营业额核对 + 现金清点 + 待办交接
  E5 闭店检查：水电气 + 食材保鲜 + 安全巡检
  E6 日结对账：系统账 vs 实收 + 分支付方式核对
  E7 复盘归因：今日 Top3 问题 + 根因 + Agent 建议
  E8 整改跟踪：待办事项 + 责任人 + 截止日期 + 完成率
"""
from dataclasses import dataclass
from typing import Optional

# ─── 节点定义 ───

NODE_DEFINITIONS = {
    "E1": {
        "name": "开店准备",
        "check_items": [
            {"item": "POS 开机并联网", "required": True},
            {"item": "打印机测试打印", "required": True},
            {"item": "食材到货签收", "required": True},
            {"item": "冷链温度检查", "required": True},
            {"item": "前厅桌椅摆放", "required": False},
            {"item": "灯光空调开启", "required": False},
        ],
        "estimated_minutes": 30,
    },
    "E2": {
        "name": "营业巡航",
        "check_items": [
            {"item": "客流高峰人力到位", "required": True},
            {"item": "出餐时效≤30分钟", "required": True},
            {"item": "桌台周转正常", "required": False},
            {"item": "客诉即时处理", "required": True},
        ],
        "estimated_minutes": 0,  # 持续整个营业时段
    },
    "E3": {
        "name": "异常处理",
        "check_items": [
            {"item": "客诉登记并处理", "required": True},
            {"item": "退菜原因记录", "required": True},
            {"item": "设备故障报修", "required": False},
            {"item": "缺料紧急采购", "required": False},
        ],
        "estimated_minutes": 0,
    },
    "E4": {
        "name": "交接班",
        "check_items": [
            {"item": "营业额口头交接", "required": True},
            {"item": "现金清点", "required": True},
            {"item": "待办事项交接", "required": True},
            {"item": "设备状态确认", "required": False},
        ],
        "estimated_minutes": 15,
    },
    "E5": {
        "name": "闭店检查",
        "check_items": [
            {"item": "水电气关闭", "required": True},
            {"item": "食材入冷库/保鲜", "required": True},
            {"item": "门窗锁闭", "required": True},
            {"item": "安防系统启动", "required": True},
            {"item": "垃圾清运", "required": False},
        ],
        "estimated_minutes": 20,
    },
    "E6": {
        "name": "日结对账",
        "check_items": [
            {"item": "系统营收与实收核对", "required": True},
            {"item": "微信/支付宝到账确认", "required": True},
            {"item": "现金差异≤50元", "required": True},
            {"item": "挂账单确认", "required": False},
        ],
        "estimated_minutes": 15,
    },
    "E7": {
        "name": "复盘归因",
        "check_items": [
            {"item": "查看今日 KPI 对比", "required": True},
            {"item": "确认 Top3 异常问题", "required": True},
            {"item": "查看 Agent 改进建议", "required": False},
            {"item": "填写复盘备注", "required": False},
        ],
        "estimated_minutes": 10,
    },
    "E8": {
        "name": "整改跟踪",
        "check_items": [
            {"item": "昨日整改项检查", "required": True},
            {"item": "新建今日整改任务", "required": False},
            {"item": "指定责任人和截止日", "required": True},
        ],
        "estimated_minutes": 10,
    },
}


# ─── 纯函数 ───

def get_node_definition(node_code: str) -> dict:
    """获取节点定义"""
    return NODE_DEFINITIONS.get(node_code, {})


def compute_flow_progress(node_statuses: dict[str, str]) -> dict:
    """计算流程进度

    Args:
        node_statuses: {"E1": "completed", "E2": "in_progress", ...}

    Returns:
        {"completed": 3, "total": 8, "pct": 37.5, "current_node": "E4"}
    """
    total = len(NODE_DEFINITIONS)
    completed = sum(1 for s in node_statuses.values() if s in ("completed", "skipped"))
    current = None
    for code in ["E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"]:
        if node_statuses.get(code) in ("pending", "in_progress"):
            current = code
            break

    return {
        "completed": completed,
        "total": total,
        "pct": round(completed / total * 100, 1) if total > 0 else 0,
        "current_node": current,
        "status": "completed" if completed == total else "in_progress" if completed > 0 else "not_started",
    }


def compute_node_check_result(check_items: list[dict]) -> str:
    """计算节点检查结果

    Args:
        check_items: [{"item": "xxx", "required": True, "checked": True, "result": "pass"}, ...]

    Returns:
        "pass" / "fail" / "partial"
    """
    if not check_items:
        return "pass"

    required_items = [c for c in check_items if c.get("required")]
    all_checked = all(c.get("checked") for c in check_items)
    required_passed = all(c.get("result") == "pass" for c in required_items if c.get("checked"))

    if all_checked and required_passed:
        return "pass"
    if not required_passed:
        return "fail"
    return "partial"


def get_flow_timeline(node_statuses: dict[str, str]) -> list[dict]:
    """生成流程时间轴（前端展示用）"""
    timeline = []
    for code in ["E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"]:
        defn = NODE_DEFINITIONS.get(code, {})
        status = node_statuses.get(code, "pending")
        timeline.append({
            "code": code,
            "name": defn.get("name", code),
            "status": status,
            "check_count": len(defn.get("check_items", [])),
            "estimated_minutes": defn.get("estimated_minutes", 0),
            "is_current": status in ("pending", "in_progress") and all(
                node_statuses.get(f"E{i}") in ("completed", "skipped")
                for i in range(1, int(code[1]))
            ),
        })
    return timeline
