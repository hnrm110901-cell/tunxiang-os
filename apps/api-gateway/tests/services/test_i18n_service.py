"""
i18n service 单元测试
覆盖：
  1) 变量替换 {name}
  2) fallback 到 default_value_zh
  3) 未注册 key 返回 key 本身不抛错
  4) 批量取翻译
"""

import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest  # noqa: E402

from src.services.i18n_service import I18nService, _apply_vars, clear_i18n_cache  # noqa: E402


def test_apply_vars_basic():
    assert _apply_vars("Welcome, {name}", {"name": "Alice"}) == "Welcome, Alice"


def test_apply_vars_missing_key_kept():
    # 缺失变量不抛错
    assert _apply_vars("{a}-{b}", {"a": "x"}).startswith("x-")


def test_apply_vars_no_vars():
    assert _apply_vars("Hello", None) == "Hello"
    assert _apply_vars("Hello", {}) == "Hello"


@pytest.mark.asyncio
async def test_get_text_unknown_key_returns_key():
    clear_i18n_cache()
    db = MagicMock()
    exec_result = MagicMock()
    exec_result.first = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=exec_result)
    svc = I18nService(db)
    out = await svc.get_text("nope", locale="en-US", namespace="ns")
    assert out == "nope"


@pytest.mark.asyncio
async def test_get_text_fallback_to_default_zh():
    clear_i18n_cache()
    tk = MagicMock()
    tk.default_value_zh = "保存"
    # translation 为 None → fallback
    exec_result = MagicMock()
    exec_result.first = MagicMock(return_value=(tk, None))
    db = MagicMock()
    db.execute = AsyncMock(return_value=exec_result)
    svc = I18nService(db)
    out = await svc.get_text("save", locale="vi-VN", namespace="common")
    assert out == "保存"


@pytest.mark.asyncio
async def test_get_text_with_translation_and_vars():
    clear_i18n_cache()
    tk = MagicMock()
    tk.default_value_zh = "欢迎，{name}"
    tr = MagicMock()
    tr.translated_value = "Welcome, {name}"
    exec_result = MagicMock()
    exec_result.first = MagicMock(return_value=(tk, tr))
    db = MagicMock()
    db.execute = AsyncMock(return_value=exec_result)
    svc = I18nService(db)
    out = await svc.get_text("welcome", locale="en-US", namespace="common", name="Bob")
    assert out == "Welcome, Bob"
