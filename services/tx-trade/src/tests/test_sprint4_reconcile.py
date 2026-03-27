"""Sprint 4 测试 — 三层对账体系 + 外卖平台适配器 + 会员Golden ID

覆盖场景:
1. 导入微信CSV(10条) → 运行对账 → 发现2条差异
2. 三角对账 (订单 <-> 支付 <-> 银行 三方匹配)
3. 银行流水导入和自动匹配
4. 外卖订单: receive → confirm → ready → complete → settle (每个平台)
5. 平台佣金计算 (美团18%, 饿了么20%, 抖音10%)
6. 会员Golden ID从3个来源合并
7. 跨渠道客户旅程时间线
8. 平台菜单同步
9. T+1自动对账日程
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timezone, timedelta

import pytest

from services.reconciliation import ReconciliationService
from services.delivery_adapter import DeliveryPlatformAdapter
from services.member_golden_id import MemberGoldenIDService


# ─── Fixtures ───

BRAND_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())


@pytest.fixture(autouse=True)
def clean_state():
    """每个测试前清空内存存储"""
    ReconciliationService.clear_all_data()
    DeliveryPlatformAdapter.clear_all_data()
    MemberGoldenIDService.clear_all_data()
    yield


# ══════════════════════════════════════════
# 1. Layer 1: 微信CSV导入 + 对账 + 差异发现
# ══════════════════════════════════════════


def _build_wechat_csv_10_records():
    """生成10条微信支付对账单CSV（真实格式模拟）"""
    header = "trade_time,trade_no,out_trade_no,amount,fee,settle_amount,status"
    rows = [
        "2026-03-26 12:01:00,WX20260326120100001,PAY20260326120100A1,58.00,0.35,57.65,SUCCESS",
        "2026-03-26 12:15:00,WX20260326121500002,PAY20260326121500A2,128.00,0.77,127.23,SUCCESS",
        "2026-03-26 12:30:00,WX20260326123000003,PAY20260326123000A3,88.50,0.53,87.97,SUCCESS",
        "2026-03-26 13:00:00,WX20260326130000004,PAY20260326130000A4,256.00,1.54,254.46,SUCCESS",
        "2026-03-26 13:20:00,WX20260326132000005,PAY20260326132000A5,42.00,0.25,41.75,SUCCESS",
        "2026-03-26 14:00:00,WX20260326140000006,PAY20260326140000A6,198.00,1.19,196.81,SUCCESS",
        "2026-03-26 14:30:00,WX20260326143000007,PAY20260326143000A7,75.00,0.45,74.55,SUCCESS",
        "2026-03-26 15:00:00,WX20260326150000008,PAY20260326150000A8,320.00,1.92,318.08,SUCCESS",
        # 以下两条在POS中金额不同，将产生差异
        "2026-03-26 15:30:00,WX20260326153000009,PAY20260326153000A9,166.00,1.00,165.00,SUCCESS",
        "2026-03-26 16:00:00,WX20260326160000010,PAY20260326160000AA,89.00,0.53,88.47,SUCCESS",
    ]
    return header + "\n" + "\n".join(rows)


def _build_pos_payments_10_records():
    """生成10条POS端支付记录，其中2条与渠道不一致"""
    return [
        # 前8条正常匹配
        {"payment_no": "PAY20260326120100A1", "trade_no": "WX20260326120100001",
         "amount_fen": 5800, "fee_fen": 35, "method": "wechat", "order_no": "TX20260326001"},
        {"payment_no": "PAY20260326121500A2", "trade_no": "WX20260326121500002",
         "amount_fen": 12800, "fee_fen": 77, "method": "wechat", "order_no": "TX20260326002"},
        {"payment_no": "PAY20260326123000A3", "trade_no": "WX20260326123000003",
         "amount_fen": 8850, "fee_fen": 53, "method": "wechat", "order_no": "TX20260326003"},
        {"payment_no": "PAY20260326130000A4", "trade_no": "WX20260326130000004",
         "amount_fen": 25600, "fee_fen": 154, "method": "wechat", "order_no": "TX20260326004"},
        {"payment_no": "PAY20260326132000A5", "trade_no": "WX20260326132000005",
         "amount_fen": 4200, "fee_fen": 25, "method": "wechat", "order_no": "TX20260326005"},
        {"payment_no": "PAY20260326140000A6", "trade_no": "WX20260326140000006",
         "amount_fen": 19800, "fee_fen": 119, "method": "wechat", "order_no": "TX20260326006"},
        {"payment_no": "PAY20260326143000A7", "trade_no": "WX20260326143000007",
         "amount_fen": 7500, "fee_fen": 45, "method": "wechat", "order_no": "TX20260326007"},
        {"payment_no": "PAY20260326150000A8", "trade_no": "WX20260326150000008",
         "amount_fen": 32000, "fee_fen": 192, "method": "wechat", "order_no": "TX20260326008"},
        # 第9条：POS金额 16800 vs 渠道 16600 → amount_mismatch (差200分=2元)
        {"payment_no": "PAY20260326153000A9", "trade_no": "WX20260326153000009",
         "amount_fen": 16800, "fee_fen": 100, "method": "wechat", "order_no": "TX20260326009"},
        # 第10条：POS金额 9200 vs 渠道 8900 → amount_mismatch (差300分=3元)
        {"payment_no": "PAY20260326160000AA", "trade_no": "WX20260326160000010",
         "amount_fen": 9200, "fee_fen": 53, "method": "wechat", "order_no": "TX20260326010"},
    ]


class TestLayer1ChannelReconciliation:
    """Layer 1: POS单 vs 渠道账单"""

    def test_import_wechat_csv(self):
        """导入微信CSV — 10条记录"""
        svc = ReconciliationService(BRAND_ID, _build_pos_payments_10_records())
        csv_content = _build_wechat_csv_10_records()

        result = svc.import_channel_bill("wechat", csv_content)

        assert result['imported_count'] == 10
        assert result['channel'] == 'wechat'
        assert result['batch_id'].startswith('BATCH')
        assert result['date_range']['start'] is not None
        assert result['date_range']['end'] is not None

    def test_run_reconciliation_find_2_mismatches(self):
        """运行对账 — 发现2条金额差异"""
        svc = ReconciliationService(BRAND_ID, _build_pos_payments_10_records())
        csv_content = _build_wechat_csv_10_records()

        import_result = svc.import_channel_bill("wechat", csv_content)
        batch_id = import_result['batch_id']

        recon_result = svc.run_reconciliation(batch_id)

        assert recon_result['matched'] == 8, f"应有8条匹配，实际{recon_result['matched']}"
        assert recon_result['mismatch_count'] == 2, f"应有2条差异，实际{recon_result['mismatch_count']}"
        assert recon_result['pos_only_count'] == 0
        assert recon_result['channel_only_count'] == 0
        assert recon_result['diff_fen'] > 0

    def test_get_reconciliation_diffs(self):
        """获取差异明细"""
        svc = ReconciliationService(BRAND_ID, _build_pos_payments_10_records())
        csv_content = _build_wechat_csv_10_records()

        import_result = svc.import_channel_bill("wechat", csv_content)
        batch_id = import_result['batch_id']
        svc.run_reconciliation(batch_id)

        diffs = svc.get_reconciliation_diffs(batch_id)

        assert len(diffs) == 2
        for d in diffs:
            assert d['diff_type'] == 'amount_mismatch'
            assert d['status'] == 'pending'
            assert d['diff_fen'] != 0

        # 验证第一条差异: POS 16800 vs 渠道 16600
        diff_amounts = sorted([d['pos_amount_fen'] for d in diffs])
        assert 9200 in diff_amounts
        assert 16800 in diff_amounts

    def test_resolve_diff(self):
        """手动处理差异"""
        svc = ReconciliationService(BRAND_ID, _build_pos_payments_10_records())
        csv_content = _build_wechat_csv_10_records()

        import_result = svc.import_channel_bill("wechat", csv_content)
        batch_id = import_result['batch_id']
        svc.run_reconciliation(batch_id)

        diffs = svc.get_reconciliation_diffs(batch_id)
        diff_id = diffs[0]['diff_id']

        resolve_result = svc.resolve_diff(
            diff_id=diff_id,
            resolution='written_off',
            notes='经财务确认，差异2元已核销（顾客优惠券未入系统）',
        )

        assert resolve_result['status'] == 'resolved'
        assert resolve_result['resolution'] == 'written_off'

        # 再次查差异，应标记为已解决
        diffs_after = svc.get_reconciliation_diffs(batch_id)
        resolved_diff = next(d for d in diffs_after if d['diff_id'] == diff_id)
        assert resolved_diff['status'] == 'resolved'

    def test_pos_only_and_channel_only_detection(self):
        """检测POS有渠道无 + 渠道有POS无"""
        # POS多一条
        pos_payments = [
            {"payment_no": "PAY001", "trade_no": "WX001", "amount_fen": 5000,
             "fee_fen": 30, "method": "wechat", "order_no": "TX001"},
            {"payment_no": "PAY002", "trade_no": "WX_EXTRA", "amount_fen": 3000,
             "fee_fen": 18, "method": "wechat", "order_no": "TX002"},
        ]

        # 渠道多一条
        csv_content = (
            "trade_no,out_trade_no,amount,fee,settle_amount,trade_time,status\n"
            "WX001,PAY001,50.00,0.30,49.70,2026-03-26 12:00:00,SUCCESS\n"
            "WX_CH_EXTRA,PAYXXX,80.00,0.48,79.52,2026-03-26 13:00:00,SUCCESS\n"
        )

        svc = ReconciliationService(BRAND_ID, pos_payments)
        import_result = svc.import_channel_bill("wechat", csv_content)
        recon_result = svc.run_reconciliation(import_result['batch_id'])

        assert recon_result['matched'] == 1
        assert recon_result['pos_only_count'] == 1
        assert recon_result['channel_only_count'] == 1


# ══════════════════════════════════════════
# 2. Layer 2: 三角对账
# ══════════════════════════════════════════


class TestLayer2TriReconciliation:
    """Layer 2: 订单 <-> 支付 <-> 银行 三方匹配"""

    def test_tri_reconciliation_full_match(self):
        """订单+支付+银行三方完全匹配"""
        svc = ReconciliationService(BRAND_ID)

        orders = [
            {"order_id": "ORD001", "order_no": "TX20260326001", "total_fen": 15800,
             "final_fen": 15800, "status": "completed", "channel": "dine_in"},
            {"order_id": "ORD002", "order_no": "TX20260326002", "total_fen": 23600,
             "final_fen": 23600, "status": "completed", "channel": "dine_in"},
        ]
        payments = [
            {"payment_no": "PAY001", "order_id": "ORD001", "amount_fen": 15800,
             "trade_no": "WX001", "method": "wechat"},
            {"payment_no": "PAY002", "order_id": "ORD002", "amount_fen": 23600,
             "trade_no": "WX002", "method": "wechat"},
        ]
        bank_entries = [
            {"entry_id": "BANK001", "amount_fen": 15800, "description": "财付通入账",
             "counterparty": "财付通支付科技有限公司"},
            {"entry_id": "BANK002", "amount_fen": 23600, "description": "财付通入账",
             "counterparty": "财付通支付科技有限公司"},
        ]

        result = svc.run_tri_reconciliation(
            "2026-03-26",
            orders=orders,
            payments=payments,
            bank_entries=bank_entries,
        )

        assert result['total_orders'] == 2
        assert result['full_match'] == 2
        assert result['partial_match'] == 0
        assert result['no_match'] == 0
        assert result['discrepancy_fen'] == 0

    def test_tri_reconciliation_partial_and_no_match(self):
        """三角对账: 部分匹配 + 无匹配"""
        svc = ReconciliationService(BRAND_ID)

        orders = [
            {"order_id": "ORD001", "order_no": "TX001", "total_fen": 10000,
             "final_fen": 10000, "status": "completed", "channel": "dine_in"},
            {"order_id": "ORD002", "order_no": "TX002", "total_fen": 20000,
             "final_fen": 20000, "status": "completed", "channel": "dine_in"},
            {"order_id": "ORD003", "order_no": "TX003", "total_fen": 30000,
             "final_fen": 30000, "status": "completed", "channel": "dine_in"},
        ]
        # ORD001有支付+银行, ORD002只有支付, ORD003什么都没有
        payments = [
            {"payment_no": "PAY001", "order_id": "ORD001", "amount_fen": 10000,
             "trade_no": "WX001", "method": "wechat"},
            {"payment_no": "PAY002", "order_id": "ORD002", "amount_fen": 20000,
             "trade_no": "WX002", "method": "wechat"},
        ]
        bank_entries = [
            {"entry_id": "BANK001", "amount_fen": 10000, "description": "入账",
             "counterparty": "微信支付"},
        ]

        result = svc.run_tri_reconciliation(
            "2026-03-26",
            orders=orders,
            payments=payments,
            bank_entries=bank_entries,
        )

        assert result['total_orders'] == 3
        assert result['full_match'] == 1   # ORD001: 支付+银行都匹配
        assert result['partial_match'] == 1  # ORD002: 只有支付匹配
        assert result['no_match'] == 1      # ORD003: 无支付无银行


# ══════════════════════════════════════════
# 3. Layer 3: 银行流水
# ══════════════════════════════════════════


class TestLayer3BankStatement:
    """Layer 3: 银行流水导入+匹配"""

    def _build_bank_csv(self):
        """尝在一起品牌 — 招商银行流水"""
        return (
            "date,description,amount,balance,counterparty\n"
            "2026-03-26,财付通批量入账,1285.65,523860.25,财付通支付科技有限公司\n"
            "2026-03-26,支付宝批量入账,860.00,524720.25,支付宝(中国)网络技术有限公司\n"
            "2026-03-26,美团外卖结算,2350.00,527070.25,北京三快在线科技有限公司\n"
            "2026-03-26,POS刷卡入账,580.00,527650.25,中国银联股份有限公司\n"
            "2026-03-26,转账汇入,10000.00,537650.25,湖南省尝在一起餐饮管理有限公司\n"
        )

    def test_import_bank_statement(self):
        """导入招商银行流水"""
        svc = ReconciliationService(BRAND_ID)
        csv_content = self._build_bank_csv()

        result = svc.import_bank_statement("招商银行", csv_content)

        assert result['imported_count'] == 5
        assert result['bank_name'] == '招商银行'
        assert result['date_range']['start'] is not None

    def test_match_bank_entries(self):
        """银行流水自动匹配"""
        pos_payments = [
            {"payment_no": "PAY_WX01", "trade_no": "WX001", "amount_fen": 128565,
             "fee_fen": 0, "method": "wechat", "order_no": "TX001"},
            {"payment_no": "PAY_ALI01", "trade_no": "ALI001", "amount_fen": 86000,
             "fee_fen": 0, "method": "alipay", "order_no": "TX002"},
        ]

        svc = ReconciliationService(BRAND_ID, pos_payments)
        csv_content = self._build_bank_csv()
        svc.import_bank_statement("招商银行", csv_content)

        result = svc.match_bank_entries("2026-03-26")

        assert result['total_entries'] == 5
        assert result['matched'] >= 2  # 至少精确金额匹配2条
        assert result['match_rate'] > 0


# ══════════════════════════════════════════
# 4. 外卖订单全流程
# ══════════════════════════════════════════


class TestDeliveryOrderLifecycle:
    """外卖订单: receive → confirm → ready → complete"""

    def _build_menu_items(self):
        return [
            {"dish_id": "D001", "name": "酸菜鱼", "price_fen": 6800,
             "category": "招牌菜", "stock": 50, "sku_id": "SKU_SCY"},
            {"dish_id": "D002", "name": "水煮牛肉", "price_fen": 5800,
             "category": "热菜", "stock": 30, "sku_id": "SKU_SZNR"},
            {"dish_id": "D003", "name": "米饭", "price_fen": 200,
             "category": "主食", "stock": 999, "sku_id": "SKU_MF"},
            {"dish_id": "D004", "name": "蒜蓉西兰花", "price_fen": 2800,
             "category": "素菜", "stock": 40, "sku_id": "SKU_SRXLH"},
        ]

    def test_meituan_full_lifecycle(self):
        """美团外卖: 接单→确认→出餐→完成→结算"""
        adapter = DeliveryPlatformAdapter(
            store_id=STORE_ID,
            brand_id=BRAND_ID,
            menu_items=self._build_menu_items(),
        )

        # 1. 接单
        order = adapter.receive_order(
            platform="meituan",
            platform_order_id="MT2026032600001",
            items=[
                {"name": "酸菜鱼", "quantity": 1, "price_fen": 6800, "sku_id": "SKU_SCY"},
                {"name": "米饭", "quantity": 2, "price_fen": 200, "sku_id": "SKU_MF"},
            ],
            total_fen=7200,
            customer_phone="138****1234",
            delivery_address="长沙市岳麓区梅溪湖路188号",
            expected_time="2026-03-26T13:00:00+08:00",
        )

        assert order['status'] == 'confirmed'
        assert order['commission_fen'] == round(7200 * 0.18)  # 美团18%佣金
        assert order['merchant_receive_fen'] == 7200 - order['commission_fen']
        assert len(order['items_mapped']) == 2
        assert all(i['mapped'] for i in order['items_mapped'])

        order_id = order['order_id']

        # 2. 确认 + 设置出餐时间
        confirmed = adapter.confirm_order(order_id, estimated_ready_min=20)
        assert confirmed['status'] == 'preparing'
        assert confirmed['estimated_ready_min'] == 20

        # 3. 出餐
        ready = adapter.mark_ready(order_id)
        assert ready['status'] == 'ready'
        assert ready['ready_at'] is not None

        # 4. 完成配送
        completed = adapter.complete_order(order_id)
        assert completed['status'] == 'completed'
        assert completed['settlement_info']['commission_fen'] == round(7200 * 0.18)
        assert completed['settlement_info']['settle_days'] == 'T+7'

    def test_eleme_order_with_commission(self):
        """饿了么订单 — 20%佣金"""
        adapter = DeliveryPlatformAdapter(STORE_ID, BRAND_ID, self._build_menu_items())

        order = adapter.receive_order(
            platform="eleme",
            platform_order_id="EL2026032600001",
            items=[
                {"name": "水煮牛肉", "quantity": 1, "price_fen": 5800, "sku_id": "SKU_SZNR"},
                {"name": "蒜蓉西兰花", "quantity": 1, "price_fen": 2800, "sku_id": "SKU_SRXLH"},
                {"name": "米饭", "quantity": 3, "price_fen": 200, "sku_id": "SKU_MF"},
            ],
            total_fen=9200,
            customer_phone="139****5678",
            delivery_address="长沙市天心区芙蓉南路二段100号",
        )

        expected_commission = round(9200 * 0.20)
        assert order['commission_fen'] == expected_commission
        assert order['merchant_receive_fen'] == 9200 - expected_commission

    def test_douyin_order_with_commission(self):
        """抖音外卖 — 10%佣金 + T+3结算"""
        adapter = DeliveryPlatformAdapter(STORE_ID, BRAND_ID, self._build_menu_items())

        order = adapter.receive_order(
            platform="douyin",
            platform_order_id="DY2026032600001",
            items=[
                {"name": "酸菜鱼", "quantity": 2, "price_fen": 6800, "sku_id": "SKU_SCY"},
            ],
            total_fen=13600,
            customer_phone="137****9999",
            delivery_address="长沙市开福区万达广场B栋1501",
        )

        expected_commission = round(13600 * 0.10)
        assert order['commission_fen'] == expected_commission

        # 完成后检查T+3结算
        adapter.confirm_order(order['order_id'])
        adapter.mark_ready(order['order_id'])
        completed = adapter.complete_order(order['order_id'])
        assert completed['settlement_info']['settle_days'] == 'T+3'

    def test_cancel_order_merchant_responsible(self):
        """商家责任取消 — 全额退款"""
        adapter = DeliveryPlatformAdapter(STORE_ID, BRAND_ID, self._build_menu_items())

        order = adapter.receive_order(
            platform="meituan",
            platform_order_id="MT2026032600002",
            items=[{"name": "酸菜鱼", "quantity": 1, "price_fen": 6800}],
            total_fen=6800,
        )

        cancel_result = adapter.cancel_order(
            order['order_id'],
            reason="食材售罄",
            responsible_party="merchant",
        )

        assert cancel_result['status'] == 'cancelled'
        assert cancel_result['responsible_party'] == 'merchant'
        assert cancel_result['refund_fen'] == 6800  # 全额退

    def test_cancel_order_customer_responsible(self):
        """顾客责任取消"""
        adapter = DeliveryPlatformAdapter(STORE_ID, BRAND_ID, self._build_menu_items())

        order = adapter.receive_order(
            platform="eleme",
            platform_order_id="EL2026032600002",
            items=[{"name": "米饭", "quantity": 3, "price_fen": 200}],
            total_fen=600,
        )

        cancel_result = adapter.cancel_order(
            order['order_id'],
            reason="顾客不想要了",
            responsible_party="customer",
        )

        assert cancel_result['status'] == 'cancelled'
        assert cancel_result['responsible_party'] == 'customer'


# ══════════════════════════════════════════
# 5. 平台佣金计算
# ══════════════════════════════════════════


class TestPlatformCommission:
    """平台佣金计算验证"""

    def test_commission_rates(self):
        """验证三大平台佣金率"""
        assert DeliveryPlatformAdapter.PLATFORMS['meituan']['commission_rate'] == 0.18
        assert DeliveryPlatformAdapter.PLATFORMS['eleme']['commission_rate'] == 0.20
        assert DeliveryPlatformAdapter.PLATFORMS['douyin']['commission_rate'] == 0.10

    def test_platform_settlement_report(self):
        """平台结算报告"""
        adapter = DeliveryPlatformAdapter(STORE_ID, BRAND_ID)

        # 创建3笔美团订单
        for i in range(3):
            order = adapter.receive_order(
                platform="meituan",
                platform_order_id=f"MT_SETTLE_{i}",
                items=[{"name": "测试菜品", "quantity": 1, "price_fen": 10000}],
                total_fen=10000,
            )
            adapter.confirm_order(order['order_id'])
            adapter.mark_ready(order['order_id'])
            adapter.complete_order(order['order_id'])

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        settlement = adapter.get_platform_settlement(
            platform="meituan",
            date_range=(today, today),
        )

        assert settlement['completed_count'] == 3
        assert settlement['revenue_fen'] == 30000
        assert settlement['commission_fen'] == round(30000 * 0.18)
        assert settlement['commission_rate'] == 0.18
        assert settlement['net_fen'] == 30000 - round(30000 * 0.18)

    def test_get_platform_orders(self):
        """查询平台订单列表"""
        adapter = DeliveryPlatformAdapter(STORE_ID, BRAND_ID)

        adapter.receive_order(
            platform="meituan",
            platform_order_id="MT_LIST_001",
            items=[{"name": "鱼香肉丝", "quantity": 1, "price_fen": 3200}],
            total_fen=3200,
        )
        adapter.receive_order(
            platform="eleme",
            platform_order_id="EL_LIST_001",
            items=[{"name": "宫保鸡丁", "quantity": 1, "price_fen": 2800}],
            total_fen=2800,
        )

        # 全部订单
        all_orders = adapter.get_platform_orders()
        assert len(all_orders) == 2

        # 仅美团
        mt_orders = adapter.get_platform_orders(platform="meituan")
        assert len(mt_orders) == 1
        assert mt_orders[0]['platform'] == 'meituan'


# ══════════════════════════════════════════
# 6. 会员Golden ID
# ══════════════════════════════════════════


class TestMemberGoldenID:
    """会员Golden ID — 多源合并"""

    def test_merge_3_sources(self):
        """从堂食+美团+小程序三个渠道合并"""
        svc = MemberGoldenIDService(BRAND_ID)

        profiles = [
            {
                "source": "dine_in",
                "name": "张三丰",
                "gender": "male",
                "birthday": "1990-05-15",
                "total_spend_fen": 128000,  # 1280元
                "visit_count": 8,
                "preferred_dishes": ["酸菜鱼", "水煮牛肉", "剁椒鱼头"],
                "tags": ["湘菜爱好者", "辣度重"],
                "last_visit": "2026-03-20T12:00:00+08:00",
                "registered_at": "2025-06-01T10:00:00+08:00",
            },
            {
                "source": "meituan",
                "name": "张三丰",
                "total_spend_fen": 45600,   # 456元
                "visit_count": 12,
                "preferred_dishes": ["酸菜鱼", "麻婆豆腐", "回锅肉"],
                "tags": ["外卖常客"],
                "last_visit": "2026-03-25T19:30:00+08:00",
                "registered_at": "2025-09-15T14:00:00+08:00",
            },
            {
                "source": "miniapp",
                "name": "张三丰",
                "address": "长沙市岳麓区梅溪湖路188号",
                "email": "zhangsan@example.com",
                "total_spend_fen": 8800,    # 88元
                "visit_count": 2,
                "preferred_dishes": ["蛋炒饭"],
                "tags": ["小程序用户"],
                "last_visit": "2026-03-22T11:00:00+08:00",
                "registered_at": "2026-01-10T16:00:00+08:00",
            },
        ]

        result = svc.merge_profiles("13812345678", profiles)

        assert result['member_id'].startswith('GID')
        assert result['source_count'] == 3

        merged = result['merged_profile']
        assert merged['name'] == '张三丰'
        assert merged['total_spend_fen'] == 128000 + 45600 + 8800  # 合计
        assert merged['visit_count'] == 8 + 12 + 2  # 合计
        assert '酸菜鱼' in merged['preferred_dishes']
        assert '麻婆豆腐' in merged['preferred_dishes']
        assert '蛋炒饭' in merged['preferred_dishes']
        assert 'dine_in' in merged['sources']
        assert 'meituan' in merged['sources']
        assert 'miniapp' in merged['sources']
        assert merged['address'] == '长沙市岳麓区梅溪湖路188号'

    def test_get_golden_profile_with_rfm(self):
        """获取统一画像 — 含RFM评分"""
        svc = MemberGoldenIDService(BRAND_ID)

        # 创建高价值会员
        now = datetime.now(timezone.utc)
        svc.merge_profiles("13812345678", [
            {
                "source": "dine_in",
                "name": "李富贵",
                "total_spend_fen": 680000,  # 6800元
                "visit_count": 25,
                "last_visit": (now - timedelta(days=5)).isoformat(),
                "registered_at": (now - timedelta(days=365)).isoformat(),
            },
        ])

        member_id = svc.merge_profiles("13812345678", [])['member_id']
        profile = svc.get_golden_profile(member_id)

        assert profile['total_spend_fen'] == 680000
        assert profile['visit_count'] == 25
        assert profile['rfm']['tier'] in ('diamond', 'gold')
        assert profile['rfm']['recency_level'] == 'active'
        assert profile['rfm']['frequency_level'] == 'high'
        assert profile['rfm']['monetary_level'] == 'high'
        assert profile['lifecycle'] == 'mature'

    def test_enrich_from_order(self):
        """订单后自动充实画像"""
        svc = MemberGoldenIDService(BRAND_ID)

        # 先创建会员
        result = svc.merge_profiles("13899998888", [
            {
                "source": "dine_in",
                "name": "王小明",
                "total_spend_fen": 50000,
                "visit_count": 3,
                "last_visit": "2026-03-15T12:00:00+08:00",
                "registered_at": "2026-01-01T10:00:00+08:00",
            },
        ])
        member_id = result['member_id']

        # 模拟一笔新订单
        enrich = svc.enrich_from_order(member_id, {
            "order_id": "ORD_NEW_001",
            "order_no": "TX20260327001",
            "channel": "dine_in",
            "total_fen": 18800,
            "items": [
                {"name": "糖醋排骨", "quantity": 1, "price_fen": 5800},
                {"name": "啤酒鸭", "quantity": 1, "price_fen": 6800},
                {"name": "米饭", "quantity": 2, "price_fen": 200},
            ],
            "order_time": "2026-03-27T12:30:00+08:00",
        })

        assert enrich['new_spend_total_fen'] == 50000 + 18800
        assert enrich['new_visit_count'] == 4
        assert 'total_spend_fen' in enrich['updated_fields']
        assert 'visit_count' in enrich['updated_fields']

    def test_detect_duplicate(self):
        """检测重复会员"""
        svc = MemberGoldenIDService(BRAND_ID)

        svc.merge_profiles("13812345678", [
            {"source": "dine_in", "name": "张三丰", "total_spend_fen": 50000, "visit_count": 5},
        ])
        svc.merge_profiles("13899999999", [
            {"source": "dine_in", "name": "张三丰", "total_spend_fen": 30000, "visit_count": 3},
        ])

        # 精确手机号匹配
        dups = svc.detect_duplicate("13812345678")
        assert len(dups) >= 1
        assert dups[0]['match_type'] == 'exact_phone'
        assert dups[0]['confidence'] == 1.0

        # 同名匹配
        dups_name = svc.detect_duplicate("13800001111", name="张三丰")
        same_name = [d for d in dups_name if d['match_type'] == 'same_name']
        assert len(same_name) >= 1


# ══════════════════════════════════════════
# 7. 跨渠道客户旅程
# ══════════════════════════════════════════


class TestCrossChannelJourney:
    """跨渠道客户旅程时间线"""

    def test_journey_timeline(self):
        """多渠道触点时间线"""
        svc = MemberGoldenIDService(BRAND_ID)

        result = svc.merge_profiles("13866667777", [
            {
                "source": "dine_in",
                "name": "赵大厨",
                "total_spend_fen": 20000,
                "visit_count": 1,
                "last_visit": "2026-03-01T12:00:00+08:00",
                "registered_at": "2026-03-01T12:00:00+08:00",
            },
        ])
        member_id = result['member_id']

        # 模拟多个渠道的订单
        svc.enrich_from_order(member_id, {
            "order_id": "ORD_DI_001",
            "order_no": "TX20260301001",
            "channel": "dine_in",
            "total_fen": 20000,
            "items": [{"name": "红烧肉", "quantity": 1, "price_fen": 4800}],
            "order_time": "2026-03-01T12:00:00+08:00",
        })

        svc.enrich_from_order(member_id, {
            "order_id": "ORD_MT_001",
            "order_no": "MT20260310001",
            "channel": "meituan",
            "total_fen": 5600,
            "items": [{"name": "酸菜鱼", "quantity": 1, "price_fen": 5600}],
            "order_time": "2026-03-10T19:00:00+08:00",
        })

        svc.enrich_from_order(member_id, {
            "order_id": "ORD_MP_001",
            "order_no": "MP20260320001",
            "channel": "miniapp",
            "total_fen": 3200,
            "items": [{"name": "鱼香肉丝套餐", "quantity": 1, "price_fen": 3200}],
            "order_time": "2026-03-20T12:30:00+08:00",
        })

        journey = svc.get_cross_channel_journey(member_id)

        assert len(journey) == 3
        # 验证按时间排序
        assert journey[0]['channel'] == 'dine_in'
        assert journey[1]['channel'] == 'meituan'
        assert journey[2]['channel'] == 'miniapp'

        # 验证金额
        assert journey[0]['amount_fen'] == 20000
        assert journey[1]['amount_fen'] == 5600
        assert journey[2]['amount_fen'] == 3200

    def test_ltv_prediction(self):
        """会员LTV预测"""
        svc = MemberGoldenIDService(BRAND_ID)
        now = datetime.now(timezone.utc)

        result = svc.merge_profiles("13877778888", [
            {
                "source": "dine_in",
                "name": "陈老板",
                "total_spend_fen": 320000,  # 3200元
                "visit_count": 15,
                "last_visit": (now - timedelta(days=3)).isoformat(),
                "registered_at": (now - timedelta(days=180)).isoformat(),
            },
        ])
        member_id = result['member_id']

        ltv = svc.calculate_ltv(member_id)

        assert ltv['historical_spend_fen'] == 320000
        assert ltv['visit_count'] == 15
        assert ltv['avg_order_fen'] > 0
        assert ltv['frequency_per_month'] > 0
        assert ltv['retention_rate'] > 0
        assert ltv['predicted_ltv_fen'] > 0
        assert ltv['predicted_ltv_fen'] > ltv['historical_spend_fen']  # LTV应大于历史消费


# ══════════════════════════════════════════
# 8. 平台菜单同步
# ══════════════════════════════════════════


class TestMenuSync:
    """平台菜单同步"""

    def test_sync_menu_to_meituan(self):
        """同步菜单到美团"""
        menu_items = [
            {"dish_id": "D001", "name": "酸菜鱼（大份）", "price_fen": 6800,
             "category": "招牌菜", "stock": 50},
            {"dish_id": "D002", "name": "水煮牛肉", "price_fen": 5800,
             "category": "热菜", "stock": 30},
            {"dish_id": "D003", "name": "米饭", "price_fen": 200,
             "category": "主食", "stock": 999},
            {"dish_id": "D004", "name": "可乐", "price_fen": 500,
             "category": "饮品", "stock": 100},
        ]

        adapter = DeliveryPlatformAdapter(STORE_ID, BRAND_ID, menu_items)
        result = adapter.sync_menu_to_platform("meituan")

        assert result['platform'] == 'meituan'
        assert result['platform_name'] == '美团外卖'
        assert result['synced_count'] == 4
        assert result['failed_count'] == 0

        # 验证每个菜品都有平台SKU
        synced_items = [d for d in result['details'] if d['status'] == 'synced']
        assert len(synced_items) == 4
        for item in synced_items:
            assert item['platform_sku_id'].startswith('MEITUAN_')

    def test_sync_menu_to_all_platforms(self):
        """同步菜单到所有平台"""
        menu_items = [
            {"dish_id": "D001", "name": "剁椒鱼头", "price_fen": 8800, "category": "招牌菜", "stock": 20},
        ]
        adapter = DeliveryPlatformAdapter(STORE_ID, BRAND_ID, menu_items)

        for platform in ["meituan", "eleme", "douyin"]:
            result = adapter.sync_menu_to_platform(platform)
            assert result['synced_count'] == 1
            assert result['platform'] == platform

    def test_unmapped_items_warning(self):
        """外卖订单中有菜品未在门店菜单中映射"""
        menu_items = [
            {"dish_id": "D001", "name": "酸菜鱼", "price_fen": 6800, "stock": 50},
        ]
        adapter = DeliveryPlatformAdapter(STORE_ID, BRAND_ID, menu_items)

        order = adapter.receive_order(
            platform="meituan",
            platform_order_id="MT_UNMAP_001",
            items=[
                {"name": "酸菜鱼", "quantity": 1, "price_fen": 6800},
                {"name": "神秘新菜", "quantity": 1, "price_fen": 9900},  # 菜单中没有
            ],
            total_fen=16700,
        )

        assert '神秘新菜' in order['unmapped_items']
        mapped_flags = [i['mapped'] for i in order['items_mapped']]
        assert True in mapped_flags   # 酸菜鱼匹配
        assert False in mapped_flags  # 神秘新菜未匹配


# ══════════════════════════════════════════
# 9. T+1自动对账调度
# ══════════════════════════════════════════


class TestAutoReconcileSchedule:
    """T+1自动对账日程"""

    def test_auto_reconcile_schedule(self):
        """生成自动对账任务列表"""
        svc = ReconciliationService(BRAND_ID)
        schedule = svc.auto_reconcile_schedule()

        assert schedule['brand_id'] == BRAND_ID
        assert len(schedule['tasks']) == 5

        task_types = [t['task_type'] for t in schedule['tasks']]
        assert 'channel_reconcile' in task_types
        assert 'tri_reconcile' in task_types
        assert 'bank_match' in task_types
        assert 'daily_report' in task_types

        # 验证微信和支付宝都有单独任务
        channel_tasks = [t for t in schedule['tasks'] if t['task_type'] == 'channel_reconcile']
        channels = [t['channel'] for t in channel_tasks]
        assert 'wechat' in channels
        assert 'alipay' in channels

        # 验证日期是昨天
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
        assert schedule['reconcile_target_date'] == yesterday

    def test_daily_reconciliation_report(self):
        """日对账报告"""
        pos_payments = _build_pos_payments_10_records()
        svc = ReconciliationService(BRAND_ID, pos_payments)

        # 先运行对账
        csv_content = _build_wechat_csv_10_records()
        import_result = svc.import_channel_bill("wechat", csv_content)
        svc.run_reconciliation(import_result['batch_id'])

        report = svc.get_daily_reconciliation_report("2026-03-26")

        assert report['transaction_count'] == 10
        assert report['revenue_fen'] > 0
        assert report['fee_fen'] > 0
        assert report['net_fen'] == report['revenue_fen'] - report['fee_fen']
        assert 'wechat' in report['by_method']
        assert report['matched'] == 8
        assert report['unmatched'] == 0  # mismatch不算unmatched
        assert len(report['action_items']) >= 2  # 2条差异生成2条待办

    def test_reconciliation_summary(self):
        """对账汇总报告"""
        svc = ReconciliationService(BRAND_ID, _build_pos_payments_10_records())
        csv_content = _build_wechat_csv_10_records()

        import_result = svc.import_channel_bill("wechat", csv_content)
        svc.run_reconciliation(import_result['batch_id'])

        summary = svc.get_reconciliation_summary(("2026-03-01", "2026-03-31"))

        assert summary['total_matched'] == 8
        assert summary['unresolved_count'] == 2
        assert summary['match_rate'] > 0
        assert 'wechat' in summary['by_channel']


# ══════════════════════════════════════════
# 10. 平台对账
# ══════════════════════════════════════════


class TestPlatformReconciliation:
    """平台订单对账"""

    def test_reconcile_meituan_orders(self):
        """美团订单内部 vs 平台对账"""
        adapter = DeliveryPlatformAdapter(STORE_ID, BRAND_ID)

        # 创建2笔完成订单
        for i in range(2):
            order = adapter.receive_order(
                platform="meituan",
                platform_order_id=f"MT_RECON_{i}",
                items=[{"name": "菜品", "quantity": 1, "price_fen": 5000}],
                total_fen=5000,
            )
            adapter.confirm_order(order['order_id'])
            adapter.mark_ready(order['order_id'])
            adapter.complete_order(order['order_id'])

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result = adapter.reconcile_platform("meituan", today)

        assert result['total_internal'] == 2
        assert result['matched'] == 2
        assert result['internal_only'] == 0
        assert result['platform_only'] == 0
        assert result['amount_mismatch'] == 0


# ══════════════════════════════════════════
# 运行入口
# ══════════════════════════════════════════


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
