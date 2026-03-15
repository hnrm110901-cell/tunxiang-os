import React, { useState, useEffect, useCallback, lazy, Suspense } from 'react';
import {
  Button, Tag, Space, Tabs, message, Popconfirm, Spin, Badge,
} from 'antd';
import {
  ArrowLeftOutlined, EditOutlined, StopOutlined,
  CheckCircleOutlined, ShopOutlined, TeamOutlined,
  ApiOutlined, RobotOutlined, DollarOutlined,
  AppstoreOutlined, ProfileOutlined, WechatWorkOutlined,
} from '@ant-design/icons';
import { useParams, useSearchParams, useNavigate } from 'react-router-dom';
import { apiClient } from '../../services/api';
import type { MerchantDetail, ConfigSummary } from './merchant-constants';
import { CUISINE_LABELS } from './merchant-constants';
import OverviewTab from './merchant-tabs/OverviewTab';
import StoresTab from './merchant-tabs/StoresTab';
import UsersTab from './merchant-tabs/UsersTab';
import CostTargetsTab from './merchant-tabs/CostTargetsTab';
import IMConfigTab from './merchant-tabs/IMConfigTab';
import AgentConfigTab from './merchant-tabs/AgentConfigTab';
import ChannelsTab from './merchant-tabs/ChannelsTab';
import styles from './MerchantDetailPage.module.css';

const MerchantDetailPage: React.FC = () => {
  const { brandId } = useParams<{ brandId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const activeTab = searchParams.get('tab') || 'overview';

  const [detail, setDetail] = useState<MerchantDetail | null>(null);
  const [configSummary, setConfigSummary] = useState<ConfigSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchDetail = useCallback(async () => {
    if (!brandId) return;
    setLoading(true);
    try {
      const data = await apiClient.get<MerchantDetail>(`/api/v1/merchants/${brandId}`);
      setDetail(data);
    } catch {
      message.error('加载商户详情失败');
    } finally {
      setLoading(false);
    }
  }, [brandId]);

  const fetchConfigSummary = useCallback(async () => {
    if (!brandId) return;
    try {
      const data = await apiClient.get<ConfigSummary>(`/api/v1/merchants/${brandId}/config-summary`);
      setConfigSummary(data);
    } catch { /* silent */ }
  }, [brandId]);

  useEffect(() => { fetchDetail(); fetchConfigSummary(); }, [fetchDetail, fetchConfigSummary]);

  const handleToggleMerchant = async () => {
    if (!brandId) return;
    try {
      await apiClient.post(`/api/v1/merchants/${brandId}/toggle-status`, {});
      message.success('状态已切换');
      fetchDetail();
      fetchConfigSummary();
    } catch {
      message.error('操作失败');
    }
  };

  const onTabChange = (key: string) => {
    setSearchParams({ tab: key });
  };

  if (loading && !detail) {
    return (
      <div className={styles.loadingContainer}>
        <Spin size="large" />
      </div>
    );
  }

  if (!detail) {
    return (
      <div className={styles.loadingContainer}>
        <div>商户不存在</div>
        <Button onClick={() => navigate('/platform/merchants')}>返回列表</Button>
      </div>
    );
  }

  const tabItems = [
    {
      key: 'overview',
      label: <span><ProfileOutlined /> 概览</span>,
      children: (
        <OverviewTab
          detail={detail}
          configSummary={configSummary}
          onRefresh={() => { fetchDetail(); fetchConfigSummary(); }}
        />
      ),
    },
    {
      key: 'stores',
      label: <span><ShopOutlined /> 门店 ({detail.stores.length})</span>,
      children: (
        <StoresTab
          brandId={detail.brand_id}
          stores={detail.stores}
          onRefresh={fetchDetail}
        />
      ),
    },
    {
      key: 'users',
      label: <span><TeamOutlined /> 用户 ({detail.users.length})</span>,
      children: (
        <UsersTab
          brandId={detail.brand_id}
          users={detail.users}
          stores={detail.stores}
          onRefresh={fetchDetail}
        />
      ),
    },
    {
      key: 'costs',
      label: <span><DollarOutlined /> 成本目标</span>,
      children: (
        <CostTargetsTab
          detail={detail}
          onRefresh={fetchDetail}
        />
      ),
    },
    {
      key: 'im',
      label: (
        <span>
          <ApiOutlined /> IM 集成
          {configSummary?.im.configured && (
            <Badge status="success" style={{ marginLeft: 6 }} />
          )}
        </span>
      ),
      children: (
        <IMConfigTab brandId={detail.brand_id} />
      ),
    },
    {
      key: 'agents',
      label: (
        <span>
          <RobotOutlined /> Agent 配置
          {configSummary && (
            <Tag color="blue" style={{ marginLeft: 6, fontSize: 11 }}>
              {configSummary.agents.enabled}/{configSummary.agents.total}
            </Tag>
          )}
        </span>
      ),
      children: (
        <AgentConfigTab brandId={detail.brand_id} brandName={detail.brand_name} />
      ),
    },
    {
      key: 'channels',
      label: (
        <span>
          <AppstoreOutlined /> 销售渠道
          {configSummary && configSummary.channels.count > 0 && (
            <Tag style={{ marginLeft: 6, fontSize: 11 }}>
              {configSummary.channels.count}
            </Tag>
          )}
        </span>
      ),
      children: (
        <ChannelsTab brandId={detail.brand_id} />
      ),
    },
  ];

  return (
    <div className={styles.container}>
      {/* ── Header ────────────────────────────────────────────────────────────── */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/platform/merchants')}
            className={styles.backBtn}
          />
          <div className={styles.brandInfo}>
            <div className={styles.brandName}>
              {detail.brand_name}
              <Tag
                color={detail.status === 'active' ? 'green' : 'red'}
                style={{ marginLeft: 8, verticalAlign: 'middle' }}
              >
                {detail.status === 'active' ? '运营中' : '已停用'}
              </Tag>
            </div>
            <div className={styles.brandMeta}>
              <span>{CUISINE_LABELS[detail.cuisine_type] || detail.cuisine_type}</span>
              {detail.avg_ticket_yuan && <span>人均 ¥{detail.avg_ticket_yuan}</span>}
              <span className={styles.brandIdText}>{detail.brand_id}</span>
              {detail.created_at && <span>开通于 {new Date(detail.created_at).toLocaleDateString('zh-CN')}</span>}
            </div>
          </div>
        </div>
        <Space>
          <Popconfirm
            title={`确认${detail.status === 'active' ? '停用' : '启用'}该商户？`}
            onConfirm={handleToggleMerchant}
          >
            <Button
              danger={detail.status === 'active'}
              icon={detail.status === 'active' ? <StopOutlined /> : <CheckCircleOutlined />}
            >
              {detail.status === 'active' ? '停用' : '启用'}
            </Button>
          </Popconfirm>
        </Space>
      </div>

      {/* ── Config Summary Badges ─────────────────────────────────────────────── */}
      {configSummary && (
        <div className={styles.configBadges}>
          <div className={styles.configBadge}>
            <ApiOutlined />
            <span>IM: {configSummary.im.configured ? (configSummary.im.platform === 'wechat_work' ? '企微已配置' : '钉钉已配置') : '未配置'}</span>
          </div>
          <div className={styles.configBadge}>
            <RobotOutlined />
            <span>Agent: {configSummary.agents.enabled}/{configSummary.agents.total} 启用</span>
          </div>
          <div className={styles.configBadge}>
            <AppstoreOutlined />
            <span>渠道: {configSummary.channels.count} 个</span>
          </div>
          <div className={styles.configBadge}>
            <ShopOutlined />
            <span>门店: {configSummary.store_count}</span>
          </div>
          <div className={styles.configBadge}>
            <TeamOutlined />
            <span>用户: {configSummary.user_count}</span>
          </div>
        </div>
      )}

      {/* ── Tabs ──────────────────────────────────────────────────────────────── */}
      <Tabs
        activeKey={activeTab}
        onChange={onTabChange}
        items={tabItems}
        className={styles.tabs}
      />
    </div>
  );
};

export default MerchantDetailPage;
