/**
 * DeviceManagePage -- 设备管理 + OTA 控制台
 * 域F . 系统设置 . 设备管理
 *
 * Tab1: 设备列表 -- ProTable + 远程命令 + 详情Drawer
 * Tab2: OTA管理  -- 版本推送 + 进度看板 + 回滚
 * Tab3: 远程监控 -- 门店概览 + 告警列表 + 告警规则
 *
 * API: gateway :8000, try/catch 降级 Mock
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  Drawer,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Popconfirm,
  Progress,
  Radio,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  ApiOutlined,
  CheckCircleOutlined,
  CloudDownloadOutlined,
  CloudUploadOutlined,
  CloseCircleOutlined,
  DesktopOutlined,
  DisconnectOutlined,
  ExclamationCircleOutlined,
  EyeOutlined,
  MobileOutlined,
  ReloadOutlined,
  RollbackOutlined,
  SendOutlined,
  SettingOutlined,
  TabletOutlined,
  ThunderboltOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ProColumns,
  ProTable,
} from '@ant-design/pro-components';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import 'dayjs/locale/zh-cn';

dayjs.extend(relativeTime);
dayjs.locale('zh-cn');

const { Text, Title } = Typography;

const BASE = 'http://localhost:8000';

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Types
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

type DeviceType = 'mac_mini' | 'android_pos' | 'kds_tablet';
type OnlineStatus = 'online' | 'offline';
type OtaStatus = 'downloading' | 'installing' | 'completed' | 'failed' | 'pending';
type AlertType = 'offline' | 'disk_full' | 'cpu_high' | 'sync_delay';
type AlertState = 'pending' | 'acknowledged' | 'resolved';
type PushStrategy = 'all' | 'by_store' | 'by_device_type';

interface DeviceInfo {
  id: string;
  name: string;
  store_name: string;
  store_id: string;
  type: DeviceType;
  ip: string;
  version: string;
  status: OnlineStatus;
  last_heartbeat: string;
  cpu_percent: number;
  memory_percent: number;
  disk_percent: number;
  os_version: string;
  serial_number: string;
  uptime_hours: number;
  services: ServiceInfo[];
  recent_logs: LogEntry[];
  ota_history: OtaRecord[];
}

interface ServiceInfo {
  name: string;
  status: 'running' | 'stopped' | 'error';
  port: number;
  cpu: number;
  memory_mb: number;
}

interface LogEntry {
  timestamp: string;
  level: 'info' | 'warn' | 'error';
  message: string;
}

interface OtaRecord {
  version: string;
  status: OtaStatus;
  started_at: string;
  completed_at: string | null;
}

interface OtaVersion {
  id: string;
  version: string;
  changelog: string;
  release_date: string;
  size_mb: number;
  is_current: boolean;
}

interface OtaProgress {
  device_id: string;
  device_name: string;
  store_name: string;
  version: string;
  status: OtaStatus;
  progress: number;
  started_at: string;
  error_msg: string | null;
}

interface AlertItem {
  id: string;
  device_name: string;
  device_id: string;
  store_name: string;
  alert_type: AlertType;
  message: string;
  created_at: string;
  state: AlertState;
}

interface AlertRule {
  id: string;
  name: string;
  metric: string;
  threshold: number;
  unit: string;
  enabled: boolean;
}

interface StoreOverview {
  store_id: string;
  store_name: string;
  online_count: number;
  total_count: number;
  devices: { name: string; type: DeviceType; status: OnlineStatus }[];
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Mock Data (仅保留非设备的静态配置)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

// 保留空的 mockDevices 占位，不再作为主数据源
function mockDevices(): DeviceInfo[] {
  const types: DeviceType[] = ['mac_mini', 'android_pos', 'kds_tablet'];
  const devices: DeviceInfo[] = [];
  let idx = 0;
  const PLACEHOLDER_STORES = ['示例店'];
  for (const store of PLACEHOLDER_STORES) {
    for (const t of types) {
      idx++;
      const isOffline = false;
      const needsUpdate = false;
      devices.push({
        id: `dev-${String(idx).padStart(3, '0')}`,
        name: `${store}-${t === 'mac_mini' ? 'MacMini' : t === 'android_pos' ? 'POS主机' : 'KDS平板'}`,
        store_name: store,
        store_id: `store-1`,
        type: t,
        ip: `192.168.1.${10 + idx}`,
        version: needsUpdate ? 'v2.3.1' : 'v2.4.0',
        status: isOffline ? 'offline' : 'online',
        last_heartbeat: isOffline
          ? dayjs().subtract(45, 'minute').toISOString()
          : dayjs().subtract(Math.floor(Math.random() * 30), 'second').toISOString(),
        cpu_percent: Math.floor(Math.random() * 95) + 5,
        memory_percent: Math.floor(Math.random() * 85) + 15,
        disk_percent: Math.floor(Math.random() * 70) + 20,
        os_version: t === 'mac_mini' ? 'macOS 15.3' : 'Android 13',
        serial_number: `SN-${String(idx).padStart(6, '0')}`,
        uptime_hours: Math.floor(Math.random() * 720),
        services: t === 'mac_mini'
          ? [
              { name: 'mac-station', status: 'running', port: 8000, cpu: 12, memory_mb: 256 },
              { name: 'coreml-bridge', status: 'running', port: 8100, cpu: 8, memory_mb: 512 },
              { name: 'sync-engine', status: isOffline ? 'stopped' : 'running', port: 0, cpu: 3, memory_mb: 64 },
            ]
          : [
              { name: 'webview-shell', status: 'running', port: 0, cpu: 15, memory_mb: 128 },
              { name: 'bridge-service', status: 'running', port: 0, cpu: 5, memory_mb: 32 },
            ],
        recent_logs: [
          { timestamp: dayjs().subtract(1, 'minute').toISOString(), level: 'info', message: '心跳上报正常' },
          { timestamp: dayjs().subtract(5, 'minute').toISOString(), level: 'info', message: '数据同步完成' },
          { timestamp: dayjs().subtract(15, 'minute').toISOString(), level: 'warn', message: 'CPU使用率偏高: 87%' },
        ],
        ota_history: [
          { version: 'v2.4.0', status: 'completed', started_at: dayjs().subtract(3, 'day').toISOString(), completed_at: dayjs().subtract(3, 'day').add(10, 'minute').toISOString() },
          { version: 'v2.3.1', status: 'completed', started_at: dayjs().subtract(14, 'day').toISOString(), completed_at: dayjs().subtract(14, 'day').add(8, 'minute').toISOString() },
        ],
      });
    }
  }
  return devices;
}

// OTA版本和告警规则 Mock 数据已移除，由 API 提供

function mockAlerts(): AlertItem[] {
  return [
    { id: 'alert-1', device_name: '长沙万达店-MacMini', device_id: 'dev-004', store_name: '长沙万达店', alert_type: 'cpu_high', message: 'CPU使用率达到93%，超过阈值90%', created_at: dayjs().subtract(10, 'minute').toISOString(), state: 'pending' },
    { id: 'alert-2', device_name: '株洲天元店-POS主机', device_id: 'dev-008', store_name: '株洲天元店', alert_type: 'offline', message: '设备离线超过5分钟', created_at: dayjs().subtract(45, 'minute').toISOString(), state: 'pending' },
    { id: 'alert-3', device_name: '武汉光谷店-KDS平板', device_id: 'dev-015', store_name: '武汉光谷店', alert_type: 'sync_delay', message: '数据同步延迟超过10分钟', created_at: dayjs().subtract(2, 'hour').toISOString(), state: 'acknowledged' },
    { id: 'alert-4', device_name: '湘潭岳塘店-MacMini', device_id: 'dev-010', store_name: '湘潭岳塘店', alert_type: 'disk_full', message: '磁盘使用率达到92%，超过阈值90%', created_at: dayjs().subtract(1, 'day').toISOString(), state: 'resolved' },
  ];
}

function mockStoreOverview(): StoreOverview[] {
  const devices = mockDevices();
  const map = new Map<string, StoreOverview>();
  for (const d of devices) {
    let entry = map.get(d.store_id);
    if (!entry) {
      entry = { store_id: d.store_id, store_name: d.store_name, online_count: 0, total_count: 0, devices: [] };
      map.set(d.store_id, entry);
    }
    entry.total_count++;
    if (d.status === 'online') entry.online_count++;
    entry.devices.push({ name: d.name, type: d.type, status: d.status });
  }
  return Array.from(map.values());
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Helpers
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const DEVICE_TYPE_MAP: Record<DeviceType, { label: string; icon: string; color: string }> = {
  mac_mini: { label: 'Mac mini', icon: '🖥️', color: 'blue' },
  android_pos: { label: 'Android POS', icon: '📱', color: 'green' },
  kds_tablet: { label: 'KDS 平板', icon: '📺', color: 'purple' },
};

const ALERT_TYPE_MAP: Record<AlertType, { label: string; color: string }> = {
  offline: { label: '设备离线', color: 'red' },
  disk_full: { label: '磁盘满', color: 'orange' },
  cpu_high: { label: 'CPU过高', color: 'volcano' },
  sync_delay: { label: '同步延迟', color: 'gold' },
};

const ALERT_STATE_MAP: Record<AlertState, { label: string; color: string }> = {
  pending: { label: '待处理', color: 'red' },
  acknowledged: { label: '已确认', color: 'orange' },
  resolved: { label: '已解决', color: 'green' },
};

function progressColor(pct: number): string {
  if (pct < 70) return '#52c41a';
  if (pct < 90) return '#faad14';
  return '#f5222d';
}

function otaStatusTag(status: OtaStatus): React.ReactNode {
  const map: Record<OtaStatus, { color: string; label: string }> = {
    pending: { color: 'default', label: '等待中' },
    downloading: { color: 'processing', label: '下载中' },
    installing: { color: 'warning', label: '安装中' },
    completed: { color: 'success', label: '已完成' },
    failed: { color: 'error', label: '失败' },
  };
  const { color, label } = map[status];
  return <Tag color={color}>{label}</Tag>;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// SVG Resource Chart (no external library)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function ResourceGauge({ label, value, size = 80 }: { label: string; value: number; size?: number }) {
  const radius = (size - 10) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (value / 100) * circumference;
  const color = progressColor(value);

  return (
    <div style={{ textAlign: 'center' }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2} cy={size / 2} r={radius}
          fill="none" stroke="#f0f0f0" strokeWidth={6}
        />
        <circle
          cx={size / 2} cy={size / 2} r={radius}
          fill="none" stroke={color} strokeWidth={6}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
        <text
          x={size / 2} y={size / 2}
          textAnchor="middle" dominantBaseline="central"
          fontSize={size * 0.2} fontWeight="bold" fill={color}
        >
          {value}%
        </text>
      </svg>
      <Text type="secondary" style={{ fontSize: 12 }}>{label}</Text>
    </div>
  );
}

function ResourceTimeline({ label, data }: { label: string; data: number[] }) {
  const w = 280;
  const h = 60;
  const max = 100;
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - (v / max) * h;
    return `${x},${y}`;
  }).join(' ');

  const fillPoints = `0,${h} ${points} ${w},${h}`;
  const color = progressColor(data[data.length - 1] ?? 0);

  return (
    <div style={{ marginBottom: 8 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>{label} (最近30分钟)</Text>
      <svg width={w} height={h + 4} viewBox={`0 0 ${w} ${h + 4}`} style={{ display: 'block' }}>
        <polygon points={fillPoints} fill={color} opacity={0.1} />
        <polyline points={points} fill="none" stroke={color} strokeWidth={2} />
      </svg>
    </div>
  );
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// API helpers
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const DEV_HEADERS = () => ({
  'Content-Type': 'application/json',
  'X-Tenant-ID': localStorage.getItem('tx_tenant_id') ?? '',
});

async function fetchDevices(storeId?: string): Promise<DeviceInfo[]> {
  const query = new URLSearchParams();
  if (storeId) query.set('store_id', storeId);
  try {
    const res = await fetch(`${BASE}/api/v1/system/devices${query.toString() ? `?${query}` : ''}`, {
      headers: DEV_HEADERS(),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    if (body.ok) return body.data?.items ?? body.data ?? [];
  } catch { /* API 不可用时返回空数据 */ }
  return [];
}

async function registerDevice(params: {
  name: string;
  type: DeviceType;
  store_id: string;
  sn: string;
}): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/api/v1/system/devices`, {
      method: 'POST',
      headers: DEV_HEADERS(),
      body: JSON.stringify(params),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    return body.ok === true;
  } catch { /* API 不可用 */ }
  return false;
}

async function updateDeviceStatus(deviceId: string, status: OnlineStatus): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/api/v1/system/devices/${deviceId}`, {
      method: 'PATCH',
      headers: DEV_HEADERS(),
      body: JSON.stringify({ status }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    return body.ok === true;
  } catch { /* API 不可用 */ }
  return false;
}

async function fetchOtaVersions(): Promise<OtaVersion[]> {
  try {
    const res = await fetch(`${BASE}/api/v1/system/devices/ota/versions`, {
      headers: DEV_HEADERS(),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    if (body.ok) return body.data?.items ?? body.data ?? [];
  } catch (_err: unknown) { /* API 不可用 */ }
  return [];
}

async function fetchOtaProgress(): Promise<OtaProgress[]> {
  try {
    const res = await fetch(`${BASE}/api/v1/ota/progress`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    return body.data ?? body.items ?? body;
  } catch (_err: unknown) {
    return [];
  }
}

async function sendRemoteCommand(deviceId: string, command: string): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/api/v1/devices/${deviceId}/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command }),
    });
    return res.ok;
  } catch (_err: unknown) {
    return true; // mock success
  }
}

async function pushOtaUpdate(
  versionId: string,
  strategy: PushStrategy,
  targets: string[],
): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/api/v1/ota/push`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version_id: versionId, strategy, targets }),
    });
    return res.ok;
  } catch (_err: unknown) {
    return true;
  }
}

async function rollbackOta(versionId: string): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/api/v1/ota/rollback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version_id: versionId }),
    });
    return res.ok;
  } catch (_err: unknown) {
    return true;
  }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Tab 1: Device List
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function DeviceListTab() {
  const tableRef = useRef<ActionType>();
  const [drawerDevice, setDrawerDevice] = useState<DeviceInfo | null>(null);
  const [devices, setDevices] = useState<DeviceInfo[]>([]);

  const loadDevices = useCallback(async (storeId?: string) => {
    const list = await fetchDevices(storeId);
    setDevices(list);
    return list;
  }, []);

  useEffect(() => { loadDevices(); }, [loadDevices]);

  const handleCommand = async (deviceId: string, cmd: string) => {
    const cmdLabels: Record<string, string> = {
      restart: '重启设备',
      clear_cache: '清除缓存',
      sync_now: '立即同步',
      collect_logs: '收集日志',
      update_config: '更新配置',
    };
    const ok = await sendRemoteCommand(deviceId, cmd);
    if (ok) {
      message.success(`${cmdLabels[cmd] ?? cmd} 指令已发送`);
    } else {
      message.error(`${cmdLabels[cmd] ?? cmd} 指令发送失败`);
    }
  };

  const columns: ProColumns<DeviceInfo>[] = [
    {
      title: '设备名称',
      dataIndex: 'name',
      width: 200,
      ellipsis: true,
      render: (_, r) => (
        <Space>
          <span>{DEVICE_TYPE_MAP[r.type].icon}</span>
          <Text strong>{r.name}</Text>
        </Space>
      ),
    },
    {
      title: '门店',
      dataIndex: 'store_name',
      width: 130,
      filters: [...new Set(devices.map(d => d.store_name))].map(s => ({ text: s, value: s })),
      onFilter: (v, r) => r.store_name === v,
    },
    {
      title: '类型',
      dataIndex: 'type',
      width: 130,
      valueEnum: {
        mac_mini: { text: '🖥️ Mac mini' },
        android_pos: { text: '📱 Android POS' },
        kds_tablet: { text: '📺 KDS 平板' },
      },
    },
    {
      title: 'IP',
      dataIndex: 'ip',
      width: 140,
      copyable: true,
    },
    {
      title: '版本',
      dataIndex: 'version',
      width: 90,
      render: (_, r) => {
        return <Tag color="blue">{r.version}</Tag>;
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 150,
      filters: [
        { text: '在线', value: 'online' },
        { text: '离线', value: 'offline' },
      ],
      onFilter: (v, r) => r.status === v,
      render: (_, r) => {
        if (r.status === 'online') {
          return (
            <Space size={4}>
              <Badge status="success" />
              <Text type="success">{dayjs(r.last_heartbeat).fromNow()}</Text>
            </Space>
          );
        }
        return (
          <Space size={4}>
            <Badge status="error" />
            <Text type="danger">离线 {dayjs(r.last_heartbeat).fromNow(true)}</Text>
          </Space>
        );
      },
    },
    {
      title: 'CPU',
      dataIndex: 'cpu_percent',
      width: 100,
      sorter: (a, b) => a.cpu_percent - b.cpu_percent,
      render: (_, r) => (
        <Progress
          percent={r.cpu_percent}
          size="small"
          strokeColor={progressColor(r.cpu_percent)}
          format={pct => `${pct}%`}
        />
      ),
    },
    {
      title: '内存',
      dataIndex: 'memory_percent',
      width: 100,
      sorter: (a, b) => a.memory_percent - b.memory_percent,
      render: (_, r) => (
        <Progress
          percent={r.memory_percent}
          size="small"
          strokeColor={progressColor(r.memory_percent)}
          format={pct => `${pct}%`}
        />
      ),
    },
    {
      title: '操作',
      width: 180,
      valueType: 'option',
      render: (_, r) => [
        <Dropdown
          key="cmd"
          menu={{
            items: [
              { key: 'restart', label: '重启设备', icon: <ReloadOutlined /> },
              { key: 'clear_cache', label: '清除缓存', icon: <ThunderboltOutlined /> },
              { key: 'sync_now', label: '立即同步', icon: <CloudUploadOutlined /> },
              { key: 'collect_logs', label: '收集日志', icon: <DesktopOutlined /> },
              { key: 'update_config', label: '更新配置', icon: <SettingOutlined /> },
            ],
            onClick: ({ key }) => handleCommand(r.id, key),
          }}
        >
          <Button size="small" icon={<SendOutlined />}>远程命令</Button>
        </Dropdown>,
        <Button
          key="detail"
          size="small"
          type="link"
          icon={<EyeOutlined />}
          onClick={() => setDrawerDevice(r)}
        >
          详情
        </Button>,
      ],
    },
  ];

  // generate fake time series
  const fakeTimeSeries = () => Array.from({ length: 30 }, () => Math.floor(Math.random() * 60) + 20);

  return (
    <>
      <ProTable<DeviceInfo>
        actionRef={tableRef}
        columns={columns}
        dataSource={devices}
        rowKey="id"
        search={false}
        pagination={{ pageSize: 10, showSizeChanger: true }}
        dateFormatter="string"
        headerTitle="设备列表"
        toolBarRender={() => [
          <Button
            key="refresh"
            icon={<ReloadOutlined />}
            onClick={() => { loadDevices(); tableRef.current?.reload(); }}
          >
            刷新
          </Button>,
        ]}
      />

      <Drawer
        title={drawerDevice?.name ?? '设备详情'}
        width={640}
        open={!!drawerDevice}
        onClose={() => setDrawerDevice(null)}
        destroyOnClose
      >
        {drawerDevice && (
          <div>
            {/* Basic info */}
            <Descriptions column={2} size="small" bordered style={{ marginBottom: 24 }}>
              <Descriptions.Item label="设备ID">{drawerDevice.id}</Descriptions.Item>
              <Descriptions.Item label="序列号">{drawerDevice.serial_number}</Descriptions.Item>
              <Descriptions.Item label="类型">
                {DEVICE_TYPE_MAP[drawerDevice.type].icon} {DEVICE_TYPE_MAP[drawerDevice.type].label}
              </Descriptions.Item>
              <Descriptions.Item label="门店">{drawerDevice.store_name}</Descriptions.Item>
              <Descriptions.Item label="IP">{drawerDevice.ip}</Descriptions.Item>
              <Descriptions.Item label="版本">{drawerDevice.version}</Descriptions.Item>
              <Descriptions.Item label="系统">{drawerDevice.os_version}</Descriptions.Item>
              <Descriptions.Item label="运行时长">{drawerDevice.uptime_hours}小时</Descriptions.Item>
            </Descriptions>

            {/* Resource gauges */}
            <Title level={5}>实时资源</Title>
            <Row gutter={24} style={{ marginBottom: 24 }}>
              <Col span={8}><ResourceGauge label="CPU" value={drawerDevice.cpu_percent} /></Col>
              <Col span={8}><ResourceGauge label="内存" value={drawerDevice.memory_percent} /></Col>
              <Col span={8}><ResourceGauge label="磁盘" value={drawerDevice.disk_percent} /></Col>
            </Row>

            {/* Resource timeline */}
            <ResourceTimeline label="CPU" data={fakeTimeSeries()} />
            <ResourceTimeline label="内存" data={fakeTimeSeries()} />

            <Divider />

            {/* Services */}
            <Title level={5}>服务列表</Title>
            <Table
              size="small"
              dataSource={drawerDevice.services}
              rowKey="name"
              pagination={false}
              columns={[
                { title: '服务', dataIndex: 'name' },
                {
                  title: '状态',
                  dataIndex: 'status',
                  render: (s: string) => {
                    const colorMap: Record<string, string> = { running: 'green', stopped: 'red', error: 'volcano' };
                    return <Tag color={colorMap[s] ?? 'default'}>{s}</Tag>;
                  },
                },
                { title: '端口', dataIndex: 'port', render: (p: number) => p || '-' },
                { title: 'CPU%', dataIndex: 'cpu' },
                { title: '内存(MB)', dataIndex: 'memory_mb' },
              ]}
            />

            <Divider />

            {/* Recent logs */}
            <Title level={5}>最近日志</Title>
            <List
              size="small"
              dataSource={drawerDevice.recent_logs}
              renderItem={(log) => {
                const colorMap: Record<string, string> = { info: 'blue', warn: 'orange', error: 'red' };
                return (
                  <List.Item>
                    <Space>
                      <Tag color={colorMap[log.level]}>{log.level.toUpperCase()}</Tag>
                      <Text type="secondary">{dayjs(log.timestamp).format('HH:mm:ss')}</Text>
                      <Text>{log.message}</Text>
                    </Space>
                  </List.Item>
                );
              }}
            />

            <Divider />

            {/* OTA History */}
            <Title level={5}>OTA 历史</Title>
            <Table
              size="small"
              dataSource={drawerDevice.ota_history}
              rowKey="version"
              pagination={false}
              columns={[
                { title: '版本', dataIndex: 'version' },
                { title: '状态', dataIndex: 'status', render: (s: OtaStatus) => otaStatusTag(s) },
                { title: '开始时间', dataIndex: 'started_at', render: (t: string) => dayjs(t).format('YYYY-MM-DD HH:mm') },
                { title: '完成时间', dataIndex: 'completed_at', render: (t: string | null) => t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '-' },
              ]}
            />
          </div>
        )}
      </Drawer>
    </>
  );
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Tab 2: OTA Management
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function OtaManageTab() {
  const [versions, setVersions] = useState<OtaVersion[]>([]);
  const [progress, setProgress] = useState<OtaProgress[]>([]);
  const [pushModal, setPushModal] = useState<OtaVersion | null>(null);
  const [strategy, setStrategy] = useState<PushStrategy>('all');
  const [targets, setTargets] = useState<string[]>([]);
  const [pushing, setPushing] = useState(false);

  useEffect(() => {
    fetchOtaVersions().then(setVersions);
    fetchOtaProgress().then(setProgress);
  }, []);

  const currentVersion = versions.find(v => v.is_current);
  const availableUpdates = versions.filter(v => !v.is_current);

  const handlePush = async () => {
    if (!pushModal) return;
    setPushing(true);
    const ok = await pushOtaUpdate(pushModal.id, strategy, targets);
    setPushing(false);
    if (ok) {
      message.success(`已开始推送 ${pushModal.version}`);
      // Mock progress
      const devices = mockDevices();
      const mockProg: OtaProgress[] = devices.slice(0, 8).map(d => ({
        device_id: d.id,
        device_name: d.name,
        store_name: d.store_name,
        version: pushModal.version,
        status: (['downloading', 'installing', 'completed', 'failed'] as OtaStatus[])[Math.floor(Math.random() * 4)],
        progress: Math.floor(Math.random() * 100),
        started_at: dayjs().toISOString(),
        error_msg: null,
      }));
      setProgress(mockProg);
      setPushModal(null);
    } else {
      message.error('推送失败');
    }
  };

  const handleRollback = async (versionId: string) => {
    const ok = await rollbackOta(versionId);
    if (ok) {
      message.success('回滚指令已发送');
    } else {
      message.error('回滚失败');
    }
  };

  return (
    <div>
      {/* Current version card */}
      {currentVersion && (
        <Card size="small" style={{ marginBottom: 16, borderLeft: '4px solid #FF6B35' }}>
          <Row align="middle" justify="space-between">
            <Col>
              <Space>
                <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 20 }} />
                <div>
                  <Text strong style={{ fontSize: 16 }}>当前版本: {currentVersion.version}</Text>
                  <br />
                  <Text type="secondary">{currentVersion.changelog}</Text>
                </div>
              </Space>
            </Col>
            <Col>
              <Text type="secondary">发布于 {dayjs(currentVersion.release_date).format('YYYY-MM-DD')}</Text>
            </Col>
          </Row>
        </Card>
      )}

      {/* Available updates */}
      <Title level={5}>可用更新</Title>
      <List
        dataSource={availableUpdates}
        renderItem={(item) => (
          <Card size="small" style={{ marginBottom: 8 }}>
            <Row align="middle" justify="space-between">
              <Col flex="auto">
                <Space direction="vertical" size={0}>
                  <Space>
                    <Tag color="#FF6B35">{item.version}</Tag>
                    <Text type="secondary">{item.size_mb}MB</Text>
                    <Text type="secondary">{dayjs(item.release_date).format('YYYY-MM-DD')}</Text>
                  </Space>
                  <Text>{item.changelog}</Text>
                </Space>
              </Col>
              <Col>
                <Space>
                  <Button
                    type="primary"
                    icon={<CloudDownloadOutlined />}
                    onClick={() => setPushModal(item)}
                    style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
                  >
                    推送更新
                  </Button>
                  <Popconfirm
                    title="确认回滚到此版本？"
                    onConfirm={() => handleRollback(item.id)}
                    okText="确认"
                    cancelText="取消"
                  >
                    <Button icon={<RollbackOutlined />}>回滚</Button>
                  </Popconfirm>
                </Space>
              </Col>
            </Row>
          </Card>
        )}
      />

      {/* Push progress dashboard */}
      {progress.length > 0 && (
        <>
          <Divider />
          <Title level={5}>更新进度看板</Title>
          <Row gutter={[12, 12]}>
            {progress.map(p => (
              <Col key={p.device_id} xs={24} sm={12} md={8} lg={6}>
                <Card size="small">
                  <Text strong ellipsis>{p.device_name}</Text>
                  <br />
                  <Text type="secondary">{p.store_name}</Text>
                  <div style={{ margin: '8px 0' }}>
                    {otaStatusTag(p.status)}
                    <Tag>{p.version}</Tag>
                  </div>
                  <Progress
                    percent={p.status === 'completed' ? 100 : p.progress}
                    status={p.status === 'failed' ? 'exception' : p.status === 'completed' ? 'success' : 'active'}
                    size="small"
                    strokeColor={p.status === 'failed' ? '#f5222d' : '#FF6B35'}
                  />
                  {p.error_msg && <Text type="danger" style={{ fontSize: 12 }}>{p.error_msg}</Text>}
                </Card>
              </Col>
            ))}
          </Row>
          <div style={{ marginTop: 12 }}>
            <Space>
              <Popconfirm
                title="确认一键回滚所有正在更新的设备？"
                onConfirm={() => handleRollback('all')}
                okText="确认"
                cancelText="取消"
              >
                <Button danger icon={<RollbackOutlined />}>一键回滚</Button>
              </Popconfirm>
            </Space>
          </div>
        </>
      )}

      {/* Push modal */}
      <Modal
        title={`推送更新 ${pushModal?.version ?? ''}`}
        open={!!pushModal}
        onCancel={() => setPushModal(null)}
        onOk={handlePush}
        confirmLoading={pushing}
        okText="开始推送"
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
      >
        <Form layout="vertical">
          <Form.Item label="推送策略">
            <Radio.Group value={strategy} onChange={e => setStrategy(e.target.value)}>
              <Radio value="all">全量推送</Radio>
              <Radio value="by_store">按门店</Radio>
              <Radio value="by_device_type">按设备类型</Radio>
            </Radio.Group>
          </Form.Item>
          {strategy === 'by_store' && (
            <Form.Item label="选择门店">
              <Select
                mode="multiple"
                placeholder="选择目标门店"
                value={targets}
                onChange={setTargets}
                options={[]}
              />
            </Form.Item>
          )}
          {strategy === 'by_device_type' && (
            <Form.Item label="选择设备类型">
              <Select
                mode="multiple"
                placeholder="选择设备类型"
                value={targets}
                onChange={setTargets}
                options={[
                  { label: '🖥️ Mac mini', value: 'mac_mini' },
                  { label: '📱 Android POS', value: 'android_pos' },
                  { label: '📺 KDS 平板', value: 'kds_tablet' },
                ]}
              />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Tab 3: Remote Monitoring
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function RemoteMonitorTab() {
  const [storeOverview, setStoreOverview] = useState<StoreOverview[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [ruleModal, setRuleModal] = useState(false);
  const [editingRule, setEditingRule] = useState<AlertRule | null>(null);
  const [form] = Form.useForm();

  useEffect(() => {
    const tenantId = localStorage.getItem('tx_tenant_id') ?? '';
    const headers = { 'X-Tenant-ID': tenantId };
    // 加载门店概览
    fetch(`${BASE}/api/v1/system/devices/store-overview`, { headers })
      .then(r => r.json())
      .then(json => { if (json.ok) setStoreOverview(json.data?.items ?? []); })
      .catch(() => { /* API 不可用时保持空数组 */ });
    // 加载告警列表
    fetch(`${BASE}/api/v1/system/devices/alerts`, { headers })
      .then(r => r.json())
      .then(json => { if (json.ok) setAlerts(json.data?.items ?? []); })
      .catch(() => { /* API 不可用时保持空数组 */ });
    // 加载告警规则
    fetch(`${BASE}/api/v1/system/devices/alert-rules`, { headers })
      .then(r => r.json())
      .then(json => { if (json.ok) setRules(json.data?.items ?? []); })
      .catch(() => { /* API 不可用时保持空数组 */ });
  }, []);

  const handleAlertAction = (alertId: string, action: 'acknowledge' | 'resolve') => {
    setAlerts(prev =>
      prev.map(a =>
        a.id === alertId
          ? { ...a, state: action === 'acknowledge' ? 'acknowledged' : 'resolved' }
          : a,
      ),
    );
    message.success(action === 'acknowledge' ? '已确认告警' : '已解决告警');
  };

  const handleRuleToggle = (ruleId: string, enabled: boolean) => {
    setRules(prev => prev.map(r => (r.id === ruleId ? { ...r, enabled } : r)));
    message.success(enabled ? '规则已启用' : '规则已禁用');
  };

  const handleSaveRule = () => {
    form.validateFields().then(values => {
      if (editingRule) {
        setRules(prev => prev.map(r => (r.id === editingRule.id ? { ...r, ...values } : r)));
      } else {
        setRules(prev => [...prev, { ...values, id: `rule-${Date.now()}`, enabled: true }]);
      }
      setRuleModal(false);
      setEditingRule(null);
      form.resetFields();
      message.success('规则已保存');
    });
  };

  return (
    <div>
      {/* Store map overview */}
      <Title level={5}>门店设备概览</Title>
      <Row gutter={[12, 12]} style={{ marginBottom: 24 }}>
        {storeOverview.map(store => {
          const allOnline = store.online_count === store.total_count;
          return (
            <Col key={store.store_id} xs={24} sm={12} md={8}>
              <Card
                size="small"
                title={
                  <Space>
                    {allOnline
                      ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
                      : <ExclamationCircleOutlined style={{ color: '#faad14' }} />
                    }
                    <Text strong>{store.store_name}</Text>
                  </Space>
                }
                extra={
                  <Tag color={allOnline ? 'green' : 'orange'}>
                    {store.online_count}/{store.total_count} 在线
                  </Tag>
                }
              >
                <Space wrap>
                  {store.devices.map(d => (
                    <Tooltip key={d.name} title={d.name}>
                      <Tag
                        color={d.status === 'online' ? 'green' : 'red'}
                        icon={d.status === 'online' ? <ApiOutlined /> : <DisconnectOutlined />}
                      >
                        {DEVICE_TYPE_MAP[d.type].icon}
                      </Tag>
                    </Tooltip>
                  ))}
                </Space>
              </Card>
            </Col>
          );
        })}
      </Row>

      {/* Alerts */}
      <Title level={5}>告警列表</Title>
      <Table<AlertItem>
        size="small"
        dataSource={alerts}
        rowKey="id"
        pagination={false}
        style={{ marginBottom: 24 }}
        columns={[
          {
            title: '设备',
            dataIndex: 'device_name',
            width: 200,
            render: (name: string, r) => (
              <Space direction="vertical" size={0}>
                <Text strong>{name}</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>{r.store_name}</Text>
              </Space>
            ),
          },
          {
            title: '告警类型',
            dataIndex: 'alert_type',
            width: 110,
            render: (t: AlertType) => <Tag color={ALERT_TYPE_MAP[t].color}>{ALERT_TYPE_MAP[t].label}</Tag>,
          },
          {
            title: '告警内容',
            dataIndex: 'message',
            ellipsis: true,
          },
          {
            title: '时间',
            dataIndex: 'created_at',
            width: 150,
            render: (t: string) => (
              <Tooltip title={dayjs(t).format('YYYY-MM-DD HH:mm:ss')}>
                {dayjs(t).fromNow()}
              </Tooltip>
            ),
          },
          {
            title: '状态',
            dataIndex: 'state',
            width: 90,
            render: (s: AlertState) => <Tag color={ALERT_STATE_MAP[s].color}>{ALERT_STATE_MAP[s].label}</Tag>,
          },
          {
            title: '操作',
            width: 160,
            render: (_, r) => (
              <Space>
                {r.state === 'pending' && (
                  <Button size="small" onClick={() => handleAlertAction(r.id, 'acknowledge')}>
                    确认
                  </Button>
                )}
                {r.state !== 'resolved' && (
                  <Button size="small" type="link" onClick={() => handleAlertAction(r.id, 'resolve')}>
                    解决
                  </Button>
                )}
              </Space>
            ),
          },
        ]}
      />

      {/* Alert rules */}
      <Row align="middle" justify="space-between" style={{ marginBottom: 12 }}>
        <Col><Title level={5} style={{ margin: 0 }}>告警规则</Title></Col>
        <Col>
          <Button
            type="primary"
            size="small"
            onClick={() => { setEditingRule(null); form.resetFields(); setRuleModal(true); }}
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
          >
            新增规则
          </Button>
        </Col>
      </Row>
      <Table<AlertRule>
        size="small"
        dataSource={rules}
        rowKey="id"
        pagination={false}
        columns={[
          { title: '规则名称', dataIndex: 'name', width: 180 },
          { title: '监控指标', dataIndex: 'metric', width: 150 },
          {
            title: '阈值',
            width: 120,
            render: (_, r) => <Text>{r.threshold}{r.unit}</Text>,
          },
          {
            title: '状态',
            dataIndex: 'enabled',
            width: 80,
            render: (enabled: boolean, r) => (
              <Switch
                checked={enabled}
                size="small"
                onChange={val => handleRuleToggle(r.id, val)}
              />
            ),
          },
          {
            title: '操作',
            width: 80,
            render: (_, r) => (
              <Button
                type="link"
                size="small"
                onClick={() => {
                  setEditingRule(r);
                  form.setFieldsValue(r);
                  setRuleModal(true);
                }}
              >
                编辑
              </Button>
            ),
          },
        ]}
      />

      {/* Rule modal */}
      <Modal
        title={editingRule ? '编辑告警规则' : '新增告警规则'}
        open={ruleModal}
        onCancel={() => { setRuleModal(false); setEditingRule(null); }}
        onOk={handleSaveRule}
        okText="保存"
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="规则名称" rules={[{ required: true, message: '请输入规则名称' }]}>
            <Input placeholder="如：CPU过高告警" />
          </Form.Item>
          <Form.Item name="metric" label="监控指标" rules={[{ required: true, message: '请选择监控指标' }]}>
            <Select
              placeholder="选择指标"
              options={[
                { label: 'CPU使用率', value: 'cpu_percent' },
                { label: '内存使用率', value: 'memory_percent' },
                { label: '磁盘使用率', value: 'disk_percent' },
                { label: '离线时长(分钟)', value: 'offline_minutes' },
              ]}
            />
          </Form.Item>
          <Form.Item name="threshold" label="阈值" rules={[{ required: true, message: '请输入阈值' }]}>
            <InputNumber min={1} max={100} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="unit" label="单位" rules={[{ required: true, message: '请输入单位' }]}>
            <Input placeholder="如：% 或 分钟" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Main Page
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export function DeviceManagePage() {
  const [devices, setDevices] = useState<DeviceInfo[]>([]);
  const [activeTab, setActiveTab] = useState('devices');

  useEffect(() => {
    fetchDevices().then(setDevices);
  }, []);

  const totalCount = devices.length;
  const onlineCount = devices.filter(d => d.status === 'online').length;
  const offlineCount = devices.filter(d => d.status === 'offline').length;
  // 无法从 API 加载当前版本前，暂时不计算需要更新的设备数
  const needsUpdateCount = 0;

  return (
    <div style={{ padding: 24 }}>
      {/* Stats cards */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={6}>
          <Card size="small" hoverable>
            <Statistic
              title="设备总数"
              value={totalCount}
              prefix={<DesktopOutlined style={{ color: '#FF6B35' }} />}
              valueStyle={{ color: '#FF6B35' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" hoverable>
            <Statistic
              title="在线"
              value={onlineCount}
              prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" hoverable>
            <Statistic
              title="离线"
              value={offlineCount}
              prefix={<CloseCircleOutlined style={{ color: '#f5222d' }} />}
              valueStyle={{ color: '#f5222d' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" hoverable>
            <Statistic
              title="需更新"
              value={needsUpdateCount}
              prefix={<WarningOutlined style={{ color: '#faad14' }} />}
              valueStyle={{ color: '#faad14' }}
            />
          </Card>
        </Col>
      </Row>

      {/* Tabs */}
      <Card>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'devices',
              label: (
                <span><DesktopOutlined /> 设备列表</span>
              ),
              children: <DeviceListTab />,
            },
            {
              key: 'ota',
              label: (
                <span><CloudDownloadOutlined /> OTA 管理</span>
              ),
              children: <OtaManageTab />,
            },
            {
              key: 'monitor',
              label: (
                <span><MobileOutlined /> 远程监控</span>
              ),
              children: <RemoteMonitorTab />,
            },
          ]}
        />
      </Card>
    </div>
  );
}
