/**
 * PayrollLaborCost — 人工成本分析 (P0)
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  - 维度切换Tab：按门店/按区域/按品牌/按岗位
 *  - 顶部StatisticCard：总人工成本/平均成本率/人均成本
 *  - 图表区：Line折线图（月度趋势）+ Pie饼图（岗位分布）
 *  - 底部ProTable明细：门店名/人数/总成本/营收/成本率（成本率>35%红色Tag）
 *
 * API: GET /api/v1/payroll/labor-cost/analysis?store_id=&month=
 */

import { useRef, useState } from 'react';
import { Card, Col, Row, Statistic, Tabs, Tag } from 'antd';
import {
  DollarOutlined,
  PercentageOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { ProColumns, ProTable } from '@ant-design/pro-components';
import type { ActionType } from '@ant-design/pro-components';
import { Line, Pie } from '@ant-design/charts';
import dayjs from 'dayjs';
import { txFetch } from '../../../api';

// ─── Design Token ────────────────────────────────────────────────────────────
const TX_PRIMARY = '#FF6B35';
const TX_DANGER = '#A32D2D';

// ─── Types ───────────────────────────────────────────────────────────────────

interface LaborCostSummary {
  total_cost_fen: number;
  avg_cost_rate: number;
  per_capita_cost_fen: number;
  total_headcount: number;
}

interface LaborCostTrend {
  month: string;
  cost_fen: number;
  cost_rate: number;
}

interface RoleDistribution {
  role: string;
  cost_fen: number;
  percentage: number;
}

interface LaborCostDetail {
  id: string;
  store_name: string;
  headcount: number;
  total_cost_fen: number;
  revenue_fen: number;
  cost_rate: number;
}

interface AnalysisResp {
  summary: LaborCostSummary;
  trends: LaborCostTrend[];
  role_distribution: RoleDistribution[];
  details: { items: LaborCostDetail[]; total: number };
}

type Dimension = 'store' | 'region' | 'brand' | 'role';

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fenToYuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;
const fenToWan = (fen: number) => `${(fen / 100 / 10000).toFixed(1)}万`;

// ─── Component ───────────────────────────────────────────────────────────────

export default function PayrollLaborCost() {
  const actionRef = useRef<ActionType>(null);
  const [dimension, setDimension] = useState<Dimension>('store');
  const [summary, setSummary] = useState<LaborCostSummary>({
    total_cost_fen: 0,
    avg_cost_rate: 0,
    per_capita_cost_fen: 0,
    total_headcount: 0,
  });
  const [trends, setTrends] = useState<LaborCostTrend[]>([]);
  const [roleDistribution, setRoleDistribution] = useState<RoleDistribution[]>([]);

  // ─── Columns ─────────────────────────────────────────────────────────────

  const columns: ProColumns<LaborCostDetail>[] = [
    { title: '门店名称', dataIndex: 'store_name', width: 160 },
    { title: '人数', dataIndex: 'headcount', width: 80, hideInSearch: true },
    {
      title: '总人工成本',
      dataIndex: 'total_cost_fen',
      width: 130,
      hideInSearch: true,
      renderText: (v: number) => fenToYuan(v),
    },
    {
      title: '营收',
      dataIndex: 'revenue_fen',
      width: 130,
      hideInSearch: true,
      renderText: (v: number) => fenToYuan(v),
    },
    {
      title: '成本率',
      dataIndex: 'cost_rate',
      width: 100,
      hideInSearch: true,
      render: (_, r) => (
        <Tag color={r.cost_rate > 35 ? 'error' : 'success'}>
          {r.cost_rate.toFixed(1)}%
        </Tag>
      ),
    },
    {
      title: '月份',
      dataIndex: 'month',
      valueType: 'dateMonth',
      hideInTable: true,
    },
  ];

  // ─── Line Chart Config ───────────────────────────────────────────────────

  const lineConfig = {
    data: trends,
    xField: 'month',
    yField: 'cost_fen',
    smooth: true,
    color: TX_PRIMARY,
    yAxis: { label: { formatter: (v: string) => fenToWan(Number(v)) } },
    tooltip: {
      formatter: (datum: LaborCostTrend) => ({
        name: '人工成本',
        value: fenToYuan(datum.cost_fen),
      }),
    },
  };

  // ─── Pie Chart Config ────────────────────────────────────────────────────

  const pieConfig = {
    data: roleDistribution,
    angleField: 'cost_fen',
    colorField: 'role',
    radius: 0.8,
    label: { type: 'outer', content: '{name} {percentage}' },
    interactions: [{ type: 'element-active' }],
  };

  return (
    <div style={{ padding: 24 }}>
      {/* ── 统计卡片 ── */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={8}>
          <Card>
            <Statistic
              title="总人工成本"
              value={summary.total_cost_fen / 100}
              precision={2}
              prefix={<DollarOutlined style={{ color: TX_PRIMARY }} />}
              suffix="元"
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="平均成本率"
              value={summary.avg_cost_rate}
              precision={1}
              prefix={<PercentageOutlined style={{ color: TX_PRIMARY }} />}
              suffix="%"
              valueStyle={summary.avg_cost_rate > 35 ? { color: TX_DANGER } : undefined}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="人均成本"
              value={summary.per_capita_cost_fen / 100}
              precision={0}
              prefix={<TeamOutlined style={{ color: TX_PRIMARY }} />}
              suffix="元"
            />
          </Card>
        </Col>
      </Row>

      {/* ── 维度切换 ── */}
      <Tabs
        activeKey={dimension}
        onChange={(k) => {
          setDimension(k as Dimension);
          actionRef.current?.reload();
        }}
        items={[
          { key: 'store', label: '按门店' },
          { key: 'region', label: '按区域' },
          { key: 'brand', label: '按品牌' },
          { key: 'role', label: '按岗位' },
        ]}
        style={{ marginBottom: 16 }}
      />

      {/* ── 图表区 ── */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={14}>
          <Card title="月度人工成本趋势">
            <Line {...lineConfig} height={280} />
          </Card>
        </Col>
        <Col span={10}>
          <Card title="岗位成本分布">
            <Pie {...pieConfig} height={280} />
          </Card>
        </Col>
      </Row>

      {/* ── 明细表 ── */}
      <ProTable<LaborCostDetail>
        headerTitle="人工成本明细"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 80 }}
        request={async (params) => {
          const query = new URLSearchParams();
          if (params.month) query.set('month', params.month);
          query.set('dimension', dimension);
          query.set('page', String(params.current ?? 1));
          query.set('size', String(params.pageSize ?? 20));
          try {
            const res = await txFetch(`/api/v1/payroll/labor-cost/analysis?${query}`) as { ok: boolean; data: AnalysisResp };
            if (res.ok && res.data) {
              setSummary(res.data.summary);
              setTrends(res.data.trends ?? []);
              setRoleDistribution(res.data.role_distribution ?? []);
              return {
                data: res.data.details?.items ?? [],
                total: res.data.details?.total ?? 0,
                success: true,
              };
            }
          } catch { /* fallback */ }
          return { data: [], total: 0, success: true };
        }}
        pagination={{ defaultPageSize: 20 }}
      />
    </div>
  );
}
