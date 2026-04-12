/**
 * StoreReadinessPage — 今日营业就绪度
 *
 * 功能：
 *  1. 就绪度总览仪表板（4张统计卡片）
 *  2. 今日门店就绪度概览（高亮卡片）
 *  3. 就绪度历史列表（ProTable + 维度展开行）
 *  4. 就绪度趋势图（Line chart + 参考线）
 *  5. 新建/更新就绪度评分（ModalForm）
 *  6. 详情Drawer（Descriptions + Progress + Timeline）
 *
 * API:
 *  GET  /api/v1/store-readiness/dashboard
 *  GET  /api/v1/store-readiness/today
 *  GET  /api/v1/store-readiness?page=X&size=Y&...
 *  GET  /api/v1/store-readiness/trend?store_id=X&days=Y
 *  POST /api/v1/store-readiness
 *  DELETE /api/v1/store-readiness/:id
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { ProTable, StatisticCard, ModalForm, ProFormText, ProFormDatePicker, ProFormSelect } from '@ant-design/pro-components';
import type { ProColumns, ActionType } from '@ant-design/pro-components';
import {
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  InputNumber,
  message,
  Popconfirm,
  Progress,
  Row,
  Select,
  Space,
  Table,
  Timeline,
  Typography,
  Form,
} from 'antd';
import {
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  CloseCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { Line } from '@ant-design/charts';
import dayjs from 'dayjs';
import { txFetchData } from '../../api/client';

const { Title, Text } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface ReadinessRecord {
  id: string;
  store_id: string;
  score_date: string;
  shift: string;
  overall_score: number;
  dimensions: {
    shift_coverage: number;
    skill_coverage: number;
    newbie_ratio: number;
    training_completion: number;
  };
  risk_level: string;
  risk_positions: { position: string; gap: number; reason: string }[];
  action_items: { action: string; priority: string; assigned_to: string }[];
  created_at: string;
  updated_at: string;
}

interface DashboardData {
  green_count: number;
  yellow_count: number;
  red_count: number;
  avg_score: number;
  worst_stores: ReadinessRecord[];
  dimension_averages: {
    shift_coverage: number;
    skill_coverage: number;
    newbie_ratio: number;
    training_completion: number;
  };
}

interface TrendPoint {
  score_date: string;
  overall_score: number;
}

// ─── 常量 ────────────────────────────────────────────────────────────────────

const SHIFT_LABELS: Record<string, string> = {
  full_day: '全天',
  morning: '早班',
  afternoon: '午班',
  evening: '晚班',
};

const RISK_BORDER_COLOR: Record<string, string> = {
  red: '#A32D2D',
  yellow: '#BA7517',
  green: '#0F6E56',
};

const RISK_BADGE_STATUS: Record<string, 'success' | 'warning' | 'error'> = {
  green: 'success',
  yellow: 'warning',
  red: 'error',
};

const RISK_LABEL: Record<string, string> = {
  green: '正常',
  yellow: '警告',
  red: '异常',
};

function scoreColor(score: number): string {
  if (score >= 80) return '#0F6E56';
  if (score >= 60) return '#BA7517';
  return '#A32D2D';
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function StoreReadinessPage() {
  const tableRef = useRef<ActionType>();

  // Section 1: Dashboard
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [dashLoading, setDashLoading] = useState(false);

  // Section 2: Today
  const [todayItems, setTodayItems] = useState<ReadinessRecord[]>([]);
  const [todayLoading, setTodayLoading] = useState(false);

  // Section 4: Trend
  const [trendStoreId, setTrendStoreId] = useState('');
  const [trendDays, setTrendDays] = useState(7);
  const [trendData, setTrendData] = useState<TrendPoint[]>([]);
  const [trendLoading, setTrendLoading] = useState(false);

  // Section 5: Modal
  const [modalOpen, setModalOpen] = useState(false);

  // Section 6: Drawer
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detailRecord, setDetailRecord] = useState<ReadinessRecord | null>(null);

  // ─── 数据获取 ──────────────────────────────────────────────────────────────

  const fetchDashboard = useCallback(async () => {
    setDashLoading(true);
    try {
      const res = await txFetchData<DashboardData>('/api/v1/store-readiness/dashboard');
      setDashboard(res.data);
    } catch (err) {
      message.error('获取仪表板数据失败');
    } finally {
      setDashLoading(false);
    }
  }, []);

  const fetchToday = useCallback(async () => {
    setTodayLoading(true);
    try {
      const res = await txFetchData<{ items: ReadinessRecord[] }>('/api/v1/store-readiness/today');
      setTodayItems(res.data?.items ?? []);
    } catch (err) {
      message.error('获取今日就绪度失败');
    } finally {
      setTodayLoading(false);
    }
  }, []);

  const fetchTrend = useCallback(async () => {
    if (!trendStoreId) return;
    setTrendLoading(true);
    try {
      const res = await txFetchData<{ items: TrendPoint[] }>(
        `/api/v1/store-readiness/trend?store_id=${encodeURIComponent(trendStoreId)}&days=${trendDays}`,
      );
      setTrendData(res.data?.items ?? []);
    } catch (err) {
      message.error('获取趋势数据失败');
    } finally {
      setTrendLoading(false);
    }
  }, [trendStoreId, trendDays]);

  useEffect(() => {
    fetchDashboard();
    fetchToday();
  }, [fetchDashboard, fetchToday]);

  useEffect(() => {
    fetchTrend();
  }, [fetchTrend]);

  // ─── 操作 ──────────────────────────────────────────────────────────────────

  const handleDelete = async (id: string) => {
    try {
      await txFetchData(`/api/v1/store-readiness/${id}`, { method: 'DELETE' });
      message.success('删除成功');
      tableRef.current?.reload();
      fetchDashboard();
      fetchToday();
    } catch (err) {
      message.error('删除失败');
    }
  };

  const openDetail = (record: ReadinessRecord) => {
    setDetailRecord(record);
    setDrawerOpen(true);
  };

  // ─── Section 3: ProTable columns ──────────────────────────────────────────

  const columns: ProColumns<ReadinessRecord>[] = [
    {
      title: '门店',
      dataIndex: 'store_id',
      ellipsis: true,
      width: 160,
    },
    {
      title: '评分日期',
      dataIndex: 'score_date',
      valueType: 'date',
      width: 120,
    },
    {
      title: '班次',
      dataIndex: 'shift',
      valueType: 'select',
      width: 100,
      valueEnum: {
        full_day: { text: '全天' },
        morning: { text: '早班' },
        afternoon: { text: '午班' },
        evening: { text: '晚班' },
      },
      hideInSearch: true,
      render: (_, r) => SHIFT_LABELS[r.shift] ?? r.shift,
    },
    {
      title: '就绪分',
      dataIndex: 'overall_score',
      width: 100,
      hideInSearch: true,
      sorter: true,
      render: (_, r) => (
        <Text strong style={{ color: scoreColor(r.overall_score) }}>
          {r.overall_score.toFixed(1)}
        </Text>
      ),
    },
    {
      title: '风险等级',
      dataIndex: 'risk_level',
      width: 100,
      valueType: 'select',
      valueEnum: {
        green: { text: '正常', status: 'Success' },
        yellow: { text: '警告', status: 'Warning' },
        red: { text: '异常', status: 'Error' },
      },
      render: (_, r) => (
        <Badge status={RISK_BADGE_STATUS[r.risk_level] ?? 'default'} text={RISK_LABEL[r.risk_level] ?? r.risk_level} />
      ),
    },
    {
      title: '缺岗数',
      dataIndex: 'risk_positions',
      width: 80,
      hideInSearch: true,
      render: (_, r) => (
        <Text type={r.risk_positions.length > 0 ? 'danger' : undefined}>
          {r.risk_positions.length}
        </Text>
      ),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 180,
      render: (_, r) => [
        <a key="detail" onClick={() => openDetail(r)}>详情</a>,
        <a key="edit" onClick={() => { setDetailRecord(r); setModalOpen(true); }}>编辑</a>,
        <Popconfirm key="del" title="确认删除？" onConfirm={() => handleDelete(r.id)}>
          <a style={{ color: '#A32D2D' }}>删除</a>
        </Popconfirm>,
      ],
    },
  ];

  // ─── 维度展开行 ────────────────────────────────────────────────────────────

  const expandedRowRender = (record: ReadinessRecord) => {
    const dims = record.dimensions;
    const items = [
      { label: '排班覆盖率', value: dims.shift_coverage },
      { label: '技能覆盖率', value: dims.skill_coverage },
      { label: '新人占比', value: dims.newbie_ratio },
      { label: '培训完成率', value: dims.training_completion },
    ];
    return (
      <Row gutter={24} style={{ padding: '8px 0' }}>
        {items.map((item) => (
          <Col span={6} key={item.label}>
            <Text type="secondary" style={{ fontSize: 12 }}>{item.label}</Text>
            <Progress
              percent={item.value}
              size="small"
              strokeColor={scoreColor(item.value)}
              format={(v) => `${v}%`}
            />
          </Col>
        ))}
      </Row>
    );
  };

  // ─── 趋势图配置 ────────────────────────────────────────────────────────────

  const trendConfig = {
    data: trendData,
    xField: 'score_date',
    yField: 'overall_score',
    smooth: true,
    point: { size: 3, shape: 'circle' },
    yAxis: { min: 0, max: 100 },
    annotations: [
      {
        type: 'line' as const,
        start: ['min', 80] as [string, number],
        end: ['max', 80] as [string, number],
        style: { stroke: '#0F6E56', lineDash: [4, 4], lineWidth: 1 },
        text: { content: '80分', position: 'start' as const, style: { fill: '#0F6E56', fontSize: 11 } },
      },
      {
        type: 'line' as const,
        start: ['min', 60] as [string, number],
        end: ['max', 60] as [string, number],
        style: { stroke: '#A32D2D', lineDash: [4, 4], lineWidth: 1 },
        text: { content: '60分', position: 'start' as const, style: { fill: '#A32D2D', fontSize: 11 } },
      },
    ],
  };

  // ─── 渲染 ──────────────────────────────────────────────────────────────────

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>今日营业就绪度</Title>

      {/* ─── Section 1: 仪表板 ─── */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <StatisticCard
            loading={dashLoading}
            statistic={{
              title: '绿灯门店数',
              value: dashboard?.green_count ?? 0,
              icon: <CheckCircleOutlined style={{ color: '#0F6E56' }} />,
            }}
            style={{ borderTop: '3px solid #0F6E56' }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            loading={dashLoading}
            statistic={{
              title: '黄灯门店数',
              value: dashboard?.yellow_count ?? 0,
              icon: <ExclamationCircleOutlined style={{ color: '#BA7517' }} />,
            }}
            style={{ borderTop: '3px solid #BA7517' }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            loading={dashLoading}
            statistic={{
              title: '红灯门店数',
              value: dashboard?.red_count ?? 0,
              icon: <CloseCircleOutlined style={{ color: '#A32D2D' }} />,
            }}
            style={{ borderTop: '3px solid #A32D2D' }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            loading={dashLoading}
            statistic={{
              title: '平均就绪分',
              value: dashboard?.avg_score?.toFixed(1) ?? '—',
              suffix: '分',
            }}
            style={{ borderTop: '3px solid #185FA5' }}
          />
        </Col>
      </Row>

      {/* ─── Section 2: 今日就绪度概览 ─── */}
      <Card
        title="今日门店就绪度"
        loading={todayLoading}
        style={{ marginBottom: 24 }}
        extra={
          <Button icon={<ReloadOutlined />} size="small" onClick={fetchToday}>
            刷新
          </Button>
        }
      >
        {todayItems.length === 0 ? (
          <Text type="secondary">暂无今日就绪度数据</Text>
        ) : (
          <Row gutter={[16, 16]}>
            {todayItems.map((item) => {
              const borderColor = RISK_BORDER_COLOR[item.risk_level] ?? '#d9d9d9';
              return (
                <Col xs={24} sm={12} md={8} lg={6} key={item.id}>
                  <Card
                    hoverable
                    size="small"
                    style={{
                      borderLeft: `4px solid ${borderColor}`,
                      cursor: 'pointer',
                    }}
                    onClick={() => openDetail(item)}
                  >
                    <Space direction="vertical" size={4} style={{ width: '100%' }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {item.store_id.slice(0, 8)}
                      </Text>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <Text strong style={{ fontSize: 28, color: scoreColor(item.overall_score) }}>
                          {item.overall_score.toFixed(1)}
                        </Text>
                        <Badge
                          status={RISK_BADGE_STATUS[item.risk_level] ?? 'default'}
                          text={RISK_LABEL[item.risk_level] ?? item.risk_level}
                        />
                      </div>
                    </Space>
                  </Card>
                </Col>
              );
            })}
          </Row>
        )}
      </Card>

      {/* ─── Section 3: 历史列表 ─── */}
      <ProTable<ReadinessRecord>
        headerTitle="就绪度历史记录"
        actionRef={tableRef}
        columns={columns}
        rowKey="id"
        expandable={{ expandedRowRender }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
        request={async (params, sort) => {
          const query = new URLSearchParams();
          query.set('page', String(params.current ?? 1));
          query.set('size', String(params.pageSize ?? 20));
          if (params.store_id) query.set('store_id', params.store_id);
          if (params.risk_level) query.set('risk_level', params.risk_level);
          if (params.score_date) query.set('score_date', params.score_date);
          if (sort?.overall_score) {
            query.set('sort', sort.overall_score === 'ascend' ? 'overall_score' : '-overall_score');
          }
          try {
            const res = await txFetchData<{ items: ReadinessRecord[]; total: number }>(
              `/api/v1/store-readiness?${query.toString()}`,
            );
            return {
              data: res.data?.items ?? [],
              total: res.data?.total ?? 0,
              success: true,
            };
          } catch {
            return { data: [], total: 0, success: false };
          }
        }}
        toolBarRender={() => [
          <Button
            key="create"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => { setDetailRecord(null); setModalOpen(true); }}
          >
            评估就绪度
          </Button>,
          <Button
            key="refresh"
            icon={<ReloadOutlined />}
            onClick={() => {
              tableRef.current?.reload();
              fetchDashboard();
              fetchToday();
            }}
          >
            刷新
          </Button>,
        ]}
      />

      {/* ─── Section 4: 趋势图 ─── */}
      <Card
        title="门店就绪度趋势"
        style={{ marginTop: 24 }}
        extra={
          <Space>
            <Select
              style={{ width: 200 }}
              placeholder="输入门店ID"
              showSearch
              allowClear
              value={trendStoreId || undefined}
              onChange={(v) => setTrendStoreId(v ?? '')}
              options={
                todayItems.length > 0
                  ? todayItems.map((s) => ({ label: s.store_id.slice(0, 8), value: s.store_id }))
                  : []
              }
            />
            <Select
              style={{ width: 100 }}
              value={trendDays}
              onChange={setTrendDays}
              options={[
                { label: '近7天', value: 7 },
                { label: '近14天', value: 14 },
                { label: '近30天', value: 30 },
              ]}
            />
          </Space>
        }
      >
        {trendStoreId ? (
          <Line {...trendConfig} loading={trendLoading} height={320} />
        ) : (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Text type="secondary">请选择门店查看就绪度趋势</Text>
          </div>
        )}
      </Card>

      {/* ─── Section 5: 新建/编辑 ModalForm ─── */}
      <ModalForm<{
        store_id: string;
        score_date: string;
        shift: string;
        shift_coverage: number;
        skill_coverage: number;
        newbie_ratio: number;
        training_completion: number;
      }>
        title={detailRecord ? '更新就绪度评分' : '评估就绪度'}
        open={modalOpen}
        onOpenChange={setModalOpen}
        initialValues={
          detailRecord
            ? {
                store_id: detailRecord.store_id,
                score_date: detailRecord.score_date,
                shift: detailRecord.shift,
                shift_coverage: detailRecord.dimensions.shift_coverage,
                skill_coverage: detailRecord.dimensions.skill_coverage,
                newbie_ratio: detailRecord.dimensions.newbie_ratio,
                training_completion: detailRecord.dimensions.training_completion,
              }
            : {
                score_date: dayjs().format('YYYY-MM-DD'),
                shift: 'full_day',
                shift_coverage: 100,
                skill_coverage: 100,
                newbie_ratio: 0,
                training_completion: 100,
              }
        }
        modalProps={{ destroyOnClose: true }}
        onFinish={async (values) => {
          try {
            const body = {
              store_id: values.store_id,
              score_date: values.score_date,
              shift: values.shift,
              dimensions: {
                shift_coverage: values.shift_coverage,
                skill_coverage: values.skill_coverage,
                newbie_ratio: values.newbie_ratio,
                training_completion: values.training_completion,
              },
            };
            if (detailRecord) {
              await txFetchData(`/api/v1/store-readiness/${detailRecord.id}`, {
                method: 'PUT',
                body: JSON.stringify(body),
              });
              message.success('更新成功');
            } else {
              await txFetchData('/api/v1/store-readiness', {
                method: 'POST',
                body: JSON.stringify(body),
              });
              message.success('评估提交成功');
            }
            tableRef.current?.reload();
            fetchDashboard();
            fetchToday();
            return true;
          } catch {
            message.error('提交失败');
            return false;
          }
        }}
      >
        <ProFormText
          name="store_id"
          label="门店ID"
          rules={[{ required: true, message: '请输入门店ID' }]}
          disabled={!!detailRecord}
        />
        <ProFormDatePicker
          name="score_date"
          label="评分日期"
          rules={[{ required: true, message: '请选择评分日期' }]}
        />
        <ProFormSelect
          name="shift"
          label="班次"
          rules={[{ required: true, message: '请选择班次' }]}
          options={[
            { label: '全天', value: 'full_day' },
            { label: '早班', value: 'morning' },
            { label: '午班', value: 'afternoon' },
            { label: '晚班', value: 'evening' },
          ]}
        />
        <Form.Item name="shift_coverage" label="排班覆盖率" rules={[{ required: true }]}>
          <InputNumber min={0} max={100} addonAfter="%" style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="skill_coverage" label="技能覆盖率" rules={[{ required: true }]}>
          <InputNumber min={0} max={100} addonAfter="%" style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="newbie_ratio" label="新人占比" rules={[{ required: true }]}>
          <InputNumber min={0} max={100} addonAfter="%" style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="training_completion" label="培训完成率" rules={[{ required: true }]}>
          <InputNumber min={0} max={100} addonAfter="%" style={{ width: '100%' }} />
        </Form.Item>
      </ModalForm>

      {/* ─── Section 6: 详情Drawer ─── */}
      <Drawer
        title="就绪度详情"
        width={640}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        destroyOnClose
      >
        {detailRecord && (
          <div>
            {/* 基本信息 */}
            <Descriptions
              column={2}
              bordered
              size="small"
              style={{ marginBottom: 24 }}
            >
              <Descriptions.Item label="门店ID">{detailRecord.store_id}</Descriptions.Item>
              <Descriptions.Item label="评分日期">{detailRecord.score_date}</Descriptions.Item>
              <Descriptions.Item label="班次">{SHIFT_LABELS[detailRecord.shift] ?? detailRecord.shift}</Descriptions.Item>
              <Descriptions.Item label="就绪分">
                <Text strong style={{ color: scoreColor(detailRecord.overall_score), fontSize: 18 }}>
                  {detailRecord.overall_score.toFixed(1)}
                </Text>
              </Descriptions.Item>
              <Descriptions.Item label="风险等级">
                <Badge
                  status={RISK_BADGE_STATUS[detailRecord.risk_level] ?? 'default'}
                  text={RISK_LABEL[detailRecord.risk_level] ?? detailRecord.risk_level}
                />
              </Descriptions.Item>
              <Descriptions.Item label="创建时间">{detailRecord.created_at}</Descriptions.Item>
            </Descriptions>

            {/* 四维度 Progress */}
            <Title level={5} style={{ marginBottom: 16 }}>维度评分</Title>
            <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
              {[
                { label: '排班覆盖率', key: 'shift_coverage' as const },
                { label: '技能覆盖率', key: 'skill_coverage' as const },
                { label: '新人占比', key: 'newbie_ratio' as const },
                { label: '培训完成率', key: 'training_completion' as const },
              ].map((dim) => (
                <Col span={12} key={dim.key}>
                  <Text type="secondary" style={{ fontSize: 12 }}>{dim.label}</Text>
                  <Progress
                    percent={detailRecord.dimensions[dim.key]}
                    strokeColor={scoreColor(detailRecord.dimensions[dim.key])}
                    format={(v) => `${v}%`}
                  />
                </Col>
              ))}
            </Row>

            {/* 缺岗 Table */}
            {detailRecord.risk_positions.length > 0 && (
              <>
                <Title level={5} style={{ marginBottom: 16 }}>缺岗详情</Title>
                <Table
                  dataSource={detailRecord.risk_positions}
                  rowKey={(_, i) => String(i)}
                  size="small"
                  pagination={false}
                  style={{ marginBottom: 24 }}
                  columns={[
                    { title: '岗位', dataIndex: 'position', key: 'position' },
                    { title: '缺口', dataIndex: 'gap', key: 'gap' },
                    { title: '原因', dataIndex: 'reason', key: 'reason' },
                  ]}
                />
              </>
            )}

            {/* 行动项 Timeline */}
            {detailRecord.action_items.length > 0 && (
              <>
                <Title level={5} style={{ marginBottom: 16 }}>行动计划</Title>
                <Timeline
                  items={detailRecord.action_items.map((item, idx) => ({
                    key: idx,
                    color: item.priority === 'high' ? 'red' : item.priority === 'medium' ? 'orange' : 'green',
                    children: (
                      <div>
                        <Text strong>{item.action}</Text>
                        <br />
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          优先级: {item.priority} | 负责人: {item.assigned_to}
                        </Text>
                      </div>
                    ),
                  }))}
                />
              </>
            )}
          </div>
        )}
      </Drawer>
    </div>
  );
}
