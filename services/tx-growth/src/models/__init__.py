"""增长服务数据模型

ABTest, AttributionSummary, JourneyInstance, ReferralCampaign 依赖 shared 模块，
通过 __getattr__ 懒加载以避免在 Python 3.9 环境中触发 shared 的 import 错误。
"""

from models.wecom_channel_code import WecomChannelCode

__all__ = [
    "MarketingTouch",
    "AttributionSummary",
    "JourneyInstance",
    "ReferralCampaign",
    "WecomChannelCode",
    "ABTest",
    "ABTestAssignment",
]


def __getattr__(name: str):
    """懒加载依赖 shared 模块的模型类"""
    _lazy_map = {
        "ABTest": ("models.ab_test", "ABTest"),
        "ABTestAssignment": ("models.ab_test", "ABTestAssignment"),
        "AttributionSummary": ("models.attribution", "AttributionSummary"),
        "MarketingTouch": ("models.attribution", "MarketingTouch"),
        "JourneyInstance": ("models.journey_instance", "JourneyInstance"),
        "ReferralCampaign": ("models.referral", "ReferralCampaign"),
        "ReferralLink": ("models.referral", "ReferralLink"),
        "ReferralConversion": ("models.referral", "ReferralConversion"),
    }
    if name in _lazy_map:
        import importlib

        mod_path, attr_name = _lazy_map[name]
        mod = importlib.import_module(mod_path)
        return getattr(mod, attr_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
