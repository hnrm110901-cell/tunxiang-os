"""
费控模块枚举定义
包含费用申请状态、审批动作、场景代码、Agent类型等所有枚举。
"""
from enum import Enum


class ExpenseStatus(str, Enum):
    """费用申请状态"""
    DRAFT = "draft"              # 草稿（申请人填写中）
    SUBMITTED = "submitted"      # 已提交（等待审批）
    IN_REVIEW = "in_review"      # 审批中（有审批节点处理中）
    APPROVED = "approved"        # 审批通过
    REJECTED = "rejected"        # 审批驳回
    PAID = "paid"                # 已付款
    CANCELLED = "cancelled"      # 已撤回


class ApprovalAction(str, Enum):
    """审批动作"""
    APPROVE = "approve"                   # 通过
    REJECT = "reject"                     # 驳回
    TRANSFER = "transfer"                 # 转交
    REQUEST_REVISION = "request_revision" # 要求修改


class ApprovalNodeStatus(str, Enum):
    """审批节点状态"""
    PENDING = "pending"           # 待处理
    APPROVED = "approved"         # 已通过
    REJECTED = "rejected"         # 已驳回
    SKIPPED = "skipped"           # 跳过（条件不满足时）
    TRANSFERRED = "transferred"   # 已转交


class ExpenseScenarioCode(str, Enum):
    """费用申请场景代码（10个预置场景）"""
    DAILY_EXPENSE = "DAILY_EXPENSE"            # 日常费用报销（水电/耗材/维修）
    PETTY_CASH_REQUEST = "PETTY_CASH_REQUEST"  # 备用金申请/补充
    BUSINESS_TRIP = "BUSINESS_TRIP"            # 出差申请（督导/总部/培训）
    ENTERTAINMENT = "ENTERTAINMENT"            # 业务招待申请
    SPOT_PURCHASE = "SPOT_PURCHASE"            # 零星采购申请
    CONTRACT_PAYMENT = "CONTRACT_PAYMENT"      # 合同付款申请（租金/装修）
    EQUIPMENT_REPAIR = "EQUIPMENT_REPAIR"      # 设备维修申请
    MEAL_ALLOWANCE = "MEAL_ALLOWANCE"          # 员工餐补申请
    OTHER_EXPENSE = "OTHER_EXPENSE"            # 其他费用申请
    PREPAYMENT = "PREPAYMENT"                  # 预付款申请


class ApprovalRoutingType(str, Enum):
    """审批路由类型"""
    AMOUNT_BASED = "amount_based"       # 按金额路由（主要方式）
    SCENARIO_FIXED = "scenario_fixed"   # 场景固定双签（合同类）
    ESCALATED = "escalated"             # 升级审批（超差标触发）


class AgentJobStatus(str, Enum):
    """费控 Agent 任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"     # 条件不满足，跳过执行


class AgentType(str, Enum):
    """费控 Agent 类型（6大Agent）"""
    PETTY_CASH_GUARDIAN = "a1_petty_cash_guardian"    # 备用金守护
    INVOICE_VERIFIER = "a2_invoice_verifier"           # 发票核验
    STANDARD_COMPLIANCE = "a3_standard_compliance"     # 差标合规
    BUDGET_MONITOR = "a4_budget_monitor"               # 预算预警
    TRAVEL_AGENT = "a5_travel_agent"                   # 督导差旅
    COST_ATTRIBUTION = "a6_cost_attribution"           # 成本归因


class ExpenseCategoryCode(str, Enum):
    """费用科目代码（系统预置12类）"""
    UTILITIES = "UTILITIES"           # 水电费
    FOOD_WASTE = "FOOD_WASTE"         # 食材损耗
    MAINTENANCE = "MAINTENANCE"       # 设备维修
    TRAVEL = "TRAVEL"                 # 差旅费
    ENTERTAINMENT = "ENTERTAINMENT"   # 业务招待
    RENT = "RENT"                     # 租金
    DEPRECIATION = "DEPRECIATION"     # 折旧摊销
    LABOR = "LABOR"                   # 人工成本
    PLATFORM_FEE = "PLATFORM_FEE"     # 外卖平台佣金
    SUPPLIES = "SUPPLIES"             # 日常耗材
    MARKETING = "MARKETING"           # 营销推广
    OTHER = "OTHER"                   # 其他费用


class NotificationChannel(str, Enum):
    """通知推送渠道"""
    WECOM = "wecom"          # 企业微信 Webhook
    DINGTALK = "dingtalk"    # 钉钉机器人
    FEISHU = "feishu"        # 飞书机器人
    SMS = "sms"              # 短信（备用）


class NotificationEventType(str, Enum):
    """通知事件类型"""
    APPROVAL_REQUESTED = "approval_requested"   # 待审批（推送给审批人）
    APPROVED = "approved"                        # 已通过（推送给申请人）
    REJECTED = "rejected"                        # 已驳回（推送给申请人）
    TRANSFERRED = "transferred"                  # 已转交（推送给新审批人）
    REMINDER = "reminder"                        # 催办（超时未审批）


class PushStatus(str, Enum):
    """推送状态"""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"     # 无推送渠道配置时跳过


class StaffLevel(str, Enum):
    """员工职级（用于差标匹配）"""
    STORE_STAFF = "store_staff"           # 门店员工
    STORE_MANAGER = "store_manager"       # 店长
    REGION_MANAGER = "region_manager"     # 区域经理/督导
    BRAND_MANAGER = "brand_manager"       # 品牌运营总监
    EXECUTIVE = "executive"               # 高管（CFO/CEO）


class CityTier(str, Enum):
    """城市级别（用于差标匹配）"""
    TIER1 = "tier1"     # 一线：北上广深
    TIER2 = "tier2"     # 新一线/二线
    TIER3 = "tier3"     # 三线及以下
    OTHER = "other"     # 其他


class TravelExpenseType(str, Enum):
    """差旅费用类型（用于差标匹配）"""
    ACCOMMODATION = "accommodation"   # 住宿
    MEAL = "meal"                     # 餐饮补贴
    TRANSPORT = "transport"           # 交通
    OTHER_TRAVEL = "other_travel"     # 其他差旅费


class PettyCashAccountStatus(str, Enum):
    """备用金账户状态"""
    ACTIVE = "active"     # 正常运营
    FROZEN = "frozen"     # 冻结（员工离职等，等待归还）
    CLOSED = "closed"     # 关闭（门店关店）


class PettyCashTransactionType(str, Enum):
    """备用金流水类型"""
    # 收入类
    REPLENISHMENT = "replenishment"           # 补充拨付
    RETURN_FROM_KEEPER = "return_from_keeper" # 员工归还（离职/交接）
    OPENING_BALANCE = "opening_balance"       # 期初录入
    # 支出类
    DAILY_USE = "daily_use"                   # 日常支出（店长录入）
    POS_RECONCILE_ADJUST = "pos_reconcile_adjust"  # 日结差异调整
    # 系统类
    FREEZE_RESERVE = "freeze_reserve"         # 冻结备用（离职待归还）


class PettyCashSettlementStatus(str, Enum):
    """月末核销单状态"""
    DRAFT = "draft"           # A1 Agent自动生成草稿
    SUBMITTED = "submitted"   # 已提交财务
    CONFIRMED = "confirmed"   # 财务确认
    CLOSED = "closed"         # 已归档


# ─────────────────────────────────────────────────────────────────────────────
# 发票模块枚举
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceType(str, Enum):
    """发票类型"""
    VAT_SPECIAL = "vat_special"     # 增值税专用发票
    VAT_GENERAL = "vat_general"     # 增值税普通发票
    QUOTA = "quota"                  # 定额发票
    RECEIPT = "receipt"              # 收据
    OTHER = "other"                  # 其他凭证


class OcrStatus(str, Enum):
    """OCR识别状态"""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"


class VerifyStatus(str, Enum):
    """金税核验状态"""
    PENDING = "pending"
    VERIFIED_REAL = "verified_real"       # 核验为真
    VERIFIED_FAKE = "verified_fake"       # 核验为假（高亮警告，不自动驳回）
    VERIFY_FAILED = "verify_failed"       # 核验接口失败（网络等原因）
    SKIPPED = "skipped"                   # 跳过核验（定额发票等不支持）


class OcrProvider(str, Enum):
    """OCR服务提供商"""
    BAIDU = "baidu"
    ALIYUN = "aliyun"
    MOCK = "mock"   # 开发测试用
