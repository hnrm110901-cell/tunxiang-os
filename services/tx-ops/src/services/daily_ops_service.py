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
        "subtitle": "海鲜酒楼特化",
        "check_items": [
            {"item": "POS/KDS/打印机开机联网", "required": True},
            {"item": "海鲜池水温检查(18-22C)", "required": True},
            {"item": "冰鲜柜温度检查(-2~2C)", "required": True},
            {"item": "食材到货签收(检查新鲜度)", "required": True},
            {"item": "前厅桌椅+包间布置", "required": True},
            {"item": "灯光空调+背景音乐", "required": False},
            {"item": "服务员仪容仪表检查", "required": False},
            {"item": "预订确认(电话回访今日预订)", "required": True},
        ],
        "estimated_minutes": 40,
    },
    "E2": {
        "name": "营业巡航",
        "check_items": [
            {"item": "海鲜池展示鱼缸整洁", "required": True},
            {"item": "活鲜补货(低于展示量50%补充)", "required": True},
            {"item": "出餐时效<=25分钟(海鲜菜品标准)", "required": True},
            {"item": "包间服务15分钟巡台", "required": False},
            {"item": "VIP客户到店通知店长", "required": True},
        ],
        "estimated_minutes": 0,  # 持续整个营业时段
    },
    "E3": {
        "name": "异常处理",
        "subtitle": "海鲜品质与客诉应急",
        "check_items": [
            {"item": "海鲜死损登记(拍照+称重)", "required": True},
            {"item": "客诉登记并10分钟内响应", "required": True},
            {"item": "退菜原因记录(区分品质/口味/上错)", "required": True},
            {"item": "海鲜池设备故障紧急处理", "required": True},
            {"item": "缺料紧急采购(海鲜类2小时到店)", "required": True},
            {"item": "包间客户投诉店长亲自处理", "required": False},
            {"item": "食安问题立即上报区域经理", "required": True},
        ],
        "estimated_minutes": 0,
    },
    "E4": {
        "name": "交接班",
        "subtitle": "午晚市交接",
        "check_items": [
            {"item": "午市营业额及客流数交接", "required": True},
            {"item": "现金/备用金清点交接", "required": True},
            {"item": "海鲜池存量及状态交接", "required": True},
            {"item": "待处理预订/VIP信息交接", "required": True},
            {"item": "未完成客诉/退菜事项交接", "required": True},
            {"item": "设备异常状态交接", "required": False},
            {"item": "晚市预估客流及备料确认", "required": True},
        ],
        "estimated_minutes": 20,
    },
    "E5": {
        "name": "闭店检查",
        "subtitle": "海鲜酒楼闭店安全",
        "check_items": [
            {"item": "海鲜池过滤/供氧系统检查", "required": True},
            {"item": "冰鲜柜/冷冻柜温度确认并记录", "required": True},
            {"item": "剩余活鲜盘点及养护", "required": True},
            {"item": "厨房水电气关闭(保留海鲜池电源)", "required": True},
            {"item": "前厅灯光/空调/音乐关闭", "required": True},
            {"item": "门窗锁闭+安防系统启动", "required": True},
            {"item": "垃圾清运(海鲜垃圾当日必清)", "required": True},
            {"item": "消防通道畅通检查", "required": False},
        ],
        "estimated_minutes": 25,
    },
    "E6": {
        "name": "日结对账",
        "subtitle": "分渠道对账",
        "check_items": [
            {"item": "POS系统营收与实收核对", "required": True},
            {"item": "微信/支付宝/抖音到账确认", "required": True},
            {"item": "美团/饿了么外卖单核对", "required": True},
            {"item": "现金差异<=50元确认", "required": True},
            {"item": "挂账单/签单确认(含包间签单)", "required": True},
            {"item": "储值卡消费核对", "required": False},
            {"item": "海鲜称重单与出品数量核对", "required": True},
            {"item": "今日毛利率初步核算", "required": False},
        ],
        "estimated_minutes": 20,
    },
    "E7": {
        "name": "复盘归因",
        "subtitle": "经营数据复盘",
        "check_items": [
            {"item": "今日营收vs目标达成率", "required": True},
            {"item": "翻台率/桌均/人均对比分析", "required": True},
            {"item": "海鲜品类销售排行(爆品/滞销)", "required": True},
            {"item": "确认Top3异常问题及根因", "required": True},
            {"item": "查看Agent智能改进建议", "required": False},
            {"item": "填写店长复盘备注", "required": False},
        ],
        "estimated_minutes": 15,
    },
    "E8": {
        "name": "整改跟踪",
        "subtitle": "持续改善闭环",
        "check_items": [
            {"item": "昨日整改项完成情况检查", "required": True},
            {"item": "新建今日整改任务", "required": False},
            {"item": "指定责任人和截止日期", "required": True},
            {"item": "区域经理巡店问题跟踪", "required": True},
            {"item": "食安整改项优先处理确认", "required": True},
            {"item": "本周整改完成率统计", "required": False},
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
