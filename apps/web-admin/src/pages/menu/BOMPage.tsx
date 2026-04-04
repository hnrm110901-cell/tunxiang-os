/**
 * BOMPage -- 菜品BOM配方管理
 * 域B 菜品菜单 · 配方管理
 *
 * Tab1: 配方列表（ProTable + Drawer编辑）
 * Tab2: 成本分析（SVG饼图 + 柱状图 + 低毛利预警）
 * Tab3: 成本模拟（食材涨价影响模拟器）
 *
 * API: tx-menu :8002，try/catch 降级 Mock
 * 金额: 分存储，UI ÷100 显示
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ProTable,
  ActionType,
  ProColumns,
} from '@ant-design/pro-components';
import {
  Button,
  Card,
  Drawer,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Popconfirm,
  Select,
  Space,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  Descriptions,
  Divider,
  Empty,
  Statistic,
  Row,
  Col,
  Alert,
  Table,
} from 'antd';
import {
  PlusOutlined,
  EditOutlined,
  CopyOutlined,
  DeleteOutlined,
  EyeOutlined,
  SaveOutlined,
  ExperimentOutlined,
  WarningOutlined,
  PieChartOutlined,
  BarChartOutlined,
  MinusCircleOutlined,
  CalculatorOutlined,
} from '@ant-design/icons';
import { txFetch } from '../../api';

const { Text, Title } = Typography;

// ─── 常量 ──────────────────────────────────────────────────────

const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_WARNING = '#BA7517';
const TX_DANGER = '#CF1322';

// ─── 类型 ──────────────────────────────────────────────────────

interface BomIngredient {
  id: string;
  ingredient_id: string;
  name: string;
  spec: string;
  quantity: number;
  unit: string;
  unit_price_fen: number;
  subtotal_fen: number;
}

interface BomRecord {
  id: string;
  dish_id: string;
  dish_name: string;
  category: string;
  ingredient_count: number;
  total_cost_fen: number;
  sell_price_fen: number;
  margin_rate: number; // 0~100
  updated_at: string;
  ingredients: BomIngredient[];
}

interface IngredientOption {
  id: string;
  name: string;
  spec: string;
  unit: string;
  unit_price_fen: number;
}

interface DishOption {
  id: string;
  name: string;
  category: string;
  sell_price_fen: number;
}

// ─── 空数据 fallback（API 不可用时的降级默认值） ─────────────────────────────

const EMPTY_BOM_LIST: BomRecord[] = [];
const EMPTY_INGREDIENT_LIST: IngredientOption[] = [];
const EMPTY_DISH_LIST: DishOption[] = [];

// ─── 工具函数 ──────────────────────────────────────────────────

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function marginColor(rate: number): string {
  if (rate >= 60) return TX_SUCCESS;
  if (rate >= 40) return TX_WARNING;
  return TX_DANGER;
}

function marginTag(rate: number) {
  const color = rate >= 60 ? 'green' : rate >= 40 ? 'orange' : 'red';
  return <Tag color={color}>{rate.toFixed(1)}%</Tag>;
}

let idCounter = 100;
function genId(prefix: string): string {
  idCounter += 1;
  return `${prefix}_${idCounter}`;
}

// ─── API 层（txFetch + try/catch 空数据 fallback）──────────────

interface BomListResponse { items: BomRecord[]; total: number; }
interface IngredientListResponse { items: IngredientOption[]; total: number; }
interface DishListResponse { items: DishOption[]; total: number; }

async function fetchBomList(page = 1): Promise<BomRecord[]> {
  try {
    const res = await txFetch<BomListResponse>(`/api/v1/supply/recipes?page=${page}`);
    return res.data?.items ?? EMPTY_BOM_LIST;
  } catch (err) {
    console.error('[BOMPage] fetchBomList 失败:', err);
    return EMPTY_BOM_LIST;
  }
}

async function fetchBomDetail(id: string): Promise<BomRecord | null> {
  try {
    const res = await txFetch<BomRecord>(`/api/v1/supply/recipes/${id}`);
    return res.data ?? null;
  } catch (err) {
    console.error('[BOMPage] fetchBomDetail 失败:', err);
    return null;
  }
}

async function fetchIngredients(): Promise<IngredientOption[]> {
  try {
    const res = await txFetch<IngredientListResponse>('/api/v1/menu/ingredients?page=1&size=500');
    return res.data?.items ?? EMPTY_INGREDIENT_LIST;
  } catch (err) {
    console.error('[BOMPage] fetchIngredients 失败:', err);
    return EMPTY_INGREDIENT_LIST;
  }
}

async function fetchDishes(): Promise<DishOption[]> {
  try {
    const res = await txFetch<DishListResponse>('/api/v1/menu/dishes?page=1&size=200');
    return res.data?.items ?? EMPTY_DISH_LIST;
  } catch (err) {
    console.error('[BOMPage] fetchDishes 失败:', err);
    return EMPTY_DISH_LIST;
  }
}

async function createBom(payload: { dish_id: string; ingredients: BomIngredient[] }): Promise<BomRecord | null> {
  try {
    const res = await txFetch<BomRecord>('/api/v1/supply/recipes', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    return res.data ?? null;
  } catch (err) {
    console.error('[BOMPage] createBom 失败:', err);
    throw err;
  }
}

async function saveBom(bom: BomRecord): Promise<boolean> {
  try {
    await txFetch<BomRecord>(`/api/v1/supply/recipes/${bom.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ ingredients: bom.ingredients }),
    });
    return true;
  } catch (err) {
    console.error('[BOMPage] saveBom 失败:', err);
    throw err;
  }
}

async function deleteBom(id: string): Promise<boolean> {
  try {
    await txFetch<unknown>(`/api/v1/supply/recipes/${id}`, { method: 'DELETE' });
    return true;
  } catch (err) {
    console.error('[BOMPage] deleteBom 失败:', err);
    throw err;
  }
}

async function calculateBomCost(recipeId: string, targetQty: number): Promise<{ total_cost_fen: number; margin_rate: number } | null> {
  try {
    const res = await txFetch<{ total_cost_fen: number; margin_rate: number }>(
      '/api/v1/supply/recipes/calculate',
      {
        method: 'POST',
        body: JSON.stringify({ recipe_id: recipeId, target_qty: targetQty }),
      },
    );
    return res.data ?? null;
  } catch (err) {
    console.error('[BOMPage] calculateBomCost 失败:', err);
    return null;
  }
}

// ─── Tab1: 配方列表 ──────────────────────────────────────────────

function RecipeListTab() {
  const tableRef = useRef<ActionType>();
  const [bomList, setBomList] = useState<BomRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerMode, setDrawerMode] = useState<'view' | 'edit' | 'create'>('view');
  const [currentBom, setCurrentBom] = useState<BomRecord | null>(null);
  const [editIngredients, setEditIngredients] = useState<BomIngredient[]>([]);
  const [ingredientOptions, setIngredientOptions] = useState<IngredientOption[]>([]);
  const [dishOptions, setDishOptions] = useState<DishOption[]>([]);
  const [selectedDishId, setSelectedDishId] = useState<string>('');
  const [saving, setSaving] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    const [boms, ings, dishes] = await Promise.all([
      fetchBomList(),
      fetchIngredients(),
      fetchDishes(),
    ]);
    setBomList(boms);
    setIngredientOptions(ings);
    setDishOptions(dishes);
    setLoading(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const openDrawer = (mode: 'view' | 'edit' | 'create', bom?: BomRecord) => {
    setDrawerMode(mode);
    if (bom) {
      setCurrentBom({ ...bom });
      setEditIngredients(bom.ingredients.map((i) => ({ ...i })));
      setSelectedDishId(bom.dish_id);
    } else {
      setCurrentBom(null);
      setEditIngredients([]);
      setSelectedDishId('');
    }
    setDrawerOpen(true);
  };

  const handleCopy = (bom: BomRecord) => {
    const newBom: BomRecord = {
      ...bom,
      id: genId('bom'),
      dish_name: `${bom.dish_name}(副本)`,
      ingredients: bom.ingredients.map((i) => ({ ...i, id: genId('line') })),
      updated_at: new Date().toISOString().slice(0, 16).replace('T', ' '),
    };
    setBomList((prev) => [newBom, ...prev]);
    message.success('配方已复制');
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteBom(id);
      setBomList((prev) => prev.filter((b) => b.id !== id));
      message.success('配方已删除');
    } catch {
      message.error('删除失败，请重试');
    }
  };

  // ─── Drawer 内联编辑逻辑 ─────────────────────────

  const addIngredientRow = () => {
    setEditIngredients((prev) => [
      ...prev,
      {
        id: genId('line'),
        ingredient_id: '',
        name: '',
        spec: '',
        quantity: 0,
        unit: '',
        unit_price_fen: 0,
        subtotal_fen: 0,
      },
    ]);
  };

  const removeIngredientRow = (id: string) => {
    setEditIngredients((prev) => prev.filter((i) => i.id !== id));
  };

  const updateIngredientRow = (id: string, field: keyof BomIngredient, value: string | number) => {
    setEditIngredients((prev) =>
      prev.map((row) => {
        if (row.id !== id) return row;
        const updated = { ...row, [field]: value };
        if (field === 'ingredient_id') {
          const opt = ingredientOptions.find((o) => o.id === value);
          if (opt) {
            updated.name = opt.name;
            updated.spec = opt.spec;
            updated.unit = opt.unit;
            updated.unit_price_fen = opt.unit_price_fen;
          }
        }
        updated.subtotal_fen = updated.unit_price_fen * updated.quantity;
        return updated;
      }),
    );
  };

  const editTotalCost = useMemo(
    () => editIngredients.reduce((s, i) => s + i.subtotal_fen, 0),
    [editIngredients],
  );

  const editSellPrice = useMemo(() => {
    if (currentBom) return currentBom.sell_price_fen;
    const dish = dishOptions.find((d) => d.id === selectedDishId);
    return dish?.sell_price_fen ?? 0;
  }, [currentBom, selectedDishId, dishOptions]);

  const editMarginRate = useMemo(() => {
    if (editSellPrice <= 0) return 0;
    return Math.round(((editSellPrice - editTotalCost) / editSellPrice) * 10000) / 100;
  }, [editTotalCost, editSellPrice]);

  const handleSave = async () => {
    if (drawerMode === 'create' && !selectedDishId) {
      message.warning('请先选择菜品');
      return;
    }
    if (editIngredients.length === 0) {
      message.warning('请至少添加一行食材');
      return;
    }
    if (editIngredients.some((i) => !i.ingredient_id)) {
      message.warning('有食材行未选择食材');
      return;
    }

    setSaving(true);
    const dish = dishOptions.find((d) => d.id === (currentBom?.dish_id ?? selectedDishId));
    const bomToSave: BomRecord = {
      id: currentBom?.id ?? genId('bom'),
      dish_id: currentBom?.dish_id ?? selectedDishId,
      dish_name: dish?.name ?? '',
      category: dish?.category ?? '',
      ingredient_count: editIngredients.length,
      total_cost_fen: editTotalCost,
      sell_price_fen: editSellPrice,
      margin_rate: editMarginRate,
      updated_at: new Date().toISOString().slice(0, 16).replace('T', ' '),
      ingredients: editIngredients,
    };

    try {
      if (drawerMode === 'create') {
        const created = await createBom({
          dish_id: bomToSave.dish_id,
          ingredients: editIngredients,
        });
        if (created) {
          setBomList((prev) => [created, ...prev]);
        } else {
          setBomList((prev) => [bomToSave, ...prev]);
        }
      } else {
        await saveBom(bomToSave);
        setBomList((prev) => {
          const idx = prev.findIndex((b) => b.id === bomToSave.id);
          if (idx >= 0) {
            const copy = [...prev];
            copy[idx] = bomToSave;
            return copy;
          }
          return prev;
        });
      }
      message.success('配方保存成功');
      setDrawerOpen(false);
    } catch {
      message.error('保存失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  // ─── ProTable Columns ────────────────────────────

  const columns: ProColumns<BomRecord>[] = [
    {
      title: '菜品名',
      dataIndex: 'dish_name',
      width: 140,
      ellipsis: true,
    },
    {
      title: '分类',
      dataIndex: 'category',
      width: 80,
      filters: true,
      onFilter: true,
      valueEnum: {
        '热菜': { text: '热菜' },
        '凉菜': { text: '凉菜' },
        '汤类': { text: '汤类' },
        '主食': { text: '主食' },
        '饮品': { text: '饮品' },
      },
    },
    {
      title: '食材数量',
      dataIndex: 'ingredient_count',
      width: 90,
      sorter: (a, b) => a.ingredient_count - b.ingredient_count,
    },
    {
      title: '总成本(元)',
      dataIndex: 'total_cost_fen',
      width: 110,
      sorter: (a, b) => a.total_cost_fen - b.total_cost_fen,
      render: (_: unknown, record: BomRecord) => (
        <Text strong>{fenToYuan(record.total_cost_fen)}</Text>
      ),
    },
    {
      title: '售价(元)',
      dataIndex: 'sell_price_fen',
      width: 100,
      sorter: (a, b) => a.sell_price_fen - b.sell_price_fen,
      render: (_: unknown, record: BomRecord) => fenToYuan(record.sell_price_fen),
    },
    {
      title: '毛利率%',
      dataIndex: 'margin_rate',
      width: 100,
      sorter: (a, b) => a.margin_rate - b.margin_rate,
      render: (_: unknown, record: BomRecord) => marginTag(record.margin_rate),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 140,
      sorter: (a, b) => a.updated_at.localeCompare(b.updated_at),
    },
    {
      title: '操作',
      width: 200,
      valueType: 'option',
      render: (_: unknown, record: BomRecord) => (
        <Space size={4}>
          <Tooltip title="查看配方">
            <Button
              type="link"
              size="small"
              icon={<EyeOutlined />}
              onClick={() => openDrawer('view', record)}
            />
          </Tooltip>
          <Tooltip title="编辑">
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              onClick={() => openDrawer('edit', record)}
            />
          </Tooltip>
          <Tooltip title="复制">
            <Button
              type="link"
              size="small"
              icon={<CopyOutlined />}
              onClick={() => handleCopy(record)}
            />
          </Tooltip>
          <Popconfirm
            title="确定删除此配方？"
            onConfirm={() => handleDelete(record.id)}
          >
            <Tooltip title="删除">
              <Button type="link" size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // ─── Drawer 食材明细表列 ────────────────────────

  const ingredientColumns = [
    {
      title: '食材名',
      dataIndex: 'ingredient_id',
      width: 160,
      render: (val: string, record: BomIngredient) => {
        if (drawerMode === 'view') return record.name;
        return (
          <Select
            value={val || undefined}
            placeholder="选择食材"
            style={{ width: '100%' }}
            showSearch
            optionFilterProp="label"
            options={ingredientOptions.map((o) => ({
              value: o.id,
              label: `${o.name}(${o.spec})`,
            }))}
            onChange={(v: string) => updateIngredientRow(record.id, 'ingredient_id', v)}
          />
        );
      },
    },
    {
      title: '规格',
      dataIndex: 'spec',
      width: 120,
    },
    {
      title: '用量',
      dataIndex: 'quantity',
      width: 100,
      render: (val: number, record: BomIngredient) => {
        if (drawerMode === 'view') return val;
        return (
          <InputNumber
            value={val}
            min={0}
            style={{ width: '100%' }}
            onChange={(v) => updateIngredientRow(record.id, 'quantity', v ?? 0)}
          />
        );
      },
    },
    {
      title: '单位',
      dataIndex: 'unit',
      width: 60,
    },
    {
      title: '单价(元)',
      dataIndex: 'unit_price_fen',
      width: 100,
      render: (val: number) => fenToYuan(val),
    },
    {
      title: '小计(元)',
      dataIndex: 'subtotal_fen',
      width: 100,
      render: (val: number) => <Text strong>{fenToYuan(val)}</Text>,
    },
    ...(drawerMode !== 'view'
      ? [
          {
            title: '',
            width: 40,
            render: (_: unknown, record: BomIngredient) => (
              <Button
                type="link"
                danger
                size="small"
                icon={<MinusCircleOutlined />}
                onClick={() => removeIngredientRow(record.id)}
              />
            ),
          },
        ]
      : []),
  ];

  return (
    <>
      <ProTable<BomRecord>
        actionRef={tableRef}
        columns={columns}
        dataSource={bomList}
        loading={loading}
        rowKey="id"
        search={false}
        pagination={{ pageSize: 10, showSizeChanger: true }}
        headerTitle="配方列表"
        toolBarRender={() => [
          <Button
            key="create"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => openDrawer('create')}
          >
            新建配方
          </Button>,
        ]}
        options={{ density: true, reload: () => loadData() }}
      />

      <Drawer
        title={
          drawerMode === 'create'
            ? '新建配方'
            : drawerMode === 'edit'
            ? `编辑配方 - ${currentBom?.dish_name ?? ''}`
            : `查看配方 - ${currentBom?.dish_name ?? ''}`
        }
        width={720}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        extra={
          drawerMode !== 'view' ? (
            <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>
              保存配方
            </Button>
          ) : null
        }
      >
        {/* 菜品信息卡 */}
        {drawerMode === 'create' && !currentBom ? (
          <div style={{ marginBottom: 16 }}>
            <Text strong>选择菜品：</Text>
            <Select
              style={{ width: 300, marginLeft: 8 }}
              placeholder="搜索并选择菜品"
              showSearch
              optionFilterProp="label"
              value={selectedDishId || undefined}
              options={dishOptions.map((d) => ({
                value: d.id,
                label: `${d.name} - ${d.category} - ¥${fenToYuan(d.sell_price_fen)}`,
              }))}
              onChange={setSelectedDishId}
            />
          </div>
        ) : currentBom ? (
          <Descriptions
            size="small"
            column={3}
            bordered
            style={{ marginBottom: 16 }}
          >
            <Descriptions.Item label="菜品名">{currentBom.dish_name}</Descriptions.Item>
            <Descriptions.Item label="分类">{currentBom.category}</Descriptions.Item>
            <Descriptions.Item label="售价">
              ¥{fenToYuan(currentBom.sell_price_fen)}
            </Descriptions.Item>
          </Descriptions>
        ) : null}

        <Divider style={{ margin: '12px 0' }} />

        {/* 配方明细表 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <Text strong>配方明细</Text>
          {drawerMode !== 'view' && (
            <Button size="small" icon={<PlusOutlined />} onClick={addIngredientRow}>
              添加食材
            </Button>
          )}
        </div>

        <Table
          dataSource={editIngredients}
          columns={ingredientColumns}
          rowKey="id"
          pagination={false}
          size="small"
          scroll={{ y: 300 }}
        />

        {/* 底部汇总 */}
        <Card size="small" style={{ marginTop: 16 }}>
          <Row gutter={24}>
            <Col span={6}>
              <Statistic title="总成本" value={fenToYuan(editTotalCost)} prefix="¥" />
            </Col>
            <Col span={6}>
              <Statistic title="售价" value={fenToYuan(editSellPrice)} prefix="¥" />
            </Col>
            <Col span={6}>
              <Statistic
                title="毛利"
                value={fenToYuan(editSellPrice - editTotalCost)}
                prefix="¥"
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="毛利率"
                value={editMarginRate}
                suffix="%"
                valueStyle={{ color: marginColor(editMarginRate) }}
              />
            </Col>
          </Row>
        </Card>
      </Drawer>
    </>
  );
}

// ─── Tab2: 成本分析 ──────────────────────────────────────────────

/** SVG 饼图 arc 路径辅助 */
function describeArc(cx: number, cy: number, r: number, startAngle: number, endAngle: number): string {
  const start = polarToCartesian(cx, cy, r, endAngle);
  const end = polarToCartesian(cx, cy, r, startAngle);
  const largeArc = endAngle - startAngle > 180 ? 1 : 0;
  return `M ${cx} ${cy} L ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 0 ${end.x} ${end.y} Z`;
}

function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

const PIE_COLORS = ['#FF6B35', '#0F6E56', '#185FA5', '#BA7517', '#8B5CF6', '#EC4899'];

function CostAnalysisTab() {
  const [bomList, setBomList] = useState<BomRecord[]>([]);

  useEffect(() => {
    fetchBomList().then(setBomList);
  }, []);

  // 按分类分组成本
  const categoryStats = useMemo(() => {
    const map = new Map<string, number>();
    for (const b of bomList) {
      map.set(b.category, (map.get(b.category) ?? 0) + b.total_cost_fen);
    }
    const entries = Array.from(map.entries()).sort((a, b) => b[1] - a[1]);
    const total = entries.reduce((s, e) => s + e[1], 0);
    return { entries, total };
  }, [bomList]);

  // 成本最高 TOP10
  const top10ByCost = useMemo(
    () => [...bomList].sort((a, b) => b.total_cost_fen - a.total_cost_fen).slice(0, 10),
    [bomList],
  );

  // 低毛利预警
  const lowMarginList = useMemo(
    () => bomList.filter((b) => b.margin_rate < 40).sort((a, b) => a.margin_rate - b.margin_rate),
    [bomList],
  );

  const maxCost = top10ByCost.length > 0 ? top10ByCost[0].total_cost_fen : 1;

  // 饼图数据
  const pieSlices = useMemo(() => {
    if (categoryStats.total === 0) return [];
    let cumAngle = 0;
    return categoryStats.entries.map(([cat, cost], idx) => {
      const angle = (cost / categoryStats.total) * 360;
      const startAngle = cumAngle;
      cumAngle += angle;
      return {
        category: cat,
        cost,
        pct: ((cost / categoryStats.total) * 100).toFixed(1),
        startAngle,
        endAngle: cumAngle,
        color: PIE_COLORS[idx % PIE_COLORS.length],
      };
    });
  }, [categoryStats]);

  return (
    <div>
      <Row gutter={24}>
        {/* 饼图 */}
        <Col span={12}>
          <Card title={<><PieChartOutlined /> 成本分布（按分类）</>} size="small">
            {pieSlices.length === 0 ? (
              <Empty description="暂无数据" />
            ) : (
              <div style={{ display: 'flex', alignItems: 'center' }}>
                <svg width={220} height={220} viewBox="0 0 220 220">
                  {pieSlices.map((slice) => (
                    <path
                      key={slice.category}
                      d={describeArc(110, 110, 100, slice.startAngle, slice.endAngle - 0.5)}
                      fill={slice.color}
                      stroke="#fff"
                      strokeWidth={2}
                    >
                      <title>{`${slice.category}: ¥${fenToYuan(slice.cost)} (${slice.pct}%)`}</title>
                    </path>
                  ))}
                </svg>
                <div style={{ marginLeft: 20 }}>
                  {pieSlices.map((slice) => (
                    <div key={slice.category} style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
                      <span
                        style={{
                          display: 'inline-block',
                          width: 12,
                          height: 12,
                          borderRadius: 2,
                          backgroundColor: slice.color,
                          marginRight: 8,
                        }}
                      />
                      <Text style={{ fontSize: 13 }}>
                        {slice.category} ¥{fenToYuan(slice.cost)} ({slice.pct}%)
                      </Text>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Card>
        </Col>

        {/* 柱状图 */}
        <Col span={12}>
          <Card title={<><BarChartOutlined /> 成本最高 TOP10</>} size="small">
            {top10ByCost.length === 0 ? (
              <Empty description="暂无数据" />
            ) : (
              <svg width="100%" height={top10ByCost.length * 32 + 10} viewBox={`0 0 450 ${top10ByCost.length * 32 + 10}`}>
                {top10ByCost.map((bom, idx) => {
                  const barWidth = (bom.total_cost_fen / maxCost) * 280;
                  const y = idx * 32 + 5;
                  return (
                    <g key={bom.id}>
                      <text x={0} y={y + 18} fontSize={12} fill="#333" textAnchor="start">
                        {bom.dish_name}
                      </text>
                      <rect x={100} y={y + 2} width={barWidth} height={20} rx={3} fill={TX_PRIMARY} opacity={0.85}>
                        <title>¥{fenToYuan(bom.total_cost_fen)}</title>
                      </rect>
                      <text x={105 + barWidth} y={y + 17} fontSize={11} fill="#666">
                        ¥{fenToYuan(bom.total_cost_fen)}
                      </text>
                    </g>
                  );
                })}
              </svg>
            )}
          </Card>
        </Col>
      </Row>

      {/* 低毛利预警 */}
      <Card
        title={
          <Space>
            <WarningOutlined style={{ color: TX_DANGER }} />
            <span>低毛利预警（毛利率 &lt; 40%）</span>
            <Tag color="red">{lowMarginList.length}道</Tag>
          </Space>
        }
        size="small"
        style={{ marginTop: 16 }}
      >
        {lowMarginList.length === 0 ? (
          <Alert type="success" message="所有菜品毛利率均在40%以上，无需预警" showIcon />
        ) : (
          <Table
            dataSource={lowMarginList}
            rowKey="id"
            pagination={false}
            size="small"
            columns={[
              { title: '菜品', dataIndex: 'dish_name', width: 140 },
              { title: '分类', dataIndex: 'category', width: 80 },
              {
                title: '成本(元)',
                dataIndex: 'total_cost_fen',
                width: 100,
                render: (v: number) => `¥${fenToYuan(v)}`,
              },
              {
                title: '售价(元)',
                dataIndex: 'sell_price_fen',
                width: 100,
                render: (v: number) => `¥${fenToYuan(v)}`,
              },
              {
                title: '毛利率',
                dataIndex: 'margin_rate',
                width: 100,
                render: (v: number) => (
                  <Text style={{ color: TX_DANGER, fontWeight: 600 }}>{v.toFixed(1)}%</Text>
                ),
              },
              {
                title: '状态',
                width: 80,
                render: (_: unknown, r: BomRecord) => (
                  r.margin_rate < 20
                    ? <Tag color="red">严重</Tag>
                    : <Tag color="orange">警告</Tag>
                ),
              },
            ]}
          />
        )}
      </Card>
    </div>
  );
}

// ─── Tab3: 成本模拟 ──────────────────────────────────────────────

interface SimResult {
  bom_id: string;
  dish_name: string;
  category: string;
  old_cost_fen: number;
  new_cost_fen: number;
  sell_price_fen: number;
  old_margin: number;
  new_margin: number;
  margin_drop: number;
  suggested_price_fen: number;
}

function CostSimulationTab() {
  const [bomList, setBomList] = useState<BomRecord[]>([]);
  const [ingredientOptions, setIngredientOptions] = useState<IngredientOption[]>([]);
  const [selectedIngId, setSelectedIngId] = useState<string>('');
  const [priceIncrease, setPriceIncrease] = useState<number>(10);
  const [targetMargin, setTargetMargin] = useState<number>(60);
  const [simResults, setSimResults] = useState<SimResult[]>([]);
  const [hasSimulated, setHasSimulated] = useState(false);

  useEffect(() => {
    Promise.all([fetchBomList(), fetchIngredients()]).then(([boms, ings]) => {
      setBomList(boms);
      setIngredientOptions(ings);
    });
  }, []);

  const runSimulation = () => {
    if (!selectedIngId) {
      message.warning('请选择食材');
      return;
    }
    const ratio = 1 + priceIncrease / 100;
    const results: SimResult[] = [];

    for (const bom of bomList) {
      const affected = bom.ingredients.filter((i) => i.ingredient_id === selectedIngId);
      if (affected.length === 0) continue;

      const costDelta = affected.reduce(
        (s, i) => s + Math.round(i.unit_price_fen * i.quantity * (ratio - 1)),
        0,
      );
      const newCost = bom.total_cost_fen + costDelta;
      const sell = bom.sell_price_fen;
      const oldMargin = sell > 0 ? ((sell - bom.total_cost_fen) / sell) * 100 : 0;
      const newMargin = sell > 0 ? ((sell - newCost) / sell) * 100 : 0;
      // 根据目标毛利率反算建议售价: sell = cost / (1 - target/100)
      const suggestedPrice = Math.ceil(newCost / (1 - targetMargin / 100));

      results.push({
        bom_id: bom.id,
        dish_name: bom.dish_name,
        category: bom.category,
        old_cost_fen: bom.total_cost_fen,
        new_cost_fen: newCost,
        sell_price_fen: sell,
        old_margin: Math.round(oldMargin * 100) / 100,
        new_margin: Math.round(newMargin * 100) / 100,
        margin_drop: Math.round((oldMargin - newMargin) * 100) / 100,
        suggested_price_fen: suggestedPrice,
      });
    }

    results.sort((a, b) => b.margin_drop - a.margin_drop);
    setSimResults(results);
    setHasSimulated(true);
  };

  const handleBatchSuggest = () => {
    if (simResults.length === 0) return;
    Modal.info({
      title: '批量调价建议',
      width: 600,
      content: (
        <div style={{ maxHeight: 400, overflow: 'auto' }}>
          <Alert
            type="info"
            message={`基于目标毛利率 ${targetMargin}%，以下是建议售价调整：`}
            style={{ marginBottom: 12 }}
            showIcon
          />
          <Table
            dataSource={simResults.filter((r) => r.suggested_price_fen > r.sell_price_fen)}
            rowKey="bom_id"
            pagination={false}
            size="small"
            columns={[
              { title: '菜品', dataIndex: 'dish_name', width: 120 },
              {
                title: '当前售价',
                dataIndex: 'sell_price_fen',
                width: 90,
                render: (v: number) => `¥${fenToYuan(v)}`,
              },
              {
                title: '建议售价',
                dataIndex: 'suggested_price_fen',
                width: 90,
                render: (v: number) => (
                  <Text style={{ color: TX_PRIMARY, fontWeight: 600 }}>¥{fenToYuan(v)}</Text>
                ),
              },
              {
                title: '涨幅',
                width: 80,
                render: (_: unknown, r: SimResult) => {
                  const pct = ((r.suggested_price_fen - r.sell_price_fen) / r.sell_price_fen * 100).toFixed(1);
                  return <Tag color="orange">+{pct}%</Tag>;
                },
              },
            ]}
          />
        </div>
      ),
    });
  };

  const selectedIngName = ingredientOptions.find((o) => o.id === selectedIngId)?.name ?? '';

  return (
    <div>
      <Card
        title={<><ExperimentOutlined /> 食材涨价模拟器</>}
        size="small"
      >
        <Row gutter={16} align="middle">
          <Col>
            <Text strong>选择食材：</Text>
            <Select
              style={{ width: 240, marginLeft: 8 }}
              placeholder="选择食材"
              showSearch
              optionFilterProp="label"
              value={selectedIngId || undefined}
              options={ingredientOptions.map((o) => ({
                value: o.id,
                label: `${o.name}(${o.spec})`,
              }))}
              onChange={setSelectedIngId}
            />
          </Col>
          <Col>
            <Text strong>涨价比例：</Text>
            <InputNumber
              style={{ width: 100, marginLeft: 8 }}
              value={priceIncrease}
              min={1}
              max={500}
              addonAfter="%"
              onChange={(v) => setPriceIncrease(v ?? 10)}
            />
          </Col>
          <Col>
            <Text strong>目标毛利率：</Text>
            <InputNumber
              style={{ width: 100, marginLeft: 8 }}
              value={targetMargin}
              min={10}
              max={90}
              addonAfter="%"
              onChange={(v) => setTargetMargin(v ?? 60)}
            />
          </Col>
          <Col>
            <Button type="primary" icon={<CalculatorOutlined />} onClick={runSimulation}>
              开始模拟
            </Button>
          </Col>
        </Row>
      </Card>

      {hasSimulated && (
        <Card
          size="small"
          style={{ marginTop: 16 }}
          title={
            <Space>
              <span>
                模拟结果：「{selectedIngName}」涨价 {priceIncrease}%，影响 {simResults.length} 道菜品
              </span>
              {simResults.length > 0 && (
                <Button size="small" type="primary" ghost onClick={handleBatchSuggest}>
                  批量调价建议
                </Button>
              )}
            </Space>
          }
        >
          {simResults.length === 0 ? (
            <Empty description="该食材未被任何配方使用" />
          ) : (
            <Table
              dataSource={simResults}
              rowKey="bom_id"
              pagination={false}
              size="small"
              columns={[
                { title: '菜品', dataIndex: 'dish_name', width: 120 },
                { title: '分类', dataIndex: 'category', width: 80 },
                {
                  title: '原成本',
                  dataIndex: 'old_cost_fen',
                  width: 90,
                  render: (v: number) => `¥${fenToYuan(v)}`,
                },
                {
                  title: '新成本',
                  dataIndex: 'new_cost_fen',
                  width: 90,
                  render: (v: number) => (
                    <Text style={{ color: TX_DANGER }}>¥{fenToYuan(v)}</Text>
                  ),
                },
                {
                  title: '售价',
                  dataIndex: 'sell_price_fen',
                  width: 80,
                  render: (v: number) => `¥${fenToYuan(v)}`,
                },
                {
                  title: '原毛利率',
                  dataIndex: 'old_margin',
                  width: 90,
                  render: (v: number) => marginTag(v),
                },
                {
                  title: '新毛利率',
                  dataIndex: 'new_margin',
                  width: 90,
                  render: (v: number) => marginTag(v),
                },
                {
                  title: '降幅',
                  dataIndex: 'margin_drop',
                  width: 80,
                  sorter: (a: SimResult, b: SimResult) => b.margin_drop - a.margin_drop,
                  render: (v: number) => (
                    <Text style={{ color: TX_DANGER, fontWeight: 600 }}>-{v.toFixed(1)}%</Text>
                  ),
                },
                {
                  title: '建议售价',
                  dataIndex: 'suggested_price_fen',
                  width: 100,
                  render: (v: number, r: SimResult) => {
                    if (v <= r.sell_price_fen) return <Tag color="green">无需调整</Tag>;
                    return (
                      <Text style={{ color: TX_PRIMARY, fontWeight: 600 }}>
                        ¥{fenToYuan(v)}
                      </Text>
                    );
                  },
                },
              ]}
            />
          )}
        </Card>
      )}
    </div>
  );
}

// ─── 主组件 ──────────────────────────────────────────────────────

export function BOMPage() {
  return (
    <div style={{ padding: 0 }}>
      <Card bordered={false}>
        <Tabs
          defaultActiveKey="recipes"
          items={[
            {
              key: 'recipes',
              label: '配方列表',
              children: <RecipeListTab />,
            },
            {
              key: 'analysis',
              label: '成本分析',
              icon: <PieChartOutlined />,
              children: <CostAnalysisTab />,
            },
            {
              key: 'simulation',
              label: '成本模拟',
              icon: <ExperimentOutlined />,
              children: <CostSimulationTab />,
            },
          ]}
        />
      </Card>
    </div>
  );
}

export default BOMPage;
