"""供应链报表模块测试

验证15个供应链报表的模块定义完整性:
1. 每个报表有 REPORT_ID / REPORT_NAME / CATEGORY
2. 每个报表有 SQL_TEMPLATE / DIMENSIONS / METRICS / FILTERS
3. SQL_TEMPLATE 包含 :tenant_id 参数
4. CATEGORY 均为 'supply'
5. 报表注册表包含所有 SCM 报表
6. list_scm_reports() 返回 15 条
7. 各报表 SQL_TEMPLATE 不为空
"""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reports import (
    scm_purchase_stats,
    scm_receiving_detail,
    scm_supplier_summary,
    scm_purchase_ranking,
    scm_transfer_stats,
    scm_waste_report,
    scm_inventory_balance,
    scm_inventory_status,
    scm_receipt_balance,
    scm_inventory_ledger,
    scm_inventory_warning,
    scm_cost_margin,
    scm_yield_comparison,
    scm_bom_cost_analysis,
    scm_ar_ledger,
    REPORT_REGISTRY,
    list_scm_reports,
)

SCM_MODULES = [
    scm_purchase_stats,
    scm_receiving_detail,
    scm_supplier_summary,
    scm_purchase_ranking,
    scm_transfer_stats,
    scm_waste_report,
    scm_inventory_balance,
    scm_inventory_status,
    scm_receipt_balance,
    scm_inventory_ledger,
    scm_inventory_warning,
    scm_cost_margin,
    scm_yield_comparison,
    scm_bom_cost_analysis,
    scm_ar_ledger,
]


class TestScmReportDefinitions:
    @pytest.mark.parametrize("mod", SCM_MODULES, ids=lambda m: m.REPORT_ID)
    def test_has_required_attrs(self, mod):
        """每个报表模块必须有标准属性"""
        assert hasattr(mod, "REPORT_ID")
        assert hasattr(mod, "REPORT_NAME")
        assert hasattr(mod, "CATEGORY")
        assert hasattr(mod, "DIMENSIONS")
        assert hasattr(mod, "METRICS")
        assert hasattr(mod, "FILTERS")

    @pytest.mark.parametrize("mod", SCM_MODULES, ids=lambda m: m.REPORT_ID)
    def test_category_is_supply(self, mod):
        """供应链报表 CATEGORY 均为 'supply'"""
        assert mod.CATEGORY == "supply"

    @pytest.mark.parametrize("mod", SCM_MODULES, ids=lambda m: m.REPORT_ID)
    def test_sql_template_has_tenant_id(self, mod):
        """SQL模板必须包含 :tenant_id 参数"""
        sql = getattr(mod, "SQL_TEMPLATE", "")
        assert ":tenant_id" in sql

    @pytest.mark.parametrize("mod", SCM_MODULES, ids=lambda m: m.REPORT_ID)
    def test_sql_template_not_empty(self, mod):
        """SQL模板不能为空"""
        sql = getattr(mod, "SQL_TEMPLATE", "")
        assert len(sql.strip()) > 50

    @pytest.mark.parametrize("mod", SCM_MODULES, ids=lambda m: m.REPORT_ID)
    def test_dimensions_and_metrics_not_empty(self, mod):
        """维度和指标列表不能为空"""
        assert len(mod.DIMENSIONS) > 0
        assert len(mod.METRICS) > 0


class TestScmReportRegistry:
    def test_all_scm_in_registry(self):
        """15个 SCM 报表都在全局注册表中"""
        for mod in SCM_MODULES:
            assert mod.REPORT_ID in REPORT_REGISTRY, f"{mod.REPORT_ID} not in registry"

    def test_list_scm_reports_count(self):
        """list_scm_reports 返回 15 条"""
        reports = list_scm_reports()
        assert len(reports) == 15

    def test_list_scm_reports_structure(self):
        """每条报表摘要包含 report_id / report_name / category"""
        reports = list_scm_reports()
        for r in reports:
            assert "report_id" in r
            assert "report_name" in r
            assert "category" in r
            assert r["category"] == "supply"

    def test_report_ids_unique(self):
        """所有 SCM 报表 ID 不重复"""
        ids = [mod.REPORT_ID for mod in SCM_MODULES]
        assert len(ids) == len(set(ids))


class TestSpecificReports:
    def test_purchase_stats_has_store_filter(self):
        assert "store_id" in scm_purchase_stats.FILTERS

    def test_inventory_warning_no_date_filter(self):
        """库存预警是实时快照，不需日期筛选"""
        assert "start_date" not in scm_inventory_warning.FILTERS

    def test_yield_comparison_has_variance(self):
        """理论实际对比表应有差异指标"""
        assert "variance_qty" in scm_yield_comparison.METRICS
        assert "variance_pct" in scm_yield_comparison.METRICS

    def test_ar_ledger_has_running_balance(self):
        """应收挂账表应有累计余额"""
        assert "running_balance_fen" in scm_ar_ledger.METRICS

    def test_receipt_balance_has_opening_closing(self):
        """收发结存表应有期初和期末"""
        assert "opening_qty" in scm_receipt_balance.METRICS
        assert "closing_qty" in scm_receipt_balance.METRICS
