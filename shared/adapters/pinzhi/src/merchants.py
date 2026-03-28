"""三家商户的品智POS门店映射配置

门店ID和API基础地址为非敏感信息。
Token通过环境变量加载，不在代码中出现。
"""

MERCHANT_CONFIG = {
    "czyz": {  # 尝在一起
        "brand_name": "尝在一起",
        "pinzhi_base_url": "http://czyq.pinzhikeji.net:8899/pzcatering-gateway",
        "stores": {
            "2461": {"name": "文化城店", "token_env": "CZYZ_PINZHI_STORE_2461_TOKEN"},
            "7269": {"name": "浏小鲜", "token_env": "CZYZ_PINZHI_STORE_7269_TOKEN"},
            "19189": {"name": "永安店", "token_env": "CZYZ_PINZHI_STORE_19189_TOKEN"},
        },
        "api_token_env": "CZYZ_PINZHI_API_TOKEN",
    },
    "zqx": {  # 最黔线
        "brand_name": "最黔线",
        "pinzhi_base_url": "http://ljcg.pinzhikeji.net:8899/pzcatering-gateway",
        "stores": {
            "20529": {"name": "门店1", "token_env": "ZQX_PINZHI_STORE_20529_TOKEN"},
            "32109": {"name": "门店2", "token_env": "ZQX_PINZHI_STORE_32109_TOKEN"},
            "32304": {"name": "门店3", "token_env": "ZQX_PINZHI_STORE_32304_TOKEN"},
            "32305": {"name": "门店4", "token_env": "ZQX_PINZHI_STORE_32305_TOKEN"},
            "32306": {"name": "门店5", "token_env": "ZQX_PINZHI_STORE_32306_TOKEN"},
            "32309": {"name": "门店6", "token_env": "ZQX_PINZHI_STORE_32309_TOKEN"},
        },
        "api_token_env": "ZQX_PINZHI_API_TOKEN",
    },
    "sgc": {  # 尚宫厨
        "brand_name": "尚宫厨",
        "pinzhi_base_url": "http://xcsgc.pinzhikeji.net:8899/pzcatering-gateway",
        "stores": {
            "2463": {"name": "门店1", "token_env": "SGC_PINZHI_STORE_2463_TOKEN"},
            "7896": {"name": "门店2", "token_env": "SGC_PINZHI_STORE_7896_TOKEN"},
            "24777": {"name": "门店3", "token_env": "SGC_PINZHI_STORE_24777_TOKEN"},
            "36199": {"name": "门店4", "token_env": "SGC_PINZHI_STORE_36199_TOKEN"},
            "41405": {"name": "门店5", "token_env": "SGC_PINZHI_STORE_41405_TOKEN"},
        },
        "api_token_env": "SGC_PINZHI_API_TOKEN",
    },
}
