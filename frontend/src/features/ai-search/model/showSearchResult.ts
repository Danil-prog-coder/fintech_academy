import { createAsyncThunk } from '@reduxjs/toolkit';

import { searchRestored } from './aiSearchSlice';
import { type SearchRequest } from './types';
import { aiSearchApi } from '../api/aiSearchApi';
import { runMockSearch } from '../lib/runMockSearch';

/** Открывает панель сразу с готовым результатом (для навигатора по экранам). */
export const showSearchResult = createAsyncThunk<
  undefined,
  Omit<SearchRequest, 'nonce'>,
  { dispatch: AppDispatch }
>('aiSearch/showResult', async (args, { dispatch }) => {
  const request: SearchRequest = { ...args, nonce: -Date.now() };
  await dispatch(aiSearchApi.util.upsertQueryData('aiSearch', request, runMockSearch(request)));
  dispatch(searchRestored({ open: true, request, caveatAccepted: false }));
});
