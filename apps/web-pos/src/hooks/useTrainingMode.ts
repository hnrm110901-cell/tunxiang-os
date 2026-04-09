/**
 * useTrainingMode — POS 训练/演示模式管理 Hook
 *
 * 职责：
 * - 全局状态管理（isTrainingMode 存 localStorage）
 * - 进入/退出训练模式需管理员密码验证
 * - 训练模式下所有写操作拦截，不写入真实 DB
 * - 提供训练场景枚举与进度追踪
 *
 * 编码规范：TypeScript strict，无 any
 */
import { useState, useEffect, useCallback } from 'react';

// ─── 常量 ───────────────────────────────────────────────────────────────────

const STORAGE_KEY = 'tx_pos_training_mode';
const SCENARIO_KEY = 'tx_pos_training_scenario';
const DEFAULT_PASSWORD = '888888';

// ─── 类型 ───────────────────────────────────────────────────────────────────

export type TrainingScenario =
  | 'cashier_basics'    // 新手收银
  | 'shift_handover'    // 换班交接
  | 'refund_process'    // 退单处理
  | 'banquet_open';     // 宴席开台

export interface TrainingScenarioInfo {
  id: TrainingScenario;
  label: string;
  description: string;
  estimatedMinutes: number;
  steps: string[];
}

export const TRAINING_SCENARIOS: TrainingScenarioInfo[] = [
  {
    id: 'cashier_basics',
    label: '新手收银',
    description: '学习基本收银流程：开台、点菜、结账、打印小票',
    estimatedMinutes: 15,
    steps: [
      '选择空桌并开台',
      '为桌台添加菜品（至少3道）',
      '修改菜品数量和做法',
      '进入结算页面',
      '选择支付方式并完成结账',
    ],
  },
  {
    id: 'shift_handover',
    label: '换班交接',
    description: '学习交接班流程：查看当班数据、核对现金、生成交接报告',
    estimatedMinutes: 10,
    steps: [
      '查看当班营收汇总',
      '核对现金实收与系统记录',
      '检查挂单与未结账桌台',
      '生成交接班报告',
      '确认并完成交接',
    ],
  },
  {
    id: 'refund_process',
    label: '退单处理',
    description: '学习退菜和反结账流程：退菜原因填写、反结账操作、退款确认',
    estimatedMinutes: 10,
    steps: [
      '选择一个已点菜的桌台',
      '对其中一道菜品发起退菜',
      '填写退菜原因（必填）',
      '对已结账订单发起反结账',
      '确认退款金额并完成',
    ],
  },
  {
    id: 'banquet_open',
    label: '宴席开台',
    description: '学习宴席场景：多桌关联开台、预设菜单、分桌上菜',
    estimatedMinutes: 20,
    steps: [
      '进入宴席模式选择宴席厅',
      '设置宴席桌数（至少3桌）',
      '关联预设宴席套餐菜单',
      '调整各桌的特殊要求',
      '确认开台并通知后厨',
    ],
  },
];

interface TrainingModeState {
  active: boolean;
  scenario: TrainingScenario | null;
  startedAt: string | null;
}

export interface UseTrainingModeResult {
  /** 是否处于训练模式 */
  isTrainingMode: boolean;
  /** 当前训练场景 */
  currentScenario: TrainingScenarioInfo | null;
  /** 训练开始时间 */
  startedAt: Date | null;
  /** 进入训练模式（需密码验证） */
  enterTrainingMode: (password: string, scenario: TrainingScenario) => boolean;
  /** 退出训练模式（需密码验证） */
  exitTrainingMode: (password: string) => boolean;
  /** 密码是否正确 */
  verifyPassword: (password: string) => boolean;
  /** 训练模式下拦截写操作：返回 true 表示已拦截（不应写 DB） */
  shouldInterceptWrite: () => boolean;
  /** 所有可选训练场景 */
  scenarios: TrainingScenarioInfo[];
}

// ─── 读取持久化状态 ────────────────────────────────────────────────────────

function loadState(): TrainingModeState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as TrainingModeState;
      return parsed;
    }
  } catch {
    // localStorage 不可用时降级为非训练模式
  }
  return { active: false, scenario: null, startedAt: null };
}

function saveState(state: TrainingModeState): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // 静默失败
  }
}

function clearState(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
    localStorage.removeItem(SCENARIO_KEY);
  } catch {
    // 静默失败
  }
}

// ─── Hook ───────────────────────────────────────────────────────────────────

export function useTrainingMode(): UseTrainingModeResult {
  const [state, setState] = useState<TrainingModeState>(loadState);

  // 同步 localStorage 变化（多 Tab 场景）
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) {
        setState(loadState());
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const verifyPassword = useCallback((password: string): boolean => {
    // TODO: 正式上线后从门店配置读取管理员密码，此处使用默认密码
    return password === DEFAULT_PASSWORD;
  }, []);

  const enterTrainingMode = useCallback((
    password: string,
    scenario: TrainingScenario,
  ): boolean => {
    if (!verifyPassword(password)) {
      return false;
    }
    const newState: TrainingModeState = {
      active: true,
      scenario,
      startedAt: new Date().toISOString(),
    };
    saveState(newState);
    setState(newState);
    return true;
  }, [verifyPassword]);

  const exitTrainingMode = useCallback((password: string): boolean => {
    if (!verifyPassword(password)) {
      return false;
    }
    clearState();
    setState({ active: false, scenario: null, startedAt: null });
    return true;
  }, [verifyPassword]);

  const shouldInterceptWrite = useCallback((): boolean => {
    return state.active;
  }, [state.active]);

  const currentScenario = state.scenario
    ? TRAINING_SCENARIOS.find((s) => s.id === state.scenario) ?? null
    : null;

  return {
    isTrainingMode: state.active,
    currentScenario,
    startedAt: state.startedAt ? new Date(state.startedAt) : null,
    enterTrainingMode,
    exitTrainingMode,
    verifyPassword,
    shouldInterceptWrite,
    scenarios: TRAINING_SCENARIOS,
  };
}
