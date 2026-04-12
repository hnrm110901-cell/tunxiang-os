"""v233 — 三品牌真实凭证写入 systems_config

将三个首批品牌的品智收银、奥琦玮微生活CRM真实凭证硬写入 tenants.systems_config，
并启用 sync_enabled = TRUE。尚宫厨额外写入奥琦玮卡券中心（coupon_center）配置。

凭证来源：商户后台 API 凭证（可在各商户后台管理页面查看，非密钥）。

Revision ID: v233
Revises: v232
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa

revision = "v233"
down_revision = "v232"
branch_labels = None
depends_on = None

# ─── 尝在一起 (t-czq) ────────────────────────────────────────────────────────
_CZYZ_CONFIG = """{
    "pinzhi": {
        "enabled": true,
        "base_url": "https://czyq.pinzhikeji.net/api/v1",
        "app_secret": "3bbc9bed2b42c1e1b3cca26389fbb81c",
        "store_tokens": {
            "2461": "752b4b16a863ce47def11cf33b1b521f",
            "7269": "f5cc1a27db6e215ae7bb5512b6b57981",
            "19189": "56cd51b69211297104a0608f6a696b80"
        }
    },
    "aoqiwei_crm": {
        "enabled": true,
        "api_url": "https://api.acewill.net",
        "appid": "dp25MLoc2gnXE7A223ZiVv",
        "appkey": "3d2eaa5f9b9a6a6746a18d28e770b501",
        "shop_id": "1275413383"
    },
    "aoqiwei_supply": {
        "enabled": false
    },
    "yiding": {
        "enabled": true,
        "base_url": "https://open.zhidianfan.com/yidingopen/",
        "appid": "czyq001",
        "api_key": "246837915",
        "hotel_id": "czyq001"
    }
}"""

# ─── 最黔线 (t-zqx) ──────────────────────────────────────────────────────────
_ZQX_CONFIG = """{
    "pinzhi": {
        "enabled": true,
        "base_url": "https://ljcg.pinzhikeji.net/api/v1",
        "app_secret": "47a428538d350fac1640a51b6bbda68c",
        "store_tokens": {
            "20529": "29cdb6acac3615070bb853afcbb32f60",
            "32109": "ed2c948284d09cf9e096e9d965936aa3",
            "32304": "43f0b54db12b0618ea612b2a0a4d2675",
            "32305": "a8a4e4daf86875d4a4e0254b6eb7191e",
            "32306": "d656668d285a100c851bbe149d4364f3",
            "32309": "36bf0644e5703adc8a4d1ddd7b8f0e95"
        }
    },
    "aoqiwei_crm": {
        "enabled": true,
        "api_url": "https://api.acewill.net",
        "appid": "dp2C8kqBMmGrHUVpBjqAw8q3",
        "appkey": "56573c798c8ab0dc565e704190207f12",
        "shop_id": "1827518239"
    },
    "aoqiwei_supply": {
        "enabled": false
    },
    "yiding": {
        "enabled": false
    }
}"""

# ─── 尚宫厨 (t-sgc) — 含卡券中心 ─────────────────────────────────────────────
_SGC_CONFIG = """{
    "pinzhi": {
        "enabled": true,
        "base_url": "https://xcsgc.pinzhikeji.net/api/v1",
        "app_secret": "8275cf74d1943d7a32531d2d4f889870",
        "store_tokens": {
            "2463": "852f1d34c75af0b8eb740ef47f133130",
            "7896": "27a36f2feea6d3a914438f6cb32108c3",
            "24777": "5cbfb449112f698218e0b1be1a3bc7c6",
            "36199": "08f3791e15f48338405728a3a92fcd7f",
            "41405": "bb7e89dcd0ac339b51631eca99e51c9b"
        }
    },
    "aoqiwei_crm": {
        "enabled": true,
        "api_url": "https://api.acewill.net",
        "appid": "dp0X0jl45wauwdGgkRETITz",
        "appkey": "649738234c7426bfa0dbfa431c92a750",
        "shop_id": "1549254243"
    },
    "aoqiwei_supply": {
        "enabled": false
    },
    "yiding": {
        "enabled": true,
        "base_url": "https://open.zhidianfan.com/yidingopen/",
        "appid": "sgclcd001",
        "api_key": "246837915",
        "hotel_id": "sgclcd001"
    },
    "coupon_center": {
        "enabled": true,
        "base_url": "https://apigateway.acewill.net",
        "app_id": "1549254243_6",
        "app_key": "d650652396b1bab5434d51c44c4d1436",
        "platforms": ["DOUYIN", "ALIPAY", "KUAISHOU", "XHS", "VIDEONUMBER", "BANK", "QITIAN", "JD", "TAOBAO", "SHANGOU", "AMAP"]
    }
}"""


def upgrade() -> None:
    # 尝在一起
    op.execute(
        sa.text("""
            UPDATE tenants
               SET systems_config = :cfg::jsonb,
                   sync_enabled   = TRUE
             WHERE code = 't-czq'
        """).bindparams(cfg=_CZYZ_CONFIG)
    )

    # 最黔线
    op.execute(
        sa.text("""
            UPDATE tenants
               SET systems_config = :cfg::jsonb,
                   sync_enabled   = TRUE
             WHERE code = 't-zqx'
        """).bindparams(cfg=_ZQX_CONFIG)
    )

    # 尚宫厨
    op.execute(
        sa.text("""
            UPDATE tenants
               SET systems_config = :cfg::jsonb,
                   sync_enabled   = TRUE
             WHERE code = 't-sgc'
        """).bindparams(cfg=_SGC_CONFIG)
    )


def downgrade() -> None:
    # 将三品牌凭证重置为空骨架，关闭同步
    for tenant_code in ("t-czq", "t-zqx", "t-sgc"):
        op.execute(
            sa.text("""
                UPDATE tenants
                   SET systems_config = '{}'::jsonb,
                       sync_enabled   = FALSE
                 WHERE code = :code
            """).bindparams(code=tenant_code)
        )
