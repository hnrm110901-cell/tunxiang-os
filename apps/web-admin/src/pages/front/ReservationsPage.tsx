/**
 * 预订台账页 — /front/reservations
 *
 * 预订全生命周期管理：列表 + 确认 + 改约 + 冲突检查 + 入座联动
 *
 * Admin 终端：Ant Design 5.x + ProTable
 * 布局：顶部统计 + 筛选栏 + 列表 + 右侧详情/Agent区
 */
import { useRef, useState } from 'react';
import { ProTable, ProColumns, ActionType, ModalForm, ProFormText, ProFormDatePicker, ProFormDigit, ProFormSelect } from '@ant-design/pro-components';
import {
  Row, Col, Card, Statistic, Tag, Button, Space, Typography,
  Descriptions, List, Alert, Divider, Timeline, message, Segmented,
} from 'antd';
import {
  PlusOutlined, CheckOutlined, SwapOutlined, CloseOutlined,
  LoginOutlined, PhoneOutlined, CrownOutlined, WarningOutlined,
  CalendarOutlined, UnorderedListOutlined,
} from '@ant-design/icons';
import type {
  ReservationFullItem, ReservationDetail, ReservationStatus,
} from '../../../../shared/api-types/p0-pages';
import { StatusTag } from '../../components/agent/StatusTag';

const { Text, Title, Paragraph } = Typography;

// ── Mock 数据 ────────────────────────────────────────────────────────────────

const MOCK_RESERVATIONS: ReservationFullItem[] = [
  {
    reservation_id: 'R001', reservation_no: 'RES-20260401-001',
    reservation_time: '18:00', customer_name: '王先生', customer_mobile_masked: '138****8888',
    party_size: 6, table_type_required: '包厢', room_required: true,
    reservation_status: 'confirmed', source_channel: '电话',
    vip_level: 'VIP', estimated_value_level: 'high',
    special_notes: '生日宴，需要蛋糕和布置',
    confirm_status: 'confirmed', reservation_tag: ['birthday', 'vip'],
    last_updated_at: '2026-04-01T10:00:00Z',
  },
  {
    reservation_id: 'R002', reservation_no: 'RES-20260401-002',
    reservation_time: '18:30', customer_name: '李女士', customer_mobile_masked: '139****6666',
    party_size: 4, table_type_required: '散台', room_required: false,
    reservation_status: 'pending_confirm', source_channel: '小程序',
    confirm_status: 'unconfirmed',
    last_updated_at: '2026-04-01T11:00:00Z',
  },
  {
    reservation_id: 'R003', reservation_no: 'RES-20260401-003',
    reservation_time: '19:00', customer_name: '张总', customer_mobile_masked: '136****1234',
    party_size: 8, table_type_required: '包厢', room_required: true,
    reservation_status: 'confirmed', source_channel: '企业微信',
    vip_level: 'VIP', estimated_value_level: 'high',
    special_notes: '商务宴请，需要安静包厢', reservation_tag: ['vip', 'repeat_customer'],
    confirm_status: 'confirmed', assigned_table_no: '包厢1',
    last_updated_at: '2026-04-01T09:30:00Z',
  },
  {
    reservation_id: 'R004', reservation_no: 'RES-20260401-004',
    reservation_time: '19:30', customer_name: '赵先生', customer_mobile_masked: '137****5555',
    party_size: 2, table_type_required: '散台', room_required: false,
    reservation_status: 'pending_confirm', source_channel: '抖音',
    confirm_status: 'unconfirmed', agent_risk_flag: true,
    last_updated_at: '2026-04-01T12:00:00Z',
  },
  {
    reservation_id: 'R005', reservation_no: 'RES-20260401-005',
    reservation_time: '20:00', customer_name: '陈女士', customer_mobile_masked: '150****3333',
    party_size: 10, table_type_required: '包厢', room_required: true,
    reservation_status: 'confirmed', source_channel: '电话',
    reservation_tag: ['banquet'],
    special_notes: '10人团餐，需要圆桌',
    confirm_status: 'confirmed', assigned_table_no: '包厢2',
    last_updated_at: '2026-04-01T08:00:00Z',
  },
];

const MOCK_DETAIL: ReservationDetail = {
  reservation_id: 'R001',
  reservation_note: '生日宴，需要蛋糕和布置，客人偏好靠窗位置',
  customer_id: 'C-001', customer_level: 'VIP金卡',
  historical_visit_count: 12, historical_avg_spend: 680,
  dietary_preferences: ['不吃辣', '海鲜过敏'],
  arrival_eta: '17:50',
  recommended_table_options: [
    { table_id: 'P1', table_no: '包厢1', zone_name: '包厢区', capacity: 10, match_score: 0.95 },
    { table_id: 'P2', table_no: '包厢2', zone_name: '包厢区', capacity: 12, match_score: 0.80 },
  ],
  conflict_checks: [],
  contact_records: [
    { contact_time: '2026-04-01T10:00:00Z', contact_channel: 'phone', contact_result: 'confirmed' },
  ],
};

const tagColors: Record<string, string> = {
  birthday: 'magenta', vip: 'gold', banquet: 'purple', repeat_customer: 'cyan',
};
const tagLabels: Record<string, string> = {
  birthday: '生日', vip: 'VIP', banquet: '团餐', repeat_customer: '回头客',
};

// ── 页面组件 ─────────────────────────────────────────────────────────────────

export default function ReservationsPage() {
  const actionRef = useRef<ActionType>();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'list' | 'calendar'>('list');

  const selected = MOCK_RESERVATIONS.find((r) => r.reservation_id === selectedId);
  const pendingCount = MOCK_RESERVATIONS.filter((r) => r.reservation_status === 'pending_confirm').length;
  const confirmedCount = MOCK_RESERVATIONS.filter((r) => r.reservation_status === 'confirmed').length;

  const columns: ProColumns<ReservationFullItem>[] = [
    { title: '时间', dataIndex: 'reservation_time', width: 70, search: false },
    {
      title: '顾客', dataIndex: 'customer_name', width: 120,
      render: (_, r) => (
        <Space>
          {r.vip_level && <CrownOutlined style={{ color: '#BA7517' }} />}
          <Text>{r.customer_name}</Text>
          {r.agent_risk_flag && <WarningOutlined style={{ color: '#A32D2D' }} />}
        </Space>
      ),
    },
    { title: '电话', dataIndex: 'customer_mobile_masked', width: 110, search: false },
    { title: '人数', dataIndex: 'party_size', width: 60, search: false },
    { title: '桌型', dataIndex: 'table_type_required', width: 70, search: false },
    {
      title: '标签', dataIndex: 'reservation_tag', width: 120, search: false,
      render: (_, r) => r.reservation_tag?.map((t) => (
        <Tag key={t} color={tagColors[t]} style={{ fontSize: 10 }}>{tagLabels[t]}</Tag>
      )),
    },
    {
      title: '状态', dataIndex: 'reservation_status', width: 90,
      valueType: 'select',
      valueEnum: {
        pending_confirm: '待确认', confirmed: '已确认', arrived: '已到店',
        seated: '已入座', canceled: '已取消', no_show: '未到店',
      },
      render: (_, r) => <StatusTag status={r.reservation_status} />,
    },
    { title: '来源', dataIndex: 'source_channel', width: 70,
      valueType: 'select',
      valueEnum: { 电话: '电话', 小程序: '小程序', 抖音: '抖音', 企业微信: '企微' },
    },
    { title: '桌号', dataIndex: 'assigned_table_no', width: 70, search: false },
    {
      title: '操作', valueType: 'option', width: 180,
      render: (_, r) => (
        <Space size={4}>
          {r.reservation_status === 'pending_confirm' && (
            <Button size="small" type="link" icon={<CheckOutlined />}
              onClick={() => message.success(`${r.customer_name} 预订已确认`)}>
              确认
            </Button>
          )}
          <Button size="small" type="link" icon={<SwapOutlined />}>改约</Button>
          {r.reservation_status === 'confirmed' && (
            <Button size="small" type="link" icon={<LoginOutlined />}
              onClick={() => message.info('跳转桌态页安排入座')}>
              入座
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      {/* 页面标题区 */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Space>
          <Title level={4} style={{ margin: 0 }}>预订台账</Title>
          <Segmented
            value={viewMode}
            onChange={(v) => setViewMode(v as any)}
            options={[
              { value: 'list', icon: <UnorderedListOutlined /> },
              { value: 'calendar', icon: <CalendarOutlined /> },
            ]}
          />
        </Space>
        <Space>
          <Card size="small" style={{ padding: 0 }}>
            <Space size={16}>
              <Statistic title="今日总计" value={MOCK_RESERVATIONS.length} suffix="桌" valueStyle={{ fontSize: 18 }} />
              <Statistic title="待确认" value={pendingCount} valueStyle={{ fontSize: 18, color: '#BA7517' }} />
              <Statistic title="已确认" value={confirmedCount} valueStyle={{ fontSize: 18, color: '#0F6E56' }} />
            </Space>
          </Card>
          <ModalForm
            title="新建预订"
            trigger={<Button type="primary" icon={<PlusOutlined />}>新建预订</Button>}
            onFinish={async () => { message.success('预订已创建'); return true; }}
            width={480}
          >
            <ProFormText name="customer_name" label="顾客姓名" rules={[{ required: true }]} />
            <ProFormText name="customer_mobile" label="手机号" rules={[{ required: true }]} />
            <ProFormDatePicker name="reservation_date" label="日期" rules={[{ required: true }]} />
            <ProFormText name="reservation_time" label="时间" placeholder="如 18:00" rules={[{ required: true }]} />
            <ProFormDigit name="party_size" label="人数" min={1} max={30} rules={[{ required: true }]} />
            <ProFormSelect name="table_type_required" label="桌型"
              options={[{ label: '散台', value: '散台' }, { label: '包厢', value: '包厢' }]} />
            <ProFormText name="special_notes" label="备注" />
            <ProFormSelect name="source_channel" label="来源"
              options={[{ label: '电话', value: '电话' }, { label: '小程序', value: '小程序' }, { label: '企业微信', value: '企业微信' }]} />
          </ModalForm>
        </Space>
      </Row>

      <Row gutter={16}>
        {/* 列表区 */}
        <Col span={selectedId ? 15 : 24}>
          <ProTable<ReservationFullItem>
            columns={columns}
            actionRef={actionRef}
            dataSource={MOCK_RESERVATIONS}
            rowKey="reservation_id"
            search={{ labelWidth: 'auto' }}
            onRow={(record) => ({
              onClick: () => setSelectedId(record.reservation_id),
              style: { cursor: 'pointer', background: selectedId === record.reservation_id ? '#FFF3ED' : undefined },
            })}
            pagination={false}
          />
        </Col>

        {/* 右侧详情区 */}
        {selectedId && selected && (
          <Col span={9}>
            <Card
              size="small"
              title={
                <Space>
                  <Text strong>{selected.customer_name}</Text>
                  <StatusTag status={selected.reservation_status} />
                  {selected.vip_level && <Tag color="gold">{selected.vip_level}</Tag>}
                </Space>
              }
              extra={<Button type="text" size="small" onClick={() => setSelectedId(null)}>关闭</Button>}
              style={{ overflow: 'auto' }}
            >
              {/* 顾客信息 */}
              <Descriptions column={2} size="small">
                <Descriptions.Item label="时间">{selected.reservation_time}</Descriptions.Item>
                <Descriptions.Item label="人数">{selected.party_size} 人</Descriptions.Item>
                <Descriptions.Item label="桌型">{selected.table_type_required}</Descriptions.Item>
                <Descriptions.Item label="来源">{selected.source_channel}</Descriptions.Item>
                <Descriptions.Item label="到店次数" span={2}>{MOCK_DETAIL.historical_visit_count} 次</Descriptions.Item>
                <Descriptions.Item label="平均消费" span={2}>¥{MOCK_DETAIL.historical_avg_spend}</Descriptions.Item>
              </Descriptions>

              {selected.special_notes && (
                <Alert message={selected.special_notes} type="info" showIcon style={{ margin: '8px 0' }} />
              )}

              {MOCK_DETAIL.dietary_preferences && MOCK_DETAIL.dietary_preferences.length > 0 && (
                <Alert
                  message={`忌口: ${MOCK_DETAIL.dietary_preferences.join('、')}`}
                  type="warning" showIcon style={{ margin: '8px 0' }}
                />
              )}

              {/* 推荐桌位 */}
              <Divider style={{ margin: '12px 0' }} />
              <Title level={5} style={{ fontSize: 13 }}>推荐桌位</Title>
              <List
                size="small"
                dataSource={MOCK_DETAIL.recommended_table_options}
                renderItem={(t) => (
                  <List.Item actions={[
                    <Button size="small" type="primary" icon={<LoginOutlined />}>选定</Button>,
                  ]}>
                    <List.Item.Meta
                      title={<Space><Text strong>{t.table_no}</Text><Tag>{t.zone_name}</Tag></Space>}
                      description={`${t.capacity}座 · 匹配度 ${(t.match_score * 100).toFixed(0)}%`}
                    />
                  </List.Item>
                )}
              />

              {/* 冲突检查 */}
              {MOCK_DETAIL.conflict_checks.length > 0 && (
                <>
                  <Divider style={{ margin: '12px 0' }} />
                  <Alert
                    message="发现桌位冲突"
                    description={MOCK_DETAIL.conflict_checks.map((c) => c.conflict_desc).join('; ')}
                    type="warning" showIcon
                  />
                </>
              )}

              {/* 联系记录 */}
              <Divider style={{ margin: '12px 0' }} />
              <Title level={5} style={{ fontSize: 13 }}>联系记录</Title>
              <Timeline
                items={MOCK_DETAIL.contact_records.map((c) => ({
                  color: c.contact_result === 'confirmed' ? 'green' : 'orange',
                  children: (
                    <div style={{ fontSize: 12 }}>
                      <Text type="secondary">{new Date(c.contact_time).toLocaleString()}</Text>
                      <span style={{ margin: '0 8px' }}>{c.contact_channel === 'phone' ? '电话' : c.contact_channel}</span>
                      <StatusTag status={c.contact_result} label={c.contact_result === 'confirmed' ? '已确认' : c.contact_result} />
                    </div>
                  ),
                }))}
              />

              {/* 操作按钮 */}
              <Divider style={{ margin: '12px 0' }} />
              <Space direction="vertical" style={{ width: '100%' }}>
                {selected.reservation_status === 'pending_confirm' && (
                  <Button type="primary" block icon={<CheckOutlined />}>确认预订</Button>
                )}
                {selected.reservation_status === 'confirmed' && (
                  <Button type="primary" block icon={<LoginOutlined />}>安排入座</Button>
                )}
                <Button block icon={<SwapOutlined />}>改约</Button>
                <Button block icon={<PhoneOutlined />}>联系顾客</Button>
                <Button block danger icon={<CloseOutlined />}>取消预订</Button>
              </Space>
            </Card>
          </Col>
        )}
      </Row>
    </div>
  );
}
