"""
conftest.py — 宴会 Agent 测试环境引导

问题背景：
  packages/agents/banquet/src 和 apps/api-gateway/src 都叫 "src"，
  直接插路径会造成命名空间冲突。

解决方案：
  1. 在任何 import 之前，向 sys.modules 注入带真实枚举的 src.models.banquet 桩
  2. 让 fake `src` 包的 __path__ 指向 banquet/src，使 `from src.agent import` 仍能找到真实 agent 文件
"""
import sys
import enum
import types
from pathlib import Path
from unittest.mock import MagicMock

agent_root = Path(__file__).resolve().parent.parent


# ── 1. 定义真实枚举类 (agent.py 和测试都会用到) ──────────────────────────────

class BanquetHallType(str, enum.Enum):
    MAIN_HALL   = "main_hall"
    PRIVATE_ROOM = "private_room"
    OUTDOOR     = "outdoor"

class BanquetTypeEnum(str, enum.Enum):
    WEDDING     = "wedding"
    BIRTHDAY    = "birthday"
    CONFERENCE  = "conference"
    OTHER       = "other"

class LeadStageEnum(str, enum.Enum):
    NEW              = "new"
    CONTACTED        = "contacted"
    VISIT_SCHEDULED  = "visit_scheduled"
    QUOTED           = "quoted"
    WAITING_DECISION = "waiting_decision"
    DEPOSIT_PENDING  = "deposit_pending"
    WON              = "won"
    LOST             = "lost"

class OrderStatusEnum(str, enum.Enum):
    DRAFT       = "draft"
    CONFIRMED   = "confirmed"
    PREPARING   = "preparing"
    IN_PROGRESS = "in_progress"
    COMPLETED   = "completed"
    SETTLED     = "settled"
    CLOSED      = "closed"
    CANCELLED   = "cancelled"

class DepositStatusEnum(str, enum.Enum):
    UNPAID  = "unpaid"
    PARTIAL = "partial"
    PAID    = "paid"

class TaskStatusEnum(str, enum.Enum):
    PENDING    = "pending"
    IN_PROGRESS = "in_progress"
    DONE       = "done"
    OVERDUE    = "overdue"
    SKIPPED    = "skipped"

class TaskOwnerRoleEnum(str, enum.Enum):
    purchase = "purchase"
    decor    = "decor"
    kitchen  = "kitchen"
    service  = "service"
    manager  = "manager"

class PaymentTypeEnum(str, enum.Enum):
    DEPOSIT  = "deposit"
    BALANCE  = "balance"
    FULL     = "full"
    REFUND   = "refund"

class BanquetAgentTypeEnum(str, enum.Enum):
    FOLLOWUP   = "followup"
    QUOTATION  = "quotation"
    SCHEDULING = "scheduling"
    EXECUTION  = "execution"
    REVIEW     = "review"


# ── 2. 构造桩模块 ─────────────────────────────────────────────────────────────

def _make_model_class(name: str):
    """返回一个可被实例化的 MagicMock 类（供 ExecutionTask 等使用）"""
    return MagicMock

# src.models.banquet 桩
_banquet_mod = types.ModuleType("src.models.banquet")
_banquet_mod.BanquetHallType        = BanquetHallType
_banquet_mod.BanquetTypeEnum        = BanquetTypeEnum
_banquet_mod.LeadStageEnum          = LeadStageEnum
_banquet_mod.OrderStatusEnum        = OrderStatusEnum
_banquet_mod.DepositStatusEnum      = DepositStatusEnum
_banquet_mod.TaskStatusEnum         = TaskStatusEnum
_banquet_mod.TaskOwnerRoleEnum      = TaskOwnerRoleEnum
_banquet_mod.PaymentTypeEnum        = PaymentTypeEnum
_banquet_mod.BanquetAgentTypeEnum   = BanquetAgentTypeEnum
# ORM 模型桩（测试里全部用 MagicMock 替代，这里只需要名字可 import）
# 用元类让 ClassName.column_attr 返回 MagicMock 而非 AttributeError

class _ColProxy:
    """仿 SQLAlchemy 列代理：支持比较运算符、算术运算、notin_、desc 等链式调用"""
    def __eq__(self, other):  return _ColProxy()
    def __ne__(self, other):  return _ColProxy()
    def __lt__(self, other):  return _ColProxy()
    def __le__(self, other):  return _ColProxy()
    def __gt__(self, other):  return _ColProxy()
    def __ge__(self, other):  return _ColProxy()
    def __hash__(self):       return id(self)
    def __bool__(self):       return True
    def __and__(self, other): return _ColProxy()
    def __or__(self, other):  return _ColProxy()
    def __mul__(self, other): return _ColProxy()
    def __rmul__(self, other): return _ColProxy()
    def __floordiv__(self, other): return _ColProxy()
    def __truediv__(self, other): return _ColProxy()
    def __add__(self, other): return _ColProxy()
    def __sub__(self, other): return _ColProxy()
    def notin_(self, *a, **kw): return _ColProxy()
    def in_(self, *a, **kw):    return _ColProxy()
    def desc(self):             return _ColProxy()
    def asc(self):              return _ColProxy()
    def is_(self, *a):          return _ColProxy()
    def ilike(self, *a):        return _ColProxy()
    def contains(self, *a):     return _ColProxy()
    def label(self, *a):        return _ColProxy()


def _orm_init(self, *args, **kwargs):
    """通用 ORM 桩构造函数：接收任意 kwargs 并存入实例"""
    for k, v in kwargs.items():
        setattr(self, k, v)


class _OrmStubMeta(type):
    """让类级别的属性访问返回 _ColProxy，支持 BanquetLead.store_id == x 这类表达式"""
    def __getattr__(cls, name):
        return _ColProxy()

def _make_orm_stub(name: str):
    return _OrmStubMeta(name, (), {'__init__': _orm_init})

for _cls in [
    "BanquetLead", "BanquetOrder", "BanquetHall", "BanquetHallBooking",
    "MenuPackage", "ExecutionTask", "ExecutionTemplate",
    "BanquetProfitSnapshot", "BanquetAgentActionLog",
    "BanquetCustomer", "LeadFollowupRecord", "BanquetQuote",
    "MenuPackageItem", "ExecutionException", "BanquetPaymentRecord",
    "BanquetContract", "BanquetKpiDaily", "BanquetAgentRule",
]:
    setattr(_banquet_mod, _cls, _make_orm_stub(_cls))

# src.models 桩
_models_mod = types.ModuleType("src.models")
_models_mod.banquet = _banquet_mod

# src 桩（关键：__path__ 指向 agent 的真实 src 目录，让 `from src.agent import` 生效）
_src_mod = types.ModuleType("src")
_src_mod.__path__ = [str(agent_root / "src")]
_src_mod.__package__ = "src"
_src_mod.models = _models_mod

# ── 3. 注入 sys.modules ───────────────────────────────────────────────────────
sys.modules.setdefault("src", _src_mod)
sys.modules.setdefault("src.models", _models_mod)
sys.modules.setdefault("src.models.banquet", _banquet_mod)

# agent_root 进路径，让 `from src.agent import` 找到真实文件
if str(agent_root) not in sys.path:
    sys.path.insert(0, str(agent_root))

# ── 4. 导入 agent 模块，并替换 SQLAlchemy 查询构建函数 ─────────────────────────
# 原因：select(MagicMock) 会被 SQLAlchemy 的类型检查拒绝；
#       但 db.execute 已被 AsyncMock 拦截，实际不需要构建真实 SQL。
import src.agent as _agent_module  # noqa: E402

def _chainable_mock(*_a, **_kw):
    """返回支持 .where/.order_by/.label 链式调用的 MagicMock"""
    m = MagicMock()
    m.where     = lambda *a, **kw: m
    m.order_by  = lambda *a, **kw: m
    m.label     = lambda *a, **kw: m
    m.notin_    = lambda *a, **kw: m
    m.desc      = lambda *a, **kw: m
    m.__eq__    = lambda self, other: m
    return m

_agent_module.select = _chainable_mock
_agent_module.func   = MagicMock(
    count=_chainable_mock,
    sum=_chainable_mock,
    avg=_chainable_mock,
)
_agent_module.and_ = MagicMock(side_effect=lambda *args: args[0] if args else MagicMock())
