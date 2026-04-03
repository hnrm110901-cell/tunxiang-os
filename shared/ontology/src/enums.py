"""Ontology 枚举定义"""
import enum


class OrderStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    preparing = "preparing"
    ready = "ready"
    served = "served"
    completed = "completed"
    cancelled = "cancelled"


class StoreStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    renovating = "renovating"
    preparing = "preparing"
    closed = "closed"


class InventoryStatus(str, enum.Enum):
    normal = "normal"
    low = "low"
    critical = "critical"
    out_of_stock = "out_of_stock"


class TransactionType(str, enum.Enum):
    purchase = "purchase"
    usage = "usage"
    waste = "waste"
    adjustment = "adjustment"
    transfer = "transfer"
    receiving = "receiving"        # 验收入库
    transfer_out = "transfer_out"  # 调拨出库
    transfer_in = "transfer_in"    # 调拨入库


class ReceivingOrderStatus(str, enum.Enum):
    draft = "draft"
    inspecting = "inspecting"
    partially_received = "partially_received"
    fully_received = "fully_received"
    rejected = "rejected"


class ReceivingItemStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    partial = "partial"
    rejected = "rejected"


class TransferOrderStatus(str, enum.Enum):
    draft = "draft"
    approved = "approved"
    shipped = "shipped"
    received = "received"
    cancelled = "cancelled"


class EmploymentStatus(str, enum.Enum):
    trial = "trial"
    probation = "probation"
    regular = "regular"
    resigned = "resigned"


class EmploymentType(str, enum.Enum):
    regular = "regular"
    part_time = "part_time"
    intern = "intern"
    trainee = "trainee"
    temp = "temp"


class StorageType(str, enum.Enum):
    frozen = "frozen"
    chilled = "chilled"
    ambient = "ambient"
    live = "live"


class RFMLevel(str, enum.Enum):
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"
    S5 = "S5"
