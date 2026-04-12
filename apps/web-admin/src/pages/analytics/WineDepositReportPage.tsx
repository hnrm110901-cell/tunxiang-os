/**
 * 存酒 + 押金 + 企业欠款 专项报表
 * 三 Tab：存酒汇总 | 押金台账 | 企业欠款
 * API:
 *   存酒 → /api/v1/wine-storage/* (wineStorageApi)
 *   押金 → /api/v1/deposits/*     (depositApi)
 *   企业 → /api/v1/enterprise/*   (enterpriseAdminApi)
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Empty,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { txFetchData } from '../../api';
import {
  getDepositAging,
  getDepositLedger,
  listDepositsByStore,
  type DepositAgingItem,
  type DepositLedgerItem,
  type DepositRecord,
} from '../../api/depositApi';
import {
  getExpiringSoon,
  getWineSummary,
  listWineByStore,
  type WineExpiringItem,
  type WineListResponse,
  type WineSummaryReport,
} from '../../api/wineStorageApi';
import {
  listEnterprises,
  getAuditTrail,
  type EnterpriseAccount,
  type EnterpriseSignRecord,
  type EnterpriseBill,
} from '../../api/enterpriseAdminApi';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

// ─── 工具函数 ───

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function fmtMoney(fen: number): string {
  return `¥${fenToYuan(fen)}`;
}

// ─── 门店列表 Hook ───

function useStores() {
  const [stores, setStores] = useState<Array<{ value: string; label: string }>>([]);
  useEffect(() => {
    txFetchData<{ items: Array<{ id: string; name: string }> }>('/api/v1/org/stores?status=active')
      .then((d) => setStores((d.items ?? []).map((s) => ({ value: s.id, label: s.name }))))
      .catch(() => setStores([]));
  }, []);
  return stores;
}

// ═══════════════════════════════════════════════════════════
// TAB 1: 存酒汇总报表
// ═══════════════════════════════════════════════════════════

function WineSummaryTab() {
  const stores = useStores();
  const [storeId, setStoreId] = useState<string | undefined>(undefined);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [expiringLoading, setExpiringLoading] = useState(false);

  const [summary, setSummary] = useState<WineSummaryReport | null>(null);
  const [detail, setDetail] = useState<WineListResponse | null>(null);
  const [expiring, setExpiring] = useState<WineExpiringItem[]>([]);

  const load = useCallback(async (sid: string) => {
    setSummaryLoading(true);
    setDetailLoading(true);
    setExpiringLoading(true);

    const [sumRes, detRes, expRes] = await Promise.allSettled([
      getWineSummary(sid),
      listWineByStore(sid, { size: 100 }),
      getExpiringSoon(sid, 30),
    ]);

    if (sumRes.status === 'fulfilled') setSummary(sumRes.value);
    setSummaryLoading(false);

    if (detRes.status === 'fulfilled') setDetail(detRes.value);
    setDetailLoading(false);

    if (expRes.status === 'fulfilled') setExpiring(expRes.value.items);
    setExpiringLoading(false);
  }, []);

  useEffect(() => {
    if (storeId) void load(storeId);
  }, [storeId, load]);

  // 汇总表 — 按品类
  const summaryColumns: ColumnsType<{
    wine_category: string;
    storage_count: number;
    total_quantity: number;
    total_estimated_value_fen: number;
  }> = [
    { title: '品类', dataIndex: 'wine_category', key: 'wine_category' },
    { title: '存入件数', dataIndex: 'storage_count', key: 'storage_count', align: 'right' },
    { title: '剩余数量', dataIndex: 'total_quantity', key: 'total_quantity', align: 'right' },
    {
      title: '估值',
      dataIndex: 'total_estimated_value_fen',
      key: 'val',
      align: 'right',
      render: (v: number) => (v ? fmtMoney(v) : '—'),
    },
  ];

  // 明细表
  const detailColumns: ColumnsType<WineListResponse['items'][0]> = [
    { title: '客户', dataIndex: 'customer_id', key: 'cust', ellipsis: true },
    { title: '酒品', dataIndex: 'wine_name', key: 'wine_name', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s: string) => {
        const map: Record<string, string> = {
          stored: 'green',
          partially_retrieved: 'orange',
          fully_retrieved: 'default',
          expired: 'red',
        };
        const label: Record<string, string> = {
          stored: '存放中',
          partially_retrieved: '部分取出',
          fully_retrieved: '已取完',
          expired: '已到期',
          transferred: '已转让',
          written_off: '已核销',
        };
        return <Tag color={map[s] ?? 'default'}>{label[s] ?? s}</Tag>;
      },
    },
    { title: '现存量', dataIndex: 'quantity', key: 'qty', align: 'right' },
    { title: '原存量', dataIndex: 'original_qty', key: 'orig', align: 'right' },
    {
      title: '到期日',
      dataIndex: 'expires_at',
      key: 'exp',
      render: (v: string | null) => {
        if (!v) return '—';
        const days = dayjs(v).diff(dayjs(), 'day');
        return (
          <span style={{ color: days <= 7 ? '#A32D2D' : days <= 30 ? '#BA7517' : '#2C2C2A' }}>
            {dayjs(v).format('YYYY-MM-DD')}
            {days >= 0 && ` (${days}天)`}
          </span>
        );
      },
    },
    { title: '位置', dataIndex: 'cabinet_position', key: 'pos', render: (v: string | null) => v ?? '—' },
  ];

  // 即将到期
  const expiringColumns: ColumnsType<WineExpiringItem> = [
    { title: '客户', dataIndex: 'customer_id', key: 'cust', ellipsis: true },
    { title: '酒品', dataIndex: 'wine_name', key: 'wine_name' },
    { title: '剩余', dataIndex: 'quantity', key: 'qty', align: 'right' },
    {
      title: '到期日',
      dataIndex: 'expires_at',
      key: 'exp',
      render: (v: string) => dayjs(v).format('MM-DD'),
    },
    {
      title: '剩余天数',
      dataIndex: 'days_remaining',
      key: 'days',
      align: 'right',
      render: (d: number) => (
        <Tag color={d <= 7 ? 'red' : 'orange'}>{d} 天</Tag>
      ),
    },
  ];

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={16}>
      {/* 筛选 */}
      <Card size="small" styles={{ body: { padding: '12px 16px' } }}>
        <Space wrap>
          <Select
            placeholder="选择门店"
            options={stores}
            value={storeId}
            onChange={setStoreId}
            style={{ width: 220 }}
          />
          <Button
            type="primary"
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
            disabled={!storeId}
            onClick={() => storeId && void load(storeId)}
          >
            刷新数据
          </Button>
        </Space>
      </Card>

      {/* 汇总卡片 */}
      <Spin spinning={summaryLoading}>
        {summary ? (
          <Row gutter={12}>
            <Col span={8}>
              <Card size="small" style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 24, fontWeight: 700, color: '#FF6B35' }}>
                  {summary.total_count}
                </div>
                <Text style={{ fontSize: 12, color: '#5F5E5A' }}>存酒档案数</Text>
              </Card>
            </Col>
            <Col span={8}>
              <Card size="small" style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 24, fontWeight: 700, color: '#2C2C2A' }}>
                  {summary.total_quantity}
                </div>
                <Text style={{ fontSize: 12, color: '#5F5E5A' }}>总库存量</Text>
              </Card>
            </Col>
            <Col span={8}>
              <Card size="small" style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 18, fontWeight: 700, color: '#0F6E56' }}>
                  {summary.total_estimated_value_fen ? fmtMoney(summary.total_estimated_value_fen) : '—'}
                </div>
                <Text style={{ fontSize: 12, color: '#5F5E5A' }}>估值合计</Text>
              </Card>
            </Col>
          </Row>
        ) : storeId ? null : (
          <Empty description="请先选择门店" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </Spin>

      {/* 按品类汇总 */}
      {summary && (
        <Card
          size="small"
          title="按品类汇总"
          styles={{ body: { padding: '8px 0 4px' } }}
        >
          <Table
            columns={summaryColumns}
            dataSource={summary.by_category}
            rowKey="wine_category"
            pagination={false}
            size="small"
          />
        </Card>
      )}

      {/* 即将到期（30天内） */}
      <Card
        size="small"
        title={
          <Space>
            <span>即将到期存酒</span>
            {expiring.length > 0 && <Badge count={expiring.length} color="#BA7517" />}
            <Text style={{ fontSize: 12, color: '#5F5E5A', fontWeight: 400 }}>30天内</Text>
          </Space>
        }
        styles={{ body: { padding: '8px 0 4px' } }}
      >
        <Spin spinning={expiringLoading}>
          {expiring.length > 0 ? (
            <Table
              columns={expiringColumns}
              dataSource={expiring}
              rowKey="id"
              pagination={false}
              size="small"
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="30天内无到期存酒" />
          )}
        </Spin>
      </Card>

      {/* 存酒明细 */}
      <Card
        size="small"
        title="存酒明细"
        styles={{ body: { padding: '8px 0 4px' } }}
      >
        <Spin spinning={detailLoading}>
          {detail && detail.items.length > 0 ? (
            <Table
              columns={detailColumns}
              dataSource={detail.items}
              rowKey="id"
              pagination={{ pageSize: 20, showSizeChanger: false }}
              size="small"
              scroll={{ x: 700 }}
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={storeId ? '暂无存酒记录' : '请先选择门店'} />
          )}
        </Spin>
      </Card>
    </Space>
  );
}

// ═══════════════════════════════════════════════════════════
// TAB 2: 押金台账
// ═══════════════════════════════════════════════════════════

const STATUS_LABEL: Record<string, string> = {
  collected: '待使用',
  partially_applied: '部分抵扣',
  fully_applied: '已抵扣',
  refunded: '已退还',
  converted: '已转收入',
  written_off: '已核销',
};

const STATUS_COLOR: Record<string, string> = {
  collected: 'blue',
  partially_applied: 'orange',
  fully_applied: 'default',
  refunded: 'green',
  converted: 'purple',
  written_off: 'default',
};

function DepositLedgerTab() {
  const stores = useStores();
  const [storeId, setStoreId] = useState<string | undefined>(undefined);
  const [dateRange, setDateRange] = useState<[string, string]>([
    dayjs().startOf('month').format('YYYY-MM-DD'),
    dayjs().format('YYYY-MM-DD'),
  ]);

  const [ledgerLoading, setLedgerLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [agingLoading, setAgingLoading] = useState(false);

  const [ledger, setLedger] = useState<DepositLedgerItem | null>(null);
  const [records, setRecords] = useState<DepositRecord[]>([]);
  const [aging, setAging] = useState<DepositAgingItem | null>(null);

  const load = useCallback(async (sid: string, start: string, end: string) => {
    setLedgerLoading(true);
    setDetailLoading(true);
    setAgingLoading(true);

    const [ledRes, detRes, agRes] = await Promise.allSettled([
      getDepositLedger(sid, start, end),
      listDepositsByStore(sid, { size: 100 }),
      getDepositAging(sid),
    ]);

    if (ledRes.status === 'fulfilled') setLedger(ledRes.value);
    setLedgerLoading(false);

    if (detRes.status === 'fulfilled') setRecords(detRes.value.items);
    setDetailLoading(false);

    if (agRes.status === 'fulfilled') setAging(agRes.value);
    setAgingLoading(false);
  }, []);

  useEffect(() => {
    if (storeId) void load(storeId, dateRange[0], dateRange[1]);
  }, [storeId, dateRange, load]);

  const detailColumns: ColumnsType<DepositRecord> = [
    { title: '收取日期', dataIndex: 'collected_at', key: 'date', render: (v: string) => dayjs(v).format('MM-DD HH:mm'), width: 110 },
    {
      title: '金额',
      dataIndex: 'amount_fen',
      key: 'amt',
      align: 'right',
      render: (v: number) => <Text strong>{fmtMoney(v)}</Text>,
    },
    {
      title: '已退还',
      dataIndex: 'refunded_amount_fen',
      key: 'ref',
      align: 'right',
      render: (v: number) => (v > 0 ? <Text style={{ color: '#0F6E56' }}>{fmtMoney(v)}</Text> : '—'),
    },
    {
      title: '余额',
      dataIndex: 'remaining_fen',
      key: 'rem',
      align: 'right',
      render: (v: number) => <Text strong style={{ color: v > 0 ? '#FF6B35' : '#B4B2A9' }}>{fmtMoney(v)}</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s: string) => <Tag color={STATUS_COLOR[s] ?? 'default'}>{STATUS_LABEL[s] ?? s}</Tag>,
    },
    { title: '支付方式', dataIndex: 'payment_method', key: 'pay', width: 90 },
  ];

  // 账龄分析展示
  const agingRows = aging
    ? [
        { label: '0-7 天', ...aging.aging['0_7_days'] },
        { label: '8-30 天', ...aging.aging['8_30_days'] },
        { label: '31-90 天', ...aging.aging['31_90_days'] },
        { label: '90 天以上', ...aging.aging['over_90_days'] },
      ]
    : [];

  const agingColumns: ColumnsType<{ label: string; count: number; amount_fen: number }> = [
    { title: '账龄区间', dataIndex: 'label', key: 'label' },
    { title: '笔数', dataIndex: 'count', key: 'count', align: 'right' },
    {
      title: '金额',
      dataIndex: 'amount_fen',
      key: 'amt',
      align: 'right',
      render: (v: number) => <Text strong>{fmtMoney(v)}</Text>,
    },
  ];

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={16}>
      {/* 筛选 */}
      <Card size="small" styles={{ body: { padding: '12px 16px' } }}>
        <Space wrap>
          <Select
            placeholder="选择门店"
            options={stores}
            value={storeId}
            onChange={setStoreId}
            style={{ width: 200 }}
          />
          <RangePicker
            defaultValue={[dayjs().startOf('month'), dayjs()]}
            onChange={(_, ds) => {
              if (ds[0] && ds[1]) setDateRange([ds[0], ds[1]]);
            }}
            picker="date"
          />
          <Button
            type="primary"
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
            disabled={!storeId}
            onClick={() => storeId && void load(storeId, dateRange[0], dateRange[1])}
          >
            查询
          </Button>
        </Space>
      </Card>

      {/* 汇总卡片 */}
      <Spin spinning={ledgerLoading}>
        {ledger ? (
          <Row gutter={12}>
            <Col span={8}>
              <Card size="small" style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 18, fontWeight: 700, color: '#FF6B35' }}>
                  {fmtMoney(ledger.total_collected_fen)}
                </div>
                <Text style={{ fontSize: 12, color: '#5F5E5A' }}>收取总额</Text>
              </Card>
            </Col>
            <Col span={8}>
              <Card size="small" style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 18, fontWeight: 700, color: '#0F6E56' }}>
                  {fmtMoney(ledger.total_refunded_fen)}
                </div>
                <Text style={{ fontSize: 12, color: '#5F5E5A' }}>退还总额</Text>
              </Card>
            </Col>
            <Col span={8}>
              <Card size="small" style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 18, fontWeight: 700, color: '#2C2C2A' }}>
                  {fmtMoney(ledger.total_outstanding_fen)}
                </div>
                <Text style={{ fontSize: 12, color: '#5F5E5A' }}>净押金余额</Text>
              </Card>
            </Col>
          </Row>
        ) : storeId ? null : (
          <Empty description="请先选择门店" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </Spin>

      {/* 明细表 */}
      <Card
        size="small"
        title="押金明细"
        styles={{ body: { padding: '8px 0 4px' } }}
      >
        <Spin spinning={detailLoading}>
          {records.length > 0 ? (
            <Table
              columns={detailColumns}
              dataSource={records}
              rowKey="id"
              pagination={{ pageSize: 20, showSizeChanger: false }}
              size="small"
              scroll={{ x: 600 }}
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={storeId ? '暂无押金记录' : '请先选择门店'} />
          )}
        </Spin>
      </Card>

      {/* 账龄分析 */}
      <Card
        size="small"
        title="账龄分析"
        styles={{ body: { padding: '8px 0 4px' } }}
      >
        <Spin spinning={agingLoading}>
          {aging ? (
            <Table
              columns={agingColumns}
              dataSource={agingRows}
              rowKey="label"
              pagination={false}
              size="small"
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={storeId ? '暂无账龄数据' : '请先选择门店'} />
          )}
        </Spin>
      </Card>
    </Space>
  );
}

// ═══════════════════════════════════════════════════════════
// TAB 3: 企业欠款报表
// ═══════════════════════════════════════════════════════════

function EnterpriseDebtTab() {
  const thisMonth = dayjs().format('YYYY-MM');

  const [enterprisesLoading, setEnterprisesLoading] = useState(false);
  const [statementsLoading, setStatementsLoading] = useState(false);

  const [enterprises, setEnterprises] = useState<EnterpriseAccount[]>([]);
  const [bills, setBills] = useState<EnterpriseBill[]>([]);
  const [signs, setSigns] = useState<EnterpriseSignRecord[]>([]);

  const load = useCallback(async () => {
    setEnterprisesLoading(true);

    const entRes = await listEnterprises({ size: 100 }).catch(() => ({ items: [] as EnterpriseAccount[], total: 0 }));
    const entList = entRes.items ?? [];
    setEnterprises(entList);
    setEnterprisesLoading(false);

    if (entList.length === 0) return;

    // 加载每个企业当月对账单，聚合签单记录
    setStatementsLoading(true);
    const statResults = await Promise.allSettled(
      entList.map((e) => getAuditTrail(e.id, thisMonth)),
    );

    const allSigns: EnterpriseSignRecord[] = [];
    const allBills: EnterpriseBill[] = [];

    statResults.forEach((res, idx) => {
      if (res.status === 'fulfilled') {
        const stmt = res.value;
        allSigns.push(...(stmt.sign_records ?? []).map((s) => ({
          ...s,
          enterprise_name: stmt.enterprise_name ?? entList[idx]?.name,
        })));
        if (stmt.bill) allBills.push({ ...stmt.bill, enterprise_name: stmt.enterprise_name });
      }
    });

    setSigns(allSigns);
    setBills(allBills);
    setStatementsLoading(false);
  }, [thisMonth]);

  useEffect(() => { void load(); }, [load]);

  // 企业列表列
  const enterpriseColumns: ColumnsType<EnterpriseAccount> = [
    { title: '企业名称', dataIndex: 'name', key: 'name', ellipsis: true },
    {
      title: '信用额度',
      dataIndex: 'credit_limit_fen',
      key: 'limit',
      align: 'right',
      render: (v: number) => fmtMoney(v),
    },
    {
      title: '已用额度',
      dataIndex: 'used_credit_fen',
      key: 'used',
      align: 'right',
      render: (v: number, r) => {
        const pct = r.credit_limit_fen > 0 ? v / r.credit_limit_fen : 0;
        return (
          <span style={{ color: pct >= 0.9 ? '#A32D2D' : pct >= 0.7 ? '#BA7517' : '#2C2C2A', fontWeight: 600 }}>
            {fmtMoney(v)}
          </span>
        );
      },
    },
    {
      title: '欠款金额',
      key: 'debt',
      align: 'right',
      render: (_, r) => {
        const debt = r.used_credit_fen;
        return <Text strong style={{ color: debt > 0 ? '#A32D2D' : '#0F6E56' }}>{fmtMoney(debt)}</Text>;
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s: string) => (
        <Tag color={s === 'active' ? 'green' : 'red'}>
          {s === 'active' ? '正常' : '已停用'}
        </Tag>
      ),
    },
    {
      title: '结算周期',
      dataIndex: 'billing_cycle',
      key: 'cycle',
      render: (s: string) => {
        const m: Record<string, string> = { monthly: '月结', bi_monthly: '双月结', quarterly: '季结' };
        return m[s] ?? s;
      },
    },
  ];

  // 账龄分析（基于 bills 模拟）
  const now = dayjs();
  const agingBuckets = {
    '0-30天': bills.filter((b) => b.status !== 'settled' && now.diff(dayjs(b.created_at), 'day') <= 30),
    '31-90天': bills.filter((b) => b.status !== 'settled' && now.diff(dayjs(b.created_at), 'day') > 30 && now.diff(dayjs(b.created_at), 'day') <= 90),
    '90天以上': bills.filter((b) => b.status !== 'settled' && now.diff(dayjs(b.created_at), 'day') > 90),
  };

  const agingRows = Object.entries(agingBuckets).map(([label, items]) => ({
    label,
    count: items.length,
    amount_fen: items.reduce((s, b) => s + (b.total_fen - b.paid_fen), 0),
  }));

  const agingColumns: ColumnsType<{ label: string; count: number; amount_fen: number }> = [
    { title: '账龄区间', dataIndex: 'label', key: 'label' },
    { title: '账单数', dataIndex: 'count', key: 'count', align: 'right' },
    {
      title: '欠款金额',
      dataIndex: 'amount_fen',
      key: 'amt',
      align: 'right',
      render: (v: number) => (
        <Text strong style={{ color: v > 0 ? '#A32D2D' : '#B4B2A9' }}>{fmtMoney(v)}</Text>
      ),
    },
  ];

  // 月度还款汇总（按月 group bills）
  const monthlyMap = new Map<string, { month: string; total_fen: number; paid_fen: number; bill_count: number }>();
  bills.forEach((b) => {
    const m = b.month ?? dayjs(b.created_at).format('YYYY-MM');
    const cur = monthlyMap.get(m) ?? { month: m, total_fen: 0, paid_fen: 0, bill_count: 0 };
    cur.total_fen += b.total_fen;
    cur.paid_fen += b.paid_fen;
    cur.bill_count += 1;
    monthlyMap.set(m, cur);
  });
  const monthlyRows = Array.from(monthlyMap.values()).sort((a, b) => b.month.localeCompare(a.month));

  const monthlyColumns: ColumnsType<(typeof monthlyRows)[0]> = [
    { title: '月份', dataIndex: 'month', key: 'month' },
    {
      title: '账单总额',
      dataIndex: 'total_fen',
      key: 'total',
      align: 'right',
      render: (v: number) => fmtMoney(v),
    },
    {
      title: '已还款',
      dataIndex: 'paid_fen',
      key: 'paid',
      align: 'right',
      render: (v: number) => <Text style={{ color: '#0F6E56' }}>{fmtMoney(v)}</Text>,
    },
    {
      title: '未还款',
      key: 'unpaid',
      align: 'right',
      render: (_: unknown, r) => {
        const unpaid = r.total_fen - r.paid_fen;
        return (
          <Text strong style={{ color: unpaid > 0 ? '#A32D2D' : '#B4B2A9' }}>
            {fmtMoney(unpaid)}
          </Text>
        );
      },
    },
    { title: '账单数', dataIndex: 'bill_count', key: 'cnt', align: 'right' },
  ];

  // 签单明细（最近）
  const signColumns: ColumnsType<EnterpriseSignRecord> = [
    { title: '企业', dataIndex: 'enterprise_name', key: 'ent', ellipsis: true },
    { title: '签单人', dataIndex: 'signer_name', key: 'signer' },
    { title: '桌台', dataIndex: 'table_no', key: 'table', width: 70 },
    {
      title: '金额',
      dataIndex: 'amount_fen',
      key: 'amt',
      align: 'right',
      render: (v: number) => <Text strong>{fmtMoney(v)}</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s: string) => (
        <Tag color={s === 'paid' ? 'green' : 'red'}>{s === 'paid' ? '已还款' : '未还款'}</Tag>
      ),
    },
    { title: '日期', dataIndex: 'biz_date', key: 'date', width: 100 },
  ];

  // 汇总 KPI
  const totalDebt = enterprises.reduce((s, e) => s + e.used_credit_fen, 0);
  const totalLimit = enterprises.reduce((s, e) => s + e.credit_limit_fen, 0);
  const overLimitCount = enterprises.filter((e) => e.used_credit_fen / e.credit_limit_fen >= 0.9).length;

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={16}>
      {/* 顶部操作 */}
      <Card size="small" styles={{ body: { padding: '12px 16px' } }}>
        <Button
          type="primary"
          style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
          onClick={load}
        >
          刷新数据
        </Button>
      </Card>

      {/* KPI 行 */}
      <Spin spinning={enterprisesLoading}>
        <Row gutter={12}>
          <Col span={8}>
            <Card size="small" style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#A32D2D' }}>
                {fmtMoney(totalDebt)}
              </div>
              <Text style={{ fontSize: 12, color: '#5F5E5A' }}>欠款总额</Text>
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small" style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#2C2C2A' }}>
                {fmtMoney(totalLimit)}
              </div>
              <Text style={{ fontSize: 12, color: '#5F5E5A' }}>授信总额</Text>
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small" style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: overLimitCount > 0 ? '#A32D2D' : '#0F6E56' }}>
                {overLimitCount}
              </div>
              <Text style={{ fontSize: 12, color: '#5F5E5A' }}>临近额度企业</Text>
            </Card>
          </Col>
        </Row>
      </Spin>

      {/* 企业欠款列表 */}
      <Card
        size="small"
        title="企业欠款列表"
        styles={{ body: { padding: '8px 0 4px' } }}
      >
        <Spin spinning={enterprisesLoading}>
          {enterprises.length > 0 ? (
            <Table
              columns={enterpriseColumns}
              dataSource={enterprises}
              rowKey="id"
              pagination={{ pageSize: 20, showSizeChanger: false }}
              size="small"
              scroll={{ x: 700 }}
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无企业账户" />
          )}
        </Spin>
      </Card>

      {/* 欠款账龄分析 */}
      <Card
        size="small"
        title="欠款账龄分析"
        styles={{ body: { padding: '8px 0 4px' } }}
      >
        <Spin spinning={statementsLoading}>
          <Table
            columns={agingColumns}
            dataSource={agingRows}
            rowKey="label"
            pagination={false}
            size="small"
          />
        </Spin>
      </Card>

      {/* 月度还款汇总 */}
      <Card
        size="small"
        title="月度还款汇总"
        styles={{ body: { padding: '8px 0 4px' } }}
      >
        <Spin spinning={statementsLoading}>
          {monthlyRows.length > 0 ? (
            <Table
              columns={monthlyColumns}
              dataSource={monthlyRows}
              rowKey="month"
              pagination={{ pageSize: 12, showSizeChanger: false }}
              size="small"
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无账单数据" />
          )}
        </Spin>
      </Card>

      {/* 签单明细 */}
      <Card
        size="small"
        title="签单明细（近期）"
        styles={{ body: { padding: '8px 0 4px' } }}
      >
        <Spin spinning={statementsLoading}>
          {signs.length > 0 ? (
            <Table
              columns={signColumns}
              dataSource={signs}
              rowKey="id"
              pagination={{ pageSize: 20, showSizeChanger: false }}
              size="small"
              scroll={{ x: 600 }}
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无签单记录" />
          )}
        </Spin>
      </Card>
    </Space>
  );
}

// ═══════════════════════════════════════════════════════════
// 主页面
// ═══════════════════════════════════════════════════════════

export function WineDepositReportPage() {
  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <Title level={2} style={{ margin: 0, color: '#2C2C2A' }}>
          专项报表
        </Title>
        <Text style={{ color: '#5F5E5A', fontSize: 14 }}>
          存酒台账 · 押金台账 · 企业挂账欠款
        </Text>
      </div>

      <Tabs
        type="card"
        size="middle"
        items={[
          {
            key: 'wine',
            label: '存酒汇总报表',
            children: <WineSummaryTab />,
          },
          {
            key: 'deposit',
            label: '押金台账',
            children: <DepositLedgerTab />,
          },
          {
            key: 'enterprise',
            label: '企业欠款报表',
            children: <EnterpriseDebtTab />,
          },
        ]}
      />
    </div>
  );
}
