/**
 * EmployeeCreate — 新建员工（分步表单）
 * Sprint 5 · 员工主档
 *
 * API: POST /api/v1/employees
 */

import { useNavigate } from 'react-router-dom';
import { Card, Descriptions, message } from 'antd';
import {
  ProFormDatePicker,
  ProFormSelect,
  ProFormText,
  StepsForm,
} from '@ant-design/pro-components';
import { txFetchData } from '../../../api';

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface CreateEmployeeResp {
  id: string;
  employee_no: string;
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function EmployeeCreate() {
  const navigate = useNavigate();

  return (
    <Card title="新建员工">
      <StepsForm
        onFinish={async (values) => {
          const resp = await txFetchData<CreateEmployeeResp>('/api/v1/employees', {
            method: 'POST',
            body: JSON.stringify(values),
          });
          if (resp) {
            message.success(`员工创建成功，工号: ${resp.employee_no}`);
            navigate(`/hr/employees/${resp.id}`);
          }
        }}
      >
        {/* Step 1: 基本信息 */}
        <StepsForm.StepForm name="basic" title="基本信息">
          <ProFormText
            name="name"
            label="姓名"
            rules={[{ required: true, message: '请输入姓名' }]}
            width="md"
          />
          <ProFormText
            name="phone"
            label="手机号"
            rules={[{ required: true, message: '请输入手机号' }, { pattern: /^1\d{10}$/, message: '手机号格式不正确' }]}
            width="md"
          />
          <ProFormSelect
            name="gender"
            label="性别"
            width="sm"
            options={[
              { label: '男', value: 'male' },
              { label: '女', value: 'female' },
            ]}
            rules={[{ required: true }]}
          />
          <ProFormDatePicker name="birthday" label="出生日期" width="md" />
          <ProFormText name="id_card" label="身份证号" width="md" />
          <ProFormSelect
            name="education"
            label="学历"
            width="sm"
            options={[
              { label: '初中及以下', value: 'junior' },
              { label: '高中/中专', value: 'high_school' },
              { label: '大专', value: 'college' },
              { label: '本科', value: 'bachelor' },
              { label: '硕士及以上', value: 'master' },
            ]}
          />
          <ProFormText name="emergency_contact" label="紧急联系人" width="md" />
          <ProFormText name="emergency_phone" label="紧急联系电话" width="md" />
        </StepsForm.StepForm>

        {/* Step 2: 任职信息 */}
        <StepsForm.StepForm name="position" title="任职信息">
          <ProFormSelect
            name="department_id"
            label="部门"
            width="md"
            rules={[{ required: true, message: '请选择部门' }]}
            request={async () => {
              const resp = await txFetchData<{ items: { id: string; name: string }[] }>(
                '/api/v1/org-structure/departments',
              );
              return (resp?.items ?? []).map((d) => ({ label: d.name, value: d.id }));
            }}
            fieldProps={{ showSearch: true }}
          />
          <ProFormSelect
            name="position_id"
            label="岗位"
            width="md"
            rules={[{ required: true, message: '请选择岗位' }]}
            request={async () => {
              const resp = await txFetchData<{ items: { id: string; name: string }[] }>(
                '/api/v1/job-grades',
              );
              return (resp?.items ?? []).map((j) => ({ label: j.name, value: j.id }));
            }}
            fieldProps={{ showSearch: true }}
          />
          <ProFormSelect
            name="grade_id"
            label="职级"
            width="md"
            request={async () => {
              const resp = await txFetchData<{ items: { id: string; name: string }[] }>(
                '/api/v1/job-grades?type=grade',
              );
              return (resp?.items ?? []).map((g) => ({ label: g.name, value: g.id }));
            }}
          />
          <ProFormSelect
            name="employment_type"
            label="用工类型"
            width="sm"
            rules={[{ required: true }]}
            options={[
              { label: '全职', value: 'full_time' },
              { label: '兼职', value: 'part_time' },
              { label: '实习', value: 'intern' },
              { label: '外包', value: 'outsourced' },
            ]}
          />
          <ProFormDatePicker
            name="hire_date"
            label="入职日期"
            width="md"
            rules={[{ required: true }]}
          />
          <ProFormDatePicker name="contract_start" label="合同起始日期" width="md" />
          <ProFormDatePicker name="contract_end" label="合同到期日期" width="md" />
        </StepsForm.StepForm>

        {/* Step 3: 证照信息 */}
        <StepsForm.StepForm name="documents" title="证照信息">
          <ProFormText name="health_cert_no" label="健康证编号" width="md" />
          <ProFormDatePicker name="health_cert_expiry" label="健康证到期日" width="md" />
          <ProFormText name="food_safety_cert_no" label="食品安全证编号" width="md" />
          <ProFormDatePicker name="food_safety_cert_expiry" label="食品安全证到期日" width="md" />
        </StepsForm.StepForm>

        {/* Step 4: 确认提交 */}
        <StepsForm.StepForm name="confirm" title="确认提交">
          <Card style={{ background: '#fafafa' }}>
            <Descriptions title="请确认以下信息" column={2} bordered size="small">
              <Descriptions.Item label="说明">
                请确认上述所有信息无误后点击"提交"按钮完成员工创建。
                创建成功后将自动跳转至员工详情页。
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </StepsForm.StepForm>
      </StepsForm>
    </Card>
  );
}
