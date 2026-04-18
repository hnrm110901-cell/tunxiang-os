"""
shared/config_templates/base.py — 业态模板基础数据结构

设计原则：
- 所有模板输出一个 TenantConfigPackage，可原子性导入到屯象OS
- 金额统一用分（整数），不使用浮点
- 模板只提供默认值，DeliveryAgent 覆写关键字段后才生成最终包
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ── 业态枚举 ──────────────────────────────────────────────────────────


class RestaurantType(str, Enum):
    CASUAL_DINING = "casual_dining"   # 正餐（湘菜/粤菜/川菜等）
    HOT_POT = "hot_pot"               # 火锅
    FAST_FOOD = "fast_food"           # 快餐/档口
    BANQUET = "banquet"               # 宴席（徐记海鲜类大店）
    CAFE_TEA = "cafe_tea"             # 茶饮/咖啡


# ── 子配置结构 ────────────────────────────────────────────────────────


class PrinterConfig(BaseModel):
    name: str
    printer_type: str                 # receipt | kitchen | label
    protocol: str = "escpos"         # escpos | zpl | pdf
    connection: str = "network"      # network | usb | bluetooth
    ip: str = ""                     # 网口打印机 IP（运行时填入）
    is_default: bool = False
    auto_cut: bool = True
    copies: int = 1


class KDSZoneConfig(BaseModel):
    zone_code: str                    # 如 "wok", "seafood", "cold"
    zone_name: str                    # 如 "炒锅档", "海鲜档", "凉菜档"
    display_order: int = 0
    alert_minutes: int = 8           # 超时预警分钟数
    color_normal: str = "#FFFFFF"
    color_warning: str = "#FFC107"   # 橙色：即将超时
    color_overdue: str = "#F44336"   # 红色：已超时


class ShiftConfig(BaseModel):
    shift_name: str                  # 如 "午市", "晚市"
    start_time: str                  # "HH:MM"
    end_time: str                    # "HH:MM"
    is_overnight: bool = False       # 跨午夜
    settlement_cutoff: str = "02:00" # 日结截止时间


class BillingRuleSet(BaseModel):
    min_spend_fen: int = 0           # 最低消费（分），0=不限
    service_fee_rate: float = 0.0    # 服务费率（0.1 = 10%）
    service_fee_fixed_fen: int = 0   # 固定服务费（分），与 rate 二选一
    packing_fee_fen: int = 0         # 打包费（外卖用）
    min_spend_applies_to: str = "table"  # table | person


class DiscountPolicy(BaseModel):
    """折扣守护 Agent 初始策略（L3）"""
    employee_max_discount: float = 0.88      # 员工最大折扣（0.88 = 88折）
    manager_max_discount: float = 0.80       # 店长最大折扣
    owner_max_discount: float = 0.0          # 老板无限制（0.0 = 不限）
    min_gross_margin: float = 0.30           # 毛利保护线（30%）
    alert_on_gift: bool = True               # 赠菜需预警
    require_reason_below: float = 0.85       # 低于85折需填理由
    block_below_cost: bool = True            # 低于成本价自动阻断


class MemberTierConfig(BaseModel):
    tier_code: str
    tier_name: str
    min_spend_fen: int = 0           # 升级所需累计消费（分）
    point_multiplier: float = 1.0    # 积分倍率
    discount_rate: float = 1.0       # 会员折扣（1.0 = 无折扣）
    birthday_benefit: str = ""       # 生日权益描述


class AgentPolicySet(BaseModel):
    """9大 Agent 的初始策略参数"""
    # 折扣守护
    discount_guard: DiscountPolicy = Field(default_factory=DiscountPolicy)
    # 库存预警（初始阈值，Agent 开业后自动标定）
    inventory_alert_days: int = 3            # 库存不足 N 天用量时预警
    inventory_waste_alert_rate: float = 0.05 # 损耗超过 5% 时预警
    # 出餐调度
    kds_target_minutes: int = 15             # 出餐目标时间（分钟）
    kds_warn_minutes: int = 20               # 超出时预警
    # 智能排菜（宴席）
    banquet_pre_sort_hours: int = 2          # 宴席前 N 小时自动排菜
    # 财务稽核
    finance_audit_enabled: bool = True
    # 其余 Agent 默认激活
    member_insight_enabled: bool = True
    tour_inspection_enabled: bool = False    # P2，默认不激活


# ── 配置包 ─────────────────────────────────────────────────────────────


class TenantConfigPackage(BaseModel):
    """
    DeliveryAgent 生成的完整租户配置包。

    生命周期：
      1. 由 BaseTemplate.build_default() 生成默认包
      2. DeliveryAgent 将 20 问答案 apply() 覆写关键字段
      3. POST /api/v1/onboarding/import 原子性写入数据库
    """
    # 元信息
    schema_version: str = "1.0"
    restaurant_type: RestaurantType
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    delivery_session_id: str = ""    # DeliveryAgent 会话 ID，留痕

    # 门店基础
    store_name: str = ""
    store_address: str = ""
    table_count: int = 0
    vip_room_count: int = 0          # 包厢数

    # 硬件配置
    printers: list[PrinterConfig] = Field(default_factory=list)
    kds_zones: list[KDSZoneConfig] = Field(default_factory=list)

    # 营业规则
    shifts: list[ShiftConfig] = Field(default_factory=list)
    billing_rules: BillingRuleSet = Field(default_factory=BillingRuleSet)

    # 会员体系
    point_rate: float = 1.0          # 消费1元=N积分
    point_redeem_rate: float = 100.0 # N积分=1元
    member_tiers: list[MemberTierConfig] = Field(default_factory=list)

    # 渠道激活
    channels_enabled: list[str] = Field(default_factory=list)  # meituan | eleme | douyin
    delivery_packing_fee_fen: int = 0

    # 员工角色（用于 RBAC 模板）
    employee_roles: list[str] = Field(default_factory=list)

    # Agent 策略
    agent_policies: AgentPolicySet = Field(default_factory=AgentPolicySet)

    # 支付方式
    payment_methods: list[str] = Field(
        default_factory=lambda: ["wechat", "alipay", "cash"]
    )

    # 配置健康度（由 config_health 服务写入）
    config_score: float = 0.0
    missing_required: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def is_ready_for_go_live(self) -> bool:
        """配置包是否满足上线最低要求（score ≥ 90 且无 critical 缺项）"""
        return self.config_score >= 90.0 and len(self.missing_required) == 0


# ── 模板基类 ───────────────────────────────────────────────────────────


class BaseTemplate(ABC):
    """
    业态模板基类。子类只需实现 build_default() 返回带默认值的配置包。
    """

    @property
    @abstractmethod
    def restaurant_type(self) -> RestaurantType:
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        ...

    @abstractmethod
    def build_default(self) -> TenantConfigPackage:
        """返回该业态的默认配置包（未经 DeliveryAgent 定制）"""
        ...

    def apply(self, answers: dict[str, Any]) -> TenantConfigPackage:
        """
        将 DeliveryAgent 的 20 问答案应用到默认模板，返回定制化配置包。

        answers 键名对应 DeliveryAgent.DELIVERY_QUESTIONS 中的 key。
        未回答的问题保留模板默认值。
        """
        pkg = self.build_default()

        # 门店基础
        if v := answers.get("store_name"):
            pkg.store_name = v
        if v := answers.get("store_address"):
            pkg.store_address = v
        v = answers.get("table_count")
        if v is not None:
            pkg.table_count = int(v)
        v = answers.get("vip_room_count")
        if v is not None:
            pkg.vip_room_count = int(v)

        # KDS 分区（覆写）
        if zones := answers.get("kds_zones"):   # list[dict]
            pkg.kds_zones = [KDSZoneConfig(**z) for z in zones]

        # 打印机（覆写）
        if printers := answers.get("printers"):
            pkg.printers = [PrinterConfig(**p) for p in printers]

        # 折扣守护阈值
        v = answers.get("employee_max_discount")
        if v is not None:
            pkg.agent_policies.discount_guard.employee_max_discount = float(v)
        v = answers.get("manager_max_discount")
        if v is not None:
            pkg.agent_policies.discount_guard.manager_max_discount = float(v)
        v = answers.get("min_gross_margin")
        if v is not None:
            pkg.agent_policies.discount_guard.min_gross_margin = float(v)

        # 最低消费 / 服务费
        v = answers.get("min_spend_yuan")
        if v is not None:
            pkg.billing_rules.min_spend_fen = int(float(v) * 100)
        v = answers.get("service_fee_rate")
        if v is not None:
            pkg.billing_rules.service_fee_rate = float(v)

        # 渠道
        if v := answers.get("channels_enabled"):
            pkg.channels_enabled = v if isinstance(v, list) else [v]

        # 支付方式
        if v := answers.get("payment_methods"):
            pkg.payment_methods = v if isinstance(v, list) else [v]

        # 会员积分
        v = answers.get("point_rate")
        if v is not None:
            pkg.point_rate = float(v)
        v = answers.get("point_redeem_rate")
        if v is not None:
            pkg.point_redeem_rate = float(v)

        # 员工角色
        if v := answers.get("employee_roles"):
            pkg.employee_roles = v if isinstance(v, list) else [v]

        # DeliveryAgent 会话 ID
        if v := answers.get("delivery_session_id"):
            pkg.delivery_session_id = v

        return pkg
