/**
 * BOM配方编辑器页
 * 域D 供应链 · BOM管理
 *
 * 布局：左侧菜品选择（320px）+ 右侧BOM编辑区
 *
 * 功能：
 * 1. 左侧：搜索菜品 + 列表，点击选中后右侧加载BOM
 * 2. 右侧顶部：菜品名/版本号/新建版本按钮 + 产出量 + 版本备注
 * 3. 食材明细可编辑表格：行成本实时计算
 * 4. 底部汇总：总成本/每份成本 + 重新计算 + 保存
 * 5. 成本分解饼图（echarts，可折叠）
 * 6. BOM版本历史（Collapse底部）
 *
 * API（tx-supply :8006）：
 * GET  /api/v1/supply/boms?dish_id=
 * POST /api/v1/supply/boms
 * PUT  /api/v1/supply/boms/{id}
 * DELETE /api/v1/supply/boms/{id}
 * POST /api/v1/supply/boms/{id}/calculate-cost
 * GET  /api/v1/supply/boms/{id}/cost-breakdown
 *
 * 成本：分存储，UI ÷100显示，保留2位小数
 * 技术栈：antd 5.x + echarts-for-react + React 18 TypeScript strict
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  Collapse,
  ConfigProvider,
  Divider,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  message,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  CalculatorOutlined,
  DeleteOutlined,
  HistoryOutlined,
  PieChartOutlined,
  PlusOutlined,
  SaveOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import ReactECharts from 'echarts-for-react';
import { txFetch } from '../../../api';

const { Title, Text } = Typography;
const { Panel } = Collapse;
const { Option } = Select;

// ─── Design Tokens ──────────────────────────────────────────────────────────

const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_WARNING = '#BA7517';
const TX_INFO = '#185FA5';
const TX_BG_SECONDARY = '#F8F7F5';
const TX_BORDER = '#E8E6E1';
const TX_NAVY = '#1E2A3A';
const TX_TEXT_PRIMARY = '#2C2C2A';
const TX_TEXT_SECONDARY = '#5F5E5A';

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

interface Dish {
  id: string;
  name: string;
  code?: string;
  category?: string;
}

interface BomItem {
  id?: string;
  /** 本地临时key，用于表格rowKey */
  _key: string;
  ingredient_name: string;
  ingredient_code: string;
  quantity: number;
  unit: string;
  unit_cost_fen: number;
  loss_rate: number;
  is_semi_product: boolean;
  semi_product_bom_id?: string;
  /** 行成本（元），前端实时计算 */
  line_cost: number;
}

interface Bom {
  id: string;
  dish_id: string;
  dish_name?: string;
  version: number;
  version_note?: string;
  yield_quantity: number;
  yield_unit: string;
  total_cost_fen: number;
  is_active: boolean;
  created_at: string;
  items: BomItem[];
}

interface CostBreakdownItem {
  name: string;
  cost_fen: number;
  percentage: number;
}

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

const fenToYuan = (fen: number): string => (fen / 100).toFixed(2);
const yuanToFen = (yuan: number): number => Math.round(yuan * 100);

/** 实时计算行成本（元）= 数量 × 单价(元) × (1 + 损耗率/100) */
const calcLineCost = (qty: number, unitCostFen: number, lossRate: number): number => {
  return (qty * (unitCostFen / 100) * (1 + lossRate / 100));
};

const genKey = (): string => `_local_${Date.now()}_${Math.random().toString(36).slice(2)}`;

// ─── BomEditorPage ───────────────────────────────────────────────────────────

const BomEditorPage: React.FC = () => {
  // ── 左侧：菜品列表 ──
  const [dishes, setDishes] = useState<Dish[]>([]);
  const [dishSearch, setDishSearch] = useState('');
  const [dishLoading, setDishLoading] = useState(false);
  const [selectedDish, setSelectedDish] = useState<Dish | null>(null);

  // ── 右侧：BOM ──
  const [bomList, setBomList] = useState<Bom[]>([]);
  const [activeBom, setActiveBom] = useState<Bom | null>(null);
  const [bomLoading, setBomLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [recalculating, setRecalculating] = useState(false);

  // 编辑状态
  const [yieldQty, setYieldQty] = useState<number>(1);
  const [yieldUnit, setYieldUnit] = useState<string>('份');
  const [versionNote, setVersionNote] = useState<string>('');
  const [items, setItems] = useState<BomItem[]>([]);

  // 成本分解
  const [breakdown, setBreakdown] = useState<CostBreakdownItem[]>([]);
  const [breakdownLoading, setBreakdownLoading] = useState(false);

  // 新建BOM版本 Modal
  const [newVersionModal, setNewVersionModal] = useState(false);
  const [newVersionForm] = Form.useForm();

  // ── 初始加载菜品列表 ──
  const loadDishes = useCallback(async (search: string) => {
    setDishLoading(true);
    try {
      const params = search
        ? `?search=${encodeURIComponent(search)}&size=50`
        : '?size=50';
      const data = await txFetch<{ items: Dish[]; total: number }>(
        `/api/v1/menu/dishes${params}`
      );
      setDishes(data.items || []);
    } catch (err) {
      // 离线/开发时回退到 mock 数据
      setDishes([
        { id: 'dish_001', name: '红烧肉', code: 'D001', category: '热菜' },
        { id: 'dish_002', name: '清蒸鱼', code: 'D002', category: '海鲜' },
        { id: 'dish_003', name: '夫妻肺片', code: 'D003', category: '凉菜' },
        { id: 'dish_004', name: '番茄鸡蛋汤', code: 'D004', category: '汤品' },
        { id: 'dish_005', name: '麻婆豆腐', code: 'D005', category: '热菜' },
      ].filter(d =>
        !search ||
        d.name.includes(search) ||
        (d.code || '').includes(search)
      ));
    } finally {
      setDishLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDishes('');
  }, [loadDishes]);

  // 搜索防抖
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleDishSearch = (v: string) => {
    setDishSearch(v);
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => loadDishes(v), 400);
  };

  // ── 选中菜品 → 加载BOM ──
  const handleSelectDish = useCallback(async (dish: Dish) => {
    setSelectedDish(dish);
    setBomLoading(true);
    setActiveBom(null);
    setItems([]);
    setBreakdown([]);
    try {
      const data = await txFetch<{ items: Bom[]; total: number }>(
        `/api/v1/supply/boms?dish_id=${encodeURIComponent(dish.id)}`
      );
      const list: Bom[] = (data.items || []).map(b => ({
        ...b,
        items: (b.items || []).map(it => ({
          ...it,
          _key: it.id || genKey(),
          line_cost: calcLineCost(it.quantity, it.unit_cost_fen, it.loss_rate),
        })),
      }));
      setBomList(list);
      // 默认选中最新激活版本
      const active = list.find(b => b.is_active) || list[0] || null;
      if (active) {
        setActiveBom(active);
        setYieldQty(active.yield_quantity);
        setYieldUnit(active.yield_unit);
        setVersionNote(active.version_note || '');
        setItems(active.items);
      }
    } catch {
      setBomList([]);
    } finally {
      setBomLoading(false);
    }
  }, []);

  // ── 切换历史版本 ──
  const handleSwitchVersion = (bom: Bom) => {
    setActiveBom(bom);
    setYieldQty(bom.yield_quantity);
    setYieldUnit(bom.yield_unit);
    setVersionNote(bom.version_note || '');
    setItems(
      bom.items.map(it => ({
        ...it,
        _key: it.id || genKey(),
        line_cost: calcLineCost(it.quantity, it.unit_cost_fen, it.loss_rate),
      }))
    );
    setBreakdown([]);
  };

  // ── 添加食材行 ──
  const handleAddItem = () => {
    const newItem: BomItem = {
      _key: genKey(),
      ingredient_name: '',
      ingredient_code: '',
      quantity: 1,
      unit: '克',
      unit_cost_fen: 0,
      loss_rate: 0,
      is_semi_product: false,
      line_cost: 0,
    };
    setItems(prev => [...prev, newItem]);
  };

  // ── 删除食材行 ──
  const handleDeleteItem = (key: string) => {
    setItems(prev => prev.filter(it => it._key !== key));
  };

  // ── 更新食材行字段 ──
  const handleItemChange = (key: string, field: keyof BomItem, value: unknown) => {
    setItems(prev =>
      prev.map(it => {
        if (it._key !== key) return it;
        const updated = { ...it, [field]: value } as BomItem;
        updated.line_cost = calcLineCost(
          updated.quantity,
          updated.unit_cost_fen,
          updated.loss_rate
        );
        return updated;
      })
    );
  };

  // ── 汇总成本 ──
  const totalCostYuan = items.reduce((s, it) => s + it.line_cost, 0);
  const perServingCost = yieldQty > 0 ? totalCostYuan / yieldQty : 0;

  // ── 保存BOM ──
  const handleSave = async () => {
    if (!activeBom) return;
    setSaving(true);
    try {
      const payload = {
        yield_quantity: yieldQty,
        yield_unit: yieldUnit,
        version_note: versionNote,
        items: items.map(({ _key: _k, line_cost: _lc, ...rest }) => ({
          ...rest,
          unit_cost_fen: rest.unit_cost_fen,
        })),
      };
      await txFetch(`/api/v1/supply/boms/${activeBom.id}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      message.success('BOM已保存');
      // 刷新列表
      if (selectedDish) handleSelectDish(selectedDish);
    } catch (err) {
      message.error(`保存失败：${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setSaving(false);
    }
  };

  // ── 重新计算成本（调用后端API） ──
  const handleRecalculate = async () => {
    if (!activeBom) return;
    setRecalculating(true);
    try {
      const result = await txFetch<{ total_cost_fen: number }>(
        `/api/v1/supply/boms/${activeBom.id}/calculate-cost`,
        { method: 'POST' }
      );
      message.success(`重算完成，总成本：¥${fenToYuan(result.total_cost_fen)}`);
      if (selectedDish) handleSelectDish(selectedDish);
    } catch (err) {
      message.error(`重算失败：${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setRecalculating(false);
    }
  };

  // ── 成本分解 ──
  const handleLoadBreakdown = async () => {
    if (!activeBom) return;
    setBreakdownLoading(true);
    try {
      const data = await txFetch<{ items: CostBreakdownItem[] }>(
        `/api/v1/supply/boms/${activeBom.id}/cost-breakdown`
      );
      setBreakdown(data.items || []);
    } catch {
      // 本地生成分解（回退）
      const total = items.reduce((s, it) => s + it.unit_cost_fen * it.quantity, 0);
      setBreakdown(
        items
          .filter(it => it.ingredient_name)
          .map(it => ({
            name: it.ingredient_name || '未命名',
            cost_fen: Math.round(it.unit_cost_fen * it.quantity * (1 + it.loss_rate / 100)),
            percentage: total > 0
              ? Math.round((it.unit_cost_fen * it.quantity / total) * 100)
              : 0,
          }))
      );
    } finally {
      setBreakdownLoading(false);
    }
  };

  // ── 新建BOM版本 ──
  const handleCreateVersion = async (values: { version_note: string; yield_quantity: number; yield_unit: string }) => {
    if (!selectedDish) return;
    try {
      await txFetch('/api/v1/supply/boms', {
        method: 'POST',
        body: JSON.stringify({
          dish_id: selectedDish.id,
          version_note: values.version_note,
          yield_quantity: values.yield_quantity,
          yield_unit: values.yield_unit,
          items: [],
        }),
      });
      message.success('新版本已创建');
      setNewVersionModal(false);
      newVersionForm.resetFields();
      handleSelectDish(selectedDish);
    } catch (err) {
      message.error(`创建失败：${err instanceof Error ? err.message : '未知错误'}`);
    }
  };

  // ── ECharts饼图配置 ──
  const pieOption = {
    tooltip: { trigger: 'item', formatter: '{b}: ¥{c}（{d}%）' },
    legend: { orient: 'vertical', left: 'left', textStyle: { color: TX_TEXT_SECONDARY } },
    color: [TX_PRIMARY, TX_SUCCESS, TX_INFO, TX_WARNING, '#9B59B6', '#1ABC9C', '#E67E22', '#3498DB'],
    series: [
      {
        name: '成本分解',
        type: 'pie',
        radius: ['40%', '70%'],
        avoidLabelOverlap: false,
        itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
        label: { show: false, position: 'center' },
        emphasis: {
          label: { show: true, fontSize: 14, fontWeight: 'bold' },
        },
        labelLine: { show: false },
        data: breakdown.map(b => ({
          value: (b.cost_fen / 100).toFixed(2),
          name: b.name,
        })),
      },
    ],
  };

  // ── 食材表格列 ──
  const itemColumns: ColumnsType<BomItem> = [
    {
      title: '食材编码',
      dataIndex: 'ingredient_code',
      width: 110,
      render: (v: string, record) => (
        <Input
          size="small"
          value={v}
          placeholder="编码"
          onChange={e => handleItemChange(record._key, 'ingredient_code', e.target.value)}
          style={{ borderColor: TX_BORDER }}
        />
      ),
    },
    {
      title: '食材名',
      dataIndex: 'ingredient_name',
      width: 140,
      render: (v: string, record) => (
        <Input
          size="small"
          value={v}
          placeholder="食材名称"
          onChange={e => handleItemChange(record._key, 'ingredient_name', e.target.value)}
          style={{ borderColor: TX_BORDER }}
        />
      ),
    },
    {
      title: '数量',
      dataIndex: 'quantity',
      width: 90,
      render: (v: number, record) => (
        <InputNumber
          size="small"
          value={v}
          min={0}
          precision={3}
          style={{ width: '100%' }}
          onChange={val => handleItemChange(record._key, 'quantity', val ?? 0)}
        />
      ),
    },
    {
      title: '单位',
      dataIndex: 'unit',
      width: 80,
      render: (v: string, record) => (
        <Select
          size="small"
          value={v}
          style={{ width: '100%' }}
          onChange={val => handleItemChange(record._key, 'unit', val)}
        >
          {['克', '千克', '斤', '升', '毫升', '个', '条', '片', '份'].map(u => (
            <Option key={u} value={u}>{u}</Option>
          ))}
        </Select>
      ),
    },
    {
      title: '单价(元)',
      dataIndex: 'unit_cost_fen',
      width: 100,
      render: (v: number, record) => (
        <InputNumber
          size="small"
          value={v / 100}
          min={0}
          precision={2}
          prefix="¥"
          style={{ width: '100%' }}
          onChange={val => handleItemChange(record._key, 'unit_cost_fen', yuanToFen(val ?? 0))}
        />
      ),
    },
    {
      title: '损耗率%',
      dataIndex: 'loss_rate',
      width: 90,
      render: (v: number, record) => (
        <InputNumber
          size="small"
          value={v}
          min={0}
          max={100}
          precision={1}
          suffix="%"
          style={{ width: '100%' }}
          onChange={val => handleItemChange(record._key, 'loss_rate', val ?? 0)}
        />
      ),
    },
    {
      title: '行成本(元)',
      dataIndex: 'line_cost',
      width: 100,
      render: (v: number) => (
        <Text style={{ color: TX_TEXT_PRIMARY, fontWeight: 500 }}>
          ¥{v.toFixed(2)}
        </Text>
      ),
    },
    {
      title: '半成品',
      dataIndex: 'is_semi_product',
      width: 80,
      render: (v: boolean, record) => (
        <Switch
          size="small"
          checked={v}
          onChange={checked => handleItemChange(record._key, 'is_semi_product', checked)}
        />
      ),
    },
    {
      title: '半成品BOM',
      dataIndex: 'semi_product_bom_id',
      width: 130,
      render: (v: string | undefined, record) =>
        record.is_semi_product ? (
          <Input
            size="small"
            value={v || ''}
            placeholder="BOM ID"
            onChange={e => handleItemChange(record._key, 'semi_product_bom_id', e.target.value)}
          />
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>—</Text>
        ),
    },
    {
      title: '操作',
      key: 'action',
      width: 60,
      render: (_: unknown, record) => (
        <Popconfirm
          title="确认删除该行？"
          onConfirm={() => handleDeleteItem(record._key)}
          okText="删除"
          cancelText="取消"
          okButtonProps={{ danger: true }}
        >
          <Button type="text" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ];

  // ── BOM版本历史列 ──
  const historyColumns: ColumnsType<Bom> = [
    {
      title: '版本',
      dataIndex: 'version',
      width: 70,
      render: (v: number, record) => (
        <Space>
          <Tag color={record.is_active ? TX_PRIMARY : undefined} style={{ margin: 0 }}>
            v{v}
          </Tag>
          {record.is_active && <Badge status="processing" color={TX_PRIMARY} />}
        </Space>
      ),
    },
    {
      title: '备注',
      dataIndex: 'version_note',
      ellipsis: true,
      render: (v: string) => <Text style={{ fontSize: 12 }}>{v || '—'}</Text>,
    },
    {
      title: '总成本',
      dataIndex: 'total_cost_fen',
      width: 100,
      render: (v: number) => <Text style={{ fontSize: 12 }}>¥{fenToYuan(v)}</Text>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 130,
      render: (v: string) => (
        <Text type="secondary" style={{ fontSize: 11 }}>
          {v ? new Date(v).toLocaleString('zh-CN', { dateStyle: 'short', timeStyle: 'short' }) : '—'}
        </Text>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_: unknown, record) => (
        <Button
          type="link"
          size="small"
          style={{ padding: 0, color: TX_INFO }}
          onClick={() => handleSwitchVersion(record)}
        >
          查看
        </Button>
      ),
    },
  ];

  // ── 是否当前版本为只读（历史版本只读） ──
  const isReadOnly = activeBom ? !activeBom.is_active : false;

  // ─────────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────────

  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: TX_PRIMARY,
          colorSuccess: TX_SUCCESS,
          colorWarning: TX_WARNING,
          colorInfo: TX_INFO,
          colorTextBase: TX_TEXT_PRIMARY,
          colorBgBase: '#FFFFFF',
          borderRadius: 6,
          fontSize: 14,
        },
        components: {
          Table: { headerBg: TX_BG_SECONDARY },
        },
      }}
    >
      <div style={{ display: 'flex', height: '100%', minHeight: 'calc(100vh - 64px)', background: TX_BG_SECONDARY }}>

        {/* ── 左侧：菜品选择 ── */}
        <div
          style={{
            width: 320,
            flexShrink: 0,
            background: '#fff',
            borderRight: `1px solid ${TX_BORDER}`,
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {/* 标题 */}
          <div style={{ padding: '16px 16px 8px', borderBottom: `1px solid ${TX_BORDER}` }}>
            <Title level={5} style={{ margin: 0, color: TX_NAVY }}>BOM配方编辑器</Title>
            <Text type="secondary" style={{ fontSize: 12 }}>选择菜品以编辑BOM配方</Text>
          </div>

          {/* 搜索框 */}
          <div style={{ padding: '12px 16px 8px' }}>
            <Input
              allowClear
              prefix={<SearchOutlined style={{ color: TX_TEXT_SECONDARY }} />}
              placeholder="搜索菜品名或编码"
              value={dishSearch}
              onChange={e => handleDishSearch(e.target.value)}
              style={{ borderColor: TX_BORDER }}
            />
          </div>

          {/* 菜品列表 */}
          <div style={{ flex: 1, overflow: 'auto' }}>
            <Spin spinning={dishLoading} size="small">
              {dishes.length === 0 ? (
                <Empty description="暂无菜品" style={{ marginTop: 40 }} image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : (
                <List
                  dataSource={dishes}
                  renderItem={dish => (
                    <List.Item
                      key={dish.id}
                      onClick={() => handleSelectDish(dish)}
                      style={{
                        padding: '10px 16px',
                        cursor: 'pointer',
                        background: selectedDish?.id === dish.id ? '#FFF3ED' : undefined,
                        borderLeft: selectedDish?.id === dish.id ? `3px solid ${TX_PRIMARY}` : '3px solid transparent',
                        transition: 'all 0.15s',
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: selectedDish?.id === dish.id ? 600 : 400, color: TX_TEXT_PRIMARY }}>
                          {dish.name}
                        </div>
                        <div style={{ fontSize: 12, color: TX_TEXT_SECONDARY, marginTop: 2 }}>
                          {dish.code && <Tag style={{ fontSize: 11, padding: '0 4px' }}>{dish.code}</Tag>}
                          {dish.category && <Text type="secondary" style={{ fontSize: 11 }}>{dish.category}</Text>}
                        </div>
                      </div>
                    </List.Item>
                  )}
                />
              )}
            </Spin>
          </div>
        </div>

        {/* ── 右侧：BOM编辑区 ── */}
        <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
          {!selectedDish ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '60vh' }}>
              <Empty
                description={<Text type="secondary">请从左侧选择一个菜品</Text>}
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            </div>
          ) : (
            <Spin spinning={bomLoading}>
              <Space direction="vertical" style={{ width: '100%' }} size={16}>

                {/* 顶部信息行 */}
                <Card
                  bodyStyle={{ padding: '16px 20px' }}
                  style={{ boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}
                >
                  <Row align="middle" gutter={[16, 12]}>
                    <Col flex="auto">
                      <Space align="center" wrap>
                        <Title level={4} style={{ margin: 0, color: TX_NAVY }}>
                          {selectedDish.name}
                        </Title>
                        {activeBom && (
                          <Tag color={TX_PRIMARY} style={{ fontSize: 13 }}>
                            v{activeBom.version}
                          </Tag>
                        )}
                        {isReadOnly && (
                          <Tag color="default">历史版本（只读）</Tag>
                        )}
                      </Space>
                    </Col>
                    <Col>
                      <Button
                        size="small"
                        icon={<PlusOutlined />}
                        onClick={() => setNewVersionModal(true)}
                        style={{ borderColor: TX_PRIMARY, color: TX_PRIMARY }}
                      >
                        新建BOM版本
                      </Button>
                    </Col>
                  </Row>

                  <Divider style={{ margin: '12px 0' }} />

                  <Row gutter={[16, 8]} align="middle">
                    <Col>
                      <Space>
                        <Text type="secondary">产出量：</Text>
                        <InputNumber
                          size="small"
                          value={yieldQty}
                          min={0.01}
                          precision={2}
                          disabled={isReadOnly}
                          onChange={val => setYieldQty(val ?? 1)}
                          style={{ width: 80 }}
                        />
                        <Select
                          size="small"
                          value={yieldUnit}
                          disabled={isReadOnly}
                          onChange={setYieldUnit}
                          style={{ width: 70 }}
                        >
                          {['份', '人份', '克', '千克', '升'].map(u => (
                            <Option key={u} value={u}>{u}</Option>
                          ))}
                        </Select>
                      </Space>
                    </Col>
                    <Col flex="auto">
                      <Space>
                        <Text type="secondary">版本备注：</Text>
                        <Input
                          size="small"
                          value={versionNote}
                          disabled={isReadOnly}
                          placeholder="如：标准配方 2026Q1"
                          maxLength={100}
                          onChange={e => setVersionNote(e.target.value)}
                          style={{ width: 280, borderColor: TX_BORDER }}
                        />
                      </Space>
                    </Col>
                  </Row>
                </Card>

                {/* 食材明细表格 */}
                <Card
                  title={
                    <Space>
                      <span style={{ color: TX_NAVY, fontWeight: 600 }}>食材明细</span>
                      <Tag>{items.length} 行</Tag>
                    </Space>
                  }
                  extra={
                    !isReadOnly && (
                      <Button
                        type="dashed"
                        size="small"
                        icon={<PlusOutlined />}
                        onClick={handleAddItem}
                        style={{ borderColor: TX_PRIMARY, color: TX_PRIMARY }}
                      >
                        添加食材
                      </Button>
                    )
                  }
                  bodyStyle={{ padding: 0 }}
                  style={{ boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}
                >
                  <Table<BomItem>
                    columns={itemColumns}
                    dataSource={items}
                    rowKey="_key"
                    pagination={false}
                    scroll={{ x: 1000 }}
                    size="small"
                    locale={{ emptyText: <Empty description={'暂无食材，点击"添加食材"开始'} image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
                    footer={() =>
                      !isReadOnly ? (
                        <Button
                          type="dashed"
                          block
                          icon={<PlusOutlined />}
                          onClick={handleAddItem}
                          style={{ borderColor: TX_BORDER, color: TX_TEXT_SECONDARY }}
                        >
                          添加食材
                        </Button>
                      ) : null
                    }
                  />
                </Card>

                {/* 底部汇总栏 */}
                <Card
                  bodyStyle={{ padding: '16px 20px' }}
                  style={{
                    background: TX_NAVY,
                    boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
                  }}
                >
                  <Row align="middle" gutter={[24, 12]}>
                    <Col>
                      <div style={{ color: 'rgba(255,255,255,0.6)', fontSize: 12, marginBottom: 2 }}>总成本</div>
                      <div style={{ color: TX_PRIMARY, fontSize: 28, fontWeight: 700, lineHeight: 1 }}>
                        ¥{totalCostYuan.toFixed(2)}
                      </div>
                    </Col>
                    <Col>
                      <div style={{ color: 'rgba(255,255,255,0.6)', fontSize: 12, marginBottom: 2 }}>每份成本</div>
                      <div style={{ color: '#fff', fontSize: 22, fontWeight: 600, lineHeight: 1 }}>
                        ¥{perServingCost.toFixed(2)}
                      </div>
                    </Col>
                    <Col flex="auto" />
                    <Col>
                      <Space>
                        <Tooltip title="调用服务端重算成本（含最新采购价）">
                          <Button
                            icon={<CalculatorOutlined />}
                            loading={recalculating}
                            onClick={handleRecalculate}
                            disabled={!activeBom}
                            style={{ background: 'rgba(255,255,255,0.1)', borderColor: 'rgba(255,255,255,0.3)', color: '#fff' }}
                          >
                            重新计算
                          </Button>
                        </Tooltip>
                        {!isReadOnly && (
                          <Button
                            type="primary"
                            icon={<SaveOutlined />}
                            loading={saving}
                            onClick={handleSave}
                            disabled={!activeBom}
                          >
                            保存BOM
                          </Button>
                        )}
                      </Space>
                    </Col>
                  </Row>
                </Card>

                {/* 成本分解饼图（可折叠） */}
                <Collapse
                  ghost
                  style={{ background: '#fff', borderRadius: 6, border: `1px solid ${TX_BORDER}` }}
                  onChange={keys => {
                    if (keys.includes('breakdown') && breakdown.length === 0) {
                      handleLoadBreakdown();
                    }
                  }}
                >
                  <Panel
                    key="breakdown"
                    header={
                      <Space>
                        <PieChartOutlined style={{ color: TX_PRIMARY }} />
                        <span style={{ fontWeight: 600, color: TX_NAVY }}>成本分解</span>
                        <Text type="secondary" style={{ fontSize: 12 }}>展开查看各食材成本占比</Text>
                      </Space>
                    }
                  >
                    <Spin spinning={breakdownLoading}>
                      {breakdown.length === 0 ? (
                        <Empty description="暂无分解数据" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: '20px 0' }} />
                      ) : (
                        <Row gutter={24} align="middle">
                          <Col xs={24} md={12}>
                            <ReactECharts
                              option={pieOption}
                              style={{ height: 280 }}
                              notMerge
                            />
                          </Col>
                          <Col xs={24} md={12}>
                            <Space direction="vertical" style={{ width: '100%' }}>
                              {breakdown.map((item, idx) => (
                                <div key={item.name} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                  <div style={{
                                    width: 10, height: 10, borderRadius: '50%', flexShrink: 0,
                                    background: [TX_PRIMARY, TX_SUCCESS, TX_INFO, TX_WARNING, '#9B59B6', '#1ABC9C', '#E67E22', '#3498DB'][idx % 8],
                                  }} />
                                  <Text style={{ flex: 1, fontSize: 13 }}>{item.name}</Text>
                                  <Text style={{ fontSize: 13, fontWeight: 500 }}>¥{fenToYuan(item.cost_fen)}</Text>
                                  <Tag style={{ margin: 0 }}>{item.percentage}%</Tag>
                                </div>
                              ))}
                            </Space>
                          </Col>
                        </Row>
                      )}
                    </Spin>
                  </Panel>
                </Collapse>

                {/* BOM版本历史 */}
                <Collapse
                  ghost
                  style={{ background: '#fff', borderRadius: 6, border: `1px solid ${TX_BORDER}` }}
                >
                  <Panel
                    key="history"
                    header={
                      <Space>
                        <HistoryOutlined style={{ color: TX_INFO }} />
                        <span style={{ fontWeight: 600, color: TX_NAVY }}>版本历史</span>
                        <Tag color="blue">{bomList.length} 个版本</Tag>
                      </Space>
                    }
                  >
                    {bomList.length === 0 ? (
                      <Empty description="暂无版本记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                    ) : (
                      <Table<Bom>
                        columns={historyColumns}
                        dataSource={bomList}
                        rowKey="id"
                        pagination={false}
                        size="small"
                        rowClassName={record =>
                          activeBom?.id === record.id ? 'ant-table-row-selected' : ''
                        }
                      />
                    )}
                  </Panel>
                </Collapse>

              </Space>
            </Spin>
          )}
        </div>
      </div>

      {/* 新建BOM版本 Modal */}
      <Modal
        title={
          <Space>
            <PlusOutlined style={{ color: TX_PRIMARY }} />
            <span>新建BOM版本</span>
            {selectedDish && <Tag color={TX_PRIMARY}>{selectedDish.name}</Tag>}
          </Space>
        }
        open={newVersionModal}
        onCancel={() => { setNewVersionModal(false); newVersionForm.resetFields(); }}
        footer={null}
        destroyOnClose
      >
        <Form
          form={newVersionForm}
          layout="vertical"
          initialValues={{ yield_quantity: 1, yield_unit: '份' }}
          onFinish={handleCreateVersion}
          style={{ marginTop: 16 }}
        >
          <Form.Item
            name="yield_quantity"
            label="产出量"
            rules={[{ required: true, message: '请输入产出量' }]}
          >
            <InputNumber min={0.01} precision={2} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="yield_unit"
            label="产出单位"
            rules={[{ required: true, message: '请选择单位' }]}
          >
            <Select>
              {['份', '人份', '克', '千克', '升'].map(u => (
                <Option key={u} value={u}>{u}</Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="version_note" label="版本备注">
            <Input placeholder="如：标准配方 2026Q1" maxLength={100} />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0, textAlign: 'right' }}>
            <Space>
              <Button onClick={() => { setNewVersionModal(false); newVersionForm.resetFields(); }}>
                取消
              </Button>
              <Button type="primary" htmlType="submit">
                创建
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </ConfigProvider>
  );
};

export default BomEditorPage;
export { BomEditorPage };
