/**
 * 总控 Agent 工作台状态管理
 */
import { create } from 'zustand';
import type {
  OrchestratorTaskInput, OrchestratorStep, OrchestratorResult, ToolCallRecord,
} from '../../../shared/api-types/p0-pages';

type PageState = 'empty' | 'planning' | 'running' | 'partial_success' | 'done' | 'error';

interface OrchestratorState {
  taskInput: string;
  pageState: PageState;
  steps: OrchestratorStep[];
  currentStep: number;
  result: OrchestratorResult | null;
  toolCalls: ToolCallRecord[];
  errorMessage: string;

  setTaskInput: (input: string) => void;
  setPageState: (state: PageState) => void;
  setSteps: (steps: OrchestratorStep[], current: number) => void;
  setResult: (result: OrchestratorResult) => void;
  setToolCalls: (calls: ToolCallRecord[]) => void;
  setError: (msg: string) => void;
  reset: () => void;
}

export const useOrchestratorStore = create<OrchestratorState>((set) => ({
  taskInput: '',
  pageState: 'empty',
  steps: [],
  currentStep: 0,
  result: null,
  toolCalls: [],
  errorMessage: '',

  setTaskInput: (taskInput) => set({ taskInput }),
  setPageState: (pageState) => set({ pageState }),
  setSteps: (steps, currentStep) => set({ steps, currentStep }),
  setResult: (result) => set({ result, pageState: 'done' }),
  setToolCalls: (toolCalls) => set({ toolCalls }),
  setError: (errorMessage) => set({ errorMessage, pageState: 'error' }),
  reset: () => set({
    taskInput: '', pageState: 'empty', steps: [], currentStep: 0,
    result: null, toolCalls: [], errorMessage: '',
  }),
}));
