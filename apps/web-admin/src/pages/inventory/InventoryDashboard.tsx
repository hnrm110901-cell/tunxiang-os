/**
 * InventoryDashboard — R365-inspired 库存-会计联动看板
 *
 * 核心模式：库存变动自动生成会计分录（Journal Entry）
 * 进货 → 借:原材料  贷:应付账款
 * 盘亏 → 借:管理费用-盘亏  贷:原材料
 * 报损 → 借:营业外支出-报损  贷:原材料
 *
 * Admin 终端，使用 Ant Design 5.x 组件。品牌色 #FF6B35。
 */
import { useState, useMemo } from 'react';
import {
  Table, Card, Tag, Statistic, Row, Col, Badge, Timeline,
  ConfigProvider, Typography, Space, Select, Input, Tooltip,
  Progress,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { Search } = Input;

// ─── Brand Theme ──────────────────────────────────────────────
const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_WARNING = '#BA7517';
const TX_DANGER = '#A32D2D';
const TX_INFO = '#185FA5';
const TX_NAVY = '#1E2A3A';
const TX_BG = '#F8F7F5';
const TX_BG_TERTIARY = '#F0EDE6';
const TX_TEXT_SECONDARY = '#5F5E5A';
const TX_TEXT_TERTIARY = '#B4B2A9';
const TX_BORDER = '#E8E6E1';

// ─── Types ────────────────────────────────────────────────────
interface InventoryItem {
  id: string;
  name: string;
  category: string;
  currentStock: number;
  safetyLine: number;
  unit: string;
  unitPrice: number;       // 采购价（元）
  supplier: string;
  expiryDate: string;      // ISO date
  status: 'sufficient' | 'low' | 'expired';
}

interface JournalEntry {
  id: string;
  timestamp: string;
  movementType: 'purchase' | 'stocktake_loss' | 'spoilage' | 'transfer';
  ingredientName: string;
  amount: number;
  debitAccount: string;
  creditAccount: string;
  memo: string;
}

interface StockMovement {
  id: string;
  timestamp: string;
  type: 'purchase' | 'stocktake' | 'spoilage' | 'transfer';
  ingredientName: string;
  quantity: number;
  unit: string;
  operator: string;
  note: string;
}

// ─── Mock Data ────────────────────────────────────────────────
const MOCK_INVENTORY: InventoryItem[] = [
  { id: 'I001', name: '五花肉', category: '肉类', currentStock: 45, safetyLine: 20, unit: 'kg', unitPrice: 28.5, supplier: '湘菜鲜配', expiryDate: '2026-04-05', status: 'sufficient' },
  { id: 'I002', name: '鱼头', category: '水产', currentStock: 8, safetyLine: 15, unit: 'kg', unitPrice: 35.0, supplier: '农鲜达', expiryDate: '2026-03-29', status: 'low' },
  { id: 'I003', name: '黄牛肉', category: '肉类', currentStock: 32, safetyLine: 10, unit: 'kg', unitPrice: 68.0, supplier: '湘菜鲜配', expiryDate: '2026-04-02', status: 'sufficient' },
  { id: 'I004', name: '西兰花', category: '蔬菜', currentStock: 12, safetyLine: 8, unit: 'kg', unitPrice: 8.5, supplier: '绿源蔬菜', expiryDate: '2026-03-30', status: 'sufficient' },
  { id: 'I005', name: '土鸡', category: '禽类', currentStock: 6, safetyLine: 10, unit: '只', unitPrice: 45.0, supplier: '乡里土鸡', expiryDate: '2026-03-29', status: 'low' },
  { id: 'I006', name: '辣椒', category: '调料', currentStock: 18, safetyLine: 5, unit: 'kg', unitPrice: 12.0, supplier: '绿源蔬菜', expiryDate: '2026-04-10', status: 'sufficient' },
  { id: 'I007', name: '土豆', category: '蔬菜', currentStock: 25, safetyLine: 15, unit: 'kg', unitPrice: 4.5, supplier: '绿源蔬菜', expiryDate: '2026-04-08', status: 'sufficient' },
  { id: 'I008', name: '黄瓜', category: '蔬菜', currentStock: 3, safetyLine: 10, unit: 'kg', unitPrice: 6.0, supplier: '绿源蔬菜', expiryDate: '2026-03-28', status: 'expired' },
  { id: 'I009', name: '米', category: '主食', currentStock: 120, safetyLine: 50, unit: 'kg', unitPrice: 5.2, supplier: '粮油之家', expiryDate: '2026-08-15', status: 'sufficient' },
  { id: 'I010', name: '食用油', category: '调料', currentStock: 40, safetyLine: 20, unit: 'L', unitPrice: 15.8, supplier: '粮油之家', expiryDate: '2026-12-01', status: 'sufficient' },
  { id: 'I011', name: '生姜', category: '调料', currentStock: 5, safetyLine: 8, unit: 'kg', unitPrice: 18.0, supplier: '绿源蔬菜', expiryDate: '2026-04-05', status: 'low' },
  { id: 'I012', name: '大蒜', category: '调料', currentStock: 7, safetyLine: 6, unit: 'kg', unitPrice: 14.0, supplier: '绿源蔬菜', expiryDate: '2026-04-12', status: 'sufficient' },
];

const MOCK_JOURNAL_ENTRIES: JournalEntry[] = [
  {
    id: 'J001', timestamp: '2026-03-28 09:15', movementType: 'purchase', ingredientName: '五花肉',
    amount: 2850, debitAccount: '原材料-五花肉', creditAccount: '应付账款-湘菜鲜配',
    memo: '进货100kg × ¥28.50',
  },
  {
    id: 'J002', timestamp: '2026-03-28 08:30', movementType: 'spoilage', ingredientName: '黄瓜',
    amount: 36, debitAccount: '营业外支出-报损', creditAccount: '原材料-黄瓜',
    memo: '临期报废6kg × ¥6.00',
  },
  {
    id: 'J003', timestamp: '2026-03-27 22:00', movementType: 'stocktake_loss', ingredientName: '辣椒',
    amount: 24, debitAccount: '管理费用-盘亏', creditAccount: '原材料-辣椒',
    memo: '盘亏2kg × ¥12.00',
  },
  {
    id: 'J004', timestamp: '2026-03-27 14:20', movementType: 'purchase', ingredientName: '黄牛肉',
    amount: 3400, debitAccount: '原材料-黄牛肉', creditAccount: '应付账款-湘菜鲜配',
    memo: '进货50kg × ¥68.00',
  },
  {
    id: 'J005', timestamp: '2026-03-27 10:00', movementType: 'transfer', ingredientName: '米',
    amount: 260, debitAccount: '原材料-米(岳麓店)', creditAccount: '原材料-米(芙蓉路店)',
    memo: '调拨至岳麓店 50kg × ¥5.20',
  },
  {
    id: 'J006', timestamp: '2026-03-26 21:30', movementType: 'spoilage', ingredientName: '鱼头',
    amount: 105, debitAccount: '营业外支出-报损', creditAccount: '原材料-鱼头',
    memo: '过期报废3kg × ¥35.00',
  },
  {
    id: 'J007', timestamp: '2026-03-26 09:00', movementType: 'purchase', ingredientName: '土鸡',
    amount: 900, debitAccount: '原材料-土鸡', creditAccount: '应付账款-乡里土鸡',
    memo: '进货20只 × ¥45.00',
  },
];

const MOCK_MOVEMENTS: StockMovement[] = [
  { id: 'M001', timestamp: '2026-03-28 09:15', type: 'purchase', ingredientName: '五花肉', quantity: 100, unit: 'kg', operator: '张经理', note: '日常补货' },
  { id: 'M002', timestamp: '2026-03-28 08:30', type: 'spoilage', ingredientName: '黄瓜', quantity: -6, unit: 'kg', operator: '李仓管', note: '临期报废，已过效期' },
  { id: 'M003', timestamp: '2026-03-27 22:00', type: 'stocktake', ingredientName: '辣椒', quantity: -2, unit: 'kg', operator: '李仓管', note: '月末盘点，实际少2kg' },
  { id: 'M004', timestamp: '2026-03-27 14:20', type: 'purchase', ingredientName: '黄牛肉', quantity: 50, unit: 'kg', operator: '张经理', note: '周末备货' },
  { id: 'M005', timestamp: '2026-03-27 10:00', type: 'transfer', ingredientName: '米', quantity: -50, unit: 'kg', operator: '张经理', note: '调拨至岳麓店' },
  { id: 'M006', timestamp: '2026-03-26 21:30', type: 'spoilage', ingredientName: '鱼头', quantity: -3, unit: 'kg', operator: '李仓管', note: '过期报废' },
  { id: 'M007', timestamp: '2026-03-26 09:00', type: 'purchase', ingredientName: '土鸡', quantity: 20, unit: '只', operator: '张经理', note: '日常补货' },
  { id: 'M008', timestamp: '2026-03-25 16:00', type: 'stocktake', ingredientName: '食用油', quantity: -2, unit: 'L', operator: '李仓管', note: '盘点差异' },
];

// ─── Helpers ──────────────────────────────────────────────────
const formatCurrency = (yuan: number) => `¥${yuan.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`;

const statusConfig: Record<InventoryItem['status'], { color: string; label: string }> = {
  sufficient: { color: TX_SUCCESS, label: '充足' },
  low: { color: TX_WARNING, label: '低于安全线' },
  expired: { color: TX_DANGER, label: '已过期' },
};

const movementTypeConfig: Record<JournalEntry['movementType'], { color: string; label: string }> = {
  purchase: { color: TX_INFO, label: '进货' },
  stocktake_loss: { color: TX_WARNING, label: '盘亏' },
  spoilage: { color: TX_DANGER, label: '报损' },
  transfer: { color: TX_TEXT_SECONDARY, label: '调拨' },
};

const stockMovementTypeConfig: Record<StockMovement['type'], { color: string; label: string }> = {
  purchase: { color: TX_SUCCESS, label: '进货' },
  stocktake: { color: TX_WARNING, label: '盘点' },
  spoilage: { color: TX_DANGER, label: '报损' },
  transfer: { color: TX_INFO, label: '调拨' },
};

// ─── Component ────────────────────────────────────────────────
export function InventoryDashboard() {
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [searchText, setSearchText] = useState('');

  // Computed stats
  const totalInventoryValue = useMemo(
    () => MOCK_INVENTORY.reduce((sum, item) => sum + item.currentStock * item.unitPrice, 0),
    [],
  );
  const monthlyPurchase = 28650;   // Mock: 本月进货额
  const monthlyLoss = 425;         // Mock: 本月损耗
  const foodCostRate = 31.2;       // Mock: 食材成本率 %

  const categories = useMemo(() => {
    const cats = [...new Set(MOCK_INVENTORY.map(i => i.category))];
    return [{ value: 'all', label: '全部分类' }, ...cats.map(c => ({ value: c, label: c }))];
  }, []);

  const filteredInventory = useMemo(() => {
    return MOCK_INVENTORY.filter(item => {
      const matchCategory = categoryFilter === 'all' || item.category === categoryFilter;
      const matchSearch = !searchText || item.name.includes(searchText) || item.supplier.includes(searchText);
      return matchCategory && matchSearch;
    });
  }, [categoryFilter, searchText]);

  // ─── Table Columns ───────────────────────────────────────
  const inventoryColumns: ColumnsType<InventoryItem> = [
    {
      title: '食材名称',
      dataIndex: 'name',
      key: 'name',
      width: 100,
      render: (name: string, record: InventoryItem) => (
        <Space>
          <Text strong>{name}</Text>
          {record.status === 'expired' && <Badge status="error" />}
        </Space>
      ),
    },
    {
      title: '分类',
      dataIndex: 'category',
      key: 'category',
      width: 72,
      render: (cat: string) => <Tag>{cat}</Tag>,
    },
    {
      title: '当前库存',
      dataIndex: 'currentStock',
      key: 'currentStock',
      width: 100,
      sorter: (a, b) => a.currentStock - b.currentStock,
      render: (stock: number, record: InventoryItem) => {
        const ratio = stock / record.safetyLine;
        const color = ratio > 1.5 ? TX_SUCCESS : ratio >= 1 ? TX_WARNING : TX_DANGER;
        return (
          <Tooltip title={`安全线: ${record.safetyLine}${record.unit}`}>
            <div>
              <Text style={{ color, fontWeight: 600 }}>{stock}</Text>
              <Text type="secondary" style={{ fontSize: 12 }}> {record.unit}</Text>
              <Progress
                percent={Math.min((stock / (record.safetyLine * 2)) * 100, 100)}
                size="small"
                showInfo={false}
                strokeColor={color}
                trailColor={TX_BG_TERTIARY}
                style={{ marginTop: 2 }}
              />
            </div>
          </Tooltip>
        );
      },
    },
    {
      title: '安全线',
      dataIndex: 'safetyLine',
      key: 'safetyLine',
      width: 72,
      render: (val: number, record: InventoryItem) => (
        <Text type="secondary">{val} {record.unit}</Text>
      ),
    },
    {
      title: '采购价',
      dataIndex: 'unitPrice',
      key: 'unitPrice',
      width: 80,
      sorter: (a, b) => a.unitPrice - b.unitPrice,
      render: (price: number, record: InventoryItem) => (
        <Text>{formatCurrency(price)}/{record.unit}</Text>
      ),
    },
    {
      title: '供应商',
      dataIndex: 'supplier',
      key: 'supplier',
      width: 100,
      render: (s: string) => <Text type="secondary">{s}</Text>,
    },
    {
      title: '效期',
      dataIndex: 'expiryDate',
      key: 'expiryDate',
      width: 100,
      sorter: (a, b) => a.expiryDate.localeCompare(b.expiryDate),
      render: (date: string) => {
        const daysLeft = dayjs(date).diff(dayjs(), 'day');
        const color = daysLeft <= 0 ? TX_DANGER : daysLeft <= 3 ? TX_WARNING : TX_TEXT_SECONDARY;
        const label = daysLeft <= 0 ? '已过期' : daysLeft <= 3 ? `剩${daysLeft}天` : date;
        return <Text style={{ color }}>{label}</Text>;
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 96,
      filters: [
        { text: '充足', value: 'sufficient' },
        { text: '低于安全线', value: 'low' },
        { text: '已过期', value: 'expired' },
      ],
      onFilter: (value, record) => record.status === value,
      render: (status: InventoryItem['status']) => {
        const cfg = statusConfig[status];
        return <Tag color={cfg.color} style={{ borderRadius: 4 }}>{cfg.label}</Tag>;
      },
    },
  ];

  // ─── Movement Table Columns ──────────────────────────────
  const movementColumns: ColumnsType<StockMovement> = [
    {
      title: '时间',
      dataIndex: 'timestamp',
      key: 'timestamp',
      width: 140,
      render: (ts: string) => <Text type="secondary" style={{ fontSize: 13 }}>{ts}</Text>,
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 72,
      render: (type: StockMovement['type']) => {
        const cfg = stockMovementTypeConfig[type];
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '食材',
      dataIndex: 'ingredientName',
      key: 'ingredientName',
      width: 80,
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: '数量',
      dataIndex: 'quantity',
      key: 'quantity',
      width: 90,
      render: (qty: number, record: StockMovement) => {
        const color = qty > 0 ? TX_SUCCESS : TX_DANGER;
        const prefix = qty > 0 ? '+' : '';
        return <Text style={{ color, fontWeight: 600 }}>{prefix}{qty} {record.unit}</Text>;
      },
    },
    {
      title: '操作人',
      dataIndex: 'operator',
      key: 'operator',
      width: 80,
    },
    {
      title: '备注',
      dataIndex: 'note',
      key: 'note',
      ellipsis: true,
      render: (note: string) => <Text type="secondary">{note}</Text>,
    },
  ];

  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: TX_PRIMARY,
          borderRadius: 6,
          fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
        },
      }}
    >
      <div style={{ padding: '24px 32px', backgroundColor: TX_BG, minHeight: '100vh' }}>
        {/* Page Header */}
        <div style={{ marginBottom: 24 }}>
          <Title level={3} style={{ margin: 0, color: TX_NAVY }}>
            库存-会计联动看板
          </Title>
          <Text type="secondary">
            R365 模式：库存变动自动生成会计分录，实时追踪食材成本
          </Text>
        </div>

        {/* ─── Top Stats Row ─────────────────────────────────── */}
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col span={6}>
            <Card
              bordered={false}
              style={{ borderTop: `3px solid ${TX_PRIMARY}` }}
              styles={{ body: { padding: '20px 24px' } }}
            >
              <Statistic
                title={<Text type="secondary">库存总值</Text>}
                value={totalInventoryValue}
                precision={2}
                prefix="¥"
                valueStyle={{ color: TX_NAVY, fontWeight: 700 }}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                {MOCK_INVENTORY.length} 种食材在库
              </Text>
            </Card>
          </Col>
          <Col span={6}>
            <Card
              bordered={false}
              style={{ borderTop: `3px solid ${TX_INFO}` }}
              styles={{ body: { padding: '20px 24px' } }}
            >
              <Statistic
                title={<Text type="secondary">本月进货额</Text>}
                value={monthlyPurchase}
                precision={2}
                prefix="¥"
                valueStyle={{ color: TX_INFO, fontWeight: 700 }}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                较上月 <Text style={{ color: TX_SUCCESS }}>-8.3%</Text>
              </Text>
            </Card>
          </Col>
          <Col span={6}>
            <Card
              bordered={false}
              style={{ borderTop: `3px solid ${TX_DANGER}` }}
              styles={{ body: { padding: '20px 24px' } }}
            >
              <Statistic
                title={<Text type="secondary">本月损耗</Text>}
                value={monthlyLoss}
                precision={2}
                prefix="¥"
                valueStyle={{ color: TX_DANGER, fontWeight: 700 }}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                损耗率 <Text style={{ color: TX_WARNING }}>1.5%</Text>
              </Text>
            </Card>
          </Col>
          <Col span={6}>
            <Card
              bordered={false}
              style={{ borderTop: `3px solid ${TX_SUCCESS}` }}
              styles={{ body: { padding: '20px 24px' } }}
            >
              <Statistic
                title={<Text type="secondary">食材成本率</Text>}
                value={foodCostRate}
                suffix="%"
                precision={1}
                valueStyle={{ color: TX_SUCCESS, fontWeight: 700 }}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                目标 ≤ 33% <Text style={{ color: TX_SUCCESS }}>达标</Text>
              </Text>
            </Card>
          </Col>
        </Row>

        {/* ─── Two Column: Inventory + Journal ────────────────── */}
        <Row gutter={16} style={{ marginBottom: 24 }}>
          {/* Left 60%: Inventory Table */}
          <Col span={14}>
            <Card
              title={
                <Space>
                  <Text strong style={{ fontSize: 16, color: TX_NAVY }}>食材库存明细</Text>
                  <Badge
                    count={MOCK_INVENTORY.filter(i => i.status === 'low').length}
                    style={{ backgroundColor: TX_WARNING }}
                    title="低库存食材数"
                  />
                  <Badge
                    count={MOCK_INVENTORY.filter(i => i.status === 'expired').length}
                    style={{ backgroundColor: TX_DANGER }}
                    title="已过期食材数"
                  />
                </Space>
              }
              extra={
                <Space>
                  <Search
                    placeholder="搜索食材/供应商"
                    allowClear
                    size="small"
                    style={{ width: 160 }}
                    onSearch={setSearchText}
                    onChange={e => !e.target.value && setSearchText('')}
                  />
                  <Select
                    value={categoryFilter}
                    onChange={setCategoryFilter}
                    options={categories}
                    size="small"
                    style={{ width: 110 }}
                  />
                </Space>
              }
              bordered={false}
              styles={{ body: { padding: '0 0 8px' } }}
            >
              <Table<InventoryItem>
                dataSource={filteredInventory}
                columns={inventoryColumns}
                rowKey="id"
                size="small"
                pagination={false}
                scroll={{ y: 420 }}
                rowClassName={(record) =>
                  record.status === 'expired' ? 'inventory-row-expired' : ''
                }
              />
            </Card>
          </Col>

          {/* Right 40%: Auto-generated Journal Entries */}
          <Col span={10}>
            <Card
              title={
                <Space>
                  <Text strong style={{ fontSize: 16, color: TX_NAVY }}>自动会计分录</Text>
                  <Tag color={TX_PRIMARY} style={{ borderRadius: 4, fontSize: 11 }}>R365 联动</Tag>
                </Space>
              }
              bordered={false}
              styles={{ body: { padding: '12px 16px', maxHeight: 492, overflowY: 'auto' } }}
            >
              <Timeline
                items={MOCK_JOURNAL_ENTRIES.map((entry) => {
                  const cfg = movementTypeConfig[entry.movementType];
                  return {
                    key: entry.id,
                    color: cfg.color,
                    children: (
                      <div style={{ marginBottom: 8 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                          <Space size={4}>
                            <Tag
                              color={cfg.color}
                              style={{ borderRadius: 4, fontSize: 11, lineHeight: '18px', padding: '0 6px' }}
                            >
                              {cfg.label}
                            </Tag>
                            <Text strong style={{ fontSize: 13 }}>{entry.ingredientName}</Text>
                          </Space>
                          <Text type="secondary" style={{ fontSize: 11 }}>{entry.timestamp}</Text>
                        </div>
                        {/* Journal entry detail */}
                        <div
                          style={{
                            background: TX_BG_TERTIARY,
                            borderRadius: 4,
                            padding: '8px 10px',
                            fontSize: 12,
                            fontFamily: 'monospace',
                            lineHeight: '20px',
                          }}
                        >
                          <div style={{ color: TX_NAVY }}>
                            借: <Text style={{ color: cfg.color, fontSize: 12 }}>{entry.debitAccount}</Text>
                            <Text style={{ float: 'right', fontWeight: 600, fontSize: 12 }}>{formatCurrency(entry.amount)}</Text>
                          </div>
                          <div style={{ color: TX_NAVY }}>
                            贷: <Text type="secondary" style={{ fontSize: 12 }}>{entry.creditAccount}</Text>
                            <Text type="secondary" style={{ float: 'right', fontSize: 12 }}>{formatCurrency(entry.amount)}</Text>
                          </div>
                        </div>
                        <Text type="secondary" style={{ fontSize: 11 }}>{entry.memo}</Text>
                      </div>
                    ),
                  };
                })}
              />
            </Card>
          </Col>
        </Row>

        {/* ─── Bottom: Stock Movement Log ─────────────────────── */}
        <Card
          title={
            <Text strong style={{ fontSize: 16, color: TX_NAVY }}>库存流水记录</Text>
          }
          extra={
            <Space>
              <Tag color={TX_SUCCESS}>进货 {MOCK_MOVEMENTS.filter(m => m.type === 'purchase').length}</Tag>
              <Tag color={TX_WARNING}>盘点 {MOCK_MOVEMENTS.filter(m => m.type === 'stocktake').length}</Tag>
              <Tag color={TX_DANGER}>报损 {MOCK_MOVEMENTS.filter(m => m.type === 'spoilage').length}</Tag>
              <Tag color={TX_INFO}>调拨 {MOCK_MOVEMENTS.filter(m => m.type === 'transfer').length}</Tag>
            </Space>
          }
          bordered={false}
          styles={{ body: { padding: 0 } }}
        >
          <Table<StockMovement>
            dataSource={MOCK_MOVEMENTS}
            columns={movementColumns}
            rowKey="id"
            size="small"
            pagination={{ pageSize: 10, size: 'small', showTotal: (total) => `共 ${total} 条记录` }}
          />
        </Card>
      </div>

      {/* Scoped styles for row highlighting */}
      <style>{`
        .inventory-row-expired {
          background-color: #FFF1F0 !important;
        }
        .inventory-row-expired:hover > td {
          background-color: #FFE4E1 !important;
        }
      `}</style>
    </ConfigProvider>
  );
}

export default InventoryDashboard;
