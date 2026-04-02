"""Forge 应用市场 — 第三方应用生态平台 (U3.3)

让第三方开发者在屯象OS上构建、发布、分发应用。
商业模式：上架费 + 交易抽成(30%) + API调用费

核心能力：
- 开发者注册与认证
- 应用提交、审核、上架全生命周期
- 租户级应用安装/卸载
- 沙箱测试环境
- 收入结算与分成（平台30%，开发者70%）
- 市场分析与趋势

金额单位统一为"分"（fen），与 V2.x 保持一致。
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  常量与配置
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

APP_CATEGORIES = {
    "supply_chain": {
        "name": "供应链对接",
        "icon": "truck",
        "description": "供应商ERP集成、采购管理",
    },
    "delivery": {
        "name": "外卖聚合",
        "icon": "bike",
        "description": "美团/饿了么/抖音统一管理",
    },
    "finance": {
        "name": "财务税务",
        "icon": "calculator",
        "description": "金蝶/用友/税务申报对接",
    },
    "ai_addon": {
        "name": "AI增值",
        "icon": "brain",
        "description": "语音点餐/AR菜单/智能客服",
    },
    "iot": {
        "name": "IoT设备",
        "icon": "cpu",
        "description": "温控/称重/能耗监测集成",
    },
    "analytics": {
        "name": "行业数据",
        "icon": "chart",
        "description": "行业报告/竞品分析/趋势预测",
    },
    "marketing": {
        "name": "营销工具",
        "icon": "megaphone",
        "description": "私域运营/社交裂变/短视频",
    },
    "hr": {
        "name": "人力资源",
        "icon": "users",
        "description": "招聘/培训/绩效/社保",
    },
    "payment": {
        "name": "支付集成",
        "icon": "credit-card",
        "description": "聚合支付/数字货币/分期",
    },
    "compliance": {
        "name": "合规安全",
        "icon": "shield",
        "description": "食安审计/证照管理/消防",
    },
}

PRICING_MODELS = {
    "free": {"name": "免费", "platform_fee_rate": 0.0},
    "one_time": {"name": "一次性买断", "platform_fee_rate": 0.30},
    "monthly": {"name": "月订阅", "platform_fee_rate": 0.30},
    "per_store": {"name": "按门店数", "platform_fee_rate": 0.30},
    "usage_based": {"name": "按用量", "platform_fee_rate": 0.20},
    "freemium": {"name": "基础免费+高级付费", "platform_fee_rate": 0.30},
}

DEV_TYPES = {"individual", "company", "isv"}

APP_STATUSES = {
    "draft",
    "pending_review",
    "approved",
    "rejected",
    "needs_changes",
    "published",
    "suspended",
    "deprecated",
}

REVIEW_DECISIONS = {"approved", "rejected", "needs_changes"}

PAYOUT_STATUSES = {"pending", "processing", "completed", "failed"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _gen_api_key() -> str:
    return f"txforge_{secrets.token_urlsafe(32)}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  预置示例应用数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _build_seed_developers() -> Dict[str, dict]:
    """构建预置开发者数据"""
    now = _now_iso()
    devs = {
        "dev_meituan": {
            "developer_id": "dev_meituan",
            "name": "美团外卖开放平台",
            "email": "open@meituan.com",
            "company": "北京三快在线科技有限公司",
            "dev_type": "company",
            "description": "美团外卖官方开放平台，提供订单/配送/评价等API对接能力",
            "status": "verified",
            "created_at": now,
            "updated_at": now,
        },
        "dev_kingdee": {
            "developer_id": "dev_kingdee",
            "name": "金蝶云星辰",
            "email": "openapi@kingdee.com",
            "company": "深圳市金蝶软件科技有限公司",
            "dev_type": "isv",
            "description": "金蝶云星辰智能财务平台，连接企业经营与财务管理",
            "status": "verified",
            "created_at": now,
            "updated_at": now,
        },
        "dev_txlabs": {
            "developer_id": "dev_txlabs",
            "name": "屯象AI实验室",
            "email": "labs@tunxiang.com",
            "company": "屯象科技（湖南）有限公司",
            "dev_type": "company",
            "description": "屯象OS官方AI增值服务，语音点餐/智能客服/AR菜单",
            "status": "verified",
            "created_at": now,
            "updated_at": now,
        },
        "dev_hailan": {
            "developer_id": "dev_hailan",
            "name": "海蓝物联",
            "email": "dev@hailan-iot.com",
            "company": "广州海蓝物联科技有限公司",
            "dev_type": "company",
            "description": "餐饮IoT解决方案提供商，海鲜池温控/冷链监测/能耗管理",
            "status": "verified",
            "created_at": now,
            "updated_at": now,
        },
        "dev_safecheck": {
            "developer_id": "dev_safecheck",
            "name": "食安卫士",
            "email": "dev@safecheck.cn",
            "company": "杭州食安卫士科技有限公司",
            "dev_type": "company",
            "description": "餐饮食品安全巡检与合规管理平台",
            "status": "verified",
            "created_at": now,
            "updated_at": now,
        },
        "dev_douyin": {
            "developer_id": "dev_douyin",
            "name": "抖音本地生活",
            "email": "locallife-dev@bytedance.com",
            "company": "北京字节跳动科技有限公司",
            "dev_type": "company",
            "description": "抖音本地生活官方开放平台，短视频/直播/团购券核销",
            "status": "verified",
            "created_at": now,
            "updated_at": now,
        },
        "dev_supplydirect": {
            "developer_id": "dev_supplydirect",
            "name": "供直达",
            "email": "dev@supplydirect.cn",
            "company": "成都供直达科技有限公司",
            "dev_type": "isv",
            "description": "餐饮供应链B2B平台，连接餐企与优质供应商",
            "status": "verified",
            "created_at": now,
            "updated_at": now,
        },
    }
    return devs


def _build_seed_apps() -> Dict[str, dict]:
    """构建预置示例应用数据"""
    now = _now_iso()
    apps = {
        "app_meituan_delivery": {
            "app_id": "app_meituan_delivery",
            "developer_id": "dev_meituan",
            "app_name": "美团外卖聚合",
            "category": "delivery",
            "description": (
                "美团外卖官方对接插件。自动接单、订单状态同步、配送轨迹追踪、"
                "差评预警、经营数据看板。支持多店统一管理，日均处理10万+订单。"
            ),
            "version": "2.4.1",
            "icon_url": "/icons/meituan-delivery.png",
            "screenshots": [
                "/screenshots/meituan-1.png",
                "/screenshots/meituan-2.png",
                "/screenshots/meituan-3.png",
            ],
            "pricing_model": "monthly",
            "price_fen": 29900,  # 299元/月/门店
            "price_display": "299元/月/门店",
            "permissions": ["order.read", "order.write", "menu.read", "store.read"],
            "api_endpoints": ["/api/v1/meituan/orders", "/api/v1/meituan/menu-sync"],
            "webhook_urls": ["https://callback.meituan.com/txos/order"],
            "status": "published",
            "rating": 4.7,
            "rating_count": 328,
            "install_count": 8560,
            "revenue_total_fen": 25680000,  # 累计收入 256,800 元
            "created_at": now,
            "updated_at": now,
            "published_at": now,
        },
        "app_kingdee_voucher": {
            "app_id": "app_kingdee_voucher",
            "developer_id": "dev_kingdee",
            "app_name": "金蝶云凭证",
            "category": "finance",
            "description": (
                "屯象OS经营数据自动生成金蝶记账凭证。日结数据→收入/成本/费用凭证，"
                "一键推送金蝶云星辰。支持多品牌合并报表，省去财务手工录入。"
            ),
            "version": "1.8.0",
            "icon_url": "/icons/kingdee-voucher.png",
            "screenshots": [
                "/screenshots/kingdee-1.png",
                "/screenshots/kingdee-2.png",
            ],
            "pricing_model": "monthly",
            "price_fen": 19900,  # 199元/月/门店
            "price_display": "199元/月/门店",
            "permissions": ["finance.read", "order.read", "store.read"],
            "api_endpoints": ["/api/v1/kingdee/vouchers", "/api/v1/kingdee/sync"],
            "webhook_urls": ["https://openapi.kingdee.com/txos/callback"],
            "status": "published",
            "rating": 4.5,
            "rating_count": 186,
            "install_count": 3240,
            "revenue_total_fen": 6447600,  # 累计收入 64,476 元
            "created_at": now,
            "updated_at": now,
            "published_at": now,
        },
        "app_voice_ordering": {
            "app_id": "app_voice_ordering",
            "developer_id": "dev_txlabs",
            "app_name": "智能语音点餐",
            "category": "ai_addon",
            "description": (
                "基于屯象AI引擎的语音点餐能力。顾客用自然语言下单，"
                "支持方言识别（湘/粤/川）、模糊菜名匹配、智能推荐加购。"
                "平均每桌节省2分钟点餐时间。"
            ),
            "version": "3.1.2",
            "icon_url": "/icons/voice-ordering.png",
            "screenshots": [
                "/screenshots/voice-1.png",
                "/screenshots/voice-2.png",
                "/screenshots/voice-3.png",
            ],
            "pricing_model": "usage_based",
            "price_fen": 10,  # 0.1元/次调用
            "price_display": "0.1元/次调用",
            "permissions": ["menu.read", "order.write", "ai.inference"],
            "api_endpoints": ["/api/v1/voice/transcribe", "/api/v1/voice/order"],
            "webhook_urls": [],
            "status": "published",
            "rating": 4.8,
            "rating_count": 412,
            "install_count": 2150,
            "revenue_total_fen": 4320000,  # 累计收入 43,200 元
            "created_at": now,
            "updated_at": now,
            "published_at": now,
        },
        "app_seafood_tank": {
            "app_id": "app_seafood_tank",
            "developer_id": "dev_hailan",
            "app_name": "海鲜池温控",
            "category": "iot",
            "description": (
                "海鲜池水温/盐度/溶氧实时监测。异常自动报警，"
                "历史数据趋势分析，设备远程控制。减少海鲜损耗30%+。"
                "支持多种品牌水循环设备对接。"
            ),
            "version": "1.5.3",
            "icon_url": "/icons/seafood-tank.png",
            "screenshots": [
                "/screenshots/tank-1.png",
                "/screenshots/tank-2.png",
            ],
            "pricing_model": "per_store",
            "price_fen": 9900,  # 99元/门店/月
            "price_display": "99元/门店/月",
            "permissions": ["iot.read", "iot.write", "store.read", "alert.write"],
            "api_endpoints": ["/api/v1/iot/tank/status", "/api/v1/iot/tank/control"],
            "webhook_urls": ["https://api.hailan-iot.com/txos/alert"],
            "status": "published",
            "rating": 4.6,
            "rating_count": 95,
            "install_count": 680,
            "revenue_total_fen": 673200,  # 累计收入 6,732 元
            "created_at": now,
            "updated_at": now,
            "published_at": now,
        },
        "app_food_safety": {
            "app_id": "app_food_safety",
            "developer_id": "dev_safecheck",
            "app_name": "食安巡检助手",
            "category": "compliance",
            "description": (
                "食品安全巡检数字化工具。每日巡检清单、拍照留痕、"
                "自动生成合规报告。对接市监局明厨亮灶系统，"
                "证照到期自动提醒。完全免费，食安无小事。"
            ),
            "version": "2.0.1",
            "icon_url": "/icons/food-safety.png",
            "screenshots": [
                "/screenshots/safety-1.png",
                "/screenshots/safety-2.png",
                "/screenshots/safety-3.png",
            ],
            "pricing_model": "free",
            "price_fen": 0,
            "price_display": "免费",
            "permissions": ["store.read", "compliance.read", "compliance.write"],
            "api_endpoints": ["/api/v1/safety/checklists", "/api/v1/safety/reports"],
            "webhook_urls": [],
            "status": "published",
            "rating": 4.9,
            "rating_count": 520,
            "install_count": 12300,
            "revenue_total_fen": 0,
            "created_at": now,
            "updated_at": now,
            "published_at": now,
        },
        "app_douyin_marketing": {
            "app_id": "app_douyin_marketing",
            "developer_id": "dev_douyin",
            "app_name": "抖音营销",
            "category": "marketing",
            "description": (
                "抖音本地生活一站式营销。团购券创建与核销、"
                "达人探店邀约管理、短视频素材库、直播预约引流。"
                "ROI数据实时追踪，营销效果一目了然。"
            ),
            "version": "1.9.4",
            "icon_url": "/icons/douyin-marketing.png",
            "screenshots": [
                "/screenshots/douyin-1.png",
                "/screenshots/douyin-2.png",
                "/screenshots/douyin-3.png",
            ],
            "pricing_model": "monthly",
            "price_fen": 39900,  # 399元/月
            "price_display": "399元/月",
            "permissions": ["store.read", "order.read", "marketing.read", "marketing.write"],
            "api_endpoints": ["/api/v1/douyin/coupons", "/api/v1/douyin/analytics"],
            "webhook_urls": ["https://openapi.douyin.com/txos/coupon-verify"],
            "status": "published",
            "rating": 4.4,
            "rating_count": 267,
            "install_count": 4820,
            "revenue_total_fen": 19240800,  # 累计收入 192,408 元
            "created_at": now,
            "updated_at": now,
            "published_at": now,
        },
        "app_supplier_direct": {
            "app_id": "app_supplier_direct",
            "developer_id": "dev_supplydirect",
            "app_name": "供应商直连",
            "category": "supply_chain",
            "description": (
                "餐企与供应商直连平台。基础功能免费：供应商目录、"
                "询比价、下单。高级版：智能补货预测、合同管理、"
                "质检追溯、账期管理。去掉中间商，采购成本降低10-15%。"
            ),
            "version": "2.2.0",
            "icon_url": "/icons/supplier-direct.png",
            "screenshots": [
                "/screenshots/supplier-1.png",
                "/screenshots/supplier-2.png",
            ],
            "pricing_model": "freemium",
            "price_fen": 0,  # 基础免费
            "price_display": "基础免费 / 高级版599元/月",
            "permissions": ["supply.read", "supply.write", "ingredient.read", "ingredient.write"],
            "api_endpoints": ["/api/v1/supplier/catalog", "/api/v1/supplier/orders"],
            "webhook_urls": ["https://api.supplydirect.cn/txos/order-status"],
            "status": "published",
            "rating": 4.3,
            "rating_count": 142,
            "install_count": 1890,
            "revenue_total_fen": 3402000,  # 累计收入 34,020 元
            "created_at": now,
            "updated_at": now,
            "published_at": now,
        },
    }
    return apps


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Forge 应用市场服务
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ForgeMarketplaceService:
    """Forge 应用市场 — 第三方应用生态平台

    让第三方开发者在屯象OS上构建、发布、分发应用。
    商业模式：上架费 + 交易抽成(30%) + API调用费
    """

    def __init__(self, seed_data: bool = True) -> None:
        # 内存存储（纯函数风格，生产环境接 DB）
        self._developers: Dict[str, dict] = {}
        self._apps: Dict[str, dict] = {}
        self._reviews: Dict[str, list[dict]] = {}  # app_id -> [review_records]
        self._installations: Dict[str, dict] = {}  # "{tenant_id}:{app_id}" -> install_record
        self._api_keys: Dict[str, dict] = {}  # key_id -> key_record
        self._sandboxes: Dict[str, dict] = {}  # sandbox_id -> sandbox_record
        self._payouts: Dict[str, list[dict]] = {}  # developer_id -> [payout_records]
        self._app_revenue_log: Dict[str, list[dict]] = {}  # app_id -> [revenue_entries]

        if seed_data:
            self._developers = _build_seed_developers()
            self._apps = _build_seed_apps()

    # ──────────────────────────────────────────────────────
    #  1. Developer Management（开发者管理）
    # ──────────────────────────────────────────────────────

    def register_developer(
        self,
        name: str,
        email: str,
        company: str,
        dev_type: str,
        description: str = "",
    ) -> dict:
        """注册开发者

        Args:
            name: 开发者名称
            email: 联系邮箱
            company: 公司名称
            dev_type: 类型 (individual/company/isv)
            description: 简介

        Returns:
            developer_id, api_key, sandbox_url
        """
        if dev_type not in DEV_TYPES:
            raise ValueError(f"无效开发者类型: {dev_type}，可选: {DEV_TYPES}")

        developer_id = _gen_id("dev")
        api_key = _gen_api_key()
        now = _now_iso()

        developer = {
            "developer_id": developer_id,
            "name": name,
            "email": email,
            "company": company,
            "dev_type": dev_type,
            "description": description,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        self._developers[developer_id] = developer

        # 自动生成一个默认 API key
        key_id = _gen_id("key")
        self._api_keys[key_id] = {
            "key_id": key_id,
            "developer_id": developer_id,
            "key_name": "默认密钥",
            "api_key": api_key,
            "permissions": ["read", "write"],
            "status": "active",
            "created_at": now,
        }

        return {
            "developer_id": developer_id,
            "api_key": api_key,
            "sandbox_url": f"https://sandbox.forge.tunxiangos.com/{developer_id}",
            "status": "active",
            "created_at": now,
        }

    def get_developer_profile(self, developer_id: str) -> dict:
        """获取开发者档案"""
        dev = self._developers.get(developer_id)
        if not dev:
            raise ValueError(f"开发者不存在: {developer_id}")

        # 统计该开发者的应用数和总安装量
        dev_apps = [a for a in self._apps.values() if a["developer_id"] == developer_id]
        total_installs = sum(a.get("install_count", 0) for a in dev_apps)

        return {
            **dev,
            "app_count": len(dev_apps),
            "total_installs": total_installs,
        }

    def update_developer(self, developer_id: str, updates: dict) -> dict:
        """更新开发者信息

        Args:
            developer_id: 开发者ID
            updates: 可更新字段 (name, email, company, description)

        Returns:
            更新后的开发者信息
        """
        dev = self._developers.get(developer_id)
        if not dev:
            raise ValueError(f"开发者不存在: {developer_id}")

        allowed_fields = {"name", "email", "company", "description"}
        for key, value in updates.items():
            if key in allowed_fields:
                dev[key] = value

        dev["updated_at"] = _now_iso()
        return dev

    def list_developers(self, status: Optional[str] = None) -> list[dict]:
        """列出开发者

        Args:
            status: 可选，按状态筛选 (active/verified/suspended)

        Returns:
            开发者列表
        """
        devs = list(self._developers.values())
        if status:
            devs = [d for d in devs if d.get("status") == status]
        return devs

    # ──────────────────────────────────────────────────────
    #  2. Application Lifecycle（应用生命周期）
    # ──────────────────────────────────────────────────────

    def submit_app(
        self,
        developer_id: str,
        app_name: str,
        category: str,
        description: str,
        version: str,
        icon_url: str = "",
        screenshots: Optional[list[str]] = None,
        pricing_model: str = "free",
        price_fen: int = 0,
        permissions: Optional[list[str]] = None,
        api_endpoints: Optional[list[str]] = None,
        webhook_urls: Optional[list[str]] = None,
    ) -> dict:
        """提交应用

        Args:
            developer_id: 开发者ID
            app_name: 应用名称
            category: 分类 (见 APP_CATEGORIES)
            description: 应用描述
            version: 版本号
            icon_url: 图标URL
            screenshots: 截图URL列表
            pricing_model: 定价模式 (见 PRICING_MODELS)
            price_fen: 价格（分）
            permissions: 所需权限列表
            api_endpoints: API端点列表
            webhook_urls: Webhook URL列表

        Returns:
            app_id, status="pending_review"
        """
        if developer_id not in self._developers:
            raise ValueError(f"开发者不存在: {developer_id}")
        if category not in APP_CATEGORIES:
            raise ValueError(f"无效分类: {category}，可选: {list(APP_CATEGORIES.keys())}")
        if pricing_model not in PRICING_MODELS:
            raise ValueError(f"无效定价模式: {pricing_model}，可选: {list(PRICING_MODELS.keys())}")

        app_id = _gen_id("app")
        now = _now_iso()

        # 生成价格显示文本
        pricing_info = PRICING_MODELS[pricing_model]
        if pricing_model == "free":
            price_display = "免费"
        elif pricing_model == "freemium":
            price_display = f"基础免费 / 高级版{price_fen / 100:.0f}元/月"
        elif pricing_model == "usage_based":
            price_display = f"{price_fen / 100:.2f}元/次调用"
        elif pricing_model == "per_store":
            price_display = f"{price_fen / 100:.0f}元/门店/月"
        else:
            price_display = f"{price_fen / 100:.0f}元/月"

        app = {
            "app_id": app_id,
            "developer_id": developer_id,
            "app_name": app_name,
            "category": category,
            "description": description,
            "version": version,
            "icon_url": icon_url,
            "screenshots": screenshots or [],
            "pricing_model": pricing_model,
            "price_fen": price_fen,
            "price_display": price_display,
            "permissions": permissions or [],
            "api_endpoints": api_endpoints or [],
            "webhook_urls": webhook_urls or [],
            "status": "pending_review",
            "rating": 0.0,
            "rating_count": 0,
            "install_count": 0,
            "revenue_total_fen": 0,
            "created_at": now,
            "updated_at": now,
            "published_at": None,
        }
        self._apps[app_id] = app

        return {
            "app_id": app_id,
            "app_name": app_name,
            "status": "pending_review",
            "created_at": now,
        }

    def update_app(self, app_id: str, updates: dict) -> dict:
        """更新应用信息

        Args:
            app_id: 应用ID
            updates: 可更新字段

        Returns:
            更新后的应用信息
        """
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"应用不存在: {app_id}")

        allowed_fields = {
            "app_name", "description", "version", "icon_url",
            "screenshots", "pricing_model", "price_fen",
            "permissions", "api_endpoints", "webhook_urls",
        }

        for key, value in updates.items():
            if key in allowed_fields:
                app[key] = value

        app["updated_at"] = _now_iso()
        return app

    def list_apps(
        self,
        category: Optional[str] = None,
        status: Optional[str] = None,
        sort_by: str = "popularity",
    ) -> list[dict]:
        """列出应用

        Args:
            category: 按分类筛选
            status: 按状态筛选
            sort_by: 排序方式 (popularity/newest/rating/price)

        Returns:
            应用列表
        """
        apps = list(self._apps.values())

        if category:
            apps = [a for a in apps if a["category"] == category]
        if status:
            apps = [a for a in apps if a["status"] == status]

        sort_keys = {
            "popularity": lambda a: a.get("install_count", 0),
            "newest": lambda a: a.get("created_at", ""),
            "rating": lambda a: a.get("rating", 0),
            "price": lambda a: a.get("price_fen", 0),
        }
        sort_fn = sort_keys.get(sort_by, sort_keys["popularity"])
        reverse = sort_by != "price"
        apps.sort(key=sort_fn, reverse=reverse)

        return apps

    def get_app_detail(self, app_id: str) -> dict:
        """获取应用详情

        Args:
            app_id: 应用ID

        Returns:
            应用详情（含开发者信息和分类信息）
        """
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"应用不存在: {app_id}")

        developer = self._developers.get(app["developer_id"], {})
        category_info = APP_CATEGORIES.get(app["category"], {})
        pricing_info = PRICING_MODELS.get(app["pricing_model"], {})

        return {
            **app,
            "developer_name": developer.get("name", ""),
            "developer_company": developer.get("company", ""),
            "category_name": category_info.get("name", ""),
            "category_icon": category_info.get("icon", ""),
            "pricing_model_name": pricing_info.get("name", ""),
            "platform_fee_rate": pricing_info.get("platform_fee_rate", 0),
        }

    def search_apps(self, query: str) -> list[dict]:
        """搜索应用

        基于名称、描述、分类名称进行模糊匹配。

        Args:
            query: 搜索关键词

        Returns:
            匹配的应用列表
        """
        if not query or not query.strip():
            return self.list_apps(status="published")

        query_lower = query.lower().strip()
        results = []

        for app in self._apps.values():
            # 搜索范围：应用名、描述、分类名
            cat_name = APP_CATEGORIES.get(app["category"], {}).get("name", "")
            searchable = f"{app['app_name']} {app['description']} {cat_name}".lower()

            if query_lower in searchable:
                results.append(app)

        # 按安装量排序
        results.sort(key=lambda a: a.get("install_count", 0), reverse=True)
        return results

    # ──────────────────────────────────────────────────────
    #  3. Review & Approval（审核）
    # ──────────────────────────────────────────────────────

    def review_app(
        self,
        app_id: str,
        reviewer_id: str,
        decision: str,
        review_notes: str = "",
    ) -> dict:
        """审核应用

        Args:
            app_id: 应用ID
            reviewer_id: 审核人ID
            decision: 审核结果 (approved/rejected/needs_changes)
            review_notes: 审核备注

        Returns:
            审核记录
        """
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"应用不存在: {app_id}")
        if decision not in REVIEW_DECISIONS:
            raise ValueError(f"无效审核结果: {decision}，可选: {REVIEW_DECISIONS}")

        now = _now_iso()
        review_id = _gen_id("rev")

        review_record = {
            "review_id": review_id,
            "app_id": app_id,
            "reviewer_id": reviewer_id,
            "decision": decision,
            "review_notes": review_notes,
            "reviewed_at": now,
        }

        # 记录审核历史
        if app_id not in self._reviews:
            self._reviews[app_id] = []
        self._reviews[app_id].append(review_record)

        # 更新应用状态
        if decision == "approved":
            app["status"] = "published"
            app["published_at"] = now
        elif decision == "rejected":
            app["status"] = "rejected"
        elif decision == "needs_changes":
            app["status"] = "needs_changes"

        app["updated_at"] = now

        return {
            **review_record,
            "app_name": app["app_name"],
            "new_status": app["status"],
        }

    def get_pending_reviews(self) -> list[dict]:
        """获取待审核应用列表"""
        pending = []
        for app in self._apps.values():
            if app["status"] == "pending_review":
                developer = self._developers.get(app["developer_id"], {})
                pending.append({
                    "app_id": app["app_id"],
                    "app_name": app["app_name"],
                    "developer_name": developer.get("name", ""),
                    "category": app["category"],
                    "version": app["version"],
                    "submitted_at": app["created_at"],
                })
        return pending

    def get_review_history(self, app_id: str) -> list[dict]:
        """获取应用审核历史

        Args:
            app_id: 应用ID

        Returns:
            审核记录列表（按时间倒序）
        """
        if app_id not in self._apps:
            raise ValueError(f"应用不存在: {app_id}")

        records = self._reviews.get(app_id, [])
        return sorted(records, key=lambda r: r["reviewed_at"], reverse=True)

    # ──────────────────────────────────────────────────────
    #  4. Installation & Subscription（安装/订阅）
    # ──────────────────────────────────────────────────────

    def install_app(
        self,
        tenant_id: str,
        app_id: str,
        store_ids: Optional[list[str]] = None,
    ) -> dict:
        """为租户安装应用

        Args:
            tenant_id: 租户ID
            app_id: 应用ID
            store_ids: 可选，限定安装到指定门店

        Returns:
            安装记录
        """
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"应用不存在: {app_id}")
        if app["status"] != "published":
            raise ValueError(f"应用未发布，当前状态: {app['status']}")

        install_key = f"{tenant_id}:{app_id}"
        if install_key in self._installations:
            raise ValueError(f"应用已安装: {app['app_name']}")

        now = _now_iso()
        install_id = _gen_id("inst")

        installation = {
            "install_id": install_id,
            "tenant_id": tenant_id,
            "app_id": app_id,
            "app_name": app["app_name"],
            "store_ids": store_ids or [],
            "status": "active",
            "installed_at": now,
        }
        self._installations[install_key] = installation

        # 增加应用安装计数
        app["install_count"] = app.get("install_count", 0) + 1

        # 如果是付费应用，记录收入
        if app["price_fen"] > 0:
            self._record_revenue(app_id, tenant_id, app["price_fen"])

        return installation

    def uninstall_app(self, tenant_id: str, app_id: str) -> dict:
        """卸载应用

        Args:
            tenant_id: 租户ID
            app_id: 应用ID

        Returns:
            卸载确认
        """
        install_key = f"{tenant_id}:{app_id}"
        installation = self._installations.get(install_key)
        if not installation:
            raise ValueError(f"应用未安装: {app_id}")

        installation["status"] = "uninstalled"
        installation["uninstalled_at"] = _now_iso()

        # 减少安装计数
        app = self._apps.get(app_id)
        if app:
            app["install_count"] = max(0, app.get("install_count", 0) - 1)

        return {
            "tenant_id": tenant_id,
            "app_id": app_id,
            "status": "uninstalled",
            "uninstalled_at": installation["uninstalled_at"],
        }

    def list_installed_apps(self, tenant_id: str) -> list[dict]:
        """列出租户已安装的应用

        Args:
            tenant_id: 租户ID

        Returns:
            已安装应用列表
        """
        installed = []
        for key, inst in self._installations.items():
            if inst["tenant_id"] == tenant_id and inst["status"] == "active":
                app = self._apps.get(inst["app_id"], {})
                installed.append({
                    **inst,
                    "app_name": app.get("app_name", ""),
                    "category": app.get("category", ""),
                    "version": app.get("version", ""),
                    "pricing_model": app.get("pricing_model", ""),
                    "price_display": app.get("price_display", ""),
                })
        return installed

    def get_installation_status(self, tenant_id: str, app_id: str) -> dict:
        """查询安装状态

        Args:
            tenant_id: 租户ID
            app_id: 应用ID

        Returns:
            安装状态信息
        """
        install_key = f"{tenant_id}:{app_id}"
        installation = self._installations.get(install_key)
        if not installation:
            return {
                "tenant_id": tenant_id,
                "app_id": app_id,
                "installed": False,
                "status": "not_installed",
            }

        return {
            "tenant_id": tenant_id,
            "app_id": app_id,
            "installed": installation["status"] == "active",
            "status": installation["status"],
            "installed_at": installation.get("installed_at"),
            "store_ids": installation.get("store_ids", []),
        }

    # ──────────────────────────────────────────────────────
    #  5. SDK & API Keys（开发者工具）
    # ──────────────────────────────────────────────────────

    def generate_api_key(
        self,
        developer_id: str,
        key_name: str,
        permissions: Optional[list[str]] = None,
    ) -> dict:
        """生成 API Key

        Args:
            developer_id: 开发者ID
            key_name: 密钥名称
            permissions: 权限列表

        Returns:
            key_id, api_key, permissions
        """
        if developer_id not in self._developers:
            raise ValueError(f"开发者不存在: {developer_id}")

        key_id = _gen_id("key")
        api_key = _gen_api_key()
        now = _now_iso()

        key_record = {
            "key_id": key_id,
            "developer_id": developer_id,
            "key_name": key_name,
            "api_key": api_key,
            "permissions": permissions or ["read"],
            "status": "active",
            "created_at": now,
            "last_used_at": None,
            "usage_count": 0,
        }
        self._api_keys[key_id] = key_record

        return {
            "key_id": key_id,
            "api_key": api_key,
            "key_name": key_name,
            "permissions": key_record["permissions"],
            "created_at": now,
        }

    def revoke_api_key(self, key_id: str) -> dict:
        """撤销 API Key

        Args:
            key_id: 密钥ID

        Returns:
            撤销确认
        """
        key = self._api_keys.get(key_id)
        if not key:
            raise ValueError(f"密钥不存在: {key_id}")

        key["status"] = "revoked"
        key["revoked_at"] = _now_iso()

        return {
            "key_id": key_id,
            "key_name": key["key_name"],
            "status": "revoked",
            "revoked_at": key["revoked_at"],
        }

    def list_api_keys(self, developer_id: str) -> list[dict]:
        """列出开发者的 API Key

        Args:
            developer_id: 开发者ID

        Returns:
            密钥列表（不含完整密钥，仅前8位）
        """
        if developer_id not in self._developers:
            raise ValueError(f"开发者不存在: {developer_id}")

        keys = []
        for key in self._api_keys.values():
            if key["developer_id"] == developer_id:
                # 安全：仅显示密钥前缀
                masked_key = key["api_key"][:16] + "..." if key.get("api_key") else ""
                keys.append({
                    "key_id": key["key_id"],
                    "key_name": key["key_name"],
                    "api_key_prefix": masked_key,
                    "permissions": key["permissions"],
                    "status": key["status"],
                    "created_at": key["created_at"],
                    "last_used_at": key.get("last_used_at"),
                    "usage_count": key.get("usage_count", 0),
                })
        return keys

    def get_api_usage(self, developer_id: str, period: str = "month") -> dict:
        """获取 API 使用统计

        Args:
            developer_id: 开发者ID
            period: 统计周期 (day/week/month)

        Returns:
            API调用统计
        """
        if developer_id not in self._developers:
            raise ValueError(f"开发者不存在: {developer_id}")

        # 统计该开发者所有 key 的使用量
        total_calls = 0
        key_breakdown = []
        for key in self._api_keys.values():
            if key["developer_id"] == developer_id and key["status"] == "active":
                usage = key.get("usage_count", 0)
                total_calls += usage
                key_breakdown.append({
                    "key_id": key["key_id"],
                    "key_name": key["key_name"],
                    "usage_count": usage,
                })

        # 模拟用量限制
        quota = 100000 if self._developers[developer_id].get("dev_type") == "company" else 10000

        return {
            "developer_id": developer_id,
            "period": period,
            "total_calls": total_calls,
            "quota": quota,
            "usage_rate": round(total_calls / quota * 100, 2) if quota > 0 else 0,
            "key_breakdown": key_breakdown,
        }

    # ──────────────────────────────────────────────────────
    #  6. Sandbox Environment（沙箱测试）
    # ──────────────────────────────────────────────────────

    def create_sandbox(self, developer_id: str, app_id: str) -> dict:
        """创建沙箱测试环境

        Args:
            developer_id: 开发者ID
            app_id: 应用ID

        Returns:
            sandbox_url, test_tenant_id, test_api_key, expires_at
        """
        if developer_id not in self._developers:
            raise ValueError(f"开发者不存在: {developer_id}")
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"应用不存在: {app_id}")
        if app["developer_id"] != developer_id:
            raise ValueError("只能为自己的应用创建沙箱")

        sandbox_id = _gen_id("sandbox")
        test_tenant_id = _gen_id("test_tenant")
        test_api_key = _gen_api_key()
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(days=7)).isoformat()

        sandbox = {
            "sandbox_id": sandbox_id,
            "developer_id": developer_id,
            "app_id": app_id,
            "sandbox_url": f"https://sandbox.forge.tunxiangos.com/{sandbox_id}",
            "test_tenant_id": test_tenant_id,
            "test_api_key": test_api_key,
            "status": "running",
            "created_at": now.isoformat(),
            "expires_at": expires_at,
            "test_data": {
                "stores": ["test_store_001", "test_store_002"],
                "menu_items": 56,
                "employees": 12,
                "orders_today": 128,
            },
        }
        self._sandboxes[sandbox_id] = sandbox

        return {
            "sandbox_id": sandbox_id,
            "sandbox_url": sandbox["sandbox_url"],
            "test_tenant_id": test_tenant_id,
            "test_api_key": test_api_key,
            "expires_at": expires_at,
            "test_data": sandbox["test_data"],
        }

    def get_sandbox_status(self, sandbox_id: str) -> dict:
        """查询沙箱状态

        Args:
            sandbox_id: 沙箱ID

        Returns:
            沙箱状态信息
        """
        sandbox = self._sandboxes.get(sandbox_id)
        if not sandbox:
            raise ValueError(f"沙箱不存在: {sandbox_id}")

        return {
            "sandbox_id": sandbox_id,
            "status": sandbox["status"],
            "sandbox_url": sandbox["sandbox_url"],
            "created_at": sandbox["created_at"],
            "expires_at": sandbox["expires_at"],
            "test_data": sandbox["test_data"],
        }

    def delete_sandbox(self, sandbox_id: str) -> dict:
        """删除沙箱

        Args:
            sandbox_id: 沙箱ID

        Returns:
            删除确认
        """
        sandbox = self._sandboxes.get(sandbox_id)
        if not sandbox:
            raise ValueError(f"沙箱不存在: {sandbox_id}")

        sandbox["status"] = "deleted"
        sandbox["deleted_at"] = _now_iso()

        return {
            "sandbox_id": sandbox_id,
            "status": "deleted",
            "deleted_at": sandbox["deleted_at"],
        }

    # ──────────────────────────────────────────────────────
    #  7. Revenue & Settlement（收入结算）
    # ──────────────────────────────────────────────────────

    def _record_revenue(self, app_id: str, tenant_id: str, amount_fen: int) -> None:
        """内部方法：记录收入条目"""
        app = self._apps.get(app_id)
        if not app:
            return

        pricing_model = app.get("pricing_model", "free")
        fee_rate = PRICING_MODELS.get(pricing_model, {}).get("platform_fee_rate", 0.30)
        platform_fee = int(amount_fen * fee_rate)
        developer_payout = amount_fen - platform_fee

        entry = {
            "app_id": app_id,
            "tenant_id": tenant_id,
            "amount_fen": amount_fen,
            "platform_fee_fen": platform_fee,
            "developer_payout_fen": developer_payout,
            "fee_rate": fee_rate,
            "created_at": _now_iso(),
        }

        if app_id not in self._app_revenue_log:
            self._app_revenue_log[app_id] = []
        self._app_revenue_log[app_id].append(entry)

        # 更新应用累计收入
        app["revenue_total_fen"] = app.get("revenue_total_fen", 0) + amount_fen

    def get_developer_revenue(self, developer_id: str, period: str = "month") -> dict:
        """获取开发者收入

        Args:
            developer_id: 开发者ID
            period: 统计周期 (day/week/month/quarter/year)

        Returns:
            total_revenue, platform_fee(30%), developer_payout
        """
        if developer_id not in self._developers:
            raise ValueError(f"开发者不存在: {developer_id}")

        # 汇总该开发者所有应用的收入
        total_revenue = 0
        total_platform_fee = 0
        total_payout = 0
        app_breakdown = []

        for app in self._apps.values():
            if app["developer_id"] != developer_id:
                continue

            entries = self._app_revenue_log.get(app["app_id"], [])
            app_revenue = sum(e["amount_fen"] for e in entries)
            app_fee = sum(e["platform_fee_fen"] for e in entries)
            app_payout = sum(e["developer_payout_fen"] for e in entries)

            total_revenue += app_revenue
            total_platform_fee += app_fee
            total_payout += app_payout

            if app_revenue > 0:
                app_breakdown.append({
                    "app_id": app["app_id"],
                    "app_name": app["app_name"],
                    "revenue_fen": app_revenue,
                    "platform_fee_fen": app_fee,
                    "developer_payout_fen": app_payout,
                    "install_count": app.get("install_count", 0),
                })

        return {
            "developer_id": developer_id,
            "period": period,
            "total_revenue_fen": total_revenue,
            "platform_fee_fen": total_platform_fee,
            "developer_payout_fen": total_payout,
            "platform_fee_rate": 0.30,
            "app_breakdown": app_breakdown,
        }

    def get_app_revenue(self, app_id: str, period: str = "month") -> dict:
        """获取应用收入

        Args:
            app_id: 应用ID
            period: 统计周期

        Returns:
            应用收入明细
        """
        app = self._apps.get(app_id)
        if not app:
            raise ValueError(f"应用不存在: {app_id}")

        entries = self._app_revenue_log.get(app_id, [])
        total_revenue = sum(e["amount_fen"] for e in entries)
        platform_fee = sum(e["platform_fee_fen"] for e in entries)
        developer_payout = sum(e["developer_payout_fen"] for e in entries)

        pricing_info = PRICING_MODELS.get(app["pricing_model"], {})

        return {
            "app_id": app_id,
            "app_name": app["app_name"],
            "period": period,
            "pricing_model": app["pricing_model"],
            "platform_fee_rate": pricing_info.get("platform_fee_rate", 0),
            "total_revenue_fen": total_revenue,
            "platform_fee_fen": platform_fee,
            "developer_payout_fen": developer_payout,
            "transaction_count": len(entries),
            "install_count": app.get("install_count", 0),
        }

    def request_payout(
        self,
        developer_id: str,
        amount_fen: int,
        bank_account: str,
    ) -> dict:
        """请求提现

        Args:
            developer_id: 开发者ID
            amount_fen: 提现金额（分）
            bank_account: 银行账户信息

        Returns:
            提现记录
        """
        if developer_id not in self._developers:
            raise ValueError(f"开发者不存在: {developer_id}")
        if amount_fen <= 0:
            raise ValueError("提现金额必须大于0")

        # 计算可提现余额
        revenue = self.get_developer_revenue(developer_id)
        available = revenue["developer_payout_fen"]

        # 扣除已提现金额
        existing_payouts = self._payouts.get(developer_id, [])
        already_paid = sum(
            p["amount_fen"]
            for p in existing_payouts
            if p["status"] in ("pending", "processing", "completed")
        )
        available -= already_paid

        if amount_fen > available:
            raise ValueError(
                f"余额不足: 可提现 {available} 分，请求 {amount_fen} 分"
            )

        payout_id = _gen_id("payout")
        now = _now_iso()

        payout = {
            "payout_id": payout_id,
            "developer_id": developer_id,
            "amount_fen": amount_fen,
            "bank_account": bank_account,
            "status": "pending",
            "requested_at": now,
            "completed_at": None,
        }

        if developer_id not in self._payouts:
            self._payouts[developer_id] = []
        self._payouts[developer_id].append(payout)

        return payout

    def get_payout_history(self, developer_id: str) -> list[dict]:
        """获取提现历史

        Args:
            developer_id: 开发者ID

        Returns:
            提现记录列表
        """
        if developer_id not in self._developers:
            raise ValueError(f"开发者不存在: {developer_id}")

        records = self._payouts.get(developer_id, [])
        return sorted(records, key=lambda r: r["requested_at"], reverse=True)

    # ──────────────────────────────────────────────────────
    #  8. Marketplace Analytics（市场分析）
    # ──────────────────────────────────────────────────────

    def get_marketplace_stats(self) -> dict:
        """获取市场整体统计

        Returns:
            total_apps, total_developers, total_installs, monthly_revenue
        """
        published_apps = [a for a in self._apps.values() if a["status"] == "published"]
        total_installs = sum(a.get("install_count", 0) for a in self._apps.values())
        total_revenue = sum(a.get("revenue_total_fen", 0) for a in self._apps.values())

        # 按分类统计
        category_counts: Dict[str, int] = {}
        for app in published_apps:
            cat = app["category"]
            category_counts[cat] = category_counts.get(cat, 0) + 1

        return {
            "total_apps": len(self._apps),
            "published_apps": len(published_apps),
            "total_developers": len(self._developers),
            "total_installs": total_installs,
            "total_revenue_fen": total_revenue,
            "category_distribution": category_counts,
            "avg_rating": round(
                sum(a.get("rating", 0) for a in published_apps) / len(published_apps), 2
            ) if published_apps else 0,
            "generated_at": _now_iso(),
        }

    def get_trending_apps(self, period: str = "week", limit: int = 10) -> list[dict]:
        """获取热门应用

        Args:
            period: 统计周期 (day/week/month)
            limit: 返回数量

        Returns:
            热门应用列表（按安装量+评分综合排序）
        """
        published = [a for a in self._apps.values() if a["status"] == "published"]

        # 综合评分：安装量归一化 * 0.6 + 评分归一化 * 0.4
        max_installs = max((a.get("install_count", 0) for a in published), default=1) or 1
        max_rating = 5.0

        for app in published:
            install_score = app.get("install_count", 0) / max_installs
            rating_score = app.get("rating", 0) / max_rating
            app["_trend_score"] = install_score * 0.6 + rating_score * 0.4

        published.sort(key=lambda a: a.get("_trend_score", 0), reverse=True)

        results = []
        for i, app in enumerate(published[:limit]):
            developer = self._developers.get(app["developer_id"], {})
            cat_info = APP_CATEGORIES.get(app["category"], {})
            results.append({
                "rank": i + 1,
                "app_id": app["app_id"],
                "app_name": app["app_name"],
                "developer_name": developer.get("name", ""),
                "category": app["category"],
                "category_name": cat_info.get("name", ""),
                "rating": app.get("rating", 0),
                "install_count": app.get("install_count", 0),
                "price_display": app.get("price_display", ""),
                "trend_score": round(app.get("_trend_score", 0), 4),
            })

        # 清理临时字段
        for app in published:
            app.pop("_trend_score", None)

        return results

    def get_category_stats(self) -> list[dict]:
        """获取分类统计

        Returns:
            各分类的应用数、安装量、平均评分
        """
        stats: Dict[str, dict] = {}

        for cat_key, cat_info in APP_CATEGORIES.items():
            stats[cat_key] = {
                "category": cat_key,
                "category_name": cat_info["name"],
                "icon": cat_info["icon"],
                "description": cat_info["description"],
                "app_count": 0,
                "total_installs": 0,
                "total_revenue_fen": 0,
                "ratings": [],
            }

        for app in self._apps.values():
            cat = app.get("category")
            if cat in stats:
                stats[cat]["app_count"] += 1
                stats[cat]["total_installs"] += app.get("install_count", 0)
                stats[cat]["total_revenue_fen"] += app.get("revenue_total_fen", 0)
                if app.get("rating", 0) > 0:
                    stats[cat]["ratings"].append(app["rating"])

        result = []
        for cat_key, s in stats.items():
            ratings = s.pop("ratings")
            s["avg_rating"] = round(sum(ratings) / len(ratings), 2) if ratings else 0
            result.append(s)

        # 按应用数量降序
        result.sort(key=lambda x: x["app_count"], reverse=True)
        return result
