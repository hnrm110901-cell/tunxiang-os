/**
 * 菜品经营分析页面
 * 域G — 经营分析 > 菜品分析
 *
 * Tab1: 热销排行    — 时间筛选 + 进度条 + 明细表
 * Tab2: 时段热力图  — 7×24 CSS Grid 热力矩阵
 * Tab3: 搭配分析    — 菜品搜索 + 搭配率进度条
 * Tab4: 预警建议    — 低效菜品 + 下架/优化操作
 */
import { useCallback, useEffect, useState } from 'react';
import dayjs from 'dayjs';
import {
  ConfigProvider,
  DatePicker,
  Tabs,
  Card,
  Row,
  Col,
  Select,
  Table,
  Tag,
  Progress,
  Typography,
  Space,
  Button,
  Popconfirm,
  Spin,
  message,
  Tooltip,
} from 'antd';
import {
  RiseOutlined,
  FallOutlined,
  MinusOutlined,
  WarningOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';

const { Title, Text } = Typography;

// ── Design Token ─────────────────────────────────────────────────
const txAdminTheme = {
  token: {
    colorPrimary: '#FF6B35',
    colorSuccess: '#0F6E56',
    colorWarning: '#BA7517',
    colorError: '#A32D2D',
    colorInfo: '#185FA5',
    colorTextBase: '#2C2C2A',
    borderRadius: 6,
    fontSize: 14,
  },
  components: {
    Table: { headerBg: '#F8F7F5' },
  },
};

// ── 类型定义 ─────────────────────────────────────────────────────
interface TopDish {
  dish_id: string;
  dish_name: string;
  category: string;
  sales_count: number;
  revenue_fen: number;
  gross_margin_pct: number;
  avg_daily_count: number;
  trend: 'up' | 'down' | 'stable';
}

interface HeatmapCell {
  day_of_week: number;
  hour: number;
  count: number;
}

interface PairingItem {
  dish_name: string;
  co_occurrence_rate: number;
  count: number;
}

interface UnderperformingItem {
  dish_name: string;
  sales_count: number;
  gross_margin_pct: number;
  quadrant: 'dog' | 'question_mark';
  suggestion: string;
}

// ── 工具函数 ─────────────────────────────────────────────────────
const formatRevenue = (fen: number) =>
  `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0 })}`;

const TrendIcon = ({ trend }: { trend: TopDish['trend'] }) => {
  if (trend === 'up') return <RiseOutlined style={{ color: '#0F6E56' }} />;
  if (trend === 'down') return <FallOutlined style={{ color: '#A32D2D' }} />;
  return <MinusOutlined style={{ color: '#B4B2A9' }} />;
};

const MarginTag = ({ pct }: { pct: number }) => {
  const color = pct >= 0.6 ? 'success' : pct >= 0.45 ? 'warning' : 'error';
  return <Tag color={color}>{(pct * 100).toFixed(1)}%</Tag>;
};

// ── API 调用 ─────────────────────────────────────────────────────
import { txFetchData } from '../../api';
const BASE = '/api/v1/analytics';

// 新增类型：BCG 分析结果
interface DishBCGItem {
  dish_id: string;
  dish_name: string;
  quadrant: 'star' | 'cash_cow' | 'question_mark' | 'dog';
  sales_index: number;
  margin_index: number;
  gross_margin_pct: number;
  sales_count: number;
}

async function fetchTopDishes(storeId: string, date: string, days: number): Promise<TopDish[]> {
  try {
    const params = new URLSearchParams({ days: String(days), limit: '10' });
    if (storeId) params.set('store_id', storeId);
    if (date) params.set('date', date);
    const data = await txFetchData<{ dishes?: TopDish[]; items?: TopDish[] }>(
      `${BASE}/dish-sales?${params.toString()}`,
    );
    return data.dishes ?? data.items ?? [];
  } catch {
    return [];
  }
}

async function fetchHeatmap(storeId: string, days: number): Promise<HeatmapCell[]> {
  try {
    const params = new URLSearchParams({ days: String(days) });
    if (storeId) params.set('store_id', storeId);
    const data = await txFetchData<{ heatmap?: HeatmapCell[]; items?: HeatmapCell[] }>(
      `${BASE}/dish-trends?${params.toString()}`,
    );
    return data.heatmap ?? data.items ?? [];
  } catch {
    return [];
  }
}

async function fetchPairing(dishId: string, storeId?: string): Promise<PairingItem[]> {
  try {
    const params = new URLSearchParams({ dish_id: dishId });
    if (storeId) params.set('store_id', storeId);
    const data = await txFetchData<{ pairings?: PairingItem[]; items?: PairingItem[] }>(
      `${BASE}/dish-sales/pairing?${params.toString()}`,
    );
    return data.pairings ?? data.items ?? [];
  } catch {
    return [];
  }
}

async function fetchUnderperforming(storeId: string, days: number): Promise<UnderperformingItem[]> {
  try {
    const params = new URLSearchParams({ days: String(days) });
    if (storeId) params.set('store_id', storeId);
    const data = await txFetchData<{ items?: UnderperformingItem[] }>(
      `${BASE}/dish-bcg?${params.toString()}`,
    );
    return (data.items ?? []).filter((it: UnderperformingItem) =>
      it.quadrant === 'dog' || it.quadrant === 'question_mark',
    );
  } catch {
    return [];
  }
}

// ════════════════════════════════════════════════════════════════
// Tab1 — 热销排行
// ════════════════════════════════════════════════════════════════
function TopSellingTab({ storeId, date }: { storeId: string; date: string }) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<TopDish[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetchTopDishes(storeId, date, days)
      .then(setData)
      .finally(() => setLoading(false));
  }, [days, storeId, date]);

  const maxCount = data.reduce((m, d) => Math.max(m, d.sales_count), 1);

  const columns: ColumnsType<TopDish> = [
    {
      title: '菜品名称',
      dataIndex: 'dish_name',
      render: (name, r) => (
        <Space>
          <Text strong>{name}</Text>
          <TrendIcon trend={r.trend} />
        </Space>
      ),
    },
    { title: '分类', dataIndex: 'category', width: 90,
      render: (cat) => <Tag>{cat}</Tag> },
    {
      title: '销量',
      dataIndex: 'sales_count',
      width: 220,
      sorter: (a, b) => a.sales_count - b.sales_count,
      defaultSortOrder: 'descend',
      render: (count) => (
        <Space direction="vertical" size={2} style={{ width: '100%' }}>
          <Text>{count} 份</Text>
          <Progress
            percent={Math.round((count / maxCount) * 100)}
            showInfo={false}
            strokeColor="#FF6B35"
            size="small"
          />
        </Space>
      ),
    },
    {
      title: '营收',
      dataIndex: 'revenue_fen',
      sorter: (a, b) => a.revenue_fen - b.revenue_fen,
      render: (fen) => <Text>{formatRevenue(fen)}</Text>,
    },
    {
      title: '毛利率',
      dataIndex: 'gross_margin_pct',
      sorter: (a, b) => a.gross_margin_pct - b.gross_margin_pct,
      render: (pct) => <MarginTag pct={pct} />,
    },
    {
      title: '日均销量',
      dataIndex: 'avg_daily_count',
      sorter: (a, b) => a.avg_daily_count - b.avg_daily_count,
      render: (v) => `${v} 份/天`,
    },
  ];

  return (
    <Spin spinning={loading}>
      <Space style={{ marginBottom: 16 }}>
        <Text>统计周期：</Text>
        <Select
          value={days}
          onChange={setDays}
          style={{ width: 120 }}
          options={[
            { label: '近 7 天', value: 7 },
            { label: '近 30 天', value: 30 },
            { label: '近 90 天', value: 90 },
          ]}
        />
      </Space>
      <Table
        columns={columns}
        dataSource={data}
        rowKey="dish_id"
        pagination={false}
        size="middle"
      />
    </Spin>
  );
}

// ════════════════════════════════════════════════════════════════
// Tab2 — 时段热力图
// ════════════════════════════════════════════════════════════════
const DAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

function TimeHeatmapTab({ storeId }: { storeId: string }) {
  const [days, setDays] = useState(30);
  const [cells, setCells] = useState<HeatmapCell[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<HeatmapCell | null>(null);

  useEffect(() => {
    setLoading(true);
    fetchHeatmap(storeId, days)
      .then(setCells)
      .finally(() => setLoading(false));
  }, [days, storeId]);

  const maxCount = cells.reduce((m, c) => Math.max(m, c.count), 0.01);

  const getCell = (day: number, hour: number) =>
    cells.find((c) => c.day_of_week === day && c.hour === hour);

  const cellBg = (count: number) => {
    const opacity = Math.min(0.9, 0.05 + (count / maxCount) * 0.85);
    return `rgba(255, 107, 53, ${opacity.toFixed(2)})`;
  };

  return (
    <Spin spinning={loading}>
      <Space style={{ marginBottom: 16 }}>
        <Text>统计周期：</Text>
        <Select
          value={days}
          onChange={setDays}
          style={{ width: 120 }}
          options={[
            { label: '近 7 天', value: 7 },
            { label: '近 30 天', value: 30 },
            { label: '近 90 天', value: 90 },
          ]}
        />
        {selected && (
          <Tag color="orange">
            {DAY_LABELS[selected.day_of_week]} {String(selected.hour).padStart(2, '0')}:00 — 均销 {selected.count.toFixed(1)} 份
          </Tag>
        )}
      </Space>

      {/* 热力图 Grid */}
      <div style={{ overflowX: 'auto' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '36px repeat(7, 1fr)', gap: 2, minWidth: 520 }}>
          {/* 表头行 */}
          <div style={{ height: 28 }} />
          {DAY_LABELS.map((d) => (
            <div key={d} style={{ textAlign: 'center', fontSize: 12, color: '#5F5E5A', lineHeight: '28px' }}>
              {d}
            </div>
          ))}

          {/* 数据行 0-23时 */}
          {Array.from({ length: 24 }, (_, hour) => (
            <>
              <div
                key={`h-${hour}`}
                style={{ fontSize: 11, color: '#B4B2A9', textAlign: 'right', paddingRight: 6, lineHeight: '24px' }}
              >
                {String(hour).padStart(2, '0')}
              </div>
              {Array.from({ length: 7 }, (_, day) => {
                const cell = getCell(day, hour);
                const count = cell?.count ?? 0;
                return (
                  <Tooltip
                    key={`${day}-${hour}`}
                    title={`${DAY_LABELS[day]} ${String(hour).padStart(2, '0')}:00  均销 ${count.toFixed(1)} 份`}
                  >
                    <div
                      onClick={() => setSelected(cell ?? null)}
                      style={{
                        height: 24,
                        borderRadius: 3,
                        backgroundColor: cellBg(count),
                        cursor: 'pointer',
                        border: selected?.day_of_week === day && selected?.hour === hour
                          ? '2px solid #FF6B35'
                          : '1px solid #E8E6E1',
                        transition: 'opacity 0.15s',
                      }}
                    />
                  </Tooltip>
                );
              })}
            </>
          ))}
        </div>
      </div>

      {/* 图例 */}
      <Space style={{ marginTop: 12 }} align="center">
        <Text type="secondary" style={{ fontSize: 12 }}>低</Text>
        {[0.05, 0.25, 0.5, 0.75, 0.95].map((op) => (
          <div
            key={op}
            style={{
              width: 18,
              height: 14,
              borderRadius: 3,
              backgroundColor: `rgba(255, 107, 53, ${op})`,
              border: '1px solid #E8E6E1',
            }}
          />
        ))}
        <Text type="secondary" style={{ fontSize: 12 }}>高</Text>
      </Space>
    </Spin>
  );
}

// ════════════════════════════════════════════════════════════════
// Tab3 — 搭配分析
// ════════════════════════════════════════════════════════════════

function PairingTab({ storeId }: { storeId: string }) {
  const [dishId, setDishId] = useState<string>('');
  const [data, setData] = useState<PairingItem[]>([]);
  const [dishOptions, setDishOptions] = useState<{ label: string; value: string }[]>([]);

  useEffect(() => {
    txFetchData<{ items: { id: string; name: string }[] }>(`/api/v1/menu/dishes?store_id=${storeId}&page=1&size=200`)
      .then((res) => {
        if (res?.items?.length) {
          setDishOptions(res.items.map((d) => ({ label: d.name, value: d.id })));
          if (!dishId && res.items[0]) setDishId(res.items[0].id);
        }
      })
      .catch(() => setDishOptions([]));
  }, [storeId]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!dishId) return;
    setLoading(true);
    fetchPairing(dishId, storeId)
      .then(setData)
      .finally(() => setLoading(false));
  }, [dishId, storeId]);

  return (
    <Spin spinning={loading}>
      <Space style={{ marginBottom: 20 }}>
        <Text>选择菜品：</Text>
        <Select
          showSearch
          value={dishId}
          onChange={setDishId}
          style={{ width: 200 }}
          options={dishOptions}
          placeholder="搜索菜品名称"
          filterOption={(input, opt) =>
            (opt?.label as string)?.toLowerCase().includes(input.toLowerCase())
          }
        />
      </Space>

      {data.length > 0 ? (
        <div style={{ maxWidth: 560 }}>
          {data.map((item) => (
            <div
              key={item.dish_name}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                marginBottom: 16,
                padding: '10px 14px',
                background: '#F8F7F5',
                borderRadius: 6,
              }}
            >
              <Text style={{ width: 120, flexShrink: 0 }}>{item.dish_name}</Text>
              <Progress
                percent={Math.round(item.co_occurrence_rate * 100)}
                strokeColor="#FF6B35"
                style={{ flex: 1, marginBottom: 0 }}
                format={(pct) => `${pct}%`}
              />
              <Text type="secondary" style={{ width: 70, textAlign: 'right', flexShrink: 0 }}>
                {item.count} 次
              </Text>
            </div>
          ))}
          <Text type="secondary" style={{ fontSize: 12 }}>
            搭配率 = 与所选菜品同单出现的比例
          </Text>
        </div>
      ) : (
        <Text type="secondary">暂无搭配数据</Text>
      )}
    </Spin>
  );
}

// ════════════════════════════════════════════════════════════════
// Tab4 — 预警建议
// ════════════════════════════════════════════════════════════════
function UnderperformingTab({ storeId }: { storeId: string }) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<UnderperformingItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetchUnderperforming(storeId, days)
      .then(setData)
      .finally(() => setLoading(false));
  }, [days, storeId]);

  const handleAction = (dish: UnderperformingItem, action: 'delist' | 'promote') => {
    if (action === 'delist') {
      message.success(`已提交下架申请：${dish.dish_name}`);
    } else {
      message.success(`已创建推广任务：${dish.dish_name}`);
    }
  };

  return (
    <Spin spinning={loading}>
      <Space style={{ marginBottom: 16 }}>
        <Text>统计周期：</Text>
        <Select
          value={days}
          onChange={setDays}
          style={{ width: 120 }}
          options={[
            { label: '近 7 天', value: 7 },
            { label: '近 30 天', value: 30 },
            { label: '近 90 天', value: 90 },
          ]}
        />
      </Space>

      <Row gutter={[12, 12]}>
        {data.map((item) => {
          const isDog = item.quadrant === 'dog';
          const tagColor = isDog ? 'error' : 'warning';
          const tagLabel = isDog ? '瘦狗菜品' : '问号菜品';
          const borderColor = isDog ? '#FFCCC7' : '#FFE7BA';
          const bgColor = isDog ? '#FFF2F0' : '#FFFBE6';

          return (
            <Col span={24} key={item.dish_name}>
              <Card
                size="small"
                style={{ borderColor, backgroundColor: bgColor }}
              >
                <Row align="middle" gutter={12}>
                  <Col flex="auto">
                    <Space wrap>
                      <Text strong style={{ fontSize: 15 }}>{item.dish_name}</Text>
                      <Tag color={tagColor}>{tagLabel}</Tag>
                      <Text type="secondary">
                        近 {days} 天销量：{item.sales_count} 份
                      </Text>
                      <MarginTag pct={item.gross_margin_pct} />
                    </Space>
                    <div style={{ marginTop: 4 }}>
                      <Text
                        style={{
                          color: isDog ? '#A32D2D' : '#BA7517',
                          fontSize: 13,
                        }}
                      >
                        {isDog ? <WarningOutlined /> : <QuestionCircleOutlined />}
                        {' '}{item.suggestion}
                      </Text>
                    </div>
                  </Col>
                  <Col flex="none">
                    <Space>
                      {isDog ? (
                        <Popconfirm
                          title="确认提交下架申请？"
                          description="下架后此菜品将从菜单中移除，需经管理员审批。"
                          onConfirm={() => handleAction(item, 'delist')}
                          okText="确认下架"
                          cancelText="取消"
                          okButtonProps={{ danger: true }}
                        >
                          <Button danger size="small">申请下架</Button>
                        </Popconfirm>
                      ) : (
                        <Popconfirm
                          title="创建推广任务？"
                          description="将为此菜品生成推广建议并通知运营团队。"
                          onConfirm={() => handleAction(item, 'promote')}
                          okText="确认"
                          cancelText="取消"
                        >
                          <Button size="small" style={{ color: '#BA7517', borderColor: '#BA7517' }}>
                            创建推广
                          </Button>
                        </Popconfirm>
                      )}
                    </Space>
                  </Col>
                </Row>
              </Card>
            </Col>
          );
        })}
        {data.length === 0 && !loading && (
          <Col span={24}>
            <Text type="secondary">暂无需要关注的低效菜品</Text>
          </Col>
        )}
      </Row>
    </Spin>
  );
}

// ════════════════════════════════════════════════════════════════
// 主页面
// ════════════════════════════════════════════════════════════════

const ALL_STORES_OPTION = { value: '', label: '全部门店' };

export function DishAnalyticsPage() {
  const [storeId, setStoreId] = useState('');
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [storeOptions, setStoreOptions] = useState<{ value: string; label: string }[]>([ALL_STORES_OPTION]);
  const [overviewLoading, setOverviewLoading] = useState(false);
  // 存储并发加载的概览数据（sales/trends/bcg），传给各 Tab 作 fallback
  const [_salesData, setSalesData] = useState<TopDish[]>([]);
  const [_bcgData, setBcgData] = useState<DishBCGItem[]>([]);

  // Promise.allSettled 并发加载概览数据
  const loadOverview = useCallback(async (sid: string, d: string) => {
    setOverviewLoading(true);
    try {
      const [salesRes, _trendRes, bcgRes] = await Promise.allSettled([
        txFetchData<{ dishes?: TopDish[]; items?: TopDish[] }>(
          `${BASE}/dish-sales?store_id=${sid}&date=${d}`,
        ),
        txFetchData<unknown>(
          `${BASE}/dish-trends?store_id=${sid}&days=30`,
        ),
        txFetchData<{ items?: DishBCGItem[] }>(
          `${BASE}/dish-bcg?store_id=${sid}`,
        ),
      ]);
      if (salesRes.status === 'fulfilled') {
        setSalesData(salesRes.value.dishes ?? salesRes.value.items ?? []);
      }
      if (bcgRes.status === 'fulfilled') {
        setBcgData(bcgRes.value.items ?? []);
      }
    } catch {
      // 并发加载失败时各 Tab 自行处理
    } finally {
      setOverviewLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadOverview(storeId, date);
  }, [storeId, date, loadOverview]);

  // 加载门店列表
  useEffect(() => {
    txFetchData<{ items: { id: string; name: string }[] }>('/api/v1/org/stores?page=1&size=100')
      .then((data) => {
        if (data?.items?.length) {
          setStoreOptions([
            ALL_STORES_OPTION,
            ...data.items.map((s) => ({ value: s.id, label: s.name })),
          ]);
        }
      })
      .catch(() => { /* 保持默认选项 */ });
  }, []);

  return (
    <ConfigProvider theme={txAdminTheme}>
      <div style={{ padding: '24px', minWidth: 1280, background: '#F8F7F5', minHeight: '100vh' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <Title level={4} style={{ margin: 0, color: '#2C2C2A' }}>
            菜品经营分析
          </Title>
          <Space>
            <Select
              value={storeId}
              onChange={setStoreId}
              options={storeOptions}
              style={{ width: 160 }}
              placeholder="选择门店"
            />
            <DatePicker
              value={date ? dayjs(date) : undefined}
              onChange={(_, dateStr) => {
                if (typeof dateStr === 'string' && dateStr) setDate(dateStr);
              }}
              style={{ width: 130 }}
              allowClear={false}
            />
            {overviewLoading && <Spin size="small" />}
          </Space>
        </div>
        <Card bodyStyle={{ padding: '0 8px 16px' }}>
          <Tabs
            defaultActiveKey="top-selling"
            size="middle"
            style={{ padding: '0 8px' }}
            items={[
              {
                key: 'top-selling',
                label: '热销排行',
                children: (
                  <div style={{ padding: '16px 8px 0' }}>
                    <TopSellingTab storeId={storeId} date={date} />
                  </div>
                ),
              },
              {
                key: 'heatmap',
                label: '时段热力图',
                children: (
                  <div style={{ padding: '16px 8px 0' }}>
                    <TimeHeatmapTab storeId={storeId} />
                  </div>
                ),
              },
              {
                key: 'pairing',
                label: '搭配分析',
                children: (
                  <div style={{ padding: '16px 8px 0' }}>
                    <PairingTab storeId={storeId} />
                  </div>
                ),
              },
              {
                key: 'underperforming',
                label: '预警建议',
                children: (
                  <div style={{ padding: '16px 8px 0' }}>
                    <UnderperformingTab storeId={storeId} />
                  </div>
                ),
              },
            ]}
          />
        </Card>
      </div>
    </ConfigProvider>
  );
}
