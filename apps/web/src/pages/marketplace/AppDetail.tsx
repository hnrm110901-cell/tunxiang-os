/**
 * 应用详情页 — 定价方案 + 安装 + 评价
 */
import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Button, Modal, Radio, List, Rate, message, Spin, Tag, Descriptions } from 'antd';
import { apiClient, handleApiError } from '../../services/api';

interface Tier {
  id: string;
  tier_name: string;
  monthly_fee_yuan: number;
  usage_limits: Record<string, number>;
  features: string[];
}
interface Detail {
  id: string;
  code: string;
  name: string;
  category: string;
  description: string;
  provider: string;
  price_model: string;
  price_yuan: number;
  version: string;
  trial_days: number;
  tiers: Tier[];
  reviews: { rating: number; review_text: string; reviewed_by: string }[];
}

const AppDetail: React.FC = () => {
  const { id } = useParams();
  const nav = useNavigate();
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedTier, setSelectedTier] = useState<string>('basic');

  // demo 默认用当前租户 ID；真实场景从 auth context 读
  const tenantId = localStorage.getItem('tenant_id') || 'demo-tenant';

  useEffect(() => {
    (async () => {
      try {
        const resp = await apiClient.get(`/api/v1/marketplace/apps/${id}`);
        setDetail(resp.data);
        if (resp.data.tiers?.length) setSelectedTier(resp.data.tiers[0].tier_name);
      } catch (e) {
        message.error(handleApiError(e));
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  const install = async () => {
    try {
      await apiClient.post(
        `/api/v1/marketplace/apps/${id}/install?tenant_id=${tenantId}`,
        { tier_name: selectedTier },
      );
      message.success('安装成功');
      setModalOpen(false);
      nav('/marketplace/my-apps');
    } catch (e) {
      message.error(handleApiError(e));
    }
  };

  if (loading) return <Spin style={{ margin: 40 }} />;
  if (!detail) return null;

  return (
    <div style={{ padding: 24 }}>
      <h2>{detail.name}</h2>
      <Tag color="orange">{detail.category}</Tag>
      <Tag>v{detail.version}</Tag>
      <p style={{ color: '#666', marginTop: 12 }}>{detail.description}</p>
      <Descriptions column={2} size="small" style={{ marginTop: 12 }}>
        <Descriptions.Item label="提供方">{detail.provider}</Descriptions.Item>
        <Descriptions.Item label="计费模式">{detail.price_model}</Descriptions.Item>
        <Descriptions.Item label="标价">¥{detail.price_yuan.toFixed(2)}</Descriptions.Item>
        <Descriptions.Item label="试用天数">{detail.trial_days} 天</Descriptions.Item>
      </Descriptions>

      <h3 style={{ marginTop: 24 }}>定价方案</h3>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {detail.tiers.map((t) => (
          <Card key={t.id} title={t.tier_name.toUpperCase()} style={{ width: 260 }}>
            <div style={{ fontSize: 24, color: '#FF6B2C', marginBottom: 8 }}>
              ¥{t.monthly_fee_yuan.toFixed(0)}/月
            </div>
            <List
              size="small"
              dataSource={t.features}
              renderItem={(f) => <List.Item>✓ {f}</List.Item>}
            />
          </Card>
        ))}
      </div>
      <Button type="primary" style={{ marginTop: 16 }} onClick={() => setModalOpen(true)}>
        安装应用
      </Button>

      <h3 style={{ marginTop: 24 }}>评价 ({detail.reviews.length})</h3>
      <List
        dataSource={detail.reviews}
        renderItem={(r) => (
          <List.Item>
            <Rate disabled value={r.rating} />
            <span style={{ marginLeft: 8 }}>{r.review_text}</span>
            <span style={{ color: '#999', marginLeft: 8 }}>— {r.reviewed_by}</span>
          </List.Item>
        )}
        locale={{ emptyText: '暂无评价' }}
      />

      <Modal
        title="选择定价方案"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={install}
        okText="确认安装"
      >
        <Radio.Group
          value={selectedTier}
          onChange={(e) => setSelectedTier(e.target.value)}
        >
          {detail.tiers.map((t) => (
            <Radio key={t.id} value={t.tier_name} style={{ display: 'block', padding: 6 }}>
              {t.tier_name.toUpperCase()} — ¥{t.monthly_fee_yuan.toFixed(0)}/月
            </Radio>
          ))}
        </Radio.Group>
      </Modal>
    </div>
  );
};

export default AppDetail;
