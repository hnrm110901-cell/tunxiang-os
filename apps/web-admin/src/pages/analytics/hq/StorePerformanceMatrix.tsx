/**
 * StorePerformanceMatrix — HQ 门店绩效矩阵页
 *
 * 终端：Admin（总部管理后台）
 * 域G：经营分析 → HQ总部看板
 * 路由：/analytics/hq/stores
 *
 * 布局：
 *   1. 顶部：品牌Tab选择 + 日期选择 + 城市Select + 排序Select
 *   2. 门店绩效 ProTable（含毛利率 Tag 变色、达成率变色、趋势箭头、预警 Badge）
 *   3. 行点击：右侧 Drawer 展示该门店 P&L 概览
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  ConfigProvider,
  Tabs,
  Select,
  Drawer,
  Tag,
  Badge,
  Space,
  Descriptions,
  Skeleton,
  message,
  Typography,
  Row,
  Col,
  Statistic,
  Divider,
  Tooltip,
} from 'antd';
import {
  ArrowUpOutlined,
  ArrowDownOutlined,
  MinusOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns, RequestData } from '@ant-design/pro-components';

import { fenToYuan, pctDisplay } from '../../../utils/format';
import {
  getBrandStorePerformance,
  getBrandsOverview,
  getStorePnlOverview,
  type StorePerformanceItem,
  type StorePnlOverview,
  type StorePerformanceParams,
  type HQDateParams,
} from '../../../api/hqAnalyticsApi';

const { Title, Text } = Typography;
const { Option } = Select;

// ─── 主题 Token ───────────────────────────────────────────────────────────────

const txAdminTheme = {
  token: {
    colorPrimary: '#FF6B35',
    colorSuccess: '#0F6E56',
    colorWarning: '#BA7517',
    colorError: '#A32D2D',
    colorInfo: '#185FA5',
    colorTextBase: '#2C2C2A',
  },
  components: {
    Table: { headerBg: '#F8F7F5' },
  },
} as const;

// ─── 常量 ────────────────────────────────────────────────────────────────────

type PeriodKey = 'today' | 'week' | 'month';

const PERIOD_OPTIONS = [
  { label: '今日', value: 'today' },
  { label: '本周', value: 'week' },
  { label: '本月', value: 'month' },
];

const SORT_OPTIONS = [
  { label: '按营收排序', value: 'revenue' },
  { label: '按达成率排序', value: 'target_rate' },
  { label: '按毛利率排序', value: 'gross_margin' },
  { label: '按健康分排序', value: 'health_score' },
];

// ─── 工具函数 ────────────────────────────────────────────────────────────────

function marginTagColor(margin: number): 'red' | 'orange' | 'green' {
  if (margin < 0.4) return 'red';
  if (margin <= 0.55) return 'orange';
  return 'green';
}

function targetRateColor(rate: number): 'red' | 'orange' | 'green' {
  if (rate < 0.8) return 'red';
  if (rate < 1) return 'orange';
  return 'green';
}

function TrendIcon({ trend }: { trend: 'up' | 'down' | 'flat' }) {
  if (trend === 'up') return <ArrowUpOutlined style={{ color: '#0F6E56' }} />;
  if (trend === 'down') return <ArrowDownOutlined style={{ color: '#A32D2D' }} />;
  return <MinusOutlined style={{ color: '#BA7517' }} />;
}

// ─── 门店 P&L Drawer ─────────────────────────────────────────────────────────

interface StorePnlDrawerProps {
  storeId: string | null;
  storeName: string;
  period: PeriodKey;
  open: boolean;
  onClose: () => void;
}

function StorePnlDrawer({ storeId, storeName, period, open, onClose }: StorePnlDrawerProps) {
  const [loading, setLoading] = useState(false);
  const [pnl, setPnl] = useState<StorePnlOverview | null>(null);

  useEffect(() => {
    if (!open || !storeId) return;
    setLoading(true);
    const params: HQDateParams = { period };
    getStorePnlOverview(storeId, params)
      .then((data) => setPnl(data))
      .catch((err) => {
        const msg = err instanceof Error ? err.message : '加载失败';
        message.error(`P&L数据加载失败：${msg}`);
      })
      .finally(() => setLoading(false));
  }, [storeId, period, open]);

  return (
    <Drawer
      title={`${storeName} · P&L 概览`}
      width={480}
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      {loading || !pnl ? (
        <Skeleton active paragraph={{ rows: 10 }} />
      ) : (
        <>
          <Text type="secondary" style={{ fontSize: 12 }}>统计周期：{pnl.period_label}</Text>

          {/* 核心指标卡 */}
          <Row gutter={16} style={{ marginTop: 16, marginBottom: 16 }}>
            <Col span={12}>
              <Statistic
                title="营收"
                value={fenToYuan(pnl.revenue_fen)}
                valueStyle={{ color: '#FF6B35', fontSize: 16 }}
              />
            </Col>
            <Col span={12}>
              <Statistic
                title="毛利润"
                value={fenToYuan(pnl.gross_profit_fen)}
                valueStyle={{
                  color: pnl.gross_margin >= 0.4 ? '#0F6E56' : '#A32D2D',
                  fontSize: 16,
                }}
              />
            </Col>
            <Col span={12} style={{ marginTop: 12 }}>
              <Statistic
                title="毛利率"
                value={pctDisplay(pnl.gross_margin)}
                valueStyle={{
                  color: marginTagColor(pnl.gross_margin) === 'green' ? '#0F6E56'
                    : marginTagColor(pnl.gross_margin) === 'orange' ? '#BA7517' : '#A32D2D',
                  fontSize: 16,
                }}
              />
            </Col>
            <Col span={12} style={{ marginTop: 12 }}>
              <Statistic
                title="净利率"
                value={pctDisplay(pnl.net_margin)}
                valueStyle={{
                  color: pnl.net_margin >= 0.1 ? '#0F6E56' : pnl.net_margin >= 0 ? '#BA7517' : '#A32D2D',
                  fontSize: 16,
                }}
              />
            </Col>
          </Row>

          <Divider style={{ margin: '12px 0' }} />

          {/* 成本明细 */}
          <Descriptions
            title="成本结构"
            column={1}
            size="small"
            labelStyle={{ color: '#5F5E5A', minWidth: 100 }}
          >
            <Descriptions.Item label="销售成本">
              <Space>
                <Text>{fenToYuan(pnl.cost_of_goods_fen)}</Text>
                <Tag color={marginTagColor(pnl.gross_margin)}>
                  毛利率 {pctDisplay(pnl.gross_margin)}
                </Tag>
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label="人力成本">
              <Space>
                <Text>{fenToYuan(pnl.labor_cost_fen)}</Text>
                <Tag color={pnl.labor_cost_rate > 0.35 ? 'red' : 'green'}>
                  {pctDisplay(pnl.labor_cost_rate)}
                </Tag>
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label="运营费用">
              <Text>{fenToYuan(pnl.operating_expense_fen)}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="净利润">
              <Text strong style={{ color: pnl.net_profit_fen >= 0 ? '#0F6E56' : '#A32D2D' }}>
                {fenToYuan(pnl.net_profit_fen)}（{pctDisplay(pnl.net_margin)}）
              </Text>
            </Descriptions.Item>
          </Descriptions>
        </>
      )}
    </Drawer>
  );
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export function StorePerformanceMatrix() {
  // 品牌Tab — 动态从 API 加载
  const [brandTabs, setBrandTabs] = useState<{ brand_id: string; brand_name: string }[]>([]);
  const [activeBrandId, setActiveBrandId] = useState<string>('all');
  const [period, setPeriod] = useState<PeriodKey>('today');
  const [city, setCity] = useState<string | undefined>(undefined);
  const [sortBy, setSortBy] = useState<StorePerformanceParams['sort_by']>('revenue');

  // Drawer 状态
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedStore, setSelectedStore] = useState<{ id: string; name: string } | null>(null);

  // 加载品牌列表（用 getBrandsOverview 获取品牌名）
  useEffect(() => {
    getBrandsOverview({ period: 'today' })
      .then((res) => {
        const tabs = (res.brands ?? []).map((b) => ({
          brand_id: b.brand_id,
          brand_name: b.brand_name,
        }));
        setBrandTabs(tabs);
      })
      .catch(() => {
        // 加载失败时保留空状态，不展示错误（品牌Tab非核心阻塞项）
      });
  }, []);

  // ProTable 请求函数
  const fetchStores = useCallback(
    async (
      params: { current?: number; pageSize?: number } & Record<string, unknown>,
    ): Promise<RequestData<StorePerformanceItem>> => {
      const reqParams: StorePerformanceParams = {
        period,
        city: city || undefined,
        sort_by: sortBy,
        sort_order: 'desc',
        page: params.current ?? 1,
        size: params.pageSize ?? 20,
      };

      const brandId = activeBrandId === 'all' ? 'all' : activeBrandId;

      try {
        const res = await getBrandStorePerformance(brandId, reqParams);
        return { data: res.items, total: res.total, success: true };
      } catch (err) {
        const msg = err instanceof Error ? err.message : '加载失败';
        message.error(`门店绩效数据加载失败：${msg}`);
        return { data: [], total: 0, success: false };
      }
    },
    [activeBrandId, period, city, sortBy],
  );

  // ─── ProTable 列配置 ───────────────────────────────────────────────────────

  const columns: ProColumns<StorePerformanceItem>[] = [
    {
      title: '排名',
      dataIndex: 'rank',
      width: 56,
      align: 'center',
      render: (_, record) => (
        <Text strong style={{ color: record.rank <= 3 ? '#FF6B35' : undefined }}>
          {record.rank}
        </Text>
      ),
    },
    {
      title: '门店名',
      dataIndex: 'store_name',
      ellipsis: true,
      render: (_, record) => (
        <a onClick={() => {
          setSelectedStore({ id: record.store_id, name: record.store_name });
          setDrawerOpen(true);
        }}>
          {record.store_name}
        </a>
      ),
    },
    {
      title: '城市',
      dataIndex: 'city',
      width: 80,
    },
    {
      title: '今日营收',
      dataIndex: 'today_revenue_fen',
      width: 120,
      render: (_, record) => (
        <Text strong style={{ color: '#FF6B35' }}>
          {fenToYuan(record.today_revenue_fen)}
        </Text>
      ),
    },
    {
      title: '目标达成率',
      dataIndex: 'target_rate',
      width: 110,
      render: (_, record) => (
        <Tag color={targetRateColor(record.target_rate)}>
          {pctDisplay(record.target_rate)}
        </Tag>
      ),
    },
    {
      title: '毛利率',
      dataIndex: 'gross_margin',
      width: 100,
      render: (_, record) => (
        <Tag color={marginTagColor(record.gross_margin)}>
          {pctDisplay(record.gross_margin)}
        </Tag>
      ),
    },
    {
      title: '人力成本率',
      dataIndex: 'labor_cost_rate',
      width: 105,
      render: (_, record) => (
        <Tag color={record.labor_cost_rate > 0.35 ? 'red' : 'green'}>
          {pctDisplay(record.labor_cost_rate)}
        </Tag>
      ),
    },
    {
      title: '客流量',
      dataIndex: 'customer_count',
      width: 80,
      render: (_, record) => `${record.customer_count.toLocaleString('zh-CN')} 人`,
    },
    {
      title: '趋势',
      dataIndex: 'trend',
      width: 60,
      align: 'center',
      render: (_, record) => <TrendIcon trend={record.trend} />,
    },
    {
      title: '预警',
      dataIndex: 'alert_count',
      width: 70,
      align: 'center',
      render: (_, record) =>
        record.alert_count > 0 ? (
          <Tooltip title={`${record.alert_count} 条预警`}>
            <Badge count={record.alert_count} color={record.alert_count >= 3 ? 'red' : 'orange'} />
          </Tooltip>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 80,
      render: (_, record) => [
        <a
          key="detail"
          onClick={() => {
            setSelectedStore({ id: record.store_id, name: record.store_name });
            setDrawerOpen(true);
          }}
        >
          P&L
        </a>,
      ],
    },
  ];

  // ─── 渲染 ─────────────────────────────────────────────────────────────────

  return (
    <ConfigProvider theme={txAdminTheme}>
      <div style={{ minWidth: 1280, padding: '0 4px' }}>
        {/* 页头 */}
        <div style={{ marginBottom: 16 }}>
          <Title level={4} style={{ margin: 0 }}>门店绩效矩阵</Title>
        </div>

        {/* 筛选区 */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          marginBottom: 16,
          flexWrap: 'wrap',
        }}>
          {/* 日期选择 */}
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>周期</Text>
            <Select
              value={period}
              onChange={(v) => setPeriod(v as PeriodKey)}
              options={PERIOD_OPTIONS}
              style={{ width: 100 }}
              size="small"
            />
          </Space>

          {/* 城市筛选 */}
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>城市</Text>
            <Select
              allowClear
              placeholder="全部城市"
              value={city}
              onChange={(v) => setCity(v)}
              style={{ width: 120 }}
              size="small"
            >
              <Option value="长沙">长沙</Option>
              <Option value="北京">北京</Option>
              <Option value="上海">上海</Option>
              <Option value="深圳">深圳</Option>
              <Option value="广州">广州</Option>
            </Select>
          </Space>

          {/* 排序 */}
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>排序</Text>
            <Select
              value={sortBy}
              onChange={(v) => setSortBy(v as StorePerformanceParams['sort_by'])}
              options={SORT_OPTIONS}
              style={{ width: 140 }}
              size="small"
            />
          </Space>
        </div>

        {/* 品牌Tab */}
        <Tabs
          activeKey={activeBrandId}
          onChange={(key) => setActiveBrandId(key)}
          size="small"
          style={{ marginBottom: 0 }}
          items={[
            { key: 'all', label: '全部品牌' },
            ...brandTabs.map((b) => ({
              key: b.brand_id,
              label: b.brand_name,
            })),
          ]}
        />

        {/* 门店绩效 ProTable */}
        <ProTable<StorePerformanceItem>
          columns={columns}
          request={fetchStores}
          rowKey="store_id"
          search={false}
          options={{ reload: true, density: false, setting: true }}
          pagination={{ defaultPageSize: 20, showSizeChanger: true, showQuickJumper: true }}
          size="small"
          scroll={{ x: 1100 }}
          onRow={(record) => ({
            onClick: () => {
              setSelectedStore({ id: record.store_id, name: record.store_name });
              setDrawerOpen(true);
            },
            style: { cursor: 'pointer' },
          })}
          params={{ period, city, sortBy, activeBrandId }}
        />

        {/* 门店 P&L Drawer */}
        <StorePnlDrawer
          storeId={selectedStore?.id ?? null}
          storeName={selectedStore?.name ?? ''}
          period={period}
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
        />
      </div>
    </ConfigProvider>
  );
}
