/**
 * ComplianceAuditPage -- 考勤深度合规审计
 * 域F · 组织人事 · 考勤管理
 *
 * 功能：
 *  1. 统计卡片：本月违规总数 / GPS异常 / 同设备 / 加班超时 / 待处理
 *  2. 操作区：选日期 + 门店 → "运行扫描" 按钮
 *  3. ProTable 违规记录列表 + 确认/驳回操作
 *
 * API:
 *  POST /api/v1/attendance-compliance/scan
 *  GET  /api/v1/attendance-compliance/violations
 *  GET  /api/v1/attendance-compliance/stats
 *  PUT  /api/v1/attendance-compliance/violations/:id/confirm
 *  PUT  /api/v1/attendance-compliance/violations/:id/dismiss
 */

import { useEffect, useRef, useState } from 'react';
import {
  Button,
  Card,
  Col,
  DatePicker,
  Input,
  message,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
} from 'antd';
import {
  ProTable,
} from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import {
  AlertOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  RadarChartOutlined,
  SafetyCertificateOutlined,
  ScanOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { txFetchData } from '../../../api';

const { Title } = Typography;
const TX_PRIMARY = '#FF6B35';

// ── Types ─────────────────────────────────────────────────────────────────────

interface ViolationRecord {
  id: string;
  employee_id: string;
  employee_name: string;
  store_id: string;
  check_date: string;
  violation_type: string;
  severity: string;
  detail: Record<string, unknown>;
  status: string;
  confirmed_by: string | null;
  confirmed_at: string | null;
  appeal_reason: string | null;
  created_at: string;
}

interface ComplianceStats {
  month: string;
  total: number;
  by_type: Record<string, number>;
  by_severity: Record<string, number>;
  by_status: Record<string, number>;
}

// ── 枚举映射 ──────────────────────────────────────────────────────────────────

const VIOLATION_TYPE_MAP: Record<string, { label: string; color: string }> = {
  gps_anomaly:      { label: 'GPS异常',   color: 'volcano' },
  same_device:      { label: '同设备打卡', color: 'red' },
  overtime_exceed:  { label: '加班超时',   color: 'orange' },
  proxy_punch:      { label: '代打卡',     color: 'magenta' },
  location_mismatch:{ label: '位置不符',   color: 'purple' },
};

const SEVERITY_MAP: Record<string, { label: string; color: string }> = {
  critical: { label: '紧急', color: 'red' },
  high:     { label: '高',   color: 'orange' },
  medium:   { label: '中',   color: 'gold' },
  low:      { label: '低',   color: 'blue' },
};

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  pending:   { label: '待处理', color: 'processing' },
  confirmed: { label: '已确认', color: 'error' },
  dismissed: { label: '已驳回', color: 'default' },
  appealed:  { label: '申诉中', color: 'warning' },
};

// ── 主组件 ────────────────────────────────────────────────────────────────────

export default function ComplianceAuditPage() {
  const actionRef = useRef<ActionType>();
  const [scanDate, setScanDate] = useState(dayjs());
  const [storeId, setStoreId] = useState<string>('');
  const [stores, setStores] = useState<{ store_id: string; store_name: string }[]>([]);
  const [stats, setStats] = useState<ComplianceStats | null>(null);
  const [scanning, setScanning] = useState(false);
  const [dismissReasonMap, setDismissReasonMap] = useState<Record<string, string>>({});

  // 加载门店列表
  useEffect(() => {
    txFetchData<{ items: { store_id: string; store_name: string }[] }>('/api/v1/stores?size=200')
      .then((res) => setStores(res?.items ?? []))
      .catch(() => {
        setStores([
          { store_id: 's001', store_name: '尝在一起·五一广场店' },
          { store_id: 's002', store_name: '尝在一起·岳麓山店' },
        ]);
      });
  }, []);

  // 加载统计
  useEffect(() => {
    const month = dayjs().format('YYYY-MM');
    txFetchData<ComplianceStats>(`/api/v1/attendance-compliance/stats?month=${month}`)
      .then((res) => setStats(res))
      .catch(() => setStats(null));
  }, []);

  // 运行扫描
  const handleScan = async () => {
    setScanning(true);
    try {
      await txFetchData('/api/v1/attendance-compliance/scan', {
        method: 'POST',
        body: JSON.stringify({
          date: scanDate.format('YYYY-MM-DD'),
          store_id: storeId || undefined,
        }),
      });
      message.success('合规扫描完成');
      actionRef.current?.reload();
      // 刷新统计
      const month = dayjs().format('YYYY-MM');
      const newStats = await txFetchData<ComplianceStats>(
        `/api/v1/attendance-compliance/stats?month=${month}`,
      );
      setStats(newStats);
    } catch {
      message.error('扫描失败，请重试');
    } finally {
      setScanning(false);
    }
  };

  // 确认违规
  const handleConfirm = async (id: string) => {
    const userId = localStorage.getItem('tx_user_id');
    if (!userId) {
      message.error('无法获取当前用户ID，请重新登录');
      return;
    }
    try {
      await txFetchData(`/api/v1/attendance-compliance/violations/${id}/confirm`, {
        method: 'PUT',
        body: JSON.stringify({ confirmer_id: userId }),
      });
      message.success('已确认违规');
      actionRef.current?.reload();
    } catch {
      message.error('操作失败');
    }
  };

  // 驳回违规
  const handleDismiss = async (id: string) => {
    const reason = (dismissReasonMap[id] || '').trim();
    if (!reason) {
      message.warning('请输入驳回原因');
      return;
    }
    try {
      await txFetchData(`/api/v1/attendance-compliance/violations/${id}/dismiss`, {
        method: 'PUT',
        body: JSON.stringify({ reason }),
      });
      message.success('已驳回');
      setDismissReasonMap((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      actionRef.current?.reload();
    } catch {
      message.error('操作失败');
    }
  };

  // ── 表格列定义 ──────────────────────────────────────────────────────────

  const columns: ProColumns<ViolationRecord>[] = [
    {
      title: '员工',
      dataIndex: 'employee_name',
      width: 100,
      ellipsis: true,
    },
    {
      title: '日期',
      dataIndex: 'check_date',
      valueType: 'date',
      width: 110,
    },
    {
      title: '违规类型',
      dataIndex: 'violation_type',
      width: 120,
      render: (_, r) => {
        const cfg = VIOLATION_TYPE_MAP[r.violation_type] ?? { label: r.violation_type, color: 'default' };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
      valueEnum: Object.fromEntries(
        Object.entries(VIOLATION_TYPE_MAP).map(([k, v]) => [k, { text: v.label }]),
      ),
    },
    {
      title: '严重度',
      dataIndex: 'severity',
      width: 80,
      render: (_, r) => {
        const cfg = SEVERITY_MAP[r.severity] ?? { label: r.severity, color: 'default' };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
      valueEnum: Object.fromEntries(
        Object.entries(SEVERITY_MAP).map(([k, v]) => [k, { text: v.label }]),
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (_, r) => {
        const cfg = STATUS_MAP[r.status] ?? { label: r.status, color: 'default' };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
      valueEnum: Object.fromEntries(
        Object.entries(STATUS_MAP).map(([k, v]) => [k, { text: v.label }]),
      ),
    },
    {
      title: '详情',
      dataIndex: 'detail',
      width: 200,
      ellipsis: true,
      search: false,
      render: (_, r) => {
        const d = r.detail || {};
        if (r.violation_type === 'gps_anomaly') {
          return `距门店 ${(d as Record<string, unknown>).distance_meters ?? (d as Record<string, unknown>).distance_m ?? '?'}m`;
        }
        if (r.violation_type === 'overtime_exceed') {
          return `加班 ${(d as Record<string, unknown>).overtime_hours ?? (d as Record<string, unknown>).weekly_ot_hours ?? '?'}h (上限36h)`;
        }
        if (r.violation_type === 'same_device' || r.violation_type === 'proxy_punch') {
          return `设备: ${(d as Record<string, unknown>).device_id ?? (d as Record<string, unknown>).device_info ?? '-'}`;
        }
        return JSON.stringify(d).slice(0, 60);
      },
    },
    {
      title: '操作',
      valueType: 'option',
      width: 160,
      render: (_, r) => {
        if (r.status !== 'pending') return '-';
        return (
          <Space size={4}>
            <Popconfirm
              title="确认此违规记录？"
              onConfirm={() => handleConfirm(r.id)}
            >
              <Button type="link" size="small" icon={<CheckCircleOutlined />}>
                确认
              </Button>
            </Popconfirm>
            <Popconfirm
              title={
                <div>
                  <div style={{ marginBottom: 8 }}>驳回原因：</div>
                  <Input.TextArea
                    rows={2}
                    value={dismissReasonMap[r.id] || ''}
                    onChange={(e) =>
                      setDismissReasonMap((prev) => ({ ...prev, [r.id]: e.target.value }))
                    }
                    placeholder="请输入驳回原因"
                  />
                </div>
              }
              onConfirm={() => handleDismiss(r.id)}
              onCancel={() =>
                setDismissReasonMap((prev) => {
                  const next = { ...prev };
                  delete next[r.id];
                  return next;
                })
              }
              okText="确定驳回"
              cancelText="取消"
            >
              <Button type="link" size="small" danger icon={<CloseCircleOutlined />}>
                驳回
              </Button>
            </Popconfirm>
          </Space>
        );
      },
    },
  ];

  // ── 渲染 ────────────────────────────────────────────────────────────────

  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 16 }}>
        <SafetyCertificateOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
        考勤深度合规审计
      </Title>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={4}>
          <Card size="small">
            <Statistic
              title="本月违规总数"
              value={stats?.total ?? 0}
              prefix={<AlertOutlined />}
              valueStyle={{ color: stats?.total ? '#A32D2D' : '#2C2C2A' }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic
              title="GPS异常"
              value={stats?.by_type?.gps_anomaly ?? 0}
              valueStyle={{ color: '#FA541C' }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic
              title="同设备打卡"
              value={stats?.by_type?.same_device ?? 0}
              valueStyle={{ color: '#F5222D' }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic
              title="加班超时"
              value={stats?.by_type?.overtime_exceed ?? 0}
              valueStyle={{ color: '#FA8C16' }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic
              title="代打卡"
              value={stats?.by_type?.proxy_punch ?? 0}
              valueStyle={{ color: '#EB2F96' }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic
              title="待处理"
              value={stats?.by_status?.pending ?? 0}
              prefix={<WarningOutlined />}
              valueStyle={{ color: TX_PRIMARY }}
            />
          </Card>
        </Col>
      </Row>

      {/* 扫描操作区 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space>
          <span>扫描日期：</span>
          <DatePicker
            value={scanDate}
            onChange={(v) => v && setScanDate(v)}
            allowClear={false}
          />
          <span>门店：</span>
          <Select
            style={{ width: 220 }}
            placeholder="全部门店"
            allowClear
            value={storeId || undefined}
            onChange={(v) => setStoreId(v || '')}
            options={stores.map((s) => ({ value: s.store_id, label: s.store_name }))}
          />
          <Button
            type="primary"
            icon={<ScanOutlined />}
            loading={scanning}
            onClick={handleScan}
          >
            运行合规扫描
          </Button>
        </Space>
      </Card>

      {/* 违规记录列表 */}
      <ProTable<ViolationRecord>
        actionRef={actionRef}
        columns={columns}
        rowKey="id"
        headerTitle={
          <Space>
            <RadarChartOutlined />
            违规记录
          </Space>
        }
        request={async (params) => {
          const query = new URLSearchParams();
          if (params.violation_type) query.set('violation_type', params.violation_type);
          if (params.status) query.set('status', params.status);
          if (storeId) query.set('store_id', storeId);
          query.set('page', String(params.current ?? 1));
          query.set('size', String(params.pageSize ?? 20));

          try {
            const res = await txFetchData<{ items: ViolationRecord[]; total: number }>(
              `/api/v1/attendance-compliance/violations?${query.toString()}`,
            );
            return {
              data: res?.items ?? [],
              total: res?.total ?? 0,
              success: true,
            };
          } catch {
            return { data: [], total: 0, success: false };
          }
        }}
        search={{ labelWidth: 'auto', defaultCollapsed: true }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
        dateFormatter="string"
        options={{ density: true, reload: true }}
      />
    </div>
  );
}
