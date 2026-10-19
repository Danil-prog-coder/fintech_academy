import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

import { type DemoScenario, type ReplyScenario } from '../config/scenarios';

export type AiReplyStatus = 'idle' | 'preparing' | 'ready' | 'error';

export interface LetterAiReply {
  status: AiReplyStatus;
  /** Текущий шаг подготовки (0..2). */
  step: number;
  scenario: ReplyScenario | null;
}

interface AiReplyState {
  byLetter: Record<string, LetterAiReply>;
  demoScenario: DemoScenario;
  panelCollapsed: boolean;
}

const initialState: AiReplyState = {
  byLetter: {},
  demoScenario: 'complete',
  panelCollapsed: false,
};

const idle: LetterAiReply = { status: 'idle', step: 0, scenario: null };

interface LetterPayload {
  letterId: string;
}

export const aiReplySlice = createSlice({
  name: 'aiReply',
  initialState,
  reducers: {
    preparationStarted: (state, action: PayloadAction<LetterPayload>) => {
      state.byLetter[action.payload.letterId] = { status: 'preparing', step: 0, scenario: null };
      state.panelCollapsed = false;
    },
    stepAdvanced: (state, action: PayloadAction<LetterPayload & { step: number }>) => {
      const reply = state.byLetter[action.payload.letterId];
      if (reply) {
        reply.step = action.payload.step;
      }
    },
    preparationSucceeded: (
      state,
      action: PayloadAction<LetterPayload & { scenario: ReplyScenario }>,
    ) => {
      state.byLetter[action.payload.letterId] = {
        status: 'ready',
        step: 3,
        scenario: action.payload.scenario,
      };
    },
    /** Ошибка AI не трогает черновик. Демо-сбой срабатывает один раз — повтор успешен. */
    preparationFailed: (state, action: PayloadAction<LetterPayload>) => {
      state.byLetter[action.payload.letterId] = { status: 'error', step: 0, scenario: 'error' };
      state.demoScenario = 'complete';
    },
    aiReplyReset: (state, action: PayloadAction<LetterPayload>) => {
      Reflect.deleteProperty(state.byLetter, action.payload.letterId);
    },
    allAiRepliesReset: (state) => {
      state.byLetter = {};
      state.panelCollapsed = false;
    },
    demoScenarioChanged: (state, action: PayloadAction<DemoScenario>) => {
      state.demoScenario = action.payload;
    },
    panelCollapsedChanged: (state, action: PayloadAction<boolean>) => {
      state.panelCollapsed = action.payload;
    },
  },
  selectors: {
    selectDemoScenario: (state) => state.demoScenario,
    selectPanelCollapsed: (state) => state.panelCollapsed,
  },
});

export const {
  preparationStarted,
  stepAdvanced,
  preparationSucceeded,
  preparationFailed,
  aiReplyReset,
  allAiRepliesReset,
  demoScenarioChanged,
  panelCollapsedChanged,
} = aiReplySlice.actions;

export const { selectDemoScenario, selectPanelCollapsed } = aiReplySlice.selectors;

export const selectAiReply = (state: RootState, letterId: string | null): LetterAiReply =>
  (letterId ? state.aiReply.byLetter[letterId] : undefined) ?? idle;
