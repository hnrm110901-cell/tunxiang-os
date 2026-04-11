"""tx-civic 合规领域枚举定义"""
import enum

class CivicDomain(str, enum.Enum):
    """监管领域"""
    trace = "trace"              # 食安追溯
    kitchen = "kitchen"          # 明厨亮灶
    env = "env"                  # 环保合规
    fire = "fire"                # 消防安全
    license = "license"          # 证照管理
    anti_waste = "anti_waste"    # 反食品浪费
    labor = "labor"              # 用工合规

class RegistrationStatus(str, enum.Enum):
    pending = "pending"
    registered = "registered"
    suspended = "suspended"

class SubmissionStatus(str, enum.Enum):
    pending = "pending"
    submitting = "submitting"
    accepted = "accepted"
    rejected = "rejected"
    retry = "retry"
    failed = "failed"

class SubmissionType(str, enum.Enum):
    auto = "auto"
    manual = "manual"
    scheduled = "scheduled"
    event_driven = "event_driven"

class RiskLevel(str, enum.Enum):
    green = "green"    # >=80分
    yellow = "yellow"  # >=60分
    red = "red"        # <60分

class LicenseType(str, enum.Enum):
    business_license = "business_license"        # 营业执照
    food_permit = "food_permit"                  # 食品经营许可证
    health_permit = "health_permit"              # 卫生许可证
    fire_cert = "fire_cert"                      # 消防安全证
    drain_permit = "drain_permit"                # 排水许可证
    env_permit = "env_permit"                    # 环保许可证
    special_food = "special_food"                # 特殊食品经营许可
    alcohol = "alcohol"                          # 酒类经营许可
    tobacco = "tobacco"                          # 烟草专卖许可

class RenewalStatus(str, enum.Enum):
    valid = "valid"
    expiring_soon = "expiring_soon"
    expired = "expired"
    renewing = "renewing"

class DeviceType(str, enum.Enum):
    camera = "camera"
    temperature_sensor = "temperature_sensor"
    humidity_sensor = "humidity_sensor"

class AlertType(str, enum.Enum):
    no_mask = "no_mask"                      # 未戴口罩
    no_cap = "no_cap"                        # 未戴帽子
    smoking = "smoking"                      # 吸烟
    rat = "rat"                              # 鼠患
    unauthorized_person = "unauthorized_person"  # 非授权人员
    dirty_surface = "dirty_surface"          # 操作台脏污
    other = "other"

class AlertSeverity(str, enum.Enum):
    info = "info"
    warning = "warning"
    critical = "critical"

class WasteType(str, enum.Enum):
    kitchen_waste = "kitchen_waste"      # 餐厨垃圾
    waste_oil = "waste_oil"              # 废弃油脂
    recyclable = "recyclable"            # 可回收
    hazardous = "hazardous"              # 有害垃圾
    other = "other"

class FireEquipmentType(str, enum.Enum):
    extinguisher = "extinguisher"         # 灭火器
    smoke_detector = "smoke_detector"     # 烟感
    sprinkler = "sprinkler"              # 喷淋
    gas_alarm = "gas_alarm"              # 燃气报警器
    fire_door = "fire_door"              # 防火门
    emergency_light = "emergency_light"   # 应急灯
    fire_hose = "fire_hose"              # 消防水带

class InspectionType(str, enum.Enum):
    routine = "routine"       # 日常
    monthly = "monthly"       # 月检
    quarterly = "quarterly"   # 季检
    annual = "annual"         # 年检
    special = "special"       # 专项

class ProductCategory(str, enum.Enum):
    meat = "meat"              # 肉类
    seafood = "seafood"        # 水产
    vegetable = "vegetable"    # 蔬菜
    frozen = "frozen"          # 冷冻品
    dry_goods = "dry_goods"    # 干货
    seasoning = "seasoning"    # 调味品
    dairy = "dairy"            # 乳制品
    grain = "grain"            # 粮油
    other = "other"
