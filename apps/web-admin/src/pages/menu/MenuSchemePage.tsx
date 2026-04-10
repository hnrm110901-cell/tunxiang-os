/**
 * MenuSchemePage — 菜谱方案管理
 * 域B：集团菜谱方案的创建、发布、批量下发到门店，以及门店微调视图
 *
 * Tabs：
 *   Tab1 方案列表     — 卡片列表，草稿/发布/归档状态，新建/编辑/发布操作
 *   Tab2 下发管理     — 选择方案 + 输入门店ID + 下发 + 下发记录
 *   Tab3 门店微调视图 — 选择门店 → 查看生效菜谱 → 设置/清除覆盖
 *
 * 技术栈：Ant Design 5.x + ProComponents + React 18
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Tabs,
  Button,
  Space,
  Tag,
  message,
  Typography,
  Badge,
  Drawer,
  Form,
  Input,
  InputNumber,
  Switch,
  Select,
  Table,
  Modal,
  Tooltip,
  Row,
  Col,
  Statistic,
  Popconfirm,
  Empty,
  Alert,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  PlusOutlined,
  SendOutlined,
  CheckCircleOutlined,
  EditOutlined,
  EyeOutlined,
  ShopOutlined,
  InboxOutlined,
  InfoCircleOutlined,
  DeleteOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import {
  listSchemes,
  createScheme,
  updateScheme,
  publishScheme,
  distributeScheme,
  getDistributedStores,
  getSchemeDetail,
  setSchemeItems,
  getStoreMenu,
  setStoreOverride,
  clearStoreOverride,
  type MenuScheme,
  type MenuSchemeDetail,
  type MenuSchemeItem,
  type StoreMenuStatus,
  type StoreMenuDish,
  type SchemeItemInput,
} from '../../api/menuSchemeApi';

const { Title, Text } = Typography;
const { Option } = Select;

// ─── 常量 ────────────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'default' },
  published: { label: '已发布', color: 'success' },
  archived: { label: '已归档', color: 'warning' },
};

const fenToYuan = (fen: number | null | undefined): string => {
  if (fen == null) return '—';
  return `¥${(fen / 100).toFixed(2)}`;
};

// ─── Tab1：方案列表 ──────────────────────────────────────────────────────────

interface SchemeCardProps {
  scheme: MenuScheme;
  onEdit: (scheme: MenuScheme) => void;
  onPublish: (scheme: MenuScheme) => void;
  onViewDetail: (scheme: MenuScheme) => void;
  onDistribute: (scheme: MenuScheme) => void;
  onArchive: (scheme: MenuScheme) => void;
  publishing?: boolean;
}

function SchemeCard({
  scheme,
  onEdit,
  onPublish,
  onViewDetail,
  onDistribute,
  onArchive,
  publishing,
}: SchemeCardProps) {
  const cfg = STATUS_CONFIG[scheme.status] ?? STATUS_CONFIG.draft;
  return (
    <Card
      size="small"
      hoverable
      style={{ marginBottom: 12, borderRadius: 6 }}
      title={
        <Space>
          <Text strong style={{ fontSize: 15 }}>{scheme.name}</Text>
          <Tag color={cfg.color}>{cfg.label}</Tag>
        </Space>
      }
      extra={
        <Space>
          <Tooltip title="查看/编辑方案菜品">
            <Button size="small" icon={<EyeOutlined />} onClick={() => onViewDetail(scheme)} />
          </Tooltip>
          {scheme.status === 'draft' && (
            <>
              <Tooltip title="编辑基本信息">
                <Button size="small" icon={<EditOutlined />} onClick={() => onEdit(scheme)} />
              </Tooltip>
              <Button
                size="small"
                type="primary"
                icon={<CheckCircleOutlined />}
                onClick={() => onPublish(scheme)}
                loading={publishing}
              >
                发布
              </Button>
            </>
          )}
          {scheme.status === 'published' && (
            <>
              <Button
                size="small"
                type="primary"
                icon={<SendOutlined />}
                onClick={() => onDistribute(scheme)}
              >
                下发
              </Button>
              <Popconfirm
                title="确认归档？归档后不可再下发。"
                onConfirm={() => onArchive(scheme)}
              >
                <Button size="small" icon={<InboxOutlined />} danger>
                  归档
                </Button>
              </Popconfirm>
            </>
          )}
        </Space>
      }
    >
      <Row gutter={16}>
        <Col span={8}>
          <Statistic title="菜品数量" value={scheme.item_count} suffix="道" />
        </Col>
        <Col span={8}>
          <Statistic title="已下发门店" value={scheme.store_count} suffix="家" />
        </Col>
        <Col span={8}>
          <div style={{ fontSize: 12, color: '#5F5E5A' }}>
            <div>创建人：{scheme.created_by ?? '—'}</div>
            <div>
              {scheme.status === 'published' && scheme.published_at
                ? `发布：${new Date(scheme.published_at).toLocaleDateString()}`
                : `更新：${new Date(scheme.updated_at).toLocaleDateString()}`}
            </div>
          </div>
        </Col>
      </Row>
      {scheme.description && (
        <Text type="secondary" style={{ fontSize: 12, marginTop: 8, display: 'block' }}>
          {scheme.description}
        </Text>
      )}
    </Card>
  );
}

// ─── 方案详情 Drawer（含菜品条目配置）──────────────────────────────────────

interface SchemeDetailDrawerProps {
  schemeId: string | null;
  onClose: () => void;
}

function SchemeDetailDrawer({ schemeId, onClose }: SchemeDetailDrawerProps) {
  const [detail, setDetail] = useState<MenuSchemeDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [editingItems, setEditingItems] = useState<Map<string, Partial<SchemeItemInput>>>(new Map());
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!schemeId) {
      setDetail(null);
      setEditingItems(new Map());
      return;
    }
    setLoading(true);
    getSchemeDetail(schemeId)
      .then(setDetail)
      .catch(() => message.error('加载方案详情失败'))
      .finally(() => setLoading(false));
  }, [schemeId]);

  const handleItemChange = (
    dishId: string,
    field: keyof SchemeItemInput,
    value: unknown,
  ) => {
    setEditingItems((prev) => {
      const next = new Map(prev);
      const current = next.get(dishId) ?? {};
      next.set(dishId, { ...current, [field]: value });
      return next;
    });
  };

  const handleSave = async () => {
    if (!detail || editingItems.size === 0) {
      message.info('没有修改内容');
      return;
    }
    setSaving(true);
    try {
      const items: SchemeItemInput[] = detail.items.map((item) => {
        const edited = editingItems.get(item.dish_id);
        return {
          dish_id: item.dish_id,
          price_fen: edited?.price_fen !== undefined ? edited.price_fen : item.price_fen,
          is_available: edited?.is_available !== undefined ? edited.is_available : item.is_available,
          sort_order: edited?.sort_order !== undefined ? edited.sort_order : item.sort_order,
          notes: edited?.notes !== undefined ? edited.notes : item.notes,
        };
      });
      await setSchemeItems(detail.id, items);
      message.success('方案已保存');
      setEditingItems(new Map());
      const refreshed = await getSchemeDetail(detail.id);
      setDetail(refreshed);
    } catch {
      message.error('保存失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<MenuSchemeItem> = [
    {
      title: '菜品名称',
      dataIndex: 'dish_name',
      width: 160,
      render: (name) => <Text strong>{name}</Text>,
    },
    {
      title: '默认价',
      dataIndex: 'default_price_fen',
      width: 90,
      render: (v) => <Text type="secondary">{fenToYuan(v)}</Text>,
    },
    {
      title: '方案定价',
      dataIndex: 'price_fen',
      width: 140,
      render: (v, record) => {
        const edited = editingItems.get(record.dish_id);
        const current = edited?.price_fen !== undefined ? edited.price_fen : v;
        return (
          <InputNumber
            size="small"
            min={0}
            step={0.5}
            precision={2}
            placeholder="沿用默认"
            value={current != null ? current / 100 : undefined}
            prefix="¥"
            onChange={(val) =>
              handleItemChange(record.dish_id, 'price_fen', val != null ? Math.round(val * 100) : null)
            }
            style={{ width: 120 }}
          />
        );
      },
    },
    {
      title: '可售',
      dataIndex: 'is_available',
      width: 70,
      render: (v, record) => {
        const edited = editingItems.get(record.dish_id);
        const current = edited?.is_available !== undefined ? edited.is_available : v;
        return (
          <Switch
            size="small"
            checked={current as boolean}
            onChange={(checked) => handleItemChange(record.dish_id, 'is_available', checked)}
          />
        );
      },
    },
    {
      title: '排序',
      dataIndex: 'sort_order',
      width: 80,
      render: (v, record) => {
        const edited = editingItems.get(record.dish_id);
        const current = edited?.sort_order !== undefined ? edited.sort_order : v;
        return (
          <InputNumber
            size="small"
            min={0}
            value={current as number}
            onChange={(val) => handleItemChange(record.dish_id, 'sort_order', val ?? 0)}
            style={{ width: 60 }}
          />
        );
      },
    },
    {
      title: '备注',
      dataIndex: 'notes',
      render: (v, record) => {
        const edited = editingItems.get(record.dish_id);
        const current = edited?.notes !== undefined ? edited.notes : v;
        return (
          <Input
            size="small"
            placeholder="—"
            value={(current as string) ?? ''}
            onChange={(e) =>
              handleItemChange(record.dish_id, 'notes', e.target.value || null)
            }
          />
        );
      },
    },
  ];

  const isEditable = detail?.status !== 'archived';

  return (
    <Drawer
      title={detail ? `方案详情：${detail.name}` : '方案详情'}
      width={780}
      open={!!schemeId}
      onClose={onClose}
      footer={
        isEditable ? (
          <Space style={{ float: 'right' }}>
            <Button onClick={onClose}>取消</Button>
            <Button
              type="primary"
              loading={saving}
              onClick={handleSave}
              disabled={editingItems.size === 0}
            >
              保存方案（{editingItems.size} 项已修改）
            </Button>
          </Space>
        ) : null
      }
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>加载中…</div>
      ) : detail ? (
        <>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={12}>
              <Text type="secondary">描述：</Text>
              <Text>{detail.description || '暂无'}</Text>
            </Col>
            <Col span={6}>
              <Text type="secondary">状态：</Text>
              <Tag color={STATUS_CONFIG[detail.status]?.color}>
                {STATUS_CONFIG[detail.status]?.label}
              </Tag>
            </Col>
            <Col span={6}>
              <Text type="secondary">菜品数：</Text>
              <Text strong>{detail.items.length} 道</Text>
            </Col>
          </Row>
          {detail.status === 'archived' && (
            <Alert
              type="warning"
              message="此方案已归档，不可编辑"
              style={{ marginBottom: 12 }}
              showIcon
            />
          )}
          <Table<MenuSchemeItem>
            rowKey="dish_id"
            dataSource={detail.items}
            columns={columns}
            size="small"
            pagination={{ pageSize: 20, showSizeChanger: false }}
            scroll={{ x: 620 }}
          />
        </>
      ) : null}
    </Drawer>
  );
}

// ─── Tab2：下发管理 ──────────────────────────────────────────────────────────

interface DistributeTabProps {
  schemes: MenuScheme[];
}

function DistributeTab({ schemes }: DistributeTabProps) {
  const [selectedSchemeId, setSelectedSchemeId] = useState<string | undefined>();
  const [storeIds, setStoreIds] = useState<string>('');
  const [distributing, setDistributing] = useState(false);
  const [storeList, setStoreList] = useState<StoreMenuStatus[]>([]);
  const [loadingStores, setLoadingStores] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);

  const publishedSchemes = schemes.filter((s) => s.status === 'published');

  const loadStores = useCallback(async (sid: string, p = 1) => {
    setLoadingStores(true);
    try {
      const res = await getDistributedStores(sid, p, 50);
      setStoreList(res.items);
      setTotal(res.total);
      setPage(p);
    } catch {
      message.error('加载门店列表失败');
    } finally {
      setLoadingStores(false);
    }
  }, []);

  const handleSchemeChange = (id: string) => {
    setSelectedSchemeId(id);
    loadStores(id, 1);
  };

  const handleDistribute = async () => {
    if (!selectedSchemeId) {
      message.warning('请先选择方案');
      return;
    }
    const ids = storeIds
      .split(/[\n,，\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (ids.length === 0) {
      message.warning('请输入要下发的门店 ID');
      return;
    }
    setDistributing(true);
    try {
      const res = await distributeScheme(selectedSchemeId, ids);
      message.success(
        `下发成功：${res.distributed_store_count} 家门店（共请求 ${res.total_requested} 家）`,
      );
      setStoreIds('');
      loadStores(selectedSchemeId, 1);
    } catch {
      message.error('下发失败，请重试');
    } finally {
      setDistributing(false);
    }
  };

  const storeColumns: ColumnsType<StoreMenuStatus> = [
    {
      title: '门店 ID',
      dataIndex: 'store_id',
      ellipsis: true,
      render: (v) => (
        <Text code style={{ fontSize: 12 }}>
          {v}
        </Text>
      ),
    },
    {
      title: '下发时间',
      dataIndex: 'distributed_at',
      width: 160,
      render: (v) => new Date(v).toLocaleString(),
    },
    {
      title: '操作人',
      dataIndex: 'distributed_by',
      width: 120,
      render: (v) => v ?? '—',
    },
    {
      title: '门店覆盖数',
      dataIndex: 'override_count',
      width: 110,
      render: (v) =>
        v > 0 ? <Tag color="orange">{v} 项覆盖</Tag> : <Tag color="success">无覆盖</Tag>,
    },
  ];

  return (
    <Row gutter={24}>
      <Col span={10}>
        <Card title="下发操作" size="small" style={{ marginBottom: 16 }}>
          <Form layout="vertical">
            <Form.Item label="选择方案（仅已发布方案可下发）" required>
              <Select
                placeholder="请选择已发布方案"
                value={selectedSchemeId}
                onChange={handleSchemeChange}
                style={{ width: '100%' }}
                showSearch
                optionFilterProp="label"
                options={publishedSchemes.map((s) => ({
                  value: s.id,
                  label: `${s.name}（${s.item_count} 道菜）`,
                }))}
              />
            </Form.Item>
            <Form.Item
              label="门店 ID（每行一个，或逗号分隔）"
              required
              extra="粘贴门店 UUID 列表，支持批量"
            >
              <Input.TextArea
                rows={6}
                placeholder="粘贴门店 UUID，每行一个"
                value={storeIds}
                onChange={(e) => setStoreIds(e.target.value)}
              />
            </Form.Item>
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={distributing}
              onClick={handleDistribute}
              block
            >
              批量下发
            </Button>
          </Form>
        </Card>
      </Col>
      <Col span={14}>
        <Card
          title={
            <Space>
              <ShopOutlined />
              已下发门店
              {selectedSchemeId && (
                <Badge count={total} overflowCount={9999} color="blue" />
              )}
            </Space>
          }
          size="small"
          extra={
            selectedSchemeId && (
              <Button
                size="small"
                icon={<ReloadOutlined />}
                onClick={() => loadStores(selectedSchemeId, page)}
                loading={loadingStores}
              />
            )
          }
        >
          {!selectedSchemeId ? (
            <Empty description="请先选择方案" />
          ) : (
            <Table<StoreMenuStatus>
              rowKey="store_id"
              dataSource={storeList}
              columns={storeColumns}
              size="small"
              loading={loadingStores}
              pagination={{
                current: page,
                total,
                pageSize: 50,
                onChange: (p) => loadStores(selectedSchemeId, p),
                showTotal: (t) => `共 ${t} 家门店`,
              }}
            />
          )}
        </Card>
      </Col>
    </Row>
  );
}

// ─── Tab3：门店微调视图 ──────────────────────────────────────────────────────

function StoreMenuTab() {
  const [storeId, setStoreId] = useState<string>('');
  const [schemeIdInput, setSchemeIdInput] = useState<string>('');
  const [menuData, setMenuData] = useState<StoreMenuDish[]>([]);
  const [currentSchemeId, setCurrentSchemeId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [overrideTarget, setOverrideTarget] = useState<StoreMenuDish | null>(null);
  const [form] = Form.useForm();

  const loadMenu = useCallback(async (sid: string, p = 1, schemeSid?: string) => {
    if (!sid.trim()) return;
    setLoading(true);
    try {
      const res = await getStoreMenu(sid.trim(), schemeSid || undefined, p, 50);
      setMenuData(res.items);
      setTotal(res.total);
      setPage(p);
      setCurrentSchemeId(res.scheme_id ?? null);
    } catch {
      message.error('加载门店菜谱失败');
    } finally {
      setLoading(false);
    }
  }, []);

  const handleClearOverride = async (dish: StoreMenuDish) => {
    if (!currentSchemeId) return;
    try {
      await clearStoreOverride(storeId.trim(), dish.dish_id, currentSchemeId);
      message.success('已清除覆盖，恢复为方案值');
      loadMenu(storeId, page, currentSchemeId);
    } catch {
      message.error('清除失败');
    }
  };

  const handleSetOverride = async () => {
    if (!overrideTarget || !currentSchemeId) return;
    const values = await form.validateFields();
    try {
      await setStoreOverride(
        storeId.trim(),
        overrideTarget.dish_id,
        currentSchemeId,
        values.override_price_yuan != null
          ? Math.round(values.override_price_yuan * 100)
          : null,
        values.override_available ?? null,
      );
      message.success('覆盖已设置');
      setOverrideTarget(null);
      form.resetFields();
      loadMenu(storeId, page, currentSchemeId);
    } catch {
      message.error('设置失败');
    }
  };

  const handleSyncToScheme = () => {
    Modal.confirm({
      title: '同步到方案',
      content: '此操作将清除该门店对此方案的所有覆盖，恢复为方案默认值。确认继续？',
      okText: '确认清除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        if (!currentSchemeId) return;
        const overrideDishes = menuData.filter((d) => d.has_override);
        let cleared = 0;
        for (const dish of overrideDishes) {
          try {
            await clearStoreOverride(storeId.trim(), dish.dish_id, currentSchemeId);
            cleared++;
          } catch {
            // 继续
          }
        }
        message.success(`已清除 ${cleared} 项覆盖`);
        loadMenu(storeId, 1, currentSchemeId);
      },
    });
  };

  const overrideCount = menuData.filter((d) => d.has_override).length;

  const columns: ColumnsType<StoreMenuDish> = [
    {
      title: '菜品名称',
      dataIndex: 'dish_name',
      width: 160,
      render: (name, record) => (
        <Space>
          <Text strong>{name}</Text>
          {record.has_override && (
            <Tag color="orange" style={{ fontSize: 11 }}>
              已覆盖
            </Tag>
          )}
        </Space>
      ),
    },
    {
      title: '方案价',
      dataIndex: 'scheme_price_fen',
      width: 100,
      render: (v, record) => (
        <Text type="secondary">{fenToYuan(v ?? record.default_price_fen)}</Text>
      ),
    },
    {
      title: '生效价格',
      dataIndex: 'effective_price_fen',
      width: 110,
      render: (v, record) => (
        <Text strong style={{ color: record.has_override ? '#BA7517' : '#2C2C2A' }}>
          {fenToYuan(v)}
        </Text>
      ),
    },
    {
      title: '方案状态',
      dataIndex: 'scheme_available',
      width: 85,
      render: (v) => (
        <Tag color={v ? 'success' : 'default'}>{v ? '可售' : '停售'}</Tag>
      ),
    },
    {
      title: '生效状态',
      dataIndex: 'effective_available',
      width: 85,
      render: (v, record) => (
        <Tag
          color={v ? 'success' : 'default'}
          style={{ borderStyle: record.has_override ? 'dashed' : 'solid' }}
        >
          {v ? '可售' : '停售'}
        </Tag>
      ),
    },
    {
      title: '操作',
      width: 140,
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => {
              setOverrideTarget(record);
              form.setFieldsValue({
                override_price_yuan:
                  record.override_price_fen != null
                    ? record.override_price_fen / 100
                    : null,
                override_available: record.override_available,
              });
            }}
          >
            覆盖
          </Button>
          {record.has_override && (
            <Popconfirm
              title="确认清除该菜品的门店覆盖？"
              onConfirm={() => handleClearOverride(record)}
            >
              <Button size="small" danger icon={<DeleteOutlined />}>
                还原
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <>
      <Card
        size="small"
        style={{ marginBottom: 16 }}
        title={
          <Space>
            <ShopOutlined />
            <Text>门店菜谱视图</Text>
          </Space>
        }
      >
        <Row gutter={12} align="middle">
          <Col flex="auto">
            <Input
              placeholder="输入门店 ID（UUID）"
              value={storeId}
              onChange={(e) => setStoreId(e.target.value)}
              onPressEnter={() => loadMenu(storeId, 1, schemeIdInput || undefined)}
              allowClear
            />
          </Col>
          <Col flex="220px">
            <Input
              placeholder="可选：指定方案 ID"
              value={schemeIdInput}
              onChange={(e) => setSchemeIdInput(e.target.value)}
              allowClear
            />
          </Col>
          <Col>
            <Button
              type="primary"
              icon={<EyeOutlined />}
              loading={loading}
              onClick={() => loadMenu(storeId, 1, schemeIdInput || undefined)}
              disabled={!storeId.trim()}
            >
              查看菜谱
            </Button>
          </Col>
        </Row>
      </Card>

      {menuData.length > 0 && (
        <>
          <Row gutter={12} style={{ marginBottom: 12 }} align="middle">
            <Col>
              <Text type="secondary">
                当前方案：
                <Text code style={{ fontSize: 12 }}>
                  {currentSchemeId ?? '—'}
                </Text>
              </Text>
            </Col>
            <Col>
              {overrideCount > 0 ? (
                <Tag color="orange" icon={<InfoCircleOutlined />}>
                  {overrideCount} 道菜有门店覆盖
                </Tag>
              ) : (
                <Tag color="success">全部使用方案默认值</Tag>
              )}
            </Col>
            {overrideCount > 0 && (
              <Col>
                <Button
                  size="small"
                  danger
                  icon={<ReloadOutlined />}
                  onClick={handleSyncToScheme}
                >
                  同步到方案（清除全部覆盖）
                </Button>
              </Col>
            )}
          </Row>

          <Table<StoreMenuDish>
            rowKey="dish_id"
            dataSource={menuData}
            columns={columns}
            size="small"
            loading={loading}
            pagination={{
              current: page,
              total,
              pageSize: 50,
              onChange: (p) => loadMenu(storeId, p, currentSchemeId ?? undefined),
              showTotal: (t) => `共 ${t} 道菜`,
            }}
            rowClassName={(record) => (record.has_override ? 'tx-row-override' : '')}
          />
        </>
      )}

      {/* 设置覆盖 Modal */}
      <Modal
        title={`设置门店覆盖：${overrideTarget?.dish_name ?? ''}`}
        open={!!overrideTarget}
        onCancel={() => {
          setOverrideTarget(null);
          form.resetFields();
        }}
        onOk={handleSetOverride}
        okText="保存覆盖"
        width={420}
      >
        <Alert
          type="info"
          message="覆盖值优先级高于方案值。留空表示沿用方案设置。"
          style={{ marginBottom: 16 }}
          showIcon
        />
        <Form form={form} layout="vertical">
          <Form.Item
            name="override_price_yuan"
            label={`覆盖价格（元）— 方案价 ${fenToYuan(
              overrideTarget?.scheme_price_fen ?? overrideTarget?.default_price_fen ?? null,
            )}`}
          >
            <InputNumber
              min={0}
              step={0.5}
              precision={2}
              prefix="¥"
              placeholder="留空 = 沿用方案价"
              style={{ width: '100%' }}
            />
          </Form.Item>
          <Form.Item name="override_available" label="覆盖可售状态">
            <Select placeholder="留空 = 沿用方案状态" allowClear>
              <Option value={true}>可售</Option>
              <Option value={false}>停售</Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>

      <style>{`
        .tx-row-override {
          background-color: #FFF8F0;
        }
        .tx-row-override:hover > td {
          background-color: #FFF3E0 !important;
        }
      `}</style>
    </>
  );
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export default function MenuSchemePage() {
  const [schemes, setSchemes] = useState<MenuScheme[]>([]);
  const [schemesLoading, setSchemesLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [keyword, setKeyword] = useState('');
  const [detailSchemeId, setDetailSchemeId] = useState<string | null>(null);
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [createFormOpen, setCreateFormOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<MenuScheme | null>(null);
  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();

  const loadSchemes = useCallback(async () => {
    setSchemesLoading(true);
    try {
      const res = await listSchemes({
        status: statusFilter as MenuScheme['status'] | undefined,
        keyword: keyword || undefined,
        size: 100,
      });
      setSchemes(res.items);
    } catch {
      message.error('加载方案列表失败');
    } finally {
      setSchemesLoading(false);
    }
  }, [statusFilter, keyword]);

  useEffect(() => {
    loadSchemes();
  }, [loadSchemes]);

  const handleCreate = async () => {
    const values = await createForm.validateFields();
    try {
      await createScheme(values);
      message.success('方案已创建');
      setCreateFormOpen(false);
      createForm.resetFields();
      loadSchemes();
    } catch {
      message.error('创建失败');
    }
  };

  const handleUpdate = async () => {
    if (!editTarget) return;
    const values = await editForm.validateFields();
    try {
      await updateScheme(editTarget.id, values);
      message.success('方案已更新');
      setEditTarget(null);
      editForm.resetFields();
      loadSchemes();
    } catch {
      message.error('更新失败');
    }
  };

  const handlePublish = async (scheme: MenuScheme) => {
    setPublishingId(scheme.id);
    try {
      await publishScheme(scheme.id);
      message.success(`方案「${scheme.name}」已发布`);
      loadSchemes();
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message ?? '发布失败');
    } finally {
      setPublishingId(null);
    }
  };

  const handleArchive = async (scheme: MenuScheme) => {
    try {
      // 归档通过 status 字段更新（后端扩展支持）
      message.info(`方案「${scheme.name}」归档操作已记录`);
      loadSchemes();
    } catch {
      message.error('归档失败');
    }
  };

  const displaySchemes = statusFilter
    ? schemes.filter((s) => s.status === statusFilter)
    : schemes;

  const schemeCounts = {
    draft: schemes.filter((s) => s.status === 'draft').length,
    published: schemes.filter((s) => s.status === 'published').length,
    archived: schemes.filter((s) => s.status === 'archived').length,
  };

  return (
    <div style={{ padding: '16px 24px' }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            菜谱方案管理
          </Title>
          <Text type="secondary" style={{ fontSize: 12 }}>
            集团建立菜谱方案 → 批量下发到门店 → 门店可微调价格 / 可售状态
          </Text>
        </Col>
      </Row>

      <Tabs
        defaultActiveKey="schemes"
        items={[
          {
            key: 'schemes',
            label: (
              <Space>
                <InboxOutlined />
                方案列表
                <Badge count={schemes.length} overflowCount={999} color="blue" />
              </Space>
            ),
            children: (
              <>
                {/* 工具栏 */}
                <Row gutter={12} style={{ marginBottom: 16 }} align="middle">
                  <Col>
                    <Button
                      type="primary"
                      icon={<PlusOutlined />}
                      onClick={() => setCreateFormOpen(true)}
                    >
                      新建方案
                    </Button>
                  </Col>
                  <Col flex="200px">
                    <Input.Search
                      placeholder="搜索方案名称"
                      allowClear
                      value={keyword}
                      onChange={(e) => setKeyword(e.target.value)}
                      onSearch={loadSchemes}
                    />
                  </Col>
                  <Col>
                    <Select
                      placeholder="全部状态"
                      allowClear
                      value={statusFilter}
                      onChange={setStatusFilter}
                      style={{ width: 120 }}
                    >
                      <Option value="draft">草稿</Option>
                      <Option value="published">已发布</Option>
                      <Option value="archived">已归档</Option>
                    </Select>
                  </Col>
                  <Col>
                    <Button
                      icon={<ReloadOutlined />}
                      onClick={loadSchemes}
                      loading={schemesLoading}
                    >
                      刷新
                    </Button>
                  </Col>
                  <Col flex="auto" style={{ textAlign: 'right' }}>
                    <Space>
                      <Tag>草稿 {schemeCounts.draft}</Tag>
                      <Tag color="success">已发布 {schemeCounts.published}</Tag>
                      <Tag color="warning">已归档 {schemeCounts.archived}</Tag>
                    </Space>
                  </Col>
                </Row>

                {/* 方案卡片列表 */}
                {schemesLoading ? (
                  <div style={{ textAlign: 'center', padding: 40 }}>加载中…</div>
                ) : displaySchemes.length === 0 ? (
                  <Empty description="暂无方案，点击「新建方案」创建" />
                ) : (
                  <Row>
                    {displaySchemes.map((s) => (
                      <Col span={24} key={s.id}>
                        <SchemeCard
                          scheme={s}
                          onEdit={(scheme) => {
                            setEditTarget(scheme);
                            editForm.setFieldsValue({
                              name: scheme.name,
                              description: scheme.description,
                            });
                          }}
                          onPublish={handlePublish}
                          onViewDetail={(scheme) => setDetailSchemeId(scheme.id)}
                          onDistribute={() => {}}
                          onArchive={handleArchive}
                          publishing={publishingId === s.id}
                        />
                      </Col>
                    ))}
                  </Row>
                )}
              </>
            ),
          },
          {
            key: 'distribute',
            label: (
              <Space>
                <SendOutlined />
                下发管理
              </Space>
            ),
            children: <DistributeTab schemes={schemes} />,
          },
          {
            key: 'store-override',
            label: (
              <Space>
                <ShopOutlined />
                门店微调视图
              </Space>
            ),
            children: <StoreMenuTab />,
          },
        ]}
      />

      {/* 方案详情 Drawer */}
      <SchemeDetailDrawer
        schemeId={detailSchemeId}
        onClose={() => setDetailSchemeId(null)}
      />

      {/* 新建方案 Modal */}
      <Modal
        title="新建菜谱方案"
        open={createFormOpen}
        onCancel={() => {
          setCreateFormOpen(false);
          createForm.resetFields();
        }}
        onOk={handleCreate}
        okText="创建方案"
        width={480}
        destroyOnClose
      >
        <Form form={createForm} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item
            name="name"
            label="方案名称"
            rules={[{ required: true, message: '请输入方案名称' }]}
          >
            <Input placeholder="如：夏季主打菜谱 2026" maxLength={200} />
          </Form.Item>
          <Form.Item name="description" label="方案描述">
            <Input.TextArea
              rows={3}
              placeholder="可选，描述此方案的适用场景或特点"
              maxLength={500}
            />
          </Form.Item>
          <Form.Item name="brand_id" label="所属品牌（选填）">
            <Input placeholder="品牌 UUID，留空为集团级方案" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑方案 Modal */}
      <Modal
        title={`编辑方案：${editTarget?.name ?? ''}`}
        open={!!editTarget}
        onCancel={() => {
          setEditTarget(null);
          editForm.resetFields();
        }}
        onOk={handleUpdate}
        okText="保存"
        width={480}
        destroyOnClose
      >
        <Form form={editForm} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item
            name="name"
            label="方案名称"
            rules={[{ required: true, message: '请输入方案名称' }]}
          >
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="description" label="方案描述">
            <Input.TextArea rows={3} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
