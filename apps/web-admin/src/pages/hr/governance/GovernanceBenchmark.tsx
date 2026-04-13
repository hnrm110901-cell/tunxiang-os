/**
 * GovernanceBenchmark — 区域对标
 * Sprint 6 · 总部治理台
 *
 * API: GET /api/v1/hr/governance/benchmark
 */

import { useEffect, useRef, useState } from 'react';
import { Card, Col, Row, Tag } from 'antd';
import { ActionType, ProColumns, ProTable } from '@ant-design/pro-components';
import { Column } from '@ant-design/charts';
import { txFetchData } from '../../../api';

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface BenchmarkItem {
  store_name: string;
  value: number;
  rank: number;
  diff_from_avg: number;
}

interface BenchmarkResp {
  metric: string;
  average: number;
  items: BenchmarkItem[];
}

// ─── 指标选项 ────────────────────────────────────────────────────────────────

const metricOptions = [
  { label: '出勤率(%)', value: 'attendance_rate' },
  { label: '人均工时(h)', value: 'avg_hours' },
  { label: '人工成本率(%)', value: 'labor_cost_rate' },
  { label: '人效(元/人/月)', value: 'efficiency' },
];

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function GovernanceBenchmark() {
  const actionRef = useRef<ActionType>();
  const [metric, setMetric] = useState<string>('attendance_rate');
  const [benchData, setBenchData] = useState<BenchmarkResp | null>(null);

  const loadData = async (m: string) => {
    const resp = await txFetchData<BenchmarkResp>(
      `/api/v1/hr/governance/benchmark?metric=${m}`,
    );
    setBenchData(resp);
  };

  useEffect(() => {
    loadData(metric);
  }, [metric]);

  const columns: ProColumns<BenchmarkItem>[] = [
    { title: '排名', dataIndex: 'rank', width: 70, sorter: (a, b) => a.rank - b.rank },
    { title: '门店', dataIndex: 'store_name' },
    { title: '指标值', dataIndex: 'value', valueType: 'digit', width: 100 },
    {
      title: '与均值差异',
      dataIndex: 'diff_from_avg',
      width: 120,
      render: (_, r) => {
        const isPositive = r.diff_from_avg > 0;
        // 对成本率指标正值为差，其他指标正值为好
        const isGood = metric === 'labor_cost_rate' ? !isPositive : isPositive;
        return (
          <Tag color={isGood ? 'green' : r.diff_from_avg === 0 ? 'default' : 'red'}>
            {isPositive ? '+' : ''}{r.diff_from_avg.toFixed(1)}
          </Tag>
        );
      },
    },
  ];

  // 图表数据（带均值线）
  const chartData = (benchData?.items ?? []).map((item) => ({
    store_name: item.store_name,
    value: item.value,
  }));

  return (
    <div>
      {/* 指标选择 */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col>
            <strong>对标指标：</strong>
          </Col>
          {metricOptions.map((opt) => (
            <Col key={opt.value}>
              <Tag
                color={metric === opt.value ? '#FF6B35' : 'default'}
                style={{ cursor: 'pointer', padding: '4px 12px' }}
                onClick={() => {
                  setMetric(opt.value);
                  actionRef.current?.reload();
                }}
              >
                {opt.label}
              </Tag>
            </Col>
          ))}
          {benchData && (
            <Col>
              <Tag color="blue">均值: {benchData.average.toFixed(1)}</Tag>
            </Col>
          )}
        </Row>
      </Card>

      <Row gutter={16}>
        {/* 柱状图 */}
        <Col span={14}>
          <Card title="门店间对比">
            <Column
              data={chartData}
              xField="store_name"
              yField="value"
              height={400}
              color="#FF6B35"
              annotations={
                benchData
                  ? [
                      {
                        type: 'line',
                        start: ['min', benchData.average],
                        end: ['max', benchData.average],
                        style: { stroke: '#185FA5', lineWidth: 2, lineDash: [4, 4] },
                        text: { content: `均值 ${benchData.average.toFixed(1)}`, position: 'end', style: { fill: '#185FA5' } },
                      },
                    ]
                  : []
              }
              xAxis={{ label: { autoRotate: true } }}
            />
          </Card>
        </Col>

        {/* 排名表 */}
        <Col span={10}>
          <ProTable<BenchmarkItem>
            headerTitle="门店排名"
            actionRef={actionRef}
            columns={columns}
            dataSource={benchData?.items ?? []}
            rowKey="store_name"
            search={false}
            pagination={{ pageSize: 15 }}
            toolBarRender={false}
          />
        </Col>
      </Row>
    </div>
  );
}
