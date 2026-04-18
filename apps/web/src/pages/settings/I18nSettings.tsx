/**
 * i18n 管理页 — 翻译编辑 + LLM 批量自动翻译
 * 管理员查看文案 key + 各语种翻译，支持人工审核和 LLM 一键补齐
 */
import { useEffect, useState } from 'react';
import { Button, Card, message, Select, Space, Table, Tag } from 'antd';
import { apiClient } from '../../services/api';
import { useI18n, type Locale } from '../../i18n';

interface TextKey {
  id: string;
  namespace: string;
  key: string;
  default_value_zh: string;
  translations: Record<string, { value: string; reviewed: boolean; translator: string }>;
}

const LOCALES: Locale[] = ['zh-CN', 'zh-TW', 'en-US', 'vi-VN', 'th-TH', 'id-ID'];

export default function I18nSettings() {
  const { t } = useI18n();
  const [rows, setRows] = useState<TextKey[]>([]);
  const [loading, setLoading] = useState(false);
  const [targetLocale, setTargetLocale] = useState<Locale>('en-US');

  const reload = async () => {
    setLoading(true);
    try {
      // 简化：拉取所有语种 bundle，前端组装表格
      const bundles: Record<string, Record<string, Record<string, string>>> = {};
      for (const loc of LOCALES) {
        const r = await apiClient.get(`/api/v1/i18n/translations?locale=${loc}`);
        bundles[loc] = r.data || {};
      }
      // 以 zh-CN 为主列
      const list: TextKey[] = [];
      const zhBundle = bundles['zh-CN'] || {};
      for (const ns of Object.keys(zhBundle)) {
        for (const k of Object.keys(zhBundle[ns] || {})) {
          const tr: TextKey['translations'] = {};
          for (const loc of LOCALES) {
            tr[loc] = {
              value: bundles[loc]?.[ns]?.[k] || '',
              reviewed: true,
              translator: 'human',
            };
          }
          list.push({
            id: `${ns}.${k}`,
            namespace: ns,
            key: k,
            default_value_zh: zhBundle[ns][k],
            translations: tr,
          });
        }
      }
      setRows(list);
    } catch (e) {
      message.error(t('common.failed'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reload();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const autoTranslate = async () => {
    try {
      const r = await apiClient.post(`/api/v1/i18n/auto-translate?locale=${targetLocale}&limit=100`);
      message.success(`LLM 生成 ${r.data?.created || 0} 条（待人工审核）`);
      await reload();
    } catch {
      message.error(t('common.failed'));
    }
  };

  return (
    <Card title="i18n 翻译管理" extra={
      <Space>
        <Select
          size="small"
          value={targetLocale}
          onChange={(v) => setTargetLocale(v as Locale)}
          options={LOCALES.map((l) => ({ value: l, label: l }))}
          style={{ width: 120 }}
        />
        <Button type="primary" onClick={autoTranslate}>LLM 批量翻译缺失项</Button>
        <Button onClick={reload}>{t('common.loading')}</Button>
      </Space>
    }>
      <Table
        loading={loading}
        rowKey="id"
        dataSource={rows}
        size="small"
        scroll={{ x: 1400 }}
        columns={[
          { title: 'ns', dataIndex: 'namespace', width: 80, fixed: 'left' },
          { title: 'key', dataIndex: 'key', width: 160, fixed: 'left' },
          ...LOCALES.map((loc) => ({
            title: loc,
            key: loc,
            width: 180,
            render: (_: unknown, r: TextKey) => {
              const tr = r.translations[loc];
              if (!tr?.value) return <Tag color="red">缺失</Tag>;
              return <span>{tr.value}</span>;
            },
          })),
        ]}
      />
    </Card>
  );
}
