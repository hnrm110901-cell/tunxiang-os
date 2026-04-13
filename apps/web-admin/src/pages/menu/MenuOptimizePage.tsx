/**
 * MenuOptimizePage — 菜品优化AI推荐
 * 调用 POST /api/v1/menu/recommendation/generate  生成推荐方案
 * 调用 GET  /api/v1/menu/recommendation/history    历史记录
 * 调用 POST /api/v1/menu/recommendation/apply      应用方案
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Button,
  Card,
  Col,
  message,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  BulbOutlined,
  CheckCircleOutlined,
  ExperimentOutlined,
  HistoryOutlined,
  ReloadOutlined,
  RocketOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { txFetchData } from '../../api';
import { formatPrice } from '@tx-ds/utils';

const { Text } = Typography;

// ─── 类型定义 ───

interface DishRecommendation {
  dish_id: string;
  dish_name: string;
  category: string;
  current_price_fen: number;
  suggested_price_fen?: number;
  quadrant: 'star' | 'cash_cow' | 'question' | 'dog';
  action: 'keep' | 'promote' | 'demote' | 'add' | 'remove' | 'price_up' | 'price_down' | 'combo';
  confidence: number;
  reasoning: string;
  factors: string[];
  sales_7d: number;
  sales_30d: number;
  gross_margin_pct: number;
  inventory_days?: number;
  combo_with: string[];
}

interface RecommendationSummary {
  total_dishes: number;
  keep_count: number;
  promote_count: number;
  demote_count: number;
  add_count: number;
  remove_count: number;
  combo_count: number;
  estimated_margin_change_pct: number;
  estimated_turnover_change_pct: number;
  ai_confidence: number;
  key_insights: string[];
}

interface RecommendationPlan {
  plan_id: string;
  store_id: string;
  target_date: string;
  meal_period: string;
  optimization_goal: string;
  summary: RecommendationSummary;
  dishes: DishRecommendation[];
  generated_at: string;
  applied_at?: string;
}

interface HistoryRecord {
  plan_id: string;
  store_id: string;
  target_date: string;
  total_dishes: number;
  applied: boolean;
  applied_at?: string;
  optimization_goal: string;
  estimated_margin_change_pct: number;
  generated_at: string;
}

type OptimizationGoal = 'balanced' | 'margin' | 'turnover' | 'inventory';

// ─── 常量 ───

const OPTIMIZATION_GOALS: { value: OptimizationGoal; label: string }[] = [
  { value: 'balanced', label: '综合平衡' },
  { value: 'margin', label: '毛利优先' },
  { value: 'turnover', label: '翻台优先' },
  { value: 'inventory', label: '库存消耗' },
];

const MEAL_PERIODS = [
  { value: 'lunch', label: '午市' },
  { value: 'dinner', label: '晚市' },
  { value: 'breakfast', label: '早市' },
];

const QUADRANT_CONFIG: Record<string, { color: string; label: string }> = {
  star: { color: 'gold', label: '明星菜' },
  cash_cow: { color: 'green', label: '现金牛' },
  question: { color: 'blue', label: '问题菜' },
  dog: { color: 'default', label: '瘦狗菜' },
};

const ACTION_CONFIG: Record<string, { color: string; label: string }> = {
  keep: { color: 'default', label: '保持' },
  promote: { color: 'green', label: '推广' },
  demote: { color: 'orange', label: '降级' },
  add: { color: 'cyan', label: '新增' },
  remove: { color: 'red', label: '移除' },
  price_up: { color: 'volcano', label: '涨价' },
  price_down: { color: 'purple', label: '降价' },
  combo: { color: 'geekblue', label: '组合' },
};

// ─── 样式常量 ───

const PAGE_BG = '#0d1e28';
const CARD_BG = '#1a2a33';
const BORDER_COLOR = '#2a3a44';
const ACCENT = '#FF6B35';

const darkCardStyle: React.CSSProperties = {
  background: CARD_BG,
  border: `1px solid ${BORDER_COLOR}`,
  borderRadius: 10,
};

// ─── 主组件 ───

export function MenuOptimizePage() {
  const [storeId, setStoreId] = useState('');
  const [stores, setStores] = useState<{ id: string; name: string }[]>([]);
  const [goal, setGoal] = useState<OptimizationGoal>('balanced');
  const [mealPeriod, setMealPeriod] = useState('lunch');
  const [loading, setLoading] = useState(false);
  const [applyLoading, setApplyLoading] = useState(false);
  const [plan, setPlan] = useState<RecommendationPlan | null>(null);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [activeTab, setActiveTab] = useState('recommend');
  const historyRef = useRef<ActionType>();

  // 加载门店列表
  useEffect(() => {
    txFetchData<{ items: { id: string; name: string }[] }>('/api/v1/org/stores?page=1&size=100')
      .then((data) => {
        if (data?.items?.length) {
          setStores(data.items);
          setStoreId(data.items[0].id);
        }
      })
      .catch(() => setStores([]));
  }, []);

  // 生成推荐方案
  const handleGenerate = useCallback(async () => {
    if (!storeId) {
      message.warning('请先选择门店');
      return;
    }
    setLoading(true);
    setPlan(null);
    setSelectedRowKeys([]);
    try {
      const result = await txFetchData<RecommendationPlan>(
        '/api/v1/menu/recommendation/generate',
        {
          method: 'POST',
          body: JSON.stringify({
            store_id: storeId,
            meal_period: mealPeriod,
            optimization_goal: goal,
          }),
        },
      );
      setPlan(result);
      message.success('AI推荐方案已生成');
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '生成推荐方案失败');
    } finally {
      setLoading(false);
    }
  }, [storeId, mealPeriod, goal]);

  // 应用方案
  const handleApply = useCallback(async (applyAll: boolean) => {
    if (!plan) return;
    setApplyLoading(true);
    try {
      const actions = applyAll
        ? undefined
        : selectedRowKeys.map((key) => {
            const dish = plan.dishes.find((d) => d.dish_id === key);
            return dish ? { dish_id: dish.dish_id, action: dish.action } : null;
          }).filter(Boolean);

      await txFetchData('/api/v1/menu/recommendation/apply', {
        method: 'POST',
        body: JSON.stringify({
          plan_id: plan.plan_id,
          store_id: plan.store_id,
          apply_actions: actions,
        }),
      });
      message.success(applyAll ? '方案已全部应用' : `已应用 ${selectedRowKeys.length} 项建议`);
      setPlan((prev) => prev ? { ...prev, applied_at: new Date().toISOString() } : prev);
      historyRef.current?.reload();
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '应用方案失败');
    } finally {
      setApplyLoading(false);
    }
  }, [plan, selectedRowKeys]);

  // ─── 推荐表格列定义 ───
  const recommendColumns: ProColumns<DishRecommendation>[] = [
    {
      title: '菜品名',
      dataIndex: 'dish_name',
      width: 160,
      fixed: 'left',
      render: (_, record) => {
        const q = QUADRANT_CONFIG[record.quadrant];
        return (
          <Space>
            <span style={{
              display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
              background: q?.color === 'gold' ? '#faad14' : q?.color === 'green' ? '#52c41a' : q?.color === 'blue' ? '#1890ff' : '#888',
            }} />
            <Text strong style={{ color: '#fff' }}>{record.dish_name}</Text>
          </Space>
        );
      },
    },
    {
      title: '分类',
      dataIndex: 'category',
      width: 100,
      render: (text) => <Text style={{ color: '#aaa' }}>{text as string}</Text>,
    },
    {
      title: '当前价',
      dataIndex: 'current_price_fen',
      width: 90,
      align: 'right',
      render: (_, record) => <Text style={{ color: '#ccc' }}>{formatPrice(record.current_price_fen)}</Text>,
    },
    {
      title: '建议价',
      dataIndex: 'suggested_price_fen',
      width: 90,
      align: 'right',
      render: (_, record) => {
        if (!record.suggested_price_fen || record.suggested_price_fen === record.current_price_fen) {
          return <Text style={{ color: '#666' }}>-</Text>;
        }
        const isUp = record.suggested_price_fen > record.current_price_fen;
        return (
          <Text strong style={{ color: isUp ? '#ff4d4f' : '#52c41a' }}>
            {formatPrice(record.suggested_price_fen)}
          </Text>
        );
      },
    },
    {
      title: '四象限',
      dataIndex: 'quadrant',
      width: 90,
      render: (_, record) => {
        const cfg = QUADRANT_CONFIG[record.quadrant];
        return <Tag color={cfg?.color}>{cfg?.label}</Tag>;
      },
    },
    {
      title: '推荐动作',
      dataIndex: 'action',
      width: 80,
      render: (_, record) => {
        const cfg = ACTION_CONFIG[record.action];
        return <Tag color={cfg?.color}>{cfg?.label}</Tag>;
      },
    },
    {
      title: '7日销量',
      dataIndex: 'sales_7d',
      width: 80,
      align: 'right',
      sorter: (a, b) => a.sales_7d - b.sales_7d,
    },
    {
      title: '毛利率',
      dataIndex: 'gross_margin_pct',
      width: 120,
      sorter: (a, b) => a.gross_margin_pct - b.gross_margin_pct,
      render: (_, record) => (
        <Space>
          <Progress
            percent={Math.round(record.gross_margin_pct * 100)}
            size="small"
            strokeColor={record.gross_margin_pct >= 0.6 ? '#52c41a' : record.gross_margin_pct >= 0.4 ? '#faad14' : '#ff4d4f'}
            style={{ width: 60, marginBottom: 0 }}
            showInfo={false}
          />
          <Text style={{ color: '#ccc', fontSize: 12 }}>{(record.gross_margin_pct * 100).toFixed(1)}%</Text>
        </Space>
      ),
    },
    {
      title: 'AI置信度',
      dataIndex: 'confidence',
      width: 110,
      sorter: (a, b) => a.confidence - b.confidence,
      render: (_, record) => (
        <Progress
          percent={Math.round(record.confidence * 100)}
          size="small"
          strokeColor={ACCENT}
          format={(pct) => `${pct}%`}
          style={{ marginBottom: 0 }}
        />
      ),
    },
    {
      title: '推理说明',
      dataIndex: 'reasoning',
      width: 200,
      ellipsis: true,
      render: (_, record) => (
        <Tooltip title={record.reasoning} placement="topLeft" overlayStyle={{ maxWidth: 400 }}>
          <Text style={{ color: '#aaa', fontSize: 12 }}>{record.reasoning}</Text>
        </Tooltip>
      ),
    },
  ];

  // ─── 历史记录列定义 ───
  const historyColumns: ProColumns<HistoryRecord>[] = [
    {
      title: '方案ID',
      dataIndex: 'plan_id',
      width: 180,
      ellipsis: true,
      render: (text) => <Text copyable style={{ color: '#ccc', fontSize: 12 }}>{text as string}</Text>,
    },
    {
      title: '生成日期',
      dataIndex: 'generated_at',
      width: 160,
      render: (text) => <Text style={{ color: '#ccc' }}>{String(text).slice(0, 16).replace('T', ' ')}</Text>,
    },
    {
      title: '目标日期',
      dataIndex: 'target_date',
      width: 110,
    },
    {
      title: '优化目标',
      dataIndex: 'optimization_goal',
      width: 100,
      render: (text) => {
        const g = OPTIMIZATION_GOALS.find((o) => o.value === text);
        return <Tag>{g?.label ?? text}</Tag>;
      },
    },
    {
      title: '菜品数',
      dataIndex: 'total_dishes',
      width: 80,
      align: 'right',
    },
    {
      title: '预估毛利变化',
      dataIndex: 'estimated_margin_change_pct',
      width: 130,
      align: 'right',
      render: (_, record) => {
        const pct = record.estimated_margin_change_pct ?? 0;
        const color = pct > 0 ? '#52c41a' : pct < 0 ? '#ff4d4f' : '#888';
        return <Text style={{ color }}>{pct > 0 ? '+' : ''}{pct.toFixed(1)}%</Text>;
      },
    },
    {
      title: '状态',
      dataIndex: 'applied',
      width: 100,
      render: (_, record) =>
        record.applied
          ? <Tag icon={<CheckCircleOutlined />} color="success">已应用</Tag>
          : <Tag color="default">未应用</Tag>,
    },
  ];

  // ─── 汇总卡片 ───
  const renderSummaryCards = () => {
    if (!plan) return null;
    const s = plan.summary;
    const kpis: { label: string; value: number; color?: string; suffix?: string }[] = [
      { label: '总菜品', value: s.total_dishes, color: '#fff' },
      { label: '保持', value: s.keep_count, color: '#888' },
      { label: '推广', value: s.promote_count, color: '#52c41a' },
      { label: '新增', value: s.add_count, color: '#1890ff' },
      { label: '移除', value: s.remove_count, color: '#ff4d4f' },
      { label: '组合', value: s.combo_count, color: '#722ed1' },
    ];

    return (
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        {kpis.map((kpi) => (
          <Col key={kpi.label} xs={12} sm={8} md={4}>
            <Card size="small" style={darkCardStyle} bodyStyle={{ padding: '12px 16px' }}>
              <Statistic
                title={<Text style={{ color: '#888', fontSize: 12 }}>{kpi.label}</Text>}
                value={kpi.value}
                valueStyle={{ color: kpi.color ?? '#fff', fontSize: 22, fontWeight: 700 }}
              />
            </Card>
          </Col>
        ))}
        <Col xs={12} sm={8} md={4}>
          <Card size="small" style={darkCardStyle} bodyStyle={{ padding: '12px 16px' }}>
            <Statistic
              title={<Text style={{ color: '#888', fontSize: 12 }}>预估毛利变化</Text>}
              value={s.estimated_margin_change_pct * 100}
              precision={1}
              suffix="%"
              prefix={s.estimated_margin_change_pct > 0 ? '+' : ''}
              valueStyle={{
                color: s.estimated_margin_change_pct > 0 ? '#52c41a' : s.estimated_margin_change_pct < 0 ? '#ff4d4f' : '#fff',
                fontSize: 22, fontWeight: 700,
              }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small" style={darkCardStyle} bodyStyle={{ padding: '12px 16px' }}>
            <Statistic
              title={<Text style={{ color: '#888', fontSize: 12 }}>AI置信度</Text>}
              value={Math.round(s.ai_confidence * 100)}
              suffix="%"
              valueStyle={{ color: ACCENT, fontSize: 22, fontWeight: 700 }}
            />
          </Card>
        </Col>
      </Row>
    );
  };

  // ─── 关键洞察 ───
  const renderInsights = () => {
    if (!plan?.summary.key_insights?.length) return null;
    return (
      <Card
        size="small"
        title={<Space><BulbOutlined style={{ color: '#faad14' }} /><Text style={{ color: '#ddd' }}>AI 关键洞察</Text></Space>}
        style={{ ...darkCardStyle, marginBottom: 16 }}
        headStyle={{ background: 'transparent', borderBottom: `1px solid ${BORDER_COLOR}`, color: '#ddd' }}
        bodyStyle={{ padding: '12px 20px' }}
      >
        <ul style={{ margin: 0, paddingLeft: 20 }}>
          {plan.summary.key_insights.map((insight, idx) => (
            <li key={idx} style={{ color: '#ccc', fontSize: 13, lineHeight: 2 }}>{insight}</li>
          ))}
        </ul>
      </Card>
    );
  };

  // ─── Tab: AI推荐方案 ───
  const renderRecommendTab = () => (
    <>
      {/* 顶部操作栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
        marginBottom: 20, padding: '16px 20px',
        background: CARD_BG, borderRadius: 10, border: `1px solid ${BORDER_COLOR}`,
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <Text style={{ color: '#888', fontSize: 12 }}>门店</Text>
          <Select
            value={storeId || undefined}
            onChange={setStoreId}
            placeholder="选择门店"
            style={{ minWidth: 180 }}
            options={stores.map((s) => ({ value: s.id, label: s.name }))}
          />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <Text style={{ color: '#888', fontSize: 12 }}>餐段</Text>
          <Select
            value={mealPeriod}
            onChange={setMealPeriod}
            style={{ minWidth: 100 }}
            options={MEAL_PERIODS}
          />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <Text style={{ color: '#888', fontSize: 12 }}>优化目标</Text>
          <Select
            value={goal}
            onChange={setGoal}
            style={{ minWidth: 130 }}
            options={OPTIMIZATION_GOALS}
          />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignSelf: 'flex-end' }}>
          <Text style={{ color: 'transparent', fontSize: 12 }}>_</Text>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            loading={loading}
            onClick={handleGenerate}
            style={{ background: ACCENT, borderColor: ACCENT }}
          >
            生成AI推荐
          </Button>
        </div>
      </div>

      {/* 空状态 */}
      {!plan && !loading && (
        <div style={{
          background: CARD_BG, borderRadius: 12, border: `1px dashed ${BORDER_COLOR}`,
          padding: '60px 24px', textAlign: 'center',
        }}>
          <ExperimentOutlined style={{ fontSize: 52, color: '#555', marginBottom: 14 }} />
          <div style={{ color: '#888', fontSize: 15 }}>选择门店和优化目标，点击「生成AI推荐」</div>
          <div style={{ color: '#666', fontSize: 13, marginTop: 6 }}>
            AI将分析菜品四象限、毛利率、销量趋势与库存数据，生成优化方案
          </div>
        </div>
      )}

      {/* 方案结果 */}
      {plan && !loading && (
        <>
          {renderSummaryCards()}
          {renderInsights()}

          {/* 推荐表格 */}
          <ProTable<DishRecommendation>
            columns={recommendColumns}
            dataSource={plan.dishes}
            rowKey="dish_id"
            search={false}
            dateFormatter="string"
            pagination={{ pageSize: 20, showSizeChanger: true }}
            scroll={{ x: 1200 }}
            rowSelection={{
              selectedRowKeys,
              onChange: setSelectedRowKeys,
            }}
            headerTitle={
              <Space>
                <RocketOutlined style={{ color: ACCENT }} />
                <Text style={{ color: '#ddd', fontWeight: 600 }}>菜品推荐明细</Text>
                <Tag>{plan.dishes.length} 道</Tag>
              </Space>
            }
            toolBarRender={() => [
              <Button
                key="filter-promote"
                size="small"
                onClick={() => {
                  const keys = plan.dishes
                    .filter((d) => d.action === 'promote' || d.action === 'add' || d.action === 'combo')
                    .map((d) => d.dish_id);
                  setSelectedRowKeys(keys);
                }}
              >
                选中推广/新增/组合
              </Button>,
            ]}
            options={{
              density: true,
              reload: false,
            }}
            style={{ ...darkCardStyle }}
            cardProps={{ bodyStyle: { padding: 0 } }}
            expandable={{
              expandedRowRender: (record) => (
                <div style={{ padding: '8px 16px', color: '#aaa', fontSize: 13 }}>
                  <div style={{ marginBottom: 8 }}>
                    <Text strong style={{ color: '#ccc' }}>推理说明：</Text>
                    {record.reasoning}
                  </div>
                  {record.factors.length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      <Text strong style={{ color: '#ccc' }}>影响因子：</Text>
                      <Space wrap style={{ marginTop: 4 }}>
                        {record.factors.map((f, i) => <Tag key={i} color="processing">{f}</Tag>)}
                      </Space>
                    </div>
                  )}
                  {record.combo_with.length > 0 && (
                    <div>
                      <Text strong style={{ color: '#ccc' }}>推荐搭配：</Text>
                      <Space wrap style={{ marginTop: 4 }}>
                        {record.combo_with.map((c, i) => <Tag key={i} color="geekblue">{c}</Tag>)}
                      </Space>
                    </div>
                  )}
                  {record.inventory_days != null && (
                    <div style={{ marginTop: 8 }}>
                      <Text strong style={{ color: '#ccc' }}>库存天数：</Text>
                      <Text style={{ color: record.inventory_days <= 3 ? '#ff4d4f' : '#ccc' }}>
                        {record.inventory_days} 天
                      </Text>
                    </div>
                  )}
                  <div style={{ marginTop: 8 }}>
                    <Text strong style={{ color: '#ccc' }}>30日销量：</Text>
                    <Text style={{ color: '#ccc' }}>{record.sales_30d}</Text>
                  </div>
                </div>
              ),
            }}
          />

          {/* 底部操作栏 */}
          <div style={{
            display: 'flex', justifyContent: 'flex-end', gap: 12,
            marginTop: 16, padding: '12px 20px',
            background: CARD_BG, borderRadius: 10, border: `1px solid ${BORDER_COLOR}`,
          }}>
            {plan.applied_at && (
              <Tag icon={<CheckCircleOutlined />} color="success" style={{ lineHeight: '30px' }}>
                已于 {plan.applied_at.slice(0, 16).replace('T', ' ')} 应用
              </Tag>
            )}
            <Button
              onClick={() => handleApply(false)}
              disabled={selectedRowKeys.length === 0 || !!plan.applied_at}
              loading={applyLoading}
            >
              选择性应用 ({selectedRowKeys.length})
            </Button>
            <Button
              type="primary"
              icon={<CheckCircleOutlined />}
              onClick={() => handleApply(true)}
              disabled={!!plan.applied_at}
              loading={applyLoading}
              style={!plan.applied_at ? { background: ACCENT, borderColor: ACCENT } : {}}
            >
              全部应用
            </Button>
          </div>
        </>
      )}
    </>
  );

  // ─── Tab: 历史记录 ───
  const renderHistoryTab = () => (
    <ProTable<HistoryRecord>
      actionRef={historyRef}
      columns={historyColumns}
      rowKey="plan_id"
      search={false}
      dateFormatter="string"
      pagination={{ pageSize: 10 }}
      request={async () => {
        if (!storeId) return { data: [], total: 0, success: true };
        try {
          const data = await txFetchData<{ items: HistoryRecord[]; total: number }>(
            `/api/v1/menu/recommendation/history?store_id=${encodeURIComponent(storeId)}&limit=50`,
          );
          return { data: data.items ?? [], total: data.total ?? 0, success: true };
        } catch {
          message.error('加载历史记录失败');
          return { data: [], total: 0, success: true };
        }
      }}
      params={{ storeId }}
      headerTitle={
        <Space>
          <HistoryOutlined style={{ color: ACCENT }} />
          <Text style={{ color: '#ddd', fontWeight: 600 }}>推荐方案历史</Text>
        </Space>
      }
      toolBarRender={() => [
        <Button key="reload" icon={<ReloadOutlined />} onClick={() => historyRef.current?.reload()}>
          刷新
        </Button>,
      ]}
      style={darkCardStyle}
      cardProps={{ bodyStyle: { padding: 0 } }}
      options={{ density: true, reload: false }}
    />
  );

  return (
    <div style={{ padding: 24, minHeight: '100vh', background: PAGE_BG, color: '#fff' }}>
      {/* 页头 */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: '#fff' }}>
          <ExperimentOutlined style={{ marginRight: 8, color: ACCENT }} />
          菜品优化AI推荐
        </h2>
        <p style={{ color: '#888', margin: '4px 0 0', fontSize: 13 }}>
          基于菜品四象限分析、毛利率、销量趋势与库存数据，AI生成最优菜品调整方案
        </p>
      </div>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'recommend',
            label: (
              <Space><ThunderboltOutlined />AI推荐方案</Space>
            ),
            children: renderRecommendTab(),
          },
          {
            key: 'history',
            label: (
              <Space><HistoryOutlined />历史记录</Space>
            ),
            children: renderHistoryTab(),
          },
        ]}
      />
    </div>
  );
}
