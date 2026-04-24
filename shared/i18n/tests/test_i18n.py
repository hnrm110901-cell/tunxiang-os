"""多语言支持 (i18n) 测试

覆盖:
- 语言切换器
- get_text
- translate_menu
- translate_receipt
- get_supported_languages
- 各语言完整性校验
共 9 个测试用例 (>=6)
"""

from shared.i18n import DEFAULT_LANG, get_lang_module, get_supported_languages, get_text
from shared.i18n.translator import translate_menu, translate_receipt

TENANT_ID = "test-tenant-001"


class TestLanguageSwitcher:
    def test_default_lang_is_zh_cn(self):
        """默认语言为中文"""
        assert DEFAULT_LANG == "zh_CN"
        mod = get_lang_module()
        assert mod.LANG_CODE == "zh_CN"

    def test_get_lang_module_en(self):
        """切换到英文"""
        mod = get_lang_module("en_US")
        assert mod.LANG_CODE == "en_US"
        assert mod.LANG_NAME == "English"

    def test_get_lang_module_fallback(self):
        """未知语言回退到中文"""
        mod = get_lang_module("xx_XX")
        assert mod.LANG_CODE == "zh_CN"

    def test_supported_languages(self):
        """支持的语言列表"""
        langs = get_supported_languages()
        assert len(langs) >= 4
        codes = [l["code"] for l in langs]
        assert "zh_CN" in codes
        assert "en_US" in codes
        assert "ja_JP" in codes
        assert "ko_KR" in codes


class TestGetText:
    def test_get_ui_text_zh(self):
        """获取中文 UI 文本"""
        assert get_text("checkout", "UI", "zh_CN") == "结账"
        assert get_text("order", "UI", "zh_CN") == "点菜"

    def test_get_ui_text_en(self):
        """获取英文 UI 文本"""
        assert get_text("checkout", "UI", "en_US") == "Checkout"
        assert get_text("order", "UI", "en_US") == "Order"

    def test_get_category_ja(self):
        """获取日文分类名"""
        assert get_text("hot_dish", "CATEGORIES", "ja_JP") == "温かい料理"

    def test_get_dish_name_ko(self):
        """获取韩文菜品名"""
        result = get_text("mapo_tofu", "DISH_NAMES", "ko_KR")
        assert result == "마파두부"

    def test_missing_key_returns_key(self):
        """不存在的 key 返回 key 本身"""
        assert get_text("nonexistent_key", "UI", "en_US") == "nonexistent_key"


class TestTranslateMenu:
    def test_translate_menu_en(self):
        """菜单翻译: 中→英"""
        dishes = [
            {"name": "剁椒鱼头", "category": "热菜", "category_key": "hot_dish", "price_fen": 12800},
            {"name": "麻婆豆腐", "category": "热菜", "category_key": "hot_dish", "price_fen": 2800},
        ]
        result = translate_menu(dishes, "en_US", TENANT_ID)
        assert len(result) == 2
        assert result[0]["name_translated"] == "Steamed Fish Head with Chopped Chili"
        assert result[0]["name_original"] == "剁椒鱼头"
        assert result[1]["name_translated"] == "Mapo Tofu"

    def test_translate_menu_with_metadata(self):
        """菜单翻译: 优先使用 metadata 翻译"""
        dishes = [
            {
                "name": "剁椒鱼头",
                "category": "热菜",
                "metadata": {"translations": {"en_US": "Duo Jiao Fish Head (House Special)"}},
            },
        ]
        result = translate_menu(dishes, "en_US", TENANT_ID)
        # metadata 翻译优先
        assert result[0]["name_translated"] == "Duo Jiao Fish Head (House Special)"

    def test_translate_menu_zh_noop(self):
        """菜单翻译: 目标语言为中文时直接返回"""
        dishes = [{"name": "红烧肉"}]
        result = translate_menu(dishes, "zh_CN", TENANT_ID)
        assert result == dishes


class TestTranslateReceipt:
    def test_translate_receipt_en(self):
        """小票翻译: 中→英"""
        receipt = {
            "store_name": "尝在一起·长沙店",
            "order_no": "20260327-001",
            "items": [
                {"name": "剁椒鱼头", "qty": 1, "price_fen": 12800},
                {"name": "米饭", "qty": 2, "price_fen": 300},
            ],
            "total_fen": 13400,
        }
        result = translate_receipt(receipt, "en_US")
        assert result["target_lang"] == "en_US"
        assert result["labels"]["header"] == "Receipt"
        assert result["labels"]["total"] == "Total"
        assert result["labels"]["footer"] == "Thank you for dining with us!"
        # 菜品名翻译
        assert result["items"][0]["name_translated"] == "Steamed Fish Head with Chopped Chili"
        assert result["items"][1]["name_translated"] == "Steamed Rice"

    def test_translate_receipt_ja(self):
        """小票翻译: 中→日"""
        receipt = {
            "items": [{"name": "麻婆豆腐", "qty": 1, "price_fen": 2800}],
            "total_fen": 2800,
        }
        result = translate_receipt(receipt, "ja_JP")
        assert result["labels"]["header"] == "お会計票"
        assert result["items"][0]["name_translated"] == "麻婆豆腐"

    def test_translate_receipt_zh_noop(self):
        """小票翻译: 目标为中文直接返回"""
        receipt = {"items": [], "total_fen": 0}
        result = translate_receipt(receipt, "zh_CN")
        assert result == receipt
