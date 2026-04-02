/**
 * FilterBar — 统一筛选栏
 *
 * 用于预警中心、预订台账等列表页顶部。
 * 支持：品牌/区域/门店/日期/状态/自定义字段 筛选
 */
import { Card, Space, Select, DatePicker, Input, Button } from 'antd';
import { SearchOutlined, ReloadOutlined } from '@ant-design/icons';

const { RangePicker } = DatePicker;

export interface FilterField {
  key: string;
  label: string;
  type: 'select' | 'date' | 'dateRange' | 'search';
  options?: { label: string; value: string }[];
  placeholder?: string;
  width?: number;
}

interface FilterBarProps {
  fields: FilterField[];
  values: Record<string, any>;
  onChange: (key: string, value: any) => void;
  onReset: () => void;
  onSearch?: () => void;
}

export function FilterBar({ fields, values, onChange, onReset, onSearch }: FilterBarProps) {
  return (
    <Card size="small" style={{ marginBottom: 16 }}>
      <Space wrap size={8}>
        {fields.map((f) => {
          if (f.type === 'select') {
            return (
              <Select
                key={f.key}
                value={values[f.key]}
                onChange={(v) => onChange(f.key, v)}
                options={f.options}
                placeholder={f.placeholder || f.label}
                allowClear
                style={{ width: f.width || 140 }}
              />
            );
          }
          if (f.type === 'date') {
            return (
              <DatePicker
                key={f.key}
                value={values[f.key]}
                onChange={(v) => onChange(f.key, v)}
                placeholder={f.placeholder || f.label}
                style={{ width: f.width || 140 }}
              />
            );
          }
          if (f.type === 'search') {
            return (
              <Input
                key={f.key}
                value={values[f.key]}
                onChange={(e) => onChange(f.key, e.target.value)}
                prefix={<SearchOutlined />}
                placeholder={f.placeholder || f.label}
                style={{ width: f.width || 180 }}
                allowClear
              />
            );
          }
          return null;
        })}
        <Button icon={<ReloadOutlined />} onClick={onReset}>重置</Button>
        {onSearch && <Button type="primary" icon={<SearchOutlined />} onClick={onSearch}>搜索</Button>}
      </Space>
    </Card>
  );
}
