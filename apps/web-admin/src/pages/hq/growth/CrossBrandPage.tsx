/**
 * CrossBrandPage — 跨品牌增长中心
 * 路由: /hq/growth/cross-brand
 * V2.3: 跨品牌增长机会发现 + 实验自动迭代监控
 */
import { useState, useCallback } from 'react';
import {
  Card, Table, Tag, Space, Row, Col, Statistic, Drawer, Spin,
  Button, Alert, Descriptions, Timeline, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useApi } from '../../../hooks/useApi';
import type {
  CrossBrandOpportunity,
  CrossBrandProfile,
  ExperimentAdjustment,
} from '../../../api/growthHubApi';
import {
  fetchCrossBrandOpportunities,
  fetchCrossBrandProfile,
  fetchCrossBrandFrequency,
  triggerAutoIterate,
  fetchExperimentAdjustments,
} from '../../../api/growthHubApi';

// ---- 颜色常量（深色主题）----
const PAGE_BG = '#0d1e28';
const CARD_BG = '#142833';
const BORDER = '#1e3a4a';
const TEXT_PRIMARY = '#e8e8e8';
const TEXT_SECONDARY = '#8899a6';
const BRAND_ORANGE = '#FF6B35';
const SUCCESS_GREEN = '#52c41a';
const WARNING_ORANGE = '#faad14';
const DANGER_RED = '#ff4d4f';
const INFO_BLUE = '#1890ff';

// ---- Stage/Priority 颜色映射 ----
const STAGE_COLOR: Record<string, string> = {
  new: INFO_BLUE,
  exploring: WARNING_ORANGE,
  stable: SUCCESS_GREEN,
  declining: DANGER_RED,
  dormant: TEXT_SECONDARY,
};

const PRIORITY_COLOR: Record<string, string> = {
  high: DANGER_RED,
  medium: WARNING_ORANGE,
  low: SUCCESS_GREEN,
  none: TEXT_SECONDARY,
};

export function CrossBrandPage() {
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedCustomerId, setSelectedCustomerId] = useState<string | null>(null);
  const [customerProfile, setCustomerProfile] = useState<CrossBrandProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [frequencyInfo, setFrequencyInfo] = useState<{ can_touch: boolean; today_count: number; week_count: number } | null>(null);
  const [iterating, setIterating] = useState(false);

  // 跨品牌机会列表
  const { data: oppData, loading: oppLoading } = useApi<{ items: CrossBrandOpportunity[]; total: number }>(
    `/api/v1/growth/cross-brand/opportunities?page=${page}&size=${pageSize}`,
    { cacheMs: 10_000 },
  );

  // 实验调整建议
  const { data: adjustData, loading: adjustLoading, refresh: refreshAdjust } = useApi<{ adjustments: ExperimentAdjustment[] }>(
    '/api/v1/growth/experiments/adjustments',
    { cacheMs: 30_000 },
  );

  const opportunities = oppData?.items || [];
  const total = oppData?.total || 0;
  const adjustments = adjustData?.adjustments || [];

  // 统计
  const crossBrandCount = opportunities.filter(o => o.brand_count >= 2).length;
  const opportunityCount = opportunities.filter(o => o.opportunity !== null).length;
  const weekTouchCount = opportunities.reduce((sum, _) => sum, 0); // placeholder

  // 打开客户详情Drawer
  const openDrawer = useCallback(async (customerId: string) => {
    setSelectedCustomerId(customerId);
    setDrawerOpen(true);
    setProfileLoading(true);
    try {
      const [profile, freq] = await Promise.all([
        fetchCrossBrandProfile(customerId),
        fetchCrossBrandFrequency(customerId),
      ]);
      setCustomerProfile(profile);
      setFrequencyInfo(freq);
    } catch {
      message.error('加载客户画像失败');
    } finally {
      setProfileLoading(false);
    }
  }, []);

  // 手动触发自动迭代
  const handleAutoIterate = useCallback(async () => {
    setIterating(true);
    try {
      await triggerAutoIterate();
      message.success('自动迭代已触发，结果将在完成后显示');
      refreshAdjust();
    } catch {
      message.error('触发自动迭代失败');
    } finally {
      setIterating(false);
    }
  }, [refreshAdjust]);

  // 机会列表列定义
  const columns: ColumnsType<CrossBrandOpportunity> = [
    {
      title: '客户ID',
      dataIndex: 'customer_id',
      key: 'customer_id',
      width: 220,
      render: (id: string) => (
        <a style={{ color: INFO_BLUE }} onClick={() => openDrawer(id)}>
          {id.slice(0, 8)}...
        </a>
      ),
    },
    {
      title: '涉及品牌数',
      dataIndex: 'brand_count',
      key: 'brand_count',
      width: 100,
      sorter: (a, b) => a.brand_count - b.brand_count,
      render: (v: number) => (
        <Tag color={v >= 3 ? 'gold' : v >= 2 ? 'blue' : 'default'}>{v}</Tag>
      ),
    },
    {
      title: '品牌画像摘要',
      dataIndex: 'brands',
      key: 'brands',
      render: (brands: CrossBrandOpportunity['brands']) => (
        <Space wrap size={4}>
          {brands.map(b => (
            <Tag key={b.brand_id} color={STAGE_COLOR[b.repurchase_stage] || TEXT_SECONDARY}>
              {b.brand_name}: {b.repurchase_stage}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '机会类型',
      dataIndex: 'opportunity',
      key: 'opp_type',
      width: 140,
      render: (opp: CrossBrandOpportunity['opportunity']) =>
        opp ? <Tag color={BRAND_ORANGE}>{opp.type}</Tag> : <Tag>--</Tag>,
    },
    {
      title: '推荐动作',
      dataIndex: 'opportunity',
      key: 'opp_action',
      render: (opp: CrossBrandOpportunity['opportunity']) =>
        opp ? <span style={{ color: TEXT_PRIMARY }}>{opp.recommended_action}</span> : '--',
    },
  ];

  // 调整建议列定义
  const adjustColumns: ColumnsType<ExperimentAdjustment> = [
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 160,
      render: (t: string) => (
        <Tag color={t === 'low_open_rate' ? WARNING_ORANGE : DANGER_RED}>
          {t === 'low_open_rate' ? '低打开率' : '低完成率'}
        </Tag>
      ),
    },
    {
      title: '旅程/机制',
      key: 'target',
      width: 200,
      render: (_: unknown, r: ExperimentAdjustment) =>
        r.journey_name || `${r.mechanism_type || '--'} / ${r.channel || '--'}`,
    },
    {
      title: '数据',
      key: 'rate',
      width: 120,
      render: (_: unknown, r: ExperimentAdjustment) => {
        if (r.open_rate != null) return <span style={{ color: DANGER_RED }}>{r.open_rate}%</span>;
        if (r.completion_rate != null) return <span style={{ color: DANGER_RED }}>{r.completion_rate}%</span>;
        return '--';
      },
    },
    {
      title: '建议',
      dataIndex: 'recommendation',
      key: 'recommendation',
    },
  ];

  return (
    <div style={{ padding: 24, background: PAGE_BG, minHeight: '100vh' }}>
      {/* 区域1: 概览卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={8}>
          <Card style={{ background: CARD_BG, border: `1px solid ${BORDER}` }} bordered={false}>
            <Statistic
              title={<span style={{ color: TEXT_SECONDARY }}>跨品牌客户数</span>}
              value={crossBrandCount}
              valueStyle={{ color: INFO_BLUE, fontSize: 32 }}
              suffix={<span style={{ fontSize: 14, color: TEXT_SECONDARY }}>在2+品牌有画像</span>}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card style={{ background: CARD_BG, border: `1px solid ${BORDER}` }} bordered={false}>
            <Statistic
              title={<span style={{ color: TEXT_SECONDARY }}>交叉推荐机会</span>}
              value={opportunityCount}
              valueStyle={{ color: BRAND_ORANGE, fontSize: 32 }}
              suffix={<span style={{ fontSize: 14, color: TEXT_SECONDARY }}>可转化</span>}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card style={{ background: CARD_BG, border: `1px solid ${BORDER}` }} bordered={false}>
            <Statistic
              title={<span style={{ color: TEXT_SECONDARY }}>本周跨品牌触达</span>}
              value={weekTouchCount}
              valueStyle={{ color: SUCCESS_GREEN, fontSize: 32 }}
              suffix={<span style={{ fontSize: 14, color: TEXT_SECONDARY }}>次</span>}
            />
          </Card>
        </Col>
      </Row>

      {/* 区域2: 跨品牌机会列表 */}
      <Card
        title={<span style={{ color: TEXT_PRIMARY }}>跨品牌增长机会</span>}
        style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 24 }}
        bordered={false}
      >
        <Spin spinning={oppLoading}>
          <Table<CrossBrandOpportunity>
            columns={columns}
            dataSource={opportunities}
            rowKey="customer_id"
            pagination={{
              current: page,
              pageSize,
              total,
              onChange: (p) => setPage(p),
              showTotal: (t) => `共 ${t} 条`,
            }}
            expandable={{
              expandedRowRender: (record) => (
                <div style={{ padding: '8px 16px' }}>
                  {record.brands.map(b => (
                    <Descriptions
                      key={b.brand_id}
                      title={<span style={{ color: TEXT_PRIMARY }}>{b.brand_name}</span>}
                      column={4}
                      size="small"
                      style={{ marginBottom: 8 }}
                      labelStyle={{ color: TEXT_SECONDARY }}
                      contentStyle={{ color: TEXT_PRIMARY }}
                    >
                      <Descriptions.Item label="复购阶段">
                        <Tag color={STAGE_COLOR[b.repurchase_stage]}>{b.repurchase_stage}</Tag>
                      </Descriptions.Item>
                      <Descriptions.Item label="召回优先级">
                        <Tag color={PRIORITY_COLOR[b.reactivation_priority]}>{b.reactivation_priority}</Tag>
                      </Descriptions.Item>
                    </Descriptions>
                  ))}
                  {record.opportunity && (
                    <Alert
                      type="info"
                      showIcon
                      message={record.opportunity.description}
                      description={`推荐动作: ${record.opportunity.recommended_action}`}
                      style={{ marginTop: 8 }}
                    />
                  )}
                </div>
              ),
            }}
            style={{ background: 'transparent' }}
            size="middle"
          />
        </Spin>
      </Card>

      {/* 区域4: 实验自动迭代监控 */}
      <Card
        title={<span style={{ color: TEXT_PRIMARY }}>实验自动迭代监控</span>}
        extra={
          <Button
            type="primary"
            loading={iterating}
            onClick={handleAutoIterate}
            style={{ background: BRAND_ORANGE, borderColor: BRAND_ORANGE }}
          >
            手动触发迭代
          </Button>
        }
        style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
        bordered={false}
      >
        {/* 低效旅程警告 */}
        {adjustments
          .filter(a => a.type === 'low_completion_rate')
          .map((a, i) => (
            <Alert
              key={i}
              type="warning"
              showIcon
              message={`低效旅程: ${a.journey_name || a.journey_code}`}
              description={a.recommendation}
              style={{ marginBottom: 12 }}
            />
          ))}

        <Spin spinning={adjustLoading}>
          <Table<ExperimentAdjustment>
            columns={adjustColumns}
            dataSource={adjustments}
            rowKey={(_, i) => String(i)}
            pagination={false}
            size="middle"
            style={{ background: 'transparent' }}
            locale={{ emptyText: '暂无调整建议，所有旅程运行正常' }}
          />
        </Spin>
      </Card>

      {/* 区域3: 客户详情Drawer */}
      <Drawer
        title={<span style={{ color: TEXT_PRIMARY }}>跨品牌客户详情</span>}
        width={640}
        open={drawerOpen}
        onClose={() => { setDrawerOpen(false); setCustomerProfile(null); }}
        styles={{
          body: { background: PAGE_BG, padding: 24 },
          header: { background: CARD_BG, borderBottom: `1px solid ${BORDER}` },
        }}
      >
        <Spin spinning={profileLoading}>
          {customerProfile && (
            <>
              {/* 频控状态 */}
              {frequencyInfo && (
                <Alert
                  type={frequencyInfo.can_touch ? 'success' : 'error'}
                  showIcon
                  message={frequencyInfo.can_touch ? '可触达' : '频控限制中'}
                  description={`今日: ${frequencyInfo.today_count}次 / 本周: ${frequencyInfo.week_count}次`}
                  style={{ marginBottom: 16 }}
                />
              )}

              {/* 各品牌画像卡片 */}
              <div style={{ marginBottom: 16 }}>
                <div style={{ color: TEXT_SECONDARY, fontSize: 12, marginBottom: 8 }}>
                  品牌画像 ({customerProfile.brand_count} 个品牌)
                </div>
                <Row gutter={12}>
                  {customerProfile.brand_profiles.map(bp => (
                    <Col span={12} key={bp.brand_id} style={{ marginBottom: 12 }}>
                      <Card
                        size="small"
                        title={<span style={{ color: TEXT_PRIMARY }}>{bp.brand_name}</span>}
                        style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
                        bordered={false}
                      >
                        <Space direction="vertical" size={4} style={{ width: '100%' }}>
                          <div>
                            <span style={{ color: TEXT_SECONDARY, fontSize: 12 }}>复购阶段: </span>
                            <Tag color={STAGE_COLOR[bp.repurchase_stage]}>{bp.repurchase_stage}</Tag>
                          </div>
                          <div>
                            <span style={{ color: TEXT_SECONDARY, fontSize: 12 }}>心理距离: </span>
                            <Tag>{bp.psych_distance_level || '--'}</Tag>
                          </div>
                          <div>
                            <span style={{ color: TEXT_SECONDARY, fontSize: 12 }}>超级用户: </span>
                            <Tag color={bp.super_user_level === 'high' ? 'gold' : undefined}>
                              {bp.super_user_level || '--'}
                            </Tag>
                          </div>
                        </Space>
                      </Card>
                    </Col>
                  ))}
                </Row>
              </div>

              {/* 统一触达历史 */}
              <Card
                size="small"
                title={<span style={{ color: TEXT_PRIMARY }}>跨品牌触达统计</span>}
                style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
                bordered={false}
              >
                <Descriptions column={3} size="small" labelStyle={{ color: TEXT_SECONDARY }} contentStyle={{ color: TEXT_PRIMARY }}>
                  <Descriptions.Item label="总触达">
                    {customerProfile.cross_brand_touch_total}
                  </Descriptions.Item>
                  <Descriptions.Item label="今日">
                    {customerProfile.cross_brand_touch_today}
                  </Descriptions.Item>
                  <Descriptions.Item label="本周">
                    {customerProfile.cross_brand_touch_week}
                  </Descriptions.Item>
                </Descriptions>
              </Card>
            </>
          )}
          {!customerProfile && !profileLoading && (
            <div style={{ textAlign: 'center', color: TEXT_SECONDARY, padding: 48 }}>
              选择一个客户查看详情
            </div>
          )}
        </Spin>
      </Drawer>
    </div>
  );
}
