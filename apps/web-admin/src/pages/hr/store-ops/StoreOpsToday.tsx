/**
 * StoreOpsToday — 今日人力作战台 (P0核心)
 * 域F · 组织人事 · 门店作战台
 *
 * 功能：
 *  1. 顶部门店选择器 + 日期（默认今天）
 *  2. 四个StatisticCard：应到/实到/缺岗/异常
 *  3. 岗位在岗矩阵（每个岗位一张卡，显示required/actual/gap）
 *  4. 缺岗列表（Table，岗位/时段/紧急程度/状态，操作：补位/指派）
 *  5. 待处理事项区（Tabs：待审假/待处理调班/异常考勤）
 *  6. 今日时间线（Timeline组件，打卡/迟到/请假等事件）
 *  7. 人工成本卡片（今日预估+月累计+成本率）
 *
 * API:
 *  GET /api/v1/store-ops/today?store_id=xxx&date=xxx
 */

import { useEffect, useRef, useState } from 'react';
import { formatPrice } from '@tx-ds/utils';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  DatePicker,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd';
import {
  ReloadOutlined,
  WarningOutlined,
  TeamOutlined,
  ClockCircleOutlined,
  DollarOutlined,
} from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns, ActionType } from '@ant-design/pro-components';
import dayjs, { Dayjs } from 'dayjs';
import { txFetchData } from '../../../api';

const { Title, Text } = Typography;

// ─── Design Token ────────────────────────────────────────────────────────────
const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_WARNING = '#BA7517';
const TX_DANGER  = '#A32D2D';

// ─── Types ───────────────────────────────────────────────────────────────────

interface StoreOption {
  store_id: string;
  store_name: string;
}

interface TodayOverview {
  expected: number;
  actual: number;
  gap: number;
  anomaly: number;
  position_matrix: PositionSlot[];
  gaps: GapItem[];
  pending_leaves: PendingItem[];
  pending_swaps: PendingItem[];
  anomaly_records: PendingItem[];
  timeline_events: TimelineEvent[];
  cost: CostInfo;
}

interface PositionSlot {
  position: string;
  position_label: string;
  required: number;
  actual: number;
  gap: number;
}

interface GapItem {
  id: string;
  position: string;
  position_label: string;
  time_slot: string;
  urgency: 'high' | 'medium' | 'low';
  status: 'open' | 'filling' | 'filled';
}

interface PendingItem {
  id: string;
  employee_name: string;
  type: string;
  detail: string;
  created_at: string;
}

interface TimelineEvent {
  time: string;
  content: string;
  type: 'clock_in' | 'clock_out' | 'late' | 'leave' | 'anomaly';
}

interface CostInfo {
  today_estimate_fen: number;
  month_total_fen: number;
  cost_rate: number;
}

// ─── 枚举 ────────────────────────────────────────────────────────────────────

const URGENCY_MAP: Record<string, { label: string; color: string }> = {
  high:   { label: '紧急', color: 'red' },
  medium: { label: '一般', color: 'orange' },
  low:    { label: '低',   color: 'blue' },
};

const GAP_STATUS_MAP: Record<string, { label: string; color: string }> = {
  open:    { label: '待补位', color: 'red' },
  filling: { label: '补位中', color: 'orange' },
  filled:  { label: '已补位', color: 'green' },
};

const EVENT_COLOR: Record<string, string> = {
  clock_in: 'green',
  clock_out: 'gray',
  late: 'orange',
  leave: 'blue',
  anomaly: 'red',
};

// ─── 岗位矩阵子组件 ─────────────────────────────────────────────────────────

function PositionMatrix({ slots }: { slots: PositionSlot[] }) {
  return (
    <Card title="岗位在岗矩阵" style={{ marginBottom: 16 }}>
      <Row gutter={[16, 16]}>
        {slots.map((s) => (
          <Col xs={12} sm={8} md={6} key={s.position}>
            <Card
              size="small"
              style={{
                borderLeft: s.gap > 0 ? `3px solid ${TX_DANGER}` : `3px solid ${TX_SUCCESS}`,
              }}
            >
              <Text strong>{s.position_label}</Text>
              <div style={{ marginTop: 8 }}>
                <Text type="secondary">需求：</Text><Text>{s.required}</Text>
                <br />
                <Text type="secondary">实到：</Text><Text>{s.actual}</Text>
                <br />
                <Text type="secondary">缺口：</Text>
                <Text style={{ color: s.gap > 0 ? TX_DANGER : TX_SUCCESS, fontWeight: 600 }}>
                  {s.gap}
                </Text>
              </div>
            </Card>
          </Col>
        ))}
      </Row>
    </Card>
  );
}

// ─── 缺岗列表子组件 ─────────────────────────────────────────────────────────

function GapTable({
  gaps,
  loading,
  onFill,
  onAssign,
}: {
  gaps: GapItem[];
  loading: boolean;
  onFill: (id: string) => void;
  onAssign: (id: string) => void;
}) {
  const columns: ProColumns<GapItem>[] = [
    { title: '岗位', dataIndex: 'position_label', width: 100 },
    { title: '时段', dataIndex: 'time_slot', width: 120 },
    {
      title: '紧急程度',
      dataIndex: 'urgency',
      width: 90,
      render: (_, r) => {
        const u = URGENCY_MAP[r.urgency];
        return <Tag color={u?.color}>{u?.label}</Tag>;
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (_, r) => {
        const s = GAP_STATUS_MAP[r.status];
        return <Tag color={s?.color}>{s?.label}</Tag>;
      },
    },
    {
      title: '操作',
      width: 160,
      render: (_, r) =>
        r.status === 'open' ? (
          <Space>
            <Button type="link" size="small" onClick={() => onFill(r.id)}>
              补位
            </Button>
            <Button type="link" size="small" onClick={() => onAssign(r.id)}>
              指派
            </Button>
          </Space>
        ) : (
          <Text type="secondary">-</Text>
        ),
    },
  ];

  return (
    <Card title="缺岗列表" style={{ marginBottom: 16 }}>
      <ProTable<GapItem>
        columns={columns}
        dataSource={gaps}
        loading={loading}
        rowKey="id"
        search={false}
        options={false}
        pagination={false}
        size="small"
      />
    </Card>
  );
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export default function StoreOpsToday() {
  const [storeId, setStoreId] = useState<string>('');
  const [date, setDate] = useState<Dayjs>(dayjs());
  const [stores, setStores] = useState<StoreOption[]>([]);
  const [data, setData] = useState<TodayOverview | null>(null);
  const [loading, setLoading] = useState(false);

  // 加载门店列表
  useEffect(() => {
    (async () => {
      try {
        const res = await txFetchData<StoreOption[]>('/api/v1/org/stores');
        const list = res.data ?? [];
        setStores(list);
        if (list.length > 0) setStoreId(list[0].store_id);
      } catch (err) {
        message.error('加载门店列表失败');
      }
    })();
  }, []);

  // 加载作战台数据
  const load = async () => {
    if (!storeId) return;
    setLoading(true);
    try {
      const res = await txFetchData<TodayOverview>(
        `/api/v1/store-ops/today?store_id=${storeId}&date=${date.format('YYYY-MM-DD')}`,
      );
      setData(res.data);
    } catch (err) {
      message.error('加载作战台数据失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [storeId, date]);

  /** @deprecated Use formatPrice from @tx-ds/utils */
  const fenToYuan = (fen: number) => `¥${(fen / 100).toFixed(0)}`;

  return (
    <div style={{ padding: 24 }}>
      {/* 顶部筛选 */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <TeamOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
            今日人力作战台
          </Title>
        </Col>
        <Col>
          <Space>
            <Select
              value={storeId}
              onChange={setStoreId}
              style={{ width: 200 }}
              placeholder="选择门店"
              options={stores.map((s) => ({ label: s.store_name, value: s.store_id }))}
            />
            <DatePicker value={date} onChange={(d) => d && setDate(d)} allowClear={false} />
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
              刷新
            </Button>
          </Space>
        </Col>
      </Row>

      {/* 四个统计卡 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic title="应到" value={data?.expected ?? '-'} valueStyle={{ color: TX_PRIMARY }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="实到" value={data?.actual ?? '-'} valueStyle={{ color: TX_SUCCESS }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="缺岗"
              value={data?.gap ?? '-'}
              valueStyle={{ color: (data?.gap ?? 0) > 0 ? TX_DANGER : TX_SUCCESS }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="异常"
              value={data?.anomaly ?? '-'}
              prefix={<WarningOutlined />}
              valueStyle={{ color: (data?.anomaly ?? 0) > 0 ? TX_WARNING : TX_SUCCESS }}
            />
          </Card>
        </Col>
      </Row>

      {/* 岗位矩阵 */}
      <PositionMatrix slots={data?.position_matrix ?? []} />

      {/* 缺岗列表 */}
      <GapTable
        gaps={data?.gaps ?? []}
        loading={loading}
        onFill={(id) => {
          message.info(`跳转补位台，缺岗ID：${id}`);
          // TODO: navigate to StoreOpsFillGaps with gap_id
        }}
        onAssign={(id) => {
          message.info(`指派缺岗：${id}`);
        }}
      />

      <Row gutter={16}>
        {/* 待处理事项 */}
        <Col span={14}>
          <Card title="待处理事项" style={{ marginBottom: 16 }}>
            <Tabs
              items={[
                {
                  key: 'leave',
                  label: (
                    <Badge count={data?.pending_leaves?.length ?? 0} size="small" offset={[8, -2]}>
                      待审假
                    </Badge>
                  ),
                  children: (
                    <Table
                      dataSource={data?.pending_leaves ?? []}
                      rowKey="id"
                      size="small"
                      pagination={false}
                      columns={[
                        { title: '员工', dataIndex: 'employee_name', width: 80 },
                        { title: '类型', dataIndex: 'type', width: 80 },
                        { title: '详情', dataIndex: 'detail' },
                        {
                          title: '操作',
                          width: 80,
                          render: () => (
                            <Button type="link" size="small">
                              审批
                            </Button>
                          ),
                        },
                      ]}
                    />
                  ),
                },
                {
                  key: 'swap',
                  label: (
                    <Badge count={data?.pending_swaps?.length ?? 0} size="small" offset={[8, -2]}>
                      待处理调班
                    </Badge>
                  ),
                  children: (
                    <Table
                      dataSource={data?.pending_swaps ?? []}
                      rowKey="id"
                      size="small"
                      pagination={false}
                      columns={[
                        { title: '员工', dataIndex: 'employee_name', width: 80 },
                        { title: '详情', dataIndex: 'detail' },
                        {
                          title: '操作',
                          width: 80,
                          render: () => (
                            <Button type="link" size="small">
                              处理
                            </Button>
                          ),
                        },
                      ]}
                    />
                  ),
                },
                {
                  key: 'anomaly',
                  label: (
                    <Badge count={data?.anomaly_records?.length ?? 0} size="small" offset={[8, -2]}>
                      异常考勤
                    </Badge>
                  ),
                  children: (
                    <Table
                      dataSource={data?.anomaly_records ?? []}
                      rowKey="id"
                      size="small"
                      pagination={false}
                      columns={[
                        { title: '员工', dataIndex: 'employee_name', width: 80 },
                        { title: '类型', dataIndex: 'type', width: 80 },
                        { title: '详情', dataIndex: 'detail' },
                        {
                          title: '操作',
                          width: 80,
                          render: () => (
                            <Button type="link" size="small">
                              处理
                            </Button>
                          ),
                        },
                      ]}
                    />
                  ),
                },
              ]}
            />
          </Card>
        </Col>

        {/* 今日时间线 + 成本 */}
        <Col span={10}>
          <Card
            title={
              <span>
                <ClockCircleOutlined style={{ marginRight: 8 }} />
                今日时间线
              </span>
            }
            style={{ marginBottom: 16 }}
          >
            <div style={{ maxHeight: 300, overflow: 'auto' }}>
              <Timeline
                items={(data?.timeline_events ?? []).map((e) => ({
                  color: EVENT_COLOR[e.type] ?? 'gray',
                  children: (
                    <span>
                      <Text type="secondary" style={{ marginRight: 8 }}>
                        {e.time}
                      </Text>
                      {e.content}
                    </span>
                  ),
                }))}
              />
              {(!data?.timeline_events || data.timeline_events.length === 0) && (
                <Text type="secondary">暂无事件</Text>
              )}
            </div>
          </Card>

          <Card
            title={
              <span>
                <DollarOutlined style={{ marginRight: 8 }} />
                人工成本
              </span>
            }
          >
            <Row gutter={16}>
              <Col span={8}>
                <Statistic
                  title="今日预估"
                  value={data ? fenToYuan(data.cost.today_estimate_fen) : '-'}
                  valueStyle={{ fontSize: 18 }}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="月累计"
                  value={data ? fenToYuan(data.cost.month_total_fen) : '-'}
                  valueStyle={{ fontSize: 18 }}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="成本率"
                  value={data ? `${(data.cost.cost_rate * 100).toFixed(1)}%` : '-'}
                  valueStyle={{
                    fontSize: 18,
                    color: data && data.cost.cost_rate > 0.3 ? TX_DANGER : TX_SUCCESS,
                  }}
                />
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
