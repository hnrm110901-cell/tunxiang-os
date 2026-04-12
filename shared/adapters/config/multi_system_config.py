"""多系统凭证配置 Pydantic 模型

定义四个外部系统的配置结构，以及组合的租户多系统配置容器。
数据存储于 tenants.systems_config JSONB 列，通过管理 API 读写，
凭证绝不硬编码，全部经由数据库读取。

系统列表：
  pinzhi        — 品智收银（base_url + app_secret 作 API token）
  aoqiwei_crm   — 奥琦玮微生活会员（api.acewill.net）
  aoqiwei_supply — 奥琦玮供应链（openapi.acescm.cn）
  yiding        — 易订预订（open.zhidianfan.com/yidingopen）
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class PinzhiConfig(BaseModel):
    """品智收银系统配置。

    品智适配器实际使用 base_url + token；
    此处保留 app_id / app_secret / org_id 字段以备未来 OAuth 升级，
    当前主凭证通过 app_secret 字段存储品智 API Token。
    """

    enabled: bool = True
    base_url: str = Field(default="", description="品智 API 基础 URL，例如 https://xxx.pinzhikeji.net/pzcatering-gateway")
    app_id: str = Field(default="", description="品智应用 ID（预留，当前版本不使用）")
    app_secret: str = Field(default="", description="品智 API Token / AppSecret")
    org_id: str = Field(default="", description="品智组织 ID（ognid，可选）")


class AoqiweiCrmConfig(BaseModel):
    """奥琦玮微生活会员系统配置（api.acewill.net）。

    认证方式：appid + appkey（MD5 签名，API 方要求）。
    appkey 仅用于签名计算，不发送到请求体。
    """

    enabled: bool = True
    api_url: str = Field(default="https://api.acewill.net", description="CRM API 基础 URL")
    appid: str = Field(default="", description="微生活 AppID")
    appkey: str = Field(default="", description="微生活 AppKey（签名密钥）")
    shop_id: str = Field(default="", description="门店 ID（shop_id，整数字符串）")


class AoqiweiSupplyConfig(BaseModel):
    """奥琦玮供应链开放平台配置（openapi.acescm.cn）。

    认证方式：app_id（appkey）+ app_secret（appsecret）MD5 签名。
    """

    enabled: bool = True
    api_url: str = Field(default="https://openapi.acescm.cn", description="供应链 API 基础 URL")
    app_id: str = Field(default="", description="供应链 AppKey")
    app_secret: str = Field(default="", description="供应链 AppSecret（签名密钥）")
    shop_code: str = Field(default="", description="门店编码（shopCode）")


class YidingConfig(BaseModel):
    """易订预订系统配置（open.zhidianfan.com/yidingopen）。

    认证方式：appid + secret → access_token（自动刷新）。
    api_key 字段存储 secret 值（统一字段命名）。
    """

    enabled: bool = True
    base_url: str = Field(default="https://open.zhidianfan.com/yidingopen/", description="易订 API 基础 URL")
    api_key: str = Field(default="", description="易订 Secret（appid 对应的密钥）")
    hotel_id: str = Field(default="", description="易订门店 ID（hotel_id，多店时使用）")


class TenantSystemsConfig(BaseModel):
    """租户多系统配置容器。

    每个字段均为可选，未配置的系统设为 None。
    JSON 序列化后直接存入 tenants.systems_config JSONB 列。
    """

    pinzhi: Optional[PinzhiConfig] = None
    aoqiwei_crm: Optional[AoqiweiCrmConfig] = None
    aoqiwei_supply: Optional[AoqiweiSupplyConfig] = None
    yiding: Optional[YidingConfig] = None
