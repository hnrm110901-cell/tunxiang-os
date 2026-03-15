import React, { useState } from 'react';
import {
  Form, InputNumber, Button, Row, Col, Divider, message, Card,
} from 'antd';
import { EditOutlined, SaveOutlined } from '@ant-design/icons';
import { apiClient } from '../../../services/api';
import type { MerchantDetail } from '../merchant-constants';
import { CUISINE_LABELS, CUISINE_OPTIONS } from '../merchant-constants';
import styles from './CostTargetsTab.module.css';

interface Props {
  detail: MerchantDetail;
  onRefresh: () => void;
}

const CostTargetsTab: React.FC<Props> = ({ detail, onRefresh }) => {
  const [editing, setEditing] = useState(false);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  const startEdit = () => {
    form.setFieldsValue({
      target_food_cost_pct: detail.target_food_cost_pct,
      target_labor_cost_pct: detail.target_labor_cost_pct,
      target_rent_cost_pct: detail.target_rent_cost_pct,
      target_waste_pct: detail.target_waste_pct,
    });
    setEditing(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      await apiClient.put(`/api/v1/merchants/${detail.brand_id}`, values);
      message.success('成本目标已更新');
      setEditing(false);
      onRefresh();
    } catch {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  if (!editing) {
    return (
      <div>
        <div className={styles.header}>
          <span className={styles.title}>经营成本目标</span>
          <Button icon={<EditOutlined />} onClick={startEdit}>编辑</Button>
        </div>
        <div className={styles.targetGrid}>
          <Card size="small" className={styles.targetCard}>
            <div className={styles.targetValue}>{detail.target_food_cost_pct}%</div>
            <div className={styles.targetLabel}>食材成本率</div>
          </Card>
          <Card size="small" className={styles.targetCard}>
            <div className={styles.targetValue}>{detail.target_labor_cost_pct}%</div>
            <div className={styles.targetLabel}>人力成本率</div>
          </Card>
          <Card size="small" className={styles.targetCard}>
            <div className={styles.targetValue}>{detail.target_rent_cost_pct != null ? `${detail.target_rent_cost_pct}%` : '-'}</div>
            <div className={styles.targetLabel}>租金成本率</div>
          </Card>
          <Card size="small" className={styles.targetCard}>
            <div className={styles.targetValue}>{detail.target_waste_pct}%</div>
            <div className={styles.targetLabel}>损耗率</div>
          </Card>
        </div>
        <div className={styles.hint}>
          这些目标值将用于 Agent 自动告警阈值计算和经营报告中的偏差分析。
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className={styles.header}>
        <span className={styles.title}>编辑成本目标</span>
        <div className={styles.headerActions}>
          <Button onClick={() => setEditing(false)}>取消</Button>
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>保存</Button>
        </div>
      </div>
      <Form form={form} layout="vertical">
        <Row gutter={24}>
          <Col span={12}>
            <Form.Item name="target_food_cost_pct" label="食材成本率">
              <InputNumber min={0} max={100} addonAfter="%" style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="target_labor_cost_pct" label="人力成本率">
              <InputNumber min={0} max={100} addonAfter="%" style={{ width: '100%' }} />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={24}>
          <Col span={12}>
            <Form.Item name="target_rent_cost_pct" label="租金成本率">
              <InputNumber min={0} max={100} addonAfter="%" style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="target_waste_pct" label="损耗率">
              <InputNumber min={0} max={100} addonAfter="%" style={{ width: '100%' }} />
            </Form.Item>
          </Col>
        </Row>
      </Form>
    </div>
  );
};

export default CostTargetsTab;
