/**
 * 日清日结状态管理
 */
import { create } from 'zustand';
import type {
  DayCloseRecord, DayCloseStep, CloseStepCode, DayCloseAgentExplanation,
} from '../../../shared/api-types/p0-pages';

interface DayCloseState {
  record: DayCloseRecord | null;
  steps: DayCloseStep[];
  currentStep: number;
  agentExplanation: DayCloseAgentExplanation | null;
  loading: boolean;

  setRecord: (record: DayCloseRecord) => void;
  setSteps: (steps: DayCloseStep[]) => void;
  setCurrentStep: (step: number) => void;
  completeCurrentStep: () => void;
  setAgentExplanation: (explanation: DayCloseAgentExplanation) => void;
  setLoading: (loading: boolean) => void;
}

export const useDayCloseStore = create<DayCloseState>((set, get) => ({
  record: null,
  steps: [],
  currentStep: 0,
  agentExplanation: null,
  loading: false,

  setRecord: (record) => set({ record }),
  setSteps: (steps) => set({ steps }),
  setCurrentStep: (currentStep) => set({ currentStep }),
  completeCurrentStep: () => {
    const { steps, currentStep } = get();
    const updated = steps.map((s, i) =>
      i === currentStep ? { ...s, step_status: 'completed' as const }
      : i === currentStep + 1 ? { ...s, step_status: 'processing' as const }
      : s
    );
    set({
      steps: updated,
      currentStep: Math.min(currentStep + 1, steps.length - 1),
    });
  },
  setAgentExplanation: (agentExplanation) => set({ agentExplanation }),
  setLoading: (loading) => set({ loading }),
}));
