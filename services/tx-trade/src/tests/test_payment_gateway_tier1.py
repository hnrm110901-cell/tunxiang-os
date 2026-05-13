"""test_payment_gateway_tier1 — _method_to_category SoT 契约 Tier1

Tier1 铁律（CLAUDE.md §17/§20）:
  - PaymentGateway 是 method→category 映射的**唯一 SoT**
  - CashierEngine 不得维护重复 mapping (PR #527 P2 historic dup, Issue #541 follow-up)
  - 行为契约: 7 个支付方式映射 + 未知 method fallback "other"

去重前 (PR pre-#542 follow-up):
  - payment_gateway.py:660 + cashier_engine.py:1308 字节级完全一致的 mapping
  - 漂移风险: 新增支付方式 (如数字人民币) 只改一处时, cashier 路径 silently 走 "other"

本测试锁定:
  - SoT 在 PaymentGateway._method_to_category (positive)
  - CashierEngine 无重复 _method_to_category 静态方法 (invariant)

#542 tier1-gate 正向 TDD 压力验证: 本文件是 *tier1*.py 命中 glob,
配对 payment_gateway.py + cashier_engine.py 源改动, 走"源/测试改动配对" gate。
"""

from __future__ import annotations

# 用 src-prefix 跟随同 dir 17 个 tier1 文件 majority (test_api_idempotency_tier1 等).
# 混入 FQN `services.tx_trade.src.X` 会与 src-prefix 形成同一 .py 双 sys.modules 路径,
# 触发 SQLAlchemy `Table 'payments' is already defined` MetaData dup (CI vs local 差异).
# memory feedback_pytest_stub_setdefault_pitfall.md 5/13 实测扩展。
from src.services.cashier_engine import CashierEngine
from src.services.payment_gateway import PaymentGateway


class TestMethodToCategorySoT:
    """_method_to_category 单一 SoT 在 PaymentGateway 上"""

    def test_payment_gateway_is_sot_for_method_category_mapping(self):
        """PaymentGateway._method_to_category 覆盖 7 个法定 method → 中文 category"""
        assert PaymentGateway._method_to_category("cash") == "现金"
        assert PaymentGateway._method_to_category("wechat") == "移动支付"
        assert PaymentGateway._method_to_category("alipay") == "移动支付"
        assert PaymentGateway._method_to_category("unionpay") == "银联卡"
        assert PaymentGateway._method_to_category("member_balance") == "会员消费"
        assert PaymentGateway._method_to_category("credit_account") == "挂账"

    def test_payment_gateway_unknown_method_falls_back_to_other(self):
        """未知 method 不抛, 返回 "other" — 防止 KeyError 中断结算"""
        assert PaymentGateway._method_to_category("unknown") == "other"
        assert PaymentGateway._method_to_category("digital_rmb") == "other"
        assert PaymentGateway._method_to_category("") == "other"

    def test_cashier_engine_does_not_duplicate_method_to_category(self):
        """CashierEngine 不得维护重复 mapping — 漂移防护

        若新增支付方式 (例如 digital_rmb) 只改 PaymentGateway 而忘了 CashierEngine,
        cashier 路径 silently 走 "other" 分类, 财务报表 by_method 聚合错乱。
        SoT 单一化后此风险消失。
        """
        assert not hasattr(CashierEngine, "_method_to_category"), (
            "CashierEngine._method_to_category should be removed — "
            "PaymentGateway is the single SoT. Found duplicate definition."
        )


class TestPaymentMethodCategoryCoverage:
    """法定 PAYMENT_METHODS 7 keys 全部有 category 映射 — 漂移守门"""

    def test_all_payment_methods_have_category_mapping(self):
        """PAYMENT_METHODS 6 法定 method 必须全部映射到非 "other" category

        cash / wechat / alipay / unionpay / member_balance / credit_account
        — 这 6 个是源 PaymentGateway.PAYMENT_METHODS keys, 必须 mapping 命中。
        """
        methods = PaymentGateway.PAYMENT_METHODS
        for method in methods:
            category = PaymentGateway._method_to_category(method)
            assert category != "other", (
                f"PAYMENT_METHODS contains '{method}' but _method_to_category "
                f"returns 'other' — mapping 漂移"
            )
