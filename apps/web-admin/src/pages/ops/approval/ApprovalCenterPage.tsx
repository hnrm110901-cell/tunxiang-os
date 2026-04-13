/**
 * 审批中心 — 总部视角全局审批管理
 * 路由：/approval-center
 * API：GET /api/v1/ops/approvals/instances
 *       GET /api/v1/ops/approvals/instances/{id}
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Table, Tabs, Tag, Button, Space, Drawer, Typography, Spin,
  Timeline, Descriptions, Input, Select, Row, Col, Statistic, Card,
} from 'antd';
import { EyeOutlined, SearchOutlined, ClockCircleOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { txFetchData } from '../../../api';

const { Title, Text } = Typography;
const { Search } = Input;

// ─── 类型定义 ────────────────────────────────────────────────────────────────

type InstanceStatus = 'pending' | 'approved' | 'rejected' | 'expired';
type BusinessType =
  | 'discount' | 'refund' | 'void_order'
  | 'large_purchase' | 'leave' | 'payroll';

interface ApprovalStep {
  step_no: number;
  approver_role: string;
  approver_name?: string;
  status: 'pending' | 'approved' | 'rejected' | 'waiting';
  comment?: string;
  acted_at?: string;
}

interface ApprovalInstance {
  id: string;
  instance_no: string;
  title: string;
  business_type: BusinessType;
  initiator_name: string;
  initiator_id: string;
  store_name: string;
  amount_fen?: number;
  current_step: number;
  total_steps: number;
  status: InstanceStatus;
  created_at: string;
  deadline_at?: string;
  steps?: ApprovalStep[];
  context_data?: Record<string, unknown>;
}

interface InstanceListResponse {
  items: ApprovalInstance[];
  total: number;
}

// ─── 常量 ────────────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<InstanceStatus, { label: string; color: string }> = {
  pending:  { label: '审批中', color: 'orange' },
  approved: { label: '已通过', color: 'green' },
  rejected: { label: '已拒绝', color: 'red' },
  expired:  { label: '已过期', color: 'default' },
};

const BIZ_TYPE_CONFIG: Record<BusinessType, { label: string; color: string }> = {
  discount:       { label: '折扣审批', color: 'orange' },
  refund:         { label: '退款审批', color: 'red' },
  void_order:     { label: '作废单', color: 'volcano' },
  large_purchase: { label: '大额采购', color: 'blue' },
  leave:          { label: '员工请假', color: 'purple' },
  payroll:        { label: '薪资审批', color: 'gold' },
};

const STEP_STATUS_CONFIG: Record<string, { label: string; color: string; dot?: React.ReactNode }> = {
  approved: { label: '已通过', color: '#0F6E56' },
  rejected: { label: '已拒绝', color: '#A32D2D' },
  pending:  { label: '审批中', color: '#BA7517', dot: <ClockCircleOutlined style={{ color: '#BA7517' }} /> },
  waiting:  { label: '待处理', color: '#999' },
};

// ─── Mock 数据已移除，API 加载失败时回退空列表 ─────────────────────────────────

// ─── 辅助函数 ────────────────────────────────────────────────────────────────

function formatAmount(fen?: number): string {
  if (fen == null) return '—';
  return `¥${(fen / 100).toFixed(2)}`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  });
}

// ─── 详情 Drawer ─────────────────────────────────────────────────────────────

function InstanceDetailDrawer({
  instance,
  onClose,
}: {
  instance: ApprovalInstance | null;
  onClose: () => void;
}) {
  if (!instance) return null;
  const biz = BIZ_TYPE_CONFIG[instance.business_type];
  const status = STATUS_CONFIG[instance.status];

  const timelineItems = (instance.steps || []).map(step => {
    const sc = STEP_STATUS_CONFIG[step.status] || { label: step.status, color: '#999' };
    return {
      dot: sc.dot,
      color: sc.color,
      children: (
        <div>
          <div style={{ fontWeight: 600 }}>
            第{step.step_no}步 — {step.approver_role}
            {step.approver_name && <Text type="secondary"> ({step.approver_name})</Text>}
          </div>
          <Tag color={sc.color} style={{ marginTop: 4 }}>{sc.label}</Tag>
          {step.comment && (
            <div style={{ marginTop: 4, color: '#5F5E5A', fontSize: 13 }}>
              意见：{step.comment}
            </div>
          )}
          {step.acted_at && (
            <div style={{ fontSize: 12, color: '#B4B2A9', marginTop: 2 }}>
              {formatDate(step.acted_at)}
            </div>
          )}
        </div>
      ),
    };
  });

  return (
    <Drawer
      title={
        <Space>
          <Tag color={biz?.color}>{biz?.label}</Tag>
          <Text strong>{instance.title}</Text>
        </Space>
      }
      placement="right"
      width={480}
      open={!!instance}
      onClose={onClose}
    >
      <Descriptions column={2} size="small" bordered style={{ marginBottom: 24 }}>
        <Descriptions.Item label="审批编号" span={2}>
          <Text copyable>{instance.instance_no}</Text>
        </Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag color={status.color}>{status.label}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="金额">
          <Text strong>{formatAmount(instance.amount_fen)}</Text>
        </Descriptions.Item>
        <Descriptions.Item label="发起人">{instance.initiator_name}</Descriptions.Item>
        <Descriptions.Item label="门店">{instance.store_name}</Descriptions.Item>
        <Descriptions.Item label="当前进度" span={2}>
          {instance.current_step} / {instance.total_steps} 步
        </Descriptions.Item>
        <Descriptions.Item label="创建时间" span={2}>
          {formatDate(instance.created_at)}
        </Descriptions.Item>
        {instance.deadline_at && (
          <Descriptions.Item label="截止时间" span={2}>
            <Text type={new Date(instance.deadline_at) < new Date() ? 'danger' : 'secondary'}>
              {formatDate(instance.deadline_at)}
            </Text>
          </Descriptions.Item>
        )}
      </Descriptions>

      <div style={{ marginBottom: 12 }}>
        <Text strong>审批步骤时间轴</Text>
      </div>
      {timelineItems.length > 0 ? (
        <Timeline items={timelineItems} />
      ) : (
        <Text type="secondary">暂无步骤信息</Text>
      )}
    </Drawer>
  );
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function ApprovalCenterPage() {
  const [instances, setInstances] = useState<ApprovalInstance[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [activeTab, setActiveTab] = useState<'all' | 'pending' | 'completed'>('all');
  const [keyword, setKeyword] = useState('');
  const [bizFilter, setBizFilter] = useState<BusinessType | ''>('');
  const [detailInstance, setDetailInstance] = useState<ApprovalInstance | null>(null);

  // ── 统计数字 ──
  const pendingCount = instances.filter(i => i.status === 'pending').length;
  const approvedCount = instances.filter(i => i.status === 'approved').length;
  const rejectedCount = instances.filter(i => i.status === 'rejected').length;
  const expiredCount = instances.filter(i => i.status === 'expired').length;

  const loadInstances = useCallback(async (p = 1, tab = activeTab, kw = keyword, biz = bizFilter) => {
    setLoading(true);
    try {
      const statusParam = tab === 'pending' ? '&status=pending'
        : tab === 'completed' ? '&status=approved,rejected,expired'
        : '';
      const kwParam = kw ? `&keyword=${encodeURIComponent(kw)}` : '';
      const bizParam = biz ? `&business_type=${encodeURIComponent(biz)}` : '';
      const res = await txFetchData<InstanceListResponse>(
        `/api/v1/ops/approvals/instances?page=${p}&size=20${statusParam}${kwParam}${bizParam}`,
      );
      setInstances(res?.items ?? []);
      setTotal(res?.total ?? 0);
    } catch {
      // API 失败时保持空列表
      setInstances([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [activeTab, keyword, bizFilter]);

  useEffect(() => {
    loadInstances(page);
  }, [loadInstances, page]);

  // 切 Tab 重置到第一页
  const handleTabChange = (tab: string) => {
    setActiveTab(tab as 'all' | 'pending' | 'completed');
    setPage(1);
    loadInstances(1, tab as 'all' | 'pending' | 'completed', keyword, bizFilter);
  };

  const handleSearch = (kw: string) => {
    setKeyword(kw);
    setPage(1);
    loadInstances(1, activeTab, kw, bizFilter);
  };

  const handleBizFilter = (biz: BusinessType | '') => {
    setBizFilter(biz);
    setPage(1);
    loadInstances(1, activeTab, keyword, biz);
  };

  // 打开详情：先用列表数据，再懒加载完整步骤
  const handleViewDetail = async (record: ApprovalInstance) => {
    setDetailInstance(record);
    if (!record.steps || record.steps.length === 0) {
      try {
        const full = await txFetchData<ApprovalInstance>(`/api/v1/ops/approvals/instances/${record.id}`);
        setDetailInstance(full ?? record);
      } catch {
        /* 使用列表数据 */
      }
    }
  };

  // ── 表格列 ──
  const columns: ColumnsType<ApprovalInstance> = [
    {
      title: '审批编号',
      dataIndex: 'instance_no',
      key: 'instance_no',
      width: 140,
      render: (no: string) => <Text code style={{ fontSize: 12 }}>{no}</Text>,
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (t: string) => <Text>{t}</Text>,
    },
    {
      title: '业务类型',
      dataIndex: 'business_type',
      key: 'business_type',
      width: 100,
      render: (bt: BusinessType) => {
        const conf = BIZ_TYPE_CONFIG[bt];
        return <Tag color={conf?.color}>{conf?.label ?? bt}</Tag>;
      },
    },
    {
      title: '发起人',
      dataIndex: 'initiator_name',
      key: 'initiator_name',
      width: 90,
    },
    {
      title: '金额',
      dataIndex: 'amount_fen',
      key: 'amount_fen',
      width: 100,
      render: (fen?: number) => <Text strong>{formatAmount(fen)}</Text>,
    },
    {
      title: '当前步骤',
      key: 'step_progress',
      width: 90,
      render: (_, r) => (
        <Text type="secondary">{r.current_step} / {r.total_steps}</Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (s: InstanceStatus) => {
        const conf = STATUS_CONFIG[s];
        return <Tag color={conf.color}>{conf.label}</Tag>;
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (t: string) => formatDate(t),
    },
    {
      title: '操作',
      key: 'actions',
      width: 80,
      render: (_, record) => (
        <Button
          type="link"
          size="small"
          icon={<EyeOutlined />}
          onClick={() => handleViewDetail(record)}
        >
          查看
        </Button>
      ),
    },
  ];

  const tabItems = [
    { key: 'all',       label: `全部 (${total})` },
    { key: 'pending',   label: `待审批 (${pendingCount})` },
    { key: 'completed', label: '已完成' },
  ];

  return (
    <div style={{ padding: '24px 32px', background: '#f8f7f5', minHeight: '100vh' }}>
      {/* 标题 */}
      <div style={{ marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0, color: '#1E2A3A' }}>审批中心</Title>
        <Text type="secondary" style={{ fontSize: 13 }}>总部视角 · 跨门店审批流统一管理</Text>
      </div>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        {[
          { label: '审批中', value: pendingCount, color: '#BA7517' },
          { label: '已通过', value: approvedCount, color: '#0F6E56' },
          { label: '已拒绝', value: rejectedCount, color: '#A32D2D' },
          { label: '已过期', value: expiredCount, color: '#999' },
        ].map(item => (
          <Col span={6} key={item.label}>
            <Card size="small" style={{ textAlign: 'center', borderRadius: 8 }}>
              <Statistic
                title={item.label}
                value={item.value}
                valueStyle={{ color: item.color, fontSize: 28 }}
              />
            </Card>
          </Col>
        ))}
      </Row>

      {/* 内容区 */}
      <div style={{ background: '#fff', borderRadius: 8, padding: '16px 24px' }}>
        {/* 搜索/筛选栏 */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          <Search
            placeholder="搜索审批编号或标题"
            allowClear
            style={{ width: 260 }}
            prefix={<SearchOutlined />}
            onSearch={handleSearch}
          />
          <Select
            placeholder="业务类型"
            allowClear
            style={{ width: 140 }}
            value={bizFilter || undefined}
            onChange={v => handleBizFilter(v ?? '')}
            options={[
              ...Object.entries(BIZ_TYPE_CONFIG).map(([k, v]) => ({
                value: k as BusinessType,
                label: v.label,
              })),
            ]}
          />
        </div>

        {/* Tabs */}
        <Tabs
          activeKey={activeTab}
          onChange={handleTabChange}
          items={tabItems}
          style={{ marginBottom: 8 }}
        />

        {/* 表格 */}
        <Table<ApprovalInstance>
          columns={columns}
          dataSource={instances}
          rowKey="id"
          loading={loading}
          pagination={{
            current: page,
            total,
            pageSize: 20,
            showSizeChanger: false,
            showTotal: t => `共 ${t} 条`,
            onChange: setPage,
          }}
          size="middle"
        />
      </div>

      {/* 详情侧边 Drawer */}
      <InstanceDetailDrawer
        instance={detailInstance}
        onClose={() => setDetailInstance(null)}
      />
    </div>
  );
}
