/**
 * DishBatchPage — 菜品批量操作
 * 域B：批量上下架、批量调价、批量设置标签、批量转移分类、CSV导入导出
 * 技术栈：Ant Design 5.x + ProComponents
 */
import { useRef, useState, useEffect, useCallback } from 'react';
import { txFetch } from '../../api';
import {
  ProTable,
  ModalForm,
  ProFormSelect,
  ProFormRadio,
  ActionType,
  ProColumns,
} from '@ant-design/pro-components';
import {
  Button,
  Tag,
  Space,
  message,
  Modal,
  Form,
  InputNumber,
  Typography,
  Dropdown,
  Upload,
  Divider,
  Alert,
  Badge,
  Tooltip,
  Select,
} from 'antd';
import {
  CheckCircleOutlined,
  MinusCircleOutlined,
  DollarOutlined,
  TagsOutlined,
  FolderOpenOutlined,
  UploadOutlined,
  DownloadOutlined,
  CaretDownOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons';

const { Text } = Typography;

// ─── 类型定义 ───────────────────────────────────────────────

interface DishBatchItem {
  id: string;
  name: string;
  category_id: string;
  category_name: string;
  price_fen: number;
  status: 'on' | 'off';
  tags: ('recommended' | 'new' | 'limited')[];
}

// ─── 标签常量 ───────────────────────────────────────────────

const TAG_OPTIONS = [
  { label: '推荐', value: 'recommended' },
  { label: '新品', value: 'new' },
  { label: '限时', value: 'limited' },
];

// ─── API ────────────────────────────────────────────────────

interface CategoryOption { value: string; label: string; }

async function apiFetchDishes(page: number, catId?: string): Promise<{ items: DishBatchItem[]; total: number }> {
  try {
    const params = new URLSearchParams({ page: String(page) });
    if (catId) params.set('category_id', catId);
    const res = await txFetch<{ items: DishBatchItem[]; total: number }>(
      `/api/v1/menu/dishes?${params.toString()}`
    );
    return res ?? { items: [], total: 0 };
  } catch {
    return { items: [], total: 0 };
  }
}

async function apiBatchToggle(ids: string[], is_available: boolean): Promise<void> {
  await txFetch('/api/v1/menu/dishes/batch-toggle', {
    method: 'POST',
    body: JSON.stringify({ ids, is_available }),
  });
}

async function apiBatchPrice(ids: string[], price_fen: number): Promise<void> {
  await txFetch('/api/v1/menu/dishes/batch-price', {
    method: 'POST',
    body: JSON.stringify({ ids, price_fen }),
  });
}

async function apiFetchCategories(): Promise<CategoryOption[]> {
  try {
    const res = await txFetch<{ items: Array<{ category_id: string; category_name: string }> }>(
      '/api/v1/menu/categories'
    );
    return (res?.items ?? []).map((c) => ({ value: c.category_id, label: c.category_name }));
  } catch {
    return [];
  }
}

// ─── 工具函数 ────────────────────────────────────────────────

function fenToYuan(fen: number) {
  return `¥${(fen / 100).toFixed(2)}`;
}

function exportToCSV(dishes: DishBatchItem[], selectedIds: string[]) {
  const data = selectedIds.length > 0
    ? dishes.filter((d) => selectedIds.includes(d.id))
    : dishes;

  const header = '菜品名称,分类,价格,状态,标签';
  const rows = data.map((d) => [
    d.name,
    d.category_name,
    fenToYuan(d.price_fen),
    d.status === 'on' ? '上架' : '下架',
    d.tags.map((t) => ({ recommended: '推荐', new: '新品', limited: '限时' }[t])).join('/'),
  ].join(','));

  const csv = [header, ...rows].join('\n');
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `菜品数据_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── 调价弹窗组件 ────────────────────────────────────────────

interface PriceAdjustModalProps {
  open: boolean;
  selectedCount: number;
  onClose: () => void;
  onConfirm: (adjustType: 'ratio' | 'fixed', value: number) => void;
}

function PriceAdjustModal({ open, selectedCount, onClose, onConfirm }: PriceAdjustModalProps) {
  const [adjustType, setAdjustType] = useState<'ratio' | 'fixed'>('ratio');
  const [value, setValue] = useState<number>(0);

  const handleConfirm = () => {
    if (value === 0) {
      message.warning('调整值不能为0');
      return;
    }
    onConfirm(adjustType, value);
  };

  const previewText = adjustType === 'ratio'
    ? value >= 0
      ? `价格上调 ${value}%`
      : `价格下调 ${Math.abs(value)}%`
    : value >= 0
    ? `价格增加 ¥${(value / 100).toFixed(2)}`
    : `价格减少 ¥${(Math.abs(value) / 100).toFixed(2)}`;

  return (
    <Modal
      title={`批量调价 — 已选 ${selectedCount} 个菜品`}
      open={open}
      onCancel={onClose}
      onOk={handleConfirm}
      okText="确认调价"
      okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
      width={480}
    >
      <Alert
        type="warning"
        showIcon
        message="调价后将立即影响前台展示价格，请谨慎操作。"
        style={{ marginBottom: 16 }}
      />
      <Form layout="vertical">
        <Form.Item label="调整方式">
          <Select
            value={adjustType}
            onChange={(v) => setAdjustType(v)}
            options={[
              { label: '按比例调整（%）', value: 'ratio' },
              { label: '固定金额增减（分）', value: 'fixed' },
            ]}
            style={{ width: '100%' }}
          />
        </Form.Item>
        <Form.Item
          label={adjustType === 'ratio' ? '调整比例（正数涨价，负数降价）' : '调整金额（分，正数涨价，负数降价）'}
        >
          <InputNumber
            value={value}
            onChange={(v) => setValue(v ?? 0)}
            addonAfter={adjustType === 'ratio' ? '%' : '分'}
            min={-9999}
            max={9999}
            style={{ width: '100%' }}
            placeholder={adjustType === 'ratio' ? '如：10 表示涨价10%' : '如：100 表示涨价1元'}
          />
          {adjustType === 'fixed' && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              100分 = ¥1.00
            </Text>
          )}
        </Form.Item>
        {value !== 0 && (
          <div
            style={{
              padding: '10px 16px',
              background: '#fff3ed',
              borderRadius: 6,
              border: '1px solid #ffd8c0',
              color: '#FF6B35',
              fontWeight: 600,
            }}
          >
            预计效果：{previewText}
          </div>
        )}
      </Form>
    </Modal>
  );
}

// ─── 主组件 ─────────────────────────────────────────────────

export function DishBatchPage() {
  const actionRef = useRef<ActionType>();
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([]);
  const [priceModalOpen, setPriceModalOpen] = useState(false);
  const [tagModalOpen, setTagModalOpen] = useState(false);
  const [categoryModalOpen, setCategoryModalOpen] = useState(false);
  const [categories, setCategories] = useState<CategoryOption[]>([]);

  // 加载分类列表
  useEffect(() => {
    apiFetchCategories().then(setCategories);
  }, []);

  // ── 批量上架 ──
  const handleBatchOnline = useCallback(() => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要上架的菜品');
      return;
    }
    Modal.confirm({
      title: `确认上架 ${selectedRowKeys.length} 个菜品？`,
      icon: <CheckCircleOutlined style={{ color: '#0F6E56' }} />,
      onOk: async () => {
        try {
          await apiBatchToggle(selectedRowKeys, true);
          message.success(`已上架 ${selectedRowKeys.length} 个菜品`);
        } catch {
          message.error('操作失败，请重试');
        }
        setSelectedRowKeys([]);
        actionRef.current?.reload();
      },
    });
  }, [selectedRowKeys]);

  // ── 批量下架 ──
  const handleBatchOffline = useCallback(() => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要下架的菜品');
      return;
    }
    Modal.confirm({
      title: `确认下架 ${selectedRowKeys.length} 个菜品？`,
      icon: <ExclamationCircleOutlined style={{ color: '#A32D2D' }} />,
      content: '下架后顾客将无法看到这些菜品，请确认。',
      okText: '确认下架',
      okType: 'danger',
      onOk: async () => {
        try {
          await apiBatchToggle(selectedRowKeys, false);
          message.success(`已下架 ${selectedRowKeys.length} 个菜品`);
        } catch {
          message.error('操作失败，请重试');
        }
        setSelectedRowKeys([]);
        actionRef.current?.reload();
      },
    });
  }, [selectedRowKeys]);

  // ── 批量调价 ──
  const handlePriceAdjust = async (adjustType: 'ratio' | 'fixed', value: number) => {
    // 调价需要知道当前价格，这里用 fixed 方式直接传增减额；ratio 方式前端计算后批量调
    try {
      if (adjustType === 'fixed') {
        await apiBatchPrice(selectedRowKeys, value);
      } else {
        // ratio 模式：先获取当前菜品价格，再逐一计算（或由后端支持 ratio 参数）
        await txFetch('/api/v1/menu/dishes/batch-price', {
          method: 'POST',
          body: JSON.stringify({ ids: selectedRowKeys, adjust_type: 'ratio', ratio: value }),
        });
      }
      message.success(`已调整 ${selectedRowKeys.length} 个菜品的价格`);
    } catch {
      message.error('调价失败，请重试');
    }
    setPriceModalOpen(false);
    setSelectedRowKeys([]);
    actionRef.current?.reload();
  };

  // ── 批量设置标签 ──
  const handleBatchTag = async (values: { tags: ('recommended' | 'new' | 'limited')[] }) => {
    try {
      await txFetch('/api/v1/menu/dishes/batch-tags', {
        method: 'POST',
        body: JSON.stringify({ ids: selectedRowKeys, tags: values.tags }),
      });
      message.success(`已为 ${selectedRowKeys.length} 个菜品设置标签`);
    } catch {
      message.error('设置标签失败，请重试');
    }
    setSelectedRowKeys([]);
    actionRef.current?.reload();
    return true;
  };

  // ── 批量转移分类 ──
  const handleBatchCategory = async (values: { category_id: string }) => {
    const cat = categories.find((c) => c.value === values.category_id);
    try {
      await txFetch('/api/v1/menu/dishes/batch-category', {
        method: 'POST',
        body: JSON.stringify({ ids: selectedRowKeys, category_id: values.category_id }),
      });
      message.success(`已将 ${selectedRowKeys.length} 个菜品转移到「${cat?.label}」分类`);
    } catch {
      message.error('转移分类失败，请重试');
    }
    setSelectedRowKeys([]);
    actionRef.current?.reload();
    return true;
  };

  // ── 列定义 ──
  const columns: ProColumns<DishBatchItem>[] = [
    {
      title: '菜品名称',
      dataIndex: 'name',
      width: 160,
      render: (_, r) => <Text strong>{r.name}</Text>,
    },
    {
      title: '分类',
      dataIndex: 'category_id',
      width: 90,
      valueType: 'select',
      valueEnum: Object.fromEntries(categories.map((c) => [c.value, { text: c.label }])),
      render: (_, r) => <Tag>{r.category_name}</Tag>,
    },
    {
      title: '价格',
      dataIndex: 'price_fen',
      width: 90,
      search: false,
      render: (_, r) => (
        <Text style={{ color: '#FF6B35', fontWeight: 600 }}>
          {fenToYuan(r.price_fen)}
        </Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      valueType: 'select',
      valueEnum: {
        on: { text: '上架', status: 'Success' },
        off: { text: '下架', status: 'Default' },
      },
      render: (_, r) =>
        r.status === 'on' ? (
          <Badge status="success" text="上架" />
        ) : (
          <Badge status="default" text="下架" />
        ),
    },
    {
      title: '标签',
      dataIndex: 'tags',
      search: false,
      render: (_, r) => (
        <Space size={4}>
          {r.tags.length === 0 ? (
            <Text type="secondary" style={{ fontSize: 12 }}>无</Text>
          ) : (
            r.tags.map((tag) => (
              <Tag
                key={tag}
                color={tag === 'recommended' ? 'orange' : tag === 'new' ? 'green' : 'gold'}
                style={{ fontSize: 11 }}
              >
                {tag === 'recommended' ? '推荐' : tag === 'new' ? '新品' : '限时'}
              </Tag>
            ))
          )}
        </Space>
      ),
    },
  ];

  const selectedCount = selectedRowKeys.length;

  return (
    <div>
      {/* 批量操作提示条 */}
      {selectedCount > 0 && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={
            <span>
              已选 <Text strong style={{ color: '#FF6B35' }}>{selectedCount}</Text> 个菜品
              <Divider type="vertical" />
              <Space size={8}>
                <Button size="small" icon={<CheckCircleOutlined />} onClick={handleBatchOnline}>
                  批量上架
                </Button>
                <Button size="small" danger icon={<MinusCircleOutlined />} onClick={handleBatchOffline}>
                  批量下架
                </Button>
                <Button size="small" icon={<DollarOutlined />} onClick={() => setPriceModalOpen(true)}>
                  批量调价
                </Button>
                <Button size="small" icon={<TagsOutlined />} onClick={() => setTagModalOpen(true)}>
                  设置标签
                </Button>
                <Button size="small" icon={<FolderOpenOutlined />} onClick={() => setCategoryModalOpen(true)}>
                  转移分类
                </Button>
                <Button
                  size="small"
                  icon={<DownloadOutlined />}
                  onClick={async () => {
                    try {
                      const res = await apiFetchDishes(1);
                      exportToCSV(res.items, selectedRowKeys);
                      message.success(`已导出 ${selectedCount} 个菜品的CSV文件`);
                    } catch {
                      message.error('导出失败');
                    }
                  }}
                >
                  导出所选
                </Button>
              </Space>
            </span>
          }
        />
      )}

      {/* 批量调价弹窗 */}
      <PriceAdjustModal
        open={priceModalOpen}
        selectedCount={selectedCount}
        onClose={() => setPriceModalOpen(false)}
        onConfirm={handlePriceAdjust}
      />

      {/* 批量设置标签 ModalForm */}
      <ModalForm
        title={`批量设置标签 — 已选 ${selectedCount} 个菜品`}
        open={tagModalOpen}
        onOpenChange={setTagModalOpen}
        onFinish={handleBatchTag}
        modalProps={{ width: 440 }}
        initialValues={{ tags: [] }}
      >
        <Alert
          type="warning"
          showIcon
          message="将覆盖所选菜品已有的标签设置。"
          style={{ marginBottom: 16 }}
        />
        <ProFormSelect
          name="tags"
          label="标签"
          options={TAG_OPTIONS}
          fieldProps={{ mode: 'multiple' }}
          placeholder="选择要设置的标签（可多选）"
          extra="不选任何标签则清空所选菜品的所有标签"
        />
      </ModalForm>

      {/* 批量转移分类 ModalForm */}
      <ModalForm
        title={`批量转移分类 — 已选 ${selectedCount} 个菜品`}
        open={categoryModalOpen}
        onOpenChange={setCategoryModalOpen}
        onFinish={handleBatchCategory}
        modalProps={{ width: 440 }}
      >
        <Alert
          type="info"
          showIcon
          message="转移分类后，菜品将从原分类移出，前台显示位置将变更。"
          style={{ marginBottom: 16 }}
        />
        <ProFormSelect
          name="category_id"
          label="目标分类"
          options={categories}
          rules={[{ required: true, message: '请选择目标分类' }]}
          placeholder="选择目标分类"
        />
      </ModalForm>

      {/* ProTable 主列表 */}
      <ProTable<DishBatchItem>
        actionRef={actionRef}
        columns={columns}
        rowKey="id"
        headerTitle="批量操作管理"
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys as string[]),
          preserveSelectedRowKeys: true,
        }}
        request={async (params) => {
          const page = params.current ?? 1;
          const catId = params.category_id as string | undefined;
          const result = await apiFetchDishes(page, catId);
          return { data: result.items, total: result.total, success: true };
        }}
        search={{
          labelWidth: 'auto',
          filterType: 'light',
        }}
        toolBarRender={() => [
          <Tooltip key="import" title="支持CSV格式，字段：菜品名/分类/价格/状态">
            <Upload
              accept=".csv"
              showUploadList={false}
              beforeUpload={() => {
                message.success('CSV导入成功（Mock）');
                return false;
              }}
            >
              <Button icon={<UploadOutlined />}>导入CSV</Button>
            </Upload>
          </Tooltip>,
          <Dropdown
            key="export"
            menu={{
              items: [
                {
                  key: 'export-all',
                  label: '导出全部',
                  icon: <DownloadOutlined />,
                  onClick: async () => {
                    try {
                      const res = await apiFetchDishes(1);
                      exportToCSV(res.items, []);
                      message.success(`已导出 ${res.items.length} 个菜品的CSV文件`);
                    } catch {
                      message.error('导出失败');
                    }
                  },
                },
                {
                  key: 'export-selected',
                  label: selectedCount > 0 ? `导出所选（${selectedCount}）` : '导出所选（请先选中）',
                  icon: <DownloadOutlined />,
                  disabled: selectedCount === 0,
                  onClick: async () => {
                    try {
                      const res = await apiFetchDishes(1);
                      exportToCSV(res.items, selectedRowKeys);
                      message.success(`已导出 ${selectedCount} 个菜品的CSV文件`);
                    } catch {
                      message.error('导出失败');
                    }
                  },
                },
              ],
            }}
          >
            <Button icon={<DownloadOutlined />}>
              导出 <CaretDownOutlined />
            </Button>
          </Dropdown>,
          <ProFormRadio.Group
            key="status-filter"
            name="status"
            fieldProps={{
              optionType: 'button',
              buttonStyle: 'solid',
              options: [
                { label: '全部', value: '' },
                { label: '上架中', value: 'on' },
                { label: '已下架', value: 'off' },
              ],
            }}
          />,
        ]}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        cardBordered
        scroll={{ x: 800 }}
      />
    </div>
  );
}
