import { createAsyncThunk } from '@reduxjs/toolkit';

import { draftTextChanged, selectDraft } from '@/entities/draft';
import { delay } from '@/shared/lib/time';

import { refineCleared, refineFailed, refineStarted, refineSucceeded } from './refineSlice';
import { applyRefinement } from '../lib/applyRefinement';

interface RefineReplyArgs {
  letterId: string;
  query: string;
  instant?: boolean;
}

/** Точечное уточнение готового ответа («короче», «уточни срок»). */
export const refineReply = createAsyncThunk<undefined, RefineReplyArgs, { state: RootState }>(
  'refine/run',
  async ({ letterId, query, instant = false }, { dispatch, getState }) => {
    dispatch(refineStarted({ letterId, query }));
    if (!instant) {
      await delay(1300);
    }

    if (getState().refine.failNextRequest) {
      dispatch(refineFailed({ letterId }));
      return;
    }

    const text = selectDraft(getState(), letterId)?.text ?? '';
    const result = applyRefinement(text, query);
    if (result.changed) {
      dispatch(draftTextChanged({ letterId, text: result.text }));
    }
    dispatch(
      refineSucceeded({
        letterId,
        query,
        previousText: result.changed ? text : null,
        changed: result.changed,
        resultTitle: result.title,
        resultDescription: result.description,
      }),
    );
  },
  {
    condition: ({ letterId, query }, { getState }) =>
      Boolean(query.trim()) && getState().refine.byLetter[letterId]?.status !== 'loading',
  },
);

/** Отменяет только последнее AI-изменение. */
export const undoRefine = createAsyncThunk<undefined, { letterId: string }, { state: RootState }>(
  'refine/undo',
  ({ letterId }, { dispatch, getState }) => {
    const previousText = getState().refine.byLetter[letterId]?.previousText;
    if (previousText !== null && previousText !== undefined) {
      dispatch(draftTextChanged({ letterId, text: previousText }));
    }
    dispatch(refineCleared({ letterId }));
  },
);
