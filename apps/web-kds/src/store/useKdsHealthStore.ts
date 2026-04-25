/**
 * useKdsHealthStore — Sprint C2
 *
 * Zustand store，记录 /kds/orders/delta 轮询的连接健康状态。供
 * <ConnectionHealthBadge /> 与未来 KDS 主页面共享同一份事实。
 *
 * 字段语义（参见 ConnectionHealthBadge.tsx 的状态机）：
 *   - lastSuccessAt:  最近一次 poll 成功（fetch resolve 200）的 epoch ms
 *   - inFlight:       是否有 poll 进行中（fetch 已发出尚未 resolve）
 *   - failureStreak:  连续失败次数；任意一次成功后归零
 *
 * 推导出的状态由组件计算：
 *   - synced:         lastSuccessAt 距今 < 10s 且非 inFlight
 *   - syncing:        inFlight === true
 *   - stale:          10s ≤ since(lastSuccessAt) ≤ 60s 且 failureStreak < 3
 *   - disconnected:   since(lastSuccessAt) > 60s 或 failureStreak ≥ 3
 *
 * 埋点路径（KDS 主页面或自定义 hook 中）：
 *   beforePoll() → 异步发请求 → 成功 markPollSuccess() / 失败 markPollFailure()
 */
import { create } from 'zustand';

export interface KdsHealthState {
  /** 上次 poll 成功的 epoch ms；-1 表示从未成功（初始） */
  lastSuccessAt: number;
  /** 是否有进行中的请求 */
  inFlight: boolean;
  /** 连续失败次数 */
  failureStreak: number;

  /** 一次 poll 开始 */
  beforePoll: () => void;
  /** poll 成功 */
  markPollSuccess: () => void;
  /** poll 失败 */
  markPollFailure: () => void;
  /** 测试 / 切店时复位 */
  reset: () => void;
}

/**
 * 创建一个独立 store。生产用单例 useKdsHealthStore；测试可调用
 * createKdsHealthStore() 拿到隔离实例。
 */
export function createKdsHealthStore() {
  return create<KdsHealthState>((set) => ({
    lastSuccessAt: -1,
    inFlight: false,
    failureStreak: 0,

    beforePoll: () => {
      set({ inFlight: true });
    },
    markPollSuccess: () => {
      set({
        lastSuccessAt: Date.now(),
        inFlight: false,
        failureStreak: 0,
      });
    },
    markPollFailure: () => {
      set((s) => ({
        inFlight: false,
        failureStreak: s.failureStreak + 1,
      }));
    },
    reset: () => {
      set({ lastSuccessAt: -1, inFlight: false, failureStreak: 0 });
    },
  }));
}

/** 全局单例 */
export const useKdsHealthStore = createKdsHealthStore();
