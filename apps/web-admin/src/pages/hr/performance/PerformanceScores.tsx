/**
 * PerformanceScores — 绩效评分
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  - ProTable展示评分列表（员工/岗位/评分/等级/评分人/日期）
 *  - 新建评分ModalForm（选员工+各维度打分+总评）
 *  - 等级Tag颜色编码（A优绿/B良蓝/C中灰/D差红）
 *
 * API: GET  /api/v1/performance/scores?store_id=&period=
 *      POST /api/v1/performance/scores
 */

import { useRef } from 'react';
import { Button, Tag, Typography, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDigit,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import { txFetchData } from '../../../api';

const { Title } = Typography;

// ─── Types ───────────────────────────────────────────────────────────────────

type Grade = 'A' | 'B' | 'C' | 'D';

interface ScoreRecord {
  id: string;
  employee_id: string;
  employee_name: string;
  role: string;
  overall_score: number;
  grade: Grade;
  reviewer: string;
  review_date: string;
  period: string;
  store_name: string;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const GRADE_TAG: Record<Grade, { color: string; label: string }> = {
  A: { color: 'success', label: 'A优' },
  B: { color: 'processing', label: 'B良' },
  C: { color: 'default', label: 'C中' },
  D: { color: 'error', label: 'D差' },
};

// ─── Component ───────────────────────────────────────────────────────────────

export default function PerformanceScores() {
  const actionRef = useRef<ActionType>(null);
  const [messageApi, contextHolder] = message.useMessage();

  const columns: ProColumns<ScoreRecord>[] = [
    { title: '员工', dataIndex: 'employee_name', width: 100 },
    { title: '门店', dataIndex: 'store_name', width: 140, hideInSearch: true },
    { title: '岗位', dataIndex: 'role', width: 100, hideInSearch: true },
    {
      title: '评分',
      dataIndex: 'overall_score',
      width: 80,
      hideInSearch: true,
      sorter: true,
    },
    {
      title: '等级',
      dataIndex: 'grade',
      width: 80,
      valueEnum: { A: { text: 'A优' }, B: { text: 'B良' }, C: { text: 'C中' }, D: { text: 'D差' } },
      render: (_, r) => {
        const t = GRADE_TAG[r.grade];
        return <Tag color={t.color}>{t.label}</Tag>;
      },
    },
    { title: '评分人', dataIndex: 'reviewer', width: 100, hideInSearch: true },
    { title: '评分日期', dataIndex: 'review_date', width: 120, hideInSearch: true },
    {
      title: '考核期',
      dataIndex: 'period',
      valueType: 'dateMonth',
      width: 120,
    },
    {
      title: '门店',
      dataIndex: 'store_id',
      hideInTable: true,
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      {contextHolder}
      <Title level={4}>绩效评分</Title>

      <ProTable<ScoreRecord>
        headerTitle="评分列表"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 80 }}
        toolBarRender={() => [
          <ModalForm
            key="create"
            title="新建绩效评分"
            trigger={
              <Button
                type="primary"
                icon={<PlusOutlined />}
                style={{ backgroundColor: '#FF6B35', borderColor: '#FF6B35' }}
              >
                新建评分
              </Button>
            }
            onFinish={async (values) => {
              try {
                const res = await txFetchData('/api/v1/performance/scores', {
                  method: 'POST',
                  body: JSON.stringify(values),
                }) as { ok: boolean };
                if (res.ok) {
                  messageApi.success('评分创建成功');
                  actionRef.current?.reload();
                  return true;
                }
                messageApi.error('创建失败');
              } catch {
                messageApi.error('创建失败');
              }
              return false;
            }}
            modalProps={{ destroyOnClose: true }}
          >
            <ProFormSelect
              name="employee_id"
              label="员工"
              rules={[{ required: true, message: '请选择员工' }]}
              request={async () => {
                try {
                  const res = await txFetchData('/api/v1/org/employees?page=1&size=200') as {
                    ok: boolean;
                    data: { items: { id: string; name: string }[] };
                  };
                  if (res.ok) {
                    return res.data.items.map((e) => ({ label: e.name, value: e.id }));
                  }
                } catch { /* empty */ }
                return [];
              }}
            />
            <ProFormText name="period" label="考核期" placeholder="YYYY-MM" rules={[{ required: true }]} />
            <ProFormDigit name="service_score" label="服务评分" min={0} max={100} rules={[{ required: true }]} />
            <ProFormDigit name="efficiency_score" label="效率评分" min={0} max={100} rules={[{ required: true }]} />
            <ProFormDigit name="quality_score" label="质量评分" min={0} max={100} rules={[{ required: true }]} />
            <ProFormDigit name="attendance_score" label="出勤评分" min={0} max={100} rules={[{ required: true }]} />
            <ProFormTextArea name="comments" label="总评" />
          </ModalForm>,
        ]}
        request={async (params) => {
          const query = new URLSearchParams();
          if (params.store_id) query.set('store_id', params.store_id);
          if (params.period) query.set('period', params.period);
          if (params.grade) query.set('grade', params.grade);
          query.set('page', String(params.current ?? 1));
          query.set('size', String(params.pageSize ?? 20));
          try {
            const res = await txFetchData(`/api/v1/performance/scores?${query}`) as {
              ok: boolean;
              data: { items: ScoreRecord[]; total: number };
            };
            if (res.ok) {
              return { data: res.data.items, total: res.data.total, success: true };
            }
          } catch { /* fallback */ }
          return { data: [], total: 0, success: true };
        }}
        pagination={{ defaultPageSize: 20 }}
      />
    </div>
  );
}
