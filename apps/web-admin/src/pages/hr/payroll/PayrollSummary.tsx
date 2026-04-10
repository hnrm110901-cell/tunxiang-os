/**
 * PayrollSummary — 月度薪资汇总
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  - 月份选择器+门店选择
 *  - StatisticCard：总应发/总实发/总社保/总个税/平均薪资
 *  - ProTable汇总：按部门/岗位汇总（人数/总额/平均）
 *  - Column柱状图：各月薪资趋势对比
 *
 * API: GET /api/v1/payroll/summary?month=&store_id=
 */

import { useRef, useState } from 'react';
import { Card, Col, Row, Statistic, Typography } from 'antd';
import {
  DollarOutlined,
  SafetyCertificateOutlined,
  AccountBookOutlined,
  UserOutlined,
  BankOutlined,
} from '@ant-design/icons';
import { ProColumns, ProTable } from '@ant-design/pro-components';
import type { ActionType } from '@ant-design/pro-components';
import { Column } from '@ant-design/charts';
import { txFetch } from '../../../api';

const { Title } = Typography;
const TX_PRIMARY = '#FF6B35';

// ─── Types ───────────────────────────────────────────────────────────────────

interface SummaryStats {
  total_gross_fen: number;
  total_net_fen: number;
  total_social_insurance_fen: number;
  total_tax_fen: number;
  avg_salary_fen: number;
}

interface DepartmentSummary {
  id: string;
  department: string;
  role: string;
  headcount: number;
  total_amount_fen: number;
  avg_amount_fen: number;
}

interface MonthlyTrend {
  month: string;
  gross_fen: number;
  net_fen: number;
}

interface SummaryResp {
  stats: SummaryStats;
  departments: { items: DepartmentSummary[]; total: number };
  trends: MonthlyTrend[];
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fenToYuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

// ─── Component ───────────────────────────────────────────────────────────────

export default function PayrollSummary() {
  const actionRef = useRef<ActionType>(null);
  const [stats, setStats] = useState<SummaryStats>({
    total_gross_fen: 0,
    total_net_fen: 0,
    total_social_insurance_fen: 0,
    total_tax_fen: 0,
    avg_salary_fen: 0,
  });
  const [trends, setTrends] = useState<MonthlyTrend[]>([]);

  const columns: ProColumns<DepartmentSummary>[] = [
    { title: '部门', dataIndex: 'department', width: 140 },
    { title: '岗位', dataIndex: 'role', width: 120 },
    { title: '人数', dataIndex: 'headcount', width: 80, hideInSearch: true },
    {
      title: '总金额',
      dataIndex: 'total_amount_fen',
      width: 130,
      hideInSearch: true,
      renderText: (v: number) => fenToYuan(v),
    },
    {
      title: '平均薪资',
      dataIndex: 'avg_amount_fen',
      width: 130,
      hideInSearch: true,
      renderText: (v: number) => fenToYuan(v),
    },
    {
      title: '月份',
      dataIndex: 'month',
      valueType: 'dateMonth',
      hideInTable: true,
    },
    {
      title: '门店',
      dataIndex: 'store_id',
      hideInTable: true,
    },
  ];

  // ─── Chart Data ──────────────────────────────────────────────────────────

  const chartData = trends.flatMap((t) => [
    { month: t.month, type: '应发', value: t.gross_fen / 100 },
    { month: t.month, type: '实发', value: t.net_fen / 100 },
  ]);

  const columnConfig = {
    data: chartData,
    xField: 'month',
    yField: 'value',
    seriesField: 'type',
    isGroup: true,
    color: [TX_PRIMARY, '#1890ff'],
    label: { position: 'top' as const },
    yAxis: { label: { formatter: (v: string) => `${(Number(v) / 10000).toFixed(1)}万` } },
  };

  return (
    <div style={{ padding: 24 }}>
      <Title level={4}>月度薪资汇总</Title>

      {/* ── 统计卡片 ── */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={5}>
          <Card>
            <Statistic
              title="总应发"
              value={stats.total_gross_fen / 100}
              precision={2}
              prefix={<DollarOutlined style={{ color: TX_PRIMARY }} />}
              suffix="元"
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card>
            <Statistic
              title="总实发"
              value={stats.total_net_fen / 100}
              precision={2}
              prefix={<BankOutlined style={{ color: TX_PRIMARY }} />}
              suffix="元"
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card>
            <Statistic
              title="总社保"
              value={stats.total_social_insurance_fen / 100}
              precision={2}
              prefix={<SafetyCertificateOutlined style={{ color: '#1890ff' }} />}
              suffix="元"
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card>
            <Statistic
              title="总个税"
              value={stats.total_tax_fen / 100}
              precision={2}
              prefix={<AccountBookOutlined style={{ color: '#faad14' }} />}
              suffix="元"
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="平均薪资"
              value={stats.avg_salary_fen / 100}
              precision={0}
              prefix={<UserOutlined style={{ color: TX_PRIMARY }} />}
              suffix="元"
            />
          </Card>
        </Col>
      </Row>

      {/* ── 趋势图 ── */}
      <Card title="各月薪资趋势对比" style={{ marginBottom: 24 }}>
        <Column {...columnConfig} height={300} />
      </Card>

      {/* ── 汇总表 ── */}
      <ProTable<DepartmentSummary>
        headerTitle="部门/岗位薪资汇总"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 80 }}
        request={async (params) => {
          const query = new URLSearchParams();
          if (params.month) query.set('month', params.month);
          if (params.store_id) query.set('store_id', params.store_id);
          query.set('page', String(params.current ?? 1));
          query.set('size', String(params.pageSize ?? 20));
          try {
            const res = await txFetch(`/api/v1/payroll/summary?${query}`) as {
              ok: boolean;
              data: SummaryResp;
            };
            if (res.ok && res.data) {
              setStats(res.data.stats);
              setTrends(res.data.trends ?? []);
              return {
                data: res.data.departments?.items ?? [],
                total: res.data.departments?.total ?? 0,
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
