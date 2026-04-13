/**
 * GrowthJourneyTemplatePage — 旅程模板管理
 * 路由: /hq/growth/journey-templates
 * 卡片列表 + Drawer查看步骤
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Card, Tag, Button, Space, Row, Col, Select, Drawer, Switch, Spin, Table, message, Badge,
} from 'antd';
import { PlusOutlined, EditOutlined, ExperimentOutlined } from '@ant-design/icons';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { txFetchData } from '../../../api';
import type { JourneyTemplate, JourneyStep, ExperimentSummary, ExperimentSelectResult, ExperimentAutoPauseResult } from '../../../api/growthHubApi';

echarts.use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

// ---- 颜色常量 ----
const PAGE_BG = '#0d1e28';
const CARD_BG = '#142833';
const BORDER = '#1e3a4a';
const TEXT_PRIMARY = '#e8e8e8';
const TEXT_SECONDARY = '#8899a6';
const BRAND_ORANGE = '#FF6B35';
const SUCCESS_GREEN = '#52c41a';

const JOURNEY_TYPE_COLORS: Record<string, string> = {
  first_to_second: 'green',
  reactivation: 'orange',
  service_repair: 'red',
  retention: 'blue',
  upsell: 'purple',
  referral: 'cyan',
};

const JOURNEY_TYPE_LABELS: Record<string, string> = {
  first_to_second: '首转二',
  reactivation: '激活沉默',
  service_repair: '服务修复',
  retention: '留存维护',
  upsell: '提频升单',
  referral: '裂变拉新',
};

const MECHANISM_COLORS: Record<string, string> = {
  hook: 'cyan',
  loss_aversion: 'orange',
  repair: 'red',
  mixed: 'purple',
  social_proof: 'blue',
  scarcity: 'gold',
};

const STEP_TYPE_LABELS: Record<string, string> = {
  wait: '等待',
  touch: '触达',
  observe: '观察窗口',
  condition: '条件判断',
  action: '动作执行',
  exit: '退出判断',
};

// ---- 组件 ----
export function GrowthJourneyTemplatePage() {
  const [loading, setLoading] = useState(false);
  const [templates, setTemplates] = useState<JourneyTemplate[]>([]);
  const [filterType, setFilterType] = useState<string | undefined>();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<JourneyTemplate | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Sprint I: Experiment state
  const [expDrawerOpen, setExpDrawerOpen] = useState(false);
  const [expTemplateId, setExpTemplateId] = useState<string | null>(null);
  const [expSummary, setExpSummary] = useState<ExperimentSummary | null>(null);
  const [expSelectResult, setExpSelectResult] = useState<ExperimentSelectResult | null>(null);
  const [expAutoPause, setExpAutoPause] = useState<ExperimentAutoPauseResult | null>(null);
  const [expLoading, setExpLoading] = useState(false);

  const fetchTemplates = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (filterType) params.journey_type = filterType;
      const qs = Object.keys(params).length > 0 ? '?' + new URLSearchParams(params).toString() : '';
      const resp = await txFetchData<{ items: JourneyTemplate[]; total: number }>(`/api/v1/growth/journey-templates${qs}`);
      if (resp) setTemplates(resp.items);
    } catch (err) {
      console.error('fetch templates error', err);
    } finally {
      setLoading(false);
    }
  }, [filterType]);

  useEffect(() => { fetchTemplates(); }, [fetchTemplates]);

  const handleCardClick = async (tpl: JourneyTemplate) => {
    setSelectedTemplate(tpl);
    setDrawerOpen(true);
    if (!tpl.steps) {
      setDetailLoading(true);
      try {
        const resp = await txFetchData<JourneyTemplate>(`/api/v1/growth/journey-templates/${tpl.id}`);
        if (resp) setSelectedTemplate(resp);
      } catch (err) {
        console.error('fetch template detail error', err);
      } finally {
        setDetailLoading(false);
      }
    }
  };

  // Sprint I: Open experiment drawer
  const openExperimentDrawer = async (templateId: string) => {
    setExpTemplateId(templateId);
    setExpDrawerOpen(true);
    setExpLoading(true);
    try {
      const [summaryResp, selectResp, pauseResp] = await Promise.all([
        txFetchData<ExperimentSummary>(`/api/v1/growth/experiments/${templateId}/summary`),
        txFetchData<ExperimentSelectResult>(`/api/v1/growth/experiments/${templateId}/select-variant`),
        txFetchData<ExperimentAutoPauseResult>(`/api/v1/growth/experiments/${templateId}/auto-pause-check?min_samples=30`),
      ]);
      if (summaryResp) setExpSummary(summaryResp);
      if (selectResp) setExpSelectResult(selectResp);
      if (pauseResp) setExpAutoPause(pauseResp);
    } catch (fetchErr) {
      console.error('fetch experiment data error', fetchErr);
    } finally {
      setExpLoading(false);
    }
  };

  // Sprint I: Experiment chart
  const expChartOption = expSummary && expSummary.variants.length > 0 ? {
    tooltip: { trigger: 'axis' as const },
    grid: { left: 60, right: 20, top: 30, bottom: 30 },
    xAxis: {
      type: 'category' as const,
      data: expSummary.variants.map(v => v.variant),
      axisLabel: { color: '#8899a6' },
      axisLine: { lineStyle: { color: '#1e3a4a' } },
    },
    yAxis: {
      type: 'value' as const, name: '完成率(%)',
      axisLabel: { color: '#8899a6' },
      splitLine: { lineStyle: { color: '#1e3a4a', type: 'dashed' as const } },
    },
    series: [{
      name: '完成率',
      type: 'bar',
      data: expSummary.variants.map(v => v.completion_rate),
      itemStyle: {
        color: (params: { dataIndex: number }) => {
          const v = expSummary!.variants[params.dataIndex];
          if (expSelectResult?.selected === v.variant) return '#FF6B35';
          if (expAutoPause?.pause_variants?.includes(v.variant)) return '#ff4d4f';
          return '#1890ff';
        },
      },
      label: { show: true, position: 'top', color: '#8899a6', formatter: '{c}%' },
    }],
  } : {};

  return (
    <div style={{ padding: 24, background: PAGE_BG, minHeight: '100vh' }}>
      {/* 顶部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ color: TEXT_PRIMARY, margin: 0 }}>旅程模板管理</h2>
        <Space>
          <Select
            placeholder="旅程类型"
            value={filterType}
            onChange={setFilterType}
            allowClear
            style={{ width: 160 }}
            options={Object.entries(JOURNEY_TYPE_LABELS).map(([k, v]) => ({ value: k, label: v }))}
          />
          <Button type="primary" icon={<PlusOutlined />} style={{ background: BRAND_ORANGE, borderColor: BRAND_ORANGE }}>
            创建旅程
          </Button>
        </Space>
      </div>

      {/* 模板卡片列表 */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>
      ) : templates.length === 0 ? (
        <Card style={{ background: CARD_BG, border: `1px solid ${BORDER}`, textAlign: 'center', padding: 60 }}>
          <div style={{ color: TEXT_SECONDARY, fontSize: 16 }}>暂无旅程模板</div>
          <Button type="primary" style={{ marginTop: 16, background: BRAND_ORANGE, borderColor: BRAND_ORANGE }}>
            创建第一个旅程模板
          </Button>
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {templates.map((tpl) => (
            <Col key={tpl.id} xs={24} sm={12} lg={8} xl={6}>
              <Card
                hoverable
                onClick={() => handleCardClick(tpl)}
                style={{
                  background: CARD_BG, border: `1px solid ${BORDER}`, cursor: 'pointer',
                  height: '100%',
                }}
                bodyStyle={{ padding: 16 }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
                  <div style={{ color: TEXT_PRIMARY, fontSize: 15, fontWeight: 600, flex: 1 }}>
                    {tpl.name}
                  </div>
                  {tpl.is_system && <Tag color="default" style={{ flexShrink: 0 }}>系统</Tag>}
                </div>

                <Space size={4} wrap style={{ marginBottom: 12 }}>
                  <Tag color={JOURNEY_TYPE_COLORS[tpl.journey_type] || 'default'}>
                    {JOURNEY_TYPE_LABELS[tpl.journey_type] || tpl.journey_type}
                  </Tag>
                  <Tag color={(tpl.mechanism_family ? MECHANISM_COLORS[tpl.mechanism_family] : undefined) || 'default'}>
                    {tpl.mechanism_family}
                  </Tag>
                </Space>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ color: TEXT_SECONDARY, fontSize: 12 }}>
                    优先级: <span style={{ color: TEXT_PRIMARY }}>{tpl.priority}</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 12, color: TEXT_SECONDARY }}>
                      {tpl.is_active ? '启用' : '停用'}
                    </span>
                    <Switch
                      size="small"
                      checked={tpl.is_active}
                      onClick={(_, e) => e.stopPropagation()}
                      onChange={() => message.info('功能开发中')}
                    />
                  </div>
                </div>

                <div style={{ marginTop: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: TEXT_SECONDARY, fontSize: 11 }}>
                    创建于 {tpl.created_at?.slice(0, 10)}
                  </span>
                  {!!(tpl as unknown as Record<string, unknown>).ab_test_id && (
                    <Button
                      size="small"
                      icon={<ExperimentOutlined />}
                      style={{ borderColor: BRAND_ORANGE, color: BRAND_ORANGE, fontSize: 11 }}
                      onClick={(e) => { e.stopPropagation(); openExperimentDrawer(tpl.id); }}
                    >
                      <Badge color={BRAND_ORANGE} dot style={{ marginRight: 4 }} />
                      实验
                    </Button>
                  )}
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      {/* 步骤详情Drawer */}
      <Drawer
        title={<span style={{ color: TEXT_PRIMARY }}>{selectedTemplate?.name || '模板详情'}</span>}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={520}
        styles={{
          header: { background: CARD_BG, borderBottom: `1px solid ${BORDER}` },
          body: { background: PAGE_BG, padding: 16 },
        }}
      >
        {selectedTemplate && (
          <div>
            <Space style={{ marginBottom: 16 }}>
              <Tag color={JOURNEY_TYPE_COLORS[selectedTemplate.journey_type] || 'default'}>
                {JOURNEY_TYPE_LABELS[selectedTemplate.journey_type] || selectedTemplate.journey_type}
              </Tag>
              <Tag color={(selectedTemplate.mechanism_family ? MECHANISM_COLORS[selectedTemplate.mechanism_family] : undefined) || 'default'}>
                {selectedTemplate.mechanism_family}
              </Tag>
              <Tag>{selectedTemplate.is_active ? '启用中' : '已停用'}</Tag>
              <Tag>优先级 {selectedTemplate.priority}</Tag>
            </Space>

            <Card
              title={<span style={{ color: TEXT_PRIMARY }}>旅程步骤</span>}
              style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
              styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
              bodyStyle={{ padding: 0 }}
            >
              {detailLoading ? (
                <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
              ) : selectedTemplate.steps && selectedTemplate.steps.length > 0 ? (
                <Table
                  dataSource={selectedTemplate.steps}
                  rowKey="id"
                  size="small"
                  pagination={false}
                  columns={[
                    {
                      title: '#', dataIndex: 'step_no', width: 50,
                      render: (v: number) => <span style={{ color: BRAND_ORANGE, fontWeight: 600 }}>{v}</span>,
                    },
                    {
                      title: '类型', dataIndex: 'step_type', width: 100,
                      render: (v: string) => <Tag>{STEP_TYPE_LABELS[v] || v}</Tag>,
                    },
                    {
                      title: '机制', dataIndex: 'mechanism_type', width: 100,
                      render: (v: string | null) => v ? <Tag color="cyan">{v}</Tag> : '-',
                    },
                    {
                      title: '等待(分钟)', dataIndex: 'wait_minutes', width: 100,
                      render: (v: number | null) => v != null ? (
                        <span style={{ color: TEXT_PRIMARY }}>
                          {v >= 1440 ? `${(v / 1440).toFixed(0)}天` : v >= 60 ? `${(v / 60).toFixed(0)}小时` : `${v}分`}
                        </span>
                      ) : '-',
                    },
                    {
                      title: '观察窗口', dataIndex: 'observe_window_hours', width: 100,
                      render: (v: number | null) => v != null ? (
                        <span style={{ color: TEXT_PRIMARY }}>
                          {v >= 24 ? `${(v / 24).toFixed(0)}天` : `${v}小时`}
                        </span>
                      ) : '-',
                    },
                  ]}
                />
              ) : (
                <div style={{ textAlign: 'center', padding: 40, color: TEXT_SECONDARY }}>暂无步骤</div>
              )}
            </Card>

            <div style={{ marginTop: 16, textAlign: 'center' }}>
              <Button icon={<EditOutlined />} style={{ borderColor: BRAND_ORANGE, color: BRAND_ORANGE }}>
                编辑模板
              </Button>
            </div>
          </div>
        )}
      </Drawer>

      {/* Sprint I: 实验监控Drawer */}
      <Drawer
        title={<span style={{ color: TEXT_PRIMARY }}>A/B实验监控</span>}
        open={expDrawerOpen}
        onClose={() => { setExpDrawerOpen(false); setExpSummary(null); setExpSelectResult(null); setExpAutoPause(null); }}
        width={600}
        styles={{
          header: { background: CARD_BG, borderBottom: `1px solid ${BORDER}` },
          body: { background: PAGE_BG, padding: 16 },
        }}
      >
        {expLoading ? (
          <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Thompson Sampling最优variant */}
            {expSelectResult && (
              <Card size="small" style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}>
                <div style={{ marginBottom: 8, fontSize: 13, color: TEXT_SECONDARY }}>Thompson Sampling 当前最优</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <Tag color="orange" style={{ fontSize: 16, padding: '4px 12px' }}>{expSelectResult.selected}</Tag>
                  <span style={{ color: TEXT_SECONDARY, fontSize: 12 }}>
                    策略: {expSelectResult.reason === 'thompson_sampling' ? 'Thompson Sampling自动选择' : '无数据(默认control)'}
                  </span>
                </div>
              </Card>
            )}

            {/* 暂停建议 */}
            {expAutoPause && expAutoPause.action === 'pause_underperformers' && (
              <Card size="small" style={{ background: '#ff4d4f11', border: '1px solid #ff4d4f33' }}>
                <div style={{ color: '#ff4d4f', fontWeight: 600, marginBottom: 8 }}>
                  建议暂停低效variant
                </div>
                <div style={{ color: TEXT_SECONDARY, fontSize: 12 }}>
                  以下variant成功率低于最佳的50%：
                  {expAutoPause.pause_variants?.map(v => (
                    <Tag key={v} color="red" style={{ marginLeft: 8 }}>{v}</Tag>
                  ))}
                </div>
                <div style={{ color: TEXT_SECONDARY, fontSize: 11, marginTop: 8 }}>
                  最佳成功率: {((expAutoPause.best_rate ?? 0) * 100).toFixed(1)}%
                </div>
              </Card>
            )}

            {/* Variant completion_rate对比表 */}
            {expSummary && expSummary.variants.length > 0 && (
              <Card
                title={<span style={{ color: TEXT_PRIMARY }}>Variant对比</span>}
                size="small"
                style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
                styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
                bodyStyle={{ padding: 0 }}
              >
                <Table
                  dataSource={expSummary.variants}
                  rowKey="variant"
                  size="small"
                  pagination={false}
                  columns={[
                    { title: 'Variant', dataIndex: 'variant', width: 80,
                      render: (val: string) => (
                        <Tag color={val === expSelectResult?.selected ? 'orange' : 'default'}>
                          {val} {val === expSelectResult?.selected ? '(最优)' : ''}
                        </Tag>
                      ),
                    },
                    { title: '总数', dataIndex: 'total', width: 60 },
                    { title: '完成', dataIndex: 'completed', width: 60,
                      render: (val: number) => <span style={{ color: SUCCESS_GREEN }}>{val}</span> },
                    { title: '退出', dataIndex: 'exited', width: 60,
                      render: (val: number) => <span style={{ color: '#ff4d4f' }}>{val}</span> },
                    { title: '完成率', dataIndex: 'completion_rate', width: 80,
                      render: (val: number) => (
                        <span style={{ color: val >= 30 ? SUCCESS_GREEN : val >= 15 ? '#faad14' : '#ff4d4f', fontWeight: 600 }}>
                          {val.toFixed(1)}%
                        </span>
                      ),
                    },
                    { title: '平均时长', dataIndex: 'avg_duration_hours', width: 90,
                      render: (val: number | null) => (
                        <span style={{ color: TEXT_SECONDARY }}>{val != null ? `${val.toFixed(1)}h` : '--'}</span>
                      ),
                    },
                  ]}
                />
              </Card>
            )}

            {/* ECharts柱状图 */}
            {expSummary && expSummary.variants.length > 0 && (
              <Card
                title={<span style={{ color: TEXT_PRIMARY }}>完成率对比图</span>}
                size="small"
                style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
                styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
              >
                <ReactEChartsCore echarts={echarts} option={expChartOption} style={{ height: 250 }} />
              </Card>
            )}

            {(!expSummary || expSummary.variants.length === 0) && (
              <div style={{ textAlign: 'center', padding: 40, color: TEXT_SECONDARY }}>
                该模板暂无A/B实验数据
              </div>
            )}
          </div>
        )}
      </Drawer>
    </div>
  );
}
