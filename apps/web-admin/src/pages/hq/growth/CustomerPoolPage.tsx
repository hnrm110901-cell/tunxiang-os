/**
 * CustomerPoolPage — 客户总池
 * 路由: /hq/growth/customers
 * 左侧快速分组 + 右侧客户列表 + 底部批量操作
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Card, Table, Tag, Button, Drawer, Select, Input, Space, Row, Col,
  Descriptions, message, Spin,
} from 'antd';
import { SearchOutlined, TeamOutlined, UserOutlined } from '@ant-design/icons';
import { txFetch } from '../../../api';

// ---- 颜色常量 ----
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

// ---- 类型 ----
interface CustomerRow {
  customer_id: string;
  display_name: string;
  level: string;
  last_order_at: string | null;
  order_count_30d: number;
  primary_store_name: string | null;
  source_channel: string | null;
  stored_value_balance_fen: number;
  repurchase_stage: string | null;
  recommended_action: string | null;
}

interface CustomerListResp {
  items: CustomerRow[];
  total: number;
}

// ---- 快速分组配置 ----
const QUICK_GROUPS = [
  { key: 'all', label: '全部客户', icon: '👥', filter: {} },
  { key: 'new', label: '新客（首单30天内）', icon: '🆕', filter: { repurchase_stage: 'first_order' } },
  { key: 'silent', label: '沉默客（>60天未消费）', icon: '😴', filter: { repurchase_stage: 'silent' } },
  { key: 'high_value', label: '高价值客户', icon: '💎', filter: { level: 'S1,S2' } },
  { key: 'repairing', label: '修复中', icon: '🔧', filter: { service_repair_status: 'in_progress' } },
  { key: 'banquet', label: '宴席客', icon: '🎉', filter: { tag: 'banquet' } },
];

const STAGE_TAG_MAP: Record<string, { color: string; label: string }> = {
  first_order: { color: 'blue', label: '首单' },
  second_order: { color: 'cyan', label: '二单' },
  active: { color: 'green', label: '活跃' },
  silent: { color: 'orange', label: '沉默' },
  lapsed: { color: 'red', label: '流失' },
  reactivated: { color: 'purple', label: '已激活' },
};

const LEVEL_COLORS: Record<string, string> = {
  S1: 'gold', S2: 'purple', S3: 'blue', S4: 'cyan', S5: 'default',
};

// ---- 组件 ----
export function CustomerPoolPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [customers, setCustomers] = useState<CustomerRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [activeGroup, setActiveGroup] = useState('all');
  const [searchText, setSearchText] = useState('');
  const [filterStage, setFilterStage] = useState<string | undefined>();
  const [filterLevel, setFilterLevel] = useState<string | undefined>();
  const [filterChannel, setFilterChannel] = useState<string | undefined>();
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerCustomer, setDrawerCustomer] = useState<CustomerRow | null>(null);

  const fetchCustomers = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = { page: String(page), size: String(pageSize) };
      if (searchText) params.search = searchText;
      if (filterStage) params.repurchase_stage = filterStage;
      if (filterLevel) params.level = filterLevel;
      if (filterChannel) params.source_channel = filterChannel;
      // 快速分组filter
      const groupDef = QUICK_GROUPS.find((g) => g.key === activeGroup);
      if (groupDef) {
        Object.entries(groupDef.filter).forEach(([k, v]) => { params[k] = v; });
      }
      const qs = new URLSearchParams(params).toString();
      const resp = await txFetch<CustomerListResp>(`/api/v1/member/customers?${qs}`);
      if (resp.data) {
        setCustomers(resp.data.items);
        setTotal(resp.data.total);
      }
    } catch (err) {
      console.error('fetch customers error', err);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, searchText, filterStage, filterLevel, filterChannel, activeGroup]);

  useEffect(() => { fetchCustomers(); }, [fetchCustomers]);

  const handleRowClick = (record: CustomerRow) => {
    setDrawerCustomer(record);
    setDrawerOpen(true);
  };

  const columns = [
    {
      title: '客户名', dataIndex: 'display_name', key: 'display_name', width: 140,
      render: (text: string) => <span style={{ color: TEXT_PRIMARY, fontWeight: 500 }}>{text || '匿名'}</span>,
    },
    {
      title: '等级', dataIndex: 'level', key: 'level', width: 80,
      render: (val: string) => <Tag color={LEVEL_COLORS[val] || 'default'}>{val}</Tag>,
    },
    {
      title: '最近消费', dataIndex: 'last_order_at', key: 'last_order_at', width: 120,
      render: (val: string | null) => (
        <span style={{ color: TEXT_SECONDARY }}>{val ? val.slice(0, 10) : '-'}</span>
      ),
    },
    {
      title: '30天频次', dataIndex: 'order_count_30d', key: 'order_count_30d', width: 90,
      render: (val: number) => (
        <span style={{ color: val >= 3 ? SUCCESS_GREEN : val >= 1 ? TEXT_PRIMARY : TEXT_SECONDARY }}>
          {val}次
        </span>
      ),
    },
    {
      title: '常去门店', dataIndex: 'primary_store_name', key: 'primary_store_name', width: 120,
      render: (val: string | null) => <span style={{ color: TEXT_SECONDARY }}>{val || '-'}</span>,
    },
    {
      title: '渠道', dataIndex: 'source_channel', key: 'source_channel', width: 90,
      render: (val: string | null) => <Tag>{val || '未知'}</Tag>,
    },
    {
      title: '储值余额', dataIndex: 'stored_value_balance_fen', key: 'balance', width: 100,
      render: (val: number) => (
        <span style={{ color: val > 0 ? SUCCESS_GREEN : TEXT_SECONDARY }}>
          {val > 0 ? `¥${(val / 100).toFixed(0)}` : '-'}
        </span>
      ),
    },
    {
      title: '生命阶段', dataIndex: 'repurchase_stage', key: 'repurchase_stage', width: 90,
      render: (val: string | null) => {
        const cfg = val ? STAGE_TAG_MAP[val] : null;
        return cfg ? <Tag color={cfg.color}>{cfg.label}</Tag> : <span style={{ color: TEXT_SECONDARY }}>-</span>;
      },
    },
    {
      title: '推荐动作', dataIndex: 'recommended_action', key: 'recommended_action', width: 130,
      render: (val: string | null) =>
        val ? <Tag color="orange">{val}</Tag> : <span style={{ color: TEXT_SECONDARY }}>-</span>,
    },
  ];

  return (
    <div style={{ padding: 24, background: PAGE_BG, minHeight: '100vh' }}>
      <h2 style={{ color: TEXT_PRIMARY, marginBottom: 24 }}>客户总池</h2>

      <Row gutter={16}>
        {/* 左侧快速分组 */}
        <Col span={4}>
          <Card style={{ background: CARD_BG, border: `1px solid ${BORDER}` }} bodyStyle={{ padding: 8 }}>
            <div style={{ fontSize: 12, color: TEXT_SECONDARY, padding: '8px 12px', fontWeight: 600 }}>
              快速分组
            </div>
            {QUICK_GROUPS.map((g) => (
              <div
                key={g.key}
                onClick={() => { setActiveGroup(g.key); setPage(1); }}
                style={{
                  padding: '10px 12px', borderRadius: 6, cursor: 'pointer', fontSize: 13,
                  display: 'flex', alignItems: 'center', gap: 8,
                  background: activeGroup === g.key ? 'rgba(255,107,53,0.15)' : 'transparent',
                  color: activeGroup === g.key ? BRAND_ORANGE : TEXT_PRIMARY,
                  transition: 'background 0.15s',
                }}
              >
                <span>{g.icon}</span>
                <span>{g.label}</span>
              </div>
            ))}
          </Card>
        </Col>

        {/* 右侧主体 */}
        <Col span={20}>
          {/* 搜索筛选条 */}
          <Card
            style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 16 }}
            bodyStyle={{ padding: '12px 16px' }}
          >
            <Space wrap size={12}>
              <Input
                placeholder="搜索姓名/手机号"
                prefix={<SearchOutlined style={{ color: TEXT_SECONDARY }} />}
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                onPressEnter={() => { setPage(1); fetchCustomers(); }}
                style={{ width: 200, background: '#0d1e28', borderColor: BORDER }}
                allowClear
              />
              <Select
                placeholder="生命周期"
                value={filterStage}
                onChange={(v) => { setFilterStage(v); setPage(1); }}
                allowClear
                style={{ width: 130 }}
                options={Object.entries(STAGE_TAG_MAP).map(([k, v]) => ({ value: k, label: v.label }))}
              />
              <Select
                placeholder="价值层级"
                value={filterLevel}
                onChange={(v) => { setFilterLevel(v); setPage(1); }}
                allowClear
                style={{ width: 130 }}
                options={['S1', 'S2', 'S3', 'S4', 'S5'].map((s) => ({ value: s, label: s }))}
              />
              <Select
                placeholder="渠道来源"
                value={filterChannel}
                onChange={(v) => { setFilterChannel(v); setPage(1); }}
                allowClear
                style={{ width: 130 }}
                options={['微信', '抖音', '美团', '堂食', '企微'].map((c) => ({ value: c, label: c }))}
              />
            </Space>
          </Card>

          {/* 客户列表 */}
          <Card style={{ background: CARD_BG, border: `1px solid ${BORDER}` }} bodyStyle={{ padding: 0 }}>
            <Table
              loading={loading}
              dataSource={customers}
              columns={columns}
              rowKey="customer_id"
              size="small"
              onRow={(record) => ({
                onClick: () => handleRowClick(record),
                style: { cursor: 'pointer' },
              })}
              rowSelection={{
                selectedRowKeys,
                onChange: (keys) => setSelectedRowKeys(keys as string[]),
              }}
              pagination={{
                current: page,
                pageSize,
                total,
                onChange: (p) => setPage(p),
                showTotal: (t) => `共 ${t} 位客户`,
                size: 'small',
              }}
              scroll={{ x: 1100 }}
            />
          </Card>

          {/* 批量操作条 */}
          {selectedRowKeys.length > 0 && (
            <Card
              style={{
                background: CARD_BG, border: `1px solid ${BRAND_ORANGE}`, marginTop: 12,
              }}
              bodyStyle={{ padding: '10px 16px', display: 'flex', alignItems: 'center', gap: 12 }}
            >
              <span style={{ color: TEXT_PRIMARY, fontSize: 13 }}>
                已选 <span style={{ color: BRAND_ORANGE, fontWeight: 600 }}>{selectedRowKeys.length}</span> 位客户
              </span>
              <Button size="small" type="primary" style={{ background: BRAND_ORANGE, borderColor: BRAND_ORANGE }}>
                加入人群包
              </Button>
              <Button size="small" style={{ borderColor: INFO_BLUE, color: INFO_BLUE }}>
                发起旅程
              </Button>
              <Button size="small" style={{ borderColor: SUCCESS_GREEN, color: SUCCESS_GREEN }}>
                交给Agent
              </Button>
            </Card>
          )}
        </Col>
      </Row>

      {/* 客户快览Drawer */}
      <Drawer
        title={
          <span style={{ color: TEXT_PRIMARY }}>
            <UserOutlined style={{ marginRight: 8 }} />
            {drawerCustomer?.display_name || '客户详情'}
          </span>
        }
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={420}
        styles={{
          header: { background: CARD_BG, borderBottom: `1px solid ${BORDER}` },
          body: { background: PAGE_BG, padding: 16 },
        }}
      >
        {drawerCustomer && (
          <div>
            <Descriptions
              column={1}
              size="small"
              labelStyle={{ color: TEXT_SECONDARY }}
              contentStyle={{ color: TEXT_PRIMARY }}
            >
              <Descriptions.Item label="客户ID">{drawerCustomer.customer_id}</Descriptions.Item>
              <Descriptions.Item label="等级">
                <Tag color={LEVEL_COLORS[drawerCustomer.level] || 'default'}>{drawerCustomer.level}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="生命阶段">
                {drawerCustomer.repurchase_stage
                  ? <Tag color={STAGE_TAG_MAP[drawerCustomer.repurchase_stage]?.color}>
                      {STAGE_TAG_MAP[drawerCustomer.repurchase_stage]?.label}
                    </Tag>
                  : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="最近消费">{drawerCustomer.last_order_at?.slice(0, 10) || '-'}</Descriptions.Item>
              <Descriptions.Item label="30天频次">{drawerCustomer.order_count_30d}次</Descriptions.Item>
              <Descriptions.Item label="常去门店">{drawerCustomer.primary_store_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="储值余额">
                {drawerCustomer.stored_value_balance_fen > 0
                  ? `¥${(drawerCustomer.stored_value_balance_fen / 100).toFixed(0)}`
                  : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="推荐动作">
                {drawerCustomer.recommended_action
                  ? <Tag color="orange">{drawerCustomer.recommended_action}</Tag>
                  : '-'}
              </Descriptions.Item>
            </Descriptions>

            <div style={{ marginTop: 24, textAlign: 'center' }}>
              <Button
                type="primary"
                style={{ background: BRAND_ORANGE, borderColor: BRAND_ORANGE }}
                onClick={() => navigate(`/hq/growth/customers/${drawerCustomer.customer_id}`)}
              >
                进入360详情
              </Button>
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
