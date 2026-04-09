/**
 * 打印管理器页面
 *
 * 功能：
 *  - 打印机列表（名称/IP/类型/状态/连接方式）
 *  - 打印机状态指示（在线绿 / 离线红 / 错误黄）
 *  - 打印队列查看（待打印/打印中/已完成/失败）
 *  - 测试打印按钮
 *  - 打印机配置（小票宽度 58/80mm、字号、LOGO 开关）
 */
import { useState, useCallback, useMemo } from 'react';
import { printReceipt } from '../bridge/TXBridge';

/* ═══════════════════════════════════════════
   类型定义
   ═══════════════════════════════════════════ */

type PrinterConnectionType = 'usb' | 'network' | 'bluetooth';
type PrinterStatus = 'online' | 'offline' | 'error';
type PrinterType = 'receipt' | 'kitchen' | 'label';
type PaperWidth = '58mm' | '80mm';
type QueueJobStatus = 'pending' | 'printing' | 'completed' | 'failed';

interface PrinterConfig {
  paperWidth: PaperWidth;
  fontSize: number;
  logoEnabled: boolean;
  autoCut: boolean;
  copies: number;
}

interface Printer {
  id: string;
  name: string;
  ip: string;
  type: PrinterType;
  status: PrinterStatus;
  connection: PrinterConnectionType;
  config: PrinterConfig;
  lastActiveAt: string;
  errorMessage?: string;
}

interface QueueJob {
  id: string;
  printerId: string;
  printerName: string;
  title: string;
  status: QueueJobStatus;
  createdAt: string;
  completedAt?: string;
  retries: number;
  errorMessage?: string;
}

/* ═══════════════════════════════════════════
   Mock 数据
   ═══════════════════════════════════════════ */

const MOCK_PRINTERS: Printer[] = [
  {
    id: 'p1', name: '前台小票机', ip: '192.168.1.101', type: 'receipt',
    status: 'online', connection: 'usb',
    config: { paperWidth: '80mm', fontSize: 16, logoEnabled: true, autoCut: true, copies: 1 },
    lastActiveAt: '2026-04-09 12:30:15',
  },
  {
    id: 'p2', name: '厨房打印机-热菜档', ip: '192.168.1.102', type: 'kitchen',
    status: 'online', connection: 'network',
    config: { paperWidth: '80mm', fontSize: 18, logoEnabled: false, autoCut: true, copies: 1 },
    lastActiveAt: '2026-04-09 12:29:58',
  },
  {
    id: 'p3', name: '厨房打印机-凉菜档', ip: '192.168.1.103', type: 'kitchen',
    status: 'error', connection: 'network',
    config: { paperWidth: '80mm', fontSize: 18, logoEnabled: false, autoCut: true, copies: 1 },
    lastActiveAt: '2026-04-09 11:45:00',
    errorMessage: '缺纸',
  },
  {
    id: 'p4', name: '蓝牙便携机', ip: '-', type: 'receipt',
    status: 'offline', connection: 'bluetooth',
    config: { paperWidth: '58mm', fontSize: 16, logoEnabled: false, autoCut: false, copies: 1 },
    lastActiveAt: '2026-04-08 22:10:00',
  },
  {
    id: 'p5', name: '标签打印机', ip: '192.168.1.105', type: 'label',
    status: 'online', connection: 'usb',
    config: { paperWidth: '58mm', fontSize: 16, logoEnabled: false, autoCut: true, copies: 1 },
    lastActiveAt: '2026-04-09 12:28:30',
  },
];

const MOCK_QUEUE: QueueJob[] = [
  { id: 'q1', printerId: 'p1', printerName: '前台小票机', title: '订单TX20260409001小票', status: 'completed', createdAt: '2026-04-09 12:30:10', completedAt: '2026-04-09 12:30:12', retries: 0 },
  { id: 'q2', printerId: 'p2', printerName: '厨房打印机-热菜档', title: '订单TX20260409001厨房单', status: 'completed', createdAt: '2026-04-09 12:30:10', completedAt: '2026-04-09 12:30:14', retries: 0 },
  { id: 'q3', printerId: 'p3', printerName: '厨房打印机-凉菜档', title: '订单TX20260409002厨房单', status: 'failed', createdAt: '2026-04-09 12:28:00', retries: 3, errorMessage: '打印机缺纸' },
  { id: 'q4', printerId: 'p1', printerName: '前台小票机', title: '订单TX20260409003小票', status: 'printing', createdAt: '2026-04-09 12:31:00', retries: 0 },
  { id: 'q5', printerId: 'p2', printerName: '厨房打印机-热菜档', title: '订单TX20260409003厨房单', status: 'pending', createdAt: '2026-04-09 12:31:01', retries: 0 },
  { id: 'q6', printerId: 'p1', printerName: '前台小票机', title: '订单TX20260409004小票', status: 'pending', createdAt: '2026-04-09 12:31:30', retries: 0 },
];

/* ═══════════════════════════════════════════
   色彩常量（与 PrintTemplatePage 保持一致）
   ═══════════════════════════════════════════ */

const C = {
  bg: '#0B1A20',
  card: '#112228',
  cardAlt: '#112B36',
  border: '#1A3A48',
  accent: '#FF6B35',
  accentHover: '#FF8255',
  text: '#E0E0E0',
  textDim: '#8899A6',
  white: '#FFFFFF',
  danger: '#EF4444',
  success: '#22C55E',
  warning: '#EAB308',
} as const;

const BTN_BASE: React.CSSProperties = {
  minWidth: 48,
  minHeight: 48,
  border: 'none',
  borderRadius: 8,
  cursor: 'pointer',
  fontFamily: 'inherit',
  fontSize: 16,
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 6,
  padding: '0 16px',
  transition: 'background 0.15s, transform 0.2s',
  userSelect: 'none',
};

/* ═══════════════════════════════════════════
   工具函数
   ═══════════════════════════════════════════ */

const statusColor = (s: PrinterStatus): string =>
  s === 'online' ? C.success : s === 'error' ? C.warning : C.danger;

const statusLabel = (s: PrinterStatus): string =>
  s === 'online' ? '在线' : s === 'error' ? '异常' : '离线';

const connectionLabel = (c: PrinterConnectionType): string =>
  c === 'usb' ? 'USB' : c === 'network' ? '网络' : '蓝牙';

const typeLabel = (t: PrinterType): string =>
  t === 'receipt' ? '小票机' : t === 'kitchen' ? '厨房机' : '标签机';

const jobStatusColor = (s: QueueJobStatus): string =>
  s === 'completed' ? C.success : s === 'failed' ? C.danger : s === 'printing' ? C.accent : C.textDim;

const jobStatusLabel = (s: QueueJobStatus): string =>
  s === 'pending' ? '待打印' : s === 'printing' ? '打印中' : s === 'completed' ? '已完成' : '失败';

/* ═══════════════════════════════════════════
   子组件：打印机配置弹层
   ═══════════════════════════════════════════ */

function PrinterConfigModal({
  printer,
  onSave,
  onClose,
}: {
  printer: Printer;
  onSave: (id: string, config: PrinterConfig) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<PrinterConfig>({ ...printer.config });

  const inputStyle: React.CSSProperties = {
    background: C.card,
    color: C.white,
    border: `1px solid ${C.border}`,
    borderRadius: 8,
    padding: '10px 12px',
    fontSize: 16,
    width: '100%',
    boxSizing: 'border-box',
    minHeight: 48,
  };

  const field = (label: string, node: React.ReactNode) => (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 16, color: C.textDim, marginBottom: 6 }}>{label}</div>
      {node}
    </div>
  );

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: C.cardAlt, borderRadius: 12, padding: 24,
          width: 400, maxHeight: '80vh', overflowY: 'auto',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ margin: '0 0 20px', color: C.white, fontSize: 20 }}>
          配置 - {printer.name}
        </h3>

        {/* 纸宽 */}
        {field(
          '小票宽度',
          <div style={{ display: 'flex', gap: 12 }}>
            {(['58mm', '80mm'] as PaperWidth[]).map((w) => (
              <button
                key={w}
                style={{
                  ...BTN_BASE,
                  flex: 1,
                  background: draft.paperWidth === w ? C.accent : C.card,
                  color: C.white,
                }}
                onClick={() => setDraft((d) => ({ ...d, paperWidth: w }))}
              >
                {w}
              </button>
            ))}
          </div>,
        )}

        {/* 字号 */}
        {field(
          '默认字号',
          <input
            type="number"
            min={12}
            max={28}
            value={draft.fontSize}
            onChange={(e) => setDraft((d) => ({ ...d, fontSize: Number(e.target.value) }))}
            style={inputStyle}
          />,
        )}

        {/* LOGO 开关 */}
        {field(
          'LOGO 打印',
          <button
            style={{
              ...BTN_BASE,
              width: '100%',
              background: draft.logoEnabled ? C.success : C.card,
              color: C.white,
            }}
            onClick={() => setDraft((d) => ({ ...d, logoEnabled: !d.logoEnabled }))}
          >
            {draft.logoEnabled ? 'LOGO 开启' : 'LOGO 关闭'}
          </button>,
        )}

        {/* 自动切纸 */}
        {field(
          '自动切纸',
          <button
            style={{
              ...BTN_BASE,
              width: '100%',
              background: draft.autoCut ? C.success : C.card,
              color: C.white,
            }}
            onClick={() => setDraft((d) => ({ ...d, autoCut: !d.autoCut }))}
          >
            {draft.autoCut ? '自动切纸 开启' : '自动切纸 关闭'}
          </button>,
        )}

        {/* 打印份数 */}
        {field(
          '打印份数',
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button
              style={{ ...BTN_BASE, width: 48, background: C.card, color: C.white }}
              onClick={() => setDraft((d) => ({ ...d, copies: Math.max(1, d.copies - 1) }))}
            >
              -
            </button>
            <span style={{ fontSize: 20, color: C.white, fontWeight: 600, minWidth: 32, textAlign: 'center' }}>
              {draft.copies}
            </span>
            <button
              style={{ ...BTN_BASE, width: 48, background: C.card, color: C.white }}
              onClick={() => setDraft((d) => ({ ...d, copies: Math.min(5, d.copies + 1) }))}
            >
              +
            </button>
          </div>,
        )}

        <div style={{ display: 'flex', gap: 12, marginTop: 20 }}>
          <button
            style={{ ...BTN_BASE, flex: 1, background: C.accent, color: C.white, fontWeight: 600 }}
            onClick={() => { onSave(printer.id, draft); onClose(); }}
          >
            保存
          </button>
          <button
            style={{ ...BTN_BASE, flex: 1, background: C.card, color: C.text }}
            onClick={onClose}
          >
            取消
          </button>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════
   主组件
   ═══════════════════════════════════════════ */

type TabKey = 'printers' | 'queue';
type QueueFilter = 'all' | QueueJobStatus;

export function PrintManagerPage() {
  const [printers, setPrinters] = useState<Printer[]>(MOCK_PRINTERS);
  const [queue, setQueue] = useState<QueueJob[]>(MOCK_QUEUE);
  const [activeTab, setActiveTab] = useState<TabKey>('printers');
  const [queueFilter, setQueueFilter] = useState<QueueFilter>('all');
  const [configTarget, setConfigTarget] = useState<Printer | null>(null);
  const [testPrintingId, setTestPrintingId] = useState<string | null>(null);

  /* ── 过滤队列 ── */
  const filteredQueue = useMemo(
    () => (queueFilter === 'all' ? queue : queue.filter((j) => j.status === queueFilter)),
    [queue, queueFilter],
  );

  const queueCounts = useMemo(() => {
    const c = { pending: 0, printing: 0, completed: 0, failed: 0 };
    queue.forEach((j) => { c[j.status]++; });
    return c;
  }, [queue]);

  /* ── 测试打印 ── */
  const handleTestPrint = useCallback((printer: Printer) => {
    if (printer.status === 'offline') return;
    setTestPrintingId(printer.id);

    const content = [
      '======== 打印测试 ========',
      `打印机: ${printer.name}`,
      `类型: ${typeLabel(printer.type)}`,
      `纸宽: ${printer.config.paperWidth}`,
      `时间: ${new Date().toLocaleString('zh-CN')}`,
      '==========================',
      '测试打印成功!',
    ].join('\n');

    printReceipt(content)
      .then(() => {
        // 添加到队列
        setQueue((q) => [
          {
            id: `q_test_${Date.now()}`,
            printerId: printer.id,
            printerName: printer.name,
            title: '测试打印',
            status: 'completed' as const,
            createdAt: new Date().toLocaleString('zh-CN'),
            completedAt: new Date().toLocaleString('zh-CN'),
            retries: 0,
          },
          ...q,
        ]);
      })
      .catch(() => {
        setQueue((q) => [
          {
            id: `q_test_${Date.now()}`,
            printerId: printer.id,
            printerName: printer.name,
            title: '测试打印',
            status: 'failed' as const,
            createdAt: new Date().toLocaleString('zh-CN'),
            retries: 0,
            errorMessage: '打印失败',
          },
          ...q,
        ]);
      })
      .finally(() => setTestPrintingId(null));
  }, []);

  /* ── 重试失败任务 ── */
  const handleRetry = useCallback((jobId: string) => {
    setQueue((q) =>
      q.map((j) => (j.id === jobId ? { ...j, status: 'pending' as const, retries: j.retries + 1, errorMessage: undefined } : j)),
    );
  }, []);

  /* ── 保存配置 ── */
  const handleSaveConfig = useCallback((printerId: string, config: PrinterConfig) => {
    setPrinters((ps) =>
      ps.map((p) => (p.id === printerId ? { ...p, config } : p)),
    );
  }, []);

  /* ── Tab 样式 ── */
  const tabStyle = (active: boolean): React.CSSProperties => ({
    ...BTN_BASE,
    background: active ? C.accent : 'transparent',
    color: active ? C.white : C.textDim,
    fontWeight: active ? 700 : 500,
    fontSize: 18,
    borderRadius: 8,
    padding: '0 24px',
    minHeight: 48,
  });

  const filterBtnStyle = (active: boolean): React.CSSProperties => ({
    ...BTN_BASE,
    background: active ? C.accent : C.card,
    color: active ? C.white : C.textDim,
    fontSize: 16,
    padding: '0 16px',
    minHeight: 40,
    borderRadius: 20,
  });

  /* ═══════════════════════════════════════════
     渲染
     ═══════════════════════════════════════════ */

  return (
    <div
      style={{
        minHeight: '100vh',
        background: C.bg,
        color: C.text,
        fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
        padding: 20,
      }}
    >
      {/* ── 顶栏 ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 24, color: C.white, fontWeight: 700 }}>
          打印管理
        </h2>
        <div style={{ display: 'flex', gap: 8 }}>
          <button style={tabStyle(activeTab === 'printers')} onClick={() => setActiveTab('printers')}>
            打印机列表
          </button>
          <button style={tabStyle(activeTab === 'queue')} onClick={() => setActiveTab('queue')}>
            打印队列
            {queueCounts.pending + queueCounts.printing > 0 && (
              <span
                style={{
                  marginLeft: 6,
                  background: C.danger,
                  color: C.white,
                  borderRadius: 10,
                  padding: '2px 8px',
                  fontSize: 16,
                  fontWeight: 700,
                }}
              >
                {queueCounts.pending + queueCounts.printing}
              </span>
            )}
          </button>
        </div>
      </div>

      {/* ── 打印机列表 ── */}
      {activeTab === 'printers' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {/* 汇总条 */}
          <div
            style={{
              display: 'flex', gap: 20, padding: '12px 16px',
              background: C.card, borderRadius: 12, marginBottom: 4,
            }}
          >
            <span style={{ fontSize: 16, color: C.textDim }}>
              共 <strong style={{ color: C.white }}>{printers.length}</strong> 台
            </span>
            <span style={{ fontSize: 16, color: C.success }}>
              在线 {printers.filter((p) => p.status === 'online').length}
            </span>
            <span style={{ fontSize: 16, color: C.warning }}>
              异常 {printers.filter((p) => p.status === 'error').length}
            </span>
            <span style={{ fontSize: 16, color: C.danger }}>
              离线 {printers.filter((p) => p.status === 'offline').length}
            </span>
          </div>

          {printers.map((printer) => (
            <div
              key={printer.id}
              style={{
                background: C.card,
                borderRadius: 12,
                padding: 20,
                borderLeft: `4px solid ${statusColor(printer.status)}`,
                display: 'flex',
                alignItems: 'center',
                gap: 16,
              }}
            >
              {/* 状态指示灯 */}
              <div
                style={{
                  width: 16,
                  height: 16,
                  borderRadius: '50%',
                  background: statusColor(printer.status),
                  flexShrink: 0,
                  boxShadow: printer.status === 'online' ? `0 0 8px ${C.success}` : 'none',
                }}
              />

              {/* 信息 */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 18, fontWeight: 700, color: C.white }}>{printer.name}</span>
                  <span
                    style={{
                      fontSize: 16, padding: '2px 10px', borderRadius: 6,
                      background: C.cardAlt, color: C.textDim,
                    }}
                  >
                    {typeLabel(printer.type)}
                  </span>
                  <span
                    style={{
                      fontSize: 16, padding: '2px 10px', borderRadius: 6,
                      background: C.cardAlt, color: C.textDim,
                    }}
                  >
                    {connectionLabel(printer.connection)}
                  </span>
                  <span
                    style={{
                      fontSize: 16, padding: '2px 10px', borderRadius: 6,
                      background: C.cardAlt, color: statusColor(printer.status),
                      fontWeight: 600,
                    }}
                  >
                    {statusLabel(printer.status)}
                  </span>
                </div>

                <div style={{ display: 'flex', gap: 16, marginTop: 6, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 16, color: C.textDim }}>IP: {printer.ip}</span>
                  <span style={{ fontSize: 16, color: C.textDim }}>纸宽: {printer.config.paperWidth}</span>
                  <span style={{ fontSize: 16, color: C.textDim }}>字号: {printer.config.fontSize}px</span>
                  <span style={{ fontSize: 16, color: C.textDim }}>LOGO: {printer.config.logoEnabled ? '开' : '关'}</span>
                </div>

                {printer.errorMessage && (
                  <div style={{ fontSize: 16, color: C.danger, marginTop: 4 }}>
                    {printer.errorMessage}
                  </div>
                )}

                <div style={{ fontSize: 16, color: C.textDim, marginTop: 4 }}>
                  最后活动: {printer.lastActiveAt}
                </div>
              </div>

              {/* 操作按钮 */}
              <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
                <button
                  style={{
                    ...BTN_BASE,
                    background: printer.status === 'offline' ? '#333' : C.accent,
                    color: C.white,
                    opacity: printer.status === 'offline' ? 0.5 : 1,
                    cursor: printer.status === 'offline' ? 'not-allowed' : 'pointer',
                  }}
                  disabled={printer.status === 'offline'}
                  onClick={() => handleTestPrint(printer)}
                >
                  {testPrintingId === printer.id ? '打印中...' : '测试打印'}
                </button>
                <button
                  style={{ ...BTN_BASE, background: C.cardAlt, color: C.text }}
                  onClick={() => setConfigTarget(printer)}
                >
                  配置
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── 打印队列 ── */}
      {activeTab === 'queue' && (
        <div>
          {/* 筛选条 */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
            {(
              [
                { key: 'all' as QueueFilter, label: '全部', count: queue.length },
                { key: 'pending' as QueueFilter, label: '待打印', count: queueCounts.pending },
                { key: 'printing' as QueueFilter, label: '打印中', count: queueCounts.printing },
                { key: 'completed' as QueueFilter, label: '已完成', count: queueCounts.completed },
                { key: 'failed' as QueueFilter, label: '失败', count: queueCounts.failed },
              ] as const
            ).map((f) => (
              <button
                key={f.key}
                style={filterBtnStyle(queueFilter === f.key)}
                onClick={() => setQueueFilter(f.key)}
              >
                {f.label} ({f.count})
              </button>
            ))}
          </div>

          {/* 队列列表 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {filteredQueue.length === 0 && (
              <div style={{ textAlign: 'center', padding: 40, color: C.textDim, fontSize: 18 }}>
                暂无打印任务
              </div>
            )}
            {filteredQueue.map((job) => (
              <div
                key={job.id}
                style={{
                  background: C.card,
                  borderRadius: 12,
                  padding: '16px 20px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  borderLeft: `4px solid ${jobStatusColor(job.status)}`,
                }}
              >
                {/* 状态标记 */}
                <span
                  style={{
                    fontSize: 16,
                    fontWeight: 600,
                    color: jobStatusColor(job.status),
                    minWidth: 64,
                    flexShrink: 0,
                  }}
                >
                  {jobStatusLabel(job.status)}
                </span>

                {/* 任务信息 */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 17, color: C.white, fontWeight: 500 }}>{job.title}</div>
                  <div style={{ fontSize: 16, color: C.textDim, marginTop: 2 }}>
                    {job.printerName} | {job.createdAt}
                    {job.completedAt && ` | 完成: ${job.completedAt}`}
                    {job.retries > 0 && ` | 重试: ${job.retries}次`}
                  </div>
                  {job.errorMessage && (
                    <div style={{ fontSize: 16, color: C.danger, marginTop: 2 }}>
                      {job.errorMessage}
                    </div>
                  )}
                </div>

                {/* 操作 */}
                {job.status === 'failed' && (
                  <button
                    style={{ ...BTN_BASE, background: C.accent, color: C.white }}
                    onClick={() => handleRetry(job.id)}
                  >
                    重试
                  </button>
                )}
                {job.status === 'printing' && (
                  <div
                    style={{
                      width: 20,
                      height: 20,
                      border: `3px solid ${C.accent}`,
                      borderTopColor: 'transparent',
                      borderRadius: '50%',
                      animation: 'txSpin 0.8s linear infinite',
                    }}
                  />
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 打印机配置弹层 ── */}
      {configTarget && (
        <PrinterConfigModal
          printer={configTarget}
          onSave={handleSaveConfig}
          onClose={() => setConfigTarget(null)}
        />
      )}

      {/* 旋转动画 */}
      <style>{`
        @keyframes txSpin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
