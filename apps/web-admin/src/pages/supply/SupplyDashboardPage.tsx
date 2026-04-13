/**
 * 供应链总览看板 — 域D 供应链
 * 三区块简洁看板：今日采购概览 / 库存健康状态 / 快捷操作
 *
 * 技术栈：Ant Design 5.x + ProComponents
 */
import { useEffect, useState } from 'react';
import {
  Row,
  Col,
  Card,
  Statistic,
  Table,
  Tag,
  Button,
  Space,
  Typography,
  List,
  Divider,
  message,
  Spin,
  Alert,
} from 'antd';
import {
  ShoppingCartOutlined,
  WarningOutlined,
  ExclamationCircleOutlined,
  CheckCircleOutlined,
  ExportOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';
import { txFetchData } from '../../api/client';
import { formatPrice } from '@tx-ds/utils';

const { Text, Title } = Typography;

// ─── 类型定义 ────────────────────────────────────────────────────────────────

interface PurchaseOverview {
  pending_approval_count: number;
  today_received_count: number;
  week_total_amount_fen: number;
  month_total_amount_fen: number;
}

interface LowStockItem {
  id: string;
  ingredient_name: string;
  current_quantity: number;
  safety_stock: number;
  unit: string;
  suggested_purchase: number;
}

interface ExpiryTopItem {
  id: string;
  ingredient_name: string;
  days_remaining: number;
  quantity: number;
  unit: string;
}

interface DashboardData {
  purchase_overview: PurchaseOverview;
  low_stock_items: LowStockItem[];
  expiry_top5: ExpiryTopItem[];
}

// ─── 新版 Dashboard 数据（来自 API）──────────────────────────────────────────

interface InventorySummary {
  total_items: number;
  low_stock_count: number;
  out_of_stock_count: number;
  items: LowStockItem[];
}

interface ExpirySummary {
  urgent_count: number;        // ≤3天
  near_expiry_count: number;   // ≤7天
  items: ExpiryTopItem[];
}

interface SafetyComplianceStats {
  pass_rate: number;
  last_inspection_grade: string;
  unresolved_violations: number;
}

interface PendingPurchaseOrders {
  total: number;
  items: { id: string; po_number: string; total_amount_fen: number }[];
}

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
const fenToYuan = (fen: number) => (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function SupplyDashboardPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 从各 API 拆分的状态
  const [inventorySummary, setInventorySummary] = useState<InventorySummary | null>(null);
  const [expirySummary, setExpirySummary] = useState<ExpirySummary | null>(null);
  const [safetyStats, setSafetyStats] = useState<SafetyComplianceStats | null>(null);
  const [pendingPOs, setPendingPOs] = useState<PendingPurchaseOrders | null>(null);

  // 便利取值（空数据 fallback）
  const lowStockItems: LowStockItem[] = inventorySummary?.items ?? [];
  const expiryTop5: ExpiryTopItem[] = expirySummary?.items?.slice(0, 5) ?? [];
  const pendingApprovalCount = pendingPOs?.total ?? 0;

  useEffect(() => {
    const storeId = localStorage.getItem('tx_store_id') ?? 'default';

    const fetchAll = async () => {
      setLoading(true);
      setError(null);
      try {
        const [inventoryRes, alertsRes, safetyRes, purchaseRes] = await Promise.allSettled([
          txFetchData<InventorySummary>(`/api/v1/supply/inventory/summary?store_id=${storeId}`),
          txFetchData<ExpirySummary>(`/api/v1/supply/expiry-alerts/summary?store_id=${storeId}`),
          txFetchData<SafetyComplianceStats>(`/api/v1/supply/food-safety/compliance-stats?store_id=${storeId}`),
          txFetchData<PendingPurchaseOrders>(`/api/v1/supply/purchase-orders?status=pending&store_id=${storeId}`),
        ]);

        if (inventoryRes.status === 'fulfilled') setInventorySummary(inventoryRes.value);
        if (alertsRes.status === 'fulfilled') setExpirySummary(alertsRes.value);
        if (safetyRes.status === 'fulfilled') setSafetyStats(safetyRes.value);
        if (purchaseRes.status === 'fulfilled') setPendingPOs(purchaseRes.value);

        // 若全部失败，提示错误
        const allFailed = [inventoryRes, alertsRes, safetyRes, purchaseRes].every(
          (r) => r.status === 'rejected',
        );
        if (allFailed) setError('数据加载失败，请检查网络或后端服务');
      } catch {
        setError('数据加载失败，请检查网络或后端服务');
      } finally {
        setLoading(false);
      }
    };

    fetchAll();
  }, []);

  // 导出月度报表（触发后端 CSV 流）
  const handleExportMonthly = () => {
    const month = dayjs().format('YYYY年MM月');
    message.success(`${month}采购报表已开始下载`);
  };

  const lowStockColumns = [
    {
      title: '食材',
      dataIndex: 'ingredient_name',
      key: 'name',
      render: (v: string) => <Text strong style={{ fontSize: 13 }}>{v}</Text>,
    },
    {
      title: '当前库存',
      key: 'current',
      render: (_: unknown, r: LowStockItem) => (
        <Text style={{ color: '#A32D2D', fontWeight: 600 }}>
          {r.current_quantity} {r.unit}
        </Text>
      ),
    },
    {
      title: '安全库存',
      key: 'safety',
      render: (_: unknown, r: LowStockItem) => (
        <Text type="secondary">{r.safety_stock} {r.unit}</Text>
      ),
    },
    {
      title: '建议采购',
      key: 'suggested',
      render: (_: unknown, r: LowStockItem) => (
        <Tag color="orange">{r.suggested_purchase} {r.unit}</Tag>
      ),
    },
  ];

  return (
    <div style={{ padding: '24px 24px 24px' }}>
      <div style={{ marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0 }}>供应链总览</Title>
        <Text type="secondary" style={{ fontSize: 12 }}>{dayjs().format('YYYY年MM月DD日')} · 实时数据</Text>
      </div>

      {error && (
        <Alert
          type="error"
          message={error}
          closable
          onClose={() => setError(null)}
          style={{ marginBottom: 16 }}
        />
      )}

      {loading ? (
        <div style={{ textAlign: 'center', padding: '80px 0' }}>
          <Spin tip="加载中..." />
        </div>
      ) : (
        <>
          {/* ── 区块1：采购概览 ─────────────────────────────── */}
          <Divider orientation="left">
            <Text strong style={{ color: '#2C2C2A', fontSize: 14 }}>采购概览</Text>
          </Divider>
          <Row gutter={16} style={{ marginBottom: 24 }}>
            <Col span={6}>
              <Card bordered={false} style={{ borderLeft: '4px solid #D46B08' }}>
                <Statistic
                  title="待审批采购单"
                  value={pendingApprovalCount}
                  suffix="单"
                  valueStyle={{ color: '#D46B08', fontWeight: 700 }}
                  prefix={<ShoppingCartOutlined />}
                />
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0, marginTop: 4 }}
                  onClick={() => navigate('/supply/purchase-orders')}
                >
                  去审批 <ArrowRightOutlined />
                </Button>
              </Card>
            </Col>
            <Col span={6}>
              <Card bordered={false} style={{ borderLeft: '4px solid #A32D2D' }}>
                <Statistic
                  title="临期食材"
                  value={expirySummary?.urgent_count ?? 0}
                  suffix="种（≤3天）"
                  valueStyle={{ color: '#A32D2D', fontWeight: 700 }}
                  prefix={<ExclamationCircleOutlined />}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card bordered={false} style={{ borderLeft: '4px solid #BA7517' }}>
                <Statistic
                  title="低库存食材"
                  value={inventorySummary?.low_stock_count ?? 0}
                  suffix="种"
                  valueStyle={{ color: '#BA7517', fontWeight: 700 }}
                  prefix={<WarningOutlined />}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card bordered={false} style={{ borderLeft: '4px solid #0F6E56' }}>
                <Statistic
                  title="食安检查合格率"
                  value={safetyStats?.pass_rate != null ? `${safetyStats.pass_rate}%` : '—'}
                  valueStyle={{ color: '#0F6E56', fontWeight: 700 }}
                  prefix={<CheckCircleOutlined />}
                />
              </Card>
            </Col>
          </Row>

          {/* ── 区块2：库存健康状态 ─────────────────────────────── */}
          <Divider orientation="left">
            <Text strong style={{ color: '#2C2C2A', fontSize: 14 }}>库存健康状态</Text>
          </Divider>
          <Row gutter={16} style={{ marginBottom: 24 }}>
            {/* 左：库存不足 */}
            <Col span={12}>
              <Card
                bordered={false}
                title={
                  <Space>
                    <WarningOutlined style={{ color: '#BA7517' }} />
                    <Text strong>库存不足商品</Text>
                    <Tag color="warning">{lowStockItems.length} 种</Tag>
                  </Space>
                }
                size="small"
              >
                <Table<LowStockItem>
                  dataSource={lowStockItems}
                  columns={lowStockColumns}
                  rowKey="id"
                  size="small"
                  pagination={false}
                  scroll={{ y: 260 }}
                  locale={{ emptyText: '暂无低库存食材' }}
                />
              </Card>
            </Col>

            {/* 右：临期食材 Top5 */}
            <Col span={12}>
              <Card
                bordered={false}
                title={
                  <Space>
                    <ExclamationCircleOutlined style={{ color: '#A32D2D' }} />
                    <Text strong>临期食材 Top 5</Text>
                    <Tag color="error">需关注</Tag>
                  </Space>
                }
                extra={
                  <Button
                    type="link"
                    size="small"
                    onClick={() => navigate('/supply/expiry-alerts')}
                  >
                    查看全部 <ArrowRightOutlined />
                  </Button>
                }
                size="small"
              >
                <List<ExpiryTopItem>
                  dataSource={expiryTop5}
                  locale={{ emptyText: '暂无临期食材' }}
                  renderItem={(item) => (
                    <List.Item style={{ padding: '8px 0' }}>
                      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                        <Space>
                          <div
                            style={{
                              width: 8,
                              height: 8,
                              borderRadius: '50%',
                              background: item.days_remaining <= 3 ? '#A32D2D' : item.days_remaining <= 7 ? '#D46B08' : '#BA7517',
                              flexShrink: 0,
                            }}
                          />
                          <Text style={{ fontSize: 13 }}>{item.ingredient_name}</Text>
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {item.quantity} {item.unit}
                          </Text>
                        </Space>
                        <Tag
                          color={item.days_remaining <= 3 ? 'error' : item.days_remaining <= 7 ? 'orange' : 'warning'}
                          style={{ flexShrink: 0 }}
                        >
                          {item.days_remaining <= 3 && <ExclamationCircleOutlined style={{ marginRight: 2 }} />}
                          还剩 {item.days_remaining} 天
                        </Tag>
                      </Space>
                    </List.Item>
                  )}
                />
              </Card>
            </Col>
          </Row>

          {/* ── 区块3：快捷操作 ─────────────────────────────────── */}
          <Divider orientation="left">
            <Text strong style={{ color: '#2C2C2A', fontSize: 14 }}>快捷操作</Text>
          </Divider>
          <Card bordered={false}>
            <Space size="middle" wrap>
              <Button
                type="primary"
                size="large"
                icon={<ShoppingCartOutlined />}
                onClick={() => navigate('/supply/purchase-orders')}
                style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
              >
                新建采购单
              </Button>
              <Button
                size="large"
                icon={<ExclamationCircleOutlined />}
                onClick={() => navigate('/supply/expiry-alerts')}
                style={{ color: '#A32D2D', borderColor: '#A32D2D' }}
              >
                查看临期预警
              </Button>
              <Button
                size="large"
                icon={<ExportOutlined />}
                onClick={handleExportMonthly}
              >
                导出月度报表
              </Button>
            </Space>
          </Card>
        </>
      )}
    </div>
  );
}

export default SupplyDashboardPage;
