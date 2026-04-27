"""日清日结检查项模板库

三套行业模板，门店可按业态选择后自定义覆盖。

模板：
  - xuji_seafood   : 徐记海鲜（海鲜酒楼）
  - standard_chinese: 标准中餐
  - fast_food       : 快餐/简餐
"""

from __future__ import annotations

from copy import deepcopy
from typing import Dict, List, Optional

# ─── 类型别名 ───

CheckItem = Dict  # {"item": str, "required": bool}
NodeDef = Dict  # {"name": str, "check_items": list[CheckItem], "estimated_minutes": int, ...}
TemplateDef = Dict[str, NodeDef]  # {"E1": NodeDef, ..., "E8": NodeDef}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  徐记海鲜模板
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

XUJI_SEAFOOD: TemplateDef = {
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
        "estimated_minutes": 0,
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  标准中餐模板
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STANDARD_CHINESE: TemplateDef = {
    "E1": {
        "name": "开店准备",
        "check_items": [
            {"item": "POS/打印机开机联网", "required": True},
            {"item": "冷藏柜/冰箱温度检查", "required": True},
            {"item": "食材到货签收验收", "required": True},
            {"item": "前厅桌椅摆放及台面清洁", "required": True},
            {"item": "灯光空调开启", "required": False},
            {"item": "服务员晨会/仪容检查", "required": False},
            {"item": "今日预订情况确认", "required": True},
        ],
        "estimated_minutes": 30,
    },
    "E2": {
        "name": "营业巡航",
        "check_items": [
            {"item": "客流高峰人力调度到位", "required": True},
            {"item": "出餐时效<=30分钟", "required": True},
            {"item": "桌台周转监控", "required": True},
            {"item": "菜品出品质量巡检", "required": True},
            {"item": "客诉即时响应", "required": True},
            {"item": "服务员站位及巡台", "required": False},
        ],
        "estimated_minutes": 0,
    },
    "E3": {
        "name": "异常处理",
        "check_items": [
            {"item": "客诉登记并处理", "required": True},
            {"item": "退菜原因登记", "required": True},
            {"item": "设备故障报修", "required": True},
            {"item": "缺料紧急采购", "required": False},
            {"item": "食安问题上报", "required": True},
        ],
        "estimated_minutes": 0,
    },
    "E4": {
        "name": "交接班",
        "check_items": [
            {"item": "营业额及客流交接", "required": True},
            {"item": "现金/备用金清点", "required": True},
            {"item": "待办事项交接", "required": True},
            {"item": "设备状态确认", "required": False},
            {"item": "未完成客诉交接", "required": True},
        ],
        "estimated_minutes": 15,
    },
    "E5": {
        "name": "闭店检查",
        "check_items": [
            {"item": "厨房水电气关闭", "required": True},
            {"item": "食材入冷库/保鲜处理", "required": True},
            {"item": "前厅灯光/空调关闭", "required": True},
            {"item": "门窗锁闭", "required": True},
            {"item": "安防系统启动", "required": True},
            {"item": "垃圾清运", "required": False},
            {"item": "消防设施检查", "required": False},
        ],
        "estimated_minutes": 20,
    },
    "E6": {
        "name": "日结对账",
        "check_items": [
            {"item": "系统营收与实收核对", "required": True},
            {"item": "微信/支付宝到账确认", "required": True},
            {"item": "现金差异<=50元", "required": True},
            {"item": "挂账单/签单确认", "required": True},
            {"item": "外卖平台订单核对", "required": False},
        ],
        "estimated_minutes": 15,
    },
    "E7": {
        "name": "复盘归因",
        "check_items": [
            {"item": "今日KPI达成情况", "required": True},
            {"item": "确认Top3异常问题", "required": True},
            {"item": "菜品销售排行分析", "required": True},
            {"item": "查看Agent改进建议", "required": False},
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
            {"item": "本周整改完成率", "required": False},
            {"item": "食安整改优先处理", "required": True},
        ],
        "estimated_minutes": 10,
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  快餐模板
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FAST_FOOD: TemplateDef = {
    "E1": {
        "name": "开店准备",
        "check_items": [
            {"item": "POS/自助点餐机开机联网", "required": True},
            {"item": "冷藏/冷冻柜温度检查", "required": True},
            {"item": "食材到货验收(半成品为主)", "required": True},
            {"item": "前厅座位清洁+餐具补充", "required": True},
            {"item": "出餐台/取餐区准备", "required": True},
            {"item": "灯箱菜单/电子屏检查", "required": False},
        ],
        "estimated_minutes": 20,
    },
    "E2": {
        "name": "营业巡航",
        "check_items": [
            {"item": "出餐时效<=10分钟", "required": True},
            {"item": "排队等候<=5分钟监控", "required": True},
            {"item": "自助点餐机运行正常", "required": True},
            {"item": "餐桌翻台及时清理", "required": True},
            {"item": "备餐量动态调整", "required": True},
            {"item": "外卖出餐单独通道", "required": False},
        ],
        "estimated_minutes": 0,
    },
    "E3": {
        "name": "异常处理",
        "check_items": [
            {"item": "客诉快速处理(5分钟内)", "required": True},
            {"item": "退餐/换餐登记", "required": True},
            {"item": "设备故障(POS/点餐机)应急", "required": True},
            {"item": "外卖骑手异常沟通", "required": False},
            {"item": "食安问题上报", "required": True},
        ],
        "estimated_minutes": 0,
    },
    "E4": {
        "name": "交接班",
        "check_items": [
            {"item": "营业额/单量交接", "required": True},
            {"item": "现金/备用金清点", "required": True},
            {"item": "备餐量及库存交接", "required": True},
            {"item": "设备状态交接", "required": False},
            {"item": "待处理外卖异常交接", "required": True},
        ],
        "estimated_minutes": 10,
    },
    "E5": {
        "name": "闭店检查",
        "check_items": [
            {"item": "设备关闭(POS/点餐机/灯箱)", "required": True},
            {"item": "剩余食材处理及冷藏", "required": True},
            {"item": "厨房深度清洁", "required": True},
            {"item": "水电气关闭", "required": True},
            {"item": "门窗锁闭+安防", "required": True},
            {"item": "垃圾清运", "required": False},
        ],
        "estimated_minutes": 15,
    },
    "E6": {
        "name": "日结对账",
        "check_items": [
            {"item": "POS系统与实收核对", "required": True},
            {"item": "外卖平台(美团/饿了么)对账", "required": True},
            {"item": "自助点餐机支付核对", "required": True},
            {"item": "现金差异确认", "required": True},
            {"item": "优惠券/满减核销核对", "required": False},
        ],
        "estimated_minutes": 10,
    },
    "E7": {
        "name": "复盘归因",
        "check_items": [
            {"item": "今日单量/营收目标达成", "required": True},
            {"item": "平均出餐时效分析", "required": True},
            {"item": "外卖vs堂食占比分析", "required": True},
            {"item": "确认Top3问题", "required": True},
            {"item": "查看Agent建议", "required": False},
        ],
        "estimated_minutes": 10,
    },
    "E8": {
        "name": "整改跟踪",
        "check_items": [
            {"item": "昨日整改项检查", "required": True},
            {"item": "新建今日整改任务", "required": False},
            {"item": "指定责任人和截止日", "required": True},
            {"item": "食安整改优先确认", "required": True},
            {"item": "出餐效率改善跟踪", "required": False},
        ],
        "estimated_minutes": 10,
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  模板注册表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TEMPLATE_REGISTRY: Dict[str, TemplateDef] = {
    "xuji_seafood": XUJI_SEAFOOD,
    "standard_chinese": STANDARD_CHINESE,
    "fast_food": FAST_FOOD,
}

TEMPLATE_META: Dict[str, Dict[str, str]] = {
    "xuji_seafood": {
        "name": "徐记海鲜",
        "description": "海鲜酒楼定制模板，含海鲜池管理、活鲜养护、包间服务等特色检查项",
        "industry": "海鲜酒楼",
    },
    "standard_chinese": {
        "name": "标准中餐",
        "description": "通用中餐厅模板，适用于大部分中餐连锁门店",
        "industry": "中式正餐",
    },
    "fast_food": {
        "name": "快餐/简餐",
        "description": "快餐模板，强调出餐效率、排队管控和外卖管理",
        "industry": "快餐简餐",
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  公共函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_template(template_key: str) -> TemplateDef:
    """获取指定模板的节点定义（深拷贝，可安全修改）。

    Args:
        template_key: 模板标识 (xuji_seafood / standard_chinese / fast_food)

    Returns:
        E1-E8 节点定义字典

    Raises:
        ValueError: 模板不存在时抛出
    """
    if template_key not in TEMPLATE_REGISTRY:
        available = ", ".join(TEMPLATE_REGISTRY.keys())
        raise ValueError(f"Unknown template '{template_key}'. Available: {available}")
    return deepcopy(TEMPLATE_REGISTRY[template_key])


def list_templates() -> List[Dict[str, str]]:
    """列出所有可用模板及其元信息。"""
    result = []
    for key, meta in TEMPLATE_META.items():
        template = TEMPLATE_REGISTRY[key]
        total_items = sum(len(node.get("check_items", [])) for node in template.values())
        result.append(
            {
                "key": key,
                "name": meta["name"],
                "description": meta["description"],
                "industry": meta["industry"],
                "node_count": len(template),
                "total_check_items": total_items,
            }
        )
    return result


def get_node_from_template(
    template_key: str,
    node_code: str,
) -> Optional[NodeDef]:
    """从指定模板获取单个节点定义。

    Args:
        template_key: 模板标识
        node_code: 节点编号 (E1-E8)

    Returns:
        节点定义字典，不存在则返回 None
    """
    template = get_template(template_key)
    return template.get(node_code)


def merge_custom_items(
    template_key: str,
    node_code: str,
    extra_items: List[CheckItem],
) -> NodeDef:
    """在模板节点基础上追加自定义检查项。

    Args:
        template_key: 模板标识
        node_code: 节点编号
        extra_items: 追加的检查项列表

    Returns:
        合并后的节点定义
    """
    node = get_node_from_template(template_key, node_code)
    if node is None:
        raise ValueError(f"Node {node_code} not found in template {template_key}")
    node["check_items"].extend(extra_items)
    return node
