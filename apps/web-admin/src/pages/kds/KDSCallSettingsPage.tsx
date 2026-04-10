/**
 * KDS 呼号与显示规则配置页面
 *
 * 功能：
 * - 门店选择
 * - 出单模式配置（IMMEDIATE 下单即推 / POST_PAYMENT 结账后推）
 * - 超时预警 + 颜色
 * - 渠道标识色（堂食/外带/外卖/自建外卖）
 * - 特殊菜品标识开关（赠菜/退菜/加单）
 * - 呼号音量 + 语音播报开关
 * - 实时预览卡片
 * - 保存 + 下发所有门店
 *
 * 注意：
 * - push_mode 写入后端 /api/v1/kds-config/push-mode/{store_id}
 * - 其余显示规则存 localStorage（前端本地配置，待后续 API 支持）
 *
 * 设计规范：admin.md + tokens.md
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Divider,
  Form,
  Row,
  Select,
  Slider,
  Space,
  Switch,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  DownloadOutlined,
  SaveOutlined,
  SoundOutlined,
} from '@ant-design/icons';
import {
  DEFAULT_KDS_CALL_CONFIG,
  type KDSCallConfig,
  type KDSPushMode,
  type StoreOption,
  fetchStoreOptions,
  getKDSPushMode,
  loadKDSCallConfig,
  saveKDSCallConfig,
  setKDSPushMode,
} from '../../api/kdsManageApi';

const { Title, Text, Paragraph } = Typography;

// ─── Design Token ──────────────────────────────────────────────────────────
const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_WARNING = '#BA7517';
const TX_DANGER = '#A32D2D';
const TX_BG_SECONDARY = '#F8F7F5';
const TX_TEXT_SECONDARY = '#5F5E5A';
const TX_NAVY = '#1E2A3A';

// ─── 预设颜色选项（替代 ColorPicker，兼容所有 antd 5.x 版本） ─────────────

const PRESET_COLORS = [
  { value: '#FF6B35', label: '橙色（主色）' },
  { value: '#A32D2D', label: '危险红' },
  { value: '#BA7517', label: '警告橙' },
  { value: '#0F6E56', label: '成功绿' },
  { value: '#185FA5', label: '信息蓝' },
  { value: '#9B59B6', label: '紫色' },
  { value: '#1E2A3A', label: '深蓝（档口）' },
  { value: '#E8B800', label: '金黄' },
  { value: '#2C2C2A', label: '深灰' },
  { value: '#B4B2A9', label: '浅灰' },
];

interface ColorSelectProps {
  value?: string;
  onChange?: (v: string) => void;
}

function ColorSelect({ value, onChange }: ColorSelectProps) {
  return (
    <Select
      value={value}
      onChange={onChange}
      style={{ width: 180 }}
      options={PRESET_COLORS.map((c) => ({
        value: c.value,
        label: (
          <Space size={8}>
            <span
              style={{
                display: 'inline-block',
                width: 16,
                height: 16,
                borderRadius: 3,
                background: c.value,
                border: '1px solid rgba(0,0,0,0.12)',
                flexShrink: 0,
              }}
            />
            {c.label}
          </Space>
        ),
      }))}
    />
  );
}

// ─── KDS 订单卡片预览 ──────────────────────────────────────────────────────

interface PreviewCardProps {
  config: KDSCallConfig;
}

function KDSPreviewCard({ config }: PreviewCardProps) {
  const [blink, setBlink] = useState(true);

  useEffect(() => {
    if (!config.urgent_blink) return;
    const timer = setInterval(() => setBlink((b) => !b), 800);
    return () => clearInterval(timer);
  }, [config.urgent_blink]);

  return (
    <div style={{ padding: '0 8px' }}>
      <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
        预览效果（模拟 KDS 屏幕显示）
      </Text>

      {/* 正常订单卡片 */}
      <div style={{
        background: '#1a1a2e',
        borderRadius: 8,
        padding: 16,
        marginBottom: 12,
        border: `2px solid ${config.channel_color_dine_in}`,
        color: '#fff',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <Space>
            <Tag color={config.channel_color_dine_in} style={{ margin: 0 }}>堂食</Tag>
            <Text style={{ color: '#fff', fontWeight: 700 }}>3桌</Text>
          </Space>
          <Badge
            count="正常"
            style={{ background: config.warn_color > '' ? TX_SUCCESS : TX_SUCCESS }}
          />
        </div>
        <div style={{ fontSize: 15, marginBottom: 4 }}>红烧排骨 × 1</div>
        <div style={{ fontSize: 15, marginBottom: 4 }}>清蒸鱼 × 1</div>
        {config.show_gift_badge && (
          <div style={{ fontSize: 13, color: '#ffd700' }}>🎁 赠：例汤 × 1</div>
        )}
        <div style={{
          marginTop: 8,
          fontSize: 12,
          color: config.timeout_color,
          fontWeight: 600,
        }}>
          已等待 8 分钟 ▲
        </div>
      </div>

      {/* 超时催单卡片 */}
      <div style={{
        background: '#2a1a1a',
        borderRadius: 8,
        padding: 16,
        border: `2px solid ${config.timeout_color}`,
        color: '#fff',
        opacity: config.urgent_blink ? (blink ? 1 : 0.65) : 1,
        transition: 'opacity 0.3s',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <Space>
            <Tag color={config.channel_color_takeaway} style={{ margin: 0 }}>外带</Tag>
            <Text style={{ color: '#fff', fontWeight: 700 }}>5号</Text>
          </Space>
          <Tag color={config.urgent_color} style={{ fontWeight: 700 }}>催单</Tag>
        </div>
        <div style={{ fontSize: 15, marginBottom: 4 }}>烤鸭饭 × 2</div>
        {config.show_addon_badge && (
          <div style={{ fontSize: 13, color: '#4fc3f7' }}>➕ 加菜：辣椒炒肉 × 1</div>
        )}
        <div style={{
          marginTop: 8,
          fontSize: 12,
          color: config.timeout_color,
          fontWeight: 700,
        }}>
          超时 03:45 ⚠
        </div>
      </div>

      {/* 渠道色说明 */}
      <div style={{ marginTop: 12 }}>
        <Space size={6} wrap>
          {[
            { label: '堂食', color: config.channel_color_dine_in },
            { label: '外卖', color: config.channel_color_delivery },
            { label: '外带', color: config.channel_color_takeaway },
            { label: '自建', color: config.channel_color_self_order },
          ].map(({ label, color }) => (
            <Tag
              key={label}
              style={{
                background: color,
                color: '#fff',
                border: 'none',
                fontWeight: 600,
                fontSize: 12,
              }}
            >
              {label}
            </Tag>
          ))}
        </Space>
      </div>
    </div>
  );
}

// ─── 主页面 ────────────────────────────────────────────────────────────────

export const KDSCallSettingsPage: React.FC = () => {
  const [stores, setStores] = useState<StoreOption[]>([]);
  const [storeId, setStoreId] = useState<string>('');
  const [config, setConfig] = useState<KDSCallConfig>({
    ...DEFAULT_KDS_CALL_CONFIG,
    store_id: '',
  });
  const [loadingMode, setLoadingMode] = useState(false);
  const [saving, setSaving] = useState(false);
  const [broadcasting, setBroadcasting] = useState(false);

  // 加载门店列表
  useEffect(() => {
    fetchStoreOptions().then((opts) => {
      setStores(opts);
      if (opts.length > 0) setStoreId(opts[0].value);
    });
  }, []);

  // 加载门店配置（本地 + 后端 push_mode）
  const loadConfig = useCallback(async () => {
    if (!storeId) return;

    // 先从 localStorage 读本地配置
    const localCfg = loadKDSCallConfig(storeId);
    setConfig(localCfg);

    // 再从后端同步 push_mode
    setLoadingMode(true);
    try {
      const res = await getKDSPushMode(storeId);
      setConfig((prev) => ({
        ...prev,
        push_mode: res.push_mode as KDSPushMode,
      }));
    } catch {
      // API 失败静默降级，使用本地配置
    } finally {
      setLoadingMode(false);
    }
  }, [storeId]);

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  // 更新配置字段
  const updateConfig = <K extends keyof KDSCallConfig>(key: K, value: KDSCallConfig[K]) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
  };

  // 保存（本地存储 + 后端 push_mode）
  const handleSave = async () => {
    if (!storeId) {
      message.warning('请先选择门店');
      return;
    }
    setSaving(true);
    try {
      // 1. 本地保存
      saveKDSCallConfig(config);

      // 2. push_mode 写入后端
      await setKDSPushMode(storeId, config.push_mode);

      message.success('配置已保存');
    } catch (err) {
      // 本地保存成功但后端失败
      message.warning('本地配置已保存，出单模式同步失败：' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setSaving(false);
    }
  };

  // 下发所有门店
  const handleBroadcast = async () => {
    if (!storeId) return;
    setBroadcasting(true);
    try {
      // 遍历所有门店，写入本地配置（push_mode 后端）
      const savePromises = stores.map(async (s) => {
        const storeCfg: KDSCallConfig = { ...config, store_id: s.value };
        saveKDSCallConfig(storeCfg);
        try {
          await setKDSPushMode(s.value, config.push_mode);
        } catch {
          // 单门店失败不影响整体
        }
      });
      await Promise.all(savePromises);
      message.success(`已下发到 ${stores.length} 个门店`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '下发失败');
    } finally {
      setBroadcasting(false);
    }
  };

  const formItemStyle: React.CSSProperties = { marginBottom: 16 };

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <Title level={2} style={{ margin: 0, color: '#2C2C2A' }}>
          KDS 呼号与显示配置
        </Title>
        <Paragraph style={{ color: TX_TEXT_SECONDARY, margin: '8px 0 0', fontSize: 14 }}>
          配置后厨 KDS 屏幕的颜色预警规则、渠道标识色、呼号音量等显示参数。
        </Paragraph>
      </div>

      {/* 门店选择 */}
      <Card style={{ marginBottom: 24 }} styles={{ body: { padding: '16px 24px' } }}>
        <Space size={16} wrap>
          <Space>
            <Text strong>门店：</Text>
            <Select
              options={stores}
              value={storeId || undefined}
              onChange={(v) => setStoreId(v)}
              placeholder="选择门店"
              style={{ width: 220 }}
              showSearch
              optionFilterProp="label"
              loading={loadingMode}
            />
          </Space>
          <Alert
            type="info"
            showIcon
            message="配置保存到本地，点击「下发所有门店」同步全部门店"
            style={{ padding: '4px 12px', fontSize: 12 }}
          />
        </Space>
      </Card>

      <Row gutter={24}>
        {/* 左侧：配置区域 */}
        <Col span={16}>
          {/* 出单推送模式 */}
          <Card
            title="出单推送模式"
            style={{ marginBottom: 24 }}
            styles={{ header: { background: TX_BG_SECONDARY } }}
          >
            <Form layout="vertical">
              <Form.Item
                label={
                  <Space>
                    <Text strong>推送模式</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      （影响后厨何时看到订单）
                    </Text>
                  </Space>
                }
                style={formItemStyle}
              >
                <Select
                  value={config.push_mode}
                  onChange={(v) => updateConfig('push_mode', v as KDSPushMode)}
                  options={[
                    {
                      value: 'IMMEDIATE',
                      label: (
                        <Space>
                          <Tag color="blue">即时推送</Tag>
                          <Text style={{ fontSize: 12 }}>下单后立即显示到 KDS</Text>
                        </Space>
                      ),
                    },
                    {
                      value: 'POST_PAYMENT',
                      label: (
                        <Space>
                          <Tag color="orange">结账后推送</Tag>
                          <Text style={{ fontSize: 12 }}>收银核销后才推送到 KDS</Text>
                        </Space>
                      ),
                    },
                  ]}
                  style={{ width: 320 }}
                />
              </Form.Item>
            </Form>
          </Card>

          {/* 超时预警规则 */}
          <Card
            title="超时预警规则"
            style={{ marginBottom: 24 }}
            styles={{ header: { background: TX_BG_SECONDARY } }}
          >
            <Form layout="vertical">
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item label="超时预警时长（秒）" style={formItemStyle}>
                    <Slider
                      min={60}
                      max={1800}
                      step={30}
                      value={config.timeout_warn_seconds}
                      onChange={(v) => updateConfig('timeout_warn_seconds', v)}
                      marks={{ 60: '1分', 300: '5分', 600: '10分', 1800: '30分' }}
                      tooltip={{
                        formatter: (v) => v ? `${Math.floor(v / 60)}分${v % 60 ? v % 60 + '秒' : ''}` : '',
                      }}
                    />
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      当前：{Math.floor(config.timeout_warn_seconds / 60)}分
                      {config.timeout_warn_seconds % 60 ? config.timeout_warn_seconds % 60 + '秒' : ''}
                    </Text>
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Row gutter={16}>
                    <Col span={12}>
                      <Form.Item label="预警颜色" style={formItemStyle}>
                        <ColorSelect
                          value={config.warn_color}
                          onChange={(v) => updateConfig('warn_color', v)}
                        />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item label="超时颜色" style={formItemStyle}>
                        <ColorSelect
                          value={config.timeout_color}
                          onChange={(v) => updateConfig('timeout_color', v)}
                        />
                      </Form.Item>
                    </Col>
                  </Row>
                </Col>
              </Row>

              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item label="催单闪烁" style={formItemStyle}>
                    <Switch
                      checked={config.urgent_blink}
                      onChange={(v) => updateConfig('urgent_blink', v)}
                      checkedChildren="开启"
                      unCheckedChildren="关闭"
                    />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="催单闪烁颜色" style={formItemStyle}>
                    <ColorSelect
                      value={config.urgent_color}
                      onChange={(v) => updateConfig('urgent_color', v)}
                    />
                  </Form.Item>
                </Col>
              </Row>
            </Form>
          </Card>

          {/* 渠道标识色 */}
          <Card
            title="渠道标识颜色"
            style={{ marginBottom: 24 }}
            styles={{ header: { background: TX_BG_SECONDARY } }}
          >
            <Form layout="vertical">
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item label="堂食" style={formItemStyle}>
                    <ColorSelect
                      value={config.channel_color_dine_in}
                      onChange={(v) => updateConfig('channel_color_dine_in', v)}
                    />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="外带" style={formItemStyle}>
                    <ColorSelect
                      value={config.channel_color_takeaway}
                      onChange={(v) => updateConfig('channel_color_takeaway', v)}
                    />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item label="平台外卖（美团/饿了么）" style={formItemStyle}>
                    <ColorSelect
                      value={config.channel_color_delivery}
                      onChange={(v) => updateConfig('channel_color_delivery', v)}
                    />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="自建外卖 / 小程序" style={formItemStyle}>
                    <ColorSelect
                      value={config.channel_color_self_order}
                      onChange={(v) => updateConfig('channel_color_self_order', v)}
                    />
                  </Form.Item>
                </Col>
              </Row>
            </Form>
          </Card>

          {/* 特殊菜品标识 */}
          <Card
            title="特殊菜品标识"
            style={{ marginBottom: 24 }}
            styles={{ header: { background: TX_BG_SECONDARY } }}
          >
            <Form layout="horizontal">
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item label="赠菜标识" style={formItemStyle}>
                    <Switch
                      checked={config.show_gift_badge}
                      onChange={(v) => updateConfig('show_gift_badge', v)}
                      checkedChildren="显示"
                      unCheckedChildren="隐藏"
                    />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label="退菜标识" style={formItemStyle}>
                    <Switch
                      checked={config.show_void_badge}
                      onChange={(v) => updateConfig('show_void_badge', v)}
                      checkedChildren="显示"
                      unCheckedChildren="隐藏"
                    />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label="加单标识" style={formItemStyle}>
                    <Switch
                      checked={config.show_addon_badge}
                      onChange={(v) => updateConfig('show_addon_badge', v)}
                      checkedChildren="显示"
                      unCheckedChildren="隐藏"
                    />
                  </Form.Item>
                </Col>
              </Row>
            </Form>
          </Card>

          {/* 呼号配置 */}
          <Card
            title={
              <Space>
                <SoundOutlined style={{ color: TX_PRIMARY }} />
                呼号与语音播报
              </Space>
            }
            style={{ marginBottom: 24 }}
            styles={{ header: { background: TX_BG_SECONDARY } }}
          >
            <Form layout="vertical">
              <Form.Item
                label={
                  <Space>
                    <Text>呼号音量</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>（{config.call_volume}%）</Text>
                  </Space>
                }
                style={formItemStyle}
              >
                <Slider
                  min={0}
                  max={100}
                  step={10}
                  value={config.call_volume}
                  onChange={(v) => updateConfig('call_volume', v)}
                  marks={{ 0: '静音', 50: '50%', 100: '最大' }}
                  style={{ maxWidth: 400 }}
                />
              </Form.Item>

              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item label="语音播报" style={formItemStyle}>
                    <Switch
                      checked={config.announcement_enabled}
                      onChange={(v) => updateConfig('announcement_enabled', v)}
                      checkedChildren="开启"
                      unCheckedChildren="关闭"
                    />
                  </Form.Item>
                </Col>
                {config.announcement_enabled && (
                  <Col span={16}>
                    <Form.Item
                      label={`播报间隔（每 ${config.announcement_interval_seconds} 秒重复一次）`}
                      style={formItemStyle}
                    >
                      <Slider
                        min={15}
                        max={300}
                        step={15}
                        value={config.announcement_interval_seconds}
                        onChange={(v) => updateConfig('announcement_interval_seconds', v)}
                        marks={{ 15: '15秒', 60: '1分', 180: '3分', 300: '5分' }}
                        style={{ maxWidth: 320 }}
                      />
                    </Form.Item>
                  </Col>
                )}
              </Row>
            </Form>
          </Card>

          {/* 保存按钮组 */}
          <Space size={12}>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={saving}
              onClick={handleSave}
              disabled={!storeId}
              style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
            >
              保存当前门店配置
            </Button>
            <Button
              icon={<DownloadOutlined />}
              loading={broadcasting}
              onClick={handleBroadcast}
              disabled={!storeId || stores.length === 0}
            >
              下发所有门店（{stores.length} 个）
            </Button>
          </Space>
        </Col>

        {/* 右侧：实时预览 */}
        <Col span={8}>
          <div style={{ position: 'sticky', top: 24 }}>
            <Card
              title={
                <Space>
                  <span
                    style={{
                      display: 'inline-block',
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: TX_SUCCESS,
                      animation: 'pulse 2s infinite',
                    }}
                  />
                  实时预览
                </Space>
              }
              style={{ background: TX_NAVY, color: '#fff', borderRadius: 8 }}
              styles={{
                header: {
                  background: TX_NAVY,
                  color: '#fff',
                  borderBottom: '1px solid rgba(255,255,255,0.1)',
                },
                body: { background: TX_NAVY, padding: 16 },
              }}
            >
              <KDSPreviewCard config={config} />
            </Card>

            <Divider style={{ borderColor: '#E8E6E1' }} />

            {/* 当前配置摘要 */}
            <Card
              size="small"
              title="配置摘要"
              styles={{ body: { background: TX_BG_SECONDARY } }}
            >
              <Space direction="vertical" size={6} style={{ width: '100%', fontSize: 13 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <Text type="secondary">推送模式</Text>
                  <Tag color={config.push_mode === 'IMMEDIATE' ? 'blue' : 'orange'}>
                    {config.push_mode === 'IMMEDIATE' ? '即时推送' : '结账后推'}
                  </Tag>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <Text type="secondary">超时预警</Text>
                  <Text>
                    {Math.floor(config.timeout_warn_seconds / 60)}分钟
                  </Text>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <Text type="secondary">催单闪烁</Text>
                  <Badge
                    status={config.urgent_blink ? 'success' : 'default'}
                    text={config.urgent_blink ? '开启' : '关闭'}
                  />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <Text type="secondary">呼号音量</Text>
                  <Text>{config.call_volume}%</Text>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <Text type="secondary">语音播报</Text>
                  <Badge
                    status={config.announcement_enabled ? 'success' : 'default'}
                    text={config.announcement_enabled ? '开启' : '关闭'}
                  />
                </div>
              </Space>
            </Card>
          </div>
        </Col>
      </Row>
    </div>
  );
};

export default KDSCallSettingsPage;
