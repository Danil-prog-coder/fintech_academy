import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

export type RefineStatus = 'idle' | 'loading' | 'done' | 'error';

export interface LetterRefine {
  status: RefineStatus;
  query: string;
  /** Текст до последнего AI-изменения — для отмены. */
  previousText: string | null;
  changed: boolean;
  resultTitle: string;
  resultDescription: string;
}

interface RefineState {
  byLetter: Record<string, LetterRefine>;
  /** Демонстрация сбоя: следующий запрос завершится ошибкой (один раз). */
  failNextRequest: boolean;
}

const initialState: RefineState = {
  byLetter: {},
  failNextRequest: false,
};

const idle: LetterRefine = {
  status: 'idle',
  query: '',
  previousText: null,
  changed: false,
  resultTitle: '',
  resultDescription: '',
};

interface LetterPayload {
  letterId: string;
}

export const refineSlice = createSlice({
  name: 'refine',
  initialState,
  reducers: {
    refineStarted: (state, action: PayloadAction<LetterPayload & { query: string }>) => {
      state.byLetter[action.payload.letterId] = {
        ...(state.byLetter[action.payload.letterId] ?? idle),
        status: 'loading',
        query: action.payload.query,
      };
    },
    refineSucceeded: (
      state,
      action: PayloadAction<
        LetterPayload & Omit<LetterRefine, 'status'> & { previousText: string | null }
      >,
    ) => {
      const { letterId, ...result } = action.payload;
      state.byLetter[letterId] = { ...result, status: 'done' };
    },
    refineFailed: (state, action: PayloadAction<LetterPayload>) => {
      const current = state.byLetter[action.payload.letterId] ?? idle;
      state.byLetter[action.payload.letterId] = { ...current, status: 'error' };
      state.failNextRequest = false;
    },
    refineCleared: (state, action: PayloadAction<LetterPayload>) => {
      Reflect.deleteProperty(state.byLetter, action.payload.letterId);
    },
    allRefinesReset: () => initialState,
    refineFailureSimulated: (state, action: PayloadAction<boolean>) => {
      state.failNextRequest = action.payload;
    },
  },
});

export const {
  refineStarted,
  refineSucceeded,
  refineFailed,
  refineCleared,
  allRefinesReset,
  refineFailureSimulated,
} = refineSlice.actions;

export const selectRefine = (state: RootState, letterId: string | null): LetterRefine =>
  (letterId ? state.refine.byLetter[letterId] : undefined) ?? idle;
