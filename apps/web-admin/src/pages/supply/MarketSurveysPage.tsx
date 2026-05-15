/**
 * 市场调研双轨 管理页 — 域D 供应链（PRD-13 sub-B / Phase 2 W11 / T2 normal）
 * 路由：/supply/market-surveys
 *
 * 功能：
 *   1. 调研列表（market_type / status 过滤 + surveyed_at DESC 排序）
 *   2. 新建调研 Modal（market_type 4-enum + location_name + surveyed_at + notes）
 *   3. 详情 Drawer（主表 + items + photos + status transitions）
 *   4. items 增删（ingredient autocomplete + unit_price_fen + qty_per_unit）
 *   5. 照片上传（multipart/form-data → mock COS → market_survey_photos）
 *
 * 业务场景：徐记海鲜采购总监凌晨 5 点出门马王堆海鲜批发市场 →
 *   web-admin iPad 新建 draft 调研 → 逐 ingredient 录入价格 + 拍照 →
 *   提交 status=submitted → 采购总监审核 status=verified → 进 AI 训练池
 *
 * 调用接口（PRD-13 sub-A + sub-B）：
 *   POST   /api/v1/supply/market-surveys                          新建调研
 *   GET    /api/v1/supply/market-surveys                          列表 (market_type/status filter)
 *   GET    /api/v1/supply/market-surveys/{id}/detail              主表 + items + photos 聚合
 *   PATCH  /api/v1/supply/market-surveys/{id}                     更新主表
 *   DELETE /api/v1/supply/market-surveys/{id}                     软删
 *   POST   /api/v1/supply/market-surveys/{id}/transition          status 转换
 *   POST   /api/v1/supply/market-surveys/{id}/items               新增明细
 *   DELETE /api/v1/supply/market-surveys/items/{id}               软删明细
 *   POST   /api/v1/supply/market-surveys/{id}/photos/upload       multipart 上传 (sub-B)
 *   DELETE /api/v1/supply/market-surveys/photos/{id}              软删照片
 *   GET    /api/v1/supply/ingredients/search?q=&limit=20          ingredient autocomplete (sub-B)
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Drawer,
  Form,
  Image,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { UploadProps } from 'antd/es/upload/interface';
import {
  CameraOutlined,
  PlusOutlined,
  ReloadOutlined,
  SendOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { API_BASE, getTenantId, getToken, txFetchData } from '../../api/client';

const { Title, Text, Paragraph } = Typography;

// ─────────────────────────────────────────────────────────────────────────────
// 类型
// ─────────────────────────────────────────────────────────────────────────────

type MarketType = 'wholesale' | 'wet_market' | 'supermarket' | 'other';
type SurveyStatus = 'draft' | 'submitted' | 'verified';

interface MarketSurvey {
  id: string;
  tenant_id: string;
  surveyor_id: string;
  market_type: MarketType;
  location_name: string;
  surveyed_at: string;
  status: SurveyStatus;
  notes: string | null;
  created_at: string;
  updated_at: string;
  is_deleted: boolean;
}

interface MarketSurveyItem {
  id: string;
  tenant_id: string;
  survey_id: string;
  ingredient_id: string | null;
  ingredient_name: string;
  unit_price_fen: number;
  qty_per_unit: string;
  unit: string;
  notes: string | null;
  created_at: string;
}

interface MarketSurveyPhoto {
  id: string;
  tenant_id: string;
  survey_id: string;
  item_id: string | null;
  photo_url: string;
  caption: string | null;
  exif_meta: Record<string, unknown> | null;
  uploaded_at: string;
  created_at: string;
}

interface SurveyDetail {
  survey: MarketSurvey;
  items: MarketSurveyItem[];
  photos: MarketSurveyPhoto[];
}

interface IngredientCandidate {
  id: string;
  ingredient_name: string;
  unit: string | null;
  category: string | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// 文案 helper
// ─────────────────────────────────────────────────────────────────────────────

const MARKET_TYPE_LABEL: Record<MarketType, string> = {
  wholesale: '批发市场',
  wet_market: '菜市场/早市',
  supermarket: '超市',
  other: '其他',
};

const STATUS_LABEL: Record<SurveyStatus, string> = {
  draft: '草稿',
  submitted: '已提交',
  verified: '已审核',
};

const STATUS_COLOR: Record<SurveyStatus, string> = {
  draft: 'default',
  submitted: 'blue',
  verified: 'green',
};

function legalNextStatus(current: SurveyStatus): SurveyStatus[] {
  if (current === 'draft') return ['submitted'];
  if (current === 'submitted') return ['verified', 'draft'];
  return []; // verified 终态
}

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

// ─────────────────────────────────────────────────────────────────────────────
// IngredientAutocomplete 子组件 (debounced antd Select)
// ─────────────────────────────────────────────────────────────────────────────

interface IngredientAutocompleteProps {
  value?: string;
  onChange?: (name: string, ingredientId: string | null, unit: string | null) => void;
  placeholder?: string;
}

function IngredientAutocomplete({
  value,
  onChange,
  placeholder = '输入食材名（如 鲈鱼），从系统候选选择或直接键入自由文本',
}: IngredientAutocompleteProps) {
  const [options, setOptions] = useState<IngredientCandidate[]>([]);
  const [fetching, setFetching] = useState(false);

  const handleSearch = useCallback(async (q: string) => {
    if (!q || !q.trim()) {
      setOptions([]);
      return;
    }
    setFetching(true);
    try {
      const params = new URLSearchParams({ q: q.trim(), limit: '20' });
      const data = await txFetchData<IngredientCandidate[]>(
        `/api/v1/supply/ingredients/search?${params.toString()}`,
      );
      setOptions(data ?? []);
    } catch (e) {
      // 静默 — autocomplete 失败不阻塞业务, 用户可继续键入自由文本
      console.warn('ingredient autocomplete failed:', e);
      setOptions([]);
    } finally {
      setFetching(false);
    }
  }, []);

  return (
    <Select
      showSearch
      value={value}
      placeholder={placeholder}
      filterOption={false}
      onSearch={handleSearch}
      loading={fetching}
      notFoundContent={fetching ? '加载中…' : '无候选（可直接键入自由文本）'}
      style={{ width: '100%' }}
      onChange={(name) => {
        const hit = options.find((o) => o.ingredient_name === name);
        if (hit) {
          onChange?.(hit.ingredient_name, hit.id, hit.unit);
        } else {
          onChange?.(name, null, null);
        }
      }}
      options={options.map((o) => ({
        value: o.ingredient_name,
        label: `${o.ingredient_name}${o.unit ? ` (${o.unit}` : ''}${
          o.category ? `, ${o.category})` : o.unit ? ')' : ''
        }`,
      }))}
    />
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 主页
// ─────────────────────────────────────────────────────────────────────────────

export function MarketSurveysPage() {
  const [list, setList] = useState<MarketSurvey[]>([]);
  const [loading, setLoading] = useState(false);
  const [marketType, setMarketType] = useState<MarketType | undefined>(undefined);
  const [status, setStatus] = useState<SurveyStatus | undefined>(undefined);

  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm();

  const [detail, setDetail] = useState<SurveyDetail | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);

  const [addItemOpen, setAddItemOpen] = useState(false);
  const [addItemForm] = Form.useForm();
  const [pendingIngredientId, setPendingIngredientId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (marketType) params.set('market_type', marketType);
      if (status) params.set('status', status);
      params.set('limit', '100');
      const data = await txFetchData<MarketSurvey[]>(
        `/api/v1/supply/market-surveys?${params.toString()}`,
      );
      setList(data ?? []);
    } catch (e) {
      message.error('加载调研列表失败：' + String(e));
    } finally {
      setLoading(false);
    }
  }, [marketType, status]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const openDetail = useCallback(async (surveyId: string) => {
    setDetailLoading(true);
    setDetailOpen(true);
    try {
      const data = await txFetchData<SurveyDetail>(
        `/api/v1/supply/market-surveys/${surveyId}/detail`,
      );
      setDetail(data);
    } catch (e) {
      message.error('加载详情失败：' + String(e));
      setDetailOpen(false);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const handleCreate = async (values: {
    surveyor_id: string;
    market_type: MarketType;
    location_name: string;
    surveyed_at: dayjs.Dayjs;
    notes?: string;
  }) => {
    try {
      await txFetchData('/api/v1/supply/market-surveys', {
        method: 'POST',
        body: JSON.stringify({
          surveyor_id: values.surveyor_id,
          market_type: values.market_type,
          location_name: values.location_name,
          surveyed_at: values.surveyed_at.toISOString(),
          notes: values.notes || null,
        }),
      });
      message.success('调研创建成功');
      setCreateOpen(false);
      createForm.resetFields();
      await refresh();
    } catch (e) {
      message.error('创建失败：' + String(e));
    }
  };

  const handleTransition = async (target: SurveyStatus) => {
    if (!detail) return;
    try {
      await txFetchData(
        `/api/v1/supply/market-surveys/${detail.survey.id}/transition`,
        {
          method: 'POST',
          body: JSON.stringify({ target_status: target }),
        },
      );
      message.success(`已转为「${STATUS_LABEL[target]}」`);
      await openDetail(detail.survey.id);
      await refresh();
    } catch (e) {
      message.error('状态转换失败：' + String(e));
    }
  };

  const handleAddItem = async (values: {
    ingredient_name: string;
    unit_price_fen: number;
    qty_per_unit: number;
    unit: string;
    notes?: string;
  }) => {
    if (!detail) return;
    try {
      await txFetchData(
        `/api/v1/supply/market-surveys/${detail.survey.id}/items`,
        {
          method: 'POST',
          body: JSON.stringify({
            ingredient_id: pendingIngredientId,
            ingredient_name: values.ingredient_name,
            unit_price_fen: values.unit_price_fen,
            qty_per_unit: String(values.qty_per_unit),
            unit: values.unit,
            notes: values.notes || null,
          }),
        },
      );
      message.success('明细已录入');
      setAddItemOpen(false);
      addItemForm.resetFields();
      setPendingIngredientId(null);
      await openDetail(detail.survey.id);
    } catch (e) {
      message.error('录入失败：' + String(e));
    }
  };

  const handleDeleteItem = async (itemId: string) => {
    if (!detail) return;
    try {
      await txFetchData(`/api/v1/supply/market-surveys/items/${itemId}`, {
        method: 'DELETE',
      });
      message.success('明细已删除');
      await openDetail(detail.survey.id);
    } catch (e) {
      message.error('删除失败：' + String(e));
    }
  };

  const handleDeletePhoto = async (photoId: string) => {
    if (!detail) return;
    try {
      await txFetchData(`/api/v1/supply/market-surveys/photos/${photoId}`, {
        method: 'DELETE',
      });
      message.success('照片已删除');
      await openDetail(detail.survey.id);
    } catch (e) {
      message.error('删除失败：' + String(e));
    }
  };

  /** 上传 multipart/form-data — 绕过 txFetch 默认 JSON content-type 让浏览器自动设 boundary. */
  const photoUploadProps: UploadProps = {
    accept: 'image/jpeg,image/png,image/webp,image/heic',
    showUploadList: false,
    beforeUpload: async (file) => {
      if (!detail) return false;
      const formData = new FormData();
      formData.append('file', file);
      const token = getToken();
      const tenantId = getTenantId();
      try {
        const resp = await fetch(
          `${API_BASE}/api/v1/supply/market-surveys/${detail.survey.id}/photos/upload`,
          {
            method: 'POST',
            body: formData,
            headers: {
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
              ...(tenantId ? { 'X-Tenant-ID': tenantId } : {}),
            },
          },
        );
        const json = await resp.json();
        if (!resp.ok || !json.ok) {
          throw new Error(json?.error?.message || json?.detail?.message || '上传失败');
        }
        message.success('照片上传成功');
        await openDetail(detail.survey.id);
      } catch (e) {
        message.error('上传失败：' + String(e));
      }
      // 返回 false 阻止 antd 自动 PUT (我们已经手动 fetch)
      return false;
    },
  };

  const columns: ColumnsType<MarketSurvey> = [
    {
      title: '调研时间',
      dataIndex: 'surveyed_at',
      key: 'surveyed_at',
      width: 180,
      render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '市场类型',
      dataIndex: 'market_type',
      key: 'market_type',
      width: 120,
      render: (v: MarketType) => <Tag color="cyan">{MARKET_TYPE_LABEL[v]}</Tag>,
    },
    { title: '地点', dataIndex: 'location_name', key: 'location_name', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (v: SurveyStatus) => <Tag color={STATUS_COLOR[v]}>{STATUS_LABEL[v]}</Tag>,
    },
    {
      title: '操作',
      key: 'ops',
      width: 100,
      fixed: 'right',
      render: (_, row) => (
        <Button type="link" size="small" onClick={() => openDetail(row.id)}>
          查看详情
        </Button>
      ),
    },
  ];

  return (
    <Card
      title={<Title level={3}>市场调研双轨（PRD-13 sub-A/B）</Title>}
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={refresh}>
            刷新
          </Button>
          <Button icon={<PlusOutlined />} type="primary" onClick={() => setCreateOpen(true)}>
            新建调研
          </Button>
        </Space>
      }
    >
      <Alert
        message="市场调研双轨 — AI 主调研 + 人工巡店兜底"
        description={
          <Paragraph style={{ marginBottom: 0 }}>
            <Text>
              AI 主调研缺早市/批发市场价（菜场无 API），创始人/采购总监早市拍照录入兜底，
            </Text>
            <br />
            <Text>进训练池形成本地早市价数据集（连锁餐饮独家长期资产 + 政府 CPI 合作潜力）。</Text>
            <br />
            <Text type="secondary">
              工作流：draft（移动端起草） → submitted（提交进训练池候选） →
              verified（采购总监审核合格）。verified 是终态。
            </Text>
          </Paragraph>
        }
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
      />

      <Space style={{ marginBottom: 16 }} wrap>
        <span>
          市场类型：
          <Select
            allowClear
            placeholder="全部"
            style={{ width: 140 }}
            value={marketType}
            onChange={(v) => setMarketType(v)}
            options={Object.entries(MARKET_TYPE_LABEL).map(([k, v]) => ({ value: k, label: v }))}
          />
        </span>
        <span>
          状态：
          <Select
            allowClear
            placeholder="全部"
            style={{ width: 120 }}
            value={status}
            onChange={(v) => setStatus(v)}
            options={Object.entries(STATUS_LABEL).map(([k, v]) => ({ value: k, label: v }))}
          />
        </span>
      </Space>

      <Table<MarketSurvey>
        rowKey="id"
        dataSource={list}
        columns={columns}
        loading={loading}
        scroll={{ x: 1000 }}
        pagination={{ pageSize: 20 }}
      />

      {/* ───── 新建 Modal ───── */}
      <Modal
        open={createOpen}
        title="新建调研"
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        okText="创建"
        cancelText="取消"
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={handleCreate}
          initialValues={{ market_type: 'wholesale', surveyed_at: dayjs() }}
        >
          <Form.Item
            name="surveyor_id"
            label="调研人 employee_id（UUID）"
            rules={[{ required: true }]}
          >
            <Input placeholder="例如：cccccccc-0003-0003-0003-cccccccccccc" />
          </Form.Item>
          <Form.Item name="market_type" label="市场类型" rules={[{ required: true }]}>
            <Select
              options={Object.entries(MARKET_TYPE_LABEL).map(([k, v]) => ({ value: k, label: v }))}
            />
          </Form.Item>
          <Form.Item
            name="location_name"
            label="地点名称"
            rules={[{ required: true, max: 200 }]}
          >
            <Input placeholder="例如：马王堆海鲜批发市场" />
          </Form.Item>
          <Form.Item name="surveyed_at" label="调研时间" rules={[{ required: true }]}>
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} maxLength={2000} />
          </Form.Item>
        </Form>
      </Modal>

      {/* ───── 详情 Drawer ───── */}
      <Drawer
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        title={detail ? `调研详情 — ${detail.survey.location_name}` : '加载中…'}
        width={720}
        loading={detailLoading}
        destroyOnClose
      >
        {detail && (
          <>
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <div>
                <Tag color="cyan">{MARKET_TYPE_LABEL[detail.survey.market_type]}</Tag>
                <Tag color={STATUS_COLOR[detail.survey.status]}>
                  {STATUS_LABEL[detail.survey.status]}
                </Tag>
                <Text type="secondary">
                  {dayjs(detail.survey.surveyed_at).format('YYYY-MM-DD HH:mm')}
                </Text>
              </div>

              {/* status transition 按钮组 */}
              {legalNextStatus(detail.survey.status).length > 0 && (
                <Space>
                  {legalNextStatus(detail.survey.status).map((target) => (
                    <Popconfirm
                      key={target}
                      title={`确认转为「${STATUS_LABEL[target]}」？`}
                      onConfirm={() => handleTransition(target)}
                    >
                      <Button type="primary" icon={<SendOutlined />}>
                        转为 {STATUS_LABEL[target]}
                      </Button>
                    </Popconfirm>
                  ))}
                </Space>
              )}

              {/* items 区 */}
              <Card
                size="small"
                title={`调研明细（${detail.items.length} 项）`}
                extra={
                  <Button
                    size="small"
                    icon={<PlusOutlined />}
                    onClick={() => setAddItemOpen(true)}
                  >
                    新增明细
                  </Button>
                }
              >
                {detail.items.length === 0 ? (
                  <Text type="secondary">暂无明细</Text>
                ) : (
                  <Table<MarketSurveyItem>
                    rowKey="id"
                    size="small"
                    dataSource={detail.items}
                    pagination={false}
                    columns={[
                      {
                        title: '食材',
                        dataIndex: 'ingredient_name',
                        key: 'ingredient_name',
                        render: (v, row) => (
                          <>
                            {v}
                            {row.ingredient_id === null && (
                              <Tag style={{ marginLeft: 4 }}>自由文本</Tag>
                            )}
                          </>
                        ),
                      },
                      {
                        title: '单价',
                        key: 'price',
                        render: (_, row) =>
                          `¥${fenToYuan(row.unit_price_fen)} / ${row.qty_per_unit}${row.unit}`,
                      },
                      {
                        title: '操作',
                        key: 'ops',
                        width: 80,
                        render: (_, row) => (
                          <Popconfirm
                            title="删除明细？"
                            onConfirm={() => handleDeleteItem(row.id)}
                          >
                            <Button type="link" size="small" danger>
                              删除
                            </Button>
                          </Popconfirm>
                        ),
                      },
                    ]}
                  />
                )}
              </Card>

              {/* photos 区 */}
              <Card
                size="small"
                title={`调研照片（${detail.photos.length} 张）`}
                extra={
                  <Upload {...photoUploadProps}>
                    <Button size="small" icon={<CameraOutlined />}>
                      上传照片
                    </Button>
                  </Upload>
                }
              >
                {detail.photos.length === 0 ? (
                  <Text type="secondary">暂无照片</Text>
                ) : (
                  <Space wrap>
                    {detail.photos.map((p) => (
                      <div key={p.id} style={{ position: 'relative' }}>
                        <Image
                          width={120}
                          height={120}
                          src={p.photo_url}
                          fallback="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMjAiIGhlaWdodD0iMTIwIj48cmVjdCB3aWR0aD0iMTIwIiBoZWlnaHQ9IjEyMCIgZmlsbD0iI2VlZSIvPjx0ZXh0IHg9IjYwIiB5PSI2MCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iIzk5OSI+SU1HPC90ZXh0Pjwvc3ZnPg=="
                          style={{ objectFit: 'cover' }}
                        />
                        <Popconfirm
                          title="删除照片？"
                          onConfirm={() => handleDeletePhoto(p.id)}
                        >
                          <Button
                            danger
                            size="small"
                            style={{
                              position: 'absolute',
                              top: 4,
                              right: 4,
                              padding: '0 4px',
                              fontSize: 12,
                            }}
                          >
                            ×
                          </Button>
                        </Popconfirm>
                        {p.caption && (
                          <Text
                            type="secondary"
                            style={{
                              display: 'block',
                              maxWidth: 120,
                              fontSize: 12,
                            }}
                            ellipsis
                          >
                            {p.caption}
                          </Text>
                        )}
                      </div>
                    ))}
                  </Space>
                )}
              </Card>
            </Space>
          </>
        )}
      </Drawer>

      {/* ───── 新增明细 Modal ───── */}
      <Modal
        open={addItemOpen}
        title="新增调研明细"
        onCancel={() => {
          setAddItemOpen(false);
          setPendingIngredientId(null);
        }}
        onOk={() => addItemForm.submit()}
        okText="录入"
        cancelText="取消"
      >
        <Form
          form={addItemForm}
          layout="vertical"
          onFinish={handleAddItem}
          initialValues={{ qty_per_unit: 1, unit: '斤' }}
        >
          <Form.Item
            name="ingredient_name"
            label="食材名（autocomplete）"
            tooltip="系统候选不命中也可直接键入自由文本（落 ingredient_id=NULL）"
            rules={[{ required: true, max: 200 }]}
          >
            <IngredientAutocomplete
              onChange={(name, ingredientId, unit) => {
                addItemForm.setFieldsValue({ ingredient_name: name });
                setPendingIngredientId(ingredientId);
                if (unit) {
                  addItemForm.setFieldsValue({ unit });
                }
              }}
            />
          </Form.Item>
          <Form.Item
            name="unit_price_fen"
            label="单位价格（分，整数）"
            rules={[{ required: true }]}
            tooltip="例如 28 元/斤 → 输入 2800 fen"
          >
            <InputNumber<number> min={0} max={1_000_000_000} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="qty_per_unit"
            label="单位规格"
            rules={[{ required: true }]}
            tooltip="例如 1 斤、1 个、1 箱"
          >
            <InputNumber<number> min={0.001} step={0.1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="unit" label="单位" rules={[{ required: true, max: 20 }]}>
            <Input placeholder="斤 / 个 / 箱 …" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
