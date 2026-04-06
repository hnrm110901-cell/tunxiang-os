/**
 * GrowthJourneyTemplatePage — 旅程模板管理
 * 路由: /hq/growth/journey-templates
 * 卡片列表 + Drawer查看步骤
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Card, Tag, Button, Space, Row, Col, Select, Drawer, Switch, Spin, Table, message,
} from 'antd';
import { PlusOutlined, EditOutlined } from '@ant-design/icons';
import { txFetch } from '../../../api';
import type { JourneyTemplate, JourneyStep } from '../../../api/growthHubApi';

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

  const fetchTemplates = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (filterType) params.journey_type = filterType;
      const qs = Object.keys(params).length > 0 ? '?' + new URLSearchParams(params).toString() : '';
      const resp = await txFetch<{ items: JourneyTemplate[]; total: number }>(`/api/v1/growth/journey-templates${qs}`);
      if (resp.data) setTemplates(resp.data.items);
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
        const resp = await txFetch<JourneyTemplate>(`/api/v1/growth/journey-templates/${tpl.id}`);
        if (resp.data) setSelectedTemplate(resp.data);
      } catch (err) {
        console.error('fetch template detail error', err);
      } finally {
        setDetailLoading(false);
      }
    }
  };

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
                  <Tag color={MECHANISM_COLORS[tpl.mechanism_family] || 'default'}>
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

                <div style={{ marginTop: 8, color: TEXT_SECONDARY, fontSize: 11 }}>
                  创建于 {tpl.created_at?.slice(0, 10)}
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
              <Tag color={MECHANISM_COLORS[selectedTemplate.mechanism_family] || 'default'}>
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
    </div>
  );
}
