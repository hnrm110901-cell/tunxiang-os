/**
 * 我的应用 — 已装应用管理（升级/降级/卸载）
 */
import React, { useEffect, useState } from 'react';
import { Table, Button, Tag, Space, Modal, Select, message, Popconfirm } from 'antd';
import { apiClient, handleApiError } from '../../services/api';

interface Installation {
  installation_id: string;
  app_id: string;
  app_code: string;
  app_name: string;
  category: string;
  tier_name: string;
  status: string;
  installed_at: string;
  trial_ends_at?: string;
  in_trial: boolean;
}

const MyApps: React.FC = () => {
  const [rows, setRows] = useState<Installation[]>([]);
  const [loading, setLoading] = useState(false);
  const [changeOpen, setChangeOpen] = useState(false);
  const [editRow, setEditRow] = useState<Installation | null>(null);
  const [newTier, setNewTier] = useState('pro');
  const tenantId = localStorage.getItem('tenant_id') || 'demo-tenant';

  const load = async () => {
    setLoading(true);
    try {
      const resp = await apiClient.get('/api/v1/marketplace/installations/my', {
        params: { tenant_id: tenantId },
      });
      setRows(resp.data || []);
    } catch (e) {
      message.error(handleApiError(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const uninstall = async (id: string) => {
    try {
      await apiClient.post(`/api/v1/marketplace/installations/${id}/uninstall`);
      message.success('已卸载');
      load();
    } catch (e) {
      message.error(handleApiError(e));
    }
  };

  const changeTier = async () => {
    if (!editRow) return;
    try {
      await apiClient.post(
        `/api/v1/marketplace/installations/${editRow.installation_id}/change-tier`,
        { new_tier: newTier },
      );
      message.success('已切换档位');
      setChangeOpen(false);
      load();
    } catch (e) {
      message.error(handleApiError(e));
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <h2>我的应用</h2>
      <Table
        loading={loading}
        dataSource={rows}
        rowKey="installation_id"
        columns={[
          { title: '应用', dataIndex: 'app_name' },
          { title: '分类', dataIndex: 'category', render: (c) => <Tag>{c}</Tag> },
          { title: '当前档位', dataIndex: 'tier_name' },
          {
            title: '状态',
            dataIndex: 'status',
            render: (s, r) => (
              <>
                <Tag color={s === 'active' ? 'green' : 'default'}>{s}</Tag>
                {r.in_trial && <Tag color="gold">试用中</Tag>}
              </>
            ),
          },
          { title: '安装时间', dataIndex: 'installed_at' },
          {
            title: '操作',
            render: (_, r) => (
              <Space>
                <Button
                  size="small"
                  onClick={() => {
                    setEditRow(r);
                    setNewTier('pro');
                    setChangeOpen(true);
                  }}
                >
                  升级/降级
                </Button>
                <Popconfirm
                  title="确定卸载？"
                  onConfirm={() => uninstall(r.installation_id)}
                >
                  <Button size="small" danger>
                    卸载
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title={`切换档位 — ${editRow?.app_name}`}
        open={changeOpen}
        onCancel={() => setChangeOpen(false)}
        onOk={changeTier}
      >
        <Select
          value={newTier}
          onChange={setNewTier}
          style={{ width: '100%' }}
          options={[
            { value: 'basic', label: 'Basic' },
            { value: 'pro', label: 'Pro' },
            { value: 'enterprise', label: 'Enterprise' },
          ]}
        />
      </Modal>
    </div>
  );
};

export default MyApps;
