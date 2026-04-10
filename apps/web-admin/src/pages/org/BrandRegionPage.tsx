/**
 * 品牌与区域管理 — Admin 总部后台
 * Y-H1 多品牌管理统一 + Y-H2 多区域管理
 *
 * Tab 1: 品牌管理（卡片展示 + 策略配置侧边栏）
 * Tab 2: 区域管理（Tree 层级 + 右侧详情面板）
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Tabs,
  Row,
  Col,
  Card,
  Tag,
  Badge,
  Button,
  Modal,
  Form,
  Input,
  Select,
  Spin,
  Drawer,
  Descriptions,
  Typography,
  Tree,
  Space,
  Statistic,
  message,
  Tooltip,
  InputNumber,
  Divider,
} from 'antd';
import type { TreeDataNode } from 'antd';
import {
  PlusOutlined,
  ShopOutlined,
  BranchesOutlined,
  EnvironmentOutlined,
  EditOutlined,
  ApartmentOutlined,
  GlobalOutlined,
  HomeOutlined,
} from '@ant-design/icons';

const { Title, Text } = Typography;
const { TabPane } = Tabs;

const TENANT_ID = localStorage.getItem('tenantId') || 'demo-tenant';
const HEADERS = { 'X-Tenant-ID': TENANT_ID, 'Content-Type': 'application/json' };

// ── 类型定义 ──────────────────────────────────────────────────────────────────

interface Brand {
  brand_id: string;
  name: string;
  brand_code: string;
  brand_type: string | null;
  logo_url: string | null;
  primary_color: string;
  description: string | null;
  status: string;
  store_count: number;
  region_count: number;
  strategy_config: Record<string, unknown>;
  degraded?: boolean;
}

interface Region {
  region_id: string;
  parent_id: string | null;
  name: string;
  region_code: string | null;
  level: number;
  manager_name: string | null;
  tax_rate: number;
  store_count: number;
  child_count: number;
  is_active: boolean;
  children?: Region[];
}

// ── 工具函数 ──────────────────────────────────────────────────────────────────

const BRAND_TYPE_LABELS: Record<string, string> = {
  seafood: '海鲜',
  hotpot: '火锅',
  canteen: '食堂',
  quick_service: '快餐',
  banquet: '宴席',
};

const BRAND_TYPE_COLORS: Record<string, string> = {
  seafood: 'blue',
  hotpot: 'red',
  canteen: 'green',
  quick_service: 'orange',
  banquet: 'purple',
};

function regionToTreeNode(region: Region): TreeDataNode {
  const levelIconMap: Record<number, React.ReactNode> = {
    1: <GlobalOutlined style={{ color: '#FF6B35' }} />,
    2: <ApartmentOutlined style={{ color: '#185FA5' }} />,
    3: <EnvironmentOutlined style={{ color: '#0F6E56' }} />,
  };
  return {
    key: region.region_id,
    title: (
      <Space>
        {levelIconMap[region.level] ?? <EnvironmentOutlined />}
        <span>{region.name}</span>
        <Text type="secondary" style={{ fontSize: 12 }}>
          ({region.store_count} 门店)
        </Text>
      </Space>
    ),
    children: (region.children ?? []).map(regionToTreeNode),
  };
}

// ── 品牌管理 Tab ──────────────────────────────────────────────────────────────

function BrandTab() {
  const [brands, setBrands] = useState<Brand[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedBrand, setSelectedBrand] = useState<Brand | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [strategyEditOpen, setStrategyEditOpen] = useState(false);
  const [strategyText, setStrategyText] = useState('{}');
  const [createForm] = Form.useForm();
  const [savingStrategy, setSavingStrategy] = useState(false);

  const fetchBrands = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/org/brands?size=50', { headers: HEADERS });
      const json = await res.json();
      if (json.ok) {
        setBrands(json.data.items ?? []);
      }
    } catch {
      message.error('加载品牌列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchBrands(); }, [fetchBrands]);

  const handleCardClick = async (brand: Brand) => {
    try {
      const res = await fetch(`/api/v1/org/brands/${brand.brand_id}`, { headers: HEADERS });
      const json = await res.json();
      if (json.ok) {
        setSelectedBrand(json.data);
        setStrategyText(JSON.stringify(json.data.strategy_config ?? {}, null, 2));
        setDrawerOpen(true);
      }
    } catch {
      message.error('加载品牌详情失败');
    }
  };

  const handleCreateBrand = async (values: Record<string, string>) => {
    try {
      const res = await fetch('/api/v1/org/brands', {
        method: 'POST',
        headers: HEADERS,
        body: JSON.stringify(values),
      });
      const json = await res.json();
      if (json.ok) {
        message.success(`品牌「${values.name}」创建成功`);
        createForm.resetFields();
        setCreateModalOpen(false);
        fetchBrands();
      } else {
        message.error(json.error?.detail ?? '创建失败');
      }
    } catch {
      message.error('网络错误');
    }
  };

  const handleSaveStrategy = async () => {
    if (!selectedBrand) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(strategyText);
    } catch {
      message.error('JSON 格式不正确');
      return;
    }
    setSavingStrategy(true);
    try {
      const res = await fetch(`/api/v1/org/brands/${selectedBrand.brand_id}/strategy`, {
        method: 'PUT',
        headers: HEADERS,
        body: JSON.stringify({ strategy_config: parsed }),
      });
      const json = await res.json();
      if (json.ok) {
        message.success('策略配置已保存到DB');
        setSelectedBrand({ ...selectedBrand, strategy_config: parsed });
        setStrategyEditOpen(false);
      } else {
        message.error(json.error?.detail ?? '保存失败');
      }
    } catch {
      message.error('网络错误');
    } finally {
      setSavingStrategy(false);
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={5} style={{ margin: 0 }}>品牌列表</Title>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
          onClick={() => setCreateModalOpen(true)}
        >
          新建品牌
        </Button>
      </div>

      <Spin spinning={loading}>
        <Row gutter={[16, 16]}>
          {brands.map((brand) => (
            <Col key={brand.brand_id} xs={24} sm={12} md={8} lg={6}>
              <Card
                hoverable
                onClick={() => handleCardClick(brand)}
                style={{ cursor: 'pointer', borderRadius: 8 }}
                bodyStyle={{ padding: '16px' }}
              >
                {/* Logo 占位 */}
                <div
                  style={{
                    width: 56,
                    height: 56,
                    borderRadius: 8,
                    background: brand.primary_color || '#FF6B35',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    marginBottom: 12,
                    color: '#fff',
                    fontSize: 22,
                    fontWeight: 700,
                  }}
                >
                  {brand.brand_code?.slice(0, 2) ?? '?'}
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <Text strong style={{ fontSize: 15 }}>{brand.name}</Text>
                  <Badge
                    status={brand.status === 'active' ? 'success' : 'default'}
                    text={brand.status === 'active' ? '运营中' : '停用'}
                    style={{ fontSize: 12 }}
                  />
                </div>

                <div style={{ marginTop: 8 }}>
                  {brand.brand_type && (
                    <Tag color={BRAND_TYPE_COLORS[brand.brand_type] ?? 'default'}>
                      {BRAND_TYPE_LABELS[brand.brand_type] ?? brand.brand_type}
                    </Tag>
                  )}
                  <Tag icon={<ShopOutlined />} color="default" style={{ marginTop: 4 }}>
                    {brand.store_count} 门店
                  </Tag>
                </div>

                {brand.degraded && (
                  <Text type="warning" style={{ fontSize: 11, marginTop: 4, display: 'block' }}>
                    * 降级数据
                  </Text>
                )}
              </Card>
            </Col>
          ))}
          {brands.length === 0 && !loading && (
            <Col span={24}>
              <div style={{ textAlign: 'center', padding: '40px 0', color: '#B4B2A9' }}>
                暂无品牌数据，点击「新建品牌」开始
              </div>
            </Col>
          )}
        </Row>
      </Spin>

      {/* 品牌详情侧边栏 */}
      <Drawer
        title={selectedBrand?.name ?? '品牌详情'}
        width={480}
        open={drawerOpen}
        onClose={() => { setDrawerOpen(false); setStrategyEditOpen(false); }}
      >
        {selectedBrand && (
          <>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="品牌编码">{selectedBrand.brand_code}</Descriptions.Item>
              <Descriptions.Item label="品牌类型">
                <Tag color={BRAND_TYPE_COLORS[selectedBrand.brand_type ?? ''] ?? 'default'}>
                  {BRAND_TYPE_LABELS[selectedBrand.brand_type ?? ''] ?? selectedBrand.brand_type ?? '—'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="门店数">{selectedBrand.store_count}</Descriptions.Item>
              <Descriptions.Item label="区域数">{selectedBrand.region_count}</Descriptions.Item>
              <Descriptions.Item label="状态" span={2}>
                <Badge
                  status={selectedBrand.status === 'active' ? 'success' : 'default'}
                  text={selectedBrand.status === 'active' ? '运营中' : '停用'}
                />
              </Descriptions.Item>
              <Descriptions.Item label="描述" span={2}>
                {selectedBrand.description ?? '—'}
              </Descriptions.Item>
            </Descriptions>

            <Divider orientation="left" style={{ marginTop: 24 }}>
              策略配置
              <Tooltip title="存储在 DB strategy_config JSONB 字段，非内存">
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                  (DB路径)
                </Text>
              </Tooltip>
            </Divider>

            {strategyEditOpen ? (
              <>
                <Input.TextArea
                  rows={10}
                  value={strategyText}
                  onChange={(e) => setStrategyText(e.target.value)}
                  style={{ fontFamily: 'monospace', fontSize: 12 }}
                  placeholder='{"discount_threshold": 0.3, "report_template": "standard"}'
                />
                <div style={{ marginTop: 12, textAlign: 'right' }}>
                  <Space>
                    <Button onClick={() => setStrategyEditOpen(false)}>取消</Button>
                    <Button
                      type="primary"
                      loading={savingStrategy}
                      onClick={handleSaveStrategy}
                      style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
                    >
                      保存到DB
                    </Button>
                  </Space>
                </div>
              </>
            ) : (
              <>
                <pre
                  style={{
                    background: '#F8F7F5',
                    borderRadius: 6,
                    padding: 12,
                    fontSize: 12,
                    maxHeight: 200,
                    overflow: 'auto',
                    margin: 0,
                  }}
                >
                  {JSON.stringify(selectedBrand.strategy_config, null, 2) || '{}'}
                </pre>
                <Button
                  icon={<EditOutlined />}
                  style={{ marginTop: 8 }}
                  onClick={() => {
                    setStrategyText(JSON.stringify(selectedBrand.strategy_config ?? {}, null, 2));
                    setStrategyEditOpen(true);
                  }}
                >
                  编辑策略配置
                </Button>
              </>
            )}
          </>
        )}
      </Drawer>

      {/* 新建品牌 Modal */}
      <Modal
        title="新建品牌"
        open={createModalOpen}
        onCancel={() => { setCreateModalOpen(false); createForm.resetFields(); }}
        onOk={() => createForm.submit()}
        okText="创建"
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={handleCreateBrand}
          style={{ marginTop: 16 }}
        >
          <Form.Item name="name" label="品牌名称" rules={[{ required: true, message: '请输入品牌名称' }]}>
            <Input placeholder="如：徐记海鲜" maxLength={100} />
          </Form.Item>
          <Form.Item name="brand_code" label="品牌编码（留空自动生成）">
            <Input placeholder="如：XJ，最多4位字母" maxLength={4} style={{ textTransform: 'uppercase' }} />
          </Form.Item>
          <Form.Item name="brand_type" label="品牌类型">
            <Select placeholder="选择品牌类型" allowClear>
              <Select.Option value="seafood">海鲜</Select.Option>
              <Select.Option value="hotpot">火锅</Select.Option>
              <Select.Option value="canteen">食堂</Select.Option>
              <Select.Option value="quick_service">快餐</Select.Option>
              <Select.Option value="banquet">宴席</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="primary_color" label="品牌主色" initialValue="#FF6B35">
            <Input type="color" style={{ width: 80, padding: 2 }} />
          </Form.Item>
          <Form.Item name="description" label="品牌描述">
            <Input.TextArea rows={3} placeholder="可选" maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// ── 区域管理 Tab ──────────────────────────────────────────────────────────────

function RegionTab() {
  const [treeData, setTreeData] = useState<TreeDataNode[]>([]);
  const [flatRegions, setFlatRegions] = useState<Region[]>([]);
  const [selectedRegion, setSelectedRegion] = useState<Region | null>(null);
  const [loading, setLoading] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [taxRateModalOpen, setTaxRateModalOpen] = useState(false);
  const [newTaxRate, setNewTaxRate] = useState<number>(0.06);
  const [savingTaxRate, setSavingTaxRate] = useState(false);
  const [createForm] = Form.useForm();

  const fetchRegions = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/org/regions?tree=true', { headers: HEADERS });
      const json = await res.json();
      if (json.ok) {
        const roots: Region[] = json.data.tree ?? [];
        setTreeData(roots.map(regionToTreeNode));
        // 展平用于查找
        const flat: Region[] = [];
        const flatten = (r: Region) => { flat.push(r); (r.children ?? []).forEach(flatten); };
        roots.forEach(flatten);
        setFlatRegions(flat);
      }
    } catch {
      message.error('加载区域树失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchRegions(); }, [fetchRegions]);

  const handleSelectRegion = (selectedKeys: React.Key[]) => {
    if (!selectedKeys.length) { setSelectedRegion(null); return; }
    const regionId = String(selectedKeys[0]);
    const found = flatRegions.find((r) => r.region_id === regionId);
    if (found) {
      setSelectedRegion(found);
      setNewTaxRate(found.tax_rate ?? 0.06);
    }
  };

  const handleCreateRegion = async (values: Record<string, unknown>) => {
    try {
      const res = await fetch('/api/v1/org/regions', {
        method: 'POST',
        headers: HEADERS,
        body: JSON.stringify({
          ...values,
          parent_id: selectedRegion?.region_id ?? null,
          level: selectedRegion ? Math.min((selectedRegion.level ?? 1) + 1, 3) : 1,
          tax_rate: 0.06,
        }),
      });
      const json = await res.json();
      if (json.ok) {
        message.success(`区域「${values.name}」创建成功`);
        createForm.resetFields();
        setCreateModalOpen(false);
        fetchRegions();
      } else {
        message.error(json.error?.detail ?? '创建失败');
      }
    } catch {
      message.error('网络错误');
    }
  };

  const handleSaveTaxRate = async () => {
    if (!selectedRegion) return;
    setSavingTaxRate(true);
    try {
      const res = await fetch(`/api/v1/org/regions/${selectedRegion.region_id}/tax-rate`, {
        method: 'PUT',
        headers: HEADERS,
        body: JSON.stringify({ tax_rate: newTaxRate }),
      });
      const json = await res.json();
      if (json.ok) {
        message.success(json.data.note ?? '税率已更新');
        setSelectedRegion({ ...selectedRegion, tax_rate: newTaxRate });
        setTaxRateModalOpen(false);
        fetchRegions();
      } else {
        message.error(json.error?.detail ?? '更新失败');
      }
    } catch {
      message.error('网络错误');
    } finally {
      setSavingTaxRate(false);
    }
  };

  const levelLabel = (level: number) => {
    const map: Record<number, string> = { 1: '大区', 2: '省', 3: '城市' };
    return map[level] ?? `L${level}`;
  };

  return (
    <Row gutter={16}>
      {/* 左：Tree */}
      <Col xs={24} md={10} lg={8}>
        <Card
          title={
            <Space>
              <BranchesOutlined style={{ color: '#FF6B35' }} />
              <span>区域层级</span>
            </Space>
          }
          extra={
            <Button
              size="small"
              icon={<PlusOutlined />}
              onClick={() => setCreateModalOpen(true)}
            >
              新增{selectedRegion ? '子' : ''}区域
            </Button>
          }
          bodyStyle={{ padding: '12px 16px', minHeight: 400 }}
        >
          <Spin spinning={loading}>
            {treeData.length > 0 ? (
              <Tree
                treeData={treeData}
                onSelect={handleSelectRegion}
                defaultExpandAll
                showIcon
                style={{ fontSize: 14 }}
              />
            ) : (
              <div style={{ textAlign: 'center', padding: '40px 0', color: '#B4B2A9' }}>
                暂无区域，点击「新增区域」
              </div>
            )}
          </Spin>
        </Card>
      </Col>

      {/* 右：详情面板 */}
      <Col xs={24} md={14} lg={16}>
        <Card
          title={
            selectedRegion
              ? <Space>
                  <EnvironmentOutlined style={{ color: '#FF6B35' }} />
                  <span>{selectedRegion.name}</span>
                  <Tag color={['', 'orange', 'blue', 'green'][selectedRegion.level] ?? 'default'}>
                    {levelLabel(selectedRegion.level)}
                  </Tag>
                </Space>
              : '请从左侧选择区域'
          }
          extra={
            selectedRegion && (
              <Space>
                <Button
                  size="small"
                  icon={<EditOutlined />}
                  onClick={() => {
                    setNewTaxRate(selectedRegion.tax_rate ?? 0.06);
                    setTaxRateModalOpen(true);
                  }}
                >
                  修改税率
                </Button>
                <Button
                  size="small"
                  icon={<PlusOutlined />}
                  onClick={() => setCreateModalOpen(true)}
                  disabled={selectedRegion.level >= 3}
                >
                  新增子区域
                </Button>
              </Space>
            )
          }
          bodyStyle={{ minHeight: 400 }}
        >
          {selectedRegion ? (
            <>
              <Row gutter={16} style={{ marginBottom: 24 }}>
                <Col span={8}>
                  <Statistic
                    title="门店数"
                    value={selectedRegion.store_count}
                    prefix={<HomeOutlined />}
                  />
                </Col>
                <Col span={8}>
                  <Statistic
                    title="子区域数"
                    value={selectedRegion.child_count}
                    prefix={<BranchesOutlined />}
                  />
                </Col>
                <Col span={8}>
                  <Statistic
                    title="默认税率"
                    value={((selectedRegion.tax_rate ?? 0.06) * 100).toFixed(2)}
                    suffix="%"
                  />
                </Col>
              </Row>

              <Descriptions column={2} size="small" bordered>
                <Descriptions.Item label="区域编码">
                  {selectedRegion.region_code ?? '—'}
                </Descriptions.Item>
                <Descriptions.Item label="层级">
                  {levelLabel(selectedRegion.level)}（L{selectedRegion.level}）
                </Descriptions.Item>
                <Descriptions.Item label="负责人">
                  {selectedRegion.manager_name ?? '未分配'}
                </Descriptions.Item>
                <Descriptions.Item label="状态">
                  <Badge
                    status={selectedRegion.is_active ? 'success' : 'default'}
                    text={selectedRegion.is_active ? '启用' : '停用'}
                  />
                </Descriptions.Item>
              </Descriptions>

              <div style={{ marginTop: 16, padding: '12px 16px', background: '#FFF3ED', borderRadius: 6 }}>
                <Text type="secondary" style={{ fontSize: 13 }}>
                  <b>税率说明：</b>修改此区域税率将影响该区域下所有门店的默认发票税率。
                  当前税率：{((selectedRegion.tax_rate ?? 0.06) * 100).toFixed(2)}%
                </Text>
              </div>
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: '80px 0', color: '#B4B2A9' }}>
              <EnvironmentOutlined style={{ fontSize: 40, marginBottom: 12 }} />
              <div>点击左侧区域查看详情</div>
            </div>
          )}
        </Card>
      </Col>

      {/* 新建区域 Modal */}
      <Modal
        title={`新建${selectedRegion ? `「${selectedRegion.name}」的子` : ''}区域`}
        open={createModalOpen}
        onCancel={() => { setCreateModalOpen(false); createForm.resetFields(); }}
        onOk={() => createForm.submit()}
        okText="创建"
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={handleCreateRegion}
          style={{ marginTop: 16 }}
        >
          <Form.Item name="name" label="区域名称" rules={[{ required: true, message: '请输入区域名称' }]}>
            <Input placeholder="如：华中大区 / 湖南省 / 长沙市" maxLength={50} />
          </Form.Item>
          <Form.Item name="region_code" label="区域编码（可选）">
            <Input placeholder="如：HZ / HN / CS" maxLength={20} />
          </Form.Item>
          {selectedRegion && (
            <Form.Item label="父区域">
              <Input value={selectedRegion.name} disabled />
            </Form.Item>
          )}
        </Form>
      </Modal>

      {/* 修改税率 Modal */}
      <Modal
        title={`修改「${selectedRegion?.name ?? ''}」税率`}
        open={taxRateModalOpen}
        onCancel={() => setTaxRateModalOpen(false)}
        onOk={handleSaveTaxRate}
        okText="确认修改"
        confirmLoading={savingTaxRate}
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
      >
        <div style={{ padding: '16px 0' }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Text>
              修改后将影响「{selectedRegion?.name}」区域下所有门店的默认发票税率。
            </Text>
            <div>
              <Text strong>新税率（0~100%）：</Text>
              <InputNumber
                value={newTaxRate * 100}
                min={0}
                max={100}
                precision={2}
                suffix="%"
                style={{ marginLeft: 8, width: 120 }}
                onChange={(v) => setNewTaxRate((v ?? 0) / 100)}
              />
            </div>
          </Space>
        </div>
      </Modal>
    </Row>
  );
}

// ── 主页面 ────────────────────────────────────────────────────────────────────

export default function BrandRegionPage() {
  return (
    <div style={{ padding: '16px 24px' }}>
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0, color: '#2C2C2A' }}>
          品牌与区域管理
        </Title>
        <Text type="secondary">
          Y-H1 多品牌统一管理（DB路径）· Y-H2 多区域主数据CRUD
        </Text>
      </div>

      <Tabs
        defaultActiveKey="brands"
        type="card"
        size="middle"
        items={[
          {
            key: 'brands',
            label: (
              <Space>
                <ShopOutlined />
                品牌管理
              </Space>
            ),
            children: <BrandTab />,
          },
          {
            key: 'regions',
            label: (
              <Space>
                <EnvironmentOutlined />
                区域管理
              </Space>
            ),
            children: <RegionTab />,
          },
        ]}
      />
    </div>
  );
}
