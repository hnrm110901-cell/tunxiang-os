/**
 * AI营销驾驶舱 — AiMarketingDashboardPage
 * 域C: 增长营销 / AI营销自动化
 *
 * 功能区块：
 *   1. 顶部筛选栏（门店ID / 天数 / 刷新 / 一键触发）
 *   2. 健康评分卡（得分 + 等级 + 4维进度条 + AI建议）
 *   3. 四大关键指标卡
 *   4. 渠道分解表
 *   5. 活动效果表
 *   6. AI洞察 Banner
 *   7. 触达日志分页表
 *
 * API:
 *   GET /api/v1/agent/ai-marketing/health-score
 *   GET /api/v1/growth/ai-marketing/performance-summary
 *   GET /api/v1/agent/ai-marketing/touch-log
 *   POST /api/v1/agent/ai-marketing/trigger
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Badge,
  Button,
  Col,
  Divider,
  Form,
  Input,
  message,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tag,
} from 'antd';
import {
  BulbOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { ProTable, StatisticCard } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import { Bar } from '@ant-design/charts';
import { txFetch } from '../../api';

// ─── Design Token（深色驾驶舱主题）───────────────────────────────────────────
const C = {
  primary:   '#FF6B35',
  success:   '#0F6E56',
  warning:   '#BA7517',
  danger:    '#A32D2D',
  info:      '#185FA5',
  cardBg:    '#112228',
  innerBg:   '#0B1A20',
  border:    '#1a2a33',
  text:      '#fff',
  textSub:   '#ccc',
  textMuted: '#999',
};

// ─── 工具函数 ────────────────────────────────────────────────────────────────
const fmtFen  = (fen: number) => `¥${(fen / 100).toFixed(0)}`;
const scoreColor = (s: number) =>
  s >= 80 ? C.success : s >= 60 ? C.warning : C.danger;

const statusColor: Record<string, string> = {
  sent:      'blue',
  delivered: 'green',
  clicked:   'cyan',
  converted: 'gold',
  queued:    'orange',
  failed:    'red',
  pending:   'default',
};

const channelLabel: Record<string, string> = {
  sms:                'SMS',
  wechat_subscribe:   '微信订阅号',
  wechat_oa:          '微信公众号',
  wecom_chat:         '企微',
  meituan:            '美团',
  douyin:             '抖音',
  xiaohongshu_note:   '小红书',
  xiaohongshu:        '小红书',
};

const breakdownLabel: Record<string, string> = {
  channel_coverage:  '渠道覆盖',
  touch_frequency:   '触达频率',
  content_quality:   '内容质量',
  attribution_rate:  '归因率',
};

// ─── TypeScript 接口 ─────────────────────────────────────────────────────────
interface HealthScore {
  total_score: number;
  grade: string;
  breakdown: Record<string, number>;
  suggestions: string[];
}

interface CampaignPerf {
  type: string;
  sent: number;
  attributed_orders: number;
  revenue_fen: number;
}

interface PerformanceSummary {
  total_touches: number;
  unique_members_reached: number;
  total_attributed_revenue_fen: number;
  overall_roi: number;
  channel_breakdown: Record<string, { sent: number; delivered: number; conversion_rate: number }>;
  campaign_performance: CampaignPerf[];
  top_insight: string;
}

interface TouchLog {
  touch_id: string;
  member_id: string;
  channel: string;
  campaign_type: string;
  status: string;
  sent_at: string;
  attribution_revenue_fen: number;
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────
export default function AiMarketingDashboardPage() {
  const [storeId,      setStoreId]      = useState('store-001');
  const [days,         setDays]         = useState(7);
  const [loadingHS,    setLoadingHS]    = useState(false);
  const [loadingPS,    setLoadingPS]    = useState(false);
  const [loadingTouchLog, setLoadingTouchLog] = useState(false);
  const [healthScore,  setHealthScore]  = useState<HealthScore | null>(null);
  const [perfSummary,  setPerfSummary]  = useState<PerformanceSummary | null>(null);
  const [touchLogs,    setTouchLogs]    = useState<TouchLog[]>([]);
  const [touchTotal,   setTouchTotal]   = useState(0);
  const [touchPage,    setTouchPage]    = useState(1);
  const [triggerOpen,  setTriggerOpen]  = useState(false);
  const [triggerLoading, setTriggerLoading] = useState(false);
  const [triggerForm]  = Form.useForm();

  // ── 健康评分 ──
  const fetchHealthScore = useCallback(async () => {
    setLoadingHS(true);
    try {
      const res = await txFetch(
        `/api/v1/agent/ai-marketing/health-score?store_id=${storeId}&channel_count=4&monthly_touches_per_member=3&avg_open_rate=0.25&attributed_order_pct=0.08`
      );
      setHealthScore(res.data ?? null);
    } catch {
      message.error('获取健康评分失败，请检查网络或服务状态');
    } finally {
      setLoadingHS(false);
    }
  }, [storeId]);

  // ── 绩效汇总 ──
  const fetchPerformance = useCallback(async () => {
    setLoadingPS(true);
    try {
      const res = await txFetch(
        `/api/v1/growth/ai-marketing/performance-summary?store_id=${storeId}&days=${days}`
      );
      setPerfSummary(res.data ?? null);
    } catch {
      message.error('获取营销绩效数据失败');
    } finally {
      setLoadingPS(false);
    }
  }, [storeId, days]);

  // ── 触达日志 ──
  const fetchTouchLog = useCallback(async (page = 1) => {
    setLoadingTouchLog(true);
    try {
      const res = await txFetch(
        `/api/v1/agent/ai-marketing/touch-log?store_id=${storeId}&days=${days}&page=${page}&size=20`
      );
      setTouchLogs(res.data?.items ?? []);
      setTouchTotal(res.data?.total ?? 0);
      setTouchPage(page);
    } catch {
      message.error('获取触达日志失败');
    } finally {
      setLoadingTouchLog(false);
    }
  }, [storeId, days]);

  const handleRefresh = useCallback(() => {
    fetchHealthScore();
    fetchPerformance();
    fetchTouchLog(1);
  }, [fetchHealthScore, fetchPerformance, fetchTouchLog]);

  useEffect(() => { handleRefresh(); }, [handleRefresh]);

  // ── 一键触发 ──
  const handleTrigger = async () => {
    try {
      const values = await triggerForm.validateFields();
      setTriggerLoading(true);
      await txFetch('/api/v1/agent/ai-marketing/trigger', {
        method: 'POST',
        body: JSON.stringify({ store_id: storeId, ...values }),
      });
      message.success('触发成功，营销动作已加入队列');
      setTriggerOpen(false);
      triggerForm.resetFields();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return; // 表单校验失败
      message.error('触发失败，请稍后重试');
    } finally {
      setTriggerLoading(false);
    }
  };

  // ── 活动效果表数据（按归因收入降序）──
  const campaignRows = perfSummary
    ? [...perfSummary.campaign_performance].sort(
        (a, b) => b.revenue_fen - a.revenue_fen
      )
    : [];

  // ─── 列定义 ──────────────────────────────────────────────────────────────
  const campaignColumns: ProColumns<CampaignPerf>[] = [
    { title: '活动类型', dataIndex: 'type' },
    { title: '发送数',   dataIndex: 'sent',              align: 'right' },
    { title: '归因订单', dataIndex: 'attributed_orders', align: 'right' },
    {
      title: '归因收入（元）',
      dataIndex: 'revenue_fen',
      align: 'right',
      render: (_, row) => fmtFen(row.revenue_fen),
    },
  ];

  const touchLogColumns: ProColumns<TouchLog>[] = [
    {
      title: '触达ID',
      dataIndex: 'touch_id',
      ellipsis: true,
      width: 140,
    },
    {
      title: '会员ID',
      dataIndex: 'member_id',
      render: (_, row) => `${row.member_id.slice(0, 8)}...`,
      width: 120,
    },
    {
      title: '渠道',
      dataIndex: 'channel',
      render: (_, row) => (
        <Tag color="geekblue">{channelLabel[row.channel] ?? row.channel}</Tag>
      ),
      width: 110,
    },
    { title: '活动类型', dataIndex: 'campaign_type', width: 120 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (_, row) => (
        <Tag color={statusColor[row.status] ?? 'default'}>{row.status}</Tag>
      ),
    },
    {
      title: '发送时间',
      dataIndex: 'sent_at',
      width: 170,
      render: (_, row) => row.sent_at ? new Date(row.sent_at).toLocaleString('zh-CN') : '—',
    },
    {
      title: '归因收入',
      dataIndex: 'attribution_revenue_fen',
      align: 'right',
      width: 100,
      render: (_, row) => row.attribution_revenue_fen > 0 ? fmtFen(row.attribution_revenue_fen) : '—',
    },
  ];

  // ─── 共用卡片样式 ─────────────────────────────────────────────────────────
  const cardStyle: React.CSSProperties = {
    background: C.cardBg,
    border: `1px solid ${C.border}`,
    borderRadius: 8,
  };

  // ─── 健康评分卡 ──────────────────────────────────────────────────────────
  const gradeColor = (g: string) =>
    g === 'A' ? C.success : g === 'B' ? C.info : g === 'C' ? C.warning : C.danger;

  const renderHealthCard = () => (
    <Spin spinning={loadingHS}>
      <div style={{ ...cardStyle, padding: 20, height: '100%' }}>
        <div style={{ color: C.textSub, fontSize: 13, marginBottom: 8 }}>
          AI营销健康评分
        </div>
        {healthScore ? (
          <>
            {/* 大分数 */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
              <span
                style={{
                  fontSize: 52,
                  fontWeight: 700,
                  color: scoreColor(healthScore.total_score),
                  lineHeight: 1,
                }}
              >
                {healthScore.total_score}
              </span>
              <Badge
                count={healthScore.grade}
                style={{
                  backgroundColor: gradeColor(healthScore.grade),
                  fontSize: 16,
                  fontWeight: 700,
                  padding: '0 10px',
                  borderRadius: 4,
                }}
              />
            </div>

            {/* 4维进度条 */}
            <div style={{ marginBottom: 16 }}>
              {Object.entries(healthScore.breakdown).map(([key, val]) => (
                <div key={key} style={{ marginBottom: 10 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span style={{ color: C.textMuted, fontSize: 12 }}>
                      {breakdownLabel[key] ?? key}
                    </span>
                    <span style={{ color: C.textSub, fontSize: 12 }}>{val}</span>
                  </div>
                  <Progress
                    percent={val}
                    showInfo={false}
                    size="small"
                    strokeColor={scoreColor(val)}
                    trailColor={C.border}
                  />
                </div>
              ))}
            </div>

            <Divider style={{ borderColor: C.border, margin: '12px 0' }} />

            {/* AI 建议 */}
            <div style={{ color: C.textMuted, fontSize: 12, marginBottom: 8 }}>AI 建议</div>
            <ul style={{ paddingLeft: 16, margin: 0 }}>
              {healthScore.suggestions.map((s, i) => (
                <li key={i} style={{ color: C.textSub, fontSize: 12, marginBottom: 6 }}>
                  {s}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <div style={{ color: C.textMuted, textAlign: 'center', paddingTop: 40 }}>
            暂无数据
          </div>
        )}
      </div>
    </Spin>
  );

  // ─── 四大指标卡 ──────────────────────────────────────────────────────────
  const renderStatCards = () => (
    <Spin spinning={loadingPS}>
      <StatisticCard.Group>
        <StatisticCard statistic={{ title: '总触达次数', value: perfSummary?.total_touches ?? '-', suffix: '次' }} />
        <StatisticCard statistic={{ title: '触达会员数', value: perfSummary?.unique_members_reached ?? '-', suffix: '人' }} />
        <StatisticCard statistic={{ title: '归因收入', value: perfSummary ? fmtFen(perfSummary.total_attributed_revenue_fen) : '-' }} />
        <StatisticCard statistic={{ title: '营销ROI', value: perfSummary?.overall_roi ?? '-', suffix: 'x', valueStyle: { color: (perfSummary?.overall_roi ?? 0) >= 5 ? C.success : C.warning } }} />
      </StatisticCard.Group>
    </Spin>
  );

  // ─── 渲染 ─────────────────────────────────────────────────────────────────
  return (
    <div
      style={{
        minHeight: '100vh',
        background: C.innerBg,
        padding: 20,
        color: C.text,
      }}
    >
      {/* ── 标题 + 筛选栏 ── */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 16,
          flexWrap: 'wrap',
          gap: 8,
        }}
      >
        <div>
          <h2 style={{ margin: 0, color: C.text, fontSize: 20 }}>
            AI 营销驾驶舱
          </h2>
          <div style={{ color: C.textMuted, fontSize: 12, marginTop: 2 }}>
            渠道触达 · 活动效果 · 健康评分 · 实时日志
          </div>
        </div>

        <Space wrap>
          <Select
            value={storeId}
            onChange={setStoreId}
            style={{ width: 180 }}
            options={[
              { label: '全部门店',    value: 'all'       },
              { label: '总部示例店',  value: 'store-001' },
              { label: '长沙旗舰店',  value: 'store-002' },
              { label: '北京中关村店', value: 'store-003' },
            ]}
            placeholder="选择门店"
          />
          <span style={{ color: C.textSub, fontSize: 13 }}>周期</span>
          <Select
            value={days}
            onChange={setDays}
            style={{ width: 90 }}
            options={[
              { label: '近7天',  value: 7  },
              { label: '近14天', value: 14 },
              { label: '近30天', value: 30 },
            ]}
          />
          <Button
            icon={<ReloadOutlined />}
            onClick={handleRefresh}
            style={{
              background: C.cardBg,
              border: `1px solid ${C.border}`,
              color: C.text,
            }}
          >
            刷新
          </Button>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            style={{ background: C.primary, borderColor: C.primary }}
            onClick={() => setTriggerOpen(true)}
          >
            一键触发
          </Button>
        </Space>
      </div>

      {/* ── 主体：健康评分 + 右侧内容 ── */}
      <Row gutter={[16, 16]}>
        {/* 左：健康评分卡 */}
        <Col xs={24} md={6}>
          {renderHealthCard()}
        </Col>

        {/* 右：四大指标 + 渠道/活动表 + 洞察 */}
        <Col xs={24} md={18}>
          <Space direction="vertical" style={{ width: '100%' }} size={16}>
            {/* 四大指标 */}
            <div style={{ ...cardStyle, padding: 16 }}>
              <div style={{ color: C.textSub, fontSize: 13, marginBottom: 12 }}>
                关键营销指标
              </div>
              {renderStatCards()}
            </div>

            {/* 渠道分解 + 活动效果（并排） */}
            <Row gutter={[16, 16]}>
              <Col xs={24} md={12}>
                <div style={{ ...cardStyle, padding: 16 }}>
                  <div style={{ color: C.textSub, fontSize: 13, marginBottom: 12 }}>
                    渠道分解
                  </div>
                  <Spin spinning={loadingPS}>
                    {perfSummary ? (() => {
                      const channelData = Object.entries(perfSummary.channel_breakdown).map(([channel, v]) => ({
                        channel: channelLabel[channel] || channel,
                        value: v.sent,
                        type: '发送数',
                      })).concat(Object.entries(perfSummary.channel_breakdown).map(([channel, v]) => ({
                        channel: channelLabel[channel] || channel,
                        value: v.delivered,
                        type: '到达数',
                      })));
                      return (
                        <Bar
                          data={channelData}
                          xField="value"
                          yField="channel"
                          seriesField="type"
                          isGroup
                          color={[C.primary, C.info]}
                          legend={{ position: 'top-right' }}
                          xAxis={{ grid: null }}
                          height={Math.max(200, Object.keys(perfSummary.channel_breakdown).length * 50)}
                        />
                      );
                    })() : (
                      <div style={{ color: C.textMuted, textAlign: 'center', padding: '40px 0' }}>
                        暂无渠道数据
                      </div>
                    )}
                  </Spin>
                </div>
              </Col>
              <Col xs={24} md={12}>
                <div style={{ ...cardStyle, padding: 16 }}>
                  <div style={{ color: C.textSub, fontSize: 13, marginBottom: 12 }}>
                    活动效果（按归因收入降序）
                  </div>
                  <Spin spinning={loadingPS}>
                    <Table
                      dataSource={campaignRows}
                      columns={campaignColumns}
                      rowKey="type"
                      size="small"
                      pagination={false}
                      locale={{ emptyText: <span style={{ color: C.textMuted }}>暂无活动数据</span> }}
                      style={{ background: 'transparent' }}
                      className="tx-dark-table"
                    />
                  </Spin>
                </div>
              </Col>
            </Row>

            {/* AI洞察 Banner */}
            {perfSummary?.top_insight && (
              <div
                style={{
                  background: 'linear-gradient(90deg, #3a2500 0%, #2a1800 100%)',
                  border: `1px solid ${C.warning}44`,
                  borderRadius: 8,
                  padding: '12px 20px',
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 12,
                }}
              >
                <BulbOutlined
                  style={{ color: C.warning, fontSize: 18, marginTop: 2 }}
                />
                <div>
                  <div
                    style={{
                      color: C.warning,
                      fontWeight: 600,
                      fontSize: 13,
                      marginBottom: 4,
                    }}
                  >
                    AI 洞察
                  </div>
                  <div style={{ color: C.textSub, fontSize: 13 }}>
                    {perfSummary.top_insight}
                  </div>
                </div>
              </div>
            )}
          </Space>
        </Col>
      </Row>

      {/* ── 触达日志表 ── */}
      <div style={{ ...cardStyle, padding: 16, marginTop: 16 }}>
        <div style={{ color: C.textSub, fontSize: 13, marginBottom: 12 }}>
          触达日志
        </div>
        <ProTable<TouchLog>
          columns={touchLogColumns}
          dataSource={touchLogs}
          rowKey="touch_id"
          loading={loadingTouchLog}
          search={false}
          pagination={{
            current: touchPage,
            pageSize: 20,
            total: touchTotal,
            onChange: (p) => fetchTouchLog(p),
            showSizeChanger: false,
          }}
          toolBarRender={false}
          style={{ background: C.cardBg }}
          scroll={{ x: 900 }}
        />
      </div>

      {/* ── 一键触发 Modal ── */}
      <Modal
        title={<span style={{ color: C.text }}>一键触发营销动作</span>}
        open={triggerOpen}
        onCancel={() => { setTriggerOpen(false); triggerForm.resetFields(); }}
        onOk={handleTrigger}
        confirmLoading={triggerLoading}
        okText="确认触发"
        cancelText="取消"
        styles={{
          content: { background: C.cardBg, border: `1px solid ${C.border}` },
          header: { background: C.cardBg, borderBottom: `1px solid ${C.border}` },
          footer: { background: C.cardBg, borderTop: `1px solid ${C.border}` },
          mask: { backdropFilter: 'blur(2px)' },
        }}
        okButtonProps={{ style: { background: C.primary, borderColor: C.primary } }}
      >
        <Form
          form={triggerForm}
          layout="vertical"
          style={{ marginTop: 16 }}
        >
          <Form.Item
            name="action"
            label={<span style={{ color: C.textSub }}>营销动作</span>}
            rules={[{ required: true, message: '请选择营销动作' }]}
          >
            <Select
              placeholder="选择动作类型"
              options={[
                { label: '下单感谢',  value: 'order_thank_you' },
                { label: '欢迎旅程',  value: 'welcome_journey'  },
                { label: '唤醒旅程',  value: 'reactivation'     },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="member_id"
            label={<span style={{ color: C.textSub }}>会员ID</span>}
            rules={[{ required: true, message: '请输入会员ID' }]}
          >
            <Input
              placeholder="输入目标会员ID"
              style={{
                background: C.innerBg,
                border: `1px solid ${C.border}`,
                color: C.text,
              }}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* ── 深色表格全局样式（局部注入）── */}
      <style>{`
        .tx-dark-table .ant-table {
          background: transparent !important;
          color: ${C.textSub};
        }
        .tx-dark-table .ant-table-thead > tr > th {
          background: ${C.innerBg} !important;
          color: ${C.textMuted} !important;
          border-bottom: 1px solid ${C.border} !important;
          font-size: 12px;
        }
        .tx-dark-table .ant-table-tbody > tr > td {
          background: transparent !important;
          border-bottom: 1px solid ${C.border} !important;
          color: ${C.textSub};
          font-size: 13px;
        }
        .tx-dark-table .ant-table-tbody > tr:hover > td {
          background: ${C.cardBg} !important;
        }
        .tx-dark-table .ant-pagination-item a,
        .tx-dark-table .ant-pagination-prev button,
        .tx-dark-table .ant-pagination-next button {
          color: ${C.textSub} !important;
        }
        .tx-dark-table .ant-pagination-item-active {
          border-color: ${C.primary} !important;
        }
        .tx-dark-table .ant-pagination-item-active a {
          color: ${C.primary} !important;
        }
      `}</style>
    </div>
  );
}
