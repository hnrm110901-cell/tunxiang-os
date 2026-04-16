/**
 * MenuPlanPage — 菜谱方案批量下发与门店差异化（模块3.4）
 *
 * Tabs：
 *   Tab1 方案列表   — 版本号标签 + 适用门店数 + 下发按钮
 *   Tab2 下发配置   — 多选门店 + 确认下发 + 进度显示
 *   Tab3 门店差异化 — 选择门店 → 查看覆盖项 → 修改价格/可售
 *   Tab4 版本历史   — 变更记录 + 一键回滚
 *
 * 路由：/menu/plans
 * 技术栈：Ant Design 5.x + React 18
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
  Table,
  Modal,
  Form,
  Input,
  InputNumber,
  Switch,
  Select,
  Checkbox,
  Popconfirm,
  Tooltip,
  Row,
  Col,
  Statistic,
  Badge,
  Empty,
  Alert,
  Steps,
  Spin,
  Divider,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  PlusOutlined,
  SendOutlined,
  HistoryOutlined,
  ShopOutlined,
  RollbackOutlined,
  EditOutlined,
  DeleteOutlined,
  ReloadOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
  EyeOutlined,
} from '@ant-design/icons';

import {
  listSchemes,
  publishScheme,
  distributeScheme,
  type MenuScheme,
} from '../../api/menuSchemeApi';
import {
  listPlanVersions,
  rollbackPlanVersion,
  getDistributeLog,
  listStoreOverrides,
  batchUpsertStoreOverrides,
  resetStoreOverrides,
  type PlanVersion,
  type DistributeLogEntry,
  type StoreOverrideItem,
} from '../../api/menuPlanApi';

const { Title, Text } = Typography;
const { Option } = Select;

// ─── 工具函数 ────────────────────────────────────────────────────────────────

const fenToYuan = (fen: number | null | undefined): string => {
  if (fen == null) return '—';
  return `¥${(fen / 100).toFixed(2)}`;
};

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'default' },
  published: { label: '已发布', color: 'success' },
  archived: { label: '已归档', color: 'warning' },
};

const DISTRIBUTE_STATUS: Record<string, { label: string; color: string }> = {
  success: { label: '成功', color: 'success' },
  failed: { label: '失败', color: 'error' },
  pending: { label: '待处理', color: 'processing' },
};

// ─── Tab1：方案列表 ──────────────────────────────────────────────────────────

interface PlanListTabProps {
  onSwitchToDistribute: (scheme: MenuScheme) => void;
  onSwitchToVersions: (scheme: MenuScheme) => void;
}

function PlanListTab({ onSwitchToDistribute, onSwitchToVersions }: PlanListTabProps) {
  const [schemes, setSchemes] = useState<MenuScheme[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [publishing, setPublishing] = useState<string | null>(null);

  const load = useCallback(async (p = page) => {
    setLoading(true);
    try {
      const res = await listSchemes({ page: p, size: 20 });
      setSchemes(res.items);
      setTotal(res.total);
    } catch {
      message.error('加载方案列表失败');
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => { load(); }, [load]);

  const handlePublish = async (scheme: MenuScheme) => {
    setPublishing(scheme.id);
    try {
      await publishScheme(scheme.id);
      message.success(`方案「${scheme.name}」已发布`);
      load();
    } catch {
      message.error('发布失败，请检查方案是否包含菜品');
    } finally {
      setPublishing(null);
    }
  };

  const columns: ColumnsType<MenuScheme> = [
    {
      title: '方案名称',
      dataIndex: 'name',
      render: (name: string, rec: MenuScheme) => (
        <Space direction="vertical" size={2}>
          <Text strong>{name}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{rec.description || '无描述'}</Text>
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (s: string) => {
        const cfg = STATUS_CONFIG[s] ?? STATUS_CONFIG.draft;
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '菜品数',
      dataIndex: 'item_count',
      width: 80,
      render: (n: number) => <Badge count={n} showZero color="blue" />,
    },
    {
      title: '已下发门店',
      dataIndex: 'store_count',
      width: 100,
      render: (n: number) => (
        <Space>
          <ShopOutlined />
          <Text>{n} 家</Text>
        </Space>
      ),
    },
    {
      title: '发布时间',
      dataIndex: 'published_at',
      width: 160,
      render: (t: string | null) => t ? new Date(t).toLocaleString('zh-CN') : '—',
    },
    {
      title: '操作',
      width: 220,
      render: (_, rec: MenuScheme) => (
        <Space>
          {rec.status === 'draft' && (
            <Button
              size="small"
              type="primary"
              icon={<CheckCircleOutlined />}
              loading={publishing === rec.id}
              onClick={() => handlePublish(rec)}
            >
              发布
            </Button>
          )}
          {rec.status === 'published' && (
            <Button
              size="small"
              icon={<SendOutlined />}
              onClick={() => onSwitchToDistribute(rec)}
            >
              批量下发
            </Button>
          )}
          <Button
            size="small"
            icon={<HistoryOutlined />}
            onClick={() => onSwitchToVersions(rec)}
          >
            版本历史
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="方案总数" value={total} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="已发布"
              value={schemes.filter(s => s.status === 'published').length}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="草稿"
              value={schemes.filter(s => s.status === 'draft').length}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="已下发门店(本页合计)"
              value={schemes.reduce((a, b) => a + b.store_count, 0)}
            />
          </Card>
        </Col>
      </Row>

      <Table
        loading={loading}
        dataSource={schemes}
        columns={columns}
        rowKey="id"
        pagination={{
          current: page,
          total,
          pageSize: 20,
          onChange: (p) => { setPage(p); load(p); },
          showTotal: (t) => `共 ${t} 个方案`,
        }}
      />
    </div>
  );
}

// ─── Tab2：下发配置 ──────────────────────────────────────────────────────────

interface DistributeTabProps {
  initialScheme?: MenuScheme | null;
  onReset: () => void;
}

function DistributeTab({ initialScheme, onReset }: DistributeTabProps) {
  const [schemes, setSchemes] = useState<MenuScheme[]>([]);
  const [selectedScheme, setSelectedScheme] = useState<string>(initialScheme?.id ?? '');
  const [storeIds, setStoreIds] = useState<string>('');
  const [distributing, setDistributing] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [result, setResult] = useState<{
    distributed: number;
    total: number;
  } | null>(null);

  useEffect(() => {
    listSchemes({ status: 'published', size: 100 })
      .then(r => setSchemes(r.items))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (initialScheme) {
      setSelectedScheme(initialScheme.id);
      setCurrentStep(1);
    }
  }, [initialScheme]);

  const storeIdList = storeIds
    .split(/[\n,，]+/)
    .map(s => s.trim())
    .filter(Boolean);

  const handleDistribute = async () => {
    if (!selectedScheme) { message.warning('请选择方案'); return; }
    if (storeIdList.length === 0) { message.warning('请输入目标门店 ID'); return; }

    setDistributing(true);
    setCurrentStep(2);
    try {
      const res = await distributeScheme(selectedScheme, storeIdList);
      setResult({ distributed: res.distributed_store_count, total: res.total_requested });
      setCurrentStep(3);
      message.success(`成功下发到 ${res.distributed_store_count} 家门店`);
    } catch {
      message.error('下发失败');
      setCurrentStep(1);
    } finally {
      setDistributing(false);
    }
  };

  const handleReset = () => {
    setSelectedScheme('');
    setStoreIds('');
    setCurrentStep(0);
    setResult(null);
    onReset();
  };

  const scheme = schemes.find(s => s.id === selectedScheme);

  return (
    <div style={{ maxWidth: 720 }}>
      <Steps
        current={currentStep}
        items={[
          { title: '选择方案' },
          { title: '配置门店' },
          { title: '执行下发' },
          { title: '完成' },
        ]}
        style={{ marginBottom: 32 }}
      />

      {currentStep < 3 ? (
        <Space direction="vertical" style={{ width: '100%' }} size={16}>
          <Card title="选择要下发的方案" size="small">
            <Select
              style={{ width: '100%' }}
              placeholder="选择已发布的菜谱方案"
              value={selectedScheme || undefined}
              onChange={(v) => { setSelectedScheme(v); setCurrentStep(1); }}
              showSearch
              filterOption={(input, option) =>
                String(option?.children ?? '').toLowerCase().includes(input.toLowerCase())
              }
            >
              {schemes.map(s => (
                <Option key={s.id} value={s.id}>
                  {s.name}（{s.item_count} 道菜 · {s.store_count} 家门店）
                </Option>
              ))}
            </Select>
            {scheme && (
              <Alert
                style={{ marginTop: 8 }}
                type="info"
                message={`已选：${scheme.name}`}
                description={`当前已下发 ${scheme.store_count} 家门店，本次操作将追加/更新指定门店。`}
                showIcon
              />
            )}
          </Card>

          <Card
            title="配置目标门店"
            size="small"
            extra={
              <Text type="secondary" style={{ fontSize: 12 }}>
                已输入 {storeIdList.length} 个门店 ID
              </Text>
            }
          >
            <Input.TextArea
              rows={6}
              placeholder="每行一个门店 ID，或用逗号分隔&#10;示例：&#10;store-uuid-1&#10;store-uuid-2"
              value={storeIds}
              onChange={e => setStoreIds(e.target.value)}
            />
            <Text type="secondary" style={{ fontSize: 12, marginTop: 4, display: 'block' }}>
              支持 UUID 格式的门店 ID，多个 ID 用换行或逗号分隔
            </Text>
          </Card>

          <Space>
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={distributing}
              disabled={!selectedScheme || storeIdList.length === 0}
              onClick={handleDistribute}
            >
              确认下发（{storeIdList.length} 家门店）
            </Button>
            <Button onClick={handleReset}>重置</Button>
          </Space>
        </Space>
      ) : (
        <Card>
          <Space direction="vertical" align="center" style={{ width: '100%' }}>
            <CheckCircleOutlined style={{ fontSize: 48, color: '#52c41a' }} />
            <Title level={4}>下发完成</Title>
            {result && (
              <Row gutter={32}>
                <Col>
                  <Statistic title="成功下发" value={result.distributed} suffix="家门店" />
                </Col>
                <Col>
                  <Statistic title="总请求" value={result.total} suffix="家" />
                </Col>
              </Row>
            )}
            <Button icon={<ReloadOutlined />} onClick={handleReset}>
              再次下发
            </Button>
          </Space>
        </Card>
      )}
    </div>
  );
}

// ─── Tab3：门店差异化 ─────────────────────────────────────────────────────────

function StoreOverrideTab() {
  const [storeId, setStoreId] = useState('');
  const [schemeId, setSchemeId] = useState('');
  const [overrides, setOverrides] = useState<StoreOverrideItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [editModal, setEditModal] = useState<StoreOverrideItem | null>(null);
  const [form] = Form.useForm();
  const [schemes, setSchemes] = useState<MenuScheme[]>([]);

  useEffect(() => {
    listSchemes({ status: 'published', size: 100 })
      .then(r => setSchemes(r.items))
      .catch(() => {});
  }, []);

  const loadOverrides = async () => {
    if (!storeId) { message.warning('请输入门店 ID'); return; }
    setLoading(true);
    try {
      const res = await listStoreOverrides(storeId, { scheme_id: schemeId || undefined });
      setOverrides(res.items);
    } catch {
      message.error('加载覆盖配置失败');
    } finally {
      setLoading(false);
    }
  };

  const handleSaveOverride = async () => {
    const values = await form.validateFields();
    if (!editModal) return;
    try {
      await batchUpsertStoreOverrides(storeId, [
        {
          dish_id: editModal.dish_id,
          scheme_id: editModal.scheme_id,
          override_price_fen: values.override_price_fen != null
            ? Math.round(values.override_price_fen * 100)
            : null,
          override_available: values.override_available,
        },
      ]);
      message.success('覆盖配置已保存');
      setEditModal(null);
      loadOverrides();
    } catch {
      message.error('保存失败');
    }
  };

  const handleReset = async () => {
    if (!storeId) { message.warning('请输入门店 ID'); return; }
    Modal.confirm({
      title: '确认重置',
      content: `将清空该门店${schemeId ? '此方案' : '所有方案'}的覆盖配置，恢复为集团方案设置。是否继续？`,
      okText: '确认重置',
      okType: 'danger',
      onOk: async () => {
        try {
          const res = await resetStoreOverrides(storeId, schemeId || undefined);
          message.success(`已重置 ${res.deleted_override_count} 条覆盖配置`);
          loadOverrides();
        } catch {
          message.error('重置失败');
        }
      },
    });
  };

  const columns: ColumnsType<StoreOverrideItem> = [
    {
      title: '菜品名称',
      dataIndex: 'dish_name',
      render: (name: string, rec: StoreOverrideItem) => (
        <Space direction="vertical" size={0}>
          <Text>{name}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>ID: {rec.dish_id.slice(0, 8)}...</Text>
        </Space>
      ),
    },
    {
      title: '方案价格',
      dataIndex: 'scheme_price_fen',
      width: 100,
      render: (v: number | null) => fenToYuan(v),
    },
    {
      title: '覆盖价格',
      dataIndex: 'override_price_fen',
      width: 110,
      render: (v: number | null) =>
        v != null ? (
          <Tag color="orange">{fenToYuan(v)}</Tag>
        ) : (
          <Text type="secondary">沿用方案</Text>
        ),
    },
    {
      title: '方案可售',
      dataIndex: 'scheme_available',
      width: 90,
      render: (v: boolean | null) =>
        v == null ? '—' : v ? <Tag color="success">可售</Tag> : <Tag color="error">停售</Tag>,
    },
    {
      title: '覆盖可售',
      dataIndex: 'override_available',
      width: 90,
      render: (v: boolean | null) =>
        v == null ? (
          <Text type="secondary">沿用方案</Text>
        ) : v ? (
          <Tag color="success">可售</Tag>
        ) : (
          <Tag color="error">停售</Tag>
        ),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 150,
      render: (t: string) => new Date(t).toLocaleString('zh-CN'),
    },
    {
      title: '操作',
      width: 80,
      render: (_, rec: StoreOverrideItem) => (
        <Button
          size="small"
          icon={<EditOutlined />}
          onClick={() => {
            setEditModal(rec);
            form.setFieldsValue({
              override_price_fen:
                rec.override_price_fen != null ? rec.override_price_fen / 100 : null,
              override_available: rec.override_available,
            });
          }}
        />
      ),
    },
  ];

  return (
    <div>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Input
            placeholder="门店 ID（UUID）"
            value={storeId}
            onChange={e => setStoreId(e.target.value)}
            style={{ width: 320 }}
          />
          <Select
            placeholder="可选：过滤到指定方案"
            value={schemeId || undefined}
            onChange={v => setSchemeId(v)}
            allowClear
            style={{ width: 240 }}
          >
            {schemes.map(s => (
              <Option key={s.id} value={s.id}>{s.name}</Option>
            ))}
          </Select>
          <Button type="primary" icon={<EyeOutlined />} onClick={loadOverrides}>
            查询覆盖配置
          </Button>
          <Popconfirm
            title="确认重置该门店覆盖配置为集团方案？"
            onConfirm={handleReset}
            disabled={!storeId}
          >
            <Button danger icon={<DeleteOutlined />} disabled={!storeId}>
              重置为集团方案
            </Button>
          </Popconfirm>
        </Space>
      </Card>

      {overrides.length === 0 && !loading ? (
        <Empty description="暂无覆盖配置" />
      ) : (
        <Table
          loading={loading}
          dataSource={overrides}
          columns={columns}
          rowKey="id"
          pagination={{ pageSize: 20, showTotal: t => `共 ${t} 条覆盖` }}
        />
      )}

      <Modal
        open={editModal != null}
        title={`修改覆盖：${editModal?.dish_name}`}
        onCancel={() => setEditModal(null)}
        onOk={handleSaveOverride}
        okText="保存"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            label="覆盖价格（元，留空=沿用方案价）"
            name="override_price_fen"
          >
            <InputNumber
              style={{ width: '100%' }}
              min={0}
              step={0.1}
              precision={2}
              placeholder={
                editModal?.scheme_price_fen != null
                  ? `方案价: ${fenToYuan(editModal.scheme_price_fen)}`
                  : '留空不覆盖'
              }
            />
          </Form.Item>
          <Form.Item
            label="覆盖可售状态（留空=沿用方案）"
            name="override_available"
          >
            <Select allowClear placeholder="不覆盖">
              <Option value={true}>可售</Option>
              <Option value={false}>停售</Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// ─── Tab4：版本历史 ──────────────────────────────────────────────────────────

interface VersionHistoryTabProps {
  initialScheme?: MenuScheme | null;
}

function VersionHistoryTab({ initialScheme }: VersionHistoryTabProps) {
  const [schemes, setSchemes] = useState<MenuScheme[]>([]);
  const [selectedSchemeId, setSelectedSchemeId] = useState<string>(initialScheme?.id ?? '');
  const [versions, setVersions] = useState<PlanVersion[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [rolling, setRolling] = useState<number | null>(null);

  useEffect(() => {
    listSchemes({ size: 100 })
      .then(r => setSchemes(r.items))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (initialScheme) setSelectedSchemeId(initialScheme.id);
  }, [initialScheme]);

  const loadVersions = useCallback(async (sid?: string) => {
    const id = sid ?? selectedSchemeId;
    if (!id) return;
    setLoading(true);
    try {
      const res = await listPlanVersions(id);
      setVersions(res.items);
      setTotal(res.total);
    } catch {
      message.error('加载版本历史失败');
    } finally {
      setLoading(false);
    }
  }, [selectedSchemeId]);

  useEffect(() => {
    if (selectedSchemeId) loadVersions();
  }, [selectedSchemeId, loadVersions]);

  const handleRollback = (ver: PlanVersion) => {
    Modal.confirm({
      title: `回滚到版本 v${ver.version_number}？`,
      content: (
        <Space direction="vertical">
          <Text>此操作将用版本 v{ver.version_number} 的快照替换当前方案菜品列表。</Text>
          <Text type="secondary">创建时间：{new Date(ver.created_at).toLocaleString('zh-CN')}</Text>
          {ver.change_summary && <Text>变更摘要：{ver.change_summary}</Text>}
          <Alert type="warning" message="回滚后当前版本的菜品列表将被覆盖，此操作不可撤销。" />
        </Space>
      ),
      okText: '确认回滚',
      okType: 'danger',
      onOk: async () => {
        setRolling(ver.version_number);
        try {
          const res = await rollbackPlanVersion(selectedSchemeId, ver.version_number);
          message.success(`已回滚，恢复 ${res.items_restored} 道菜品`);
          loadVersions();
        } catch {
          message.error('回滚失败');
        } finally {
          setRolling(null);
        }
      },
    });
  };

  const columns: ColumnsType<PlanVersion> = [
    {
      title: '版本号',
      dataIndex: 'version_number',
      width: 90,
      render: (v: number) => <Tag color="blue">v{v}</Tag>,
    },
    {
      title: '菜品数量',
      dataIndex: 'item_count',
      width: 90,
      render: (n: number) => `${n} 道`,
    },
    {
      title: '变更摘要',
      dataIndex: 'change_summary',
      render: (s: string | null) => s || <Text type="secondary">—</Text>,
    },
    {
      title: '发布人',
      dataIndex: 'published_by',
      width: 120,
      render: (v: string | null) => v || '—',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 160,
      render: (t: string) => new Date(t).toLocaleString('zh-CN'),
    },
    {
      title: '操作',
      width: 100,
      render: (_, rec: PlanVersion) => (
        <Tooltip title="回滚到此版本">
          <Button
            size="small"
            danger
            icon={<RollbackOutlined />}
            loading={rolling === rec.version_number}
            onClick={() => handleRollback(rec)}
          >
            回滚
          </Button>
        </Tooltip>
      ),
    },
  ];

  const selectedScheme = schemes.find(s => s.id === selectedSchemeId);

  return (
    <div>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space>
          <Select
            style={{ width: 360 }}
            placeholder="选择方案查看版本历史"
            value={selectedSchemeId || undefined}
            onChange={(v) => setSelectedSchemeId(v)}
            showSearch
            filterOption={(input, option) =>
              String(option?.children ?? '').toLowerCase().includes(input.toLowerCase())
            }
          >
            {schemes.map(s => (
              <Option key={s.id} value={s.id}>
                {s.name}
                <Tag style={{ marginLeft: 8 }} color={STATUS_CONFIG[s.status]?.color ?? 'default'}>
                  {STATUS_CONFIG[s.status]?.label}
                </Tag>
              </Option>
            ))}
          </Select>
          <Button
            icon={<ReloadOutlined />}
            disabled={!selectedSchemeId}
            onClick={() => loadVersions()}
          >
            刷新
          </Button>
        </Space>
        {selectedScheme && (
          <Alert
            style={{ marginTop: 8 }}
            type="info"
            message={`${selectedScheme.name} — 共 ${total} 个版本快照`}
            showIcon
          />
        )}
      </Card>

      {selectedSchemeId ? (
        <Table
          loading={loading}
          dataSource={versions}
          columns={columns}
          rowKey="id"
          pagination={{ pageSize: 20, showTotal: t => `共 ${t} 个版本` }}
          locale={{ emptyText: '暂无版本快照。方案发布后自动创建版本。' }}
        />
      ) : (
        <Empty description="请先选择方案" />
      )}

      <Divider />
      <Alert
        type="info"
        showIcon
        message="版本快照说明"
        description="每次发布方案时可手动触发版本快照，快照保存发布时的完整菜品列表。回滚后，当前方案菜品列表将被替换为快照内容，历史数据不会删除。"
      />
    </div>
  );
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export default function MenuPlanPage() {
  const [activeTab, setActiveTab] = useState('plans');
  const [distributeSchemeCtx, setDistributeSchemeCtx] = useState<MenuScheme | null>(null);
  const [versionSchemeCtx, setVersionSchemeCtx] = useState<MenuScheme | null>(null);

  const handleSwitchToDistribute = (scheme: MenuScheme) => {
    setDistributeSchemeCtx(scheme);
    setActiveTab('distribute');
  };

  const handleSwitchToVersions = (scheme: MenuScheme) => {
    setVersionSchemeCtx(scheme);
    setActiveTab('versions');
  };

  return (
    <div style={{ padding: '0 0 32px' }}>
      <Title level={4} style={{ marginBottom: 16 }}>
        菜谱方案管理
      </Title>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        destroyInactiveTabPane={false}
        items={[
          {
            key: 'plans',
            label: '方案列表',
            children: (
              <PlanListTab
                onSwitchToDistribute={handleSwitchToDistribute}
                onSwitchToVersions={handleSwitchToVersions}
              />
            ),
          },
          {
            key: 'distribute',
            label: '批量下发',
            children: (
              <DistributeTab
                initialScheme={distributeSchemeCtx}
                onReset={() => setDistributeSchemeCtx(null)}
              />
            ),
          },
          {
            key: 'store-override',
            label: '门店差异化',
            children: <StoreOverrideTab />,
          },
          {
            key: 'versions',
            label: '版本历史',
            children: <VersionHistoryTab initialScheme={versionSchemeCtx} />,
          },
        ]}
      />
    </div>
  );
}
