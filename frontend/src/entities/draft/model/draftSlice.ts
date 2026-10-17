import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

import { type Draft, type DraftAttachment, type Recipient } from './types';

interface DraftState {
  byLetter: Record<string, Draft>;
}

const initialState: DraftState = {
  byLetter: {},
};

interface LetterPayload {
  letterId: string;
}

export const draftSlice = createSlice({
  name: 'draft',
  initialState,
  reducers: {
    /** Создаёт пустой черновик для письма, если его ещё нет. */
    draftEnsured: (state, action: PayloadAction<LetterPayload & { to: Recipient[] }>) => {
      const { letterId, to } = action.payload;
      state.byLetter[letterId] ??= {
        letterId,
        to,
        text: '',
        attachment: null,
        saveState: 'idle',
        savedAt: null,
      };
    },
    draftTextChanged: (state, action: PayloadAction<LetterPayload & { text: string }>) => {
      const draft = state.byLetter[action.payload.letterId];
      if (draft) {
        draft.text = action.payload.text;
        draft.saveState = 'saving';
      }
    },
    draftAttachmentSet: (
      state,
      action: PayloadAction<LetterPayload & { attachment: DraftAttachment }>,
    ) => {
      const draft = state.byLetter[action.payload.letterId];
      if (draft) {
        draft.attachment = action.payload.attachment;
        draft.saveState = 'saving';
      }
    },
    draftAttachmentRemoved: (state, action: PayloadAction<LetterPayload>) => {
      const draft = state.byLetter[action.payload.letterId];
      if (draft) {
        draft.attachment = null;
        draft.saveState = 'saving';
      }
    },
    draftRecipientRemoved: (state, action: PayloadAction<LetterPayload & { email: string }>) => {
      const draft = state.byLetter[action.payload.letterId];
      if (draft) {
        draft.to = draft.to.filter((recipient) => recipient.email !== action.payload.email);
        draft.saveState = 'saving';
      }
    },
    draftSaved: (state, action: PayloadAction<LetterPayload & { time: string }>) => {
      const draft = state.byLetter[action.payload.letterId];
      if (draft) {
        draft.saveState = 'saved';
        draft.savedAt = action.payload.time;
      }
    },
    /** Удаление черновика выполняет пользователь — AI черновики не удаляет. */
    draftDiscarded: (state, action: PayloadAction<LetterPayload>) => {
      Reflect.deleteProperty(state.byLetter, action.payload.letterId);
    },
    draftsReset: () => initialState,
  },
  selectors: {
    selectDrafts: (state) => state.byLetter,
  },
});

export const {
  draftEnsured,
  draftTextChanged,
  draftAttachmentSet,
  draftAttachmentRemoved,
  draftRecipientRemoved,
  draftSaved,
  draftDiscarded,
  draftsReset,
} = draftSlice.actions;

export const { selectDrafts } = draftSlice.selectors;

export const selectDraft = (state: RootState, letterId: string | null): Draft | undefined =>
  letterId ? state.draft.byLetter[letterId] : undefined;
