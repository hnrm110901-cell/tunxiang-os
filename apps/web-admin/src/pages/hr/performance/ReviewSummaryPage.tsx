/**
 * ReviewSummaryPage -- 评审汇总
 * 域F tx-org | v254 review_cycles + review_scores
 *
 * 功能：
 *  - 排名表（员工/平均分/评审人数/排名）
 *  - 分数分布统计卡片
 *  - 校准操作（管理员可调整分数）
 *  - 导出 CSV
 *
 * API:
 *   GET /api/v1/org/performance/review-cycles/:id/summary
 *   GET /api/v1/org/performance/review-cycles/:id/stats
 *   PUT /api/v1/org/performance/review-cycles/:id/calibrate
 */

import { useEffect, useRef, useState } from 'react';
import {
  Button,
  Card,
  Col,
  InputNumber,
  message,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  DownloadOutlined,
  EditOutlined,
  TrophyOutlined,
} from '@ant-design/icons';
import { txFetchData } from '../../../api';
import { getTokenPayload } from '../../../api/client';
import type { ColumnsType } from 'antd/es/table';

const { Title, Text } = Typography;

// ─── Types ───────────────────────────────────────────────────────────────────

interface CycleOption {
  id: string;
  cycle_name: string;
  status: string;
}

interface RankingItem {
  rank: number;
  employee_id: string;
  employee_name: string;
  store_id: string | null;
  avg_score: number;
  reviewer_count: number;
}

interface ReviewStats {
  cycle_id: string;
  scored_employee_count: number;
  total_score_records: number;
  draft_count: number;
  avg_score: number;
  min_score: number;
  max_score: number;
  distribution: Record<string, number>;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function rankColor(rank: number): string {
  if (rank === 1) return '#faad14';
  if (rank === 2) return '#bfbfbf';
  if (rank === 3) return '#d48806';
  return '';
}

function scoreTag(score: number) {
  if (score >= 90) return <Tag color="success">优秀</Tag>;
  if (score >= 80) return <Tag color="processing">良好</Tag>;
  if (score >= 70) return <Tag color="default">达标</Tag>;
  if (score >= 60) return <Tag color="warning">待改进</Tag>;
  return <Tag color="error">不合格</Tag>;
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function ReviewSummaryPage() {
  const [messageApi, contextHolder] = message.useMessage();
  const [cycles, setCycles] = useState<CycleOption[]>([]);
  const [selectedCycleId, setSelectedCycleId] = useState<string | null>(null);
  const [rankings, setRankings] = useState<RankingItem[]>([]);
  const [stats, setStats] = useState<ReviewStats | null>(null);
  const [loading, setLoading] = useState(false);

  // Calibrate modal
  const [calibrateVisible, setCalibrateVisible] = useState(false);
  const [calibrateEmployee, setCalibrateEmployee] = useState<RankingItem | null>(null);
  const [calibrateScore, setCalibrateScore] = useState<number>(0);
  const [calibrating, setCalibrating] = useState(false);

  const user = getTokenPayload();

  // Fetch cycles
  useEffect(() => {
    (async () => {
      try {
        const res = (await txFetchData(
          '/api/v1/org/performance/review-cycles?size=50'
        )) as { items: CycleOption[] };
        setCycles(res.items || []);
        const params = new URLSearchParams(window.location.hash.split('?')[1] || '');
        const cycleIdParam = params.get('cycle_id');
        if (cycleIdParam && res.items.some((c) => c.id === cycleIdParam)) {
          setSelectedCycleId(cycleIdParam);
        }
      } catch {
        // silent
      }
    })();
  }, []);

  // Fetch summary + stats
  useEffect(() => {
    if (!selectedCycleId) return;
    setLoading(true);
    (async () => {
      try {
        const [summaryRes, statsRes] = await Promise.all([
          txFetchData(`/api/v1/org/performance/review-cycles/${selectedCycleId}/summary`) as Promise<{
            items: RankingItem[];
          }>,
          txFetchData(`/api/v1/org/performance/review-cycles/${selectedCycleId}/stats`) as Promise<ReviewStats>,
        ]);
        setRankings(summaryRes.items || []);
        setStats(statsRes);
      } catch {
        setRankings([]);
        setStats(null);
      } finally {
        setLoading(false);
      }
    })();
  }, [selectedCycleId]);

  const handleCalibrate = async () => {
    if (!calibrateEmployee || !selectedCycleId) return;
    setCalibrating(true);
    try {
      await txFetchData(`/api/v1/org/performance/review-cycles/${selectedCycleId}/calibrate`, {
        method: 'PUT',
        body: JSON.stringify({
          employee_id: calibrateEmployee.employee_id,
          calibrated_score: calibrateScore,
          calibrator_id: user?.user_id || '',
        }),
      });
      messageApi.success(`已校准 ${calibrateEmployee.employee_name} 的分数为 ${calibrateScore}`);
      setCalibrateVisible(false);
      // Refresh
      const summaryRes = (await txFetchData(
        `/api/v1/org/performance/review-cycles/${selectedCycleId}/summary`
      )) as { items: RankingItem[] };
      setRankings(summaryRes.items || []);
    } catch {
      messageApi.error('校准失败');
    } finally {
      setCalibrating(false);
    }
  };

  const handleExportCSV = () => {
    if (!rankings.length) return;
    const header = '排名,员工,平均分,评审人数';
    const rows = rankings.map((r) => `${r.rank},${r.employee_name},${r.avg_score},${r.reviewer_count}`);
    const csv = [header, ...rows].join('\n');
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `review_summary_${selectedCycleId}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    messageApi.success('导出成功');
  };

  const columns: ColumnsType<RankingItem> = [
    {
      title: '排名',
      dataIndex: 'rank',
      width: 80,
      render: (rank: number) => (
        <Space>
          {rank <= 3 && <TrophyOutlined style={{ color: rankColor(rank) }} />}
          <Text strong>{rank}</Text>
        </Space>
      ),
    },
    { title: '员工', dataIndex: 'employee_name', width: 120 },
    {
      title: '平均分',
      dataIndex: 'avg_score',
      width: 120,
      sorter: (a, b) => a.avg_score - b.avg_score,
      render: (score: number) => (
        <Space>
          <Text strong>{score.toFixed(2)}</Text>
          {scoreTag(score)}
        </Space>
      ),
    },
    { title: '评审人数', dataIndex: 'reviewer_count', width: 100 },
    {
      title: '操作',
      width: 100,
      render: (_, record) => (
        <Button
          type="link"
          size="small"
          icon={<EditOutlined />}
          onClick={() => {
            setCalibrateEmployee(record);
            setCalibrateScore(record.avg_score);
            setCalibrateVisible(true);
          }}
        >
          校准
        </Button>
      ),
    },
  ];

  const distBuckets = ['90-100', '80-89', '70-79', '60-69', '0-59'];

  return (
    <div style={{ padding: 24 }}>
      {contextHolder}
      <Title level={4}>评审汇总</Title>

      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col>
            <Text strong>选择评审周期：</Text>
          </Col>
          <Col flex="auto">
            <Select
              style={{ width: 360 }}
              placeholder="请选择评审周期"
              value={selectedCycleId}
              onChange={setSelectedCycleId}
              options={cycles.map((c) => ({
                label: c.cycle_name,
                value: c.id,
              }))}
            />
          </Col>
          <Col>
            <Button icon={<DownloadOutlined />} onClick={handleExportCSV} disabled={!rankings.length}>
              导出CSV
            </Button>
          </Col>
        </Row>
      </Card>

      {/* 统计卡片 */}
      {stats && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={4}>
            <Card>
              <Statistic title="已评人数" value={stats.scored_employee_count} />
            </Card>
          </Col>
          <Col span={4}>
            <Card>
              <Statistic title="评分记录" value={stats.total_score_records} />
            </Card>
          </Col>
          <Col span={4}>
            <Card>
              <Statistic title="平均分" value={stats.avg_score} precision={2} />
            </Card>
          </Col>
          <Col span={4}>
            <Card>
              <Statistic title="最高分" value={stats.max_score} precision={2} />
            </Card>
          </Col>
          <Col span={4}>
            <Card>
              <Statistic title="最低分" value={stats.min_score} precision={2} />
            </Card>
          </Col>
          <Col span={4}>
            <Card>
              <Statistic title="待提交" value={stats.draft_count} />
            </Card>
          </Col>
        </Row>
      )}

      {/* 分数分布 */}
      {stats && stats.distribution && (
        <Card title="分数分布" style={{ marginBottom: 16 }}>
          <Row gutter={16}>
            {distBuckets.map((bucket) => (
              <Col key={bucket} span={4}>
                <Statistic
                  title={`${bucket}分`}
                  value={stats.distribution[bucket] || 0}
                  suffix="人"
                />
              </Col>
            ))}
          </Row>
        </Card>
      )}

      {/* 排名表 */}
      <Card title="员工排名">
        <Table<RankingItem>
          loading={loading}
          dataSource={rankings}
          columns={columns}
          rowKey="employee_id"
          pagination={{ pageSize: 20 }}
        />
      </Card>

      {/* 校准弹窗 */}
      <Modal
        title={`校准分数 - ${calibrateEmployee?.employee_name || ''}`}
        open={calibrateVisible}
        onCancel={() => setCalibrateVisible(false)}
        onOk={handleCalibrate}
        confirmLoading={calibrating}
        okText="确认校准"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Text>
            当前平均分：<Text strong>{calibrateEmployee?.avg_score.toFixed(2)}</Text>
          </Text>
          <Text>校准分数：</Text>
          <InputNumber
            min={0}
            max={100}
            precision={2}
            value={calibrateScore}
            onChange={(v) => setCalibrateScore(v ?? 0)}
            style={{ width: '100%' }}
          />
        </Space>
      </Modal>
    </div>
  );
}
