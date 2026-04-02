/**
 * 宴席菜单管理页
 * 域A 交易履约 · 宴席菜单档次管理
 *
 * 功能：
 * 1. 顶部今日场次概览：宴席数/总桌数/总人数/进行中场次
 * 2. Table展示宴席菜单档次：菜单名/档次/人均价格/最少人数/最少桌数/是否启用/有效期/操作
 * 3. ModalForm 创建菜单档次（POST /api/v1/menu/banquet-menus）
 * 4. 查看详情 Drawer：按节展示完整菜单，可添加分节和分节内菜品
 * 5. 停用操作
 *
 * 技术栈：antd 5.x + React 18 TypeScript strict
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  Collapse,
  DatePicker,
  Drawer,
  Form,
  Input,
  InputNumber,
  List,
  message,
  Modal,
  Popconfirm,
  Row,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  AppstoreAddOutlined,
  PlusOutlined,
  ReloadOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { txFetch } from '../../../api';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;
const { Panel } = Collapse;

// ─── Design Token ─────────────────────────────────────────────────────────────
const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_WARNING = '#BA7517';
const TX_BG_HEADER = '#F8F7F5';

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

interface BanquetMenu {
  id: string;
  menu_name: string;
  tier_name: string;
  per_person_price_fen: number;
  min_persons: number;
  min_tables: number;
  is_active: boolean;
  valid_from: string;
  valid_until: string;
  section_count: number;
}

interface MenuSection {
  id: string;
  section_name: string;
  sort_order: number;
  items: SectionItem[];
}

interface SectionItem {
  id: string;
  dish_id: string;
  dish_name: string;
  qty: number;
  note: string;
}

interface BanquetMenuDetail extends BanquetMenu {
  sections: MenuSection[];
}

interface BanquetSession {
  id: string;
  banquet_date: string;
  menu_name: string;
  table_count: number;
  person_count: number;
  status: 'upcoming' | 'in_progress' | 'completed' | 'cancelled';
  store_name: string;
}

interface TodaySessionStats {
  total_banquets: number;
  total_tables: number;
  total_persons: number;
  in_progress_count: number;
}

// ─── API 函数 ─────────────────────────────────────────────────────────────────

async function fetchBanquetMenus(page = 1, size = 20): Promise<{ items: BanquetMenu[]; total: number }> {
  return txFetch(`/api/v1/menu/banquet-menus?page=${page}&size=${size}`);
}

async function fetchBanquetMenuDetail(id: string): Promise<BanquetMenuDetail> {
  return txFetch(`/api/v1/menu/banquet-menus/${id}`);
}

async function createBanquetMenu(payload: Omit<BanquetMenu, 'id' | 'section_count'>): Promise<BanquetMenu> {
  return txFetch('/api/v1/menu/banquet-menus', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

async function toggleBanquetMenu(id: string, isActive: boolean): Promise<void> {
  return txFetch(`/api/v1/menu/banquet-menus/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ is_active: isActive }),
  });
}

async function addMenuSection(menuId: string, payload: { section_name: string; sort_order: number }): Promise<MenuSection> {
  return txFetch(`/api/v1/menu/banquet-menus/${menuId}/sections`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

async function addSectionItem(
  menuId: string,
  sectionId: string,
  payload: { dish_id: string; dish_name: string; qty: number; note?: string },
): Promise<SectionItem> {
  return txFetch(`/api/v1/menu/banquet-menus/${menuId}/sections/${sectionId}/items`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

async function fetchTodaySessions(): Promise<{ items: BanquetSession[]; total: number }> {
  const today = dayjs().format('YYYY-MM-DD');
  return txFetch(`/api/v1/menu/banquet-sessions?date=${today}`);
}

// ─── 今日场次统计卡片 ─────────────────────────────────────────────────────────

interface SessionStatsCardsProps {
  sessions: BanquetSession[];
  loading: boolean;
}

const SessionStatsCards: React.FC<SessionStatsCardsProps> = ({ sessions, loading }) => {
  const stats: TodaySessionStats = {
    total_banquets: sessions.length,
    total_tables: sessions.reduce((s, x) => s + x.table_count, 0),
    total_persons: sessions.reduce((s, x) => s + x.person_count, 0),
    in_progress_count: sessions.filter((x) => x.status === 'in_progress').length,
  };

  const cards = [
    { title: '今日宴席数', value: stats.total_banquets, suffix: '场', color: TX_PRIMARY },
    { title: '总桌数', value: stats.total_tables, suffix: '桌', color: '#1677ff' },
    { title: '总人数', value: stats.total_persons, suffix: '人', color: TX_SUCCESS },
    {
      title: '进行中场次',
      value: stats.in_progress_count,
      suffix: '场',
      color: stats.in_progress_count > 0 ? TX_WARNING : '#999',
    },
  ];

  return (
    <Row gutter={16} style={{ marginBottom: 24 }}>
      {cards.map((card) => (
        <Col span={6} key={card.title}>
          <Card
            loading={loading}
            style={{ borderRadius: 6 }}
            styles={{ body: { padding: '16px 20px', background: TX_BG_HEADER } }}
          >
            <Statistic
              title={<Text type="secondary">{card.title}</Text>}
              value={card.value}
              suffix={card.suffix}
              valueStyle={{ color: card.color, fontSize: 28, fontWeight: 700 }}
            />
          </Card>
        </Col>
      ))}
    </Row>
  );
};

// ─── 菜单详情 Drawer ──────────────────────────────────────────────────────────

interface MenuDetailDrawerProps {
  menuId: string | null;
  open: boolean;
  onClose: () => void;
}

const MenuDetailDrawer: React.FC<MenuDetailDrawerProps> = ({ menuId, open, onClose }) => {
  const [detail, setDetail] = useState<BanquetMenuDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [addSectionModalOpen, setAddSectionModalOpen] = useState(false);
  const [addItemModalOpen, setAddItemModalOpen] = useState(false);
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null);
  const [sectionForm] = Form.useForm();
  const [itemForm] = Form.useForm();
  const [sectionLoading, setSectionLoading] = useState(false);
  const [itemLoading, setItemLoading] = useState(false);

  const loadDetail = useCallback(async () => {
    if (!menuId) return;
    setLoading(true);
    try {
      const d = await fetchBanquetMenuDetail(menuId);
      setDetail(d);
    } catch {
      message.error('加载菜单详情失败');
    } finally {
      setLoading(false);
    }
  }, [menuId]);

  useEffect(() => {
    if (open && menuId) loadDetail();
  }, [open, menuId, loadDetail]);

  const handleAddSection = async (values: Record<string, unknown>) => {
    if (!menuId) return;
    setSectionLoading(true);
    try {
      await addMenuSection(menuId, {
        section_name: values.section_name as string,
        sort_order: values.sort_order as number,
      });
      message.success('分节添加成功');
      sectionForm.resetFields();
      setAddSectionModalOpen(false);
      loadDetail();
    } catch {
      message.error('添加分节失败');
    } finally {
      setSectionLoading(false);
    }
  };

  const handleAddItem = async (values: Record<string, unknown>) => {
    if (!menuId || !activeSectionId) return;
    setItemLoading(true);
    try {
      await addSectionItem(menuId, activeSectionId, {
        dish_id: values.dish_id as string,
        dish_name: values.dish_name as string,
        qty: values.qty as number,
        note: values.note as string | undefined,
      });
      message.success('菜品添加成功');
      itemForm.resetFields();
      setAddItemModalOpen(false);
      loadDetail();
    } catch {
      message.error('添加菜品失败');
    } finally {
      setItemLoading(false);
    }
  };

  return (
    <>
      <Drawer
        title={detail ? `${detail.menu_name}（${detail.tier_name}）` : '菜单详情'}
        width={640}
        open={open}
        onClose={onClose}
        loading={loading}
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            size="small"
            style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
            onClick={() => setAddSectionModalOpen(true)}
          >
            添加分节
          </Button>
        }
      >
        {detail && (
          <>
            {/* 菜单基本信息 */}
            <Card
              size="small"
              style={{ marginBottom: 16, background: TX_BG_HEADER }}
            >
              <Row gutter={16}>
                <Col span={8}>
                  <Text type="secondary">人均价格</Text>
                  <div style={{ fontWeight: 700, color: TX_PRIMARY }}>
                    ¥{(detail.per_person_price_fen / 100).toFixed(0)}
                  </div>
                </Col>
                <Col span={8}>
                  <Text type="secondary">最少人数</Text>
                  <div style={{ fontWeight: 600 }}>{detail.min_persons} 人</div>
                </Col>
                <Col span={8}>
                  <Text type="secondary">最少桌数</Text>
                  <div style={{ fontWeight: 600 }}>{detail.min_tables} 桌</div>
                </Col>
              </Row>
            </Card>

            {/* 分节展示 */}
            {detail.sections.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '40px 0', color: '#999' }}>
                暂无分节，请点击右上角「添加分节」
              </div>
            ) : (
              <Collapse defaultActiveKey={detail.sections.map((s) => s.id)}>
                {detail.sections
                  .sort((a, b) => a.sort_order - b.sort_order)
                  .map((section) => (
                    <Panel
                      key={section.id}
                      header={
                        <Space>
                          <Text strong>{section.section_name}</Text>
                          <Tag>{section.items.length} 道菜</Tag>
                        </Space>
                      }
                      extra={
                        <Button
                          size="small"
                          type="link"
                          icon={<PlusOutlined />}
                          style={{ color: TX_PRIMARY }}
                          onClick={(e) => {
                            e.stopPropagation();
                            setActiveSectionId(section.id);
                            setAddItemModalOpen(true);
                          }}
                        >
                          加菜
                        </Button>
                      }
                    >
                      <List
                        size="small"
                        dataSource={section.items}
                        renderItem={(item) => (
                          <List.Item key={item.id}>
                            <Space>
                              <Text strong>{item.dish_name}</Text>
                              <Tag color="default">×{item.qty}</Tag>
                              {item.note && <Text type="secondary" style={{ fontSize: 12 }}>{item.note}</Text>}
                            </Space>
                          </List.Item>
                        )}
                        locale={{ emptyText: '本节暂无菜品' }}
                      />
                    </Panel>
                  ))}
              </Collapse>
            )}
          </>
        )}
      </Drawer>

      {/* 添加分节 Modal */}
      <Modal
        title="添加菜单分节"
        open={addSectionModalOpen}
        onCancel={() => { setAddSectionModalOpen(false); sectionForm.resetFields(); }}
        onOk={() => sectionForm.submit()}
        confirmLoading={sectionLoading}
        destroyOnClose
      >
        <Form form={sectionForm} layout="vertical" onFinish={handleAddSection} style={{ marginTop: 16 }}>
          <Form.Item name="section_name" label="分节名称" rules={[{ required: true }]}>
            <Input placeholder="如：凉菜、热菜、汤品、主食" />
          </Form.Item>
          <Form.Item name="sort_order" label="排序序号" rules={[{ required: true }]} initialValue={1}>
            <InputNumber style={{ width: '100%' }} min={1} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 添加菜品 Modal */}
      <Modal
        title="向分节添加菜品"
        open={addItemModalOpen}
        onCancel={() => { setAddItemModalOpen(false); itemForm.resetFields(); }}
        onOk={() => itemForm.submit()}
        confirmLoading={itemLoading}
        destroyOnClose
      >
        <Form form={itemForm} layout="vertical" onFinish={handleAddItem} style={{ marginTop: 16 }}>
          <Form.Item name="dish_id" label="菜品ID" rules={[{ required: true }]}>
            <Input placeholder="输入菜品ID" />
          </Form.Item>
          <Form.Item name="dish_name" label="菜品名称" rules={[{ required: true }]}>
            <Input placeholder="菜品名称" />
          </Form.Item>
          <Form.Item name="qty" label="数量" rules={[{ required: true }]} initialValue={1}>
            <InputNumber style={{ width: '100%' }} min={1} />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input placeholder="如：例份、大份、选一" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
};

// ─── 创建菜单 Modal ───────────────────────────────────────────────────────────

interface CreateMenuModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

const CreateMenuModal: React.FC<CreateMenuModalProps> = ({ open, onClose, onSuccess }) => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  const handleFinish = async (values: Record<string, unknown>) => {
    setLoading(true);
    try {
      const dateRange = values.date_range as [dayjs.Dayjs, dayjs.Dayjs];
      await createBanquetMenu({
        menu_name: values.menu_name as string,
        tier_name: values.tier_name as string,
        per_person_price_fen: Math.round((values.per_person_price as number) * 100),
        min_persons: values.min_persons as number,
        min_tables: values.min_tables as number,
        is_active: true,
        valid_from: dateRange[0].format('YYYY-MM-DD'),
        valid_until: dateRange[1].format('YYYY-MM-DD'),
      });
      message.success('宴席菜单档次创建成功');
      form.resetFields();
      onSuccess();
      onClose();
    } catch {
      message.error('创建失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title="新建宴席菜单档次"
      open={open}
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={loading}
      width={560}
      destroyOnClose
    >
      <Form form={form} layout="vertical" onFinish={handleFinish} style={{ marginTop: 16 }}>
        <Row gutter={12}>
          <Col span={14}>
            <Form.Item name="menu_name" label="菜单名称" rules={[{ required: true }]}>
              <Input placeholder="如：满汉全席·金尊版" />
            </Form.Item>
          </Col>
          <Col span={10}>
            <Form.Item name="tier_name" label="档次名称" rules={[{ required: true }]}>
              <Input placeholder="如：尊享档" />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item
          name="per_person_price"
          label="人均价格（元）"
          rules={[{ required: true }, { type: 'number', min: 1 }]}
        >
          <InputNumber style={{ width: '100%' }} min={1} precision={0} prefix="¥" />
        </Form.Item>
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item name="min_persons" label="最少人数" rules={[{ required: true }]} initialValue={10}>
              <InputNumber style={{ width: '100%' }} min={1} suffix="人" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="min_tables" label="最少桌数" rules={[{ required: true }]} initialValue={1}>
              <InputNumber style={{ width: '100%' }} min={1} suffix="桌" />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item
          name="date_range"
          label="有效期"
          rules={[{ required: true, message: '请选择有效期' }]}
        >
          <RangePicker style={{ width: '100%' }} />
        </Form.Item>
      </Form>
    </Modal>
  );
};

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function BanquetMenuPage() {
  const [menus, setMenus] = useState<BanquetMenu[]>([]);
  const [sessions, setSessions] = useState<BanquetSession[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [sessionsLoading, setSessionsLoading] = useState(false);

  // Modal / Drawer 状态
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [detailDrawerOpen, setDetailDrawerOpen] = useState(false);
  const [selectedMenuId, setSelectedMenuId] = useState<string | null>(null);

  const loadMenus = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchBanquetMenus(page, pageSize);
      setMenus(res.items);
      setTotal(res.total);
    } catch {
      message.error('加载宴席菜单失败');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize]);

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true);
    try {
      const res = await fetchTodaySessions();
      setSessions(res.items);
    } catch {
      // 静默失败
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMenus();
    loadSessions();
  }, [loadMenus, loadSessions]);

  const handleToggleActive = async (menu: BanquetMenu, checked: boolean) => {
    try {
      await toggleBanquetMenu(menu.id, checked);
      message.success(`「${menu.menu_name}」已${checked ? '启用' : '停用'}`);
      loadMenus();
    } catch {
      message.error('操作失败');
    }
  };

  const handleDeactivate = async (menu: BanquetMenu) => {
    try {
      await toggleBanquetMenu(menu.id, false);
      message.success(`「${menu.menu_name}」已停用`);
      loadMenus();
    } catch {
      message.error('停用失败');
    }
  };

  const columns: ColumnsType<BanquetMenu> = [
    {
      title: '菜单名称',
      dataIndex: 'menu_name',
      width: 180,
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: '档次',
      dataIndex: 'tier_name',
      width: 100,
      render: (tier: string) => <Tag color="gold">{tier}</Tag>,
    },
    {
      title: '人均价格',
      dataIndex: 'per_person_price_fen',
      width: 110,
      sorter: (a, b) => a.per_person_price_fen - b.per_person_price_fen,
      render: (fen: number) => (
        <Text style={{ color: TX_PRIMARY, fontWeight: 600 }}>
          ¥{(fen / 100).toFixed(0)}
        </Text>
      ),
    },
    {
      title: '最少人数',
      dataIndex: 'min_persons',
      width: 90,
      render: (v: number) => `${v} 人`,
    },
    {
      title: '最少桌数',
      dataIndex: 'min_tables',
      width: 90,
      render: (v: number) => `${v} 桌`,
    },
    {
      title: '分节数',
      dataIndex: 'section_count',
      width: 80,
      render: (v: number) => <Badge count={v} showZero color="#1677ff" />,
    },
    {
      title: '是否启用',
      dataIndex: 'is_active',
      width: 90,
      render: (active: boolean, record) => (
        <Switch
          checked={active}
          size="small"
          onChange={(checked) => handleToggleActive(record, checked)}
          checkedChildren="启用"
          unCheckedChildren="停用"
        />
      ),
    },
    {
      title: '有效期',
      key: 'validity',
      width: 180,
      render: (_, record) => {
        const from = dayjs(record.valid_from).format('MM/DD');
        const until = dayjs(record.valid_until).format('MM/DD/YYYY');
        const expired = dayjs().isAfter(dayjs(record.valid_until));
        return (
          <Space>
            <Text type={expired ? 'danger' : 'secondary'} style={{ fontSize: 12 }}>
              {from} ~ {until}
            </Text>
            {expired && <Tag color="red" style={{ fontSize: 11 }}>已过期</Tag>}
          </Space>
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      fixed: 'right',
      width: 160,
      render: (_, record) => (
        <Space size={0}>
          <Button
            type="link"
            size="small"
            icon={<UnorderedListOutlined />}
            onClick={() => {
              setSelectedMenuId(record.id);
              setDetailDrawerOpen(true);
            }}
            style={{ color: TX_PRIMARY, paddingLeft: 0 }}
          >
            查看详情
          </Button>
          <Button type="link" size="small" style={{ color: '#1677ff' }}>
            编辑
          </Button>
          {record.is_active && (
            <Popconfirm
              title="确认停用此菜单档次？"
              description="停用后该档次将不可预订"
              onConfirm={() => handleDeactivate(record)}
              okText="确认停用"
              cancelText="取消"
              okButtonProps={{ danger: true }}
            >
              <Button type="link" size="small" danger>
                停用
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ minWidth: 1280 }}>
      {/* 页面标题 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>宴席菜单管理</Title>
          <Text type="secondary" style={{ fontSize: 13 }}>管理宴席菜单档次、菜品分节与今日宴席场次</Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => { loadMenus(); loadSessions(); }}>
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateModalOpen(true)}
            style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
          >
            新建档次
          </Button>
        </Space>
      </div>

      {/* 今日场次概览 */}
      <Card
        title={
          <Space>
            <AppstoreAddOutlined style={{ color: TX_PRIMARY }} />
            <Text strong>今日场次概览</Text>
          </Space>
        }
        size="small"
        style={{ marginBottom: 20 }}
        extra={
          <Text type="secondary" style={{ fontSize: 12 }}>
            {dayjs().format('YYYY年MM月DD日')}
          </Text>
        }
      >
        <SessionStatsCards sessions={sessions} loading={sessionsLoading} />

        {/* 今日场次列表 */}
        {sessions.length > 0 && (
          <Table
            size="small"
            rowKey="id"
            dataSource={sessions}
            pagination={false}
            columns={[
              { title: '菜单档次', dataIndex: 'menu_name', width: 160 },
              { title: '门店', dataIndex: 'store_name', width: 140 },
              { title: '桌数', dataIndex: 'table_count', width: 80, render: (v: number) => `${v} 桌` },
              { title: '人数', dataIndex: 'person_count', width: 80, render: (v: number) => `${v} 人` },
              {
                title: '状态',
                dataIndex: 'status',
                width: 100,
                render: (status: BanquetSession['status']) => {
                  const config: Record<BanquetSession['status'], { label: string; color: string }> = {
                    upcoming: { label: '待开始', color: 'blue' },
                    in_progress: { label: '进行中', color: 'green' },
                    completed: { label: '已完成', color: 'default' },
                    cancelled: { label: '已取消', color: 'red' },
                  };
                  return <Tag color={config[status].color}>{config[status].label}</Tag>;
                },
              },
            ]}
          />
        )}
      </Card>

      {/* 菜单档次列表 */}
      <Card styles={{ body: { padding: 0 } }}>
        <Table<BanquetMenu>
          rowKey="id"
          dataSource={menus}
          columns={columns}
          loading={loading}
          scroll={{ x: 1100 }}
          pagination={{
            current: page,
            pageSize,
            total,
            onChange: setPage,
            showSizeChanger: false,
            showTotal: (t) => `共 ${t} 个档次`,
          }}
          size="middle"
        />
      </Card>

      {/* 创建菜单档次 Modal */}
      <CreateMenuModal
        open={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
        onSuccess={loadMenus}
      />

      {/* 菜单详情 Drawer */}
      <MenuDetailDrawer
        menuId={selectedMenuId}
        open={detailDrawerOpen}
        onClose={() => { setDetailDrawerOpen(false); setSelectedMenuId(null); }}
      />
    </div>
  );
}
