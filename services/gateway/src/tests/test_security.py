"""
Phase 4-B 安全合规测试套件

覆盖范围:
  - AuditLogService.log 写入正确字段
  - 敏感字段自动脱敏（phone / id_card_no / email）
  - CONSTRAINT_OVERRIDE severity 强制为 critical
  - audit_logs 不允许 DELETE（RLS 合规验证）
  - get_security_alerts: 5次失败登录触发告警
  - get_security_alerts: 凌晨登录告警
  - DataMasker.mask_phone 各种格式
  - DataMasker.mask_id_card
  - DataMasker.mask_dict 递归脱敏
  - DataMasker.mask_dict 不修改原始 dict（immutable）
  - compliance_check: expired_token 检测
  - compliance_check: unused_app 检测
  - weekly_report 包含所有字段
  - query_logs 分页正确
  - 跨租户审计日志隔离
"""

from __future__ import annotations

import copy
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

# ─── 路径修正：让 tests 能 import 到 src 和 shared ───
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))

from services.audit_log_service import (
    AuditAction,
    AuditEntry,
    AuditLogService,
    _mask_sensitive,
)
from utils.data_masker import DataMasker

# ────────────────────────────────────────────────────────────────────
# Fixtures 工具
# ────────────────────────────────────────────────────────────────────

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _make_db_mock(rows: list[dict] | None = None, scalar: Any = None) -> AsyncMock:
    """构造一个模拟 AsyncSession。"""
    db = AsyncMock()

    # execute 返回一个模拟 result
    result_mock = MagicMock()
    result_mock.scalar_one.return_value = scalar if scalar is not None else 0
    result_mock.scalar_one_or_none.return_value = scalar

    mapping_rows = [MagicMock(**{"__getitem__": lambda s, k: row.get(k)}) for row in (rows or [])]
    for i, row in enumerate(rows or []):
        for k, v in row.items():
            mapping_rows[i].__getitem__ = lambda s, key, _r=row: _r[key]
            mapping_rows[i].__iter__ = lambda s, _r=row: iter(_r.items())

    mappings_mock = MagicMock()
    mappings_mock.all.return_value = rows or []
    result_mock.mappings.return_value = mappings_mock

    db.execute = AsyncMock(return_value=result_mock)
    return db


def _make_entry(
    action: AuditAction = AuditAction.LOGIN,
    actor_id: str = "user_001",
    actor_type: str = "user",
    resource_type: str = "session",
    severity: str = "info",
    before_state: dict | None = None,
    after_state: dict | None = None,
    tenant_id: UUID = TENANT_A,
) -> AuditEntry:
    return AuditEntry(
        tenant_id=tenant_id,
        action=action,
        actor_id=actor_id,
        actor_type=actor_type,
        resource_type=resource_type,
        severity=severity,
        before_state=before_state,
        after_state=after_state,
        ip_address="127.0.0.1",
        user_agent="pytest/1.0",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. AuditLogService.log — 写入正确字段
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestAuditLogServiceLog:
    @pytest.mark.asyncio
    async def test_log_calls_db_execute(self):
        """log() 应调用 db.execute 写入一行记录。"""
        svc = AuditLogService()
        db = _make_db_mock()
        entry = _make_entry()
        await svc.log(entry, db)
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_insert_contains_correct_action(self):
        """INSERT SQL 应包含正确的 action 值。"""
        svc = AuditLogService()
        db = _make_db_mock()
        entry = _make_entry(action=AuditAction.DATA_EXPORT)
        await svc.log(entry, db)
        # 验证 execute 被调用，且参数中含正确 action
        call_kwargs = db.execute.call_args
        # 第二个位置参数是 params dict
        params = call_kwargs[0][1]
        assert params["action"] == AuditAction.DATA_EXPORT.value

    @pytest.mark.asyncio
    async def test_log_inserts_correct_tenant_id(self):
        """INSERT 参数中 tenant_id 应与 entry.tenant_id 一致。"""
        svc = AuditLogService()
        db = _make_db_mock()
        entry = _make_entry(tenant_id=TENANT_A)
        await svc.log(entry, db)
        params = db.execute.call_args[0][1]
        assert params["tenant_id"] == str(TENANT_A)

    @pytest.mark.asyncio
    async def test_log_invalid_actor_type_raises(self):
        """无效的 actor_type 应抛出 ValueError。"""
        svc = AuditLogService()
        db = _make_db_mock()
        entry = _make_entry(actor_type="invalid_type")
        with pytest.raises(ValueError, match="actor_type"):
            await svc.log(entry, db)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 敏感字段自动脱敏
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSensitiveFieldMasking:
    @pytest.mark.asyncio
    async def test_phone_is_masked_in_before_state(self):
        """before_state 中的 phone 字段写入前应被脱敏。"""
        svc = AuditLogService()
        db = _make_db_mock()
        entry = _make_entry(before_state={"phone": "13812348888", "name": "张三"})
        await svc.log(entry, db)
        params = db.execute.call_args[0][1]
        before_json = params["before_state"]
        before = json.loads(before_json)
        assert "****" in before["phone"]
        assert "138" in before["phone"]
        assert before["name"] == "张三"  # 非敏感字段不变

    @pytest.mark.asyncio
    async def test_id_card_masked_in_after_state(self):
        """after_state 中的 id_card_no 应被脱敏，只露前3后4。"""
        svc = AuditLogService()
        db = _make_db_mock()
        entry = _make_entry(after_state={"id_card_no": "110101199001011234"})
        await svc.log(entry, db)
        params = db.execute.call_args[0][1]
        after = json.loads(params["after_state"])
        assert after["id_card_no"].startswith("110")
        assert after["id_card_no"].endswith("1234")
        assert "199001" not in after["id_card_no"]  # 中间隐藏

    @pytest.mark.asyncio
    async def test_email_masked_in_state(self):
        """email 字段应保留首字符和域名，隐藏其余部分。"""
        svc = AuditLogService()
        db = _make_db_mock()
        entry = _make_entry(before_state={"email": "zhangsan@example.com"})
        await svc.log(entry, db)
        params = db.execute.call_args[0][1]
        before = json.loads(params["before_state"])
        assert before["email"].startswith("z")
        assert "@example.com" in before["email"]
        assert "zhangsan" not in before["email"]

    def test_mask_sensitive_none_input_returns_none(self):
        """_mask_sensitive(None) 应返回 None，不抛异常。"""
        assert _mask_sensitive(None) is None

    def test_mask_sensitive_nested_dict(self):
        """嵌套 dict 中的敏感字段也应被脱敏。"""
        data = {"user": {"phone": "13800138000", "age": 30}}
        masked = _mask_sensitive(data)
        assert "****" in masked["user"]["phone"]
        assert masked["user"]["age"] == 30


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. CONSTRAINT_OVERRIDE severity 强制 critical
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestConstraintOverrideSeverity:
    @pytest.mark.asyncio
    async def test_constraint_override_forces_critical(self):
        """CONSTRAINT_OVERRIDE 无论 entry.severity 是什么，必须写入 critical。"""
        svc = AuditLogService()
        db = _make_db_mock()
        entry = _make_entry(
            action=AuditAction.CONSTRAINT_OVERRIDE,
            severity="info",  # 故意设 info，应被强制覆盖为 critical
            resource_type="discount",
        )
        await svc.log(entry, db)
        params = db.execute.call_args[0][1]
        assert params["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_normal_action_keeps_info_severity(self):
        """普通操作（LOGIN）不应被强制为 critical。"""
        svc = AuditLogService()
        db = _make_db_mock()
        entry = _make_entry(action=AuditAction.LOGIN, severity="info")
        await svc.log(entry, db)
        params = db.execute.call_args[0][1]
        assert params["severity"] == "info"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. audit_logs 不允许 DELETE（RLS 合规验证，逻辑层面）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestAuditLogsImmutability:
    def test_no_delete_method_on_service(self):
        """AuditLogService 不应暴露 delete_log 或类似方法（防止误用）。"""
        svc = AuditLogService()
        delete_method_names = [
            name for name in dir(svc) if "delete" in name.lower() or "remove" in name.lower() or "purge" in name.lower()
        ]
        assert len(delete_method_names) == 0, f"发现了不应存在的删除方法: {delete_method_names}"

    def test_no_update_method_on_service(self):
        """AuditLogService 不应暴露 update_log 或 patch_log 方法。"""
        svc = AuditLogService()
        update_method_names = [
            name
            for name in dir(svc)
            if ("update" in name.lower() or "patch" in name.lower() or "modify" in name.lower())
            and not name.startswith("_")
        ]
        assert len(update_method_names) == 0, f"发现了不应存在的更新方法: {update_method_names}"

    def test_migration_has_no_update_delete_policy(self):
        """v070 迁移文件中不应包含 UPDATE 或 DELETE RLS policy 创建语句。"""
        migration_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "..",
            "shared",
            "db-migrations",
            "versions",
            "v070_audit_logs.py",
        )
        migration_path = os.path.normpath(migration_path)
        assert os.path.exists(migration_path), f"迁移文件不存在: {migration_path}"
        with open(migration_path, "r", encoding="utf-8") as f:
            content = f.read()
        # 确保没有创建 UPDATE/DELETE policy
        assert "FOR UPDATE" not in content
        assert "FOR DELETE" not in content
        # 确保有 SELECT 和 INSERT policy
        assert "FOR SELECT" in content
        assert "FOR INSERT" in content


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. get_security_alerts — 登录失败告警
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSecurityAlerts:
    @pytest.mark.asyncio
    async def test_excessive_login_failures_trigger_alert(self):
        """同一 actor 1小时内登录失败 >5次应触发告警。"""
        svc = AuditLogService()

        # 模拟数据库：第一次查询返回登录失败聚合行
        fail_row = {
            "actor_id": "user_hacker",
            "hour_bucket": datetime(2026, 3, 31, 10, 0, 0),
            "cnt": 8,
        }
        db = AsyncMock()
        result_mock = MagicMock()

        # 第1次 execute 返回登录失败行，后续返回空列表
        call_count = {"n": 0}

        async def execute_side_effect(sql, params=None):
            call_count["n"] += 1
            r = MagicMock()
            if call_count["n"] == 1:
                # login_failed 聚合
                mappings = MagicMock()
                mappings.all.return_value = [fail_row]
                r.mappings.return_value = mappings
            else:
                mappings = MagicMock()
                mappings.all.return_value = []
                r.mappings.return_value = mappings
            r.scalar_one.return_value = 0
            return r

        db.execute = execute_side_effect

        alerts = await svc.get_security_alerts(tenant_id=TENANT_A, hours=24, db=db)
        login_fail_alerts = [a for a in alerts if a["type"] == "excessive_login_failures"]
        assert len(login_fail_alerts) >= 1
        assert login_fail_alerts[0]["actor_id"] == "user_hacker"
        assert login_fail_alerts[0]["count"] == 8

    @pytest.mark.asyncio
    async def test_constraint_override_always_alerts(self):
        """CONSTRAINT_OVERRIDE 任意一次都应出现在告警列表中。"""
        svc = AuditLogService()

        override_row = {
            "id": uuid.uuid4(),
            "actor_id": "agent_discount",
            "actor_type": "agent",
            "resource_type": "discount",
            "resource_id": "order_123",
            "created_at": datetime(2026, 3, 31, 3, 30, 0, tzinfo=timezone.utc),
            "extra": {},
        }

        call_count = {"n": 0}

        async def execute_side_effect(sql, params=None):
            call_count["n"] += 1
            r = MagicMock()
            if call_count["n"] == 2:  # 第2次查询是 constraint_override
                mappings = MagicMock()
                mappings.all.return_value = [override_row]
                r.mappings.return_value = mappings
            else:
                mappings = MagicMock()
                mappings.all.return_value = []
                r.mappings.return_value = mappings
            r.scalar_one.return_value = 0
            return r

        db = AsyncMock()
        db.execute = execute_side_effect

        alerts = await svc.get_security_alerts(tenant_id=TENANT_A, hours=24, db=db)
        override_alerts = [a for a in alerts if a["type"] == "constraint_override"]
        assert len(override_alerts) >= 1
        assert override_alerts[0]["actor_id"] == "agent_discount"

    @pytest.mark.asyncio
    async def test_nighttime_login_triggers_alert(self):
        """凌晨 2-5 点的 LOGIN 事件应触发 nighttime_login 告警。"""
        svc = AuditLogService()

        night_row = {
            "id": uuid.uuid4(),
            "actor_id": "user_suspicious",
            "actor_type": "user",
            "ip_address": "192.168.1.100",
            "created_at": datetime(2026, 3, 31, 3, 15, 0, tzinfo=timezone.utc),
        }

        call_count = {"n": 0}

        async def execute_side_effect(sql, params=None):
            call_count["n"] += 1
            r = MagicMock()
            if call_count["n"] == 4:  # 第4次查询是 nighttime login
                mappings = MagicMock()
                mappings.all.return_value = [night_row]
                r.mappings.return_value = mappings
            else:
                mappings = MagicMock()
                mappings.all.return_value = []
                r.mappings.return_value = mappings
            r.scalar_one.return_value = 0
            return r

        db = AsyncMock()
        db.execute = execute_side_effect

        alerts = await svc.get_security_alerts(tenant_id=TENANT_A, hours=24, db=db)
        night_alerts = [a for a in alerts if a["type"] == "nighttime_login"]
        assert len(night_alerts) >= 1
        assert night_alerts[0]["actor_id"] == "user_suspicious"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. DataMasker 单元测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDataMaskerPhone:
    def test_standard_11_digit_phone(self):
        result = DataMasker.mask_phone("13812348888")
        assert result == "138****8888"

    def test_phone_with_prefix(self):
        """带+86前缀也能脱敏。"""
        result = DataMasker.mask_phone("+8613812348888")
        assert "****" in result

    def test_phone_none_returns_none(self):
        assert DataMasker.mask_phone(None) is None

    def test_short_phone_masked(self):
        """位数不足7位全遮盖。"""
        result = DataMasker.mask_phone("123")
        assert "*" in result

    def test_phone_keeps_prefix_and_suffix(self):
        result = DataMasker.mask_phone("15566667777")
        assert result.startswith("155")
        assert result.endswith("7777")


class TestDataMaskerIdCard:
    def test_standard_18_digit_id_card(self):
        result = DataMasker.mask_id_card("110101199001011234")
        assert result.startswith("110")
        assert result.endswith("1234")
        assert "199001" not in result

    def test_id_card_none_returns_none(self):
        assert DataMasker.mask_id_card(None) is None

    def test_short_id_card_fully_masked(self):
        result = DataMasker.mask_id_card("12345")
        assert result == "*" * 5

    def test_id_card_middle_all_stars(self):
        result = DataMasker.mask_id_card("110101199001011234")
        # 中间11位（18-7=11）应全是星号
        assert "***********" in result


class TestDataMaskerMaskDict:
    def test_mask_dict_masks_phone(self):
        data = {"name": "张三", "phone": "13812348888"}
        result = DataMasker.mask_dict(data)
        assert "****" in result["phone"]
        assert result["name"] == "张三"

    def test_mask_dict_does_not_modify_original(self):
        """mask_dict 不应修改原始 dict（immutable 语义）。"""
        original = {"phone": "13812348888", "email": "test@example.com"}
        original_copy = copy.deepcopy(original)
        DataMasker.mask_dict(original)
        assert original == original_copy  # 原始数据未被修改

    def test_mask_dict_nested_recursion(self):
        """嵌套 dict 中的敏感字段也应被脱敏。"""
        data = {
            "user": {
                "phone": "13800138000",
                "profile": {
                    "email": "user@company.com",
                    "age": 28,
                },
            }
        }
        result = DataMasker.mask_dict(data)
        assert "****" in result["user"]["phone"]
        assert "***" in result["user"]["profile"]["email"]
        assert result["user"]["profile"]["age"] == 28

    def test_mask_dict_list_of_dicts(self):
        """list 中的 dict 元素也应递归脱敏。"""
        data = {
            "employees": [
                {"name": "张三", "phone": "13800000001"},
                {"name": "李四", "phone": "13900000002"},
            ]
        }
        result = DataMasker.mask_dict(data)
        for emp in result["employees"]:
            assert "****" in emp["phone"]

    def test_mask_dict_custom_fields(self):
        """自定义 fields 参数只脱敏指定字段。"""
        data = {"phone": "13812348888", "id_card_no": "110101199001011234", "name": "测试"}
        result = DataMasker.mask_dict(data, fields={"phone"})
        # phone 被脱敏，id_card_no 保持原样
        assert "****" in result["phone"]
        assert result["id_card_no"] == "110101199001011234"

    def test_mask_email(self):
        assert DataMasker.mask_email("zhangsan@example.com") == "z***@example.com"

    def test_mask_email_none(self):
        assert DataMasker.mask_email(None) is None

    def test_mask_bank_account(self):
        result = DataMasker.mask_bank_account("6225880112346789")
        assert result == "****6789"

    def test_mask_bank_account_none(self):
        assert DataMasker.mask_bank_account(None) is None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7. compliance_check 检测
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestComplianceCheck:
    @pytest.mark.asyncio
    async def test_expired_token_detected(self):
        """当存在超过90天未吊销的 token 时，has_expired_tokens = True。"""
        from services.security_report_service import SecurityReportService

        svc = SecurityReportService()

        call_count = {"n": 0}

        async def execute_side_effect(sql, params=None):
            call_count["n"] += 1
            r = MagicMock()
            if call_count["n"] == 1:
                # RLS 查询：rls=True
                r.scalar_one_or_none.return_value = True
            elif call_count["n"] == 2:
                # expired_token 查询：有3个过期 token
                r.scalar_one.return_value = 3
                r.scalar_one_or_none.return_value = 3
            else:
                r.scalar_one.return_value = 0
                r.scalar_one_or_none.return_value = 0
            return r

        db = AsyncMock()
        db.execute = execute_side_effect

        result = await svc.check_compliance_status(tenant_id=TENANT_A, db=db)
        assert result["has_expired_tokens"] is True
        assert result["expired_token_count"] == 3

    @pytest.mark.asyncio
    async def test_unused_app_detected(self):
        """当存在超30天未使用的 api_app 时，has_unused_apps = True。"""
        from services.security_report_service import SecurityReportService

        svc = SecurityReportService()

        call_count = {"n": 0}

        async def execute_side_effect(sql, params=None):
            call_count["n"] += 1
            r = MagicMock()
            if call_count["n"] == 1:
                r.scalar_one_or_none.return_value = True  # rls
            elif call_count["n"] == 2:
                r.scalar_one.return_value = 0  # no expired tokens
                r.scalar_one_or_none.return_value = 0
            elif call_count["n"] == 3:
                r.scalar_one.return_value = 2  # 2 unused apps
                r.scalar_one_or_none.return_value = 2
            else:
                r.scalar_one.return_value = 0
                r.scalar_one_or_none.return_value = 0
            return r

        db = AsyncMock()
        db.execute = execute_side_effect

        result = await svc.check_compliance_status(tenant_id=TENANT_A, db=db)
        assert result["has_unused_apps"] is True
        assert result["unused_app_count"] == 2

    @pytest.mark.asyncio
    async def test_compliance_score_perfect_when_all_clean(self):
        """所有检查项正常时，overall_score 应为 100。"""
        from services.security_report_service import SecurityReportService

        svc = SecurityReportService()

        async def execute_side_effect(sql, params=None):
            r = MagicMock()
            r.scalar_one_or_none.return_value = True  # rls enabled
            r.scalar_one.return_value = 0  # 全部为 0
            return r

        db = AsyncMock()
        db.execute = execute_side_effect

        result = await svc.check_compliance_status(tenant_id=TENANT_A, db=db)
        assert result["overall_score"] == 100
        assert result["rls_enabled"] is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 8. weekly_report 包含所有字段
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestWeeklyReport:
    @pytest.mark.asyncio
    async def test_weekly_report_contains_required_fields(self):
        """周报必须包含所有规定字段。"""
        from datetime import date

        from services.security_report_service import SecurityReportService

        svc = SecurityReportService()

        async def execute_side_effect(sql, params=None):
            r = MagicMock()
            mappings = MagicMock()
            mappings.all.return_value = []
            r.mappings.return_value = mappings
            r.scalar_one.return_value = 0
            r.scalar_one_or_none.return_value = True
            return r

        db = AsyncMock()
        db.execute = execute_side_effect

        report = await svc.generate_weekly_report(
            tenant_id=TENANT_A,
            week_start=date(2026, 3, 24),
            db=db,
        )

        required_fields = {
            "tenant_id",
            "week_start",
            "week_end",
            "generated_at",
            "login_failures",
            "api_calls_by_app",
            "data_export_count",
            "critical_events",
            "critical_event_count",
            "compliance",
        }
        missing = required_fields - set(report.keys())
        assert not missing, f"周报缺少字段: {missing}"

    @pytest.mark.asyncio
    async def test_weekly_report_week_range_correct(self):
        """week_end 应为 week_start + 7天。"""
        from datetime import date

        from services.security_report_service import SecurityReportService

        svc = SecurityReportService()

        async def execute_side_effect(sql, params=None):
            r = MagicMock()
            mappings = MagicMock()
            mappings.all.return_value = []
            r.mappings.return_value = mappings
            r.scalar_one.return_value = 0
            r.scalar_one_or_none.return_value = True
            return r

        db = AsyncMock()
        db.execute = execute_side_effect

        report = await svc.generate_weekly_report(
            tenant_id=TENANT_A,
            week_start=date(2026, 3, 24),
            db=db,
        )
        assert report["week_start"] == "2026-03-24"
        assert report["week_end"] == "2026-03-31"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 9. query_logs 分页正确
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestQueryLogsPagination:
    @pytest.mark.asyncio
    async def test_query_logs_returns_pagination_structure(self):
        """query_logs 应返回含 items/total/page/size 的字典。"""
        svc = AuditLogService()

        call_count = {"n": 0}

        async def execute_side_effect(sql, params=None):
            call_count["n"] += 1
            r = MagicMock()
            if call_count["n"] == 1:
                # COUNT 查询
                r.scalar_one.return_value = 42
            else:
                # 数据行查询
                mappings = MagicMock()
                mappings.all.return_value = []
                r.mappings.return_value = mappings
            return r

        db = AsyncMock()
        db.execute = execute_side_effect

        result = await svc.query_logs(
            tenant_id=TENANT_A,
            actor_id=None,
            action=None,
            resource_type=None,
            severity=None,
            start_time=None,
            end_time=None,
            page=2,
            size=10,
            db=db,
        )
        assert result["total"] == 42
        assert result["page"] == 2
        assert result["size"] == 10
        assert "items" in result

    @pytest.mark.asyncio
    async def test_query_logs_page_clamped_to_min_1(self):
        """page < 1 时应被修正为 1。"""
        svc = AuditLogService()

        async def execute_side_effect(sql, params=None):
            r = MagicMock()
            r.scalar_one.return_value = 0
            mappings = MagicMock()
            mappings.all.return_value = []
            r.mappings.return_value = mappings
            return r

        db = AsyncMock()
        db.execute = execute_side_effect

        result = await svc.query_logs(
            tenant_id=TENANT_A,
            actor_id=None,
            action=None,
            resource_type=None,
            severity=None,
            start_time=None,
            end_time=None,
            page=-5,
            size=20,
            db=db,
        )
        assert result["page"] == 1

    @pytest.mark.asyncio
    async def test_query_logs_size_capped_at_200(self):
        """size > 200 时应被限制为 200。"""
        svc = AuditLogService()

        async def execute_side_effect(sql, params=None):
            r = MagicMock()
            r.scalar_one.return_value = 0
            mappings = MagicMock()
            mappings.all.return_value = []
            r.mappings.return_value = mappings
            return r

        db = AsyncMock()
        db.execute = execute_side_effect

        result = await svc.query_logs(
            tenant_id=TENANT_A,
            actor_id=None,
            action=None,
            resource_type=None,
            severity=None,
            start_time=None,
            end_time=None,
            page=1,
            size=9999,
            db=db,
        )
        assert result["size"] == 200


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 10. 跨租户审计日志隔离
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCrossTenantIsolation:
    @pytest.mark.asyncio
    async def test_query_uses_tenant_id_in_where_clause(self):
        """query_logs 的 SQL 中 tenant_id 参数应与调用方的 tenant_id 一致。"""
        svc = AuditLogService()
        captured_params: list[dict] = []

        async def execute_side_effect(sql, params=None):
            if params:
                captured_params.append(dict(params))
            r = MagicMock()
            r.scalar_one.return_value = 0
            mappings = MagicMock()
            mappings.all.return_value = []
            r.mappings.return_value = mappings
            return r

        db = AsyncMock()
        db.execute = execute_side_effect

        # 用 TENANT_B 查询
        await svc.query_logs(
            tenant_id=TENANT_B,
            actor_id=None,
            action=None,
            resource_type=None,
            severity=None,
            start_time=None,
            end_time=None,
            page=1,
            size=20,
            db=db,
        )
        assert len(captured_params) >= 1
        for p in captured_params:
            assert p.get("tenant_id") == str(TENANT_B), f"查询参数中 tenant_id 不正确: {p.get('tenant_id')}"

    @pytest.mark.asyncio
    async def test_log_inserts_correct_tenant_not_other(self):
        """log() 写入时 tenant_id 不应混入其他租户的 UUID。"""
        svc = AuditLogService()
        db = _make_db_mock()
        entry_a = _make_entry(tenant_id=TENANT_A)
        await svc.log(entry_a, db)
        params = db.execute.call_args[0][1]
        assert params["tenant_id"] == str(TENANT_A)
        assert params["tenant_id"] != str(TENANT_B)
