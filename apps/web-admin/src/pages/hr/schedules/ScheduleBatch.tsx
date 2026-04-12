/**
 * ScheduleBatch — 批量排班
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  - Step1: 选择班次模板
 *  - Step2: 选择员工（多选）
 *  - Step3: 选择日期范围
 *  - Step4: 预校验（显示冲突列表）
 *  - Step5: 确认创建
 *  - 使用Steps组件分步引导
 *
 * API: POST /api/v1/schedules/batch
 *      POST /api/v1/schedules/validate
 */

import { useState } from 'react';
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Result,
  Select,
  Space,
  Steps,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  CalendarOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  TeamOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { txFetchData } from '../../../api';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;
const TX_PRIMARY = '#FF6B35';

// ─── Types ───────────────────────────────────────────────────────────────────

interface ConflictItem {
  employee_name: string;
  date: string;
  existing_shift: string;
  new_shift: string;
}

interface TemplateOption {
  id: string;
  name: string;
  shift_type: string;
  time_range: string;
}

interface EmployeeOption {
  id: string;
  name: string;
  role: string;
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function ScheduleBatch() {
  const [current, setCurrent] = useState(0);
  const [messageApi, contextHolder] = message.useMessage();

  // Step 1: 班次模板
  const [templateId, setTemplateId] = useState<string>('');
  const [templates, setTemplates] = useState<TemplateOption[]>([]);
  const [templatesLoaded, setTemplatesLoaded] = useState(false);

  // Step 2: 员工选择
  const [employeeIds, setEmployeeIds] = useState<string[]>([]);
  const [employees, setEmployees] = useState<EmployeeOption[]>([]);
  const [employeesLoaded, setEmployeesLoaded] = useState(false);

  // Step 3: 日期范围
  const [dateRange, setDateRange] = useState<[string, string]>(['', '']);

  // Step 4: 校验结果
  const [conflicts, setConflicts] = useState<ConflictItem[]>([]);
  const [validating, setValidating] = useState(false);

  // Step 5: 创建
  const [creating, setCreating] = useState(false);
  const [success, setSuccess] = useState(false);

  // ─── 加载模板 ────────────────────────────────────────────────────────────

  const loadTemplates = async () => {
    if (templatesLoaded) return;
    try {
      const res = await txFetchData('/api/v1/schedules/templates?page=1&size=100') as {
        ok: boolean;
        data: { items: TemplateOption[] };
      };
      if (res.ok) setTemplates(res.data.items ?? []);
    } catch { /* empty */ }
    setTemplatesLoaded(true);
  };

  const loadEmployees = async () => {
    if (employeesLoaded) return;
    try {
      const res = await txFetchData('/api/v1/org/employees?page=1&size=200') as {
        ok: boolean;
        data: { items: EmployeeOption[] };
      };
      if (res.ok) setEmployees(res.data.items ?? []);
    } catch { /* empty */ }
    setEmployeesLoaded(true);
  };

  // ─── 预校验 ─────────────────────────────────────────────────────────────

  const handleValidate = async () => {
    setValidating(true);
    try {
      const res = await txFetchData('/api/v1/schedules/validate', {
        method: 'POST',
        body: JSON.stringify({
          template_id: templateId,
          employee_ids: employeeIds,
          start_date: dateRange[0],
          end_date: dateRange[1],
        }),
      }) as { ok: boolean; data: { conflicts: ConflictItem[] } };
      if (res.ok) {
        setConflicts(res.data.conflicts ?? []);
        setCurrent(3);
      }
    } catch {
      messageApi.error('校验失败');
    } finally {
      setValidating(false);
    }
  };

  // ─── 确认创建 ────────────────────────────────────────────────────────────

  const handleCreate = async () => {
    setCreating(true);
    try {
      const res = await txFetchData('/api/v1/schedules/batch', {
        method: 'POST',
        body: JSON.stringify({
          template_id: templateId,
          employee_ids: employeeIds,
          start_date: dateRange[0],
          end_date: dateRange[1],
        }),
      }) as { ok: boolean };
      if (res.ok) {
        setSuccess(true);
        setCurrent(4);
        messageApi.success('批量排班创建成功');
      }
    } catch {
      messageApi.error('创建失败');
    } finally {
      setCreating(false);
    }
  };

  // ─── Steps ──────────────────────────────────────────────────────────────

  const steps = [
    { title: '选择班次模板', icon: <CalendarOutlined /> },
    { title: '选择员工', icon: <TeamOutlined /> },
    { title: '选择日期', icon: <CalendarOutlined /> },
    { title: '预校验', icon: <ExclamationCircleOutlined /> },
    { title: '完成', icon: <CheckCircleOutlined /> },
  ];

  const canNext = () => {
    if (current === 0) return !!templateId;
    if (current === 1) return employeeIds.length > 0;
    if (current === 2) return dateRange[0] && dateRange[1];
    return true;
  };

  return (
    <div style={{ padding: 24 }}>
      {contextHolder}
      <Title level={4}>批量排班</Title>

      <Steps current={current} items={steps} style={{ marginBottom: 32 }} />

      <Card>
        {/* Step 1 */}
        {current === 0 && (
          <div>
            <Title level={5}>选择班次模板</Title>
            <Select
              placeholder="请选择班次模板"
              style={{ width: 400 }}
              value={templateId || undefined}
              onChange={setTemplateId}
              onFocus={loadTemplates}
              options={templates.map((t) => ({
                label: `${t.name} (${t.time_range})`,
                value: t.id,
              }))}
            />
          </div>
        )}

        {/* Step 2 */}
        {current === 1 && (
          <div>
            <Title level={5}>选择员工</Title>
            <Select
              mode="multiple"
              placeholder="选择员工（可多选）"
              style={{ width: 600 }}
              value={employeeIds}
              onChange={setEmployeeIds}
              onFocus={loadEmployees}
              options={employees.map((e) => ({
                label: `${e.name} (${e.role})`,
                value: e.id,
              }))}
            />
            <div style={{ marginTop: 8 }}>
              <Text type="secondary">已选择 {employeeIds.length} 人</Text>
            </div>
          </div>
        )}

        {/* Step 3 */}
        {current === 2 && (
          <div>
            <Title level={5}>选择日期范围</Title>
            <RangePicker
              style={{ width: 400 }}
              onChange={(_, dateStrings) => setDateRange(dateStrings as [string, string])}
            />
          </div>
        )}

        {/* Step 4 */}
        {current === 3 && (
          <div>
            <Title level={5}>预校验结果</Title>
            {conflicts.length === 0 ? (
              <Alert type="success" message="无排班冲突，可以安全创建" showIcon />
            ) : (
              <>
                <Alert
                  type="warning"
                  message={`发现 ${conflicts.length} 个排班冲突`}
                  showIcon
                  style={{ marginBottom: 16 }}
                />
                <Table
                  dataSource={conflicts}
                  rowKey={(_, idx) => String(idx)}
                  columns={[
                    { title: '员工', dataIndex: 'employee_name', width: 100 },
                    { title: '日期', dataIndex: 'date', width: 120 },
                    { title: '已有班次', dataIndex: 'existing_shift', width: 140 },
                    { title: '新排班次', dataIndex: 'new_shift', width: 140 },
                  ]}
                  pagination={false}
                  size="small"
                />
              </>
            )}
          </div>
        )}

        {/* Step 5 */}
        {current === 4 && (
          <Result
            status="success"
            title="批量排班创建成功"
            subTitle={`已为 ${employeeIds.length} 名员工创建排班`}
            extra={[
              <Button
                key="reset"
                type="primary"
                onClick={() => {
                  setCurrent(0);
                  setTemplateId('');
                  setEmployeeIds([]);
                  setDateRange(['', '']);
                  setConflicts([]);
                  setSuccess(false);
                }}
                style={{ backgroundColor: TX_PRIMARY, borderColor: TX_PRIMARY }}
              >
                继续创建
              </Button>,
            ]}
          />
        )}

        {/* ── 导航按钮 ── */}
        {current < 4 && (
          <div style={{ marginTop: 24, textAlign: 'right' }}>
            <Space>
              {current > 0 && current < 4 && (
                <Button onClick={() => setCurrent((c) => c - 1)}>上一步</Button>
              )}
              {current < 2 && (
                <Button
                  type="primary"
                  disabled={!canNext()}
                  onClick={() => setCurrent((c) => c + 1)}
                  style={{ backgroundColor: TX_PRIMARY, borderColor: TX_PRIMARY }}
                >
                  下一步
                </Button>
              )}
              {current === 2 && (
                <Button
                  type="primary"
                  disabled={!canNext()}
                  loading={validating}
                  onClick={handleValidate}
                  icon={<ThunderboltOutlined />}
                  style={{ backgroundColor: TX_PRIMARY, borderColor: TX_PRIMARY }}
                >
                  开始校验
                </Button>
              )}
              {current === 3 && (
                <Button
                  type="primary"
                  loading={creating}
                  onClick={handleCreate}
                  icon={<CheckCircleOutlined />}
                  style={{ backgroundColor: TX_PRIMARY, borderColor: TX_PRIMARY }}
                >
                  确认创建
                </Button>
              )}
            </Space>
          </div>
        )}
      </Card>
    </div>
  );
}
