"""tenant_registry — 商户码与 DEMO 租户 UUID 对齐"""

from uuid import UUID

import pytest

from shared.tenant_registry import MERCHANT_CODE_TO_TENANT_UUID, tenant_uuid_for_merchant_code


def test_merchant_codes_map_to_stable_uuids() -> None:
    assert MERCHANT_CODE_TO_TENANT_UUID["czyz"] == "a0000000-0000-0000-0000-000000000002"
    assert MERCHANT_CODE_TO_TENANT_UUID["zqx"] == "a0000000-0000-0000-0000-000000000003"
    assert MERCHANT_CODE_TO_TENANT_UUID["sgc"] == "a0000000-0000-0000-0000-000000000004"


def test_tenant_uuid_for_merchant_code_case_insensitive() -> None:
    assert tenant_uuid_for_merchant_code("CZYZ") == UUID("a0000000-0000-0000-0000-000000000002")


def test_unknown_merchant_raises() -> None:
    with pytest.raises(KeyError):
        tenant_uuid_for_merchant_code("unknown")
