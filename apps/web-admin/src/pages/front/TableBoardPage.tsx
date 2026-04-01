/**
 * 桌态总览页 — /front/tables
 *
 * 最能体现现场调度能力的页面。
 * 功能：桌态画布 + 筛选 + 详情抽屉 + Agent调度建议
 *
 * Admin 终端：Ant Design 5.x
 * 布局：顶部工具栏 + 桌态主画布 + 底部事件栏 + 右侧详情抽屉
 */
import { useState } from 'react';
import {
  Card, Row, Col, Select, Input, Button, Space, Tag, Drawer, Typography,
  Descriptions, Timeline, Segmented, Badge, Statistic, Divider, List,
} from 'antd';
import {
  SearchOutlined, AppstoreOutlined, UnorderedListOutlined,
  ClockCircleOutlined, UserOutlined, CoffeeOutlined,
  SwapOutlined, ScissorOutlined, MergeCellsOutlined,
} from '@ant-design/icons';

const { Text, Title, Paragraph } = Typography;

// ── 桌态定义 ────────────────────────────────────────────────────────────────
interface TableItem {
  id: string;
  label: string;
  zone: string;
  capacity: number;
  status: 'available' | 'reserved' | 'occupied' | 'cleaning' | 'maintenance';
  currentParty?: number;
  occupiedMinutes?: number;
  orderId?: string;
  customerName?: string;
  isVip?: boolean;
  estimatedTurnover?: number; // 预计翻台时间（分钟）
}

const STATUS_CONFIG: Record<string, { color: string; label: string }> = {
  available: { color: '#0F6E56', label: '空闲' },
  reserved: { color: '#185FA5', label: '已预订' },
  occupied: { color: '#FF6B35', label: '用餐中' },
  cleaning: { color: '#B4B2A9', label: '清台中' },
  maintenance: { color: '#5F5E5A', label: '维护' },
};

const MOCK_TABLES: TableItem[] = [
  { id: 'A1', label: 'A1', zone: 'A区-散台', capacity: 2, status: 'occupied', currentParty: 2, occupiedMinutes: 45, customerName: '李先生', estimatedTurnover: 15 },
  { id: 'A2', label: 'A2', zone: 'A区-散台', capacity: 2, status: 'occupied', currentParty: 2, occupiedMinutes: 80, customerName: '匿名', estimatedTurnover: 5 },
  { id: 'A3', label: 'A3', zone: 'A区-散台', capacity: 4, status: 'available' },
  { id: 'A4', label: 'A4', zone: 'A区-散台', capacity: 4, status: 'reserved', customerName: '王先生', isVip: true },
  { id: 'B1', label: 'B1', zone: 'B区-圆桌', capacity: 6, status: 'occupied', currentParty: 5, occupiedMinutes: 30, estimatedTurnover: 30 },
  { id: 'B2', label: 'B2', zone: 'B区-圆桌', capacity: 6, status: 'cleaning' },
  { id: 'B3', label: 'B3', zone: 'B区-圆桌', capacity: 8, status: 'available' },
  { id: 'P1', label: '包厢1', zone: '包厢区', capacity: 10, status: 'reserved', customerName: '张总', isVip: true },
  { id: 'P2', label: '包厢2', zone: '包厢区', capacity: 12, status: 'occupied', currentParty: 8, occupiedMinutes: 60, isVip: true },
];

export default function TableBoardPage() {
  const [selectedTable, setSelectedTable] = useState<TableItem | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [zoneFilter, setZoneFilter] = useState<string>('all');

  const zones = [...new Set(MOCK_TABLES.map((t) => t.zone))];
  const filtered = MOCK_TABLES.filter((t) => {
    if (statusFilter !== 'all' && t.status !== statusFilter) return false;
    if (zoneFilter !== 'all' && t.zone !== zoneFilter) return false;
    return true;
  });

  const stats = {
    total: MOCK_TABLES.length,
    available: MOCK_TABLES.filter((t) => t.status === 'available').length,
    occupied: MOCK_TABLES.filter((t) => t.status === 'occupied').length,
    reserved: MOCK_TABLES.filter((t) => t.status === 'reserved').length,
  };

  const openDetail = (table: TableItem) => {
    setSelectedTable(table);
    setDrawerOpen(true);
  };

  const isOvertime = (t: TableItem) => t.status === 'occupied' && (t.occupiedMinutes || 0) > 60;

  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>桌态总览</Title>

      {/* 顶部工具栏 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Row justify="space-between" align="middle">
          <Space>
            <Select
              value={zoneFilter}
              onChange={setZoneFilter}
              style={{ width: 140 }}
              options={[{ value: 'all', label: '全部桌区' }, ...zones.map((z) => ({ value: z, label: z }))]}
            />
            <Select
              value={statusFilter}
              onChange={setStatusFilter}
              style={{ width: 140 }}
              options={[
                { value: 'all', label: '全部状态' },
                ...Object.entries(STATUS_CONFIG).map(([k, v]) => ({ value: k, label: v.label })),
              ]}
            />
            <Input prefix={<SearchOutlined />} placeholder="搜索桌号" style={{ width: 140 }} />
          </Space>
          <Space>
            <Statistic title="空闲" value={stats.available} valueStyle={{ fontSize: 16, color: '#0F6E56' }} />
            <Statistic title="用餐" value={stats.occupied} valueStyle={{ fontSize: 16, color: '#FF6B35' }} />
            <Statistic title="预订" value={stats.reserved} valueStyle={{ fontSize: 16, color: '#185FA5' }} />
          </Space>
        </Row>
      </Card>

      {/* 桌态主画布 */}
      <Row gutter={16}>
        <Col span={drawerOpen ? 16 : 24}>
          <Card size="small">
            {zones.map((zone) => {
              const zoneTables = filtered.filter((t) => t.zone === zone);
              if (zoneTables.length === 0) return null;
              return (
                <div key={zone} style={{ marginBottom: 16 }}>
                  <Text strong style={{ fontSize: 13, marginBottom: 8, display: 'block' }}>{zone}</Text>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                    {zoneTables.map((t) => {
                      const cfg = STATUS_CONFIG[t.status];
                      const overtime = isOvertime(t);
                      return (
                        <Badge
                          key={t.id}
                          dot={overtime}
                          color="#A32D2D"
                          offset={[-4, 4]}
                        >
                          <div
                            onClick={() => openDetail(t)}
                            style={{
                              width: 90, height: 80, borderRadius: 10,
                              background: cfg.color,
                              color: '#fff', cursor: 'pointer',
                              display: 'flex', flexDirection: 'column',
                              alignItems: 'center', justifyContent: 'center',
                              position: 'relative',
                              animation: overtime ? 'pulse 1.5s infinite' : undefined,
                              boxShadow: selectedTable?.id === t.id ? '0 0 0 3px #FF6B35' : undefined,
                              transition: 'transform 0.15s, box-shadow 0.15s',
                            }}
                          >
                            <Text style={{ color: '#fff', fontWeight: 700, fontSize: 15 }}>{t.label}</Text>
                            <Text style={{ color: 'rgba(255,255,255,0.8)', fontSize: 11 }}>
                              {t.currentParty ? `${t.currentParty}人` : `${t.capacity}座`}
                            </Text>
                            {t.occupiedMinutes !== undefined && (
                              <Text style={{ color: 'rgba(255,255,255,0.7)', fontSize: 10 }}>
                                {t.occupiedMinutes}分钟
                              </Text>
                            )}
                            {t.isVip && (
                              <div style={{
                                position: 'absolute', top: 2, right: 4,
                                fontSize: 10, color: '#FFD700', fontWeight: 700,
                              }}>VIP</div>
                            )}
                          </div>
                        </Badge>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </Card>

          {/* 底部事件栏 */}
          <Card size="small" style={{ marginTop: 12 }} title="最近动态">
            <List
              size="small"
              dataSource={[
                { time: '14:25', event: 'A2桌 结账完成，进入清台', type: 'info' },
                { time: '14:22', event: 'B2桌 用餐超时80分钟', type: 'warning' },
                { time: '14:20', event: '包厢1 VIP张总预订确认', type: 'success' },
              ]}
              renderItem={(item) => (
                <List.Item>
                  <Text type="secondary" style={{ fontSize: 11 }}>{item.time}</Text>
                  <Text style={{ marginLeft: 8, fontSize: 12 }}>{item.event}</Text>
                </List.Item>
              )}
            />
          </Card>
        </Col>

        {/* 右侧详情抽屉 */}
        {drawerOpen && selectedTable && (
          <Col span={8}>
            <Card
              size="small"
              title={`${selectedTable.label} 详情`}
              extra={<Button size="small" type="text" onClick={() => setDrawerOpen(false)}>关闭</Button>}
            >
              <Descriptions column={1} size="small">
                <Descriptions.Item label="状态">
                  <Tag color={STATUS_CONFIG[selectedTable.status]?.color}>
                    {STATUS_CONFIG[selectedTable.status]?.label}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="桌区">{selectedTable.zone}</Descriptions.Item>
                <Descriptions.Item label="座位数">{selectedTable.capacity}</Descriptions.Item>
                {selectedTable.currentParty && (
                  <Descriptions.Item label="当前人数">{selectedTable.currentParty}</Descriptions.Item>
                )}
                {selectedTable.customerName && (
                  <Descriptions.Item label="顾客">
                    {selectedTable.isVip && <Tag color="gold">VIP</Tag>}
                    {selectedTable.customerName}
                  </Descriptions.Item>
                )}
                {selectedTable.occupiedMinutes !== undefined && (
                  <Descriptions.Item label="用餐时间">
                    <Text style={{ color: isOvertime(selectedTable) ? '#A32D2D' : '#2C2C2A' }}>
                      {selectedTable.occupiedMinutes} 分钟
                    </Text>
                  </Descriptions.Item>
                )}
                {selectedTable.estimatedTurnover !== undefined && (
                  <Descriptions.Item label="预计翻台">约 {selectedTable.estimatedTurnover} 分钟</Descriptions.Item>
                )}
              </Descriptions>

              <Divider style={{ margin: '12px 0' }} />
              <Text strong style={{ fontSize: 13 }}>推荐动作</Text>
              <Space direction="vertical" style={{ width: '100%', marginTop: 8 }}>
                {selectedTable.status === 'available' && <Button block icon={<UserOutlined />}>入座开台</Button>}
                {selectedTable.status === 'occupied' && <Button block icon={<CoffeeOutlined />}>催菜</Button>}
                {selectedTable.status === 'occupied' && <Button block icon={<MergeCellsOutlined />}>并台</Button>}
                {selectedTable.status === 'occupied' && <Button block icon={<ScissorOutlined />}>拆台</Button>}
                {selectedTable.status === 'cleaning' && <Button block icon={<SwapOutlined />}>标记完成</Button>}
              </Space>
            </Card>
          </Col>
        )}
      </Row>

      {/* 超时桌脉冲动画 */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.7; }
        }
      `}</style>
    </div>
  );
}
