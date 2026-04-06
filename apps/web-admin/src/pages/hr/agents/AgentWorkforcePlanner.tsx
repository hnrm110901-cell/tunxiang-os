/**
 * AgentWorkforcePlanner — 排班优化 Agent
 * 域H · Agent 中枢
 *
 * 功能：
 *  1. 下周排班优化建议列表（减班/加班/调整+预计节省成本）
 *  2. 一键采纳
 *  3. 效率对比：优化前 vs 优化后的工时/成本
 *
 * API:
 *  POST /api/v1/agent/workforce_planner/suggest_optimization
 *  POST /api/v1/agent/workforce_planner/analyze_schedule_efficiency
 */

import { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  CalendarOutlined,
  CheckOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { txFetch } from '../../../api';

const { Title, Text } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface Suggestion {
  slot: string;
  slot_label: string;
  action: 'reduce' | 'increase';
  current: number;
  suggested: number;
  delta: number;
  reason: string;
  estimated_saving_fen: number;
}

interface OptimizationResp {
  suggestions: Suggestion[];
  summary: {
    total_suggestions: number;
    estimated_net_saving_fen: number;
    optimization_rate: number;
  };
  efficiency_before: Record<string, number>;
  efficiency_after: Record<string, number>;
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function AgentWorkforcePlanner() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<OptimizationResp | null>(null);
  const [adoptedSlots, setAdoptedSlots] = useState<Set<string>>(new Set());

  const load = async () => {
    setLoading(true);
    try {
      const resp = await txFetch<{ data: OptimizationResp }>(
        '/api/v1/agent/workforce_planner/suggest_optimization',
        {
          method: 'POST',
          body: JSON.stringify({ store_id: '' }),
        },
      );
      setData(resp.data || resp as unknown as OptimizationResp);
    } catch {
      message.error('获取排班优化建议失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const fmtYuan = (fen: number) => {
    const yuan = Math.abs(fen) / 100;
    return fen >= 0 ? `${yuan.toFixed(0)}` : `-${yuan.toFixed(0)}`;
  };

  const handleAdopt = async (slot: string) => {
    try {
      // TODO: 接入真实采纳API（写入unified_schedules）
      message.success('已采纳该建议');
      setAdoptedSlots((prev) => new Set(prev).add(slot));
    } catch {
      message.error('采纳失败');
    }
  };

  const suggestions = data?.suggestions || [];
  const summary = data?.summary;
  const effBefore = data?.efficiency_before || {};
  const effAfter = data?.efficiency_after || {};

  const columns = [
    {
      title: '时段',
      dataIndex: 'slot_label',
      width: 100,
      render: (label: string) => (
        <div>
          <Tag color="blue" style={{ marginRight: 4 }}>AI建议</Tag>
          {label}
        </div>
      ),
    },
    {
      title: '操作类型',
      dataIndex: 'action',
      width: 90,
      render: (action: string) =>
        action === 'reduce' ? (
          <Tag color="green" icon={<ArrowDownOutlined />}>减班</Tag>
        ) : (
          <Tag color="orange" icon={<ArrowUpOutlined />}>加班</Tag>
        ),
    },
    {
      title: '当前人数',
      dataIndex: 'current',
      width: 90,
      align: 'center' as const,
    },
    {
      title: '建议人数',
      dataIndex: 'suggested',
      width: 90,
      align: 'center' as const,
      render: (val: number) => <Text strong>{val}</Text>,
    },
    {
      title: '变化',
      dataIndex: 'delta',
      width: 80,
      align: 'center' as const,
      render: (delta: number) => (
        <Text style={{ color: delta > 0 ? '#0F6E56' : delta < 0 ? '#A32D2D' : undefined }}>
          {delta > 0 ? '+' : ''}{delta}
        </Text>
      ),
    },
    {
      title: '原因',
      dataIndex: 'reason',
      ellipsis: true,
    },
    {
      title: '预计节省',
      dataIndex: 'estimated_saving_fen',
      width: 110,
      render: (fen: number) => {
        const color = fen > 0 ? '#0F6E56' : fen < 0 ? '#A32D2D' : undefined;
        return <Text style={{ color }}>{fmtYuan(fen)}元/天</Text>;
      },
    },
    {
      title: '操作',
      width: 100,
      render: (_: unknown, r: Suggestion) =>
        adoptedSlots.has(r.slot) ? (
          <Tag color="green">已采纳</Tag>
        ) : (
          <Button
            type="link"
            size="small"
            icon={<CheckOutlined />}
            onClick={() => handleAdopt(r.slot)}
          >
            采纳
          </Button>
        ),
    },
  ];

  // 效率对比数据
  const slotLabels: Record<string, string> = {
    morning: '早班',
    lunch_peak: '午高峰',
    afternoon: '下午班',
    dinner_peak: '晚高峰',
    night: '夜班',
  };

  const efficiencyData = Object.keys(effBefore).map((slot) => ({
    slot,
    label: slotLabels[slot] || slot,
    before: Math.round(effBefore[slot] || 0),
    after: Math.round(effAfter[slot] || 0),
    improvement: Math.round((effAfter[slot] || 0) - (effBefore[slot] || 0)),
  }));

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          <CalendarOutlined style={{ marginRight: 8, color: '#185FA5' }} />
          排班优化 Agent
        </Title>
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
          重新分析
        </Button>
      </div>

      {/* 汇总统计 */}
      {summary && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={8}>
            <Card>
              <Statistic
                title="优化建议"
                value={summary.total_suggestions}
                suffix="条"
                prefix={<ThunderboltOutlined />}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card>
              <Statistic
                title="预计日净节省"
                value={Math.abs(summary.estimated_net_saving_fen) / 100}
                suffix="元"
                valueStyle={{
                  color: summary.estimated_net_saving_fen >= 0 ? '#0F6E56' : '#A32D2D',
                }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card>
              <Statistic
                title="优化覆盖率"
                value={(summary.optimization_rate * 100).toFixed(0)}
                suffix="%"
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* 建议列表 */}
      <Card title="排班优化建议" style={{ marginBottom: 16 }}>
        <Table
          dataSource={suggestions}
          columns={columns}
          rowKey="slot"
          loading={loading}
          pagination={false}
          size="middle"
        />
      </Card>

      {/* 效率对比 */}
      {efficiencyData.length > 0 && (
        <Card title="时段人效对比（优化前 vs 优化后）">
          <Table
            dataSource={efficiencyData}
            columns={[
              { title: '时段', dataIndex: 'label', width: 100 },
              {
                title: '优化前（分/人）',
                dataIndex: 'before',
                width: 130,
                render: (v: number) => `${(v / 100).toFixed(0)}元`,
              },
              {
                title: '优化后（分/人）',
                dataIndex: 'after',
                width: 130,
                render: (v: number) => <Text strong>{(v / 100).toFixed(0)}元</Text>,
              },
              {
                title: '变化',
                dataIndex: 'improvement',
                width: 100,
                render: (v: number) => (
                  <Text style={{ color: v > 0 ? '#0F6E56' : v < 0 ? '#A32D2D' : undefined }}>
                    {v > 0 ? '+' : ''}{(v / 100).toFixed(0)}元
                  </Text>
                ),
              },
            ]}
            rowKey="slot"
            pagination={false}
            size="small"
          />
        </Card>
      )}
    </div>
  );
}
