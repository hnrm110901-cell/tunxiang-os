/**
 * CertificationPage — 岗位认证与通关
 *
 * API:
 *   GET  /api/v1/certifications/dashboard
 *   GET  /api/v1/certifications/expiring
 *   GET  /api/v1/certifications?page=&size=&...
 *   GET  /api/v1/certifications/:id
 *   POST /api/v1/certifications
 *   PUT  /api/v1/certifications/:id/exam/:idx
 *   PUT  /api/v1/certifications/:id/finalize
 *   PUT  /api/v1/certifications/:id/retake
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  InputNumber,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  message,
} from 'antd';
import {
  ProTable,
  StatisticCard,
  ModalForm,
  ProFormText,
  ProFormSelect,
} from '@ant-design/pro-components';
import type { ProColumns, ActionType } from '@ant-design/pro-components';
import {
  PlusOutlined,
  WarningOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { txFetchData } from '../../api/client';

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface ExamItem {
  item: string;
  type: string;
  score: number | null;
  passed: boolean;
  examiner_id: string | null;
  exam_date: string | null;
}

interface Certification {
  id: string;
  employee_id: string;
  store_id: string;
  position: string;
  exam_items: ExamItem[];
  total_score: number | null;
  passed: boolean;
  certified_at: string | null;
  expires_at: string | null;
  certifier_id: string | null;
  retake_count: number;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

interface DashboardData {
  total: number;
  passed: number;
  failed: number;
  expiring_soon: number;
  avg_score: number;
  by_position: { position: string; total: number; passed: number }[];
  retake_stats: { total_retakes: number; avg_retakes: number };
}

// ─── 常量 ────────────────────────────────────────────────────────────────────

const positionMap: Record<string, { label: string; color: string }> = {
  manager: { label: '店长', color: 'purple' },
  chef: { label: '厨师', color: 'orange' },
  waiter: { label: '服务员', color: 'blue' },
  cashier: { label: '收银员', color: 'green' },
  cleaner: { label: '保洁', color: 'default' },
};

const positionOptions = Object.entries(positionMap).map(([value, { label }]) => ({
  label,
  value,
}));

// ─── 辅助 ────────────────────────────────────────────────────────────────────

function isExpiringSoon(expiresAt: string | null): boolean {
  if (!expiresAt) return false;
  return dayjs(expiresAt).diff(dayjs(), 'day') <= 30;
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function CertificationPage() {
  const tableRef = useRef<ActionType>();

  // Dashboard
  const [dash, setDash] = useState<DashboardData | null>(null);
  const [dashLoading, setDashLoading] = useState(true);

  // Expiring
  const [expiring, setExpiring] = useState<Certification[]>([]);

  // Detail drawer
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detail, setDetail] = useState<Certification | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Score modal
  const [scoreModal, setScoreModal] = useState<{
    certId: string;
    idx: number;
    itemName: string;
  } | null>(null);
  const [scoreValue, setScoreValue] = useState<number | null>(null);
  const [examinerValue, setExaminerValue] = useState('');
  const [scoreSubmitting, setScoreSubmitting] = useState(false);

  // ── 加载仪表板 ──────────────────────────────────────────────────────────

  const loadDashboard = useCallback(async () => {
    setDashLoading(true);
    try {
      const resp = await txFetchData<DashboardData>('/api/v1/certifications/dashboard');
      setDash(resp.data);
    } catch {
      message.error('加载认证总览失败');
    } finally {
      setDashLoading(false);
    }
  }, []);

  const loadExpiring = useCallback(async () => {
    try {
      const resp = await txFetchData<{ items: Certification[]; total: number }>(
        '/api/v1/certifications/expiring',
      );
      setExpiring(resp.data?.items ?? []);
    } catch {
      /* 静默 */
    }
  }, []);

  useEffect(() => {
    loadDashboard();
    loadExpiring();
  }, [loadDashboard, loadExpiring]);

  // ── 加载详情 ──────────────────────────────────────────────────────────

  const openDetail = async (id: string) => {
    setDrawerOpen(true);
    setDetailLoading(true);
    try {
      const resp = await txFetchData<Certification>(`/api/v1/certifications/${id}`);
      setDetail(resp.data);
    } catch {
      message.error('加载认证详情失败');
    } finally {
      setDetailLoading(false);
    }
  };

  const refreshDetail = async () => {
    if (!detail) return;
    try {
      const resp = await txFetchData<Certification>(`/api/v1/certifications/${detail.id}`);
      setDetail(resp.data);
    } catch {
      message.error('刷新详情失败');
    }
  };

  // ── 打分 ──────────────────────────────────────────────────────────────

  const handleScore = async () => {
    if (!scoreModal || scoreValue === null || !examinerValue) {
      message.warning('请填写分数和考核人ID');
      return;
    }
    setScoreSubmitting(true);
    try {
      await txFetchData(`/api/v1/certifications/${scoreModal.certId}/exam/${scoreModal.idx}`, {
        method: 'PUT',
        body: JSON.stringify({
          score: scoreValue,
          examiner_id: examinerValue,
          passed: scoreValue >= 60,
        }),
      });
      message.success('打分成功');
      setScoreModal(null);
      setScoreValue(null);
      setExaminerValue('');
      await refreshDetail();
    } catch {
      message.error('打分失败');
    } finally {
      setScoreSubmitting(false);
    }
  };

  // ── 评定 ──────────────────────────────────────────────────────────────

  const handleFinalize = async (id: string) => {
    try {
      await txFetchData(`/api/v1/certifications/${id}/finalize`, { method: 'PUT' });
      message.success('评定完成');
      await refreshDetail();
      tableRef.current?.reload();
      loadDashboard();
      loadExpiring();
    } catch {
      message.error('评定失败');
    }
  };

  // ── 补考 ──────────────────────────────────────────────────────────────

  const handleRetake = async (id: string) => {
    try {
      await txFetchData(`/api/v1/certifications/${id}/retake`, { method: 'PUT' });
      message.success('已发起补考，考核项已重置');
      await refreshDetail();
      tableRef.current?.reload();
      loadDashboard();
    } catch {
      message.error('发起补考失败');
    }
  };

  // ── 删除 ──────────────────────────────────────────────────────────────

  const handleDelete = async (id: string) => {
    try {
      await txFetchData(`/api/v1/certifications/${id}`, { method: 'DELETE' });
      message.success('已删除');
      tableRef.current?.reload();
      loadDashboard();
      loadExpiring();
    } catch {
      message.error('删除失败');
    }
  };

  // ── 判定是否已finalize ────────────────────────────────────────────────

  const isFinalized = (cert: Certification) => cert.certified_at !== null;
  const allScored = (cert: Certification) =>
    cert.exam_items.length > 0 && cert.exam_items.every((e) => e.score !== null);

  // ── ProTable columns ─────────────────────────────────────────────────

  const columns: ProColumns<Certification>[] = [
    {
      title: '员工ID',
      dataIndex: 'employee_id',
      ellipsis: true,
      fieldProps: { placeholder: '搜索员工ID' },
    },
    {
      title: '门店',
      dataIndex: 'store_id',
      ellipsis: true,
      fieldProps: { placeholder: '搜索门店ID' },
    },
    {
      title: '岗位',
      dataIndex: 'position',
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(positionMap).map(([k, v]) => [k, { text: v.label }]),
      ),
      render: (_, r) => {
        const p = positionMap[r.position];
        return <Tag color={p?.color ?? 'default'}>{p?.label ?? r.position}</Tag>;
      },
    },
    {
      title: '总分',
      dataIndex: 'total_score',
      search: false,
      render: (_, r) => (r.total_score !== null ? r.total_score : '-'),
    },
    {
      title: '状态',
      dataIndex: 'passed',
      valueType: 'select',
      valueEnum: {
        true: { text: '已通过' },
        false: { text: '未通过' },
      },
      render: (_, r) =>
        r.passed ? (
          <Tag color="green">已通过</Tag>
        ) : (
          <Tag color="red">未通过</Tag>
        ),
    },
    {
      title: '认证日期',
      dataIndex: 'certified_at',
      search: false,
      render: (_, r) =>
        r.certified_at ? dayjs(r.certified_at).format('YYYY-MM-DD') : '-',
    },
    {
      title: '有效期至',
      dataIndex: 'expires_at',
      search: false,
      render: (_, r) => {
        if (!r.expires_at) return '-';
        const soon = isExpiringSoon(r.expires_at);
        return (
          <span style={soon ? { color: '#BA7517', fontWeight: 600 } : undefined}>
            {dayjs(r.expires_at).format('YYYY-MM-DD')}
            {soon && <WarningOutlined style={{ marginLeft: 4 }} />}
          </span>
        );
      },
    },
    {
      title: '补考次数',
      dataIndex: 'retake_count',
      search: false,
      render: (_, r) => (r.retake_count > 0 ? r.retake_count : '-'),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 200,
      render: (_, r) => (
        <Space size="small">
          <a onClick={() => openDetail(r.id)}>详情</a>
          {!isFinalized(r) && (
            <a onClick={() => openDetail(r.id)}>评定</a>
          )}
          {isFinalized(r) && !r.passed && (
            <Popconfirm title="确认发起补考？" onConfirm={() => handleRetake(r.id)}>
              <a>补考</a>
            </Popconfirm>
          )}
          <Popconfirm title="确认删除此认证记录？" onConfirm={() => handleDelete(r.id)}>
            <a style={{ color: '#A32D2D' }}>删除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // ── 即将过期预警表 columns ────────────────────────────────────────────

  const expiringColumns = [
    { title: '员工ID', dataIndex: 'employee_id', key: 'employee_id' },
    {
      title: '岗位',
      dataIndex: 'position',
      key: 'position',
      render: (v: string) => {
        const p = positionMap[v];
        return <Tag color={p?.color ?? 'default'}>{p?.label ?? v}</Tag>;
      },
    },
    { title: '门店', dataIndex: 'store_id', key: 'store_id' },
    {
      title: '过期日期',
      dataIndex: 'expires_at',
      key: 'expires_at',
      render: (v: string) => (
        <span style={{ color: '#BA7517', fontWeight: 600 }}>
          {dayjs(v).format('YYYY-MM-DD')}
        </span>
      ),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, r: Certification) => (
        <Popconfirm title="确认发起补考？" onConfirm={() => handleRetake(r.id)}>
          <Button size="small" type="link">
            发起补考
          </Button>
        </Popconfirm>
      ),
    },
  ];

  // ── 考核项表 columns ──────────────────────────────────────────────────

  const examColumns = [
    { title: '考核项目', dataIndex: 'item', key: 'item' },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      render: (v: string) =>
        v === 'theory' ? (
          <Tag color="blue">理论</Tag>
        ) : (
          <Tag color="green">实操</Tag>
        ),
    },
    {
      title: '分数',
      dataIndex: 'score',
      key: 'score',
      render: (v: number | null) => (v !== null ? v : '待考'),
    },
    {
      title: '通过',
      dataIndex: 'passed',
      key: 'passed',
      render: (v: boolean, r: ExamItem) =>
        r.score !== null ? (
          v ? (
            <Tag color="green">通过</Tag>
          ) : (
            <Tag color="red">未通过</Tag>
          )
        ) : (
          '-'
        ),
    },
    {
      title: '考核人',
      dataIndex: 'examiner_id',
      key: 'examiner_id',
      render: (v: string | null) => v ?? '-',
    },
    {
      title: '考核日期',
      dataIndex: 'exam_date',
      key: 'exam_date',
      render: (v: string | null) => (v ? dayjs(v).format('YYYY-MM-DD') : '-'),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, r: ExamItem, idx: number) =>
        r.score === null && detail ? (
          <Button
            size="small"
            type="link"
            onClick={() =>
              setScoreModal({ certId: detail.id, idx, itemName: r.item })
            }
          >
            打分
          </Button>
        ) : null,
    },
  ];

  // ─── 渲染 ──────────────────────────────────────────────────────────────

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* ── Section 1: 认证总览仪表板 ────────────────────────────────────── */}
      <Card title="认证总览" loading={dashLoading}>
        {dash && (
          <StatisticCard.Group direction="row">
            <StatisticCard
              statistic={{
                title: '总认证数',
                value: dash.total,
                icon: <SafetyCertificateOutlined style={{ color: '#185FA5' }} />,
              }}
            />
            <StatisticCard
              statistic={{
                title: '已通过',
                value: dash.passed,
                valueStyle: { color: '#0F6E56' },
              }}
            />
            <StatisticCard
              statistic={{
                title: '未通过',
                value: dash.failed,
                valueStyle: { color: '#A32D2D' },
              }}
            />
            <StatisticCard
              statistic={{
                title: '即将过期',
                value: dash.expiring_soon,
                valueStyle: { color: '#BA7517' },
                icon: <WarningOutlined style={{ color: '#BA7517' }} />,
              }}
            />
            <StatisticCard
              statistic={{
                title: '平均分数',
                value: dash.avg_score.toFixed(1),
              }}
            />
          </StatisticCard.Group>
        )}
      </Card>

      {/* ── Section 2: 即将过期预警 ──────────────────────────────────────── */}
      {expiring.length > 0 && (
        <Card>
          <Alert
            type="warning"
            showIcon
            message={`有 ${expiring.length} 条认证即将过期（30天内），请及时安排补考`}
            style={{ marginBottom: 12 }}
          />
          <Table
            dataSource={expiring.slice(0, 5)}
            columns={expiringColumns}
            rowKey="id"
            size="small"
            pagination={false}
          />
        </Card>
      )}

      {/* ── Section 3: 认证记录列表 ──────────────────────────────────────── */}
      <ProTable<Certification>
        headerTitle="认证记录"
        actionRef={tableRef}
        columns={columns}
        rowKey="id"
        search={{ labelWidth: 'auto' }}
        request={async (params) => {
          const { current = 1, pageSize = 20, position, passed, store_id, employee_id } = params;
          let filters = '';
          if (position) filters += `&position=${position}`;
          if (passed !== undefined && passed !== null && passed !== '')
            filters += `&passed=${passed}`;
          if (store_id) filters += `&store_id=${encodeURIComponent(store_id)}`;
          if (employee_id)
            filters += `&employee_id=${encodeURIComponent(employee_id)}`;
          try {
            const resp = await txFetchData<{ items: Certification[]; total: number }>(
              `/api/v1/certifications?page=${current}&size=${pageSize}${filters}`,
            );
            return {
              data: resp.data?.items ?? [],
              total: resp.data?.total ?? 0,
              success: true,
            };
          } catch {
            message.error('加载认证列表失败');
            return { data: [], total: 0, success: false };
          }
        }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
        toolBarRender={() => [
          <ModalForm<{
            employee_id: string;
            store_id: string;
            position: string;
          }>
            key="create"
            title="发起认证"
            trigger={
              <Button type="primary" icon={<PlusOutlined />}>
                发起认证
              </Button>
            }
            modalProps={{ destroyOnClose: true }}
            onFinish={async (values) => {
              try {
                await txFetchData('/api/v1/certifications', {
                  method: 'POST',
                  body: JSON.stringify(values),
                });
                message.success('认证已创建，后端已自动生成考核项');
                tableRef.current?.reload();
                loadDashboard();
                return true;
              } catch {
                message.error('创建认证失败');
                return false;
              }
            }}
          >
            <ProFormText
              name="employee_id"
              label="员工ID"
              rules={[{ required: true, message: '请输入员工ID' }]}
              placeholder="请输入员工ID"
            />
            <ProFormText
              name="store_id"
              label="门店ID"
              rules={[{ required: true, message: '请输入门店ID' }]}
              placeholder="请输入门店ID"
            />
            <ProFormSelect
              name="position"
              label="岗位"
              rules={[{ required: true, message: '请选择岗位' }]}
              options={positionOptions}
              placeholder="请选择岗位"
            />
          </ModalForm>,
        ]}
      />

      {/* ── Section 5: 认证详情 Drawer ───────────────────────────────────── */}
      <Drawer
        title="认证详情"
        width={720}
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false);
          setDetail(null);
        }}
        loading={detailLoading}
        footer={
          detail && (
            <Space>
              {!isFinalized(detail) && (
                <Button
                  type="primary"
                  disabled={!allScored(detail)}
                  onClick={() => handleFinalize(detail.id)}
                >
                  完成评定
                </Button>
              )}
              {isFinalized(detail) && !detail.passed && (
                <Popconfirm
                  title="确认发起补考？考核项分数将被重置。"
                  onConfirm={() => handleRetake(detail.id)}
                >
                  <Button>发起补考</Button>
                </Popconfirm>
              )}
            </Space>
          )
        }
      >
        {detail && (
          <>
            <Descriptions column={2} bordered size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="员工ID">{detail.employee_id}</Descriptions.Item>
              <Descriptions.Item label="门店">{detail.store_id}</Descriptions.Item>
              <Descriptions.Item label="岗位">
                <Tag color={positionMap[detail.position]?.color ?? 'default'}>
                  {positionMap[detail.position]?.label ?? detail.position}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="总分">
                {detail.total_score !== null ? detail.total_score : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="通过状态">
                {detail.passed ? (
                  <Tag color="green">已通过</Tag>
                ) : (
                  <Tag color="red">未通过</Tag>
                )}
              </Descriptions.Item>
              <Descriptions.Item label="认证日期">
                {detail.certified_at
                  ? dayjs(detail.certified_at).format('YYYY-MM-DD')
                  : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="有效期至">
                {detail.expires_at ? (
                  <span
                    style={
                      isExpiringSoon(detail.expires_at)
                        ? { color: '#BA7517', fontWeight: 600 }
                        : undefined
                    }
                  >
                    {dayjs(detail.expires_at).format('YYYY-MM-DD')}
                  </span>
                ) : (
                  '-'
                )}
              </Descriptions.Item>
              <Descriptions.Item label="补考次数">
                {detail.retake_count > 0 ? detail.retake_count : '-'}
              </Descriptions.Item>
            </Descriptions>

            <Card title="考核项列表" size="small">
              <Table
                dataSource={detail.exam_items}
                columns={examColumns}
                rowKey={(_, idx) => String(idx)}
                size="small"
                pagination={false}
              />
            </Card>
          </>
        )}
      </Drawer>

      {/* ── Section 6: 打分 Modal ────────────────────────────────────────── */}
      <Modal
        title={`打分 — ${scoreModal?.itemName ?? ''}`}
        open={!!scoreModal}
        onCancel={() => {
          setScoreModal(null);
          setScoreValue(null);
          setExaminerValue('');
        }}
        onOk={handleScore}
        confirmLoading={scoreSubmitting}
        destroyOnClose
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: '8px 0' }}>
          <div>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>分数 (0-100)</div>
            <InputNumber
              min={0}
              max={100}
              value={scoreValue}
              onChange={(v) => setScoreValue(v)}
              style={{ width: '100%' }}
              placeholder="请输入分数"
            />
          </div>
          <div>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>考核人ID</div>
            <Input
              value={examinerValue}
              onChange={(e) => setExaminerValue(e.target.value)}
              placeholder="请输入考核人ID"
            />
          </div>
          {scoreValue !== null && (
            <div>
              <span>判定结果：</span>
              {scoreValue >= 60 ? (
                <Tag color="green">通过</Tag>
              ) : (
                <Tag color="red">未通过</Tag>
              )}
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}
