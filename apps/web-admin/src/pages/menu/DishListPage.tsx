/**
 * DishListPage — 总部菜品管理（域B · 菜品列表）
 *
 * 规范 (admin.md):
 *   - 使用 Ant Design 5.x Table + Form
 *   - ConfigProvider 注入 txAdminTheme
 *   - 毛利率低于阈值红色 Tag
 *   - 最小支持 1280px 宽度
 *   - API 调用带 X-Tenant-ID
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Table, Button, Input, Select, Tag, Space, Modal, Form,
  InputNumber, message, Card, Row, Col, Statistic, Typography,
  Popconfirm, Badge, Tooltip,
} from 'antd';
import type { ColumnsType, TablePaginationConfig } from 'antd/es/table';

const { Search } = Input;
const { Title, Text } = Typography;

// ── 类型定义 ──

interface DishRecord {
  id: string;
  name: string;
  category: string;
  price: number;           // 元
  costPrice: number;       // 成本价（元）
  marginRate: number;      // 毛利率 0-1
  status: 'on' | 'off' | 'soldout';
  kitchenStation: string;
  salesCount: number;      // 近7天销量
  tags: string[];
  createdAt: string;
}

interface DishCategory {
  id: string;
  name: string;
  dishCount: number;
  sortOrder: number;
}

// ── Mock 数据 ──

const MARGIN_THRESHOLD = 0.4;

const MOCK_CATEGORIES: DishCategory[] = [
  { id: 'c1', name: '招牌菜', dishCount: 8, sortOrder: 1 },
  { id: 'c2', name: '湘菜', dishCount: 15, sortOrder: 2 },
  { id: 'c3', name: '凉菜', dishCount: 6, sortOrder: 3 },
  { id: 'c4', name: '汤品', dishCount: 4, sortOrder: 4 },
  { id: 'c5', name: '主食', dishCount: 5, sortOrder: 5 },
  { id: 'c6', name: '饮品', dishCount: 8, sortOrder: 6 },
  { id: 'c7', name: '小吃', dishCount: 6, sortOrder: 7 },
  { id: 'c8', name: '素菜', dishCount: 5, sortOrder: 8 },
];

const MOCK_DISHES: DishRecord[] = [
  { id: 'd1', name: '招牌剁椒鱼头', category: '招牌菜', price: 128, costPrice: 48, marginRate: 0.625, status: 'on', kitchenStation: '热菜档', salesCount: 342, tags: ['招牌', '辣'], createdAt: '2025-06-15' },
  { id: 'd2', name: '小炒黄牛肉', category: '湘菜', price: 68, costPrice: 28, marginRate: 0.588, status: 'on', kitchenStation: '热菜档', salesCount: 286, tags: ['辣'], createdAt: '2025-06-15' },
  { id: 'd3', name: '茶油土鸡汤', category: '汤品', price: 88, costPrice: 25, marginRate: 0.716, status: 'on', kitchenStation: '汤档', salesCount: 198, tags: ['养生'], createdAt: '2025-07-01' },
  { id: 'd4', name: '口味虾', category: '招牌菜', price: 128, costPrice: 55, marginRate: 0.570, status: 'on', kitchenStation: '热菜档', salesCount: 231, tags: ['招牌', '辣', '时令'], createdAt: '2025-06-15' },
  { id: 'd5', name: '农家小炒肉', category: '湘菜', price: 42, costPrice: 15, marginRate: 0.643, status: 'on', kitchenStation: '热菜档', salesCount: 312, tags: ['辣'], createdAt: '2025-06-20' },
  { id: 'd6', name: '凉拌黄瓜', category: '凉菜', price: 18, costPrice: 4, marginRate: 0.778, status: 'on', kitchenStation: '凉菜档', salesCount: 189, tags: [], createdAt: '2025-06-15' },
  { id: 'd7', name: '酸辣土豆丝', category: '湘菜', price: 22, costPrice: 5, marginRate: 0.773, status: 'on', kitchenStation: '热菜档', salesCount: 275, tags: ['辣'], createdAt: '2025-06-15' },
  { id: 'd8', name: '辣椒炒肉', category: '湘菜', price: 38, costPrice: 14, marginRate: 0.632, status: 'on', kitchenStation: '热菜档', salesCount: 256, tags: ['辣'], createdAt: '2025-06-18' },
  { id: 'd9', name: '蒜蓉西兰花', category: '素菜', price: 26, costPrice: 6, marginRate: 0.769, status: 'on', kitchenStation: '热菜档', salesCount: 145, tags: [], createdAt: '2025-07-10' },
  { id: 'd10', name: '紫苏桃子姜', category: '凉菜', price: 16, costPrice: 5, marginRate: 0.688, status: 'on', kitchenStation: '凉菜档', salesCount: 120, tags: ['时令'], createdAt: '2025-08-01' },
  { id: 'd11', name: '米饭', category: '主食', price: 3, costPrice: 0.8, marginRate: 0.733, status: 'on', kitchenStation: 'default', salesCount: 892, tags: [], createdAt: '2025-06-15' },
  { id: 'd12', name: '酸梅汤', category: '饮品', price: 8, costPrice: 2, marginRate: 0.75, status: 'on', kitchenStation: 'default', salesCount: 356, tags: [], createdAt: '2025-06-15' },
  { id: 'd13', name: '鲜榨橙汁', category: '饮品', price: 18, costPrice: 8, marginRate: 0.556, status: 'on', kitchenStation: 'default', salesCount: 167, tags: ['新品'], createdAt: '2025-09-01' },
  { id: 'd14', name: '糖油粑粑', category: '小吃', price: 12, costPrice: 3, marginRate: 0.75, status: 'on', kitchenStation: '面点档', salesCount: 203, tags: ['特色'], createdAt: '2025-06-15' },
  { id: 'd15', name: '臭豆腐', category: '小吃', price: 15, costPrice: 4, marginRate: 0.733, status: 'soldout', kitchenStation: '面点档', salesCount: 178, tags: ['特色'], createdAt: '2025-06-15' },
  { id: 'd16', name: '外婆菜炒蛋', category: '湘菜', price: 28, costPrice: 16, marginRate: 0.357, status: 'on', kitchenStation: '热菜档', salesCount: 134, tags: [], createdAt: '2025-07-20' },
];

// ── 毛利率Tag（自动变色） ──

function MarginTag({ rate }: { rate: number }) {
  if (rate < MARGIN_THRESHOLD * 0.8) {
    return <Tag color="red">{(rate * 100).toFixed(1)}%</Tag>;
  }
  if (rate < MARGIN_THRESHOLD) {
    return <Tag color="orange">{(rate * 100).toFixed(1)}%</Tag>;
  }
  return <Tag color="green">{(rate * 100).toFixed(1)}%</Tag>;
}

function StatusBadge({ status }: { status: DishRecord['status'] }) {
  switch (status) {
    case 'on': return <Badge status="success" text="上架" />;
    case 'off': return <Badge status="default" text="下架" />;
    case 'soldout': return <Badge status="error" text="沽清" />;
  }
}

// ── 新增/编辑弹窗 ──

interface DishFormValues {
  name: string;
  category: string;
  price: number;
  costPrice: number;
  kitchenStation: string;
  tags: string[];
}

function DishFormModal({
  open,
  editRecord,
  categories,
  onSubmit,
  onCancel,
}: {
  open: boolean;
  editRecord: DishRecord | null;
  categories: DishCategory[];
  onSubmit: (values: DishFormValues) => void;
  onCancel: () => void;
}) {
  const [form] = Form.useForm<DishFormValues>();

  useEffect(() => {
    if (open && editRecord) {
      form.setFieldsValue({
        name: editRecord.name,
        category: editRecord.category,
        price: editRecord.price,
        costPrice: editRecord.costPrice,
        kitchenStation: editRecord.kitchenStation,
        tags: editRecord.tags,
      });
    } else if (open) {
      form.resetFields();
    }
  }, [open, editRecord, form]);

  const handleOk = async () => {
    const values = await form.validateFields();
    onSubmit(values);
  };

  return (
    <Modal
      title={editRecord ? '编辑菜品' : '新增菜品'}
      open={open}
      onOk={handleOk}
      onCancel={onCancel}
      width={600}
      destroyOnClose
    >
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="name" label="菜品名称" rules={[{ required: true, message: '请输入菜品名称' }]}>
              <Input placeholder="如: 招牌剁椒鱼头" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="category" label="分类" rules={[{ required: true }]}>
              <Select placeholder="选择分类">
                {categories.map(c => (
                  <Select.Option key={c.id} value={c.name}>{c.name}</Select.Option>
                ))}
              </Select>
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={16}>
          <Col span={8}>
            <Form.Item name="price" label="售价（元）" rules={[{ required: true }]}>
              <InputNumber min={0} step={0.1} style={{ width: '100%' }} placeholder="0.00" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="costPrice" label="成本价（元）" rules={[{ required: true }]}>
              <InputNumber min={0} step={0.1} style={{ width: '100%' }} placeholder="0.00" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="kitchenStation" label="厨房档口" rules={[{ required: true }]}>
              <Select placeholder="选择档口">
                <Select.Option value="热菜档">热菜档</Select.Option>
                <Select.Option value="凉菜档">凉菜档</Select.Option>
                <Select.Option value="汤档">汤档</Select.Option>
                <Select.Option value="面点档">面点档</Select.Option>
                <Select.Option value="default">默认</Select.Option>
              </Select>
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="tags" label="标签">
          <Select mode="tags" placeholder="输入标签后回车">
            <Select.Option value="招牌">招牌</Select.Option>
            <Select.Option value="辣">辣</Select.Option>
            <Select.Option value="新品">新品</Select.Option>
            <Select.Option value="时令">时令</Select.Option>
            <Select.Option value="特色">特色</Select.Option>
            <Select.Option value="养生">养生</Select.Option>
          </Select>
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ── 主页面 ──

export function DishListPage() {
  const [dishes, setDishes] = useState<DishRecord[]>(MOCK_DISHES);
  const [categories] = useState<DishCategory[]>(MOCK_CATEGORIES);
  const [searchText, setSearchText] = useState('');
  const [filterCategory, setFilterCategory] = useState<string | undefined>();
  const [filterStatus, setFilterStatus] = useState<string | undefined>();
  const [modalOpen, setModalOpen] = useState(false);
  const [editRecord, setEditRecord] = useState<DishRecord | null>(null);

  // 统计
  const totalDishes = dishes.length;
  const onShelfCount = dishes.filter(d => d.status === 'on').length;
  const avgMargin = dishes.reduce((s, d) => s + d.marginRate, 0) / dishes.length;
  const lowMarginCount = dishes.filter(d => d.marginRate < MARGIN_THRESHOLD).length;

  // 筛选
  const filteredDishes = dishes.filter(d => {
    if (searchText && !d.name.includes(searchText) && !d.category.includes(searchText)) return false;
    if (filterCategory && d.category !== filterCategory) return false;
    if (filterStatus && d.status !== filterStatus) return false;
    return true;
  });

  const handleCreate = useCallback(() => {
    setEditRecord(null);
    setModalOpen(true);
  }, []);

  const handleEdit = useCallback((record: DishRecord) => {
    setEditRecord(record);
    setModalOpen(true);
  }, []);

  const handleSubmit = useCallback((values: DishFormValues) => {
    if (editRecord) {
      // 编辑
      setDishes(prev => prev.map(d => d.id === editRecord.id ? {
        ...d,
        ...values,
        marginRate: values.price > 0 ? (values.price - values.costPrice) / values.price : 0,
      } : d));
      message.success('菜品已更新');
    } else {
      // 新增
      const newDish: DishRecord = {
        id: `d${Date.now()}`,
        ...values,
        marginRate: values.price > 0 ? (values.price - values.costPrice) / values.price : 0,
        status: 'on',
        salesCount: 0,
        createdAt: new Date().toISOString().split('T')[0],
      };
      setDishes(prev => [...prev, newDish]);
      message.success('菜品已创建');
    }
    setModalOpen(false);
  }, [editRecord]);

  const handleToggleStatus = useCallback((record: DishRecord) => {
    const newStatus = record.status === 'on' ? 'off' : 'on';
    setDishes(prev => prev.map(d => d.id === record.id ? { ...d, status: newStatus } : d));
    message.success(newStatus === 'on' ? '已上架' : '已下架');
  }, []);

  const handleDelete = useCallback((id: string) => {
    setDishes(prev => prev.filter(d => d.id !== id));
    message.success('已删除');
  }, []);

  // ── 表格列定义 ──
  const columns: ColumnsType<DishRecord> = [
    {
      title: '菜品名称',
      dataIndex: 'name',
      width: 180,
      fixed: 'left',
      render: (name, record) => (
        <Space>
          <Text strong>{name}</Text>
          {record.tags.map(t => (
            <Tag key={t} color="default" style={{ fontSize: 12 }}>{t}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '分类',
      dataIndex: 'category',
      width: 100,
      filters: categories.map(c => ({ text: c.name, value: c.name })),
      onFilter: (value, record) => record.category === value,
    },
    {
      title: '售价',
      dataIndex: 'price',
      width: 100,
      align: 'right',
      sorter: (a, b) => a.price - b.price,
      render: (v: number) => <Text>¥{v.toFixed(2)}</Text>,
    },
    {
      title: '成本',
      dataIndex: 'costPrice',
      width: 100,
      align: 'right',
      render: (v: number) => <Text type="secondary">¥{v.toFixed(2)}</Text>,
    },
    {
      title: '毛利率',
      dataIndex: 'marginRate',
      width: 100,
      align: 'center',
      sorter: (a, b) => a.marginRate - b.marginRate,
      render: (rate: number) => <MarginTag rate={rate} />,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      align: 'center',
      render: (status: DishRecord['status']) => <StatusBadge status={status} />,
    },
    {
      title: '7天销量',
      dataIndex: 'salesCount',
      width: 100,
      align: 'right',
      sorter: (a, b) => a.salesCount - b.salesCount,
      render: (v: number) => <Text>{v}份</Text>,
    },
    {
      title: '厨房档口',
      dataIndex: 'kitchenStation',
      width: 100,
    },
    {
      title: '操作',
      width: 200,
      fixed: 'right',
      render: (_, record) => (
        <Space>
          <a onClick={() => handleEdit(record)}>编辑</a>
          <a onClick={() => handleToggleStatus(record)}>
            {record.status === 'on' ? '下架' : '上架'}
          </a>
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.id)}>
            <a style={{ color: '#A32D2D' }}>删除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: '24px 32px', background: '#FFFFFF', minHeight: '100vh' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>菜品管理</Title>
        <Text type="secondary">域B · 菜品列表 / 分类管理 / BOM配方 / 定价</Text>
      </div>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="菜品总数" value={totalDishes} suffix="道" />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="上架菜品" value={onShelfCount} suffix="道"
              valueStyle={{ color: '#0F6E56' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="平均毛利率" value={avgMargin * 100} precision={1} suffix="%"
              valueStyle={{ color: avgMargin >= MARGIN_THRESHOLD ? '#0F6E56' : '#A32D2D' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="低毛利菜品" value={lowMarginCount} suffix="道"
              valueStyle={{ color: lowMarginCount > 0 ? '#A32D2D' : '#0F6E56' }} />
          </Card>
        </Col>
      </Row>

      {/* 筛选栏 + 操作 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16, gap: 12, flexWrap: 'wrap' }}>
        <Space wrap>
          <Search
            placeholder="搜索菜品名称"
            allowClear
            onSearch={setSearchText}
            onChange={e => !e.target.value && setSearchText('')}
            style={{ width: 240 }}
          />
          <Select
            placeholder="分类"
            allowClear
            onChange={setFilterCategory}
            style={{ width: 140 }}
          >
            {categories.map(c => (
              <Select.Option key={c.id} value={c.name}>{c.name} ({c.dishCount})</Select.Option>
            ))}
          </Select>
          <Select
            placeholder="状态"
            allowClear
            onChange={setFilterStatus}
            style={{ width: 120 }}
          >
            <Select.Option value="on">上架</Select.Option>
            <Select.Option value="off">下架</Select.Option>
            <Select.Option value="soldout">沽清</Select.Option>
          </Select>
        </Space>
        <Button type="primary" onClick={handleCreate} style={{ background: '#FF6B35', borderColor: '#FF6B35' }}>
          新增菜品
        </Button>
      </div>

      {/* 菜品表格 */}
      <Table<DishRecord>
        columns={columns}
        dataSource={filteredDishes}
        rowKey="id"
        scroll={{ x: 1100 }}
        pagination={{
          defaultPageSize: 20,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 道菜品`,
        }}
        size="middle"
      />

      {/* 新增/编辑弹窗 */}
      <DishFormModal
        open={modalOpen}
        editRecord={editRecord}
        categories={categories}
        onSubmit={handleSubmit}
        onCancel={() => setModalOpen(false)}
      />
    </div>
  );
}
