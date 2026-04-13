"""wechat_pay_notify_service 纯函数单测（无 DB）"""

from __future__ import annotations

from src.services import wechat_pay_notify_service as mod


def test_amount_fen_from_decrypted_payer_total() -> None:
    assert (
        mod._amount_fen_from_decrypted(
            {"amount": {"payer_total": 8800, "total": 9000}}
        )
        == 8800
    )


def test_amount_fen_from_decrypted_fallback_total() -> None:
    assert mod._amount_fen_from_decrypted({"amount": {"total": 100}}) == 100


def test_is_uuid() -> None:
    assert mod._is_uuid("550e8400-e29b-41d4-a716-446655440000") is True
    assert mod._is_uuid("not-a-uuid") is False
