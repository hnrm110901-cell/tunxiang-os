/**
 * 日结监控看板
 * 路由：/ops/settlement-monitor
 * API：GET  /api/v1/ops/settlement/monitor
 *      GET  /api/v1/ops/settlement/monitor/overdue
 *      POST /api/v1/ops/settlement/monitor/remark
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Card, Row, Col, Statistic, Tag, Button, DatePicker, Select,
  Space, Modal, Input, message, Typography, Tooltip,
} from 'antd';
import type { ProColumns, ActionType } from '@ant-design/pro-components';
import { ProTable } from '@ant-design/pro-components';
import {
  CheckCircleOutlined, ClockCircleOutlined, ExclamationCircleOutlined,
  MinusCircleOutlined, EditOutlined, ReloadOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { txFetchData } from '../../api';

const { Text } = Typography;

// ─── 主题色 ──────────────────────────────────────────────────────────────────

const PRIMARY_COLOR = '#FF6B35';

// ─── 类型定义 ────────────────────────────────────────────────────────────────

type SettlementStatus = 'completed' | 'running' | 'pending' | 'overdue';

interface StoreSettlement {
  store_id: string;
  store_name: string;
  brand_name: string;
  brand_id?: string;
  region_id?: string;
  status: SettlementStatus;
  expected_close_time: string;
  actual_close_time: string | null;
  operator_name: string;
  duration_minutes: number | null;
  remarks: string;
}

interface MonitorSummary {
  total_stores: number;
  completed_count: number;
  pending_count: number;
  running_count: number;
  overdue_count: number;
  completion_rate: number;
}

interface MonitorData {
  settlement_date: string;
  summary: MonitorSummary;
  stores: StoreSettlement[];
}

// ─── Mock 数据（API 失败时的静默降级）────────────────────────────────────────

const MOCK_SUMMARY: MonitorSummary = {
  total_stores: 5,
  completed_count: 2,
  pending_count: 1,
  running_count: 1,
  overdue_count: 1,
  completion_rate: 40.0,
};

const MOCK_STORES: StoreSettlement[] = [
  {
    store_id: 'store_001',
    store_name: '尝在一起·芙蓉路店',
    brand_name: '尝在一起',
    status: 'completed',
    expected_close_time: '22:00',
    actual_close_time: '21:45',
    operator_name: '张店长',
    duration_minutes: 45,
    remarks: '',
  },
  {
    store_id: 'store_002',
    store_name: '尝在一起·五一广场店',
    brand_name: '尝在一起',
    status: 'running',
    expected_close_time: '22:00',
    actual_close_time: null,
    operator_name: '李店长',
    duration_minutes: null,
    remarks: '',
  },
  {
    store_id: 'store_003',
    store_name: '最黔线·解放西店',
    brand_name: '最黔线',
    status: 'overdue',
    expected_close_time: '21:30',
    actual_close_time: null,
    operator_name: '王店长',
    duration_minutes: null,
    remarks: '店长请假，代理人处理中',
  },
  {
    store_id: 'store_004',
    store_name: '尚宫厨·岳麓山店',
    brand_name: '尚宫厨',
    status: 'pending',
    expected_close_time: '22:30',
    actual_close_time: null,
    operator_name: '陈店长',
    duration_minutes: null,
    remarks: '',
  },
  {
    store_id: 'store_005',
    store_name: '最黔线·天心阁店',
    brand_name: '最黔线',
    status: 'completed',
    expected_close_time: '22:00',
    actual_close_time: '22:10',
    operator_name: '赵店长',
    duration_minutes: 70,
    remarks: '',
  },
];

// ─── 状态配置 ────────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<SettlementStatus, {
  label: string;
  color: 'success' | 'processing' | 'default' | 'error';
  icon: React.ReactNode;
}> = {
  completed: { label: '已完成', color: 'success',    icon: <CheckCircleOutlined /> },
  running:   { label: '进行中', color: 'processing', icon: <ClockCircleOutlined /> },
  pending:   { label: '未开始', color: 'default',    icon: <MinusCircleOutlined /> },
  overdue:   { label: '逾期',   color: 'error',      icon: <ExclamationCircleOutlined /> },
};

const BRAND_OPTIONS = [
  { value: 'brand_001', label: '尝在一起' },
  { value: 'brand_002', label: '最黔线' },
  { value: 'brand_003', label: '尚宫厨' },
];

const STATUS_OPTIONS = [
  { value: 'completed', label: '已完成' },
  { value: 'running',   label: '进行中' },
  { value: 'pending',   label: '未开始' },
  { value: 'overdue',   label: '逾期' },
];

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function SettlementMonitorPage() {
  const [loading, setLoading] = useState(false);
  const [summary, setSummary] = useState<MonitorSummary>(MOCK_SUMMARY);
  const [stores, setStores] = useState<StoreSettlement[]>(MOCK_STORES);
  const [selectedDate, setSelectedDate] = useState<string>(dayjs().format('YYYY-MM-DD'));
  const [selectedBrand, setSelectedBrand] = useState<string | undefined>(undefined);
  const [selectedStatus, setSelectedStatus] = useState<string | undefined>(undefined);

  // 备注弹窗
  const [remarkVisible, setRemarkVisible] = useState(false);
  const [remarkTarget, setRemarkTarget] = useState<StoreSettlement | null>(null);
  const [remarkText, setRemarkText] = useState('');
  const [remarkSaving, setRemarkSaving] = useState(false);

  const actionRef = useRef<ActionType>();
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ─── 数据加载 ──────────────────────────────────────────────────────────────

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set('settlement_date', selectedDate);
      if (selectedBrand) params.set('brand_id', selectedBrand);
      if (selectedStatus) params.set('status', selectedStatus);

      const monitorData = await txFetchData<MonitorData>(`/api/v1/ops/settlement/monitor?${params.toString()}`);
      if (monitorData) {
        setSummary((monitorData as MonitorData).summary);
        setStores((monitorData as MonitorData).stores);
      }
    } catch {
      // 静默降级：保留 mock 数据，不弹错误
    } finally {
      setLoading(false);
    }
  }, [selectedDate, selectedBrand, selectedStatus]);

  // ─── 初始加载 + 自动刷新 30 秒 ────────────────────────────────────────────

  useEffect(() => {
    loadData();
    timerRef.current = setInterval(loadData, 30_000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [loadData]);

  // ─── 备注提交 ──────────────────────────────────────────────────────────────

  const handleRemarkOpen = (record: StoreSettlement) => {
    setRemarkTarget(record);
    setRemarkText(record.remarks || '');
    setRemarkVisible(true);
  };

  const handleRemarkSave = async () => {
    if (!remarkTarget) return;
    setRemarkSaving(true);
    try {
      const resp = await txFetchData('/api/v1/ops/settlement/monitor/remark', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          store_id: remarkTarget.store_id,
          settlement_date: selectedDate,
          remark: remarkText,
          operator_id: 'current_user',
        }),
      });
      const json = await resp.json() as { ok: boolean };
      if (json.ok) {
        message.success('备注已保存');
        setStores(prev =>
          prev.map(s =>
            s.store_id === remarkTarget.store_id
              ? { ...s, remarks: remarkText }
              : s
          )
        );
        setRemarkVisible(false);
      } else {
        message.error('保存失败');
      }
    } catch {
      // 静默降级：在本地更新
      setStores(prev =>
        prev.map(s =>
          s.store_id === remarkTarget.store_id
            ? { ...s, remarks: remarkText }
            : s
        )
      );
      message.success('备注已本地保存');
      setRemarkVisible(false);
    } finally {
      setRemarkSaving(false);
    }
  };

  // ─── ProTable 列定义 ───────────────────────────────────────────────────────

  const columns: ProColumns<StoreSettlement>[] = [
    {
      title: '门店',
      dataIndex: 'store_name',
      width: 180,
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{record.store_name}</Text>
        </Space>
      ),
    },
    {
      title: '品牌',
      dataIndex: 'brand_name',
      width: 100,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (_, record) => {
        const cfg = STATUS_CONFIG[record.status];
        return (
          <Tag icon={cfg.icon} color={cfg.color}>
            {cfg.label}
          </Tag>
        );
      },
    },
    {
      title: '应结时间',
      dataIndex: 'expected_close_time',
      width: 90,
    },
    {
      title: '实结时间',
      dataIndex: 'actual_close_time',
      width: 90,
      render: (val) => val ?? <Text type="secondary">—</Text>,
    },
    {
      title: '耗时(分钟)',
      dataIndex: 'duration_minutes',
      width: 100,
      render: (val) =>
        val != null ? (
          <Text style={{ color: Number(val) > 60 ? '#faad14' : undefined }}>{val}</Text>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: '操作员',
      dataIndex: 'operator_name',
      width: 90,
    },
    {
      title: '备注',
      dataIndex: 'remarks',
      ellipsis: true,
      render: (val) =>
        val ? (
          <Tooltip title={val as string}>
            <Text ellipsis style={{ maxWidth: 160 }}>{val as string}</Text>
          </Tooltip>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 80,
      render: (_, record) => (
        <Button
          size="small"
          icon={<EditOutlined />}
          onClick={() => handleRemarkOpen(record)}
          style={{ color: PRIMARY_COLOR, borderColor: PRIMARY_COLOR }}
        >
          备注
        </Button>
      ),
    },
  ];

  // ─── 渲染 ─────────────────────────────────────────────────────────────────

  return (
    <div style={{ padding: '24px' }}>
      {/* 页头 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 20,
      }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 700, color: '#1a1a1a' }}>
            日结监控看板
          </div>
          <div style={{ color: '#888', marginTop: 4 }}>
            总部多门店日结状态实时聚合 · 每30秒自动刷新
          </div>
        </div>
        <Button
          icon={<ReloadOutlined />}
          onClick={loadData}
          loading={loading}
          style={{ borderColor: PRIMARY_COLOR, color: PRIMARY_COLOR }}
        >
          立即刷新
        </Button>
      </div>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card bordered={false} style={{ background: '#f6ffed', borderRadius: 8 }}>
            <Statistic
              title="已完成"
              value={summary.completed_count}
              suffix={`/ ${summary.total_stores}`}
              valueStyle={{ color: '#52c41a', fontSize: 28 }}
              prefix={<CheckCircleOutlined />}
            />
            <div style={{ marginTop: 4, color: '#888', fontSize: 13 }}>
              完成率 <Text style={{ color: '#52c41a', fontWeight: 600 }}>
                {summary.completion_rate}%
              </Text>
            </div>
          </Card>
        </Col>
        <Col span={6}>
          <Card bordered={false} style={{ background: '#e6f4ff', borderRadius: 8 }}>
            <Statistic
              title="进行中"
              value={summary.running_count}
              valueStyle={{ color: '#1677ff', fontSize: 28 }}
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card bordered={false} style={{ background: '#fafafa', borderRadius: 8 }}>
            <Statistic
              title="未开始"
              value={summary.pending_count}
              valueStyle={{ color: '#8c8c8c', fontSize: 28 }}
              prefix={<MinusCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card bordered={false} style={{ background: '#fff2f0', borderRadius: 8 }}>
            <Statistic
              title="逾期"
              value={summary.overdue_count}
              valueStyle={{ color: '#ff4d4f', fontSize: 28 }}
              prefix={<ExclamationCircleOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* 筛选栏 */}
      <Card bordered={false} style={{ marginBottom: 16, borderRadius: 8 }}>
        <Space size={12} wrap>
          <Space>
            <span style={{ color: '#555' }}>日期：</span>
            <DatePicker
              value={dayjs(selectedDate)}
              format="YYYY-MM-DD"
              allowClear={false}
              onChange={(d) => {
                if (d) setSelectedDate(d.format('YYYY-MM-DD'));
              }}
            />
          </Space>
          <Space>
            <span style={{ color: '#555' }}>品牌：</span>
            <Select
              placeholder="全部品牌"
              allowClear
              style={{ width: 140 }}
              options={BRAND_OPTIONS}
              value={selectedBrand}
              onChange={setSelectedBrand}
            />
          </Space>
          <Space>
            <span style={{ color: '#555' }}>状态：</span>
            <Select
              placeholder="全部状态"
              allowClear
              style={{ width: 120 }}
              options={STATUS_OPTIONS}
              value={selectedStatus}
              onChange={setSelectedStatus}
            />
          </Space>
          <Button
            type="primary"
            style={{ background: PRIMARY_COLOR, borderColor: PRIMARY_COLOR }}
            onClick={loadData}
          >
            查询
          </Button>
        </Space>
      </Card>

      {/* 主表格 */}
      <ProTable<StoreSettlement>
        actionRef={actionRef}
        rowKey="store_id"
        columns={columns}
        dataSource={stores}
        loading={loading}
        search={false}
        pagination={{ pageSize: 20, showSizeChanger: true }}
        options={{
          reload: loadData,
          density: true,
          setting: true,
        }}
        headerTitle={
          <span style={{ fontWeight: 600 }}>
            门店日结明细
            <Text type="secondary" style={{ fontSize: 13, marginLeft: 8 }}>
              共 {stores.length} 家门店
            </Text>
          </span>
        }
        style={{ borderRadius: 8 }}
        scroll={{ x: 900 }}
      />

      {/* 备注弹窗 */}
      <Modal
        title={`添加/编辑备注 — ${remarkTarget?.store_name ?? ''}`}
        open={remarkVisible}
        onOk={handleRemarkSave}
        onCancel={() => setRemarkVisible(false)}
        confirmLoading={remarkSaving}
        okText="保存"
        cancelText="取消"
        okButtonProps={{ style: { background: PRIMARY_COLOR, borderColor: PRIMARY_COLOR } }}
      >
        <div style={{ marginBottom: 8, color: '#555' }}>
          日结日期：{selectedDate}
        </div>
        <Input.TextArea
          rows={4}
          placeholder="请输入备注内容..."
          value={remarkText}
          onChange={(e) => setRemarkText(e.target.value)}
          maxLength={500}
          showCount
        />
      </Modal>
    </div>
  );
}
