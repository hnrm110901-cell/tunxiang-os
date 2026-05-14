/**
 * 供应商证件管理页 — 域D 供应链
 * 路由：/supply/supplier-certificates
 *
 * 功能：
 *   1. 选择供应商，展示该供应商的证件列表
 *   2. 按状态过滤（全部 / 有效 / 即将到期30天 / 已过期）
 *   3. 新建证件（含附件上传）
 *   4. 续证（更新到期日 + 附件）
 *   5. 删除证件（软删）
 *
 * API:
 *   GET    /api/v1/supply/supplier-portal/suppliers              — 供应商下拉列表
 *   GET    /api/v1/supply/suppliers/{id}/certificates?status=&page=&size=
 *   POST   /api/v1/supply/suppliers/{id}/certificates           — 新建
 *   POST   /api/v1/supply/certificates/{cert_id}/renew          — 续证
 *   DELETE /api/v1/supply/certificates/{cert_id}                — 软删
 *   POST   /api/v1/upload/file                                  — 附件上传，响应 data.url
 */
import { useEffect, useState, useCallback } from 'react';

// 自定义 Upload customRequest 参数类型（避免依赖 rc-upload 内部类型）
interface UploadRequestOption {
  file: File | Blob;
  onSuccess?: (body: unknown, xhr: XMLHttpRequest) => void;
  onError?: (err: Error) => void;
  onProgress?: (event: { percent: number }) => void;
}

import {
  Card,
  Table,
  Tag,
  Button,
  Space,
  Typography,
  Alert,
  Select,
  Modal,
  Form,
  Input,
  DatePicker,
  Switch,
  Upload,
  message,
  Spin,
  Radio,
  InputNumber,
  Row,
  Col,
  Statistic,
} from 'antd';
import {
  PlusOutlined,
  ReloadOutlined,
  UploadOutlined,
  LinkOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { txFetchData, getToken, getTenantId } from '../../api/client';

const { Title, Text } = Typography;

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

interface Supplier {
  id: string;
  name: string;
  category?: string;
}

interface Certificate {
  id: string;
  supplier_id: string;
  supplier_name: string | null;
  cert_type: string;
  cert_number: string;
  issuer: string | null;
  expire_date: string;
  warning_days: number[];
  auto_block_on_expire: boolean;
  attachment_url: string | null;
  created_at: string;
  updated_at: string;
}

interface CertListData {
  items: Certificate[];
  total?: number;
  page: number;
  size: number;
}

type CertStatus = 'all' | 'active' | 'expiring_30d' | 'expired';

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

/** 计算距离到期天数（正数=未过期，负数=已过期，0=今天到期） */
function daysUntilExpiry(expireDate: string): number {
  return dayjs(expireDate).diff(dayjs().startOf('day'), 'day');
}

/** 根据到期天数返回 Tag */
function expiryTag(expireDate: string) {
  const d = daysUntilExpiry(expireDate);
  if (d <= 0) return <Tag color="error">已过期 {Math.abs(d)} 天</Tag>;
  if (d <= 7) return <Tag color="orange">剩余 {d} 天</Tag>;
  if (d <= 30) return <Tag color="warning">剩余 {d} 天</Tag>;
  return <Tag color="default">剩余 {d} 天</Tag>;
}

/** 证件类型中文映射 */
const CERT_TYPE_OPTIONS = [
  { label: '营业执照', value: 'business_license' },
  { label: '食品经营许可证', value: 'food_permit' },
  { label: '健康证', value: 'health_cert' },
  { label: '其他', value: 'other' },
];

function certTypeLabel(value: string): string {
  return CERT_TYPE_OPTIONS.find((o) => o.value === value)?.label ?? value;
}

// ─── 自定义上传函数（复用 /api/v1/upload/file）─────────────────────────────

async function uploadFile(file: File): Promise<string> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('folder', 'supplier_certificates');

  const token = getToken();
  const tenantId = getTenantId();

  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (tenantId) headers['X-Tenant-ID'] = tenantId;

  const resp = await fetch('/api/v1/upload/file', {
    method: 'POST',
    headers,
    body: formData,
  });

  const json = await resp.json() as { ok: boolean; data: { url: string; key: string; size: number } | null; error?: { message: string } | null };
  if (!json.ok || !json.data) {
    throw new Error(json.error?.message ?? '上传失败');
  }
  return json.data.url;
}

// ─── 新建证件 Modal ───────────────────────────────────────────────────────────

interface CreateModalProps {
  supplierId: string;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

function CreateCertModal({ supplierId, open, onClose, onSuccess }: CreateModalProps) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [uploadUrl, setUploadUrl] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const handleUpload = async (options: UploadRequestOption) => {
    const file = options.file as File;
    setUploading(true);
    try {
      const url = await uploadFile(file);
      setUploadUrl(url);
      form.setFieldValue('attachment_url', url);
      message.success('附件上传成功');
      if (options.onSuccess) options.onSuccess({ url }, new XMLHttpRequest());
    } catch (err) {
      const msg = err instanceof Error ? err.message : '上传失败';
      message.error(msg);
      if (options.onError) options.onError(new Error(msg));
    } finally {
      setUploading(false);
    }
  };

  const handleSubmit = async () => {
    let values: Record<string, unknown>;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }

    setSubmitting(true);
    try {
      const body = {
        cert_type: values['cert_type'] as string,
        cert_number: values['cert_number'] as string,
        expire_date: (values['expire_date'] as dayjs.Dayjs).format('YYYY-MM-DD'),
        issuer: (values['issuer'] as string | undefined) ?? undefined,
        warning_days: [
          values['warning_day_1'] as number,
          values['warning_day_2'] as number,
          values['warning_day_3'] as number,
        ].filter((d): d is number => typeof d === 'number' && d > 0),
        auto_block_on_expire: (values['auto_block_on_expire'] as boolean) ?? true,
        attachment_url: uploadUrl ?? undefined,
      };

      await txFetchData(`/api/v1/supply/suppliers/${supplierId}/certificates`, {
        method: 'POST',
        body: JSON.stringify(body),
      });

      message.success('证件创建成功');
      form.resetFields();
      setUploadUrl(null);
      onSuccess();
      onClose();
    } catch (err) {
      const msg = err instanceof Error ? err.message : '创建失败';
      message.error(`创建失败: ${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title="新建证件"
      open={open}
      onCancel={() => { form.resetFields(); setUploadUrl(null); onClose(); }}
      onOk={handleSubmit}
      okText="创建"
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnClose
      width={560}
    >
      <Form form={form} layout="vertical" initialValues={{ auto_block_on_expire: true, warning_day_1: 30, warning_day_2: 15, warning_day_3: 7 }}>
        <Form.Item name="cert_type" label="证件类型" rules={[{ required: true, message: '请选择证件类型' }]}>
          <Select options={CERT_TYPE_OPTIONS} placeholder="请选择证件类型" />
        </Form.Item>
        <Form.Item name="cert_number" label="证件编号" rules={[{ required: true, message: '请输入证件编号' }, { max: 128, message: '不超过128字符' }]}>
          <Input placeholder="请输入证件编号" />
        </Form.Item>
        <Form.Item name="issuer" label="签发机构" rules={[{ max: 128, message: '不超过128字符' }]}>
          <Input placeholder="可选，如：湖南省市场监督管理局" />
        </Form.Item>
        <Form.Item name="expire_date" label="到期日" rules={[{ required: true, message: '请选择到期日' }]}>
          <DatePicker style={{ width: '100%' }} format="YYYY-MM-DD" />
        </Form.Item>
        <Form.Item label="预警天数">
          <Space>
            <Form.Item name="warning_day_1" noStyle>
              <InputNumber min={1} max={365} style={{ width: 80 }} placeholder="天" />
            </Form.Item>
            <Form.Item name="warning_day_2" noStyle>
              <InputNumber min={1} max={365} style={{ width: 80 }} placeholder="天" />
            </Form.Item>
            <Form.Item name="warning_day_3" noStyle>
              <InputNumber min={1} max={365} style={{ width: 80 }} placeholder="天" />
            </Form.Item>
            <Text type="secondary">天前预警</Text>
          </Space>
        </Form.Item>
        <Form.Item name="auto_block_on_expire" label="过期自动阻断收货" valuePropName="checked">
          <Switch checkedChildren="开" unCheckedChildren="关" />
        </Form.Item>
        <Form.Item name="attachment_url" label="证件附件" help={uploadUrl ? <Text type="success">已上传: {uploadUrl.split('/').pop()}</Text> : null}>
          <Upload
            customRequest={handleUpload}
            maxCount={1}
            showUploadList={false}
          >
            <Button icon={<UploadOutlined />} loading={uploading}>
              {uploading ? '上传中' : '上传附件'}
            </Button>
          </Upload>
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── 续证 Modal ───────────────────────────────────────────────────────────────

interface RenewModalProps {
  cert: Certificate | null;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

function RenewCertModal({ cert, open, onClose, onSuccess }: RenewModalProps) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [uploadUrl, setUploadUrl] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const handleUpload = async (options: UploadRequestOption) => {
    const file = options.file as File;
    setUploading(true);
    try {
      const url = await uploadFile(file);
      setUploadUrl(url);
      message.success('附件上传成功');
      if (options.onSuccess) options.onSuccess({ url }, new XMLHttpRequest());
    } catch (err) {
      const msg = err instanceof Error ? err.message : '上传失败';
      message.error(msg);
      if (options.onError) options.onError(new Error(msg));
    } finally {
      setUploading(false);
    }
  };

  const handleSubmit = async () => {
    if (!cert) return;
    let values: Record<string, unknown>;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }

    setSubmitting(true);
    try {
      const body: Record<string, unknown> = {
        new_expire_date: (values['new_expire_date'] as dayjs.Dayjs).format('YYYY-MM-DD'),
      };
      if (uploadUrl) body['new_attachment_url'] = uploadUrl;

      await txFetchData(`/api/v1/supply/certificates/${cert.id}/renew`, {
        method: 'POST',
        body: JSON.stringify(body),
      });

      message.success('续证成功');
      form.resetFields();
      setUploadUrl(null);
      onSuccess();
      onClose();
    } catch (err) {
      const errObj = err as { code?: string; message?: string };
      if (errObj.code === 'CERT_NOT_FOUND') {
        message.warning('证件已被删除，正在刷新列表');
        onSuccess();
        onClose();
      } else {
        message.error(`续证失败: ${errObj.message ?? '未知错误'}`);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title={`续证 — ${cert ? certTypeLabel(cert.cert_type) : ''}`}
      open={open}
      onCancel={() => { form.resetFields(); setUploadUrl(null); onClose(); }}
      onOk={handleSubmit}
      okText="确认续证"
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnClose
      width={480}
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="new_expire_date"
          label="新到期日"
          rules={[
            { required: true, message: '请选择新到期日' },
            {
              validator: (_, value: dayjs.Dayjs) => {
                if (!value || !value.isBefore(dayjs().startOf('day'))) {
                  return Promise.resolve();
                }
                return Promise.reject(new Error('续证日期不能早于今天'));
              },
            },
          ]}
        >
          <DatePicker
            style={{ width: '100%' }}
            format="YYYY-MM-DD"
            disabledDate={(d) => d.isBefore(dayjs().startOf('day'))}
          />
        </Form.Item>
        <Form.Item label="新版附件（可选）" help={uploadUrl ? <Text type="success">已上传: {uploadUrl.split('/').pop()}</Text> : null}>
          <Upload customRequest={handleUpload} maxCount={1} showUploadList={false}>
            <Button icon={<UploadOutlined />} loading={uploading}>
              {uploading ? '上传中' : '上传新附件'}
            </Button>
          </Upload>
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function SupplierCertificatesPage() {
  // 供应商列表
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [supplierLoading, setSupplierLoading] = useState(false);
  const [selectedSupplierId, setSelectedSupplierId] = useState<string | null>(null);

  // 证件列表
  const [certs, setCerts] = useState<Certificate[]>([]);
  const [loading, setLoading] = useState(false);
  const [certStatus, setCertStatus] = useState<CertStatus>('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);

  // 错误
  const [errMsg, setErrMsg] = useState<string | null>(null);

  // Modals
  const [createOpen, setCreateOpen] = useState(false);
  const [renewTarget, setRenewTarget] = useState<Certificate | null>(null);

  // ── 加载供应商列表 ──
  const loadSuppliers = useCallback(async () => {
    setSupplierLoading(true);
    try {
      // size=100 是 endpoint 当前上限；服务端 search 待 follow-up（500+ 供应商客户必须）
      const data = await txFetchData<{ items: Supplier[]; total: number }>(
        '/api/v1/supply/supplier-portal/suppliers?page=1&size=100',
      );
      const items = data.items ?? [];
      setSuppliers(items);
      if (items.length > 0 && !selectedSupplierId) {
        setSelectedSupplierId(items[0].id);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrMsg(`加载供应商列表失败: ${msg}`);
    } finally {
      setSupplierLoading(false);
    }
  }, [selectedSupplierId]);

  useEffect(() => {
    void loadSuppliers();
  }, []);

  // ── 加载证件列表 ──
  const loadCerts = useCallback(async (
    supplierId: string,
    status: CertStatus,
    currentPage: number,
    currentSize: number,
  ) => {
    setLoading(true);
    setErrMsg(null);
    try {
      const params = new URLSearchParams({
        status,
        page: String(currentPage),
        size: String(currentSize),
      });
      const data = await txFetchData<CertListData>(
        `/api/v1/supply/suppliers/${supplierId}/certificates?${params.toString()}`,
      );
      setCerts(data.items ?? []);
      setTotal(typeof data.total === 'number' ? data.total : (data.items ?? []).length);
    } catch (err) {
      const errObj = err as { code?: string; message?: string };
      const msg = errObj.message ?? String(err);
      setErrMsg(`加载证件失败: ${msg}`);
      message.error(`加载证件失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedSupplierId) {
      void loadCerts(selectedSupplierId, certStatus, page, pageSize);
    }
  }, [selectedSupplierId, certStatus, page, pageSize, loadCerts]);

  const refresh = useCallback(() => {
    if (selectedSupplierId) {
      void loadCerts(selectedSupplierId, certStatus, page, pageSize);
    }
  }, [selectedSupplierId, certStatus, page, pageSize, loadCerts]);

  // ── 删除 ──
  const handleDelete = useCallback((cert: Certificate) => {
    Modal.confirm({
      title: '确认删除证件',
      icon: <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />,
      content: `软删后「${certTypeLabel(cert.cert_type)} — ${cert.cert_number}」不再生效阻断收货。确认删除？`,
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await txFetchData(`/api/v1/supply/certificates/${cert.id}`, { method: 'DELETE' });
          message.success('证件已删除');
          refresh();
        } catch (err) {
          const errObj = err as { code?: string; message?: string };
          if (errObj.code === 'CERT_NOT_FOUND') {
            message.warning('证件已被删除，正在刷新列表');
            refresh();
          } else {
            message.error(`删除失败: ${errObj.message ?? '未知错误'}`);
          }
        }
      },
    });
  }, [refresh]);

  // ── 统计：过期天数分布 ──
  const expiredCount = certs.filter((c) => daysUntilExpiry(c.expire_date) <= 0).length;
  const expiringCount = certs.filter((c) => { const d = daysUntilExpiry(c.expire_date); return d > 0 && d <= 30; }).length;
  const activeCount = certs.filter((c) => daysUntilExpiry(c.expire_date) > 30).length;

  // ── 列定义 ──
  const columns = [
    {
      title: '证件类型',
      dataIndex: 'cert_type',
      key: 'cert_type',
      width: 130,
      render: (v: string) => <Text strong>{certTypeLabel(v)}</Text>,
    },
    {
      title: '证件编号',
      dataIndex: 'cert_number',
      key: 'cert_number',
      width: 180,
      render: (v: string) => <Text code style={{ fontSize: 12 }}>{v}</Text>,
    },
    {
      title: '签发机构',
      dataIndex: 'issuer',
      key: 'issuer',
      ellipsis: true,
      render: (v: string | null) => v ? <Text>{v}</Text> : <Text type="secondary">—</Text>,
    },
    {
      title: '到期日',
      dataIndex: 'expire_date',
      key: 'expire_date',
      width: 200,
      render: (v: string) => (
        <Space direction="vertical" size={2}>
          <Text>{v}</Text>
          {expiryTag(v)}
        </Space>
      ),
    },
    {
      title: '过期阻断',
      dataIndex: 'auto_block_on_expire',
      key: 'auto_block_on_expire',
      width: 90,
      render: (v: boolean) => (
        <Switch checked={v} size="small" disabled checkedChildren="是" unCheckedChildren="否" />
      ),
    },
    {
      title: '附件',
      dataIndex: 'attachment_url',
      key: 'attachment_url',
      width: 100,
      render: (v: string | null) =>
        v ? (
          <a href={v} target="_blank" rel="noreferrer">
            <LinkOutlined /> 查看附件
          </a>
        ) : (
          <Text type="secondary">无</Text>
        ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 130,
      render: (_: unknown, record: Certificate) => (
        <Space>
          <a
            style={{ color: '#52c41a' }}
            onClick={() => setRenewTarget(record)}
          >
            续证
          </a>
          <a
            style={{ color: '#ff4d4f' }}
            onClick={() => handleDelete(record)}
          >
            删除
          </a>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      {/* 标题 + 新建按钮 */}
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }}>
        <Title level={3} style={{ margin: 0 }}>
          供应商证件管理
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={!selectedSupplierId}
            onClick={() => setCreateOpen(true)}
          >
            新建证件
          </Button>
        </Space>
      </Space>

      {/* 全局错误提示 */}
      {errMsg && (
        <Alert
          type="error"
          showIcon
          message="加载失败"
          description={errMsg}
          style={{ marginBottom: 16 }}
          closable
          onClose={() => setErrMsg(null)}
        />
      )}

      {/* 过滤区 */}
      <Card style={{ marginBottom: 16 }}>
        <Space size="large" wrap>
          <Space>
            <Text type="secondary">供应商：</Text>
            <Select
              style={{ width: 220 }}
              placeholder="请选择供应商"
              loading={supplierLoading}
              value={selectedSupplierId}
              onChange={(v) => {
                setSelectedSupplierId(v);
                setPage(1);
              }}
              options={suppliers.map((s) => ({ label: s.name, value: s.id }))}
              showSearch
              optionFilterProp="label"
            />
          </Space>
          <Space>
            <Text type="secondary">状态：</Text>
            <Radio.Group
              value={certStatus}
              onChange={(e) => { setCertStatus(e.target.value as CertStatus); setPage(1); }}
              buttonStyle="solid"
              size="small"
            >
              <Radio.Button value="all">全部</Radio.Button>
              <Radio.Button value="active">有效</Radio.Button>
              <Radio.Button value="expiring_30d">即将到期</Radio.Button>
              <Radio.Button value="expired">已过期</Radio.Button>
            </Radio.Group>
          </Space>
        </Space>
      </Card>

      {/* 统计卡片 */}
      {selectedSupplierId && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col xs={24} md={8}>
            <Card>
              <Statistic
                title="已过期"
                value={expiredCount}
                suffix="张"
                valueStyle={{ color: '#ff4d4f' }}
              />
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card>
              <Statistic
                title="30天内到期"
                value={expiringCount}
                suffix="张"
                valueStyle={{ color: '#faad14' }}
              />
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card>
              <Statistic
                title="有效"
                value={activeCount}
                suffix="张"
                valueStyle={{ color: '#52c41a' }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* 证件表格 */}
      <Spin spinning={loading}>
        {!selectedSupplierId ? (
          <Card>
            <div style={{ textAlign: 'center', padding: '48px 0' }}>
              <Text type="secondary">请先在上方选择供应商</Text>
            </div>
          </Card>
        ) : (
          <Table<Certificate>
            rowKey="id"
            dataSource={certs}
            columns={columns}
            pagination={{
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              pageSizeOptions: ['10', '20', '50'],
              onChange: (p, s) => { setPage(p); setPageSize(s); },
              showTotal: (t) => `共 ${t} 张证件`,
            }}
            scroll={{ x: 900 }}
            locale={{ emptyText: '该供应商暂无证件记录' }}
          />
        )}
      </Spin>

      {/* 新建证件 Modal */}
      {selectedSupplierId && (
        <CreateCertModal
          supplierId={selectedSupplierId}
          open={createOpen}
          onClose={() => setCreateOpen(false)}
          onSuccess={refresh}
        />
      )}

      {/* 续证 Modal */}
      <RenewCertModal
        cert={renewTarget}
        open={!!renewTarget}
        onClose={() => setRenewTarget(null)}
        onSuccess={refresh}
      />
    </div>
  );
}

export default SupplierCertificatesPage;
