/**
 * 边缘节点管理页  /platform/edge-nodes
 *
 * 三个标签页：
 *  - 节点列表      ← 所有已注册节点及实时状态
 *  - 接入向导      ← 5步引导：门店信息→Token→安装命令→等待注册→验收
 *  - Bootstrap Token ← 发放 / 列表 / 吊销
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  ZCard, ZBadge, ZButton, ZAlert, ZEmpty, ZSkeleton, ZTabs, ZInput,
} from '../../design-system/components';
import { apiClient } from '../../services/api';
import styles from './EdgeNodeManagementPage.module.css';

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface EdgeNode {
  node_id: string;
  store_id: string;
  device_name: string;
  status: 'online' | 'offline' | 'unknown';
  ip_address: string;
  mac_address: string;
  hardware_model: string;
  cpu_usage: number;
  memory_usage: number;
  disk_usage: number;
  temperature: number;
  uptime_seconds: number;
  updated_at: string;
  credential_ok: boolean;
}

interface BootstrapToken {
  token_hash: string;
  created_by: string;
  note: string;
  store_id: string | null;
  created_at: number;
  expires_at: number;
  active: boolean;
}

// ─── 辅助函数 ──────────────────────────────────────────────────────────────

const uptimeStr = (s: number) => {
  if (s < 60) return `${s}秒`;
  if (s < 3600) return `${Math.floor(s / 60)}分钟`;
  if (s < 86400) return `${Math.floor(s / 3600)}小时`;
  return `${Math.floor(s / 86400)}天`;
};

const fmtTs = (ts: number) =>
  new Date(ts * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' });

// ─── 子组件：节点状态徽章 ────────────────────────────────────────────────────

const NodeStatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const map: Record<string, 'success' | 'warning' | 'default'> = {
    online: 'success', offline: 'warning', unknown: 'default',
  };
  const label: Record<string, string> = {
    online: '在线', offline: '离线', unknown: '未知',
  };
  return <ZBadge type={map[status] ?? 'default'} text={label[status] ?? status} />;
};

// ─── Tab 1：节点列表 ─────────────────────────────────────────────────────────

const NodeListTab: React.FC = () => {
  const [nodes, setNodes] = useState<EdgeNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const resp = await apiClient.get('/api/v1/hardware/admin/edge-nodes');
      setNodes(resp.data.nodes ?? []);
      setError('');
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? '加载失败，请检查权限');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <ZSkeleton rows={4} />;
  if (error) return <ZAlert variant="error">{error}</ZAlert>;
  if (nodes.length === 0) return (
    <ZEmpty title="暂无已注册节点" description="使用右侧「接入向导」完成首台 Pi5 部署" />
  );

  return (
    <div>
      <div className={styles.listHeader}>
        <span className={styles.listCount}>共 {nodes.length} 个节点</span>
        <ZButton size="sm" variant="ghost" onClick={load}>刷新</ZButton>
      </div>
      <div className={styles.nodeGrid}>
        {nodes.map(node => (
          <ZCard key={node.node_id} className={styles.nodeCard}>
            <div className={styles.nodeCardHeader}>
              <div>
                <div className={styles.nodeId}>{node.device_name}</div>
                <div className={styles.nodeStore}>门店 {node.store_id}</div>
              </div>
              <NodeStatusBadge status={node.status} />
            </div>

            <div className={styles.nodeMetrics}>
              <div className={styles.metric}>
                <span className={styles.metricLabel}>IP</span>
                <span className={styles.metricValue}>{node.ip_address || '—'}</span>
              </div>
              <div className={styles.metric}>
                <span className={styles.metricLabel}>CPU</span>
                <span className={styles.metricValue}>{node.cpu_usage.toFixed(1)}%</span>
              </div>
              <div className={styles.metric}>
                <span className={styles.metricLabel}>内存</span>
                <span className={styles.metricValue}>{node.memory_usage.toFixed(1)}%</span>
              </div>
              <div className={styles.metric}>
                <span className={styles.metricLabel}>温度</span>
                <span className={styles.metricValue}>{node.temperature.toFixed(1)}°C</span>
              </div>
              <div className={styles.metric}>
                <span className={styles.metricLabel}>运行时长</span>
                <span className={styles.metricValue}>{uptimeStr(node.uptime_seconds)}</span>
              </div>
              <div className={styles.metric}>
                <span className={styles.metricLabel}>密钥状态</span>
                <span className={styles.metricValue}>
                  {node.credential_ok
                    ? <ZBadge type="success" text="有效" />
                    : <ZBadge type="warning" text="待配置" />}
                </span>
              </div>
            </div>

            <div className={styles.nodeFooter}>
              <span className={styles.nodeId2}>{node.node_id}</span>
            </div>
          </ZCard>
        ))}
      </div>
    </div>
  );
};

// ─── Tab 2：接入向导 ─────────────────────────────────────────────────────────

const WIZARD_STEPS = [
  { key: 'info',    label: '1  门店信息' },
  { key: 'token',   label: '2  发放 Token' },
  { key: 'install', label: '3  安装命令' },
  { key: 'wait',    label: '4  等待注册' },
  { key: 'verify',  label: '5  验收' },
];

interface WizardForm {
  storeId: string;
  storeName: string;
  piIp: string;
  piUser: string;
}

const OnboardingWizardTab: React.FC = () => {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<WizardForm>({
    storeId: '', storeName: '', piIp: '', piUser: 'tunxiangos',
  });
  const [token, setToken] = useState('');
  const [tokenNote, setTokenNote] = useState('');
  const [tokenLoading, setTokenLoading] = useState(false);
  const [tokenErr, setTokenErr] = useState('');
  const [copied, setCopied] = useState(false);
  const [pollStatus, setPollStatus] = useState<'idle' | 'polling' | 'found' | 'timeout'>('idle');
  const [foundNode, setFoundNode] = useState<EdgeNode | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollCountRef = useRef(0);

  const updateForm = (field: keyof WizardForm) => (v: string) =>
    setForm(f => ({ ...f, [field]: v }));

  // 步骤1 → 步骤2
  const step1Valid = form.storeId.trim() && form.piIp.trim() && form.piUser.trim();

  // 生成 Bootstrap Token
  const issueToken = async () => {
    setTokenErr('');
    setTokenLoading(true);
    try {
      const resp = await apiClient.post('/api/v1/hardware/admin/bootstrap-token/issue', {
        note: tokenNote || `${form.storeName || form.storeId} ${new Date().toLocaleDateString('zh-CN')}`,
        store_id: form.storeId,
        ttl_days: 7,
      });
      setToken(resp.data.token);
    } catch (e: any) {
      const msg = e?.response?.data?.detail ?? '发放失败';
      if (e?.response?.status === 404) {
        setTokenErr('Bootstrap Token API 尚未部署到生产版本，请使用管理员 JWT 作为临时 Token');
      } else {
        setTokenErr(msg);
      }
    } finally {
      setTokenLoading(false);
    }
  };

  // 构建安装命令
  const installCmd = () => {
    const t = token || '<BOOTSTRAP_TOKEN>';
    return `cd apps/api-gateway

sudo EDGE_API_BASE_URL=https://admin.zlsjos.cn \\
     EDGE_API_TOKEN=${t} \\
     EDGE_STORE_ID=${form.storeId} \\
     EDGE_DEVICE_NAME=${form.storeId.toLowerCase().replace(/[^a-z0-9]/g, '-')}-rpi5 \\
     EDGE_SHOKZ_CALLBACK_SECRET=${form.storeId.toLowerCase()}shokz \\
     REMOTE_HOST=${form.piIp} \\
     REMOTE_USER=${form.piUser} \\
     bash scripts/install_raspberry_pi_edge_remote.sh`;
  };

  const copyCmd = () => {
    navigator.clipboard.writeText(installCmd()).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  // 步骤4：轮询注册
  const startPolling = useCallback(() => {
    if (!form.storeId) return;
    setPollStatus('polling');
    pollCountRef.current = 0;

    pollRef.current = setInterval(async () => {
      pollCountRef.current += 1;
      if (pollCountRef.current > 60) {   // 5 分钟超时
        clearInterval(pollRef.current!);
        setPollStatus('timeout');
        return;
      }
      try {
        const resp = await apiClient.get(`/api/v1/hardware/edge-node/store/${form.storeId}`);
        const nodes: EdgeNode[] = resp.data.nodes ?? [];
        if (nodes.length > 0) {
          setFoundNode(nodes[0]);
          setPollStatus('found');
          clearInterval(pollRef.current!);
        }
      } catch { /* 继续轮询 */ }
    }, 5000);
  }, [form.storeId]);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const goStep = (s: number) => {
    setStep(s);
    if (s === 3 && pollStatus === 'idle') startPolling();
  };

  // ── 渲染各步 ──────────────────────────────────────────────────────────────

  const renderStep = () => {
    switch (step) {
      // ── 步骤1 ──
      case 0: return (
        <div className={styles.wizardBody}>
          <h3 className={styles.stepTitle}>填写门店基本信息</h3>
          <p className={styles.stepDesc}>确认门店 ID 和 Pi5 的网络地址，用于生成安装命令。</p>
          <div className={styles.formGrid}>
            <label>门店 ID <span className={styles.required}>*</span>
              <ZInput value={form.storeId} onChange={updateForm('storeId')} placeholder="如 CZYZ-2461" />
            </label>
            <label>门店名称
              <ZInput value={form.storeName} onChange={updateForm('storeName')} placeholder="如 尝在一起文化城店" />
            </label>
            <label>Pi5 IP 地址 <span className={styles.required}>*</span>
              <ZInput value={form.piIp} onChange={updateForm('piIp')} placeholder="如 192.168.110.96" />
            </label>
            <label>SSH 用户名 <span className={styles.required}>*</span>
              <ZInput value={form.piUser} onChange={updateForm('piUser')} placeholder="默认 tunxiangos" />
            </label>
          </div>
          <ZAlert variant="info" style={{ marginTop: 16 }}>
            Pi5 IP 可在设备上运行 <code>hostname -I</code> 获取；SSH 用户名通常是 <code>tunxiangos</code> 或 <code>pi</code>
          </ZAlert>
          <div className={styles.wizardFooter}>
            <ZButton onClick={() => goStep(1)} disabled={!step1Valid}>下一步：发放 Token →</ZButton>
          </div>
        </div>
      );

      // ── 步骤2 ──
      case 1: return (
        <div className={styles.wizardBody}>
          <h3 className={styles.stepTitle}>发放 Bootstrap Token</h3>
          <p className={styles.stepDesc}>Token 用于 Pi5 首次注册到云端，有效期 7 天，明文仅显示一次。</p>
          <div className={styles.tokenNoteRow}>
            <label style={{ flex: 1 }}>Token 备注（可选）
              <ZInput value={tokenNote} onChange={v => setTokenNote(v)}
                placeholder={`${form.storeName || form.storeId} ${new Date().toLocaleDateString('zh-CN')}`} />
            </label>
            <ZButton onClick={issueToken} loading={tokenLoading} disabled={tokenLoading} style={{ alignSelf: 'flex-end' }}>
              生成 Token
            </ZButton>
          </div>

          {tokenErr && <ZAlert variant="warning" style={{ marginTop: 12 }}>{tokenErr}</ZAlert>}

          {token && (
            <div className={styles.tokenBox}>
              <div className={styles.tokenLabel}>✅ Token（请立即复制，仅显示一次）</div>
              <div className={styles.tokenValue}>{token}</div>
              <ZButton size="sm" variant="ghost" onClick={() => navigator.clipboard.writeText(token)}>复制 Token</ZButton>
            </div>
          )}

          <ZAlert variant="info" style={{ marginTop: 16 }}>
            如果 Token API 返回 404，说明生产服务器版本较旧，请用管理员 JWT 作为临时 Token（刷新页面登录后从浏览器开发者工具 → Application → Local Storage 获取 <code>access_token</code>）
          </ZAlert>

          <div className={styles.wizardFooter}>
            <ZButton variant="ghost" onClick={() => goStep(0)}>← 上一步</ZButton>
            <ZButton onClick={() => goStep(2)}>下一步：查看安装命令 →</ZButton>
          </div>
        </div>
      );

      // ── 步骤3 ──
      case 2: return (
        <div className={styles.wizardBody}>
          <h3 className={styles.stepTitle}>在开发机执行安装命令</h3>
          <p className={styles.stepDesc}>
            将以下命令粘贴到你的<strong>开发机终端</strong>（与 Pi5 在同一网络内）执行，约 2-3 分钟完成。
          </p>

          <div className={styles.cmdBox}>
            <pre className={styles.cmdPre}>{installCmd()}</pre>
            <ZButton size="sm" variant="ghost" onClick={copyCmd} className={styles.copyBtn}>
              {copied ? '✅ 已复制' : '复制命令'}
            </ZButton>
          </div>

          <ZAlert variant="success" style={{ marginTop: 12 }}>
            命令执行完成后，Pi5 会自动注册到云端，下一步将实时检测注册状态。
          </ZAlert>

          <div className={styles.installStepsBox}>
            <div className={styles.installStepTitle}>命令内部执行的步骤</div>
            {[
              '① SSH 连接到 Pi5',
              '② 创建 /opt/zhilian-edge/ 目录',
              '③ 传输 6 个边缘层 Python 文件',
              '④ 写入 /etc/zhilian-edge/edge-node.env 配置文件',
              '⑤ 安装 systemd 服务（zhilian-edge-node + shokz）',
              '⑥ 启动服务，Pi5 向云端注册并获取 device_secret',
              '⑦ 运行 zhilian-check 健康诊断',
            ].map(s => <div key={s} className={styles.installStepItem}>{s}</div>)}
          </div>

          <div className={styles.wizardFooter}>
            <ZButton variant="ghost" onClick={() => goStep(1)}>← 上一步</ZButton>
            <ZButton onClick={() => goStep(3)}>命令已执行，等待注册 →</ZButton>
          </div>
        </div>
      );

      // ── 步骤4 ──
      case 3: return (
        <div className={styles.wizardBody}>
          <h3 className={styles.stepTitle}>等待边缘节点注册</h3>
          <p className={styles.stepDesc}>每 5 秒自动检测一次，Pi5 完成注册后自动跳转。</p>

          {pollStatus === 'idle' && (
            <ZButton onClick={startPolling}>开始检测</ZButton>
          )}

          {pollStatus === 'polling' && (
            <div className={styles.pollBox}>
              <div className={styles.pollSpinner}>⏳</div>
              <div>正在检测门店 <strong>{form.storeId}</strong> 的节点注册状态…</div>
              <div className={styles.pollCount}>已等待 {pollCountRef.current * 5} 秒</div>
            </div>
          )}

          {pollStatus === 'timeout' && (
            <ZAlert variant="warning">
              等待超时（5分钟）。请检查安装命令是否执行成功，或手动查看 Pi5 上的服务状态：
              <code>ssh {form.piUser}@{form.piIp} "sudo journalctl -u zhilian-edge-node -n 20"</code>
            </ZAlert>
          )}

          {pollStatus === 'found' && foundNode && (
            <ZAlert variant="success">
              ✅ 节点已注册！node_id: <strong>{foundNode.node_id}</strong>
            </ZAlert>
          )}

          <div className={styles.wizardFooter}>
            <ZButton variant="ghost" onClick={() => goStep(2)}>← 上一步</ZButton>
            {(pollStatus === 'found' || pollStatus === 'timeout') && (
              <ZButton onClick={() => goStep(4)}>下一步：验收 →</ZButton>
            )}
          </div>
        </div>
      );

      // ── 步骤5 ──
      case 4: return (
        <div className={styles.wizardBody}>
          <h3 className={styles.stepTitle}>验收完成 🎉</h3>

          {foundNode ? (
            <div className={styles.summaryBox}>
              <div className={styles.summaryRow}><span>Node ID</span><code>{foundNode.node_id}</code></div>
              <div className={styles.summaryRow}><span>门店</span><code>{foundNode.store_id}</code></div>
              <div className={styles.summaryRow}><span>设备名</span><code>{foundNode.device_name}</code></div>
              <div className={styles.summaryRow}><span>IP 地址</span><code>{foundNode.ip_address}</code></div>
              <div className={styles.summaryRow}><span>MAC 地址</span><code>{foundNode.mac_address}</code></div>
              <div className={styles.summaryRow}><span>设备密钥</span>
                <ZBadge type={foundNode.credential_ok ? 'success' : 'warning'} text={foundNode.credential_ok ? '有效' : '待激活'} />
              </div>
            </div>
          ) : (
            <ZAlert variant="warning">节点未在本次向导中注册，请到「节点列表」标签页查看。</ZAlert>
          )}

          <div className={styles.checkList}>
            <div className={styles.checkTitle}>验收清单</div>
            {[
              '节点心跳正常（≤60s 上报一次）',
              'Shokz 服务运行中（zhilian-edge-shokz active）',
              '离线队列 pending=0（zhilian-queue stats）',
              'CPU 温度 < 70°C（zhilian-check）',
              '品智 POS 接入测试绿色（接入配置页）',
            ].map(item => (
              <label key={item} className={styles.checkItem}>
                <input type="checkbox" /> {item}
              </label>
            ))}
          </div>

          <div className={styles.postInstallCmds}>
            <div className={styles.checkTitle}>安装后常用命令（在 Pi5 上执行）</div>
            <pre className={styles.cmdPre}>
{`# 健康检查
ssh ${form.piUser}@${form.piIp} "zhilian-check"

# Shokz 耳机配对（耳机先进入配对模式：长按电源键5秒）
ssh ${form.piUser}@${form.piIp} "python3 /opt/zhilian-edge/shokz_bluetooth_manager.py"

# 下载本地 AI 模型
ssh ${form.piUser}@${form.piIp} "zhilian-models sync"

# 查看离线队列
ssh ${form.piUser}@${form.piIp} "zhilian-queue stats"`}
            </pre>
          </div>

          <div className={styles.wizardFooter}>
            <ZButton variant="ghost" onClick={() => { setStep(0); setToken(''); setPollStatus('idle'); setFoundNode(null); }}>
              重新接入另一台设备
            </ZButton>
          </div>
        </div>
      );
      default: return null;
    }
  };

  return (
    <div className={styles.wizardContainer}>
      {/* 步骤导航 */}
      <div className={styles.stepNav}>
        {WIZARD_STEPS.map((s, i) => (
          <div
            key={s.key}
            className={`${styles.stepNavItem} ${i === step ? styles.stepNavActive : ''} ${i < step ? styles.stepNavDone : ''}`}
            onClick={() => i < step && goStep(i)}
          >
            {i < step ? '✓' : i + 1} {s.label.slice(2)}
          </div>
        ))}
      </div>
      {renderStep()}
    </div>
  );
};

// ─── Tab 3：Bootstrap Token 管理 ────────────────────────────────────────────

const BootstrapTokenTab: React.FC = () => {
  const [tokens, setTokens] = useState<BootstrapToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revoking, setRevoking] = useState<string>('');
  const [issuing, setIssuing] = useState(false);
  const [newTokenNote, setNewTokenNote] = useState('');
  const [newTokenStoreId, setNewTokenStoreId] = useState('');
  const [newToken, setNewToken] = useState('');

  const loadTokens = useCallback(async () => {
    try {
      setLoading(true);
      const resp = await apiClient.get('/api/v1/hardware/admin/bootstrap-token/list');
      setTokens(resp.data.tokens ?? []);
      setError('');
    } catch (e: any) {
      if (e?.response?.status === 404) {
        setError('Bootstrap Token 管理 API 尚未部署到生产，请先部署最新版本。');
      } else {
        setError(e?.response?.data?.detail ?? '加载失败');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadTokens(); }, [loadTokens]);

  const issue = async () => {
    setIssuing(true);
    setNewToken('');
    try {
      const resp = await apiClient.post('/api/v1/hardware/admin/bootstrap-token/issue', {
        note: newTokenNote,
        store_id: newTokenStoreId || null,
        ttl_days: 7,
      });
      setNewToken(resp.data.token);
      await loadTokens();
    } catch (e: any) {
      alert(e?.response?.data?.detail ?? '发放失败');
    } finally {
      setIssuing(false);
    }
  };

  const revoke = async (hash: string) => {
    if (!window.confirm('确认吊销此 Token？')) return;
    setRevoking(hash);
    try {
      await apiClient.post(`/api/v1/hardware/admin/bootstrap-token/revoke/${hash}`);
      await loadTokens();
    } catch (e: any) {
      alert(e?.response?.data?.detail ?? '吊销失败');
    } finally {
      setRevoking('');
    }
  };

  if (loading) return <ZSkeleton rows={3} />;
  if (error) return <ZAlert variant="warning">{error}</ZAlert>;

  return (
    <div>
      {/* 发放新 Token */}
      <ZCard className={styles.issueCard}>
        <div className={styles.issueTitle}>发放新 Bootstrap Token</div>
        <div className={styles.issueRow}>
          <label style={{ flex: 2 }}>备注
            <ZInput value={newTokenNote} onChange={v => setNewTokenNote(v)} placeholder="如：尝在一起文化城店 2026-03-14" />
          </label>
          <label style={{ flex: 1 }}>限定门店（可选）
            <ZInput value={newTokenStoreId} onChange={v => setNewTokenStoreId(v)} placeholder="如 CZYZ-2461" />
          </label>
          <ZButton onClick={issue} loading={issuing} style={{ alignSelf: 'flex-end' }}>发放</ZButton>
        </div>
        {newToken && (
          <div className={styles.tokenBox} style={{ marginTop: 12 }}>
            <div className={styles.tokenLabel}>✅ 新 Token（仅显示一次）</div>
            <div className={styles.tokenValue}>{newToken}</div>
            <ZButton size="sm" variant="ghost" onClick={() => navigator.clipboard.writeText(newToken)}>复制</ZButton>
          </div>
        )}
      </ZCard>

      {/* Token 列表 */}
      <div className={styles.tokenListHeader}>
        <span>历史 Token（共 {tokens.length} 个）</span>
        <ZButton size="sm" variant="ghost" onClick={loadTokens}>刷新</ZButton>
      </div>

      {tokens.length === 0
        ? <ZEmpty title="暂无 Token 记录" />
        : (
          <div className={styles.tokenTable}>
            <div className={styles.tokenTableHeader}>
              <span>备注</span><span>门店</span><span>发放人</span><span>有效期</span><span>状态</span><span>操作</span>
            </div>
            {tokens.map(t => (
              <div key={t.token_hash} className={styles.tokenTableRow}>
                <span className={styles.tokenTableNote}>{t.note || '—'}</span>
                <span>{t.store_id || '通用'}</span>
                <span>{t.created_by}</span>
                <span className={styles.tokenExpiry}>{fmtTs(t.expires_at)}</span>
                <span>
                  {t.active
                    ? <ZBadge type="success" text="有效" />
                    : <ZBadge type="default" text="已吊销" />}
                </span>
                <span>
                  {t.active && (
                    <ZButton
                      size="sm" variant="ghost"
                      loading={revoking === t.token_hash}
                      onClick={() => revoke(t.token_hash)}
                    >吊销</ZButton>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}
    </div>
  );
};

// ─── 主页面 ───────────────────────────────────────────────────────────────────

const EdgeNodeManagementPage: React.FC = () => (
  <div className={styles.page}>
    <div className={styles.pageHeader}>
      <h1 className={styles.pageTitle}>边缘节点管理</h1>
      <p className={styles.pageSubtitle}>
        管理门店 Raspberry Pi 5 边缘节点 — 注册 / 监控 / Bootstrap Token
      </p>
    </div>

    <ZTabs
      items={[
        { key: 'nodes',   label: '节点列表',       children: <NodeListTab /> },
        { key: 'wizard',  label: '接入向导',        children: <OnboardingWizardTab /> },
        { key: 'tokens',  label: 'Bootstrap Token', children: <BootstrapTokenTab /> },
      ]}
    />
  </div>
);

export default EdgeNodeManagementPage;
