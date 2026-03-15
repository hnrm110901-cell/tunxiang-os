import React, { useState } from 'react';
import {
  Card, Button, Modal, Form, Input, Select, Row, Col, message,
} from 'antd';
import { EditOutlined, BankOutlined } from '@ant-design/icons';
import { apiClient } from '../../../services/api';
import type { MerchantDetail, ConfigSummary } from '../merchant-constants';
import { INDUSTRY_LABELS } from '../merchant-constants';
import styles from './OverviewTab.module.css';

interface Props {
  detail: MerchantDetail;
  configSummary: ConfigSummary | null;
  onRefresh: () => void;
}

const OverviewTab: React.FC<Props> = ({ detail, configSummary, onRefresh }) => {
  const [editGroupVisible, setEditGroupVisible] = useState(false);
  const [editGroupForm] = Form.useForm();

  const openEditGroup = () => {
    editGroupForm.setFieldsValue({ ...detail.group });
    setEditGroupVisible(true);
  };

  const handleEditGroup = async () => {
    try {
      const values = await editGroupForm.validateFields();
      await apiClient.put(`/api/v1/merchants/${detail.brand_id}/group`, values);
      message.success('集团信息已更新');
      setEditGroupVisible(false);
      onRefresh();
    } catch {
      message.error('更新失败');
    }
  };

  return (
    <div>
      {/* ── Group Info ────────────────────────────────────────────────────────── */}
      <div className={styles.section}>
        <div className={styles.sectionTitle}>
          <span><BankOutlined /> 集团信息</span>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={openEditGroup}>编辑</Button>
        </div>
        <div className={styles.groupInfo}>
          <div className={styles.groupInfoItem}>
            <span className={styles.groupInfoLabel}>集团名称</span>
            <span className={styles.groupInfoValue}>{detail.group.group_name}</span>
          </div>
          <div className={styles.groupInfoItem}>
            <span className={styles.groupInfoLabel}>法人</span>
            <span className={styles.groupInfoValue}>{detail.group.legal_entity}</span>
          </div>
          <div className={styles.groupInfoItem}>
            <span className={styles.groupInfoLabel}>信用代码</span>
            <span className={styles.groupInfoValue}>{detail.group.unified_social_credit_code}</span>
          </div>
          <div className={styles.groupInfoItem}>
            <span className={styles.groupInfoLabel}>行业</span>
            <span className={styles.groupInfoValue}>{INDUSTRY_LABELS[detail.group.industry_type] || detail.group.industry_type}</span>
          </div>
          <div className={styles.groupInfoItem}>
            <span className={styles.groupInfoLabel}>联系人</span>
            <span className={styles.groupInfoValue}>{detail.group.contact_person}</span>
          </div>
          <div className={styles.groupInfoItem}>
            <span className={styles.groupInfoLabel}>电话</span>
            <span className={styles.groupInfoValue}>{detail.group.contact_phone}</span>
          </div>
          {detail.group.address && (
            <div className={styles.groupInfoItem} style={{ gridColumn: '1 / -1' }}>
              <span className={styles.groupInfoLabel}>地址</span>
              <span className={styles.groupInfoValue}>{detail.group.address}</span>
            </div>
          )}
        </div>
      </div>

      {/* ── Targets ───────────────────────────────────────────────────────────── */}
      <div className={styles.section}>
        <div className={styles.sectionTitle}>经营目标</div>
        <div className={styles.targetGrid}>
          <div className={styles.targetCard}>
            <div className={styles.targetValue}>{detail.target_food_cost_pct}%</div>
            <div className={styles.targetLabel}>食材成本率</div>
          </div>
          <div className={styles.targetCard}>
            <div className={styles.targetValue}>{detail.target_labor_cost_pct}%</div>
            <div className={styles.targetLabel}>人力成本率</div>
          </div>
          <div className={styles.targetCard}>
            <div className={styles.targetValue}>{detail.target_rent_cost_pct ?? '-'}%</div>
            <div className={styles.targetLabel}>租金成本率</div>
          </div>
          <div className={styles.targetCard}>
            <div className={styles.targetValue}>{detail.target_waste_pct}%</div>
            <div className={styles.targetLabel}>损耗率</div>
          </div>
        </div>
      </div>

      {/* ── Config Summary ────────────────────────────────────────────────────── */}
      {configSummary && (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>配置概况</div>
          <div className={styles.configGrid}>
            <div className={styles.configCard}>
              <div className={styles.configCardValue}>{configSummary.store_count}</div>
              <div className={styles.configCardLabel}>门店数</div>
            </div>
            <div className={styles.configCard}>
              <div className={styles.configCardValue}>{configSummary.user_count}</div>
              <div className={styles.configCardLabel}>用户数</div>
            </div>
            <div className={styles.configCard}>
              <div className={styles.configCardValue}>{configSummary.im.configured ? '已配置' : '未配置'}</div>
              <div className={styles.configCardLabel}>IM 集成</div>
            </div>
            <div className={styles.configCard}>
              <div className={styles.configCardValue}>{configSummary.agents.enabled}/{configSummary.agents.total}</div>
              <div className={styles.configCardLabel}>Agent 启用</div>
            </div>
            <div className={styles.configCard}>
              <div className={styles.configCardValue}>{configSummary.channels.count}</div>
              <div className={styles.configCardLabel}>渠道数</div>
            </div>
          </div>
        </div>
      )}

      {/* ── Edit Group Modal ──────────────────────────────────────────────────── */}
      <Modal
        title="编辑集团信息"
        open={editGroupVisible}
        onCancel={() => setEditGroupVisible(false)}
        onOk={handleEditGroup}
        width={560}
      >
        <Form form={editGroupForm} layout="vertical">
          <Form.Item name="group_name" label="集团名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="legal_entity" label="法人">
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="unified_social_credit_code" label="统一社会信用代码">
                <Input maxLength={18} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="contact_person" label="联系人">
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="contact_phone" label="联系电话">
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="address" label="地址">
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default OverviewTab;
