/**
 * 前厅工作台 — /front/workbench
 *
 * 最能体现门店前厅价值的页面。
 * 迎宾、楼面经理在一个页面看清：
 * - 今日预订
 * - 当前等位
 * - 当前桌态
 * - 重点客人
 * - Agent 建议动作
 *
 * Admin 终端（迎宾iPad通过浏览器访问总部后台版）
 * 布局：顶部四卡 + 中部左右列表 + 底部桌态缩略
 */
import { useState } from 'react';
import { Row, Col, Card, Statistic, Table, Tag, Button, Space, Badge, Typography, List, Avatar } from 'antd';
import {
  CalendarOutlined, TeamOutlined, CoffeeOutlined, ClockCircleOutlined,
  PhoneOutlined, CheckOutlined, SwapOutlined, GiftOutlined,
  UserOutlined, CrownOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons';

const { Text, Title } = Typography;

// ── 桌态颜色 ────────────────────────────────────────────────────────────────
const TABLE_COLORS: Record<string, string> = {
  available: '#0F6E56',     // 绿-空闲
  reserved: '#185FA5',      // 蓝-已预订
  occupied: '#FF6B35',      // 橙-用餐中
  overtime: '#A32D2D',      // 红-超时
  cleaning: '#B4B2A9',      // 灰-清台
};

// ── Mock 数据 ────────────────────────────────────────────────────────────────
const MOCK_RESERVATIONS = [
  { id: '1', time: '18:00', name: '王先生', party: 6, type: '包厢', status: 'confirmed', isVip: true, note: '生日宴' },
  { id: '2', time: '18:30', name: '李女士', party: 4, type: '散台', status: 'pending', isVip: false, note: '' },
  { id: '3', time: '19:00', name: '张总', party: 8, type: '包厢', status: 'confirmed', isVip: true, note: '商务宴请' },
  { id: '4', time: '19:30', name: '赵先生', party: 2, type: '散台', status: 'pending', isVip: false, note: '' },
];

const MOCK_WAITLIST = [
  { id: 'W1', number: 'A003', party: 4, waitMinutes: 25, estimatedSeat: '约10分钟', risk: 'high' },
  { id: 'W2', number: 'A004', party: 2, waitMinutes: 15, estimatedSeat: '约5分钟', risk: 'low' },
  { id: 'W3', number: 'A005', party: 6, waitMinutes: 8, estimatedSeat: '约20分钟', risk: 'medium' },
];

const MOCK_TABLES = [
  { id: 'A1', status: 'occupied', label: 'A1' }, { id: 'A2', status: 'occupied', label: 'A2' },
  { id: 'A3', status: 'available', label: 'A3' }, { id: 'A4', status: 'reserved', label: 'A4' },
  { id: 'B1', status: 'occupied', label: 'B1' }, { id: 'B2', status: 'overtime', label: 'B2' },
  { id: 'B3', status: 'cleaning', label: 'B3' }, { id: 'B4', status: 'available', label: 'B4' },
  { id: 'C1', status: 'reserved', label: 'C1' }, { id: 'C2', status: 'available', label: 'C2' },
  { id: 'P1', status: 'reserved', label: '包1' }, { id: 'P2', status: 'occupied', label: '包2' },
];

export default function FrontWorkbenchPage() {
  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>前厅工作台</Title>

      {/* 顶部四卡 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="今日预订" value={12} prefix={<CalendarOutlined />} suffix="桌" />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="当前等位" value={3} prefix={<TeamOutlined />} suffix="桌"
              valueStyle={{ color: '#BA7517' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="空闲桌位" value={4} prefix={<CoffeeOutlined />} suffix="/ 12"
              valueStyle={{ color: '#0F6E56' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="超时桌" value={1} prefix={<ClockCircleOutlined />} suffix="桌"
              valueStyle={{ color: '#A32D2D' }} />
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        {/* 今日预订列表 */}
        <Col span={12}>
          <Card size="small" title="今日预订" extra={<Button size="small" type="primary">新建预订</Button>}>
            <Table
              dataSource={MOCK_RESERVATIONS}
              rowKey="id"
              size="small"
              pagination={false}
              columns={[
                { title: '时间', dataIndex: 'time', width: 60 },
                {
                  title: '顾客', dataIndex: 'name', width: 100,
                  render: (name, r) => (
                    <Space>
                      {r.isVip && <CrownOutlined style={{ color: '#BA7517' }} />}
                      <Text>{name}</Text>
                    </Space>
                  ),
                },
                { title: '人数', dataIndex: 'party', width: 50 },
                { title: '桌型', dataIndex: 'type', width: 60 },
                {
                  title: '状态', dataIndex: 'status', width: 70,
                  render: (s) => (
                    <Tag color={s === 'confirmed' ? 'green' : 'orange'}>
                      {s === 'confirmed' ? '已确认' : '待确认'}
                    </Tag>
                  ),
                },
                {
                  title: '操作', width: 120,
                  render: (_, r) => (
                    <Space size={4}>
                      {r.status === 'pending' && <Button size="small" type="link" icon={<CheckOutlined />}>确认</Button>}
                      <Button size="small" type="link" icon={<SwapOutlined />}>改约</Button>
                    </Space>
                  ),
                },
              ]}
            />
          </Card>
        </Col>

        {/* 当前等位列表 */}
        <Col span={12}>
          <Card size="small" title="当前等位" extra={<Button size="small">加入等位</Button>}>
            <List
              dataSource={MOCK_WAITLIST}
              renderItem={(item) => (
                <List.Item
                  actions={[
                    <Button size="small" type="primary">叫号</Button>,
                    <Button size="small">安抚</Button>,
                  ]}
                >
                  <List.Item.Meta
                    avatar={
                      <Badge
                        count={item.risk === 'high' ? <ExclamationCircleOutlined style={{ color: '#A32D2D' }} /> : 0}
                      >
                        <Avatar style={{ background: item.risk === 'high' ? '#A32D2D' : '#FF6B35' }}>
                          {item.number}
                        </Avatar>
                      </Badge>
                    }
                    title={
                      <Space>
                        <Text>{item.number}</Text>
                        <Text type="secondary">{item.party}人</Text>
                        {item.risk === 'high' && <Tag color="red">流失风险</Tag>}
                      </Space>
                    }
                    description={
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        已等 {item.waitMinutes} 分钟 · 预计 {item.estimatedSeat}
                      </Text>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>

      {/* 底部桌态缩略图 */}
      <Card size="small" title="桌态总览" extra={
        <Space size={12}>
          {Object.entries({ available: '空闲', reserved: '已预订', occupied: '用餐中', overtime: '超时', cleaning: '清台' })
            .map(([k, v]) => (
              <Space key={k} size={4}>
                <div style={{ width: 12, height: 12, borderRadius: 2, background: TABLE_COLORS[k] }} />
                <Text style={{ fontSize: 11 }}>{v}</Text>
              </Space>
            ))}
        </Space>
      }>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {MOCK_TABLES.map((t) => (
            <div
              key={t.id}
              style={{
                width: 64, height: 56, borderRadius: 8,
                background: TABLE_COLORS[t.status] || '#B4B2A9',
                color: '#fff', display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center',
                cursor: 'pointer', fontSize: 13, fontWeight: 600,
                transition: 'transform 0.15s',
              }}
              title={`${t.label} - ${t.status}`}
            >
              {t.label}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
