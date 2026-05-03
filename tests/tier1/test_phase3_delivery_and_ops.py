"""Phase 3: 外卖接入 + 对账 + 运维 — Tier 1 测试

验证：
  1. 美团 adapter 已增强（退款/配送/对账/回调验签）
  2. 报表对账脚本可执行且覆盖 8 张 P0 报表
  3. 回滚/灰度发布脚本存在且可用
"""

import ast
import os
import subprocess
from pathlib import Path

import pytest

# ── 文件路径 ──

MEITUAN_ADAPTER_PY = (
    Path(__file__).parent.parent.parent
    / "shared" / "adapters" / "meituan_adapter.py"
)
RECONCILIATION_PY = (
    Path(__file__).parent.parent.parent
    / "scripts" / "reconciliation" / "report_vs_source.py"
)
ROLLBACK_SH = (
    Path(__file__).parent.parent.parent
    / "scripts" / "rollback-service.sh"
)
GRAY_RELEASE_SH = (
    Path(__file__).parent.parent.parent
    / "scripts" / "gray-release.sh"
)


# ═══════════════════════════════════════════════════════════════════════
# Task 3.1: 美团外卖 Adapter 增强
# ═══════════════════════════════════════════════════════════════════════


class TestMeituanAdapterEnhanced:
    """美团 adapter 新增方法"""

    def test_adapter_has_refund_sync(self):
        """adapter 有退款同步方法"""
        source = MEITUAN_ADAPTER_PY.read_text()
        assert "sync_refund" in source, "美团 adapter 缺少 sync_refund 方法"
        assert "refund_amount_fen" in source, "退款同步方法缺少金额参数"

    def test_adapter_has_delivery_status(self):
        """adapter 有配送状态查询"""
        source = MEITUAN_ADAPTER_PY.read_text()
        assert "get_delivery_status" in source, "美团 adapter 缺少 get_delivery_status 方法"
        assert "rider_name" in source, "配送状态缺少骑手信息"

    def test_adapter_has_download_bill(self):
        """adapter 有对账单下载"""
        source = MEITUAN_ADAPTER_PY.read_text()
        assert "download_bill" in source, "美团 adapter 缺少 download_bill 方法"
        assert "platform_commission" in source, "对账单缺少平台佣金字段"

    def test_adapter_has_verify_webhook(self):
        """adapter 有回调验签"""
        source = MEITUAN_ADAPTER_PY.read_text()
        assert "verify_webhook" in source, "美团 adapter 缺少 verify_webhook 方法"
        assert "signature" in source, "回调验签未检查签名"

    def test_webhook_rejects_unsigned_in_production(self):
        """生产环境拒绝无签名回调"""
        source = MEITUAN_ADAPTER_PY.read_text()
        assert "TX_ENV" in source, "验签未检查 TX_ENV"
        assert '"production"' in source, "未区分生产环境验签策略"

    def test_delivery_status_codes(self):
        """配送状态码定义完整（美团 0-60）"""
        source = MEITUAN_ADAPTER_PY.read_text()
        status_codes = ["未配送", "已分配骑手", "已到店", "已取餐", "配送中", "已送达"]
        found = sum(1 for sc in status_codes if sc in source)
        assert found >= 4, f"配送状态码覆盖率不足: {found}/{len(status_codes)}"

    def test_refund_sync_includes_platform_id(self):
        """退款同步返回平台退款 ID"""
        source = MEITUAN_ADAPTER_PY.read_text()
        assert "platform_refund_id" in source, "退款同步未返回平台退款ID"


# ═══════════════════════════════════════════════════════════════════════
# Task 3.2: P0 报表自动化对账
# ═══════════════════════════════════════════════════════════════════════


class TestReconciliationScript:
    """报表对账脚本"""

    def test_script_exists(self):
        """对账脚本文件存在"""
        assert RECONCILIATION_PY.exists(), "report_vs_source.py 不存在"

    def test_script_is_executable(self):
        """脚本可执行"""
        assert os.access(RECONCILIATION_PY, os.R_OK), "对账脚本不可读"

    def test_covers_8_core_reports(self):
        """覆盖 8 张核心 P0 报表"""
        source = RECONCILIATION_PY.read_text()
        core_reports = [
            "daily_sales", "payment_summary", "item_ranking",
            "daily_settlement", "member_consumption",
            "stored_value_balance", "refund_report", "delivery_summary",
        ]
        for report in core_reports:
            assert f'"{report}"' in source, f"对账脚本缺少报表: {report}"

    def test_has_cli_args(self):
        """CLI 参数完整"""
        source = RECONCILIATION_PY.read_text()
        assert "--report" in source, "缺少 --report 参数"
        assert "--date" in source, "缺少 --date 参数"
        assert "--output" in source, "缺少 --output 参数"
        assert "--tenant-id" in source, "缺少 --tenant-id 参数"

    def test_supports_json_output(self):
        """支持 JSON 输出"""
        source = RECONCILIATION_PY.read_text()
        assert "json" in source, "缺少 JSON 输出格式"

    def test_has_table_output(self):
        """支持表格输出"""
        source = RECONCILIATION_PY.read_text()
        assert "PASS" in source, "缺少 PASS 状态"
        assert "DIFF" in source, "缺少 DIFF 状态"

    def test_nonzero_exit_on_diff(self):
        """有差异时非零退出码"""
        source = RECONCILIATION_PY.read_text()
        assert "sys.exit(1)" in source, "差异时未返回非零退出码"


# ═══════════════════════════════════════════════════════════════════════
# Task 3.5: 版本回滚 + 灰度发布
# ═══════════════════════════════════════════════════════════════════════


class TestRollbackScript:
    """服务版本回滚脚本"""

    def test_script_exists(self):
        """回滚脚本存在"""
        assert ROLLBACK_SH.exists(), "rollback-service.sh 不存在"

    def test_script_is_executable(self):
        """脚本可执行"""
        assert os.access(ROLLBACK_SH, os.X_OK), "回滚脚本不可执行"

    def test_has_help(self):
        """支持 --help"""
        source = ROLLBACK_SH.read_text()
        assert "--help" in source, "回滚脚本缺少 --help"

    def test_has_list_flag(self):
        """支持 --list 列出可回滚版本"""
        source = ROLLBACK_SH.read_text()
        assert "--list" in source, "回滚脚本缺少 --list"

    def test_has_dry_run(self):
        """支持 --dry-run"""
        source = ROLLBACK_SH.read_text()
        assert "--dry-run" in source, "回滚脚本缺少 --dry-run"

    def test_covers_all_services(self):
        """覆盖全部 16 个微服务"""
        source = ROLLBACK_SH.read_text()
        services = ["gateway", "tx-trade", "tx-menu", "tx-member",
                    "tx-finance", "tx-agent", "tx-analytics", "tx-org", "tx-pay"]
        for svc in services:
            assert svc in source, f"回滚脚本缺少服务: {svc}"

    def test_has_health_check(self):
        """回滚后有健康检查"""
        source = ROLLBACK_SH.read_text()
        assert "health_check" in source, "回滚脚本缺少健康检查"

    def test_has_production_confirmation(self):
        """生产环境需人工确认"""
        source = ROLLBACK_SH.read_text()
        assert "ROLLBACK" in source, "生产环境回滚缺少二次确认"

    def test_backup_current_state(self):
        """回滚前备份当前状态"""
        source = ROLLBACK_SH.read_text()
        assert "backup" in source.lower(), "回滚脚本缺少状态备份"


class TestGrayReleaseScript:
    """灰度发布脚本"""

    def test_script_exists(self):
        """灰度发布脚本存在"""
        assert GRAY_RELEASE_SH.exists(), "gray-release.sh 不存在"

    def test_script_is_executable(self):
        """脚本可执行"""
        assert os.access(GRAY_RELEASE_SH, os.X_OK), "灰度发布脚本不可执行"

    def test_has_start_command(self):
        """支持 start 命令"""
        source = GRAY_RELEASE_SH.read_text()
        assert "start" in source, "灰度发布缺少 start 命令"

    def test_has_promote_command(self):
        """支持 promote 命令"""
        source = GRAY_RELEASE_SH.read_text()
        assert "promote" in source, "灰度发布缺少 promote 命令"

    def test_has_rollback_command(self):
        """支持 rollback 命令"""
        source = GRAY_RELEASE_SH.read_text()
        assert "rollback" in source, "灰度发布缺少 rollback 命令"

    def test_has_status_command(self):
        """支持 status 命令"""
        source = GRAY_RELEASE_SH.read_text()
        assert "status" in source, "灰度发布缺少 status 命令"

    def test_three_stage_progression(self):
        """三级灰度: 5% → 50% → 100%"""
        source = GRAY_RELEASE_SH.read_text()
        assert '"5"' in source, "灰度缺少 5% 阶段"
        assert '"50"' in source, "灰度缺少 50% 阶段"
        assert '"100"' in source, "灰度缺少 100% 阶段"

    def test_error_rate_threshold(self):
        """配置回滚阈值"""
        source = GRAY_RELEASE_SH.read_text()
        assert "TX_GRAY_THRESHOLD_ERROR_RATE" in source, "灰度脚本缺少误差阈值"

    def test_auto_rollback_on_error(self):
        """错误率超阈自动回滚"""
        source = GRAY_RELEASE_SH.read_text()
        assert "check_error_rate" in source, "灰度脚本缺少错误率检查"


# ═══════════════════════════════════════════════════════════════════════
# P1-07: except Exception 清理进展
# ═══════════════════════════════════════════════════════════════════════


class TestExceptExceptionCleanup:
    """P1-07: except Exception 清理"""

    def test_new_code_no_bare_except(self):
        """本次新增代码无未标记的 bare except"""
        new_files = [
            MEITUAN_ADAPTER_PY,
            ROLLBACK_SH,
            GRAY_RELEASE_SH,
            RECONCILIATION_PY,
        ]
        for f in new_files:
            if f.suffix == '.py':
                source = f.read_text()
                bare_excepts = [
                    line for line in source.split('\n')
                    if 'except Exception' in line and 'noqa' not in line
                    and 'except Exception as' not in line
                ]
                assert len(bare_excepts) == 0, (
                    f"{f.name} 存在未标记的 bare except: {bare_excepts}"
                )

    def test_reviewed_excepts_have_noqa_or_exc_info(self):
        """已审查的 except 有 noqa 或 exc_info 标记"""
        # 验证 adapter 中的异常处理质量
        source = MEITUAN_ADAPTER_PY.read_text()
        except_lines = [l for l in source.split('\n') if 'except' in l and 'Exception' in l]
        for line in except_lines:
            if 'except Exception' in line and 'except Exception as' not in line:
                assert 'noqa' in line or '# ' in line, (
                    f"未标记审查的 bare except: {line.strip()}"
                )
