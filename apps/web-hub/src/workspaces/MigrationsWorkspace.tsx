/**
 * Workspace: Migrations — 迁移项目管理（替代 v1 TemplatesPage）
 *
 * 左侧列表 + 右侧 Object Page (8 Tab) + 五段式管线
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { hubGet, hubPost } from '../api/hubApi';

// ── 颜色常量 ──
const C = {
  bg: '#0A1418', surface: '#0E1E24', surface2: '#132932', surface3: '#1A3540',
  border: '#1A3540', border2: '#23485a',
  text: '#E6EDF1', text2: '#94A8B3', text3: '#647985',
  orange: '#FF6B2C', green: '#22C55E', yellow: '#F59E0B', red: '#EF4444', blue: '#3B82F6', purple: '#A855F7',
};

// ── 类型定义 ──

type StageStatus = 'done' | 'running' | 'paused' | 'waiting' | 'failed';
type MigrationFilter = 'all' | 'running' | 'done' | 'paused' | 'failed';
type TabKey = 'overview' | 'timeline' | 'actions' | 'traces' | 'cost' | 'logs' | 'related' | 'playbooks';

interface StageStates {
  mapping: StageStatus;
  replay: StageStatus;
  catchup: StageStatus;
  dualrun: StageStatus;
  cutover: StageStatus;
}

interface StageProgress {
  mapping: number;
  replay: number;
  catchup: number;
  dualrun: number;
  cutover: number;
}

interface MigrationProject {
  id: string;
  name: string;
  source: string;
  sourceVersion: string;
  sourceDataCount: number;
  sourceFieldCount: number;
  merchant: string;
  stage: keyof StageStates;
  stages: StageStates;
  progress: StageProgress;
  engineer: string;
  startDate: string;
  adapter: string;
  sli: {
    mappingCompleteness: number;
    replayProgress: number;
    replayRate: number;
    catchupDelay: number;
    catchupDiffRate: number;
    dualrunConsistency: number;
    dualrunDiffCount: number;
    cutoverWindow: number;
    cutoverRollbackReady: boolean;
  };
}

interface TimelineEvent {
  id: string;
  time: string;
  type: 'mapping' | 'replay' | 'catchup' | 'dualrun' | 'cutover' | 'error' | 'info';
  description: string;
  duration?: string;
  dataCount?: number;
}

// ── Mock 数据 ──

const MOCK_MIGRATIONS: MigrationProject[] = [
  {
    id: 'MIG-001', name: '徐记海鲜-品智POS迁移', source: '品智POS', sourceVersion: 'v5.2.1',
    sourceDataCount: 1285000, sourceFieldCount: 342, merchant: '徐记海鲜',
    stage: 'replay', stages: { mapping: 'done', replay: 'running', catchup: 'waiting', dualrun: 'waiting', cutover: 'waiting' },
    progress: { mapping: 100, replay: 67, catchup: 0, dualrun: 0, cutover: 0 },
    engineer: '陈工', startDate: '2026-03-15', adapter: 'pinzhi',
    sli: { mappingCompleteness: 100, replayProgress: 67, replayRate: 4200, catchupDelay: 0, catchupDiffRate: 0, dualrunConsistency: 0, dualrunDiffCount: 0, cutoverWindow: 0, cutoverRollbackReady: false },
  },
  {
    id: 'MIG-002', name: '尝在一起-天财迁移', source: '天财商龙', sourceVersion: 'v8.0.3',
    sourceDataCount: 890000, sourceFieldCount: 278, merchant: '尝在一起',
    stage: 'catchup', stages: { mapping: 'done', replay: 'done', catchup: 'running', dualrun: 'waiting', cutover: 'waiting' },
    progress: { mapping: 100, replay: 100, catchup: 45, dualrun: 0, cutover: 0 },
    engineer: '王工', startDate: '2026-02-20', adapter: 'tiancai-shanglong',
    sli: { mappingCompleteness: 100, replayProgress: 100, replayRate: 0, catchupDelay: 3.2, catchupDiffRate: 0.8, dualrunConsistency: 0, dualrunDiffCount: 0, cutoverWindow: 0, cutoverRollbackReady: false },
  },
  {
    id: 'MIG-003', name: '最黔线-奥琦玮迁移', source: '奥琦玮', sourceVersion: 'v4.1.0',
    sourceDataCount: 560000, sourceFieldCount: 215, merchant: '最黔线',
    stage: 'dualrun', stages: { mapping: 'done', replay: 'done', catchup: 'done', dualrun: 'running', cutover: 'waiting' },
    progress: { mapping: 100, replay: 100, catchup: 100, dualrun: 72, cutover: 0 },
    engineer: '李工', startDate: '2026-01-10', adapter: 'aoqiwei',
    sli: { mappingCompleteness: 100, replayProgress: 100, replayRate: 0, catchupDelay: 0, catchupDiffRate: 0, dualrunConsistency: 99.2, dualrunDiffCount: 34, cutoverWindow: 0, cutoverRollbackReady: false },
  },
  {
    id: 'MIG-004', name: '尚宫厨-客如云迁移', source: '客如云', sourceVersion: 'v6.5.2',
    sourceDataCount: 720000, sourceFieldCount: 298, merchant: '尚宫厨',
    stage: 'cutover', stages: { mapping: 'done', replay: 'done', catchup: 'done', dualrun: 'done', cutover: 'running' },
    progress: { mapping: 100, replay: 100, catchup: 100, dualrun: 100, cutover: 30 },
    engineer: '张工', startDate: '2025-12-01', adapter: 'keruyun',
    sli: { mappingCompleteness: 100, replayProgress: 100, replayRate: 0, catchupDelay: 0, catchupDiffRate: 0, dualrunConsistency: 99.8, dualrunDiffCount: 5, cutoverWindow: 15, cutoverRollbackReady: true },
  },
  {
    id: 'MIG-005', name: '湘粤楼-美团收银迁移', source: '美团收银', sourceVersion: 'v3.8.0',
    sourceDataCount: 1050000, sourceFieldCount: 310, merchant: '湘粤楼',
    stage: 'mapping', stages: { mapping: 'running', replay: 'waiting', catchup: 'waiting', dualrun: 'waiting', cutover: 'waiting' },
    progress: { mapping: 38, replay: 0, catchup: 0, dualrun: 0, cutover: 0 },
    engineer: '陈工', startDate: '2026-04-10', adapter: 'meituan',
    sli: { mappingCompleteness: 38, replayProgress: 0, replayRate: 0, catchupDelay: 0, catchupDiffRate: 0, dualrunConsistency: 0, dualrunDiffCount: 0, cutoverWindow: 0, cutoverRollbackReady: false },
  },
  {
    id: 'MIG-006', name: '悦麻辣-微生活迁移', source: '微生活', sourceVersion: 'v2.9.5',
    sourceDataCount: 420000, sourceFieldCount: 186, merchant: '悦麻辣',
    stage: 'replay', stages: { mapping: 'done', replay: 'paused', catchup: 'waiting', dualrun: 'waiting', cutover: 'waiting' },
    progress: { mapping: 100, replay: 23, catchup: 0, dualrun: 0, cutover: 0 },
    engineer: '王工', startDate: '2026-03-28', adapter: 'weishenghuo',
    sli: { mappingCompleteness: 100, replayProgress: 23, replayRate: 0, catchupDelay: 0, catchupDiffRate: 0, dualrunConsistency: 0, dualrunDiffCount: 0, cutoverWindow: 0, cutoverRollbackReady: false },
  },
  {
    id: 'MIG-007', name: '渝乡辣婆婆-二维火迁移', source: '二维火', sourceVersion: 'v7.2.1',
    sourceDataCount: 380000, sourceFieldCount: 201, merchant: '渝乡辣婆婆',
    stage: 'mapping', stages: { mapping: 'failed', replay: 'waiting', catchup: 'waiting', dualrun: 'waiting', cutover: 'waiting' },
    progress: { mapping: 62, replay: 0, catchup: 0, dualrun: 0, cutover: 0 },
    engineer: '李工', startDate: '2026-04-05', adapter: 'erp',
    sli: { mappingCompleteness: 62, replayProgress: 0, replayRate: 0, catchupDelay: 0, catchupDiffRate: 0, dualrunConsistency: 0, dualrunDiffCount: 0, cutoverWindow: 0, cutoverRollbackReady: false },
  },
  {
    id: 'MIG-008', name: '老碗会-饿了么迁移', source: '饿了么商家版', sourceVersion: 'v9.1.0',
    sourceDataCount: 670000, sourceFieldCount: 256, merchant: '老碗会',
    stage: 'cutover', stages: { mapping: 'done', replay: 'done', catchup: 'done', dualrun: 'done', cutover: 'done' },
    progress: { mapping: 100, replay: 100, catchup: 100, dualrun: 100, cutover: 100 },
    engineer: '张工', startDate: '2025-11-15', adapter: 'eleme',
    sli: { mappingCompleteness: 100, replayProgress: 100, replayRate: 0, catchupDelay: 0, catchupDiffRate: 0, dualrunConsistency: 99.97, dualrunDiffCount: 0, cutoverWindow: 8, cutoverRollbackReady: true },
  },
];

const STAGE_KEYS: (keyof StageStates)[] = ['mapping', 'replay', 'catchup', 'dualrun', 'cutover'];
const STAGE_LABELS: Record<keyof StageStates, string> = {
  mapping: '映射', replay: '历史回放', catchup: '增量追平', dualrun: '双跑对账', cutover: '切流',
};
const STATUS_ICON: Record<StageStatus, string> = {
  done: '\u2713', running: '\u25B6', paused: '\u23F8', waiting: '\u23F3', failed: '\u2717',
};
const STATUS_COLOR: Record<StageStatus, string> = {
  done: C.green, running: C.orange, paused: C.yellow, waiting: C.text3, failed: C.red,
};
const STATUS_LABEL: Record<StageStatus, string> = {
  done: '已完成', running: '进行中', paused: '暂停', waiting: '等待', failed: '失败',
};

const TABS: { key: TabKey; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'timeline', label: 'Timeline' },
  { key: 'actions', label: 'Actions' },
  { key: 'traces', label: 'Traces' },
  { key: 'cost', label: 'Cost' },
  { key: 'logs', label: 'Logs' },
  { key: 'related', label: 'Related' },
  { key: 'playbooks', label: 'Playbooks' },
];

const FILTERS: { key: MigrationFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'running', label: '进行中' },
  { key: 'done', label: '已完成' },
  { key: 'paused', label: '暂停' },
  { key: 'failed', label: '失败' },
];

// ── Helpers ──

function Placeholder({ label }: { label: string }) {
  return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 200, color: C.text3, fontSize: 14 }}>{label}</div>;
}

function ConfirmDialog({ title, description, onConfirm, onCancel }: {
  title: string; description: string; onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }} onClick={onCancel}>
      <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: 24, minWidth: 360, maxWidth: 480 }} onClick={e => e.stopPropagation()}>
        <div style={{ fontSize: 16, fontWeight: 700, color: C.text, marginBottom: 8 }}>{title}</div>
        <div style={{ fontSize: 13, color: C.text2, marginBottom: 20 }}>{description}</div>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onCancel} style={{ background: 'transparent', color: C.text2, border: `1px solid ${C.border}`, borderRadius: 6, padding: '8px 16px', fontSize: 13, cursor: 'pointer' }}>取消</button>
          <button onClick={onConfirm} style={{ background: C.orange, color: '#fff', border: 'none', borderRadius: 6, padding: '8px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>确认</button>
        </div>
      </div>
    </div>
  );
}

function MetricCard({ label, value, unit, color }: { label: string; value: string | number; unit?: string; color: string }) {
  return (
    <div style={{ flex: '1 1 140px', background: C.surface2, borderRadius: 8, padding: 12, border: `1px solid ${C.border}` }}>
      <div style={{ fontSize: 11, color: C.text3, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color }}>
        {value}<span style={{ fontSize: 12, fontWeight: 400, marginLeft: 2 }}>{unit}</span>
      </div>
    </div>
  );
}

/** 小型五段进度条（列表行用） */
function MiniPipeline({ stages, progress }: { stages: StageStates; progress: StageProgress }) {
  return (
    <div style={{ display: 'flex', gap: 2, height: 4, borderRadius: 2, overflow: 'hidden' }}>
      {STAGE_KEYS.map(key => {
        const status = stages[key];
        const pct = progress[key];
        const bg = status === 'waiting' ? C.surface3 : STATUS_COLOR[status] + '44';
        const fill = STATUS_COLOR[status];
        return (
          <div key={key} style={{ flex: 1, background: bg, position: 'relative', overflow: 'hidden' }}>
            <div style={{ width: `${pct}%`, height: '100%', background: fill, transition: 'width 0.3s' }} />
          </div>
        );
      })}
    </div>
  );
}

function getMigrationStatus(m: MigrationProject): MigrationFilter {
  const allDone = Object.values(m.stages).every(s => s === 'done');
  if (allDone) return 'done';
  const hasFailed = Object.values(m.stages).some(s => s === 'failed');
  if (hasFailed) return 'failed';
  const hasPaused = Object.values(m.stages).some(s => s === 'paused');
  if (hasPaused) return 'paused';
  return 'running';
}

// ── Overview Tab — 五段式管线 ──

function OverviewTab({ migration }: { migration: MigrationProject }) {
  const { stages, progress, sli } = migration;

  const stageDetails: Record<keyof StageStates, { metrics: { label: string; value: string }[] }> = {
    mapping: {
      metrics: [{ label: '完整度', value: `${sli.mappingCompleteness}%` }],
    },
    replay: {
      metrics: [
        { label: '回放进度', value: `${sli.replayProgress}%` },
        { label: '速率', value: sli.replayRate > 0 ? `${sli.replayRate} 条/秒` : '-' },
      ],
    },
    catchup: {
      metrics: [
        { label: '延迟', value: sli.catchupDelay > 0 ? `${sli.catchupDelay}s` : '-' },
        { label: '差异率', value: sli.catchupDiffRate > 0 ? `${sli.catchupDiffRate}%` : '-' },
      ],
    },
    dualrun: {
      metrics: [
        { label: '一致率', value: sli.dualrunConsistency > 0 ? `${sli.dualrunConsistency}%` : '-' },
        { label: '差异条数', value: sli.dualrunDiffCount > 0 ? `${sli.dualrunDiffCount}` : '-' },
      ],
    },
    cutover: {
      metrics: [
        { label: '切换窗口', value: sli.cutoverWindow > 0 ? `${sli.cutoverWindow} 分钟` : '-' },
        { label: '回滚就绪', value: sli.cutoverRollbackReady ? '是' : '否' },
      ],
    },
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 五段管线 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 20, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 16 }}>迁移管线</div>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 0 }}>
          {STAGE_KEYS.map((key, i) => {
            const status = stages[key];
            const pct = progress[key];
            const color = STATUS_COLOR[status];
            const details = stageDetails[key];
            const isLast = i === STAGE_KEYS.length - 1;

            return (
              <div key={key} style={{ display: 'flex', alignItems: 'flex-start', flex: 1, minWidth: 0 }}>
                {/* 阶段卡片 */}
                <div style={{
                  flex: 1, minWidth: 0, background: C.surface2, borderRadius: 10, padding: 14,
                  border: `1px solid ${status === 'running' ? color : C.border}`,
                  boxShadow: status === 'running' ? `0 0 12px ${color}33` : 'none',
                }}>
                  {/* 阶段头 */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                    <span style={{
                      width: 22, height: 22, borderRadius: 11, background: color + '22',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 11, color, fontWeight: 700,
                    }}>{STATUS_ICON[status]}</span>
                    <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{STAGE_LABELS[key]}</span>
                  </div>
                  {/* 进度条 */}
                  <div style={{ height: 6, borderRadius: 3, background: C.surface3, overflow: 'hidden', marginBottom: 8 }}>
                    <div style={{
                      width: `${pct}%`, height: '100%', borderRadius: 3, background: color,
                      transition: 'width 0.3s',
                      ...(status === 'running' ? { animation: 'migPulse 1.5s ease-in-out infinite' } : {}),
                    }} />
                  </div>
                  <div style={{ fontSize: 11, color: C.text3, marginBottom: 8 }}>
                    {pct}% {STATUS_LABEL[status]}
                  </div>
                  {/* SLI 指标 */}
                  {details.metrics.map(m => (
                    <div key={m.label} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 3 }}>
                      <span style={{ color: C.text3 }}>{m.label}</span>
                      <span style={{ color: C.text2, fontWeight: 600 }}>{m.value}</span>
                    </div>
                  ))}
                </div>
                {/* 箭头连线 */}
                {!isLast && (
                  <div style={{ display: 'flex', alignItems: 'center', padding: '30px 4px 0', flexShrink: 0 }}>
                    <div style={{
                      width: 24, height: 2, borderRadius: 1,
                      background: stages[STAGE_KEYS[i + 1]] === 'waiting'
                        ? C.text3 + '44'
                        : status === 'done'
                          ? C.green
                          : status === 'running'
                            ? C.orange
                            : C.text3 + '44',
                    }} />
                    <div style={{
                      width: 0, height: 0,
                      borderTop: '5px solid transparent', borderBottom: '5px solid transparent',
                      borderLeft: `6px solid ${
                        stages[STAGE_KEYS[i + 1]] === 'waiting'
                          ? C.text3 + '44'
                          : status === 'done'
                            ? C.green
                            : status === 'running'
                              ? C.orange
                              : C.text3 + '44'
                      }`,
                    }} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* 源系统 + 目标系统 */}
      <div style={{ display: 'flex', gap: 16 }}>
        <div style={{ flex: 1, background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>源系统</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px 24px', fontSize: 13 }}>
            {([
              ['系统名', migration.source],
              ['版本', migration.sourceVersion],
              ['数据量', `${(migration.sourceDataCount / 10000).toFixed(1)} 万条`],
              ['字段数', `${migration.sourceFieldCount} 个`],
            ] as const).map(([label, val]) => (
              <div key={label}>
                <div style={{ color: C.text3, fontSize: 11, marginBottom: 2 }}>{label}</div>
                <div style={{ color: C.text }}>{val}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ flex: 1, background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>目标系统</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px 24px', fontSize: 13 }}>
            {([
              ['系统', '屯象OS'],
              ['Adapter', migration.adapter],
              ['负责工程师', migration.engineer],
              ['商户', migration.merchant],
            ] as const).map(([label, val]) => (
              <div key={label}>
                <div style={{ color: C.text3, fontSize: 11, marginBottom: 2 }}>{label}</div>
                <div style={{ color: C.text }}>{val}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 项目信息 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>项目信息</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px 24px', fontSize: 13 }}>
          {([
            ['项目编号', migration.id],
            ['开始日期', migration.startDate],
            ['当前阶段', STAGE_LABELS[migration.stage]],
          ] as const).map(([label, val]) => (
            <div key={label}>
              <div style={{ color: C.text3, fontSize: 11, marginBottom: 2 }}>{label}</div>
              <div style={{ color: C.text }}>{val}</div>
            </div>
          ))}
        </div>
      </div>

      {/* keyframes for pulse animation */}
      <style>{`
        @keyframes migPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.6; }
        }
      `}</style>
    </div>
  );
}

// ── Timeline Tab ──

function TimelineTab({ migration }: { migration: MigrationProject }) {
  const [range, setRange] = useState<'7d' | '30d' | '全部'>('30d');

  const EVENT_COLOR: Record<string, string> = {
    mapping: C.blue, replay: C.purple, catchup: C.yellow, dualrun: C.orange, cutover: C.green, error: C.red, info: C.text3,
  };

  const MOCK_TIMELINE: TimelineEvent[] = [
    { id: 'te1', time: '2026-04-20 10:00', type: 'replay', description: '历史回放进度 67%', dataCount: 861450 },
    { id: 'te2', time: '2026-04-18 08:30', type: 'error', description: '回放批次 #128 遇到字段类型冲突，自动跳过 3 条' },
    { id: 'te3', time: '2026-04-15 14:00', type: 'replay', description: '历史回放启动，预计 5 天完成', dataCount: 0 },
    { id: 'te4', time: '2026-04-14 18:00', type: 'mapping', description: '映射完成，100% 字段已映射', duration: '30天' },
    { id: 'te5', time: '2026-04-10 09:00', type: 'mapping', description: '映射进度 85%，剩余 52 个字段待确认' },
    { id: 'te6', time: '2026-03-25 10:30', type: 'mapping', description: '映射进度 50%，已映射 171 个字段' },
    { id: 'te7', time: '2026-03-20 14:00', type: 'info', description: '实施工程师现场勘查完成，确认数据源接口' },
    { id: 'te8', time: '2026-03-15 09:00', type: 'mapping', description: '迁移项目启动，开始字段映射' },
  ];

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {(['7d', '30d', '全部'] as const).map(r => (
          <button key={r} onClick={() => setRange(r)} style={{
            background: range === r ? C.orange + '22' : 'transparent',
            color: range === r ? C.orange : C.text3,
            border: `1px solid ${range === r ? C.orange : C.border}`,
            borderRadius: 6, padding: '4px 12px', fontSize: 12, cursor: 'pointer',
          }}>{r}</button>
        ))}
      </div>
      <div style={{ position: 'relative', paddingLeft: 24 }}>
        <div style={{ position: 'absolute', left: 7, top: 4, bottom: 4, width: 2, background: C.border }} />
        {MOCK_TIMELINE.map((evt, i) => (
          <div key={evt.id} style={{ display: 'flex', gap: 12, marginBottom: i < MOCK_TIMELINE.length - 1 ? 20 : 0, position: 'relative' }}>
            <div style={{
              position: 'absolute', left: -20, top: 2, width: 12, height: 12, borderRadius: 6,
              background: EVENT_COLOR[evt.type] || C.text3, border: `2px solid ${C.surface}`,
            }} />
            <div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 2 }}>
                <span style={{ fontSize: 11, color: C.text3, fontFamily: 'monospace' }}>{evt.time}</span>
                {evt.duration && <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: C.green + '22', color: C.green }}>耗时 {evt.duration}</span>}
                {evt.dataCount !== undefined && evt.dataCount > 0 && (
                  <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: C.blue + '22', color: C.blue }}>
                    {(evt.dataCount / 10000).toFixed(1)} 万条
                  </span>
                )}
              </div>
              <div style={{ fontSize: 13, color: C.text }}>{evt.description}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Actions Tab ──

function ActionsTab({ migration }: { migration: MigrationProject }) {
  const [confirm, setConfirm] = useState<{ title: string; desc: string; action: () => void } | null>(null);

  const doAction = useCallback(async (path: string, body?: unknown) => {
    try {
      await hubPost(path, body);
    } catch {
      // API 未就绪，静默降级
    }
    setConfirm(null);
  }, []);

  const currentStageLabel = STAGE_LABELS[migration.stage];
  const currentIdx = STAGE_KEYS.indexOf(migration.stage);
  const nextStage = currentIdx < STAGE_KEYS.length - 1 ? STAGE_LABELS[STAGE_KEYS[currentIdx + 1]] : null;

  const actions = [
    ...(nextStage ? [{
      icon: '\u25B6', title: `推进到「${nextStage}」`, desc: `完成当前「${currentStageLabel}」阶段，推进到下一阶段`,
      color: C.green, onClick: () => setConfirm({ title: '推进阶段', desc: `确认将「${migration.name}」从「${currentStageLabel}」推进到「${nextStage}」？`, action: () => doAction(`/migrations/${migration.id}/advance`) }),
    }] : []),
    {
      icon: '\u23F8', title: '暂停当前阶段', desc: `暂停「${currentStageLabel}」阶段的执行`,
      color: C.yellow, onClick: () => setConfirm({ title: '暂停阶段', desc: `确认暂停「${migration.name}」的「${currentStageLabel}」阶段？`, action: () => doAction(`/migrations/${migration.id}/pause`) }),
    },
    {
      icon: '\u21A9', title: '回滚到上一检查点', desc: '回滚到最近的安全检查点状态',
      color: C.red, onClick: () => setConfirm({ title: '回滚', desc: `确认将「${migration.name}」回滚到上一检查点？此操作不可撤销。`, action: () => doAction(`/migrations/${migration.id}/rollback`) }),
    },
    {
      icon: '\u{1F4E4}', title: '导出差异报告', desc: '导出当前阶段的差异数据对比报告',
      color: C.blue, onClick: () => doAction(`/migrations/${migration.id}/export-diff`),
    },
    {
      icon: '\u{1F504}', title: '重新执行当前阶段', desc: `从头重新运行「${currentStageLabel}」阶段`,
      color: C.purple, onClick: () => setConfirm({ title: '重新执行', desc: `确认重新执行「${migration.name}」的「${currentStageLabel}」阶段？当前进度将清零。`, action: () => doAction(`/migrations/${migration.id}/rerun`) }),
    },
  ];

  return (
    <div>
      {confirm && <ConfirmDialog title={confirm.title} description={confirm.desc} onConfirm={confirm.action} onCancel={() => setConfirm(null)} />}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {actions.map(a => (
          <button key={a.title} onClick={a.onClick} style={{
            background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 16,
            cursor: 'pointer', textAlign: 'left', display: 'flex', gap: 12, alignItems: 'flex-start',
          }}>
            <span style={{ fontSize: 20, width: 28, textAlign: 'center' }}>{a.icon}</span>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: a.color, marginBottom: 4 }}>{a.title}</div>
              <div style={{ fontSize: 12, color: C.text3 }}>{a.desc}</div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Related Tab ──

function RelatedTab({ migration }: { migration: MigrationProject }) {
  const relations = [
    { type: '商户', name: migration.merchant, id: `merchant-${migration.id}` },
    { type: 'Adapter', name: migration.adapter, id: `adapter-${migration.adapter}` },
    { type: '工单', name: `${migration.name}-字段映射确认`, id: `ticket-${migration.id}-001` },
    { type: '工单', name: `${migration.name}-数据差异处理`, id: `ticket-${migration.id}-002` },
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {relations.map(r => (
        <div key={r.id} style={{ background: C.surface, borderRadius: 8, padding: 12, border: `1px solid ${C.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <span style={{ fontSize: 11, color: C.text3, marginRight: 8 }}>{r.type}</span>
            <span style={{ fontSize: 13, color: C.text, fontWeight: 600 }}>{r.name}</span>
          </div>
          <span style={{ fontSize: 11, color: C.text3, fontFamily: 'monospace' }}>{r.id}</span>
        </div>
      ))}
    </div>
  );
}

// ── Main Export ──

export function MigrationsWorkspace() {
  const [migrations, setMigrations] = useState<MigrationProject[]>(MOCK_MIGRATIONS);
  const [selected, setSelected] = useState<MigrationProject | null>(null);
  const [filter, setFilter] = useState<MigrationFilter>('all');
  const [tab, setTab] = useState<TabKey>('overview');

  useEffect(() => {
    hubGet<MigrationProject[]>('/migrations')
      .then(data => { if (Array.isArray(data) && data.length > 0) setMigrations(data); })
      .catch(() => { /* 使用 Mock */ });
  }, []);

  const filtered = useMemo(() => {
    if (filter === 'all') return migrations;
    return migrations.filter(m => getMigrationStatus(m) === filter);
  }, [migrations, filter]);

  const counts = useMemo(() => {
    const m: Record<string, number> = { all: migrations.length };
    for (const mig of migrations) {
      const s = getMigrationStatus(mig);
      m[s] = (m[s] || 0) + 1;
    }
    return m;
  }, [migrations]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', color: C.text }}>
      {/* 顶部栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ fontSize: 20, fontWeight: 700 }}>迁移项目</div>
      </div>

      <div style={{ display: 'flex', gap: 16, flex: 1, minHeight: 0 }}>
        {/* 左侧列表 */}
        <div style={{ width: 380, flexShrink: 0, display: 'flex', flexDirection: 'column', background: C.surface, borderRadius: 10, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
          {/* 筛选 chips */}
          <div style={{ padding: '12px 14px', borderBottom: `1px solid ${C.border}`, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {FILTERS.map(f => (
              <button key={f.key} onClick={() => setFilter(f.key)} style={{
                background: filter === f.key ? C.orange + '22' : 'transparent',
                color: filter === f.key ? C.orange : C.text3,
                border: `1px solid ${filter === f.key ? C.orange : C.border}`,
                borderRadius: 20, padding: '3px 10px', fontSize: 11, cursor: 'pointer',
              }}>
                {f.label} {counts[f.key] ?? 0}
              </button>
            ))}
          </div>
          {/* 列表项 */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {filtered.map(mig => {
              const isActive = selected?.id === mig.id;
              const status = getMigrationStatus(mig);
              const statusColor = status === 'done' ? C.green : status === 'failed' ? C.red : status === 'paused' ? C.yellow : C.orange;
              return (
                <div key={mig.id} onClick={() => { setSelected(mig); setTab('overview'); }} style={{
                  padding: '10px 14px', cursor: 'pointer',
                  borderLeft: isActive ? `3px solid ${C.orange}` : '3px solid transparent',
                  background: isActive ? C.orange + '0D' : 'transparent',
                  borderBottom: `1px solid ${C.border}`,
                }}>
                  <MiniPipeline stages={mig.stages} progress={mig.progress} />
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, marginBottom: 2 }}>
                    <span style={{ width: 8, height: 8, borderRadius: 4, background: statusColor, flexShrink: 0 }} />
                    <span style={{ fontSize: 13, fontWeight: 600, color: C.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{mig.name}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: C.text3 }}>
                    <span>{mig.source} / {mig.merchant}</span>
                    <span>{STAGE_LABELS[mig.stage]}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 右侧 Object Page */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {!selected ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: C.text3, fontSize: 14 }}>
              选择一个迁移项目查看详情
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
              {/* Header */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                <span style={{ width: 10, height: 10, borderRadius: 5, background: STATUS_COLOR[selected.stages[selected.stage]] }} />
                <span style={{ fontSize: 16, fontWeight: 700, color: C.text }}>{selected.name}</span>
                <span style={{ fontSize: 12, color: C.text3, fontFamily: 'monospace' }}>{selected.id}</span>
                <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, background: STATUS_COLOR[selected.stages[selected.stage]] + '22', color: STATUS_COLOR[selected.stages[selected.stage]], fontWeight: 600 }}>
                  {STAGE_LABELS[selected.stage]} - {STATUS_LABEL[selected.stages[selected.stage]]}
                </span>
              </div>
              {/* Tab bar */}
              <div style={{ display: 'flex', gap: 0, borderBottom: `1px solid ${C.border}`, marginBottom: 16 }}>
                {TABS.map(t => (
                  <button key={t.key} onClick={() => setTab(t.key)} style={{
                    padding: '8px 14px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
                    color: tab === t.key ? C.orange : C.text3,
                    borderBottom: tab === t.key ? `2px solid ${C.orange}` : '2px solid transparent',
                    background: 'transparent', border: 'none', borderBottomStyle: 'solid' as const,
                  }}>{t.label}</button>
                ))}
              </div>
              {/* Tab content */}
              <div style={{ flex: 1, overflowY: 'auto' }}>
                {tab === 'overview' && <OverviewTab migration={selected} />}
                {tab === 'timeline' && <TimelineTab migration={selected} />}
                {tab === 'actions' && <ActionsTab migration={selected} />}
                {tab === 'traces' && <Placeholder label="Trace 数据接入中" />}
                {tab === 'cost' && <Placeholder label="成本数据接入中" />}
                {tab === 'logs' && <Placeholder label="日志接入中" />}
                {tab === 'related' && <RelatedTab migration={selected} />}
                {tab === 'playbooks' && <Placeholder label="关联剧本列表" />}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
