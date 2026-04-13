/**
 * 活鲜菜品管理页
 * 域B 菜品管理 · 总部管理后台
 *
 * 功能：
 * 1. 顶部统计卡片：活鲜品种数/今日累计销售额/平均成活率/低库存预警数
 * 2. Table展示所有活鲜菜品：菜品名/计价方式/单价/展示单位/鱼缸位置/当前库存/成活率/是否上架/操作
 * 3. ModalForm：设置活鲜计价配置（PATCH /api/v1/menu/live-seafood/{dish_id}）
 * 4. 库存快速调整：点击库存数字弹出Popover输入框
 * 5. 鱼缸区域管理：DrawerForm管理鱼缸区域（GET/POST /api/v1/menu/tank-zones）
 *
 * 技术栈：antd 5.x + React 18 TypeScript strict
 * 设计：白底浅色管理界面，主色 #FF6B35，符合txAdminTheme规范
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  Button,
  Card,
  Col,
  Drawer,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Popover,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  EditOutlined,
  ExclamationCircleOutlined,
  ReloadOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { txFetchData } from '../../../api';

const { Title, Text } = Typography;
const { Option } = Select;

// ─── Design Token（与 txAdminTheme 对齐） ────────────────────────────────────
const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_WARNING = '#BA7517';
const TX_ERROR = '#A32D2D';
const TX_BG_HEADER = '#F8F7F5';

// ─── 类型定义 ────────────────────────────────────────────────────────────────

type PricingMethod = 'fixed' | 'weight' | 'per_piece';

interface LiveSeafoodDish {
  dish_id: string;
  dish_name: string;
  pricing_method: PricingMethod;
  unit_price_fen: number;
  weight_unit: string;
  display_unit: string;
  tank_zone_name: string;
  tank_zone_id: string;
  current_stock: number;
  survival_rate: number;
  is_available: boolean;
  min_order_qty: number;
}

interface LiveSeafoodStats {
  total_species: number;
  today_sales_fen: number;
  avg_survival_rate: number;
  low_stock_count: number;
}

interface TankZone {
  id: string;
  zone_name: string;
  capacity: number;
  location_desc: string;
}

// ─── API 函数 ────────────────────────────────────────────────────────────────

async function fetchLiveSeafood(
  storeId: string,
  inStockOnly = false,
): Promise<{ items: LiveSeafoodDish[]; total: number }> {
  const params = new URLSearchParams({ store_id: storeId });
  if (inStockOnly) params.set('in_stock_only', 'true');
  const res = await txFetchData<{ items: LiveSeafoodDish[]; total: number }>(
    `/api/v1/menu/live-seafood?${params.toString()}`,
  );
  return res ?? { items: [], total: 0 };
}

async function fetchLiveSeafoodStats(storeId: string): Promise<LiveSeafoodStats> {
  const res = await txFetchData<LiveSeafoodStats>(
    `/api/v1/menu/live-seafood/stats?store_id=${storeId}`,
  );
  return res ?? { total_species: 0, today_sales_fen: 0, avg_survival_rate: 0, low_stock_count: 0 };
}

async function fetchTankZoneList(): Promise<{ items: TankZone[]; total: number }> {
  const res = await txFetchData<{ items: TankZone[]; total: number }>(
    '/api/v1/menu/live-seafood/tanks',
  );
  return res ?? { items: [], total: 0 };
}

async function fetchTankDishes(zoneCode: string): Promise<LiveSeafoodDish[]> {
  const res = await txFetchData<{ items: LiveSeafoodDish[] }>(
    `/api/v1/menu/live-seafood/tanks/${encodeURIComponent(zoneCode)}/dishes`,
  );
  return res?.items ?? [];
}

async function patchLiveSeafood(
  dishId: string,
  payload: Partial<Omit<LiveSeafoodDish, 'dish_id' | 'dish_name' | 'tank_zone_name' | 'current_stock'>>,
): Promise<void> {
  await txFetchData<LiveSeafoodDish>(`/api/v1/menu/live-seafood/${dishId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

async function adjustStock(
  dishId: string,
  deltaCount: number,
  deltaWeightG: number,
  reason: string,
): Promise<void> {
  await txFetchData<void>(`/api/v1/menu/live-seafood/stocks/${dishId}`, {
    method: 'PATCH',
    body: JSON.stringify({ delta_count: deltaCount, delta_weight_g: deltaWeightG, reason }),
  });
}

/** 旧的 tank-zones 接口 fallback（Drawer 仍使用） */
async function fetchTankZones(): Promise<{ items: TankZone[]; total: number }> {
  try {
    return await fetchTankZoneList();
  } catch {
    return { items: [], total: 0 };
  }
}

async function createTankZone(
  payload: Omit<TankZone, 'id'>,
): Promise<TankZone> {
  const res = await txFetchData<TankZone>('/api/v1/menu/tank-zones', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  if (!res) throw new Error('创建失败');
  return res;
}

// ─── 常量 ────────────────────────────────────────────────────────────────────

const PRICING_METHOD_LABELS: Record<PricingMethod, string> = {
  fixed: '固定价',
  weight: '称重',
  per_piece: '条头',
};

const PRICING_METHOD_COLORS: Record<PricingMethod, string> = {
  fixed: 'blue',
  weight: 'orange',
  per_piece: 'purple',
};

// 门店列表从 API 加载，初始为空

// ─── 子组件：统计卡片 ────────────────────────────────────────────────────────

interface StatsCardsProps {
  stats: LiveSeafoodStats | null;
  loading: boolean;
}

const StatsCards: React.FC<StatsCardsProps> = ({ stats, loading }) => {
  const cards = [
    {
      title: '活鲜品种数',
      value: stats?.total_species ?? 0,
      suffix: '种',
      color: TX_PRIMARY,
    },
    {
      title: '今日累计销售额',
      value: stats ? `¥${(stats.today_sales_fen / 100).toFixed(0)}` : '¥0',
      color: TX_SUCCESS,
      isString: true,
    },
    {
      title: '平均成活率',
      value: stats ? `${stats.avg_survival_rate.toFixed(1)}%` : '—',
      color: stats && stats.avg_survival_rate < 85 ? TX_WARNING : TX_SUCCESS,
      isString: true,
    },
    {
      title: '低库存预警',
      value: stats?.low_stock_count ?? 0,
      suffix: '项',
      color: (stats?.low_stock_count ?? 0) > 0 ? TX_ERROR : TX_SUCCESS,
    },
  ];

  return (
    <Row gutter={16} style={{ marginBottom: 24 }}>
      {cards.map((card) => (
        <Col span={6} key={card.title}>
          <Card
            loading={loading}
            style={{ borderRadius: 6 }}
            styles={{ body: { padding: '16px 20px', background: TX_BG_HEADER } }}
          >
            {card.isString ? (
              <div>
                <Text type="secondary" style={{ fontSize: 13 }}>{card.title}</Text>
                <div style={{ fontSize: 28, fontWeight: 700, color: card.color, marginTop: 4 }}>
                  {card.value}
                </div>
              </div>
            ) : (
              <Statistic
                title={<Text type="secondary">{card.title}</Text>}
                value={card.value as number}
                suffix={card.suffix}
                valueStyle={{ color: card.color, fontSize: 28, fontWeight: 700 }}
              />
            )}
          </Card>
        </Col>
      ))}
    </Row>
  );
};

// ─── 子组件：库存快速调整 Popover ─────────────────────────────────────────────

interface StockAdjustPopoverProps {
  dish: LiveSeafoodDish;
  onSuccess: () => void;
}

const StockAdjustPopover: React.FC<StockAdjustPopoverProps> = ({ dish, onSuccess }) => {
  const [open, setOpen] = useState(false);
  const [newQty, setNewQty] = useState<number | null>(null);
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(false);

  const handleConfirm = async () => {
    if (newQty === null) {
      message.warning('请输入调整后的库存数量');
      return;
    }
    const delta = newQty - dish.current_stock;
    setLoading(true);
    try {
      await adjustStock(dish.dish_id, delta, 0, note || '手动调整');
      message.success('库存调整成功');
      setOpen(false);
      setNewQty(null);
      setNote('');
      onSuccess();
    } catch {
      message.error('库存调整失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  const content = (
    <div style={{ width: 240 }}>
      <div style={{ marginBottom: 8 }}>
        <Text type="secondary">当前库存：</Text>
        <Text strong>{dish.current_stock} {dish.display_unit}</Text>
      </div>
      <InputNumber
        style={{ width: '100%', marginBottom: 8 }}
        min={0}
        placeholder="调整后库存数量"
        value={newQty}
        onChange={(v) => setNewQty(v)}
      />
      <Input
        style={{ marginBottom: 8 }}
        placeholder="备注（可选）"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <Space>
        <Button size="small" onClick={() => setOpen(false)}>取消</Button>
        <Button size="small" type="primary" loading={loading} onClick={handleConfirm}>
          确认
        </Button>
      </Space>
    </div>
  );

  return (
    <Popover
      title="快速调整库存"
      content={content}
      trigger="click"
      open={open}
      onOpenChange={setOpen}
    >
      <Tooltip title="点击调整库存">
        <span
          style={{ cursor: 'pointer', color: TX_PRIMARY, fontWeight: 600 }}
          onClick={() => setOpen(true)}
        >
          {dish.current_stock}
          <EditOutlined style={{ marginLeft: 4, fontSize: 11 }} />
        </span>
      </Tooltip>
    </Popover>
  );
};

// ─── 子组件：活鲜配置 Modal ───────────────────────────────────────────────────

interface SeafoodConfigModalProps {
  dish: LiveSeafoodDish | null;
  tankZones: TankZone[];
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

const SeafoodConfigModal: React.FC<SeafoodConfigModalProps> = ({
  dish,
  tankZones,
  open,
  onClose,
  onSuccess,
}) => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [pricingMethod, setPricingMethod] = useState<PricingMethod>('fixed');

  useEffect(() => {
    if (dish && open) {
      form.setFieldsValue({
        pricing_method: dish.pricing_method,
        weight_unit: dish.weight_unit,
        unit_price_fen: dish.unit_price_fen / 100,
        min_order_qty: dish.min_order_qty,
        display_unit: dish.display_unit,
        tank_zone_id: dish.tank_zone_id,
        survival_rate: dish.survival_rate,
      });
      setPricingMethod(dish.pricing_method);
    }
  }, [dish, open, form]);

  const handleFinish = async (values: Record<string, unknown>) => {
    if (!dish) return;
    setLoading(true);
    try {
      await patchLiveSeafood(dish.dish_id, {
        pricing_method: values.pricing_method as PricingMethod,
        weight_unit: values.weight_unit as string,
        unit_price_fen: Math.round((values.unit_price_fen as number) * 100),
        min_order_qty: values.min_order_qty as number,
        display_unit: values.display_unit as string,
        tank_zone_id: values.tank_zone_id as string,
        survival_rate: values.survival_rate as number,
      });
      message.success('活鲜配置已更新');
      onSuccess();
      onClose();
    } catch {
      message.error('更新失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={`活鲜配置 — ${dish?.dish_name ?? ''}`}
      open={open}
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={loading}
      width={520}
      destroyOnClose
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={handleFinish}
        style={{ marginTop: 16 }}
      >
        <Form.Item name="pricing_method" label="计价方式" rules={[{ required: true }]}>
          <Select
            onChange={(v) => setPricingMethod(v as PricingMethod)}
            options={[
              { label: '固定价', value: 'fixed' },
              { label: '称重计价', value: 'weight' },
              { label: '条头计价', value: 'per_piece' },
            ]}
          />
        </Form.Item>

        {pricingMethod === 'weight' && (
          <Form.Item name="weight_unit" label="称重单位" rules={[{ required: true }]}>
            <Select>
              <Option value="斤">斤</Option>
              <Option value="两">两</Option>
              <Option value="克">克</Option>
              <Option value="kg">kg</Option>
            </Select>
          </Form.Item>
        )}

        <Form.Item
          name="unit_price_fen"
          label={pricingMethod === 'weight' ? '单价（元/单位）' : '单价（元）'}
          rules={[{ required: true }, { type: 'number', min: 0 }]}
        >
          <InputNumber
            style={{ width: '100%' }}
            min={0}
            precision={2}
            prefix="¥"
          />
        </Form.Item>

        <Form.Item name="min_order_qty" label="最小点单量" rules={[{ required: true }]}>
          <InputNumber style={{ width: '100%' }} min={1} />
        </Form.Item>

        <Form.Item name="display_unit" label="展示单位" rules={[{ required: true }]}>
          <Input placeholder="如：条、斤、只" />
        </Form.Item>

        <Form.Item name="tank_zone_id" label="鱼缸区域" rules={[{ required: true }]}>
          <Select placeholder="选择鱼缸区域">
            {tankZones.map((zone) => (
              <Option key={zone.id} value={zone.id}>
                {zone.zone_name}（{zone.location_desc}）
              </Option>
            ))}
          </Select>
        </Form.Item>

        <Form.Item
          name="survival_rate"
          label="成活率（%）"
          rules={[{ required: true }, { type: 'number', min: 0, max: 100 }]}
        >
          <InputNumber style={{ width: '100%' }} min={0} max={100} precision={1} suffix="%" />
        </Form.Item>
      </Form>
    </Modal>
  );
};

// ─── 子组件：鱼缸区域管理 Drawer ──────────────────────────────────────────────

interface TankZoneDrawerProps {
  open: boolean;
  onClose: () => void;
}

const TankZoneDrawer: React.FC<TankZoneDrawerProps> = ({ open, onClose }) => {
  const [zones, setZones] = useState<TankZone[]>([]);
  const [loading, setLoading] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchTankZones();
      setZones(res.items);
    } catch {
      message.error('加载鱼缸区域失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const handleCreate = async (values: Record<string, unknown>) => {
    setCreateLoading(true);
    try {
      await createTankZone({
        zone_name: values.zone_name as string,
        capacity: values.capacity as number,
        location_desc: values.location_desc as string,
      });
      message.success('鱼缸区域创建成功');
      form.resetFields();
      load();
    } catch {
      message.error('创建失败，请重试');
    } finally {
      setCreateLoading(false);
    }
  };

  const zoneColumns: ColumnsType<TankZone> = [
    { title: '区域名称', dataIndex: 'zone_name', width: 120 },
    { title: '容量', dataIndex: 'capacity', width: 80, render: (v: number) => `${v} 条` },
    { title: '位置描述', dataIndex: 'location_desc' },
  ];

  return (
    <Drawer
      title="鱼缸区域管理"
      width={560}
      open={open}
      onClose={onClose}
      extra={
        <Button icon={<ReloadOutlined />} onClick={load} size="small">
          刷新
        </Button>
      }
    >
      <Title level={5} style={{ marginTop: 0 }}>现有区域</Title>
      <Table
        rowKey="id"
        dataSource={zones}
        columns={zoneColumns}
        loading={loading}
        pagination={false}
        size="small"
        style={{ marginBottom: 24 }}
      />

      <Title level={5}>新增鱼缸区域</Title>
      <Form form={form} layout="vertical" onFinish={handleCreate}>
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item name="zone_name" label="区域名称" rules={[{ required: true }]}>
              <Input placeholder="如：A区大缸" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="capacity" label="容量（条）" rules={[{ required: true }]}>
              <InputNumber style={{ width: '100%' }} min={1} />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="location_desc" label="位置描述" rules={[{ required: true }]}>
          <Input placeholder="如：门口左侧第一排" />
        </Form.Item>
        <Form.Item>
          <Button
            type="primary"
            htmlType="submit"
            loading={createLoading}
            style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
          >
            新增区域
          </Button>
        </Form.Item>
      </Form>
    </Drawer>
  );
};

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export function LiveSeafoodPage() {
  const [storeId, setStoreId] = useState('');
  const [storeList, setStoreList] = useState<{ id: string; name: string }[]>([]);
  const [dishes, setDishes] = useState<LiveSeafoodDish[]>([]);
  const [stats, setStats] = useState<LiveSeafoodStats | null>(null);
  const [tankZones, setTankZones] = useState<TankZone[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [statsLoading, setStatsLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [inStockOnly, setInStockOnly] = useState(false);
  const [searchName, setSearchName] = useState('');

  // Modal / Drawer 状态
  const [configModalOpen, setConfigModalOpen] = useState(false);
  const [selectedDish, setSelectedDish] = useState<LiveSeafoodDish | null>(null);
  const [tankDrawerOpen, setTankDrawerOpen] = useState(false);

  const loadDishes = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchLiveSeafood(storeId, inStockOnly);
      setDishes(res.items);
      setTotal(res.total);
    } catch {
      message.error('加载活鲜菜品失败');
    } finally {
      setLoading(false);
    }
  }, [storeId, inStockOnly]);

  const loadStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      const s = await fetchLiveSeafoodStats(storeId);
      setStats(s);
    } catch {
      // stats加载失败不影响主列表
    } finally {
      setStatsLoading(false);
    }
  }, [storeId]);

  const loadTankZones = useCallback(async () => {
    try {
      const res = await fetchTankZones();
      setTankZones(res.items);
    } catch {
      // 静默失败
    }
  }, []);

  // 加载门店列表
  useEffect(() => {
    txFetchData<{ items: { id: string; name: string }[] }>('/api/v1/org/stores?page=1&size=100')
      .then((data) => {
        if (data?.items?.length) {
          setStoreList(data.items);
          setStoreId((prev) => prev || data.items[0].id);
        }
      })
      .catch(() => setStoreList([]));
  }, []);

  useEffect(() => {
    loadDishes();
    loadStats();
    loadTankZones();
  }, [loadDishes, loadStats, loadTankZones]);

  // 30 秒自动刷新水缸状态
  useEffect(() => {
    const timer = setInterval(() => {
      loadDishes();
      loadStats();
    }, 30_000);
    return () => clearInterval(timer);
  }, [loadDishes, loadStats]);

  const handleToggleAvailable = async (dish: LiveSeafoodDish, checked: boolean) => {
    try {
      await patchLiveSeafood(dish.dish_id, { is_available: checked });
      message.success(`${dish.dish_name} 已${checked ? '上架' : '下架'}`);
      loadDishes();
    } catch {
      message.error('操作失败');
    }
  };

  // 过滤搜索（前端过滤）
  const filteredDishes = searchName.trim()
    ? dishes.filter((d) => d.dish_name.includes(searchName.trim()))
    : dishes;

  const columns: ColumnsType<LiveSeafoodDish> = [
    {
      title: '菜品名称',
      dataIndex: 'dish_name',
      fixed: 'left',
      width: 140,
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: '计价方式',
      dataIndex: 'pricing_method',
      width: 100,
      render: (method: PricingMethod) => (
        <Tag color={PRICING_METHOD_COLORS[method]}>
          {PRICING_METHOD_LABELS[method]}
        </Tag>
      ),
    },
    {
      title: '单价',
      dataIndex: 'unit_price_fen',
      width: 110,
      render: (fen: number, record) => {
        const price = (fen / 100).toFixed(2);
        const suffix = record.pricing_method === 'weight' ? `/${record.weight_unit}` : '/份';
        return <Text>¥{price}<Text type="secondary" style={{ fontSize: 12 }}>{suffix}</Text></Text>;
      },
    },
    {
      title: '展示单位',
      dataIndex: 'display_unit',
      width: 90,
    },
    {
      title: '鱼缸区域',
      dataIndex: 'tank_zone_name',
      width: 110,
      render: (name: string) => name ? <Tag>{name}</Tag> : <Text type="secondary">—</Text>,
    },
    {
      title: '当前库存',
      dataIndex: 'current_stock',
      width: 100,
      render: (_, record) => (
        <StockAdjustPopover dish={record} onSuccess={loadDishes} />
      ),
    },
    {
      title: '成活率',
      dataIndex: 'survival_rate',
      width: 90,
      sorter: (a, b) => a.survival_rate - b.survival_rate,
      render: (rate: number) => (
        <Tag color={rate < 80 ? 'red' : rate < 90 ? 'orange' : 'green'}>{rate}%</Tag>
      ),
    },
    {
      title: '是否上架',
      dataIndex: 'is_available',
      width: 90,
      render: (available: boolean, record) => (
        <Switch
          checked={available}
          size="small"
          onChange={(checked) => handleToggleAvailable(record, checked)}
          checkedChildren="上架"
          unCheckedChildren="下架"
        />
      ),
    },
    {
      title: '操作',
      key: 'action',
      fixed: 'right',
      width: 80,
      render: (_, record) => (
        <Button
          type="link"
          size="small"
          icon={<SettingOutlined />}
          onClick={() => {
            setSelectedDish(record);
            setConfigModalOpen(true);
          }}
          style={{ color: TX_PRIMARY, padding: 0 }}
        >
          配置
        </Button>
      ),
    },
  ];

  return (
    <div style={{ minWidth: 1280 }}>
      {/* 页面标题 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>活鲜菜品管理</Title>
          <Text type="secondary" style={{ fontSize: 13 }}>管理活鲜计价、鱼缸库存与成活率监控</Text>
        </div>
        <Space>
          <Select
            value={storeId}
            onChange={setStoreId}
            style={{ width: 200 }}
            options={storeList.map((s) => ({ label: s.name, value: s.id }))}
          />
          <Button
            icon={<SettingOutlined />}
            onClick={() => setTankDrawerOpen(true)}
          >
            鱼缸区域
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => { loadDishes(); loadStats(); }}>
            刷新
          </Button>
        </Space>
      </div>

      {/* 统计卡片 */}
      <StatsCards stats={stats} loading={statsLoading} />

      {/* 搜索栏 */}
      <Card style={{ marginBottom: 16 }} styles={{ body: { padding: '12px 16px' } }}>
        <Space>
          <Input.Search
            placeholder="搜索菜品名称"
            value={searchName}
            onChange={(e) => setSearchName(e.target.value)}
            style={{ width: 240 }}
            allowClear
          />
          <Space>
            <Text type="secondary">仅显示有库存：</Text>
            <Switch
              checked={inStockOnly}
              onChange={(v) => { setInStockOnly(v); setPage(1); }}
              size="small"
            />
          </Space>
          {(stats?.low_stock_count ?? 0) > 0 && (
            <Tag color="red" icon={<ExclamationCircleOutlined />}>
              {stats?.low_stock_count} 项低库存预警
            </Tag>
          )}
        </Space>
      </Card>

      {/* 主列表 */}
      <Card styles={{ body: { padding: 0 } }}>
        <Table<LiveSeafoodDish>
          rowKey="dish_id"
          dataSource={filteredDishes}
          columns={columns}
          loading={loading}
          scroll={{ x: 1000 }}
          pagination={{
            current: page,
            pageSize,
            total,
            onChange: setPage,
            showSizeChanger: false,
            showTotal: (t) => `共 ${t} 项`,
          }}
          size="middle"
          rowClassName={(record) =>
            record.current_stock <= 2 ? 'ant-table-row-low-stock' : ''
          }
        />
      </Card>

      {/* 活鲜配置 Modal */}
      <SeafoodConfigModal
        dish={selectedDish}
        tankZones={tankZones}
        open={configModalOpen}
        onClose={() => { setConfigModalOpen(false); setSelectedDish(null); }}
        onSuccess={() => { loadDishes(); loadTankZones(); }}
      />

      {/* 鱼缸区域管理 Drawer */}
      <TankZoneDrawer
        open={tankDrawerOpen}
        onClose={() => setTankDrawerOpen(false)}
      />

      {/* 低库存行高亮样式 */}
      <style>{`
        .ant-table-row-low-stock td {
          background-color: #fff8f0 !important;
        }
      `}</style>
    </div>
  );
}
